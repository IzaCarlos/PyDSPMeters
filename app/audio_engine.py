"""
Audio Engine: Captures audio from input devices and distributes it to modules.
Uses sounddevice for low-latency capture with a thread-safe queue bridge to Qt.
"""

import sys
import queue
import logging
import time
import numpy as np
import sounddevice as sd
from app.dsp import accel as dsp_accel
from app.utils import perf_stats
from PySide6.QtCore import QObject, Signal, QTimer, Slot


class AudioEngine(QObject):
    """
    Real-time audio capture engine.

    Captures stereo audio via sounddevice and emits Qt signals
    with new data blocks for consumption by visualization modules.
    Also maintains a circular buffer for modules that need history (e.g. LUFS).
    """

    # Emits (np.ndarray) of shape (block_size, channels), float32
    data_ready = Signal(np.ndarray)
    # Emits when the stream starts/stops
    stream_started = Signal()
    stream_stopped = Signal()
    # Emits (str) on error
    error_occurred = Signal(str)

    def __init__(self, sample_rate: int = 44100, block_size: int = 1024,
                 buffer_seconds: float = 10.0, channels: int = 2, parent=None):
        super().__init__(parent)
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.channels = channels
        self._stream = None
        self._device = None
        self.gain_multiplier = 1.0

        # Thread-safe queue for bridging callback → Qt main thread
        self._queue = queue.Queue(maxsize=200)

        # Circular history buffer
        buf_len = int(sample_rate * buffer_seconds)
        self.buffer = np.zeros((buf_len, self.channels), dtype=np.float32)
        self._write_pos = 0
        self._total_written = 0

        # Timer to drain the queue on the main thread
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(16)  # ~60 Hz polling
        self._poll_timer.timeout.connect(self._drain_queue)

        # Python 3.14 SoundDevice Workaround
        # In 3.14, SoundDevice/CFFI can return NoneType instead of None after silence,
        # causing a soft-crash. We play silent audio in the background to prevent this.
        self._is_py314 = sys.version_info.major == 3 and sys.version_info.minor == 14
        self._silence_counter = 0
        self._fallback_stream = None

    # ── Device Enumeration ──────────────────────────────────────────────────

    @staticmethod
    def list_devices() -> list[dict]:
        """Return list of available input devices."""
        devices = sd.query_devices()
        inputs = []
        for i, d in enumerate(devices):
            if d["max_input_channels"] > 0:
                host_api_name = sd.query_hostapis(d["hostapi"])["name"]
                inputs.append({
                    "index": i,
                    "name": d["name"],
                    "full_id": f"{d['name']} ({host_api_name})",
                    "channels": d["max_input_channels"],
                    "sample_rate": d["default_samplerate"],
                    "hostapi": host_api_name,
                })
        return inputs

    @staticmethod
    def get_default_device() -> int | None:
        """Get the default input device index, preferring low-latency WASAPI on Windows."""
        try:
            def_idx = sd.default.device[0]
            if def_idx < 0:
                return None
            if sys.platform == "win32":
                info = sd.query_devices(def_idx)
                host_name = sd.query_hostapis(info["hostapi"])["name"]
                if "MME" in host_name:
                    base_name = info["name"].split("(")[0].strip().lower()
                    for i, d in enumerate(sd.query_devices()):
                        if d["max_input_channels"] > 0:
                            api = sd.query_hostapis(d["hostapi"])["name"]
                            if "WASAPI" in api and d["name"].split("(")[0].strip().lower() == base_name:
                                return i
            return def_idx
        except Exception:
            return None

    # ── Stream Control ──────────────────────────────────────────────────────

    def start(self, device_index: int | None = None, channels: int | None = None):
        """Start capturing audio from the given device."""
        logging.info(f"Starting AudioEngine: device={device_index}, channels={channels}")
        self.stop()
        self._device = device_index
        old_ch = self.channels
        
        # Get device info to validate parameters
        try:
            if device_index is None:
                device_index = self.get_default_device()
                if device_index is None:
                    device_index = sd.default.device[0]
            
            info = sd.query_devices(device_index, "input")
            max_ch = info.get("max_input_channels", 2)
            dev_sr = info.get("default_samplerate", 44100)
            host_api = sd.query_hostapis(info["hostapi"])["name"]
            
            logging.info(f"Targeting device: '{info['name']}' | HostAPI: {host_api} | Max Channels: {max_ch}")
            
            if channels is not None:
                self.channels = min(channels, max_ch, 2)
            else:
                self.channels = min(self.channels, max_ch, 2)

            if self.channels != old_ch:
                buf_len = len(self.buffer)
                self.buffer = np.zeros((buf_len, self.channels), dtype=np.float32)
                self._write_pos = 0
                self._total_written = 0
                
            # If our current sample rate is very different from device default, 
            # and we haven't explicitly set it, maybe try to match?
            # For now, we'll try our target rate first, then fall back.
            target_rates = [self.sample_rate, int(dev_sr)]
            if int(dev_sr) not in target_rates:
                target_rates.append(int(dev_sr))
        except Exception as e:
            self.error_occurred.emit(f"Device query error: {e}")
            return

        last_err = None
        for sr in target_rates:
            try:
                # Try preferred channels (Mono/Stereo) first
                self._stream = sd.InputStream(
                    device=device_index,
                    channels=self.channels,
                    samplerate=sr,
                    blocksize=self.block_size,
                    dtype="float32",
                    callback=self._audio_callback,
                    latency="low",
                )
                self._stream.start()
                self.sample_rate = sr
                self._poll_timer.start()
                logging.info(f"Stream started successfully at {sr}Hz, {self.channels}ch")
                self.stream_started.emit()
                return
            except Exception as e:
                # Fallback: Some professional drivers (ASIO/MME) REFUSE to open 
                # unless you request their exact native channel count.
                # If 2 channels failed, try opening with the device's max_ch.
                # Our DSP pipeline will automatically truncate this to 2 later.
                try:
                    self._stream = sd.InputStream(
                        device=device_index,
                        channels=max_ch,
                        samplerate=sr,
                        blocksize=self.block_size,
                        dtype="float32",
                        callback=self._audio_callback,
                        latency="low",
                    )
                    self._stream.start()
                    self.sample_rate = sr
                    self._poll_timer.start()
                    logging.info(f"Stream started with fallback (native channels): {max_ch}ch at {sr}Hz")
                    self.stream_started.emit()
                    return
                except:
                    last_err = e
                    continue

        # Last resort: Try absolute minimum (Mono) at device sample rate
        try:
            self.channels = 1
            # Recreate buffer
            buf_len = len(self.buffer)
            self.buffer = np.zeros((buf_len, self.channels), dtype=np.float32)
            self._write_pos = 0
            self._total_written = 0
            
            self._stream = sd.InputStream(
                device=device_index,
                channels=1,
                samplerate=int(dev_sr),
                blocksize=self.block_size,
                dtype="float32",
                callback=self._audio_callback_mono,
                latency="low",
            )
            self._stream.start()
            self.sample_rate = int(dev_sr)
            self._poll_timer.start()
            self.stream_started.emit()
        except Exception as e2:
            err_msg = f"Audio error: {last_err or e2}"
            logging.error(err_msg)
            self.error_occurred.emit(err_msg)

    def stop(self):
        """Stop the audio stream (non-blocking)."""
        self._poll_timer.stop()
        if self._stream is not None:
            try:
                # Use abort() instead of stop() or close() to prevent hanging 
                # the main thread during application exit.
                self._stream.abort()
            except Exception:
                pass
            self._stream = None

        # Clean up fallback stream if active
        if self._fallback_stream is not None:
            try:
                self._fallback_stream.abort()
                self._fallback_stream.close()
            except:
                pass
            self._fallback_stream = None
        self._silence_counter = 0

        self.stream_stopped.emit()

    def get_status_list(self) -> list[str]:
        """Return a list of status lines for the current stream."""
        if not self.is_running:
            return ["Status: Stopped"]
        try:
            info = sd.query_devices(self._device, "input")
            name = info["name"]
            if len(name) > 35:
                name = name[:32] + "..."
            api = sd.query_hostapis(info["hostapi"])["name"]
            return [
                f"Device: {name}",
                f"Driver: {api}",
                f"Format: {self.sample_rate}Hz, {self.channels}ch"
            ]
        except:
            return ["Status: Active (Unknown Device)"]

    @property
    def is_running(self) -> bool:
        return self._stream is not None and self._stream.active

    # ── Callbacks (run on audio thread) ─────────────────────────────────────

    def _audio_callback(self, indata, frames, time_info, status):
        """Sounddevice callback for stereo input."""
        try:
            self._queue.put_nowait(indata.copy())
        except queue.Full:
            pass  # Drop oldest if queue full

    def _audio_callback_mono(self, indata, frames, time_info, status):
        """Sounddevice callback for mono input — duplicated to target channels."""
        multi = np.tile(indata[:, 0:1], (1, self.channels))
        try:
            self._queue.put_nowait(multi)
        except queue.Full:
            pass

    # ── Queue Drain (runs on Qt main thread) ────────────────────────────────

    @property
    def gain_multiplier(self):
        return self._gain_multiplier

    @gain_multiplier.setter
    def gain_multiplier(self, value):
        self._gain_multiplier = float(value)

    @Slot()
    def _drain_queue(self):
        """Pull all available audio blocks from the queue and emit signals."""
        started = time.perf_counter()
        block_count = 0
        sample_count = 0
        try:
            blocks = []
            while True:
                try:
                    blocks.append(self._queue.get_nowait())
                except queue.Empty:
                    break

            block_count = len(blocks)
            if not blocks:
                if self._is_py314:
                    # On 3.14, if we get no blocks, we treat it as potential silence
                    # to trigger the keep-alive output stream if it lasts too long.
                    self._handle_silence_fallback(is_silent=True, frames=self.block_size)
                return

            # Accelerated gain application and block concatenation
            combined = dsp_accel.apply_gain_and_concat(blocks, self._gain_multiplier, self.channels)
            n = len(combined)
            sample_count = n

            # Python 3.14 Workaround: Monitor for silence
            if self._is_py314:
                # Check if the combined block is effectively silent (RMS-ish)
                is_silent = np.max(np.abs(combined)) < 1e-5
                self._handle_silence_fallback(is_silent, n)
            buf_len = len(self.buffer)

            # Update circular history buffer
            if n >= buf_len:
                self.buffer[:] = combined[-buf_len:]
                self._write_pos = 0
            else:
                end_pos = self._write_pos + n
                if end_pos <= buf_len:
                    self.buffer[self._write_pos:end_pos] = combined
                else:
                    rem = end_pos - buf_len
                    first_part = n - rem
                    self.buffer[self._write_pos:] = combined[:first_part]
                    self.buffer[:rem] = combined[first_part:]
                self._write_pos = (self._write_pos + n) % buf_len

            self._total_written += n
            self.data_ready.emit(combined)
        finally:
            perf_stats.record_timing("audio.drain_queue", time.perf_counter() - started)
            perf_stats.record_interval("audio.drain_interval")
            perf_stats.record_count("audio.blocks_per_drain", block_count)
            perf_stats.record_count("audio.samples_per_drain", sample_count)

    # ── Buffer Access ───────────────────────────────────────────────────────

    def get_history(self, seconds: float) -> np.ndarray:
        """
        Get the last N seconds of audio from the circular buffer.

        Returns:
            Array of shape (n_samples, channels), float32.
        """
        n_samples = min(int(seconds * self.sample_rate), len(self.buffer))
        available = min(n_samples, self._total_written)
        if available == 0:
            return np.zeros((1, self.channels), dtype=np.float32)

        end = self._write_pos
        if end >= available:
            return self.buffer[end - available:end].copy()
        else:
            return np.concatenate([
                self.buffer[-(available - end):],
                self.buffer[:end],
            ])

    # ── Python 3.14 Workaround Helpers ─────────────────────────────────────

    def _handle_silence_fallback(self, is_silent: bool, frames: int):
        """
        Maintains a silent output stream on Python 3.14 to prevent SoundDevice
        from hitting a CFFI bug that causes soft-crashes after long silence.
        """
        if is_silent:
            self._silence_counter += frames
            # If silent for more than 1.5 seconds, ensure fallback is running
            if self._silence_counter > int(self.sample_rate * 1.5):
                if self._fallback_stream is None:
                    try:
                        # Start a dummy output stream. This keeps the PortAudio
                        # backend active and prevents the 3.14 NoneType crash.
                        self._fallback_stream = sd.OutputStream(
                            samplerate=int(self.sample_rate),
                            channels=1,
                            callback=lambda outdata, f, t, s: outdata.fill(0)
                        )
                        self._fallback_stream.start()
                    except:
                        pass
        else:
            self._silence_counter = 0
            if self._fallback_stream is not None:
                try:
                    self._fallback_stream.abort()
                    self._fallback_stream.close()
                except:
                    pass
                self._fallback_stream = None
