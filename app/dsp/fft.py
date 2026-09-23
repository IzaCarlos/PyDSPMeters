"""
FFT processing utilities for spectrum analysis.
Supports multiple FFT sizes, window functions, and frequency scaling (Mel, Log, Linear).
"""

import numpy as np
import app.dsp.accel as accel


_WINDOW_CACHE = {}


def create_window(name: str, size: int) -> np.ndarray:
    """Generate periodic window (fftbins=True) without external dependencies."""
    if size <= 1:
        return np.ones(size, dtype=np.float32)
    n = np.arange(size, dtype=np.float64) / float(size)
    key = (name or "hann").lower().replace("-", "").replace("_", "")
    if key in ("hann", "hanning"):
        w = 0.5 - 0.5 * np.cos(2.0 * np.pi * n)
    elif key == "hamming":
        w = 0.54 - 0.46 * np.cos(2.0 * np.pi * n)
    elif key == "blackman":
        w = 0.42 - 0.5 * np.cos(2.0 * np.pi * n) + 0.08 * np.cos(4.0 * np.pi * n)
    elif key in ("blackmanharris", "blackman_harris"):
        w = (0.35875
             - 0.48829 * np.cos(2.0 * np.pi * n)
             + 0.14128 * np.cos(4.0 * np.pi * n)
             - 0.01168 * np.cos(6.0 * np.pi * n))
    elif key == "flattop":
        w = (0.21557895
             - 0.41663158 * np.cos(2.0 * np.pi * n)
             + 0.277263158 * np.cos(4.0 * np.pi * n)
             - 0.083578947 * np.cos(6.0 * np.pi * n)
             + 0.006947368 * np.cos(8.0 * np.pi * n))
    elif key in ("rect", "rectangular", "boxcar"):
        w = np.ones(size, dtype=np.float64)
    else:
        w = 0.5 - 0.5 * np.cos(2.0 * np.pi * n)
    return w.astype(np.float32)


def compute_fft(data: np.ndarray, fft_size: int = 4096,
                window: str = "hann") -> np.ndarray:
    """
    Compute the magnitude spectrum of audio data.
    Uses cached windows for performance.
    """
    cache_key = (window, fft_size)
    if cache_key in _WINDOW_CACHE:
        win = _WINDOW_CACHE[cache_key]
    else:
        win = create_window(window, fft_size)
        _WINDOW_CACHE[cache_key] = win

    return accel.compute_fft(data, win, fft_size)


def fft_frequencies(fft_size: int, sample_rate: float) -> np.ndarray:
    """Return the frequency array for a given FFT size."""
    return np.fft.rfftfreq(fft_size, d=1.0 / sample_rate)



def hz_to_mel(hz: np.ndarray) -> np.ndarray:
    """Convert Hz to Mel scale."""
    return 2595.0 * np.log10(1.0 + hz / 700.0)


def mel_to_hz(mel: np.ndarray) -> np.ndarray:
    """Convert Mel back to Hz."""
    return 700.0 * (10.0 ** (mel / 2595.0) - 1.0)


def map_frequencies_to_pixels(freqs: np.ndarray, width: int,
                              scale: str = "logarithmic",
                              f_min: float = 20.0,
                              f_max: float = 20000.0) -> np.ndarray:
    """
    Map frequency bins to pixel x-positions using the given scale.

    Args:
        freqs: Array of frequency values in Hz.
        width: Pixel width of the display.
        scale: One of 'linear', 'logarithmic', 'mel'.
        f_min: Minimum displayed frequency.
        f_max: Maximum displayed frequency.

    Returns:
        Array of pixel positions (float).
    """
    freqs = np.clip(freqs, f_min, f_max)

    if scale == "linear":
        positions = (freqs - f_min) / (f_max - f_min) * width

    elif scale == "logarithmic":
        log_min = np.log10(max(f_min, 1.0))
        log_max = np.log10(f_max)
        positions = (np.log10(np.clip(freqs, f_min, None)) - log_min) / (log_max - log_min) * width

    elif scale == "mel":
        mel_min = hz_to_mel(np.array([f_min]))[0]
        mel_max = hz_to_mel(np.array([f_max]))[0]
        mel_vals = hz_to_mel(freqs)
        positions = (mel_vals - mel_min) / (mel_max - mel_min) * width

    else:
        positions = (freqs - f_min) / (f_max - f_min) * width

    return positions


def detect_peak_frequency(magnitude_db: np.ndarray, freqs: np.ndarray,
                          f_min: float = 20.0,
                          f_max: float = 20000.0) -> tuple[float, float]:
    """
    Find the loudest frequency in the spectrum.

    Returns:
        (frequency_hz, magnitude_db)
    """
    mask = (freqs >= f_min) & (freqs <= f_max)
    if not np.any(mask):
        return 0.0, -120.0
    filtered_mag = magnitude_db[mask]
    filtered_freq = freqs[mask]
    idx = np.argmax(filtered_mag)
    
    # Quadratic interpolation for better accuracy
    if 0 < idx < len(filtered_mag) - 1:
        y1, y2, y3 = filtered_mag[idx-1], filtered_mag[idx], filtered_mag[idx+1]
        denom = (y1 - 2*y2 + y3)
        if abs(denom) > 1e-6:
            p = 0.5 * (y1 - y3) / denom
            peak_f = filtered_freq[idx] + p * (filtered_freq[idx] - filtered_freq[idx-1])
            peak_db = y2 - 0.25 * (y1 - y3) * p
            return float(peak_f), float(peak_db)
            
    return float(filtered_freq[idx]), float(filtered_mag[idx])


def hz_to_note_name(hz: float) -> str:
    """Convert a frequency in Hz to the nearest musical note name."""
    if hz <= 0:
        return "---"
    note_names = ["C", "C#", "D", "D#", "E", "F",
                  "F#", "G", "G#", "A", "A#", "B"]
    midi = 69 + 12 * np.log2(hz / 440.0)
    midi_rounded = int(round(midi))
    note = note_names[midi_rounded % 12]
    octave = (midi_rounded // 12) - 1
    cents = int(round((midi - midi_rounded) * 100))
    sign = "+" if cents >= 0 else ""
    return f"{note}{octave} {sign}{cents}c"


def apply_tilt(magnitude_db: np.ndarray, freqs: np.ndarray,
               tilt_db: float, pivot_hz: float = 1000.0) -> np.ndarray:
    """
    Apply a spectral tilt in dB/octave around a pivot frequency.
    Positive tilts boost highs, negative tilts boost lows.
    """
    return accel.apply_tilt(magnitude_db, freqs, tilt_db, pivot_hz)
