from pathlib import Path
import tempfile
import unittest

import numpy as np
import soundfile as sf

from exhibit import Recorder


class RecordingDelayTests(unittest.TestCase):
    def test_half_second_is_removed_even_across_callback_boundaries(self):
        with tempfile.TemporaryDirectory() as folder:
            recorder = Recorder(folder, 48000, start_delay_seconds=.5)
            recorder.press()
            recorder.callback(np.ones((16000, 1), dtype='float32'), 16000, None, False)
            data = np.concatenate([np.ones((8000, 1)), np.full((4000, 1), .25)]).astype('float32')
            recorder.callback(data, len(data), None, False)
            recorder.release()
            recorder.close()
            audio, rate = sf.read(recorder.last_path)
            self.assertEqual(rate, 48000)
            self.assertEqual(len(audio), 4000)
            np.testing.assert_allclose(audio, .25)

    def test_short_press_saves_nothing_and_next_press_gets_fresh_delay(self):
        with tempfile.TemporaryDirectory() as folder:
            recorder = Recorder(folder, 48000, start_delay_seconds=.5)
            recorder.press()
            recorder.callback(np.ones((12000, 1), dtype='float32'), 12000, None, False)
            recorder.release()
            recorder.press()
            recorder.callback(np.ones((24000, 1), dtype='float32'), 24000, None, False)
            recorder.callback(np.full((480, 1), .125, dtype='float32'), 480, None, False)
            recorder.close()
            files = list(Path(folder).glob('*.wav'))
            self.assertEqual(len(files), 1)
            audio, _ = sf.read(files[0])
            np.testing.assert_allclose(audio, .125)
            self.assertEqual(len(audio), 480)
            self.assertFalse(list(Path(folder).glob('*.partial')))


if __name__ == '__main__':
    unittest.main()
