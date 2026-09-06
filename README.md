# Exhibit audio controller (Windows)

Run **Start exhibit.cmd** to open the controller. Dependencies are installed on this PC.
On another Windows laptop, install Python 3.11 or newer and run **Setup.cmd** first.

1. Connect the microphone, speaker(s), and USB button. Click **Refresh connected devices**.
2. Choose the microphone and select your speaker outputs. This PC currently has a
   **Microphone (CMTECK)** and **Speakers (USB2.0 Device)**.
3. Choose the three audio files. Use **Move up/down** to set their order.
4. Click **Detect my button**, release all keys, wait two seconds, and hold the physical
   button until its key code appears. Then release it.
5. Click **Start exhibit**. Minimize the window to leave it running in the background.
6. Hold the button to record. Release it to save a new WAV in `recordings/`.
   The playlist keeps playing throughout. Recording voices does not add them to the playlist.
7. Click **Stop and save** or close the window to finish any active recording and stop playback.

After the first successful setup, **Start background.cmd** runs the saved configuration
without a control window. **Stop exhibit.cmd** gracefully stops either mode. In windowed
mode the controller stays open, ready to start again.
Only one controller instance can run at a time. Opening the launcher again restores the
existing controller window; it does not interrupt playback or start a second copy.
If a windowless background instance is running, the launcher shows an informational message.
No automatic startup is installed.

## Audio routing

The playlist plays file 1, then file 2, then file 3, then repeats. One or more files are
allowed for testing. WAV, MP3, FLAC, OGG, MP4, M4A, and AAC are supported. MP4 video is
ignored and its audio is decoded using bundled FFmpeg. Files in `audio/` are discovered
automatically on first launch.
Mono files are duplicated to stereo, and files are converted to 48 kHz for playback.
Playback starts at 50% volume. Recordings use the mic's native sample rate, mono, 16-bit WAV.

For synchronized sound on all three speakers, connect them to **one physical audio output**
using a suitable splitter/distribution amplifier or the speakers' supported wired linking.
Select that one output in the app. Separate Windows outputs are also supported, but startup
alignment is approximate and independent device clocks can drift. Bluetooth adds latency.

## Button and recording behavior

Button detection supports a USB button that sends a keyboard key and holds that key down
until release. The app polls only the configured key while running; it works without focus.
During the short detection step it checks key states to learn the binding; it does not save typing.
A regular keyboard's matching key also triggers recording. The key is not suppressed in other apps;
if your button is programmable, an unused key such as F13 is a useful binding.
Mouse-only, serial, game-controller, or custom HID buttons need a different input adapter.
Their exact protocol must be identified before use. A button that only sends a brief tap
cannot support physical hold duration in this mode.

The microphone stream stays open for quick response, but audio is only written while the
button is held. The capture boundary is approximate (10 ms key polling plus audio buffering).
No live microphone monitoring is enabled. Ambient speaker audio may still enter the mic.
Recordings are named `1 - (15-23-10).wav`, `2 - (15-24-02).wav`, and so on. The time
is the local 24-hour time when the button was pressed (hours-minutes-seconds); Windows
filenames cannot contain colons. Numbering continues after the highest numbered recording
in the folder, including unfinished `.partial` files, even after restarting the app.
Keep recordings in this folder to preserve the sequence; clearing it starts numbering at 1.
A held button is capped at 10 minutes;
release and press again to start another recording. Empty presses create no file.
Files being written have a `.partial` extension and are renamed to `.wav` on completion.
The writer flushes about once per second. An abrupt shutdown or disk failure can leave
a partial recording; preserve it for recovery. Flushing reduces buffering but cannot
guarantee recovery from power loss or a failing disk.

## Reliability and testing

While running, the app requests that Windows keep the screen and system awake; this request
is released when playback stops. Keep the laptop powered and avoid closing its lid. Check disk space
before the event (mono 48 kHz PCM uses about 5.8 MB per minute). The playlist is decoded
into memory for smooth looping (about 23 MB/minute). A 256 MB decoded playlist limit
rejects oversized files before they can exhaust memory; temporary decoding uses additional RAM.
Do a full rehearsal using the final laptop, button, and all three speakers.
Missing/disconnected audio devices are retried every five seconds while the exhibit is
running. Playback restarts from the beginning after reconnection, and any in-progress
recording is finished where possible. The Stop button also cancels retries. A missing
device is never silently replaced with a different microphone or speaker.
Brief output-buffer interruptions are logged and playback continues. If a device stops
delivering audio for five seconds, the controller attempts to reconnect it.
Microphone capture errors, disk failures, and unexpected code errors stop the session
with a visible status (or error dialog in background mode). They are not retried silently.
An error in a window action is logged and stops playback while leaving the window usable.
Recording is refused with less than 64 MB free space; space is checked again while writing.
Settings are saved atomically. Damaged settings reopen setup and retain the original file
until new settings are saved. Logs rotate in `logs/exhibit.log`.

These safeguards do not prevent Windows crashes, power loss, a hanging native audio driver,
or physical hardware failures. This app does not install an external process watchdog.

Run `.venv\Scripts\python.exe -m unittest -v` for automated audio, configuration,
failure-injection, recovery, and 500-recording stress tests.
Run `.venv\Scripts\python.exe exhibit.py --devices` to list Windows WASAPI endpoints.
`hardware_check.py` checks this PC's selected mic and speaker for two seconds with silent
output, reporting mic signal levels without saving microphone audio.
`reliability_hardware_check.py` runs configured devices for 60 seconds with silent output
and the button disabled. It creates no visitor recordings and writes its result to
`logs/hardware-reliability.json`. It does not simulate physically unplugging USB devices.

Audio APIs: [python-sounddevice](https://python-sounddevice.readthedocs.io/) and
[python-soundfile](https://python-soundfile.readthedocs.io/).
