"""Windows exhibit: continuous playlist and press-and-hold recording."""
from __future__ import annotations

import argparse
from concurrent.futures import Future
import ctypes
import json
import logging
from logging.handlers import RotatingFileHandler
import math
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime

import numpy as np
import sounddevice as sd
import soundfile as sf
from scipy.signal import resample_poly

ROOT = Path(__file__).resolve().parent
RATE = 48000
CONFIG = ROOT / 'config.json'
MIN_FREE_BYTES = 64 * 1024 * 1024
MAX_PLAYLIST_BYTES = 256 * 1024 * 1024


class DeviceUnavailable(RuntimeError):
    pass


def speaker_values(config, speaker=None):
    values = dict(volume=config.get('volume', .5), echo_amount=config.get('echo_amount', .35),
                  echo_delay_ms=config.get('echo_delay_ms', 350),
                  loop_delay_seconds=config.get('loop_delay_seconds', 0))
    values.update(config.get('speaker_settings', {}).get(speaker, {}))
    return values


def validate_speaker_settings(settings):
    if not isinstance(settings, dict):
        raise ValueError('Speaker settings must be an object.')
    for name, values in settings.items():
        if not isinstance(name, str) or not isinstance(values, dict):
            raise ValueError('Invalid speaker settings.')
        for key, low, high in [('volume', 0, 1), ('echo_amount', 0, .75), ('echo_delay_ms', 50, 1500), ('loop_delay_seconds', 0, 30)]:
            if key in values:
                value = values[key]
                if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
                    raise ValueError(f'{name}: invalid {key}.')


def validate_config(config):
    if not isinstance(config, dict):
        raise ValueError('Settings must be a JSON object. Open the controller to configure it.')
    validate_speaker_settings(config.get('speaker_settings', {}))
    if not isinstance(config.get('microphone'), str) or not config['microphone']:
        raise ValueError('Select a microphone.')
    for field in ('speakers', 'files'):
        values = config.get(field)
        if not isinstance(values, list) or not all(isinstance(v, str) and v for v in values):
            raise ValueError(f'Invalid {field} assignments.')
        identities = [os.path.normcase(str(Path(v).resolve())) if field == 'files' else v.casefold() for v in values]
        if len(set(identities)) != len(values):
            raise ValueError('Each file can be assigned only once.' if field == 'files'
                             else 'Each speaker can be assigned only once.')
    if len(config['speakers']) != len(config['files']):
        raise ValueError('Assign exactly one audio file to each enabled speaker.')
    for name, default, low, high in [('echo_amount', .35, 0, .75), ('echo_delay_ms', 350, 50, 1500), ('loop_delay_seconds', 0, 0, 30)]:
        value = config.get(name, default)
        if not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f'{name} must be between {low} and {high}.')
    paused = config.get('paused_speakers', [])
    if not isinstance(paused, list) or not all(isinstance(name, str) for name in paused):
        raise ValueError('Invalid paused speaker list.')
    key = config.get('button_vk')
    if type(key) is not int or not 1 <= key <= 254:
        raise ValueError('Detect the button again.')
    volume = config.get('volume', .5)
    if not isinstance(volume, (int, float)) or not math.isfinite(volume) or not 0 <= volume <= 1:
        raise ValueError('Playback volume must be between 0 and 1.')
    for filename in config['files']:
        if not Path(filename).is_file():
            raise ValueError(f'Audio file is missing: {filename}. Choose the files again.')
    return config


def save_config(config, path=CONFIG):
    validate_config(config)
    temporary = path.with_suffix('.tmp')
    with temporary.open('w', encoding='utf-8') as output:
        json.dump(config, output, indent=2)
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(path)


def load_gui_config(path=CONFIG):
    try:
        config = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        if not isinstance(config, dict):
            raise ValueError('Settings must be a JSON object.')
        for name in ('files', 'speakers'):
            if name in config and (not isinstance(config[name], list)
                                   or not all(isinstance(v, str) for v in config[name])):
                raise ValueError(f'Invalid {name} settings.')
        if 'microphone' in config and not isinstance(config['microphone'], str):
            raise ValueError('Invalid microphone setting.')
        if 'button_vk' in config and (type(config['button_vk']) is not int or not 1 <= config['button_vk'] <= 254):
            config.pop('button_vk')
        level = config.get('volume', .5)
        if not isinstance(level, (int, float)) or not math.isfinite(level) or not 0 <= level <= 1:
            config['volume'] = .5
        for field, default, low, high in [('echo_amount', .35, 0, .75), ('echo_delay_ms', 350, 50, 1500), ('loop_delay_seconds', 0, 0, 30)]:
            value = config.get(field, default)
            if field in config and (not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high):
                config[field] = default
        if 'paused_speakers' in config and (not isinstance(config['paused_speakers'], list)
                or not all(isinstance(name, str) for name in config['paused_speakers'])):
            config['paused_speakers'] = []
        if 'routing_rows' in config and (not isinstance(config['routing_rows'], list)
                or not all(isinstance(row, dict) and isinstance(row.get('file'), str)
                           and isinstance(row.get('output'), str) for row in config['routing_rows'])):
            config.pop('routing_rows')
        try:
            validate_speaker_settings(config.get('speaker_settings', {}))
        except ValueError:
            logging.warning('Invalid per-speaker settings reset to the existing playback defaults')
            config.pop('speaker_settings', None)
        return config
    except (ValueError, OSError) as exc:
        logging.error('Could not read settings; opening setup. Original file retained: %s', exc)
        return {}


def check_disk(folder):
    if shutil.disk_usage(folder).free < MIN_FREE_BYTES:
        raise OSError('Less than 64 MB of free disk space remains. Free space before recording again.')


def devices(kind):
    apis = sd.query_hostapis()
    return [(i, d) for i, d in enumerate(sd.query_devices())
            if d['max_' + kind + '_channels'] > 0
            and apis[d['hostapi']]['name'] == 'Windows WASAPI']


def resolve(name, kind):
    matches = [(i, d) for i, d in devices(kind) if d['name'] == name]
    if len(matches) != 1:
        raise DeviceUnavailable(f'{kind.title()} device unavailable or ambiguous: {name}. Reconnect it or select it again.')
    return matches[0]


def normalize_playback(audio):
    """Raise quiet playback to -1 dBFS peak, with at most 30 dB of gain."""
    peak = float(np.max(np.abs(audio)))
    if peak == 0:
        return audio
    gain = min(10 ** (30 / 20), 10 ** (-1 / 20) / peak)
    return (audio * gain).astype('float32')


def load_playlist(paths, rate=RATE, separate=False, normalize=False):
    tracks = []
    total_bytes = 0
    for path in paths:
        remaining_frames = (MAX_PLAYLIST_BYTES - total_bytes) // 8
        if Path(path).suffix.lower() in ('.mp4', '.m4a', '.aac', '.mov'):
            import imageio_ffmpeg
            result = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-v', 'error', '-i', str(path),
                                     '-vn', '-t', str(remaining_frames / rate + 1),
                                     '-f', 'f32le', '-acodec', 'pcm_f32le', '-ar', str(rate),
                                     '-ac', '2', 'pipe:1'], capture_output=True, timeout=300,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode:
                raise ValueError(f'Could not decode {path}: {result.stderr.decode(errors="replace")}')
            data = np.frombuffer(result.stdout, dtype='<f4').reshape(-1, 2)
            source_rate = rate
        else:
            info = sf.info(path)
            if (info.frames * rate / info.samplerate > remaining_frames
                    or info.frames * info.channels * 4 > MAX_PLAYLIST_BYTES):
                raise ValueError('Playlist is too large to load safely (256 MB decoded limit). Use shorter audio files.')
            data, source_rate = sf.read(path, dtype='float32', always_2d=True)
        if len(data) == 0:
            raise ValueError(f'Empty audio file: {path}')
        if data.shape[1] == 1:
            data = np.repeat(data, 2, axis=1)
        elif data.shape[1] != 2:
            raise ValueError(f'Use mono or stereo audio: {path}')
        if source_rate != rate:
            divisor = math.gcd(source_rate, rate)
            data = resample_poly(data, rate // divisor, source_rate // divisor).astype('float32')
        if not np.isfinite(data).all():
            raise ValueError(f'Invalid audio samples: {path}')
        total_bytes += data.nbytes
        if total_bytes > MAX_PLAYLIST_BYTES:
            raise ValueError('Playlist is too large to load safely (256 MB decoded limit). Use shorter audio files.')
        tracks.append(normalize_playback(data) if normalize else data)
    if not tracks:
        if separate:
            return []
        raise ValueError('Choose at least one audio file first.')
    return tracks if separate else np.concatenate(tracks)


def apply_echo(audio, amount=.35, delay_ms=350, rate=RATE):
    """Three decaying repeats across loop boundaries, with headroom against clipping."""
    if amount == 0:
        return audio
    delay = max(1, round(rate * delay_ms / 1000))
    result = audio.copy()
    gain = 1.0
    for repeat in range(1, 4):
        weight = amount ** repeat
        result += weight * np.roll(audio, repeat * delay, axis=0)
        gain += weight
    result /= gain
    return result


def loop_block(audio, position, frames):
    indexes = (np.arange(frames) + position) % len(audio)
    return audio[indexes], (position + frames) % len(audio)


class LiveEcho:
    """Render echo from the looping source, crossfading parameter changes over 50 ms."""
    def __init__(self, audio, amount=.35, delay_ms=350, rate=RATE):
        self.audio = audio
        self.rate = rate
        self.current = (amount, delay_ms)
        self.target = None
        self.fade_position = 0
        self.fade_frames = max(1, round(rate * .05))

    def _block(self, position, frames, settings):
        amount, delay_ms = settings
        result, _ = loop_block(self.audio, position, frames)
        if amount:
            delay = max(1, round(self.rate * delay_ms / 1000))
            gain = 1.0
            for repeat in range(1, 4):
                weight = amount ** repeat
                delayed, _ = loop_block(self.audio, position - delay * repeat, frames)
                result += weight * delayed
                gain += weight
            result /= gain
        return result

    def render(self, position, frames, amount, delay_ms):
        requested = (amount, delay_ms)
        if self.target is None and requested != self.current:
            self.target = requested
            self.fade_position = 0
        result = self._block(position, frames, self.current)
        if self.target is not None:
            updated = self._block(position, frames, self.target)
            blend = np.minimum((np.arange(frames) + self.fade_position + 1) / self.fade_frames, 1)[:, None]
            result = (result * (1 - blend) + updated * blend).astype('float32')
            self.fade_position += frames
            if self.fade_position >= self.fade_frames:
                self.current = self.target
                self.target = None
        return result


def show_existing_controller():
    """Reopening the launcher restores the existing Tk window without restarting audio."""
    from ctypes import wintypes

    user = ctypes.windll.user32
    user.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user.FindWindowW.restype = wintypes.HWND
    user.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]
    user.SetForegroundWindow.argtypes = [wintypes.HWND]
    window = user.FindWindowW('TkTopLevel', 'Exhibit audio controller')
    if window:
        user.ShowWindowAsync(window, 9)  # SW_RESTORE includes minimized windows.
        user.SetForegroundWindow(window)
        logging.info('Existing controller window restored')
    else:
        logging.info('Controller already running in background or still starting')
        user.MessageBoxW(0, 'The exhibit is already running in the background or still starting.\n\n'
                         'Use Stop exhibit.cmd to stop background playback.',
                         'Exhibit already running', 0x40)


class Recorder:
    """Ordered disk worker; no file writes occur in the audio callback."""
    def __init__(self, folder, rate, max_seconds=600, start_delay_seconds=0):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        check_disk(self.folder)
        self.rate = rate
        self.max_frames = int(rate * max_seconds)
        self.start_delay_frames = round(rate * start_delay_seconds)
        self.skip_frames = 0
        self.frames = 0
        self.active = False
        self.lock = threading.Lock()
        self.queue = queue.Queue(maxsize=2048)
        self.error = None
        self.saved = 0
        self.last_path = None
        self.closed = False
        self.last_callback = time.monotonic()
        numbers = [int(match.group(1)) for entry in self.folder.iterdir()
                   if entry.suffix.lower() in ('.wav', '.partial')
                   and (match := re.fullmatch(r'(\d+) - \(\d{2}-\d{2}-\d{2}\)', entry.stem))]
        self.next_number = max(numbers, default=0) + 1
        self.worker = threading.Thread(target=self._write, daemon=True)
        self.worker.start()

    def _put(self, event):
        try:
            self.queue.put_nowait(event)
        except queue.Full:
            self.error = 'Recording disk queue filled. Check free space and disk speed.'
            self.active = False

    def press(self):
        with self.lock:
            if not self.active and not self.error and not self.closed:
                self.frames = 0
                self.skip_frames = self.start_delay_frames
                self._put(('start', datetime.now()))
                self.active = self.error is None

    def release(self):
        with self.lock:
            if self.active:
                self.active = False
                self._put(('end', None))

    def callback(self, data, frames, timing, status):
        self.last_callback = time.monotonic()
        try:
            self._capture(data, frames, timing, status)
        except Exception as exc:
            self.error = f'Microphone callback failed: {exc}'
            self.active = False

    def _capture(self, data, frames, timing, status):
        with self.lock:
            if self.active:
                if status:
                    self.error = f'Microphone audio interruption: {status}'
                    self.active = False
                    self._put(('end', None))
                    return
                remaining = self.max_frames - self.frames
                skipped = min(self.skip_frames, len(data))
                self.skip_frames -= skipped
                data = data[skipped:]
                if not len(data):
                    return
                chunk = data[:remaining].copy()
                self._put(('audio', chunk))
                self.frames += len(chunk)
                if self.frames >= self.max_frames:
                    self.active = False
                    self._put(('end', None))

    def _write(self):
        output = None
        path = None
        flushed_at = time.monotonic()

        def finish():
            nonlocal output
            if output is not None:
                length = output.tell()
                output.close()
                output = None
                if length:
                    final = path.with_suffix('.wav')
                    path.rename(final)
                    self.last_path = final
                    self.saved += 1
                    logging.info('Saved %s', final)
                else:
                    path.unlink(missing_ok=True)

        try:
            while True:
                event, data = self.queue.get()
                if event == 'start':
                    finish()
                    check_disk(self.folder)
                    while True:
                        name = f'{self.next_number} - ({data:%H-%M-%S})'
                        self.next_number += 1
                        path = self.folder / (name + '.partial')
                        if not path.exists() and not path.with_suffix('.wav').exists():
                            break
                    output = sf.SoundFile(path, mode='x', samplerate=self.rate,
                                          channels=1, format='WAV', subtype='PCM_16')
                elif event == 'audio' and output is not None:
                    output.write(data)
                    if time.monotonic() - flushed_at >= 1:
                        output.flush()
                        check_disk(self.folder)
                        flushed_at = time.monotonic()
                elif event == 'end':
                    finish()
                elif event == 'quit':
                    finish()
                    return
        except Exception as exc:
            self.error = f'Could not save recording: {exc}'
            self.active = False
            logging.exception('Recording failed')
        finally:
            if output is not None:
                try:
                    output.close()
                except Exception:
                    logging.exception('Could not close partial recording; preserve it for recovery')

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.release()
        deadline = time.monotonic() + 10
        while self.worker.is_alive():
            try:
                self.queue.put(('quit', None), timeout=0.1)
                break
            except queue.Full:
                if time.monotonic() >= deadline:
                    raise RuntimeError('Recording disk is not responding. The partial file has been preserved.')
        self.worker.join(timeout=max(0, deadline - time.monotonic()))
        if self.worker.is_alive():
            raise RuntimeError('Recording writer did not finish; check the disk.')
        if self.error:
            raise RuntimeError(self.error)


class Engine:
    def __init__(self, config):
        self.config = config
        self.streams = []
        self.recorder = None
        self.error = None
        self.down = False
        self.output_warnings = 0
        self.reported_warnings = 0
        self.last_warning = 0
        self.output_heartbeats = []
        self.routes = {}

    def start(self):
        try:
            validate_config(self.config)
            mic_id, mic = resolve(self.config['microphone'], 'input')
            outputs = [resolve(name, 'output') for name in self.config['speakers']]
            tracks = load_playlist(self.config['files'], separate=True, normalize=True)
            mic_rate = int(mic['default_samplerate'])
            sd.check_input_settings(device=mic_id, channels=1, samplerate=mic_rate)
            for device_id, device in outputs:
                channels = min(2, device['max_output_channels'])
                sd.check_output_settings(device=device_id, channels=channels, samplerate=RATE)
            self.recorder = Recorder(ROOT / 'recordings', mic_rate, start_delay_seconds=.5)
            mic_stream = sd.InputStream(device=mic_id, samplerate=mic_rate, channels=1,
                                        dtype='float32', blocksize=480, callback=self.recorder.callback)
            self.streams.append(mic_stream)
            for (device_id, device), audio in zip(outputs, tracks):
                index = len(self.routes)
                name = self.config['speakers'][index]
                channels = min(2, device['max_output_channels'])
                route = dict(file=self.config['files'][index], callback=self._playback(audio, channels, speaker=name), channels=channels)
                stream = sd.OutputStream(device=device_id, samplerate=RATE, channels=channels,
                                         dtype='float32', callback=lambda *args, slot=route: slot['callback'](*args))
                route['stream'] = stream
                self.routes[name] = route
                self.streams.append(stream)
            self.epoch = time.monotonic() + 0.5
            for stream in self.streams:
                stream.start()
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000003)
            logging.info('Exhibit started with independent loops: %s; echo=%s, delay=%s ms',
                         list(zip(self.config['speakers'], self.config['files'])),
                         self.config.get('echo_amount', .35), self.config.get('echo_delay_ms', 350))
        except Exception:
            try:
                self.stop()
            except Exception:
                logging.exception('Cleanup after failed start also failed')
            raise

    def reconfigure(self, config, tracks):
        """Prepare new outputs first, then replace routes without touching the mic."""
        validate_config(config)
        if len(tracks) != len(config['files']):
            raise ValueError('Every speaker must have a decoded audio file.')
        previous_heartbeats = list(self.output_heartbeats)
        added = []
        replacements = {}
        planned = {}
        try:
            for name, filename, audio in zip(config['speakers'], config['files'], tracks):
                if name in self.routes:
                    route = self.routes[name]
                    planned[name] = route
                    if filename != route['file']:
                        replacements[name] = self._playback(audio, route['channels'], epoch=time.monotonic(), speaker=name)
                else:
                    device_id, device = resolve(name, 'output')
                    channels = min(2, device['max_output_channels'])
                    sd.check_output_settings(device=device_id, channels=channels, samplerate=RATE)
                    route = dict(file=filename, channels=channels, ready=False)
                    route['callback'] = self._playback(audio, channels, epoch=time.monotonic(), speaker=name)

                    def render(data, *args, slot=route):
                        if slot['ready']:
                            slot['callback'](data, *args)
                        else:
                            data.fill(0)

                    route['stream'] = sd.OutputStream(device=device_id, samplerate=RATE, channels=channels,
                                                       dtype='float32', callback=render)
                    added.append(route)
                    route['stream'].start()
                    planned[name] = route
        except Exception:
            for route in added:
                try:
                    route['stream'].abort()
                except Exception:
                    logging.exception('New speaker cleanup failed')
                finally:
                    try:
                        route['stream'].close()
                    except Exception:
                        logging.exception('New speaker close failed')
            self.output_heartbeats = previous_heartbeats
            raise
        for name, callback in replacements.items():
            planned[name]['callback'] = callback
            planned[name]['file'] = config['files'][config['speakers'].index(name)]
        for route in added:
            route['ready'] = True
        removed = [route for name, route in self.routes.items() if name not in planned]
        self.routes = planned
        self.streams = self.streams[:1] + [route['stream'] for route in planned.values()]
        self.output_heartbeats = [route['callback'].heartbeat for route in planned.values()]
        for route in removed:
            try:
                route['stream'].abort()
            except Exception:
                logging.exception('Old speaker stop failed during routing change')
            finally:
                try:
                    route['stream'].close()
                except Exception:
                    logging.exception('Old speaker close failed during routing change')
        self.config.update({key: config[key] for key in ('speakers', 'files', 'routing_rows') if key in config})
        logging.info('Live routing updated: %s', list(zip(config['speakers'], config['files'])))

    def _playback(self, audio, channels, epoch=None, speaker=None):
        position = None
        initial = speaker_values(self.config, speaker)
        echo = LiveEcho(audio, initial['echo_amount'], initial['echo_delay_ms'])
        heartbeat = [time.monotonic()]
        self.output_heartbeats.append(heartbeat)

        def callback(outdata, frames, timing, status):
            nonlocal position
            settings = speaker_values(self.config, speaker)
            if status:
                self.output_warnings += 1
            if speaker is not None and speaker in self.config.get('paused_speakers', []):
                outdata.fill(0)
                if position is None:
                    position = 0
                return
            if position is None:
                delay = timing.outputBufferDacTime - timing.currentTime
                offset = round((time.monotonic() + delay - (self.epoch if epoch is None else epoch)) * RATE)
                silence = min(frames, max(0, -offset))
                outdata.fill(0)
                if silence == frames:
                    return
                position = max(0, offset)
            else:
                silence = 0
            gap = round(settings['loop_delay_seconds'] * RATE)
            cycle = len(audio) + gap
            if position >= cycle:
                position = 0
            outdata[silence:] = 0
            written = silence
            while written < frames:
                if position < len(audio):
                    count = min(frames - written, len(audio) - position)
                    block = echo.render(position, count, settings['echo_amount'], settings['echo_delay_ms'])
                    outdata[written:written + count] = block if channels == 2 else block.mean(axis=1, keepdims=True)
                else:
                    count = min(frames - written, cycle - position)
                written += count
                position = (position + count) % cycle
            outdata *= settings['volume']
            np.clip(outdata, -1, 1, out=outdata)
        def guarded_callback(outdata, frames, timing, status):
            heartbeat[0] = time.monotonic()
            try:
                callback(outdata, frames, timing, status)
            except Exception as exc:
                outdata.fill(0)
                self.error = f'Playback callback failed: {exc}'
        guarded_callback.heartbeat = heartbeat
        return guarded_callback

    def tick(self):
        if self.recorder.error:
            raise RuntimeError(self.recorder.error)
        if self.error:
            raise RuntimeError(self.error)
        if not self.recorder.worker.is_alive():
            raise RuntimeError('Recording writer stopped unexpectedly.')
        if self.output_warnings != self.reported_warnings and time.monotonic() - self.last_warning >= 10:
            logging.warning('Speaker buffer interruptions: %s (playback continues)', self.output_warnings)
            self.reported_warnings = self.output_warnings
            self.last_warning = time.monotonic()
        if any(not stream.active for stream in self.streams):
            raise DeviceUnavailable('An audio device stopped. Waiting for it to reconnect.')
        now = time.monotonic()
        if now - self.recorder.last_callback > 5 or any(now - beat[0] > 5 for beat in self.output_heartbeats):
            raise DeviceUnavailable('An audio device stopped delivering audio. Reconnecting.')
        down = bool(ctypes.windll.user32.GetAsyncKeyState(self.config['button_vk']) & 0x8000)
        if down and not self.down:
            self.recorder.press()
        elif self.down and not down:
            self.recorder.release()
        self.down = down

    def stop(self):
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
        for stream in reversed(self.streams):
            try:
                stream.abort()
            except Exception:
                logging.exception('Device cleanup failed')
            finally:
                try:
                    stream.close()
                except Exception:
                    logging.exception('Device close failed')
        self.streams.clear()
        self.routes.clear()
        if self.recorder:
            self.recorder.close()
        logging.info('Exhibit stopped')


class Session:
    """Retry disconnected audio devices while allowing the operator to stop retries."""
    def __init__(self, config, factory=Engine):
        self.config = config
        self.factory = factory
        self.engine = None
        self.running = True
        self.retry_at = 0
        self.status = 'Starting…'
        self.saved = 0

    def stop(self):
        self.running = False
        self._close_engine()

    def apply_routes(self, config, tracks):
        if self.engine:
            self.engine.reconfigure(config, tracks)
        self.config.update({key: config[key] for key in ('speakers', 'files', 'routing_rows') if key in config})

    def _close_engine(self):
        engine, self.engine = self.engine, None
        if engine:
            try:
                engine.stop()
            finally:
                if engine.recorder:
                    self.saved += engine.recorder.saved

    def tick(self):
        if not self.running:
            return
        try:
            if self.engine is None:
                if time.monotonic() < self.retry_at:
                    return
                # Refresh PortAudio's device inventory only after all streams closed.
                sd._terminate()
                sd._initialize()
                self.engine = self.factory(self.config)
                self.engine.start()
            self.engine.tick()
            rec = self.engine.recorder
            self.status = ('RECORDING — release to save' if rec.active else 'PLAYING — hold the button to record')
            if not rec.active and not self.config.get('speakers'):
                self.status = 'PLAYBACK OFF — microphone ready; hold the button to record'
            elif not rec.active and all(name in self.config.get('paused_speakers', []) for name in self.config.get('speakers', [])):
                self.status = 'PLAYBACK PAUSED — microphone ready; hold the button to record'
            if rec.active and getattr(rec, 'skip_frames', 0) > 0:
                self.status = 'HOLD — waiting 0.5 seconds to skip the button click…'
            self.status += f' | Saved this session: {self.saved + rec.saved}'
        except (DeviceUnavailable, sd.PortAudioError) as exc:
            try:
                self._close_engine()
            except Exception:
                self.running = False
                raise
            self.retry_at = time.monotonic() + 5
            self.status = f'Waiting for audio device — retrying every 5 seconds. {exc}'
            logging.warning('%s', self.status)
        except Exception:
            self.running = False
            try:
                self._close_engine()
            except Exception:
                logging.exception('Cleanup after session error failed')
            raise


def click_scale(parent, **options):
    """A native scale that jumps to the clicked position and follows dragging."""
    from tkinter import ttk

    scale = ttk.Scale(parent, **options)

    def move(event):
        if not scale.instate(['disabled']):
            scale.focus_set()
            scale.set(float(scale.get(event.x, event.y)))
        return 'break'  # Suppress ttk's default step-and-repeat trough behavior.

    scale.bind('<Button-1>', move)
    scale.bind('<B1-Motion>', move)
    scale.bind('<ButtonRelease-1>', lambda event: 'break')
    return scale


def gui():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    window = tk.Tk()
    window.title('Exhibit audio controller')
    window.geometry(f'960x{min(870, window.winfo_screenheight() - 100)}')
    window.minsize(850, 700)
    style = ttk.Style(window)
    style.configure('Section.TLabel', font=('Segoe UI', 12, 'bold'))
    style.configure('Hint.TLabel', foreground='#505b65')
    style.configure('TNotebook.Tab', padding=(16, 8))
    shell = ttk.Frame(window, padding=20)
    shell.pack(fill='both', expand=True)
    state = {'engine': None, 'vk': None, 'files': [], 'learning': False, 'route_job': None}
    saved = load_gui_config()
    state['speaker_settings'] = {name: dict(values) for name, values in saved.get('speaker_settings', {}).items()}
    state['loading_controls'] = False
    state['paused_speakers'] = set(saved.get('paused_speakers', []))
    (ROOT / 'audio').mkdir(exist_ok=True)
    discovered = sorted(str(p) for p in (ROOT / 'audio').iterdir()
                        if p.suffix.lower() in ('.wav', '.mp3', '.flac', '.ogg', '.mp4', '.m4a', '.aac'))
    state.update(vk=saved.get('button_vk'), files=saved.get('files', discovered))
    ttk.Label(shell, text='Exhibit audio controller', font=('Segoe UI', 20)).pack(anchor='w')
    ttk.Label(shell, text='Set up your speakers, adjust the sound, and collect visitor recordings.',
              style='Hint.TLabel').pack(anchor='w', pady=(4, 16))
    footer = ttk.Frame(shell, padding=(0, 12, 0, 0))
    footer.pack(side='bottom', fill='x')
    tabs = ttk.Notebook(shell)
    tabs.pack(fill='both', expand=True)
    playback_page = ttk.Frame(tabs)
    viewport = tk.Canvas(playback_page, highlightthickness=0, background=window.cget('background'))
    scrollbar = ttk.Scrollbar(playback_page, orient='vertical', command=viewport.yview)
    scrollbar.pack(side='right', fill='y')
    viewport.pack(side='left', fill='both', expand=True)
    viewport.configure(yscrollcommand=scrollbar.set)
    frame = ttk.Frame(viewport, padding=16)
    content_window = viewport.create_window(0, 0, window=frame, anchor='nw')
    frame.bind('<Configure>', lambda event: viewport.configure(scrollregion=viewport.bbox('all')))
    viewport.bind('<Configure>', lambda event: viewport.itemconfigure(content_window, width=event.width))
    recording_tab = ttk.Frame(tabs, padding=16)
    tabs.add(playback_page, text='Playback')
    tabs.add(recording_tab, text='Recording setup')

    def scroll_playback(event):
        widget = window.winfo_containing(event.x_root, event.y_root)
        if widget and widget.winfo_class() not in ('TScale', 'TSpinbox', 'TCombobox'):
            while widget is not None:
                if widget is playback_page:
                    viewport.yview_scroll(-int(event.delta / 120), 'units')
                    return 'break'
                widget = widget.master

    window.bind('<MouseWheel>', scroll_playback)
    ttk.Label(recording_tab, text='Visitor microphone', style='Section.TLabel').pack(anchor='w')
    ttk.Label(recording_tab, text='Hold the button, wait half a second, then speak. Release to save.',
              style='Hint.TLabel').pack(anchor='w', pady=(8, 16))
    ttk.Label(recording_tab, text='Microphone input').pack(anchor='w')
    mic = ttk.Combobox(recording_tab, state='readonly')
    mic.pack(fill='x', pady=(4, 16))
    ttk.Label(frame, text='1. Assign your speakers', style='Section.TLabel').pack(anchor='w')
    ttk.Label(frame, text='One file per speaker. Selecting an assignment already in use swaps the rows.',
              style='Hint.TLabel').pack(anchor='w', pady=(4, 8))
    assignments = []
    pause_buttons = []
    for index in range(3):
        row = ttk.Frame(frame)
        row.pack(fill='x', pady=5)
        ttk.Label(row, text=f'{index + 1}.', width=3).pack(side='left')
        remembered = saved.get('routing_rows', [])
        row_saved = remembered[index] if index < len(remembered) else {}
        file_var = tk.StringVar(value=row_saved.get('file', state['files'][index] if index < len(state['files']) else ''))
        display_name = tk.StringVar(value=Path(file_var.get()).name if file_var.get() else 'Choose an audio file')
        file_var.trace_add('write', lambda *args, source=file_var, target=display_name:
                          target.set(Path(source.get()).name if source.get() else 'Choose an audio file'))
        file_entry = ttk.Entry(row, textvariable=display_name, state='readonly', width=20)
        file_entry.pack(side='left', fill='x', expand=True)

        def choose_file(variable=file_var, selected=index):
            path = filedialog.askopenfilename(initialdir=ROOT / 'audio', filetypes=[('Audio', '*.wav *.mp3 *.flac *.ogg *.mp4 *.m4a *.aac'), ('All files', '*.*')])
            if path:
                variable.set(path)
                routing_changed('file', selected)

        ttk.Button(row, text='Choose file', command=choose_file).pack(side='left', padx=5)
        output = ttk.Combobox(row, state='readonly', width=30)
        output.pack(side='left', fill='x', expand=True)
        previous = saved.get('speakers', ['Speakers (USB2.0 Device)'])
        output.set(row_saved.get('output', previous[index] if index < len(previous) else 'Off'))
        assignments.append((file_var, output))
        pause = ttk.Button(row, text='Pause', width=8, command=lambda selected=index: toggle_pause(selected))
        pause.pack(side='left', padx=(5, 0))
        pause_buttons.append(pause)
        output.bind('<<ComboboxSelected>>', lambda event, selected=index: routing_changed('output', selected))

    def refresh_pause_buttons():
        for (_, output), button in zip(assignments, pause_buttons):
            button.configure(text='Resume' if output.get() in state['paused_speakers'] else 'Pause',
                             state='disabled' if output.get() == 'Off' else 'normal')

    def toggle_pause(selected):
        name = assignments[selected][1].get()
        if name == 'Off':
            return
        if name in state['paused_speakers']:
            state['paused_speakers'].remove(name)
        else:
            state['paused_speakers'].add(name)
        refresh_pause_buttons()

    refresh_pause_buttons()

    def row_values():
        return [dict(file=file.get(), output=output.get()) for file, output in assignments]

    state['route_snapshot'] = row_values()
    route_status = tk.StringVar(value='Assignments update live. Set every speaker to Off for recording only.')
    ttk.Label(frame, textvariable=route_status, wraplength=800, style='Hint.TLabel').pack(anchor='w', pady=(4, 8))

    def restore_rows(rows):
        for (file, output), row in zip(assignments, rows):
            file.set(row['file'])
            output.set(row['output'])
        state['route_snapshot'] = row_values()
        refresh_pause_buttons()
        refresh_editor()

    def read_config():
        enabled = [(file.get(), output.get()) for file, output in assignments if output.get() != 'Off']
        return dict(microphone=mic.get(), speakers=[output for _, output in enabled],
                    files=[file for file, _ in enabled], button_vk=state['vk'], volume=saved.get('volume', .5),
                    echo_amount=saved.get('echo_amount', .35), echo_delay_ms=saved.get('echo_delay_ms', 350), routing_rows=row_values(),
                    speaker_settings={name: dict(values) for name, values in state['speaker_settings'].items()},
                    loop_delay_seconds=saved.get('loop_delay_seconds', 0), paused_speakers=sorted(state['paused_speakers']))

    def routing_changed(field, selected):
        previous = state['route_snapshot']
        rows = row_values()
        value = rows[selected][field]
        # Swap an already-used assignment instead of ever creating a duplicate route.
        for index, row in enumerate(rows):
            same = (os.path.normcase(str(Path(row[field]).resolve())) == os.path.normcase(str(Path(value).resolve()))
                    if field == 'file' else row[field] == value)
            if index != selected and value not in ('', 'Off') and same:
                variable, output = assignments[index]
                (variable if field == 'file' else output).set(previous[selected][field])
        try:
            proposed = read_config()
            # Permit configuring routes before the button has been learned.
            validate_config(dict(proposed, button_vk=proposed['button_vk'] or 13))
        except Exception as exc:
            restore_rows(previous)
            route_status.set(f'Assignment unchanged: {exc}')
            return
        state['route_snapshot'] = row_values()
        refresh_pause_buttons()
        refresh_editor()
        session = state['engine']
        if not session:
            route_status.set('Assignments ready. Press Start exhibit.')
            return
        if state['route_job']:
            restore_rows(previous)
            route_status.set('Please wait for the current file change to finish loading.')
            return
        # Decode files off the window thread so hold/release detection keeps running.
        future = Future()
        state['route_job'] = (future, proposed, session, previous)
        route_status.set('Loading new assignment… current playback and recording continue.')

        def decode():
            try:
                future.set_result(load_playlist(proposed['files'], separate=True, normalize=True))
            except Exception as exc:
                future.set_exception(exc)

        threading.Thread(target=decode, daemon=True).start()

    def refresh():
        if state['engine']:
            return
        sd._terminate()
        sd._initialize()
        inputs = [d['name'] for _, d in devices('input')]
        preferred = saved.get('microphone')
        mic['values'] = inputs + ([preferred] if preferred and preferred not in inputs else [])
        mic.set(preferred or next((n for n in inputs if 'CMTECK' in n), inputs[0] if inputs else ''))
        available = [d['name'] for _, d in devices('output')]
        for _, output in assignments:
            # Retain missing-device selections so they are never silently rerouted.
            output['values'] = ['Off'] + available + ([output.get()] if output.get() not in available + ['Off'] else [])

    ttk.Button(recording_tab, text='Refresh connected devices', command=refresh).pack(anchor='w', pady=(0, 16))
    ttk.Separator(frame).pack(fill='x', pady=(8, 16))
    ttk.Label(frame, text='2. Adjust one speaker', style='Section.TLabel').pack(anchor='w')
    ttk.Label(frame, text='Choose the speaker to edit. Its sound changes live; other speakers keep their settings.',
              style='Hint.TLabel').pack(anchor='w', pady=(4, 8))
    speaker_selector = ttk.Combobox(frame, state='readonly', name='speaker_selector')
    speaker_selector.pack(fill='x', pady=(0, 8))
    selected_hint = tk.StringVar()
    ttk.Label(frame, textvariable=selected_hint, style='Hint.TLabel').pack(anchor='w', pady=(0, 8))
    volume = tk.DoubleVar()
    echo_amount = tk.DoubleVar()
    echo_delay = tk.DoubleVar()
    loop_delay = tk.DoubleVar()
    echo_delay_label = tk.StringVar()
    loop_label = tk.StringVar()
    volume_label = tk.StringVar()
    echo_label = tk.StringVar()
    ttk.Label(frame, textvariable=volume_label).pack(anchor='w')
    volume_slider = click_scale(frame, from_=0, to=1, variable=volume, name='speaker_volume')
    volume_slider.pack(fill='x', pady=(0, 8))
    ttk.Label(frame, textvariable=echo_label).pack(anchor='w')
    echo_slider = click_scale(frame, from_=0, to=.75, variable=echo_amount, name='speaker_echo')
    echo_slider.pack(fill='x', pady=(0, 8))
    ttk.Label(frame, textvariable=echo_delay_label).pack(anchor='w')
    echo_delay_slider = click_scale(frame, from_=50, to=1500, variable=echo_delay, name='echo_delay')
    echo_delay_slider.pack(fill='x', pady=(0, 8))
    ttk.Label(frame, textvariable=loop_label).pack(anchor='w')
    loop_slider = click_scale(frame, from_=0, to=30, variable=loop_delay, name='speaker_loop_delay')
    loop_slider.pack(fill='x', pady=(0, 8))

    def selected_device():
        index = speaker_selector.current()
        return assignments[index][1].get() if index >= 0 else 'Off'

    def sound_changed(*unused):
        volume_label.set(f'Volume   {volume.get():.0%}')
        echo_label.set(f'Echo   {echo_amount.get():.0%}   ·   0% turns echo off')
        echo_delay_label.set(f'Echo delay   {echo_delay.get():.0f} ms')
        loop_label.set(f'Loop delay   {loop_delay.get():.1f} seconds - silence before this speaker repeats')
        name = state.get('editing_device', 'Off')
        if state['loading_controls'] or name == 'Off':
            return
        state['speaker_settings'][name] = dict(volume=volume.get(), echo_amount=echo_amount.get(),
                                             echo_delay_ms=echo_delay.get(), loop_delay_seconds=loop_delay.get())

    for variable in (volume, echo_amount, echo_delay, loop_delay):
        variable.trace_add('write', sound_changed)

    def refresh_editor(event=None):
        index = max(0, speaker_selector.current())
        labels = [f'Speaker {i + 1} — {output.get()}' for i, (_, output) in enumerate(assignments)]
        speaker_selector['values'] = labels
        speaker_selector.current(index)
        name = selected_device()
        settings = speaker_values(dict(saved, speaker_settings=state['speaker_settings']), name)
        state['loading_controls'] = True
        try:
            state['editing_device'] = name
            volume.set(settings['volume'])
            echo_amount.set(settings['echo_amount'])
            echo_delay.set(settings['echo_delay_ms'])
            loop_delay.set(settings['loop_delay_seconds'])
        finally:
            state['loading_controls'] = False
        enabled = 'disabled' if name == 'Off' else 'normal'
        for control in (volume_slider, echo_slider, echo_delay_slider, loop_slider):
            control.configure(state=enabled)
        selected_hint.set('This row is Off. Assign a speaker above to adjust its sound.' if name == 'Off'
                          else f'Playing: {Path(assignments[index][0].get()).name or "No file selected"}')

    speaker_selector['values'] = [f'Speaker {i+1}' for i in range(3)]
    speaker_selector.current(next((i for i, (_, output) in enumerate(assignments) if output.get() != 'Off'), 0))
    speaker_selector.bind('<<ComboboxSelected>>', refresh_editor)
    refresh_editor()
    button_text = tk.StringVar(value=f'Button key: {state["vk"] or "not configured"}')
    ttk.Label(recording_tab, text='Record button', style='Section.TLabel').pack(anchor='w', pady=(8, 8))
    ttk.Label(recording_tab, textvariable=button_text).pack(anchor='w', pady=(0, 8))

    def learn():
        if state['engine']:
            messagebox.showinfo('Stop first', 'Stop the exhibit before detecting the button.')
            return
        state['learning'] = True
        window.focus_set()
        button_text.set('Release all keys. In 2 seconds, hold the physical button…')
        window.after(2000, lambda: scan(time.monotonic() + 20))

    def scan(deadline):
        if not state['learning']:
            return
        keys = [k for k in range(1, 255) if k not in (1, 2, 4, 5, 6, 16, 17, 18)
                and ctypes.windll.user32.GetAsyncKeyState(k) & 0x8000]
        if keys:
            state['vk'] = keys[0]
            state['learning'] = False
            button_text.set(f'Button detected: Windows key code {keys[0]}. Release it now.')
        elif time.monotonic() >= deadline:
            state['learning'] = False
            button_text.set('No keyboard button detected. The button may need a different driver/protocol.')
        else:
            window.after(10, lambda: scan(deadline))

    ttk.Button(recording_tab, text='Detect my button', command=learn).pack(anchor='w')
    ttk.Separator(recording_tab).pack(fill='x', pady=24)
    ttk.Label(recording_tab, text='Saved recordings', style='Section.TLabel').pack(anchor='w')
    ttk.Label(recording_tab, text='Each hold saves a separate WAV. Playback effects do not change recordings.',
              style='Hint.TLabel').pack(anchor='w', pady=8)
    ttk.Label(recording_tab, text=str(ROOT / 'recordings'), wraplength=760).pack(anchor='w')
    status = tk.StringVar(value='Stopped — choose your speakers, then start the exhibit.')
    ttk.Separator(footer).pack(fill='x', pady=(0, 12))
    ttk.Label(footer, textvariable=status, wraplength=870).pack(anchor='w', pady=(0, 12))

    def stop():
        state['route_job'] = None
        engine = state['engine']
        state['engine'] = None
        if engine:
            try:
                engine.stop()
                save_config(engine.config)
            except Exception as exc:
                logging.exception('Stop failed')
                status.set(f'Stopped with a recording error: {exc}')
                return
        status.set('Stopped. Recordings are in ' + str(ROOT / 'recordings'))

    def start():
        if state['engine']:
            return
        try:
            if state['learning'] or state['vk'] is None:
                raise ValueError('Detect your button first.')
            config = read_config()
            save_config(config)
            engine = Session(config)
            status.set('Loading audio…')
            window.update_idletasks()
            state['engine'] = engine
            engine.tick()
            window.focus_set()
        except Exception as exc:
            logging.exception('Start failed')
            stop()
            status.set(f'Could not start: {exc}')
            messagebox.showerror('Could not start', str(exc))

    controls = ttk.Frame(footer)
    controls.pack(fill='x')
    ttk.Button(controls, text='Start exhibit', command=start).pack(side='left')
    ttk.Button(controls, text='Stop and save', command=stop).pack(side='left', padx=8)
    ttk.Button(controls, text='Minimize to background', command=window.iconify).pack(side='left')

    def tick():
        try:
            stop_file = ROOT / 'stop.flag'
            if stop_file.exists():
                stop_file.unlink()
                stop()
            engine = state['engine']
            if engine:
                engine.config['speaker_settings'] = {name: dict(values) for name, values in state['speaker_settings'].items()}
                engine.config['paused_speakers'] = sorted(state['paused_speakers'])
                job = state['route_job']
                if job and job[0].done():
                    state['route_job'] = None
                    future, proposed, session, previous = job
                    if session is engine:
                        try:
                            session.apply_routes(proposed, future.result())
                            route_status.set('Live assignments updated.')
                        except Exception as exc:
                            logging.exception('Live assignment rejected; previous routes retained')
                            restore_rows(previous)
                            route_status.set(f'Assignment unchanged: {exc}')
                engine.tick()
                status.set(engine.status)
        except Exception as exc:
            logging.exception('Exhibit interrupted')
            stop()
            status.set(f'Exhibit stopped: {exc}')
        finally:
            window.after(10, tick)

    def close():
        stop()
        try:
            save_config(read_config())
        except (ValueError, OSError):
            logging.exception('Incomplete setup was not saved on close; previous settings retained')
        window.destroy()

    def callback_error(error_type, error, traceback):
        logging.error('Window action failed', exc_info=(error_type, error, traceback))
        stop()
        status.set(f'Action failed: {error}. Correct the problem, then start again.')

    window.report_callback_exception = callback_error
    try:
        refresh()
    except Exception as exc:
        logging.exception('Device discovery failed')
        status.set(f'Could not list devices: {exc}. Connect them and click Refresh.')
    tabs.select(playback_page)
    window.protocol('WM_DELETE_WINDOW', close)
    tick()
    window.mainloop()


def main():
    (ROOT / 'logs').mkdir(exist_ok=True)
    handler = RotatingFileHandler(ROOT / 'logs' / 'exhibit.log', maxBytes=2_000_000, backupCount=3)
    logging.basicConfig(level=logging.INFO, handlers=[handler], format='%(asctime)s %(levelname)s %(message)s')
    parser = argparse.ArgumentParser()
    parser.add_argument('--devices', action='store_true')
    parser.add_argument('--headless', action='store_true', help='Run saved configuration; stop with Stop exhibit.cmd')
    args = parser.parse_args()
    if args.devices:
        for kind in ('input', 'output'):
            for i, d in devices(kind):
                print(f'{kind}: {i}: {d["name"]} ({d["max_" + kind + "_channels"]} channels)')
        return
    # Prevent two exhibit processes recording or playing at once.
    kernel = ctypes.windll.kernel32
    kernel.CreateMutexW.restype = ctypes.c_void_p
    mutex = kernel.CreateMutexW(None, False, 'Local\\ExhibitAudioController')
    already_running = kernel.GetLastError() == 183
    if not mutex:
        raise ctypes.WinError()
    if already_running:
        # A duplicate must release its handle before any dialog, so it cannot keep
        # the mutex alive after the actual controller has exited.
        kernel.CloseHandle(ctypes.c_void_p(mutex))
        show_existing_controller()
        return
    try:
        if args.headless:
            stop_file = ROOT / 'stop.flag'
            stop_file.unlink(missing_ok=True)
            engine = Session(validate_config(json.loads(CONFIG.read_text(encoding='utf-8'))))
            try:
                while not stop_file.exists():
                    engine.tick()
                    time.sleep(0.01)
            finally:
                engine.stop()
                stop_file.unlink(missing_ok=True)
        else:
            gui()
    finally:
        kernel.CloseHandle(ctypes.c_void_p(mutex))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        logging.exception('Fatal error')
        ctypes.windll.user32.MessageBoxW(0, str(exc), 'Exhibit audio controller', 0x10)
        raise
