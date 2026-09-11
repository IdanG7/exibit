import tempfile
from pathlib import Path
import unittest

import numpy as np
import soundfile as sf

from app.exhibit import load_playlist, normalize_playback


class PlaybackLevelTests(unittest.TestCase):
    def test_quiet_audio_is_boosted_with_stereo_balance_preserved(self):
        source = np.array([[.03, .015], [-.03, -.015]], dtype='float32')
        result = normalize_playback(source)
        self.assertAlmostEqual(float(np.abs(result).max()), 10 ** (-1 / 20), places=6)
        np.testing.assert_allclose(result[:, 1], result[:, 0] / 2)
        np.testing.assert_allclose(source[0], [.03, .015])

    def test_silence_stays_silent_and_very_quiet_noise_has_bounded_gain(self):
        silence = np.zeros((100, 2), dtype='float32')
        np.testing.assert_array_equal(normalize_playback(silence), silence)
        quiet = np.full((100, 2), 1e-8, dtype='float32')
        self.assertLess(float(normalize_playback(quiet).max()), 3.2e-7)

    def test_loud_audio_gets_headroom(self):
        result = normalize_playback(np.array([[1.2, -1.2]], dtype='float32'))
        self.assertLess(float(np.abs(result).max()), .9)

    def test_loading_normalizes_each_track_without_editing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory) / f'{i}.wav' for i in range(2)]
            for path, level in zip(paths, [.03, .06]):
                sf.write(path, np.full((100, 2), level), 48000, subtype='FLOAT')
            originals = [path.read_bytes() for path in paths]
            tracks = load_playlist(paths, separate=True, normalize=True)
            for track in tracks:
                self.assertAlmostEqual(float(track.max()), 10 ** (-1 / 20), places=6)
            self.assertEqual([path.read_bytes() for path in paths], originals)


if __name__ == '__main__':
    unittest.main()
