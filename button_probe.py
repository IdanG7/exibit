"""Short keyboard-button diagnostic; logs key codes and hold lengths only."""
import ctypes
import json
import time
from exhibit import ROOT

deadline = time.monotonic() + 40
held = {}
events = []
print('Listening for button holds for 40 seconds…', flush=True)
while time.monotonic() < deadline:
    now = time.monotonic()
    for key in range(8, 255):
        if key in (16, 17, 18):
            continue
        down = bool(ctypes.windll.user32.GetAsyncKeyState(key) & 0x8000)
        if down and key not in held:
            held[key] = now
        elif not down and key in held:
            seconds = round(now - held.pop(key), 3)
            if seconds >= 0.3:
                event = {'key_code': key, 'held_seconds': seconds}
                events.append(event)
                print(json.dumps(event), flush=True)
    time.sleep(.01)
(ROOT / 'logs' / 'button-probe.json').write_text(json.dumps(events, indent=2))
print('Done.', flush=True)
