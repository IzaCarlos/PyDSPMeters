"""
Multi-band crossover filters for splitting audio into Low, Mid, and High bands.
Uses Linkwitz-Riley (4th order Butterworth cascade) for flat summing.
"""

import numpy as np
from app.dsp import accel as dsp_accel


def _butter_lowpass_sos_4th(fc: float, sr: float) -> np.ndarray:
    w0 = 2.0 * np.pi * min(fc, sr * 0.499) / sr
    K = np.tan(w0 / 2.0)
    K2 = K * K
    sos = []
    for q_inv in [0.7653668647301795, 1.8477590650225735]:
        a0 = 1.0 + q_inv * K + K2
        b0 = K2 / a0
        b1 = 2.0 * b0
        b2 = b0
        a1 = 2.0 * (K2 - 1.0) / a0
        a2 = (1.0 - q_inv * K + K2) / a0
        sos.append([b0, b1, b2, 1.0, a1, a2])
    return np.array(sos, dtype=np.float64)


def _butter_highpass_sos_4th(fc: float, sr: float) -> np.ndarray:
    w0 = 2.0 * np.pi * min(fc, sr * 0.499) / sr
    K = np.tan(w0 / 2.0)
    K2 = K * K
    sos = []
    for q_inv in [0.7653668647301795, 1.8477590650225735]:
        a0 = 1.0 + q_inv * K + K2
        b0 = 1.0 / a0
        b1 = -2.0 * b0
        b2 = b0
        a1 = 2.0 * (K2 - 1.0) / a0
        a2 = (1.0 - q_inv * K + K2) / a0
        sos.append([b0, b1, b2, 1.0, a1, a2])
    return np.array(sos, dtype=np.float64)


class MultiBandFilter:
    """
    3-band crossover filter (Low / Mid / High).
    Crossover frequencies default to 250 Hz and 4000 Hz.
    Uses 4th-order Butterworth filters for clean separation.
    """

    def __init__(self, sample_rate: float = 44100.0,
                 low_cut: float = 250.0, high_cut: float = 4000.0):
        self.sample_rate = sample_rate
        self.low_cut = low_cut
        self.high_cut = high_cut
        self._design_filters()

    def _design_filters(self):
        """Design the crossover filter bank."""
        self._sos_low = _butter_lowpass_sos_4th(self.low_cut, self.sample_rate)
        self._sos_high = _butter_highpass_sos_4th(self.high_cut, self.sample_rate)
        self._sos_mid = np.vstack([
            _butter_highpass_sos_4th(self.low_cut, self.sample_rate),
            _butter_lowpass_sos_4th(self.high_cut, self.sample_rate),
        ])

    def split(self, data: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Split audio into three bands."""
        data_f64 = data.astype(np.float64)
        low, _ = dsp_accel.sosfilt(self._sos_low, data_f64)
        mid, _ = dsp_accel.sosfilt(self._sos_mid, data_f64)
        high, _ = dsp_accel.sosfilt(self._sos_high, data_f64)
        return low.astype(np.float32), mid.astype(np.float32), high.astype(np.float32)


class StreamingMultiBandFilter:
    """
    Streaming version that maintains filter state between calls
    for use with real-time audio blocks.
    """

    def __init__(self, sample_rate: float = 44100.0,
                 low_cut: float = 250.0, high_cut: float = 4000.0,
                 channels: int = 2):
        self.channels = channels
        self._filters = [MultiBandFilter(sample_rate, low_cut, high_cut)
                         for _ in range(channels)]

        sos_low = _butter_lowpass_sos_4th(low_cut, sample_rate)
        sos_high = _butter_highpass_sos_4th(high_cut, sample_rate)
        sos_mid = np.vstack([
            _butter_highpass_sos_4th(low_cut, sample_rate),
            _butter_lowpass_sos_4th(high_cut, sample_rate),
        ])

        self._zi_low = [np.zeros((sos_low.shape[0], 2), dtype=np.float64) for _ in range(channels)]
        self._zi_mid = [np.zeros((sos_mid.shape[0], 2), dtype=np.float64) for _ in range(channels)]
        self._zi_high = [np.zeros((sos_high.shape[0], 2), dtype=np.float64) for _ in range(channels)]
        self._sos_low = sos_low
        self._sos_mid = sos_mid
        self._sos_high = sos_high

    def process(self, data: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Process a block of multi-channel audio."""
        if data.ndim == 1:
            data = data[:, np.newaxis]
        n, ch = data.shape
        ch = min(ch, self.channels)

        low = np.zeros_like(data[:, :ch])
        mid = np.zeros_like(data[:, :ch])
        high = np.zeros_like(data[:, :ch])

        for c in range(ch):
            d = data[:, c].astype(np.float64)
            low[:, c], self._zi_low[c] = dsp_accel.sosfilt(self._sos_low, d, zi=self._zi_low[c])
            mid[:, c], self._zi_mid[c] = dsp_accel.sosfilt(self._sos_mid, d, zi=self._zi_mid[c])
            high[:, c], self._zi_high[c] = dsp_accel.sosfilt(self._sos_high, d, zi=self._zi_high[c])

        return low.astype(np.float32), mid.astype(np.float32), high.astype(np.float32)

