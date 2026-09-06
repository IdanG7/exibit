import json
from pathlib import Path
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
import soundfile as sf

from exhibit import (DeviceUnavailable, Engine, Recorder, Session, load_gui_config,
                     load_playlist, save_config, validate_config, gui)


class ReliabilityTests(unittest.TestCase):
    def test_window_recovers_when_tick_and_stop_both_fail(self):
        import tkinter as tk

        with tempfile.TemporaryDirectory() as directory:
            root_path = Path(directory)
            (root_path / 'audio').mkdir()
            track = root_path / 'audio' / 'track.wav'
            track.touch()
            config = dict(microphone='mic', speakers=['speaker'], files=[str(track)], button_vk=13, volume=.5)
            broken, healthy = Mock(), Mock()
            broken.config, healthy.config = config.copy(), config.copy()
            broken.status, healthy.status = 'First start', 'Healthy session'
            broken.tick.side_effect = [None, RuntimeError('capture failed')]
            broken.stop.side_effect = RuntimeError('cleanup failed')
            healthy.tick.return_value = None
            window = tk.Tk()
            window.withdraw()
            outcomes = []

            def children(widget):
                result = []
                for child in widget.winfo_children():
                    result.append(child)
                    result.extend(children(child))
                return result

            def start():
                next(w for w in children(window) if w.winfo_class() == 'TButton'
                     and w.cget('text') == 'Start exhibit').invoke()

            def restart():
                outcomes.append(any('Exhibit stopped: capture failed' in str(w.cget('text'))
                                    for w in children(window) if w.winfo_class() == 'TLabel'))
                start()

            window.after(20, start)
            window.after(150, restart)
            def finish_window_test():
                for callback in window.tk.call('after', 'info'):
                    window.after_cancel(callback)
                window.destroy()

            window.after(300, finish_window_test)
            with patch('tkinter.Tk', return_value=window), patch('exhibit.ROOT', root_path), \
                    patch('exhibit.load_gui_config', return_value=config), patch('exhibit.save_config'), \
                    patch('exhibit.sd._terminate'), patch('exhibit.sd._initialize'), \
                    patch('exhibit.devices', side_effect=lambda kind: [(0, {'name': 'mic' if kind == 'input' else 'speaker'})]), \
                    patch('exhibit.Session', side_effect=[broken, healthy]), self.assertLogs(level='ERROR'):
                gui()
            self.assertEqual(outcomes, [True])
            self.assertGreater(healthy.tick.call_count, 1)

    def test_corrupt_settings_open_setup_without_deleting_original(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            for content in ('{unfinished', '[]', '{"files": null}', '{"speakers": 123}'):
                path.write_text(content)
                with self.assertLogs(level='ERROR'):
                    self.assertEqual(load_gui_config(path), {})
                self.assertEqual(path.read_text(), content)

    def test_bad_button_and_volume_are_reset_in_setup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            path.write_text('{"button_vk": "Enter", "volume": NaN}')
            self.assertEqual(load_gui_config(path), {'volume': .5})

    def test_failed_config_save_preserves_working_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            track = Path(directory) / 'track.wav'
            track.touch()
            config = dict(microphone='mic', speakers=['speaker'], files=[str(track)], button_vk=13)
            path.write_text('{"previous": true}')
            with patch('exhibit.os.fsync', side_effect=OSError('disk full')):
                with self.assertRaises(OSError):
                    save_config(config, path)
            self.assertEqual(json.loads(path.read_text()), {'previous': True})

    def test_missing_file_and_invalid_binding_fail_before_audio_opens(self):
        with tempfile.TemporaryDirectory() as directory:
            config = dict(microphone='mic', speakers=['speaker'], files=[str(Path(directory) / 'missing.wav')], button_vk=13)
            with self.assertRaisesRegex(ValueError, 'missing'):
                validate_config(config)
            config['button_vk'] = 999
            with self.assertRaisesRegex(ValueError, 'button'):
                validate_config(config)

    def test_low_disk_blocks_recording_without_leaking_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('exhibit.shutil.disk_usage', return_value=SimpleNamespace(free=1)):
                with self.assertRaisesRegex(OSError, '64 MB'):
                    Recorder(directory, 48000)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_disk_full_during_write_is_reported_and_partial_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder = Recorder(directory, 48000)
            original_write = sf.SoundFile.write

            def fail_after_writing(output, data):
                original_write(output, data)
                raise OSError('disk full')

            with patch.object(sf.SoundFile, 'write', fail_after_writing), self.assertLogs(level='ERROR'):
                recorder.press()
                recorder.callback(np.zeros((480, 1), dtype='float32'), 480, None, False)
                with self.assertRaisesRegex(RuntimeError, 'disk full'):
                    recorder.close()
            self.assertFalse(recorder.worker.is_alive())
            partials = list(Path(directory).glob('*.partial'))
            self.assertEqual(len(partials), 1)
            self.assertEqual(sf.info(partials[0]).frames, 480)

    def test_500_visitors_have_unique_complete_recordings(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder = Recorder(directory, 48000)
            block = np.full((120, 1), .25, dtype='float32')
            for batch in range(5):
                for _ in range(100):
                    recorder.press()
                    recorder.callback(block, 120, None, False)
                    recorder.release()
                deadline = time.monotonic() + 10
                while recorder.saved < (batch + 1) * 100 and not recorder.error and time.monotonic() < deadline:
                    time.sleep(.005)
                self.assertEqual(recorder.saved, (batch + 1) * 100)
            recorder.close()
            self.assertFalse(recorder.worker.is_alive())
            files = list(Path(directory).glob('*.wav'))
            self.assertEqual(len(files), 500)
            self.assertTrue(all(sf.info(path).frames == 120 for path in files))
            self.assertEqual(len(list(Path(directory).glob('*.partial'))), 0)

    def test_closed_recorder_ignores_late_button_events(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder = Recorder(directory, 48000)
            recorder.close()
            recorder.close()
            recorder.press()
            recorder.callback(np.zeros((480, 1)), 480, None, False)
            self.assertFalse(recorder.active)
            self.assertTrue(recorder.queue.empty())

    def test_large_track_is_rejected_before_decoding(self):
        metadata = SimpleNamespace(frames=48000 * 60 * 60, samplerate=48000, channels=2)
        with patch('exhibit.sf.info', return_value=metadata), patch('exhibit.sf.read') as read:
            with self.assertRaisesRegex(ValueError, 'too large'):
                load_playlist(['large.wav'])
            read.assert_not_called()

    def test_speaker_glitch_does_not_stop_playback(self):
        engine = Engine({'volume': .5})
        engine.epoch = time.monotonic() - 1
        output = np.zeros((480, 2), dtype='float32')
        callback = engine._playback(np.ones((960, 2), dtype='float32'), 2)
        callback(output, 480, SimpleNamespace(outputBufferDacTime=0, currentTime=0), 'output underflow')
        self.assertIsNone(engine.error)
        self.assertEqual(engine.output_warnings, 1)
        np.testing.assert_allclose(output, .5, atol=1e-7)

    def test_callback_exception_outputs_silence_and_reports_problem(self):
        engine = Engine({'volume': .5})
        engine.epoch = time.monotonic() - 1
        output = np.ones((480, 2), dtype='float32')
        callback = engine._playback(np.ones((960, 2), dtype='float32'), 2)
        with patch('exhibit.loop_block', side_effect=RuntimeError('callback problem')):
            callback(output, 480, SimpleNamespace(outputBufferDacTime=0, currentTime=0), False)
        self.assertIn('callback problem', engine.error)
        self.assertFalse(output.any())

    def test_stream_close_still_runs_if_abort_fails(self):
        engine = Engine({})
        stream = Mock()
        stream.abort.side_effect = RuntimeError('disconnected')
        engine.streams = [stream]
        with self.assertLogs(level='ERROR'):
            engine.stop()
        stream.close.assert_called_once()

    @patch('exhibit.sd._initialize')
    @patch('exhibit.sd._terminate')
    def test_disconnect_retries_and_stop_cancels_retry(self, terminate, initialize):
        first, second = Mock(), Mock()
        first.start.side_effect = DeviceUnavailable('unplugged')
        first.recorder = None
        second.recorder = SimpleNamespace(saved=0, active=False)
        factory = Mock(side_effect=[first, second])
        session = Session({'speakers': ['speaker']}, factory)
        with self.assertLogs(level='WARNING'):
            session.tick()
        self.assertIsNone(session.engine)
        self.assertIn('Waiting', session.status)
        session.tick()
        self.assertEqual(factory.call_count, 1)
        session.retry_at = 0
        session.tick()
        self.assertIs(session.engine, second)
        self.assertIn('PLAYING', session.status)
        second.tick.side_effect = DeviceUnavailable('unplugged again')
        with self.assertLogs(level='WARNING'):
            session.tick()
        session.stop()
        session.retry_at = 0
        session.tick()
        self.assertEqual(factory.call_count, 2)

    @patch('exhibit.sd._initialize')
    @patch('exhibit.sd._terminate')
    def test_disk_error_does_not_restart_and_hide_recording_failure(self, terminate, initialize):
        engine = Mock()
        engine.recorder = SimpleNamespace(saved=0)
        engine.tick.side_effect = RuntimeError('disk full')
        session = Session({}, Mock(return_value=engine))
        with self.assertRaisesRegex(RuntimeError, 'disk full'):
            session.tick()
        self.assertFalse(session.running)
        self.assertIsNone(session.engine)
        engine.stop.assert_called_once()


if __name__ == '__main__':
    unittest.main()
