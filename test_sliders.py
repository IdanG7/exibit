import tkinter as tk
import unittest

from exhibit import click_scale


class SliderTests(unittest.TestCase):
    def test_click_and_drag_jump_to_pointer_and_clamp_at_ends(self):
        root = tk.Tk()
        root.geometry('400x60')
        self.addCleanup(root.destroy)
        value = tk.DoubleVar(value=0)
        slider = click_scale(root, from_=0, to=30, variable=value)
        slider.place(x=0, y=0, width=400, height=30)
        root.update()
        slider.event_generate('<Button-1>', x=300, y=15)
        self.assertGreater(value.get(), 21)
        self.assertLess(value.get(), 24)
        slider.event_generate('<B1-Motion>', x=80, y=15)
        self.assertGreater(value.get(), 4)
        self.assertLess(value.get(), 7)
        slider.event_generate('<B1-Motion>', x=-20, y=15)
        self.assertEqual(value.get(), 0)
        slider.event_generate('<B1-Motion>', x=450, y=15)
        self.assertEqual(value.get(), 30)
        slider.event_generate('<ButtonRelease-1>', x=450, y=15)
        self.assertEqual(value.get(), 30)

    def test_disabled_slider_does_not_change(self):
        root = tk.Tk()
        root.geometry('400x60')
        self.addCleanup(root.destroy)
        value = tk.DoubleVar(value=.5)
        slider = click_scale(root, from_=0, to=1, variable=value, state='disabled')
        slider.place(x=0, y=0, width=400, height=30)
        root.update()
        slider.event_generate('<Button-1>', x=300, y=15)
        self.assertEqual(value.get(), .5)


if __name__ == '__main__':
    unittest.main()
