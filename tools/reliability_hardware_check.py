"""60-second silent rehearsal of configured devices; does not record visitor audio."""
import json
import time
from unittest.mock import patch

from app.exhibit import CONFIG, Engine, ROOT, validate_config

config = validate_config(json.loads(CONFIG.read_text()))
config['volume'] = 0
for settings in config.get('speaker_settings', {}).values():
    settings['volume'] = 0
engine = Engine(config)
started = time.monotonic()
try:
    engine.start()
    with patch('app.exhibit.ctypes.windll.user32.GetAsyncKeyState', return_value=0):
        while time.monotonic() - started < 60:
            engine.tick()
            time.sleep(.01)
    report = dict(seconds=round(time.monotonic() - started, 2),
                  microphone=config['microphone'], speakers=config['speakers'],
                  output_buffer_interruptions=engine.output_warnings,
                  recordings_created=engine.recorder.saved,
                  input_callback_age_seconds=round(time.monotonic() - engine.recorder.last_callback, 3),
                  result='passed')
finally:
    engine.stop()
(ROOT / 'logs').mkdir(exist_ok=True)
(ROOT / 'logs' / 'hardware-reliability.json').write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
