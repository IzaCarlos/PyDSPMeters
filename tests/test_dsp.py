"""
Tests for DSP modules: FFT, Loudness, Correlation, and Filters.
"""

import numpy as np
import pytest
from app.dsp.fft import (
    compute_fft, fft_frequencies, map_frequencies_to_pixels,
    detect_peak_frequency, hz_to_note_name, hz_to_mel, apply_tilt,
)
from app.dsp.loudness import LoudnessMeter
from app.dsp.correlation import correlation, multiband_correlation, stereo_to_mid_side
from app.dsp.filters import MultiBandFilter



class TestFFT:
    def test_compute_fft_returns_correct_shape(self):
        data = np.random.randn(1024).astype(np.float32)
        mag = compute_fft(data, fft_size=1024)
        assert mag.shape == (513,)  # N/2 + 1

    def test_fft_frequencies_shape(self):
        freqs = fft_frequencies(4096, 44100.0)
        assert freqs.shape == (2049,)
        assert freqs[0] == 0.0
        assert abs(freqs[-1] - 22050.0) < 1.0

    def test_sine_peak_detection(self):
        """A 1kHz sine should peak at ~1000 Hz."""
        sr = 44100.0
        t = np.arange(4096) / sr
        tone = np.sin(2 * np.pi * 1000 * t).astype(np.float32)
        mag = compute_fft(tone, 4096)
        freqs = fft_frequencies(4096, sr)
        peak_hz, _ = detect_peak_frequency(mag, freqs)
        assert abs(peak_hz - 1000.0) < 20.0

    def test_hz_to_note_name(self):
        assert hz_to_note_name(440.0).startswith("A4")
        assert hz_to_note_name(261.63).startswith("C4")

    def test_mel_conversion(self):
        hz = np.array([0.0, 1000.0])
        mel = hz_to_mel(hz)
        assert mel[0] == 0.0
        assert mel[1] > 0.0

    def test_pixel_mapping_linear(self):
        freqs = np.array([20.0, 10000.0, 20000.0])
        px = map_frequencies_to_pixels(freqs, 1000, "linear")
        assert px[0] < px[1] < px[2]

    def test_pixel_mapping_log(self):
        freqs = np.array([100.0, 1000.0, 10000.0])
        px = map_frequencies_to_pixels(freqs, 1000, "logarithmic")
        assert px[0] < px[1] < px[2]

    def test_tilt_is_db_per_octave(self):
        freqs = np.array([500.0, 1000.0, 2000.0])
        mag = np.zeros(3)
        tilted = apply_tilt(mag, freqs, 6.0, pivot_hz=1000.0)
        np.testing.assert_allclose(tilted, [-6.0, 0.0, 6.0], atol=0.01)



class TestLoudness:
    def test_silence_returns_low_lufs(self):
        meter = LoudnessMeter(44100.0, 2)
        silence = np.zeros((4096, 2), dtype=np.float32)
        meter.process(silence)
        assert meter.lufs_momentary < -80

    def test_loud_signal_above_silence(self):
        meter = LoudnessMeter(44100.0, 2)
        t = np.arange(44100) / 44100.0
        tone = np.sin(2 * np.pi * 1000 * t).astype(np.float32) * 0.5
        stereo = np.column_stack([tone, tone])
        meter.process(stereo)
        assert meter.lufs_momentary > -40

    def test_rms_of_known_signal(self):
        meter = LoudnessMeter(44100.0, 1)
        # Full-scale sine has RMS of -3.01 dBFS
        t = np.arange(44100) / 44100.0
        tone = np.sin(2 * np.pi * 1000 * t).astype(np.float32)
        meter.process(tone[:, np.newaxis])
        rms = meter.rms_momentary
        assert -4.0 < rms < -2.0

    def test_true_peak(self):
        meter = LoudnessMeter(44100.0, 2)
        data = np.zeros((1024, 2), dtype=np.float32)
        data[500, 0] = 0.9
        meter.process(data)
        assert meter.true_peak > -2.0



class TestCorrelation:
    def test_identical_signals_correlation_one(self):
        sig = np.random.randn(1024).astype(np.float32)
        assert abs(correlation(sig, sig) - 1.0) < 0.01

    def test_inverted_signals_correlation_neg_one(self):
        sig = np.random.randn(1024).astype(np.float32)
        assert abs(correlation(sig, -sig) + 1.0) < 0.01

    def test_uncorrelated_near_zero(self):
        np.random.seed(42)
        a = np.random.randn(10000).astype(np.float32)
        b = np.random.randn(10000).astype(np.float32)
        c = correlation(a, b)
        assert abs(c) < 0.1

    def test_mid_side_conversion(self):
        l = np.array([1.0, 0.5], dtype=np.float32)
        r = np.array([1.0, -0.5], dtype=np.float32)
        mid, side = stereo_to_mid_side(l, r)
        np.testing.assert_allclose(mid, [1.0, 0.0], atol=1e-6)
        np.testing.assert_allclose(side, [0.0, 0.5], atol=1e-6)

    def test_multiband_returns_all_keys(self):
        sig = np.random.randn(4096).astype(np.float32)
        result = multiband_correlation(sig, sig, 44100.0)
        assert "low" in result
        assert "mid" in result
        assert "high" in result
        assert "overall" in result



class TestFilters:
    def test_split_sums_approximately(self):
        """Band-split signals should roughly reconstruct the original."""
        np.random.seed(0)
        sig = np.random.randn(4096).astype(np.float32)
        filt = MultiBandFilter(44100.0)
        low, mid, high = filt.split(sig)
        reconstructed = low + mid + high
        # Not perfect due to filter phase, but energy should be close
        orig_energy = np.sum(sig ** 2)
        recon_energy = np.sum(reconstructed ** 2)
        ratio = recon_energy / max(orig_energy, 1e-10)
        assert 0.5 < ratio < 2.0

    def test_low_band_attenuates_high_freq(self):
        """A 10kHz tone should be mostly absent from the low band."""
        sr = 44100.0
        t = np.arange(4096) / sr
        tone = np.sin(2 * np.pi * 10000 * t).astype(np.float32)
        filt = MultiBandFilter(sr)
        low, _, _ = filt.split(tone)
        assert np.max(np.abs(low)) < 0.2



class TestAcceleration:
    def test_prepare_oscilloscope_trace_shape_and_coords(self):
        from app.dsp import accel
        sig = np.sin(np.linspace(0, 2 * np.pi, 512, dtype=np.float32))
        vals, gain = accel.prepare_oscilloscope_trace(sig, 256, 128, 0, 1.0, 1.0)

        assert vals.shape == (128,)
        assert np.all(vals >= -1.0)
        assert np.all(vals <= 1.0)
        assert gain > 0.0

    def test_prepare_oscilloscope_trace_fallback_parity(self):
        from app.dsp import accel
        sig = np.sin(np.linspace(0, 4 * np.pi, 512, dtype=np.float32))
        v_acc, g_acc = accel.prepare_oscilloscope_trace(sig, 256, 100, 0, 1.0, 1.0)
        v_py, g_py = accel._prepare_oscilloscope_trace_py(sig, 256, 100, 0, 1.0, 1.0)

        np.testing.assert_allclose(v_acc, v_py, atol=1e-3)
        assert abs(g_acc - g_py) < 1e-4

    def test_calculate_true_peak_intersample(self):
        from app.dsp import accel
        t = np.arange(100) / 44100.0
        sig = (np.sin(2 * np.pi * 12000 * t) * 0.7071).astype(np.float32)
        sample_peak = float(np.max(np.abs(sig)))
        tp = accel.calculate_true_peak(sig)
        assert tp >= 20.0 * np.log10(sample_peak) - 0.1

    def test_calculate_true_peak_fallback_parity(self):
        from app.dsp import accel
        sig = np.sin(np.linspace(0, 20 * np.pi, 1024, dtype=np.float32))[:, np.newaxis]
        tp_acc = accel.calculate_true_peak(sig)
        tp_py = accel._calculate_true_peak_py(sig)
        np.testing.assert_allclose(tp_acc, tp_py, atol=0.2)

    def test_render_oscilloscope_rgba(self):
        from app.dsp import accel
        buf = np.zeros((100, 100, 4), dtype=np.uint8)
        samples = np.sin(np.linspace(0, 2 * np.pi, 64, dtype=np.float32))
        ok = accel.render_oscilloscope_rgba(buf, samples, 50.0, 30.0, False, True, 255, 128, 0, 240)
        if accel.is_accelerated():
            assert ok is True
            assert np.count_nonzero(buf) > 0

    def test_render_stereometer_rgba(self):
        from app.dsp import accel
        buf = np.zeros((120, 120, 4), dtype=np.uint8)
        left = np.random.randn(256).astype(np.float32) * 0.5
        right = np.random.randn(256).astype(np.float32) * 0.5
        ok = accel.render_stereometer_rgba(
            buf, left, right, 60.0, 60.0, 50.0, 1.0, 0.5,
            0, 0, 128, 0, 255, 128, 220
        )
        if accel.is_accelerated():
            assert ok is True
            assert np.count_nonzero(buf) > 0


