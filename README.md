# Exhibit audio controller

This app plays a different audio file on each speaker and saves visitor recordings when they hold the button. You can use one, two, or three speakers.

## Start the exhibit

1. Plug in the speakers, microphone, and button. Keep the laptop plugged into power with its lid open.
2. Double-click **Start exhibit.cmd** in this folder.
3. Open the **Playback** tab. For each numbered row, click **Choose file**, then choose the speaker that should play it. Set unused rows to **Off**.
4. Open **Recording setup** and select the microphone. Use **Refresh connected devices** if you have just plugged it in.
5. Click **Start exhibit** at the bottom of the window.

Each speaker repeats its own file. Once you have set everything up, the app remembers your choices for next time.

**Before visitors arrive:** listen to each speaker and make a short test recording. Open that recording to check that the voice is clear.

## Adjust a speaker

In **Playback**, find **Adjust one speaker** and select the speaker you want to change. The sliders show that speaker's settings.

| Control | What it does |
| --- | --- |
| **Volume** | Makes that speaker quieter or louder. |
| **Echo** | Adds repeated sound. Set it to **0%** for no echo. |
| **Echo delay** | Changes the spacing between echoes. A larger number means echoes are further apart. **1000 ms = 1 second.** |
| **Loop delay** | Adds **0 to 30 seconds of silence** before that speaker's file plays again. Set it to **0** for no gap. |

Click anywhere on a slider to jump to that position, or drag it. You can adjust the sound while the exhibit is running.

Each speaker keeps its own settings. Selecting another speaker lets you edit that speaker without changing the others. Echo affects the playback files only.

## Pause or change playback

- **Pause / Resume:** use the button beside a speaker's file assignment. Resume continues from where it paused.
- **Off:** choose this in the speaker list to turn that row off. Turning it on again starts its file again. All three rows can be Off if you only want to record visitors.
- **Change a file:** click **Choose file** beside the speaker. You can do this while running. Wait for the loading message to finish before making another change.
- **Swap assignments:** choosing a file or speaker already used in another row swaps the two assignments. Each file and speaker can only be used once.

Pausing one speaker does not pause the others or stop visitor recording.

## Record a visitor

Tell the visitor:

> Hold the button, wait half a second, then speak. Keep holding it while speaking. Release it when you finish.

The half-second wait helps keep the button click out of the recording. A very quick tap does not save a file.

The app saves a new recording each time someone does this. The speakers keep playing, and visitor recordings are not played back automatically.

### Find the recordings

Open the **recordings** folder beside this README. Finished recordings are WAV files, which you can double-click to listen to.

For example, **1 - (15-23-10).wav** means recording number 1, started at 3:23:10 pm. The next recording gets the next number, including after restarting the app.

Keep the files in this folder if you want numbering to continue. Emptying the folder starts numbering again at 1. Copy recordings elsewhere when you want a backup.

A single recording can last up to **10 minutes**. After that, release the button and press it again to record more.

### Set up the button for the first time

1. Stop the exhibit if it is running.
2. Open **Recording setup** and click **Detect my button**.
3. Release all keys and wait two seconds.
4. Hold the physical button until the app says it has detected it, then release it.

You normally only need to do this once, or when changing the button.

## Finish for the day

Click **Stop and save**. This stops playback, finishes any active recording, and saves your settings. Closing the app does the same thing.

To keep the exhibit running while hiding the window, click **Minimize to background**. Minimize does not stop it.

## If something is not working

| Problem | What to try |
| --- | --- |
| A speaker is silent | Check its power and Windows volume. In the app, check that it has a file, is not Off or paused, and its Volume is above 0. It may also be waiting through its loop delay. |
| The microphone or speaker is missing | Check the cable. Stop the exhibit, open Recording setup, and click Refresh connected devices. Check the selections before starting again. |
| A device disconnects while running | Reconnect it. The app tries to reconnect automatically. Playback starts again from the beginning after recovery. |
| No recording appears | Check the selected microphone and button setup. Hold the button for longer than half a second, then release it. Check the message at the bottom of the app. |
| A recording is quiet | Move closer to the microphone and check its input volume in Windows. The app's Volume slider controls the speaker, not the microphone. |
| The app says it is already running | Use the existing app. If you started it without a window, double-click Stop exhibit.cmd before opening Start exhibit.cmd. |
| A file will not load, or another error appears | Read the message at the bottom of the app. Try another audio file if loading failed. If you need help, share the message and the file logs/exhibit.log from this folder. |

Keep some free space on the laptop for recordings. If a power failure leaves a file ending in **.partial**, keep it and ask for help recovering it.

## Other useful details

- **Audio files:** put them in the **audio** folder, or select them from another folder using Choose file. WAV, MP3, FLAC, OGG, MP4, M4A, and AAC are supported. For video files, only the sound plays.
- **Three different sounds:** Windows must show each speaker as a separate output. A simple audio splitter sends the same sound to every connected speaker.
- **Run without a window:** after testing your setup, double-click **Start background.cmd** to run the saved settings. Double-click **Stop exhibit.cmd** to stop it. Use Start exhibit.cmd when you want to adjust settings.
- **Move to another laptop:** this app needs Windows. Install Python 3.11 or newer, then double-click **Setup.cmd** with an internet connection. When setup finishes, open Start exhibit.cmd and select the devices on that laptop. Ask the person who supplied the app for help with this one-time setup if needed.

## What the folders are for

The Start, Stop, and Setup buttons stay beside this README so they are easy to find.

| Folder | What's inside |
| --- | --- |
| **audio** | The files played through the speakers. |
| **recordings** | Saved visitor recordings. |
| **logs** | Information to share if you need help with a problem. |
| **app** | The app itself. |
| **setup** | Files used by the Setup button. |
| **tests** | Checks used by the person maintaining the app. |
| **tools** | Extra checks for microphones, speakers, and the button. |
| **docs** | Notes for the person maintaining the app. |

You normally only need the launch buttons, **audio**, and **recordings**. Leave **config.json** in place: it stores your saved settings.
