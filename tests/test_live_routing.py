import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

from app.exhibit import DeviceUnavailable, Engine, validate_config


class LiveRoutingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.files = [str(Path(self.temp.name) / f'{i}.wav') for i in range(3)]
        for name in self.files:
            Path(name).touch()
        self.config = dict(microphone='mic', speakers=['A', 'B'], files=self.files[:2],
                           button_vk=13, volume=1, echo_amount=0)
        self.tracks = [np.full((4800, 2), value, dtype='float32') for value in (.1, .2, .3)]
        self.addCleanup(patch.stopall)
        self.resolve = patch('app.exhibit.resolve', return_value=(0, dict(default_samplerate=48000, max_output_channels=2))).start()
        patch('app.exhibit.load_playlist', return_value=self.tracks[:2]).start()
        patch('app.exhibit.sd.check_input_settings').start()
        patch('app.exhibit.sd.check_output_settings').start()
        self.mic = patch('app.exhibit.sd.InputStream').start().return_value
        self.recorder = patch('app.exhibit.Recorder').start().return_value
        self.streams = []

        def output(**kwargs):
            stream = Mock()
            stream.callback = kwargs['callback']
            self.streams.append(stream)
            return stream

        self.output = patch('app.exhibit.sd.OutputStream', side_effect=output).start()
        self.engine = Engine(self.config)
        self.engine.start()
        self.addCleanup(self.engine.stop)

    def test_swap_files_without_reopening_outputs_or_microphone(self):
        self.engine.reconfigure(dict(self.config, files=self.files[:2][::-1]), self.tracks[:2][::-1])
        self.assertEqual(self.output.call_count, 2)
        self.recorder.close.assert_not_called()
        self.mic.abort.assert_not_called()
        timing = SimpleNamespace(outputBufferDacTime=0, currentTime=0)
        for stream, value in zip(self.streams, (.2, .1)):
            output = np.zeros((100, 2), dtype='float32')
            stream.callback(output, 100, timing, False)
            np.testing.assert_allclose(output, value)
        self.assertEqual(len(self.engine.output_heartbeats), 2)

    def test_add_and_remove_output_keeps_capture_running(self):
        old = self.streams[0]
        self.engine.reconfigure(dict(self.config, speakers=['C', 'B']), self.tracks[:2])
        self.assertEqual(set(self.engine.routes), {'B', 'C'})
        old.abort.assert_called_once()
        old.close.assert_called_once()
        self.recorder.close.assert_not_called()
        self.mic.abort.assert_not_called()
        self.assertIs(self.engine.streams[0], self.mic)
        self.assertEqual(len(self.engine.output_heartbeats), 2)

    def test_unavailable_speaker_preserves_old_routes_and_recording(self):
        before = dict(self.engine.routes)
        self.resolve.side_effect = DeviceUnavailable('Missing C')
        with self.assertRaises(DeviceUnavailable):
            self.engine.reconfigure(dict(self.config, speakers=['C', 'B']), self.tracks[:2])
        self.assertEqual(self.engine.routes, before)
        self.assertEqual(self.engine.config['speakers'], ['A', 'B'])
        self.mic.abort.assert_not_called()
        for stream in self.streams:
            stream.abort.assert_not_called()

    def test_partial_output_preparation_is_rolled_back(self):
        good = Mock()
        bad = Mock()
        bad.start.side_effect = RuntimeError('driver open failed')
        self.output.side_effect = [good, bad]
        before = dict(self.engine.routes)
        with self.assertRaisesRegex(RuntimeError, 'driver open failed'):
            self.engine.reconfigure(dict(self.config, speakers=['C', 'D']), self.tracks[:2])
        self.assertEqual(self.engine.routes, before)
        good.close.assert_called_once()
        bad.close.assert_called_once()
        self.assertEqual(len(self.engine.output_heartbeats), 2)
        self.recorder.close.assert_not_called()

    def test_duplicate_file_paths_and_duplicate_devices_are_rejected(self):
        same_path = str(Path(self.files[0]).parent) + '/./0.wav'
        with self.assertRaisesRegex(ValueError, 'file.*only once'):
            validate_config(dict(self.config, files=[self.files[0], same_path]))
        with self.assertRaisesRegex(ValueError, 'speaker.*only once'):
            self.engine.reconfigure(dict(self.config, speakers=['A', 'A']), self.tracks[:2])
        self.recorder.close.assert_not_called()


if __name__ == '__main__':
    unittest.main()
