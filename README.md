# Exhibit audio controller (Windows)

Run **Start exhibit.cmd** to open the controller. Dependencies are installed on this PC.
On another Windows laptop, install Python 3.11 or newer and run **Setup.cmd** first.

1. Connect the microphone, speaker(s), and USB button. Click **Refresh connected devices**.
2. Choose the microphone. In each numbered row, choose one audio file and the output
   that should play it. Set unused rows to **Off** (for example, when testing one speaker).
3. Set the playback echo amount and delay. Start with 35% / 350 ms, or use 0% for no echo.
   Echo, volume, file selections, and speaker assignments all update while playing.
   **Delay between loops** adds 0–30 seconds of silence after each file finishes, independently
   for each speaker. The shared delay slider updates live and defaults to zero.
   Click anywhere on a slider to jump directly to that value, or drag continuously.
   For an exact loop delay, type seconds into **Set seconds** and press Enter or click
   elsewhere. The arrow buttons adjust it in 0.1-second steps.
   Use a row's **Pause / Resume** button to freeze and resume that speaker's position,
   including any remaining loop delay. Other speakers and microphone recording continue.
4. Click **Detect my button**, release all keys, wait two seconds, and hold the physical
   button until its key code appears. Then release it.
5. Click **Start exhibit**. Minimize the window to leave it running in the background.
6. Hold the button, wait half a second, then speak. Release it to save a new WAV in `recordings/`.
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

Each enabled row loops its own file independently on its assigned speaker. Outputs start
together approximately; a shorter file repeats without waiting for the other files.
Zero to three outputs can be enabled. With every row set to **Off**, there is no speaker
playback and the microphone recorder still works. You can start in this mode or switch
all outputs off and back on while running. WAV, MP3, FLAC, OGG, MP4, M4A, and AAC are supported. MP4 video is
ignored and its audio is decoded using bundled FFmpeg. Files in `audio/` are discovered
automatically on first launch.
Mono files are duplicated to stereo, and files are converted to 48 kHz for playback.
Each playback file is automatically peak-normalized toward -1 dBFS with a maximum
30 dB boost before echo is applied. This makes quiet source files louder while retaining
their dynamics and stereo balance. Silence remains silent. Normalization happens in
memory on Start and live file changes; source files and microphone recordings are unchanged.
Playback starts at 50% volume. Recordings use the mic's native sample rate, mono, 16-bit WAV.

Each speaker needs a separate Windows audio output. A splitter duplicates the same signal
and cannot provide three different files. This version routes to separate Windows endpoints;
individual channels on a multichannel audio interface are not yet selectable. Independent
device clocks can drift and Bluetooth adds latency; sample-accurate synchronization is not guaranteed.

Choose a different file or speaker while running to change its assignment. Selecting one
already used in another row swaps those two assignments. Each active file and speaker can
appear only once; equivalent file paths are also treated as duplicates. New files decode in the background. Wait for the loading message to
finish before making another routing change. A failed change retains the previous routes.
Unchanged speakers keep playing, and the microphone recording stream is not restarted.
Changed files begin near their start; opening a different hardware output can add a short
delay. Pause state belongs to the speaker device, so swapping assignments preserves that
speaker's paused state. Off closes its output; enabling it again starts its file near the
beginning. Assignments, pause states, and loop delay are saved when stopped or closed.

Echo applies only to the playback files. Amount controls the strength of three decaying
repeats, and delay controls their spacing (50–1500 ms). Adjust either slider while playing;
changes crossfade over 50 ms without restarting loops or recording. Settings are saved
when you stop or close the controller. The echoes wrap across each file's
loop boundary, preserving its original duration. This produces an already-established echo
on the first loop as well. During the loop delay all playback, including echo, is silent.
Mixing includes volume headroom and output clipping protection.
Original audio files and microphone recordings are not modified by the echo.

## Button and recording behavior

Button detection supports a USB button that sends a keyboard key and holds that key down
until release. The app polls only the configured key while running; it works without focus.
During the short detection step it checks key states to learn the binding; it does not save typing.
A regular keyboard's matching key also triggers recording. The key is not suppressed in other apps;
if your button is programmable, an unused key such as F13 is a useful binding.
Mouse-only, serial, game-controller, or custom HID buttons need a different input adapter.
Their exact protocol must be identified before use. A button that only sends a brief tap
cannot support physical hold duration in this mode.

The microphone stream stays open for quick response. The first 0.5 seconds of captured
audio after each press is discarded to exclude the button click. Speak after this short
delay; the window shows HOLD during the delay and RECORDING afterward. A press shorter
than half a second creates no saved recording. Release ends recording immediately.
The capture boundary is approximate (10 ms key polling plus audio buffering).
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
