"""
DSP Accelerator: Python wrapper with graceful fallback.

Imports the Rust-compiled `dsp_accel` module when available,
otherwise provides pure-Python/NumPy fallback implementations
so the application runs identically (just slower) without the
compiled native extension.
"""

import numpy as np
import logging


_HAS_NATIVE = False
try:
    import dsp_accel as _native
    _HAS_NATIVE = True
    logging.info("DSP Accelerator: Native Rust extension loaded.")
except ImportError:
    _native = None
    logging.warning("DSP Accelerator: Native extension NOT found. Using pure-Python/NumPy fallback.")


def is_accelerated() -> bool:
    """Returns True if the Rust DSP accelerator is loaded."""
    return _HAS_NATIVE



def build_colormap(stops, n=256):
    """Build a 256-entry RGB LUT from heatmap stops.
    
    stops: list of (position_float, "#hexcolor") tuples
    Returns: (256, 3) uint8 numpy array
    """
    from PySide6.QtGui import QColor
    
    # Convert hex stops to (pos, r, g, b) tuples for Rust
    parsed = []
    for pos, color_str in stops:
        c = QColor(color_str)
        parsed.append((float(pos), c.red(), c.green(), c.blue()))
    
    if _HAS_NATIVE:
        return _native.build_colormap(parsed)
    
    # Pure Python fallback
    lut = np.zeros((n, 3), dtype=np.uint8)
    for i in range(n):
        t = i / (n - 1)
        for j in range(len(parsed) - 1):
            t0, r0, g0, b0 = parsed[j]
            t1, r1, g1, b1 = parsed[j + 1]
            if t0 <= t <= t1:
                frac = (t - t0) / (t1 - t0) if t1 > t0 else 0
                lut[i] = [
                    int(r0 + (r1 - r0) * frac),
                    int(g0 + (g1 - g0) * frac),
                    int(b0 + (b1 - b0) * frac),
                ]
                break
    return lut


def apply_colormap(history, lut, buffer_data, start_col, end_col, history_len):
    """Apply LUT to spectrogram history columns → buffer_data.
    
    history:     (history_len, display_h) f32
    lut:         (256, 3) u8
    buffer_data: (display_h, history_len, 3) u8 — modified in-place
    """
    if _HAS_NATIVE:
        _native.apply_colormap(history, lut, buffer_data, start_col, end_col, history_len)
        return
    
    # Pure Python fallback
    display_h = buffer_data.shape[0]
    for raw_idx in range(start_col, end_col):
        col = raw_idx % history_len
        indices = np.clip((history[col] * 255).astype(np.int32), 0, 255)
        rgb_col = lut[indices]
        buffer_data[:, col] = rgb_col[::-1]



def generate_spectrogram_column(norm, px_int, n_bins, display_h):
    """Generate a spectrogram column from normalized FFT data.
    
    Returns: (display_h,) f32 array
    """
    if _HAS_NATIVE:
        return _native.generate_spectrogram_column(
            norm.astype(np.float32), px_int.astype(np.int32), n_bins, display_h
        )
    
    # Pure Python fallback
    column = np.zeros(display_h, dtype=np.float32)
    np.maximum.at(column, px_int[:n_bins], norm[:n_bins])
    
    nonzero = np.where(column > 0)[0]
    if len(nonzero) > 1:
        full_idx = np.arange(nonzero[0], nonzero[-1] + 1)
        interp_vals = np.interp(full_idx, nonzero, column[nonzero])
        column[full_idx] = np.maximum(column[full_idx], interp_vals)
    
    return column



def circular_buffer_write(buffer, raw_buffer, filtered, raw_data, buf_pos):
    """Write filtered + raw data into circular buffers.
    
    Returns: new buf_pos
    """
    if _HAS_NATIVE:
        return _native.circular_buffer_write(buffer, raw_buffer, filtered, raw_data, buf_pos)
    
    # Pure Python fallback: Vectorized slicing for speed
    buf_len = len(buffer)
    n = len(filtered)
    ch = min(buffer.shape[1], filtered.shape[1])
    
    # Calculate indices for the circular buffer wrap-around
    # Number of samples that fit before the end of the buffer
    space_left = buf_len - buf_pos
    
    if n <= space_left:
        # Fits in one block
        buffer[buf_pos : buf_pos + n, :ch] = filtered[:, :ch]
        raw_buffer[buf_pos : buf_pos + n, :ch] = raw_data[:, :ch]
    else:
        # Wrap-around: fill to end, then start from beginning
        buffer[buf_pos : buf_len, :ch] = filtered[:space_left, :ch]
        raw_buffer[buf_pos : buf_len, :ch] = raw_data[:space_left, :ch]
        
        rem = n - space_left
        buffer[0 : rem, :ch] = filtered[space_left : n, :ch]
        raw_buffer[0 : rem, :ch] = raw_data[space_left : n, :ch]
        
    return (buf_pos + n) % buf_len



def waveform_reduce(data, chunk_size):
    """Reduce audio data into min/max/rms per chunk.
    
    Returns: (max_buf, min_buf, rms_buf) each (n_chunks, channels) f32
    """
    if _HAS_NATIVE:
        return _native.waveform_reduce(data.astype(np.float32), chunk_size)
    
    # Pure Python fallback
    n = len(data)
    chunk_size = max(1, chunk_size)
    n_chunks = (n + chunk_size - 1) // chunk_size
    channels = data.shape[1]
    
    max_buf = np.zeros((n_chunks, channels), dtype=np.float32)
    min_buf = np.zeros((n_chunks, channels), dtype=np.float32)
    rms_buf = np.zeros((n_chunks, channels), dtype=np.float32)
    
    for i in range(n_chunks):
        start = i * chunk_size
        end = min(start + chunk_size, n)
        chunk = data[start:end]
        if len(chunk) == 0:
            continue
        max_buf[i] = np.max(chunk, axis=0)
        min_buf[i] = np.min(chunk, axis=0)
        rms_buf[i] = np.sqrt(np.mean(chunk ** 2, axis=0))
    
    return max_buf, min_buf, rms_buf



def correlation(left: np.ndarray, right: np.ndarray) -> float:
    """Compute stereo correlation coefficient in [-1, +1]."""
    if _HAS_NATIVE:
        return _native.correlation(left.astype(np.float32), right.astype(np.float32))
    
    # Pure Python fallback
    l_norm = left - np.mean(left)
    r_norm = right - np.mean(right)
    denom = np.sqrt(np.sum(l_norm**2) * np.sum(r_norm**2))
    if denom < 1e-10:
        return 0.0
    return np.sum(l_norm * r_norm) / denom


def multiband_correlation(left: np.ndarray, right: np.ndarray, sample_rate: float, bands: list) -> dict:
    """Compute correlation per frequency band."""
    if _HAS_NATIVE:
        return _native.multiband_correlation(left.astype(np.float32), right.astype(np.float32), float(sample_rate), bands)
    
    # Pure Python fallback (simplified FFT-based approach)
    n = len(left)
    L = np.fft.rfft(left)
    R = np.fft.rfft(right)
    freqs = np.fft.rfftfreq(n, 1.0/sample_rate)
    
    results = {}
    for name, lo, hi in bands:
        mask = (freqs >= lo) & (freqs < hi)
        if not np.any(mask):
            results[name] = 0.0
            continue
            
        l_band = np.fft.irfft(L * mask, n=n)
        r_band = np.fft.irfft(R * mask, n=n)
        results[name] = correlation(l_band, r_band)
        
    return results



def apply_gain_and_concat(blocks, gain, target_channels=2):
    """Apply gain to audio blocks and concatenate.
    
    blocks: list of (n, channels) f32 arrays
    gain: float multiplier
    target_channels: ensure output has exactly this many channels
    Returns: single (total_n, target_channels) f32 array
    """
    if _HAS_NATIVE and blocks:
        f32_blocks = [b.astype(np.float32) if b.dtype != np.float32 else b for b in blocks]
        return _native.apply_gain_and_concat(f32_blocks, float(gain), int(target_channels))
    
    # Pure Python fallback (numpy)
    if not blocks:
        return np.zeros((0, target_channels), dtype=np.float32)
    
    if gain != 1.0:
        blocks = [b * gain for b in blocks]
    
    res = np.concatenate(blocks)
    if res.shape[1] != target_channels:
        # Pad or truncate channels to match target
        actual_ch = res.shape[1]
        if actual_ch < target_channels:
            padded = np.zeros((res.shape[0], target_channels), dtype=np.float32)
            padded[:, :actual_ch] = res
            return padded
        else:
            return res[:, :target_channels]
            
    return res



def compute_fft(data, window, fft_size):
    """Compute the magnitude spectrum of audio data.
    
    data: (n_samples,) f32
    window: (fft_size,) f32
    fft_size: int
    Returns: (fft_size // 2 + 1,) f32 magnitude in dB
    """
    if _HAS_NATIVE:
        return _native.compute_fft(
            data.astype(np.float32), 
            window.astype(np.float32), 
            int(fft_size)
        )
    
    # Pure Python fallback
    n = min(len(data), fft_size)
    padded = np.zeros(fft_size, dtype=np.float32)
    padded[:n] = data[:n]
    windowed = padded * window
    
    spectrum = np.fft.rfft(windowed)
    magnitude = np.abs(spectrum)
    # Correct normalization for windowed real FFT: 
    # Standard: magnitude * 2 / sum(window)
    # For Hann window, sum(window) is approx fft_size / 2.
    # So: magnitude * 2 / (fft_size / 2) = magnitude * 4 / fft_size
    magnitude = magnitude / (fft_size / 4)
    magnitude = np.clip(magnitude, 1e-10, None)
    return 20.0 * np.log10(magnitude)


_TILT_CACHE = {}

def apply_tilt(magnitude_db, freqs, tilt_db, pivot_hz=1000.0):
    """Apply dB/octave spectral tilt around a pivot frequency."""
    if abs(tilt_db) < 0.01:
        return magnitude_db

    if _HAS_NATIVE and hasattr(_native, "apply_tilt"):
        return _native.apply_tilt(
            magnitude_db.astype(np.float32),
            freqs.astype(np.float32),
            float(tilt_db),
            float(pivot_hz),
        )

    freq_step = float(freqs[1] - freqs[0]) if len(freqs) > 1 else 0.0
    cache_key = (len(freqs), float(tilt_db), float(pivot_hz), freq_step)
    if cache_key in _TILT_CACHE:
        tilt_curve = _TILT_CACHE[cache_key]
    else:
        safe_freqs = np.clip(freqs, 20.0, None)
        tilt_curve = np.log2(safe_freqs / max(pivot_hz, 1.0)) * tilt_db
        _TILT_CACHE[cache_key] = tilt_curve

    return magnitude_db + tilt_curve



def _prepare_oscilloscope_trace_py(data: np.ndarray, display_samples: int, num_points: int,
                                   gain_mode: int, manual_gain: float, prev_gain: float):
    n = len(data)
    disp = max(2, min(int(display_samples), n))
    num_pts = max(2, int(num_points))
    search_limit = max(0, n - disp)
    trig = float(search_limit)

    if search_limit > 1:
        subset = data[:search_limit]
        crossings = np.where((subset[:-1] <= 0) & (subset[1:] > 0))[0]
        if len(crossings) > 0:
            idx = crossings[-1]
            y0, y1 = float(subset[idx]), float(subset[idx + 1])
            diff = y1 - y0
            frac = -y0 / diff if abs(diff) > 1e-6 else 0.0
            trig = idx + frac

    t_indices = np.linspace(trig, trig + disp - 1, num_pts, endpoint=True)
    sample_indices = np.arange(n, dtype=np.float32)
    downsampled = np.interp(t_indices, sample_indices, data).astype(np.float32)

    if gain_mode == 2:
        target = max(0.05, float(manual_gain))
    else:
        peak = float(np.max(np.abs(downsampled))) if len(downsampled) > 0 else 0.0
        target = 1.0 if peak < 0.0005 else max(0.25, min(32.0, 0.86 / peak))

    if gain_mode == 2:
        gain = target
    else:
        alpha = 0.45 if target < prev_gain else 0.16
        gain = prev_gain + (target - prev_gain) * alpha

    vals = np.clip(downsampled * gain, -1.0, 1.0)
    return vals, float(gain)


def prepare_oscilloscope_trace(data: np.ndarray, display_samples: int, num_points: int,
                               gain_mode: int, manual_gain: float, prev_gain: float):
    """
    Prepare downsampled oscilloscope trace values and gain.
    gain_mode: 0 = Auto Fit, 1 = Auto Shared, 2 = Fixed
    """
    if _HAS_NATIVE and hasattr(_native, "prepare_oscilloscope_trace"):
        f32_data = np.ascontiguousarray(data, dtype=np.float32)
        return _native.prepare_oscilloscope_trace(
            f32_data, int(display_samples), int(num_points),
            int(gain_mode), float(manual_gain), float(prev_gain)
        )
    return _prepare_oscilloscope_trace_py(data, display_samples, num_points, gain_mode, manual_gain, prev_gain)



def _calculate_true_peak_py(data: np.ndarray) -> np.ndarray:
    was_1d = (data.ndim == 1)
    if was_1d:
        data = data[:, np.newaxis]

    if len(data) < 16:
        result = np.full(data.shape[1], -120.0, dtype=np.float64)
        return float(result[0]) if was_1d else result

    # 4x oversampling linear interpolation fallback
    n_samples, n_channels = data.shape
    peaks = np.zeros(n_channels, dtype=np.float64)
    x_orig = np.arange(n_samples, dtype=np.float64)
    x_up = np.linspace(0, n_samples - 1, (n_samples - 1) * 4 + 1)
    for c in range(n_channels):
        up = np.interp(x_up, x_orig, data[:, c])
        peaks[c] = np.max(np.abs(up))

    result = 20.0 * np.log10(np.clip(peaks, 1e-6, None))
    return float(result[0]) if was_1d else result


def calculate_true_peak(data: np.ndarray) -> np.ndarray:
    """Calculate true peak per channel in dBTP."""
    was_1d = (data.ndim == 1)
    if was_1d:
        data = data[:, np.newaxis]

    if _HAS_NATIVE and hasattr(_native, "calculate_true_peak"):
        f64_data = np.ascontiguousarray(data, dtype=np.float64)
        result = _native.calculate_true_peak(f64_data)
        return float(result[0]) if was_1d else result

    return _calculate_true_peak_py(data)



def _sosfilt_py(sos: np.ndarray, x: np.ndarray, zi: np.ndarray = None):
    n_sections = sos.shape[0]
    if zi is None:
        zi = np.zeros((n_sections, 2), dtype=np.float64)
    else:
        zi = np.array(zi, dtype=np.float64, copy=True)

    y = np.array(x, dtype=np.float64, copy=True)
    n_samples = len(y)

    for s in range(n_sections):
        b0, b1, b2, a0, a1, a2 = sos[s]
        inv_a0 = 1.0 / a0 if abs(a0) > 1e-15 else 1.0
        b0, b1, b2, a1, a2 = b0 * inv_a0, b1 * inv_a0, b2 * inv_a0, a1 * inv_a0, a2 * inv_a0
        z1, z2 = float(zi[s, 0]), float(zi[s, 1])

        for i in range(n_samples):
            xi = y[i]
            yi = b0 * xi + z1
            z1 = b1 * xi - a1 * yi + z2
            z2 = b2 * xi - a2 * yi
            y[i] = yi

        zi[s, 0] = z1
        zi[s, 1] = z2

    return y, zi


def sosfilt(sos: np.ndarray, data: np.ndarray, zi: np.ndarray = None):
    """
    Apply second-order sections (biquad) IIR filter.
    Returns: (filtered_data, updated_zi)
    """
    if _HAS_NATIVE and hasattr(_native, "sosfilt"):
        f64_sos = np.ascontiguousarray(sos, dtype=np.float64)
        f64_data = np.ascontiguousarray(data, dtype=np.float64)
        f64_zi = np.ascontiguousarray(zi, dtype=np.float64) if zi is not None else None
        return _native.sosfilt(f64_sos, f64_data, f64_zi)
    return _sosfilt_py(sos, data, zi)


def render_stereometer_rgba(buffer: np.ndarray, left: np.ndarray, right: np.ndarray,
                            cx: float, cy: float, radius: float, zoom: float, persistence: float,
                            display_mode: int, guide_mode: int, max_dots: int,
                            r: int, g: int, b: int, alpha: int) -> bool:
    """Render stereometer point cloud directly into an RGBA (h, w, 4) uint8 buffer."""
    if _HAS_NATIVE and hasattr(_native, "render_stereometer_rgba"):
        l_f32 = np.ascontiguousarray(left, dtype=np.float32)
        r_f32 = np.ascontiguousarray(right, dtype=np.float32)
        _native.render_stereometer_rgba(
            buffer, l_f32, r_f32, float(cx), float(cy), float(radius), float(zoom),
            float(persistence), int(display_mode), int(guide_mode), int(max_dots),
            int(r), int(g), int(b), int(alpha)
        )
        return True
    return False


def render_oscilloscope_rgba(buffer: np.ndarray, samples: np.ndarray,
                             center: float, factor: float, vertical: bool, clear: bool,
                             r: int, g: int, b: int, alpha: int) -> bool:
    """Render oscilloscope trace directly into an RGBA (h, w, 4) uint8 buffer."""
    if _HAS_NATIVE and hasattr(_native, "render_oscilloscope_rgba"):
        s_f32 = np.ascontiguousarray(samples, dtype=np.float32)
        _native.render_oscilloscope_rgba(
            buffer, s_f32, float(center), float(factor), bool(vertical), bool(clear),
            int(r), int(g), int(b), int(alpha)
        )
        return True
    return False



