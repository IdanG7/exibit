from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

from exhibit import Engine, gui, speaker_values, validate_speaker_settings


class SpeakerSettingsTests(unittest.TestCase):
    def test_loop_delay_is_independent_and_updates_live(self):
        config = dict(volume=1, echo_amount=0, speaker_settings={
            'A': dict(loop_delay_seconds=2/48000), 'B': dict(loop_delay_seconds=0)})
        engine = Engine(config)
        engine.epoch = 100
        source = np.full((2, 2), .5, dtype='float32')
        callbacks = {name: engine._playback(source, 2, speaker=name) for name in ('A', 'B')}
        timing = SimpleNamespace(currentTime=0, outputBufferDacTime=0)
        def render(name):
            block = np.empty((4, 2), dtype='float32')
            with patch('exhibit.time.monotonic', return_value=100):
                callbacks[name](block, 4, timing, False)
            self.assertIsNone(engine.error)
            return block[:, 0]
        np.testing.assert_array_equal(render('A'), [.5, .5, 0, 0])
        np.testing.assert_array_equal(render('B'), [.5, .5, .5, .5])
        config['speaker_settings']['A']['loop_delay_seconds'] = 0
        np.testing.assert_array_equal(render('A'), [.5, .5, .5, .5])
        np.testing.assert_array_equal(render('B'), [.5, .5, .5, .5])

    def test_legacy_settings_are_preserved_as_defaults(self):
        config = dict(volume=.2, echo_amount=.1, echo_delay_ms=200,
                      speaker_settings={'B': {'volume': .8}})
        self.assertEqual(speaker_values(config, 'A'), dict(volume=.2, echo_amount=.1, echo_delay_ms=200, loop_delay_seconds=0))
        self.assertEqual(speaker_values(config, 'B')['volume'], .8)
        with self.assertRaises(ValueError):
            validate_speaker_settings({'A': {'volume': float('nan')}})

    def test_each_output_uses_its_own_live_volume_and_echo(self):
        config = dict(volume=1, echo_amount=0, speaker_settings={
            'A': dict(volume=.2, echo_amount=0, echo_delay_ms=50),
            'B': dict(volume=.8, echo_amount=.5, echo_delay_ms=100)})
        engine = Engine(config)
        engine.epoch = 100
        source = np.ones((10000, 2), dtype='float32')
        first = engine._playback(source, 2, speaker='A')
        second = engine._playback(source, 2, speaker='B')
        timing = SimpleNamespace(outputBufferDacTime=0, currentTime=0)
        with patch('exhibit.time.monotonic', return_value=100):
            for callback, expected in [(first, .2), (second, .8)]:
                block = np.empty((480, 2), dtype='float32')
                callback(block, 480, timing, False)
                np.testing.assert_allclose(block, expected, atol=1e-7)
            config['speaker_settings']['A'] = dict(volume=.4, echo_amount=.3, echo_delay_ms=70)
            for callback, expected in [(first, .4), (second, .8)]:
                block = np.empty((3000, 2), dtype='float32')
                callback(block, 3000, timing, False)
                np.testing.assert_allclose(block, expected, atol=1e-7)
        self.assertEqual(speaker_values(config, 'B')['echo_amount'], .5)

    def test_selector_keeps_settings_separate_and_shared_sliders(self):
        import tkinter as tk

        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / 'audio').mkdir()
            files = [str(folder / 'audio' / f'{i}.wav') for i in range(2)]
            for file in files:
                Path(file).touch()
            config = dict(microphone='mic', speakers=['A', 'B'], files=files, button_vk=13,
                          volume=.5, echo_amount=.35, speaker_settings={
                              'A': dict(volume=.2, echo_amount=.1, echo_delay_ms=100),
                              'B': dict(volume=.8, echo_amount=.6, echo_delay_ms=500)})
            root = tk.Tk()
            root.withdraw()
            failures = []
            observed = []

            def descendants(widget):
                return [child for w in widget.winfo_children() for child in [w] + descendants(w)]

            def exercise():
                try:
                    widgets = descendants(root)
                    named = {w.winfo_name(): w for w in widgets}
                    selector, volume, echo = [named[n] for n in ('speaker_selector', 'speaker_volume', 'speaker_echo')]
                    self.assertEqual(sum(w.winfo_class() == 'TScale' for w in widgets), 4)
                    self.assertAlmostEqual(volume.get(), .2)
                    selector.current(1)
                    selector.event_generate('<<ComboboxSelected>>')
                    self.assertAlmostEqual(volume.get(), .8)
                    volume.set(.4)
                    echo.set(.3)
                    named['echo_delay'].set(700)
                    named['speaker_loop_delay'].set(4.5)
                    selector.current(0)
                    selector.event_generate('<<ComboboxSelected>>')
                    self.assertAlmostEqual(volume.get(), .2)
                    self.assertAlmostEqual(named['speaker_loop_delay'].get(), 0)
                    self.assertAlmostEqual(echo.get(), .1)
                    self.assertEqual(named['echo_delay'].get(), 100)
                    selector.current(2)
                    selector.event_generate('<<ComboboxSelected>>')
                    self.assertTrue(volume.instate(['disabled']))
                    selector.current(0)
                    selector.event_generate('<<ComboboxSelected>>')
                    next(w for w in widgets if w.winfo_class() == 'TButton' and w.cget('text') == 'Start exhibit').invoke()
                except Exception as exc:
                    failures.append(exc)

            def make_session(settings):
                observed.append(settings)
                return SimpleNamespace(config=settings, tick=Mock(), stop=Mock(), status='Playing')

            def finish():
                for callback in root.tk.call('after', 'info'):
                    root.after_cancel(callback)
                root.destroy()

            root.after(20, exercise)
            root.after(120, finish)
            with patch('tkinter.Tk', return_value=root), patch('exhibit.ROOT', folder), \
                    patch('exhibit.load_gui_config', return_value=config), patch('exhibit.save_config'), \
                    patch('exhibit.sd._initialize'), patch('exhibit.sd._terminate'), \
                    patch('exhibit.devices', side_effect=lambda kind: [(0, {'name': 'mic' if kind == 'input' else 'A'})]), \
                    patch('exhibit.Session', side_effect=make_session):
                gui()
            if failures:
                raise failures[0]
            self.assertEqual(observed[0]['speaker_settings']['A']['volume'], .2)
            self.assertEqual(observed[0]['speaker_settings']['B']['volume'], .4)
            self.assertEqual(observed[0]['speaker_settings']['B']['echo_amount'], .3)
            self.assertEqual(observed[0]['speaker_settings']['B']['echo_delay_ms'], 700)
            self.assertEqual(observed[0]['speaker_settings']['B']['loop_delay_seconds'], 4.5)
            self.assertEqual(observed[0]['volume'], .5)


if __name__ == '__main__':
    unittest.main()
