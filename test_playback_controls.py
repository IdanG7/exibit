import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

from exhibit import Engine, validate_config, load_playlist
import test_live_routing as routing_tests


class PlaybackControlTests(unittest.TestCase):
    def make_player(self, gap=0, paused=False):
        engine = Engine(dict(volume=1, echo_amount=0, loop_delay_seconds=gap,
                             paused_speakers=['A'] if paused else []))
        engine.epoch = 100
        source = np.repeat(np.array([.1, .2, .3], dtype='float32')[:, None], 2, axis=1)
        callback = engine._playback(source, 2, speaker='A')
        timing = SimpleNamespace(currentTime=0, outputBufferDacTime=0)

        def render(frames):
            result = np.empty((frames, 2), dtype='float32')
            with patch('exhibit.time.monotonic', return_value=100):
                callback(result, frames, timing, False)
            self.assertIsNone(engine.error)
            return result[:, 0]

        return engine, render

    def test_gap_is_silent_across_blocks_and_repeats(self):
        engine, render = self.make_player(gap=2/48000)
        actual = np.concatenate([render(4), render(3), render(5)])
        np.testing.assert_allclose(actual, [.1, .2, .3, 0, 0, .1, .2, .3, 0, 0, .1, .2])

    def test_pause_keeps_playback_position(self):
        engine, render = self.make_player()
        np.testing.assert_allclose(render(2), [.1, .2])
        engine.config['paused_speakers'] = ['A']
        np.testing.assert_array_equal(render(20), np.zeros(20))
        engine.config['paused_speakers'] = []
        np.testing.assert_allclose(render(3), [.3, .1, .2])

    def test_pausing_during_gap_freezes_remaining_delay(self):
        engine, render = self.make_player(gap=4/48000)
        render(5)
        engine.config['paused_speakers'] = ['A']
        render(100)
        engine.config['paused_speakers'] = []
        np.testing.assert_allclose(render(4), [0, 0, .1, .2])

    def test_live_delay_can_be_shortened_or_removed(self):
        engine, render = self.make_player(gap=10/48000)
        render(5)
        engine.config['loop_delay_seconds'] = 0
        np.testing.assert_allclose(render(4), [.1, .2, .3, .1])

    def test_initially_paused_starts_from_beginning_on_resume(self):
        engine, render = self.make_player(paused=True)
        np.testing.assert_array_equal(render(10), np.zeros(10))
        engine.config['paused_speakers'] = []
        np.testing.assert_allclose(render(3), [.1, .2, .3])

    def test_start_with_all_outputs_off_opens_only_microphone(self):
        config = dict(microphone='mic', speakers=[], files=[], button_vk=13)
        validate_config(config)
        self.assertEqual(load_playlist([], separate=True), [])
        with patch('exhibit.resolve', return_value=(0, dict(default_samplerate=48000))), \
                patch('exhibit.sd.check_input_settings'), patch('exhibit.Recorder') as recorder, \
                patch('exhibit.sd.InputStream') as microphone, patch('exhibit.sd.OutputStream') as output:
            engine = Engine(config)
            engine.start()
            try:
                self.assertEqual(engine.streams, [microphone.return_value])
                output.assert_not_called()
                recorder.return_value.close.assert_not_called()
            finally:
                engine.stop()


class AllOffRoutingTests(unittest.TestCase):
    setUp = routing_tests.LiveRoutingTests.setUp
    def test_all_off_and_back_on_does_not_restart_microphone(self):
        self.engine.reconfigure(dict(self.config, speakers=[], files=[]), [])
        self.assertEqual(self.engine.routes, {})
        self.assertEqual(self.engine.streams, [self.mic])
        self.assertEqual(self.engine.output_heartbeats, [])
        self.recorder.close.assert_not_called()
        self.engine.reconfigure(dict(self.config, speakers=['A'], files=self.files[:1]), self.tracks[:1])
        self.assertEqual(list(self.engine.routes), ['A'])
        self.mic.abort.assert_not_called()
        self.recorder.close.assert_not_called()


if __name__ == '__main__':
    unittest.main()
