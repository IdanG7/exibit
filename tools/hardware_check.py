"""Brief silent output / microphone check. Does not save microphone audio."""
import time
import numpy as np
import sounddevice as sd
from app.exhibit import resolve

mic_id, mic = resolve('Microphone (CMTECK)', 'input')
speaker_id, speaker = resolve('Speakers (USB2.0 Device)', 'output')
levels = []
statuses = []


def capture(data, frames, timing, status):
    levels.append(float(np.max(np.abs(data))))
    if status:
        statuses.append(str(status))


def silence(data, frames, timing, status):
    data.fill(0)
    if status:
        statuses.append(str(status))


with sd.InputStream(device=mic_id, channels=1, samplerate=mic['default_samplerate'],
                    dtype='float32', blocksize=480, callback=capture), sd.OutputStream(
                    device=speaker_id, channels=2, samplerate=48000, callback=silence):
    time.sleep(2)
print({'microphone': mic['name'], 'speaker': speaker['name'],
       'input_blocks': len(levels), 'peak': max(levels, default=0), 'warnings': statuses})
