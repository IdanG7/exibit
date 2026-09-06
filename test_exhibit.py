import tempfile
import subprocess
import unittest
from unittest.mock import patch
from datetime import datetime
from pathlib import Path

import numpy as np
import soundfile as sf

from exhibit import Recorder, load_playlist, loop_block


class ExhibitTests(unittest.TestCase):
    def test_readable_names_continue_after_restart_and_preserve_existing(self):
        with tempfile.TemporaryDirectory() as folder:
            existing = Path(folder) / '7 - (09-00-00).wav'
            sf.write(existing, np.full(120, .25), 48000)
            original = existing.read_bytes()
            # A prior interrupted capture must also reserve its sequence number.
            partial = Path(folder) / '8 - (09-01-00).partial'
            partial.write_bytes(b'preserve unfinished recording')
            for expected in (9, 10):
                recorder = Recorder(folder, 48000)
                with patch('exhibit.datetime') as clock:
                    clock.now.return_value = datetime(2026, 9, 5, 15, 23, 10)
                    recorder.press()
                recorder.callback(np.zeros((120, 1), dtype='float32'), 120, None, False)
                recorder.close()
                self.assertIsNone(recorder.error)
                self.assertEqual(recorder.last_path.name, f'{expected} - (15-23-10).wav')
            self.assertEqual(existing.read_bytes(), original)
            self.assertEqual(partial.read_bytes(), b'preserve unfinished recording')

    def test_mp4_audio_decoding(self):
        import imageio_ffmpeg
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'source.wav'
            target = Path(folder) / 'audio.mp4'
            samples = .1 * np.sin(2 * np.pi * 440 * np.arange(4800) / 48000)
            sf.write(source, samples, 48000)
            subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-v', 'error', '-i', str(source),
                            '-c:a', 'aac', str(target)], check=True, capture_output=True,
                           creationflags=subprocess.CREATE_NO_WINDOW)
            decoded = load_playlist([target])
            self.assertEqual(decoded.shape[1], 2)
            self.assertGreaterEqual(len(decoded), len(samples))
            self.assertGreater(float(np.abs(decoded).max()), .05)

    def test_playlist_order_resampling_and_wrap(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = [Path(folder) / f'{i}.wav' for i in range(3)]
            for i, path in enumerate(paths):
                sf.write(path, np.full(2400, (i + 1) / 10), 24000, subtype='FLOAT')
            audio = load_playlist(paths)
            self.assertEqual(audio.shape, (14400, 2))
            np.testing.assert_allclose(audio[[2000, 6800, 11600], 0], [.1, .2, .3], atol=.001)
            block, position = loop_block(audio, len(audio) - 2, len(audio) + 5)
            np.testing.assert_array_equal(block[:2], audio[-2:])
            np.testing.assert_array_equal(block[2:7], audio[:5])
            self.assertEqual(position, 3)

    def test_repeated_holds_only_capture_held_audio(self):
        with tempfile.TemporaryDirectory() as folder:
            recorder = Recorder(folder, 48000)
            data = np.full((480, 1), .25, dtype='float32')
            recorder.callback(data, 480, None, False)
            for _ in range(3):
                recorder.press()
                recorder.press()  # key repeats do not create additional files
                recorder.callback(data, 480, None, False)
                recorder.callback(data, 480, None, False)
                recorder.release()
                recorder.release()
                recorder.callback(data, 480, None, False)
            recorder.close()
            self.assertIsNone(recorder.error)
            files = list(Path(folder).glob('*.wav'))
            self.assertEqual(len(files), 3)
            self.assertFalse(list(Path(folder).glob('*.partial')))
            for file in files:
                samples, rate = sf.read(file)
                self.assertEqual(rate, 48000)
                self.assertEqual(len(samples), 960)
                np.testing.assert_allclose(samples, .25)

    def test_stop_while_held_and_duration_limit(self):
        with tempfile.TemporaryDirectory() as folder:
            recorder = Recorder(folder, 48000, max_seconds=.01)
            recorder.press()
            recorder.callback(np.ones((960, 1), dtype='float32'), 960, None, False)
            self.assertFalse(recorder.active)
            recorder.release()
            recorder.press()
            recorder.callback(np.zeros((120, 1), dtype='float32'), 120, None, False)
            recorder.close()
            self.assertEqual(sorted(sf.info(p).frames for p in Path(folder).glob('*.wav')), [120, 480])

    def test_recording_overflow_is_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            recorder = Recorder(folder, 48000)
            recorder.press()
            recorder.callback(np.zeros((480, 1), dtype='float32'), 480, None, 'input overflow')
            with self.assertRaisesRegex(RuntimeError, 'overflow'):
                recorder.close()
            self.assertIn('overflow', recorder.error)


if __name__ == '__main__':
    unittest.main()
