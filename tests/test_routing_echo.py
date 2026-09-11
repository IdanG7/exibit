import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

from app.exhibit import Engine, LiveEcho, apply_echo, validate_config


class RoutingEchoTests(unittest.TestCase):
    def test_live_echo_matches_loop_echo_and_preserves_source(self):
        audio = np.random.default_rng(4).uniform(-1, 1, (301, 2)).astype('float32')
        original = audio.copy()
        echo = LiveEcho(audio, .4, 75, rate=1000)
        expected = apply_echo(audio, .4, 75, rate=1000)
        actual = echo.render(290, 75, .4, 75)
        np.testing.assert_allclose(actual, expected[(np.arange(75) + 290) % 301], atol=1e-7)
        np.testing.assert_array_equal(audio, original)

    def test_live_changes_crossfade_and_keep_position(self):
        audio = np.random.default_rng(5).uniform(-1, 1, (301, 2)).astype('float32')
        echo = LiveEcho(audio, 0, 50, rate=1000)
        wet = apply_echo(audio, .5, 70, rate=1000)
        first = echo.render(100, 25, .5, 70)
        blend = np.arange(1, 26)[:, None] / 50
        np.testing.assert_allclose(first, audio[100:125] * (1-blend) + wet[100:125] * blend, atol=1e-7)
        echo.render(125, 25, .5, 70)
        np.testing.assert_allclose(echo.render(150, 10, .5, 70), wet[150:160], atol=1e-7)
        echo.render(160, 50, 0, 70)
        np.testing.assert_array_equal(echo.render(210, 10, 0, 70), audio[210:220])

    def test_playback_callback_reads_echo_updates_without_restarting(self):
        audio = np.random.default_rng(6).uniform(-.5, .5, (8000, 2)).astype('float32')
        engine = Engine(dict(volume=1, echo_amount=0, echo_delay_ms=50))
        engine.epoch = 100
        callback = engine._playback(audio, 2)
        timing = SimpleNamespace(currentTime=0, outputBufferDacTime=0)
        with patch('app.exhibit.time.monotonic', return_value=100):
            first = np.empty((100, 2), dtype='float32')
            callback(first, 100, timing, False)
            np.testing.assert_array_equal(first, audio[:100])
            engine.config.update(echo_amount=.5, echo_delay_ms=60)
            transition = np.empty((2400, 2), dtype='float32')
            callback(transition, 2400, timing, False)
            following = np.empty((100, 2), dtype='float32')
            callback(following, 100, timing, False)
            np.testing.assert_allclose(following, apply_echo(audio, .5, 60)[2500:2600], atol=1e-7)
        self.assertIsNone(engine.error)

    def test_echo_has_three_decaying_repeats(self):
        audio = np.zeros((20, 2), dtype='float32')
        audio[0] = 1
        result = apply_echo(audio, .5, 200, rate=10)
        expected = np.zeros_like(audio)
        for index, gain in [(0, 1), (2, .5), (4, .25), (6, .125)]:
            expected[index] = gain / 1.875
        np.testing.assert_allclose(result, expected)
        self.assertEqual(audio[0, 0], 1)  # Source remains intact.

    def test_echo_wraps_at_end_and_never_extends_loop(self):
        audio = np.zeros((20, 2), dtype='float32')
        audio[19] = 1
        result = apply_echo(audio, .5, 200, rate=10)
        self.assertEqual(result.shape, audio.shape)
        self.assertAlmostEqual(float(result[1, 0]), .5 / 1.875)
        np.testing.assert_array_equal(apply_echo(audio, 0), audio)

    def test_echo_headroom_at_maximum_amount(self):
        result = apply_echo(np.ones((5, 2), dtype='float32'), .75, 1500)
        self.assertLessEqual(float(result.max()), 1)

    def test_three_outputs_receive_only_their_assigned_loop(self):
        with tempfile.TemporaryDirectory() as directory:
            files = [Path(directory) / f'{n}.wav' for n in range(3)]
            for path in files:
                path.touch()
            config = dict(microphone='mic', speakers=['one', 'two', 'three'],
                          files=list(map(str, files)), button_vk=13, volume=1, echo_amount=0)
            tracks = [np.repeat((np.arange(length, dtype='float32') / 20 + offset)[:, None], 2, axis=1)
                      for length, offset in [(3, .1), (5, .3), (7, .5)]]
            callbacks = []

            def output(**kwargs):
                callbacks.append(kwargs['callback'])
                return Mock()

            with patch('app.exhibit.resolve', return_value=(0, dict(default_samplerate=48000, max_output_channels=2))), \
                    patch('app.exhibit.load_playlist', return_value=tracks), patch('app.exhibit.Recorder'), \
                    patch('app.exhibit.sd.check_input_settings'), patch('app.exhibit.sd.check_output_settings'), \
                    patch('app.exhibit.sd.InputStream'), patch('app.exhibit.sd.OutputStream', side_effect=output):
                engine = Engine(config)
                engine.start()
                try:
                    self.assertEqual(len(callbacks), 3)
                    timing = SimpleNamespace(currentTime=0, outputBufferDacTime=0)
                    with patch('app.exhibit.time.monotonic', return_value=engine.epoch):
                        for track, callback in zip(tracks, callbacks):
                            for start in (0, 10):
                                data = np.empty((10, 2), dtype='float32')
                                callback(data, 10, timing, False)
                                np.testing.assert_array_equal(data, track[(np.arange(10) + start) % len(track)])
                finally:
                    engine.stop()

    def test_unpaired_files_and_invalid_echo_are_rejected(self):
        config = dict(microphone='mic', speakers=['one'], files=['a', 'b'], button_vk=13)
        with self.assertRaisesRegex(ValueError, 'exactly one'):
            validate_config(config)
        config['files'] = ['a']
        config['echo_amount'] = float('nan')
        with self.assertRaisesRegex(ValueError, 'echo_amount'):
            validate_config(config)


if __name__ == '__main__':
    unittest.main()
