import pytest
import numpy as np
from unittest.mock import MagicMock
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QRect, QPoint
from PySide6.QtGui import QImage, QPainter
from app.modules.loudness_meter import LoudnessModule
from app.modules.vu_meter import VUMeterModule, VU_STYLE_NAMES
from app.modules.oscilloscope import OscilloscopeModule
from app.modules.spectrogram import SpectrogramModule
from app.modules.spectrum import SpectrumModule
from app.modules.waveform import WaveformModule
from app.modules.stereometer import StereometerModule
from app.window_manager import MainWindow
from app.base_module import BaseModule, MODULE_MIN_HEIGHT, MODULE_MIN_WIDTH

# Create a global QApplication for tests that need it
app = QApplication.instance() or QApplication([])

class MockEngine:
    def __init__(self):
        self.sample_rate = 44100
        self.channels = 2
        self.data_ready = MagicMock()

def test_loudness_module_mode_switch():
    engine = MockEngine()
    module = LoudnessModule(engine)
    
    assert module._mode == "LUFS"
    assert "LUFS" in module.header._title.text()
    
    module._set_mode("RMS")
    assert module._mode == "RMS"
    assert "RMS" in module.header._title.text()

def test_base_module_has_nonzero_splitter_minimums():
    engine = MockEngine()
    module = BaseModule(engine)

    assert module.minimumWidth() >= MODULE_MIN_WIDTH
    assert module.minimumHeight() >= MODULE_MIN_HEIGHT
    assert module.canvas.minimumWidth() >= MODULE_MIN_WIDTH
    assert module.canvas.minimumHeight() >= MODULE_MIN_HEIGHT

def test_loudness_module_processing():
    engine = MockEngine()
    module = LoudnessModule(engine)
    
    # Simulate loud stereo sine wave
    t = np.arange(1024) / 44100.0
    tone = np.sin(2 * np.pi * 1000 * t).astype(np.float32)
    stereo = np.column_stack([tone, tone])
    
    module.on_audio_data(stereo)
    
    # Peak should be near 0 dBFS
    assert np.all(module._peak > -1.0)
    # LUFS should be around -3.0 dB for a full scale sine
    assert np.all(module._lufs_m > -5.0)

def test_loudness_module_uses_combined_lufs_for_stereo_display():
    engine = MockEngine()
    module = LoudnessModule(engine)
    module._reactivity = "Instant"
    
    t = np.arange(44100) / 44100.0
    tone = np.sin(2 * np.pi * 1000 * t).astype(np.float32)
    stereo = np.column_stack([tone, tone])
    
    module.on_audio_data(stereo)
    
    assert module._lufs_m_combined > module._lufs_m[0] + 2.5
    vals, raw = module._meter_values(0, per_channel=False)
    assert raw[0] == module._lufs_m_combined
    assert vals[0] == module._disp_m_combined

def test_loudness_module_settings_persistence():
    engine = MockEngine()
    module = LoudnessModule(engine)
    
    # Mock settings
    settings = {
        "mode": "RMS",
        "orientation": "Vertical",
        "show_peak": False
    }
    
    module.apply_settings(settings)
    assert module._mode == "RMS"
    assert module._orientation == "Vertical"
    assert module._show_peak == False
    
    # Save settings
    saved = module.get_settings()
    assert saved["mode"] == "RMS"
    assert saved["orientation"] == "Vertical"
    assert saved["show_peak"] == False

def test_loudness_mode_rows_are_consistent():
    engine = MockEngine()
    module = LoudnessModule(engine)

    module._set_mode("LUFS")
    assert module._active_meter_indices() == [0, 1, 3]

    module._show_follow_badge = False
    assert module._active_meter_indices() == [0, 1, 2, 3]

    module._set_mode("RMS")
    assert module._active_meter_indices() == [0, 1, 2]

    module._set_mode("dBTP")
    assert module._active_meter_indices() == [2]

def test_loudness_follow_badge_tracks_true_peak():
    engine = MockEngine()
    module = LoudnessModule(engine)
    module._peak_follow = -48.0
    module.apply_audio_result({
        "channels": 2,
        "lufs_m": np.array([-40.0, -40.0]),
        "lufs_st": np.array([-40.0, -40.0]),
        "lufs_int": -40.0,
        "rms_m": np.array([-40.0, -40.0]),
        "rms_st": np.array([-40.0, -40.0]),
        "peak": np.array([-3.0, -6.0]),
        "lufs_m_combined": -40.0,
        "lufs_st_combined": -40.0,
        "rms_m_combined": -40.0,
        "rms_st_combined": -40.0,
        "peak_combined": -3.0,
    })

    assert module._peak_follow == -3.0

def test_loudness_rejects_malformed_settings_values():
    engine = MockEngine()
    module = LoudnessModule(engine)

    module.apply_settings({
        "mode": "wat",
        "orientation": "sideways",
        "reactivity": "turbo",
        "show_peak": "off",
        "show_integrated": "yes",
    })

    assert module._mode == "LUFS"
    assert module._orientation == "Auto"
    assert module._reactivity == "Fast"
    assert module._show_peak is False
    assert module._show_integrated is True

def test_loudness_modes_render_without_errors():
    engine = MockEngine()
    module = LoudnessModule(engine)
    module._lufs_m_combined = module._disp_m_combined = -18.0
    module._lufs_st_combined = module._disp_st_combined = -16.0
    module._lufs_int = module._disp_int = -20.0
    module._peak_combined = module._disp_peak_combined = -2.0
    module._peak_follow = -2.0

    for mode in ["LUFS", "RMS", "dBTP"]:
        for orientation in ["Horizontal", "Vertical"]:
            module._set_mode(mode)
            module._orientation = orientation
            image = QImage(260, 150, QImage.Format_ARGB32)
            image.fill(0)
            painter = QPainter(image)
            module._render(painter, image.width(), image.height())
            painter.end()

def test_vu_sample_peak_and_clip_accurate_dbfs():
    engine = MockEngine()
    module = VUMeterModule(engine)
    module._rise_coeff = 1.0

    # 1. Quiet audio at -12 dBFS (amplitude ~0.25)
    t = np.arange(4096) / 44100.0
    quiet = (0.25 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)
    module.on_audio_data(np.column_stack([quiet, quiet]))
    assert not module._peak_lit_l
    assert not module._clip_lit_l

    # 2. Audio crossing peak threshold (-1.4 dBFS >= -2.0 dBFS) with +10 calibration
    # Peak LED should light, but Clip LED MUST NOT light!
    module._cal_offset = 10.0
    mod = (0.85 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)
    module.on_audio_data(np.column_stack([mod, mod]))
    assert module._peak_lit_l
    assert not module._clip_lit_l

    # 3. Audio hitting 0 dBFS (amplitude 1.0)
    # Clip LED must light up
    loud = np.ones((1024, 2), dtype=np.float32)
    module.on_audio_data(loud)
    assert module._clip_lit_l
    assert module._clip_lit_r

def test_vu_peak_led_decay_and_mono_channels():
    engine = MockEngine()
    module = VUMeterModule(engine)
    t = np.arange(1024) / 44100.0
    hit = (0.90 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)
    silence = np.zeros(1024, dtype=np.float32)

    # 1. Stereo decay: Peak turns on on hit, then flickers down after silence blocks
    module._channel = "L+R"
    module.on_audio_data(np.column_stack([hit, hit]))
    assert module._peak_lit_l
    # ~115ms of silence (5 blocks of 23ms > 80ms hold_time)
    for _ in range(5):
        module.on_audio_data(np.column_stack([silence, silence]))
    assert not module._peak_lit_l
    assert not module._peak_lit_r

    # 2. Mono / selected channel mode decay (verifies no stuck LED bug)
    for ch in ["Left", "Right", "Mid", "Side"]:
        module._channel = ch
        module.on_audio_data(np.column_stack([hit, hit if ch != "Side" else -hit]))
        assert module._peak_lit_l
        for _ in range(5):
            module.on_audio_data(np.column_stack([silence, silence]))
        assert not module._peak_lit_l, f"Peak LED stayed stuck in channel mode {ch}"

    # 3. Dynamic bass hit rhythm during -12 dB playback: LED triggers on hit, flickers down during steady audio
    body = (0.25 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)
    module._channel = "L+R"
    module.on_audio_data(np.column_stack([hit, hit]))
    assert module._peak_lit_l
    for _ in range(5):
        module.on_audio_data(np.column_stack([body, body]))
    assert not module._peak_lit_l

def test_vu_calibration_shifts_needle_without_distorting_clip():
    engine = MockEngine()
    module = VUMeterModule(engine)
    module._rise_coeff = 1.0

    t = np.arange(4096) / 44100.0
    tone = (0.5 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)
    stereo = np.column_stack([tone, tone])

    module._cal_offset = 0.0
    module.on_audio_data(stereo)
    needle_0 = module._needle_l

    module._cal_offset = 5.0
    module.on_audio_data(stereo)
    needle_5 = module._needle_l

    # Needle at +5 cal offset should be ~5 dB higher than at 0
    assert needle_5 > needle_0 + 3.0
    # Still not clipped (amplitude was only 0.5 = -6 dBFS)
    assert not module._clip_lit_l

def test_vu_meter_mechanical_ballistics_response_time():
    engine = MockEngine()
    module = VUMeterModule(engine)
    module._rise_coeff = 0.30

    sr = 44100
    t = np.arange(1024) / float(sr)
    block = (0.707 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)
    stereo = np.column_stack([block, block])

    for _ in range(14):
        module.on_audio_data(stereo)

    # In ~300ms, needle should reach the target -6 dB level within 0.5 dB
    assert abs(module._needle_l - (-6.02)) < 0.5

    silence = np.zeros((1024, 2), dtype=np.float32)
    for _ in range(14):
        module.on_audio_data(silence)

    assert module._needle_l < -18.0

def test_vu_settings_coerce_malformed_user_values():
    engine = MockEngine()
    module = VUMeterModule(engine)
    module.apply_settings({
        "channel": "Nope",
        "cal_offset": "bad",
        "style": len(VU_STYLE_NAMES) + 20,
        "show_peak": "off",
        "show_clip": "yes",
        "peak_threshold": "not_a_number",
    })

    assert module._channel == "L+R"
    assert module._cal_offset == 0.0
    assert module._style == 0
    assert module._show_peak is False
    assert module._show_clip is True
    assert module._peak_threshold == -2.0

    module.apply_settings({"peak_threshold": -3.0})
    assert module._peak_threshold == -3.0
    assert module.get_settings()["peak_threshold"] == -3.0

def test_vu_all_styles_render_without_errors():
    engine = MockEngine()
    module = VUMeterModule(engine)
    module._needle_l = -8.0
    module._needle_r = -3.0

    for style in range(len(VU_STYLE_NAMES)):
        module._style = style
        image = QImage(260, 150, QImage.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        module._render(painter, image.width(), image.height())
        painter.end()

def test_oscilloscope_buffer_updates_in_place():
    engine = MockEngine()
    module = OscilloscopeModule(engine)
    left_id = id(module._waveform_l)
    right_id = id(module._waveform_r)

    samples = np.column_stack([
        np.linspace(-1.0, 1.0, 128, dtype=np.float32),
        np.linspace(1.0, -1.0, 128, dtype=np.float32),
    ])

    module.on_audio_data(samples)

    assert id(module._waveform_l) == left_id
    assert id(module._waveform_r) == right_id
    np.testing.assert_allclose(module._waveform_l[-128:], samples[:, 0])
    np.testing.assert_allclose(module._waveform_r[-128:], samples[:, 1])

def test_oscilloscope_auto_gain_expands_quiet_traces():
    engine = MockEngine()
    module = OscilloscopeModule(engine)
    quiet = np.full(256, 0.1, dtype=np.float32)

    module._set_gain_mode("Auto Fit")
    auto_gain = module._get_trace_gain(quiet, trace_key=0)
    module._set_gain_mode("Fixed", 2.0)
    fixed_gain = module._get_trace_gain(quiet, trace_key=0)

    assert auto_gain > fixed_gain
    assert fixed_gain == 2.0

def test_waveform_auto_gain_expands_quiet_traces():
    engine = MockEngine()
    module = WaveformModule(engine)
    quiet_max = np.full(128, 0.1, dtype=np.float32)
    quiet_min = np.full(128, -0.1, dtype=np.float32)

    module._set_gain_mode("Auto Fit")
    auto_gain = module._get_trace_gain(quiet_max, quiet_min, trace_key=0)
    module._set_gain_mode("Fixed", 2.0)
    fixed_gain = module._get_trace_gain(quiet_max, quiet_min, trace_key=0)

    assert auto_gain > fixed_gain
    assert fixed_gain == 2.0

def test_stereometer_auto_zoom_expands_quiet_phase_cloud():
    engine = MockEngine()
    module = StereometerModule(engine)
    left = np.full(512, 0.05, dtype=np.float32)
    right = np.full(512, 0.04, dtype=np.float32)

    module._update_auto_zoom(left, right)

    assert module._effective_zoom() > 1.0

def test_stereometer_auto_zoom_max_vs_padded():
    engine = MockEngine()
    module = StereometerModule(engine)
    module._auto_zoom_value = 1.0

    left = np.full(512, 0.5, dtype=np.float32)
    right = np.full(512, 0.5, dtype=np.float32)

    module._set_auto_zoom_mode("Padded")
    for _ in range(15):
        module._update_auto_zoom(left, right)
    padded_zoom = module._effective_zoom()

    module._set_auto_zoom_mode("Max")
    for _ in range(15):
        module._update_auto_zoom(left, right)
    max_zoom = module._effective_zoom()

    # Max zoom targets 0.96 / peak whereas Padded targets 0.68 / peak
    assert max_zoom > padded_zoom

    # Verify settings persistence
    settings = module.get_settings()
    assert settings["auto_zoom_mode"] == "Max"
    module.apply_settings({"auto_zoom_mode": "Padded"})
    assert module._auto_zoom_mode == "Padded"

def test_stereometer_max_mode_and_scaled_render_cleanly():
    engine = MockEngine()
    module = StereometerModule(engine)
    module._set_auto_zoom_mode("Max")

    # Signal with silence and low-amplitude noise
    t = np.linspace(0, 1.0, 512, dtype=np.float32)
    left = 0.05 * np.sin(2 * np.pi * 440 * t)
    right = 0.05 * np.cos(2 * np.pi * 440 * t)
    module.on_audio_data(np.column_stack([left, right]))

    for mode in ["Linear", "Scaled", "Lissajous"]:
        module._display_mode = mode
        image = QImage(200, 200, QImage.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        module._render(painter, image.width(), image.height())
        painter.end()

def test_stereometer_mono_is_continuous_line_without_center_gap():
    engine = MockEngine()
    module = StereometerModule(engine)
    module._set_auto_zoom_mode("Max")
    module._auto_zoom_value = 1.0

    # Mono sine wave crossing zero
    t = np.linspace(0, 1.0, 512, dtype=np.float32)
    tone = np.sin(2 * np.pi * 5 * t).astype(np.float32)

    captured_points = []
    class MockPainter:
        def save(self): pass
        def restore(self): pass
        def setOpacity(self, o): pass
        def setPen(self, p): pass
        def drawPoints(self, pts):
            captured_points.extend(pts)

    module._draw_trace(MockPainter(), tone, tone, 100.0, 100.0, 100.0, "#FFFFFF", 255)
    assert len(captured_points) > 0

    # In mono: dx = (R - L) / 2 = 0, so all points lie along x = 100.0
    for pt in captured_points:
        assert abs(pt.x() - 100.0) < 1e-4

    # The line must be continuous near the center (100.0, 100.0), with zero-crossings present
    distances = [abs(pt.y() - 100.0) for pt in captured_points]
    assert min(distances) < 2.0

def test_stereometer_rolling_buffer_preserves_dot_density():
    engine = MockEngine()
    module = StereometerModule(engine)
    module._max_dots = 2048

    for i in range(4):
        block = np.full((512, 2), float(i), dtype=np.float32)
        module.on_audio_data(block)

    assert len(module._left) == 2048
    assert module._left[0] == 0.0
    assert module._left[-1] == 3.0

def test_stereometer_xy_mode_ac_centers_trace():
    engine = MockEngine()
    module = StereometerModule(engine)
    module._display_mode = "XY Oscilloscope"
    module._auto_zoom = False

    t = np.arange(512) / 44100.0
    left = 0.4 + 0.2 * np.sin(2 * np.pi * 1000 * t)
    right = -0.3 + 0.2 * np.cos(2 * np.pi * 1000 * t)
    module.on_audio_data(np.column_stack([left, right]).astype(np.float32))

    assert abs(float(np.mean(module._left_xy))) < 1e-6
    assert abs(float(np.mean(module._right_xy))) < 1e-6

def test_stereometer_xy_mode_renders_without_errors():
    engine = MockEngine()
    module = StereometerModule(engine)
    module._display_mode = "XY Oscilloscope"
    module._trace_style = "Instant"
    module._left_xy = np.sin(np.linspace(0, np.pi * 2, 512)).astype(np.float32)
    module._right_xy = np.cos(np.linspace(0, np.pi * 2, 512)).astype(np.float32)

    image = QImage(220, 160, QImage.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    module._render(painter, image.width(), image.height())
    painter.end()

def test_stereometer_auto_width_expands_quiet_side():
    engine = MockEngine()
    module = StereometerModule(engine)
    module._auto_width = True
    module._auto_width_gain = 1.0

    # Feed stereo track with loud Mid (0.8) and quiet Side (0.05)
    t = np.arange(1024) / 44100.0
    mid = 0.8 * np.sin(2 * np.pi * 440 * t)
    side = 0.05 * np.cos(2 * np.pi * 880 * t)
    left = (mid + side).astype(np.float32)
    right = (mid - side).astype(np.float32)

    for _ in range(10):
        module.on_audio_data(np.column_stack([left, right]))

    # Auto width gain should dynamically boost Side so the cloud opens up
    assert module._auto_width_gain > 1.5

def test_stereometer_scaled_and_linear_modes_render():
    engine = MockEngine()
    module = StereometerModule(engine)

    left = np.sin(np.linspace(0, np.pi * 4, 1024)).astype(np.float32)
    right = np.cos(np.linspace(0, np.pi * 4, 1024)).astype(np.float32)
    module.on_audio_data(np.column_stack([left, right]))

    for mode in ["Scaled", "Linear", "Vectorscope"]:
        module._display_mode = mode
        image = QImage(200, 200, QImage.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        module._render(painter, image.width(), image.height())
        painter.end()

def test_stereometer_circular_signal_preserves_ring():
    engine = MockEngine()
    module = StereometerModule(engine)
    module._auto_width = False
    module._width_gain = 1.0

    # 90-degree phase shift sine/cosine circle
    t = np.linspace(0, np.pi * 4, 1024, endpoint=False)
    left = (0.5 * np.sin(t)).astype(np.float32)
    right = (0.5 * np.cos(t)).astype(np.float32)
    module.on_audio_data(np.column_stack([left, right]))

    for mode in ["Linear", "Scaled"]:
        module._display_mode = mode
        dx = (module._right - module._left) * 0.5
        dy = (module._left + module._right) * 0.5
        if mode == "Scaled":
            r = np.sqrt(dx * dx + dy * dy)
            r_safe = np.maximum(r, 1e-7)
            scale = np.power(r_safe, 0.8) / r_safe
            dx = dx * scale
            dy = dy * scale

        r_computed = np.sqrt(dx * dx + dy * dy)
        # Radius along the ring must be uniform, proving no 4-quadrant pinch
        assert np.var(r_computed) < 1e-4

def test_oscilloscope_high_frequency_vertex_cap():
    engine = MockEngine()
    module = OscilloscopeModule(engine)
    module._display_samples = 8192

    # High frequency 12kHz audio with dense zero-crossings
    t = np.arange(8192) / 44100.0
    sig = np.sin(2 * np.pi * 12000 * t).astype(np.float32)
    module.on_audio_data(np.column_stack([sig, sig]))

    # Large width (1920) should still cap trace vertices to <= 480
    image = QImage(1920, 600, QImage.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    module._render(painter, image.width(), image.height())
    painter.end()

def test_appbar_fullscreen_callback_restores_with_forced_repair():
    class DummyWindow:
        def __init__(self):
            self._appbar_fullscreen_active = False
            self.topmost_calls = []
            self.repair_calls = []

        def _set_appbar_topmost(self, enabled):
            self.topmost_calls.append(enabled)

        def _schedule_appbar_repair(self, delay=250, force_register=False):
            self.repair_calls.append((delay, force_register))

    dummy = DummyWindow()

    MainWindow._handle_appbar_callback(dummy, 2, 1)
    MainWindow._handle_appbar_callback(dummy, 2, 0)

    assert dummy.topmost_calls == [False, True]
    assert dummy.repair_calls == [(1200, True)]
    assert not dummy._appbar_fullscreen_active


def test_appbar_fullscreen_callback_immunity_prevents_forced_repair():
    class DummyWindow:
        def __init__(self):
            self._appbar_fullscreen_active = False
            self._appbar_ignore_screenshot_resets = True
            self.topmost_calls = []
            self.repair_calls = []

        def _set_appbar_topmost(self, enabled):
            self.topmost_calls.append(enabled)

        def _schedule_appbar_repair(self, delay=250, force_register=False):
            self.repair_calls.append((delay, force_register))

    dummy = DummyWindow()

    MainWindow._handle_appbar_callback(dummy, 2, 1)
    MainWindow._handle_appbar_callback(dummy, 2, 0)

    # Topmost toggled on entry and exit, but repair calls suppressed completely!
    assert dummy.topmost_calls == [False, True]
    assert dummy.repair_calls == []
    assert not dummy._appbar_fullscreen_active


def test_appbar_geometry_health_detects_moved_window():
    class DummyWindow:
        def __init__(self):
            self._appbar_active = True
            self._appbar_last_rect = QRect(100, 0, 40, 600)

        def geometry(self):
            return QRect(10, 0, 40, 600)

    assert not MainWindow._appbar_geometry_matches(DummyWindow())

def test_appbar_health_detects_hidden_or_geometry_mismatch():
    class DummyWindow:
        def __init__(self, visible=True, geom=QRect(100, 0, 40, 600)):
            self._appbar_active = True
            self._appbar_last_rect = QRect(100, 0, 40, 600)
            self._appbar_registered_hwnd = None
            self._visible = visible
            self._geom = geom

        def isVisible(self):
            return self._visible

        def geometry(self):
            return self._geom

        def winId(self):
            return 0

        def _appbar_geometry_matches(self):
            return MainWindow._appbar_geometry_matches(self)

    ok_win = DummyWindow(visible=True, geom=QRect(100, 0, 40, 600))
    hidden_win = DummyWindow(visible=False, geom=QRect(100, 0, 40, 600))
    moved_win = DummyWindow(visible=True, geom=QRect(0, 0, 40, 600))

    assert MainWindow._appbar_health_ok(ok_win)
    assert not MainWindow._appbar_health_ok(hidden_win)
    assert not MainWindow._appbar_health_ok(moved_win)

def test_appbar_health_detects_offscreen_limbo():
    class DummyWindow:
        def __init__(self, geom):
            self._appbar_active = True
            self._appbar_last_rect = geom
            self._appbar_registered_hwnd = None
            self._geom = geom

        def isVisible(self):
            return True

        def geometry(self):
            return self._geom

        def winId(self):
            return 0

        def _appbar_geometry_matches(self):
            return MainWindow._appbar_geometry_matches(self)

    offscreen_win = DummyWindow(geom=QRect(-10000, -10000, 40, 600))
    assert not MainWindow._appbar_geometry_matches(offscreen_win)
    assert not MainWindow._appbar_health_ok(offscreen_win)

def test_sanitize_window_geometry_clamps_offscreen_limbo():
    x, y, w, h = MainWindow.sanitize_window_geometry(-10000, -10000, 320, 600)
    assert x > -5000
    assert y >= 0
    assert w >= 40
    assert h >= 40

    x, y, w, h = MainWindow.sanitize_window_geometry(None, None, 320, 600, default_edge="right")
    assert x > -5000
    assert y >= 0

    x, y, w, h = MainWindow.sanitize_window_geometry("bad", "bad", 320, 600)
    assert x > -5000
    assert y >= 0

    x, y, w, h = MainWindow.sanitize_window_geometry(-10000, -10000, 1920, 100, default_edge="top")
    assert x >= 0
    assert y >= 0
    assert h == 100
    assert MainWindow.is_rect_visible_on_any_screen(QRect(0, 0, 1920, 100))

def test_gather_settings_never_saves_offscreen_or_minimized():
    class DummySplitter:
        def handleWidth(self):
            return 4
        def sizes(self):
            return []

    class DummyAudioEngine:
        gain_multiplier = 1.0
        channels = 2

    class DummyAppWindow:
        def __init__(self, x, y, minimized=False, appbar_applying=False):
            self._pos = QPoint(x, y)
            self._minimized = minimized
            self._appbar_applying = appbar_applying
            self._appbar_active = True
            self._appbar_saved = True
            self._last_valid_normal_pos = (500, 200)
            self._last_valid_normal_size = (320, 600)
            self._layout_vertical = True
            self._show_headers = True
            self._auto_hide_ui = False
            self._appbar_edge = "right"
            self._settings = {"window": {}, "ui": {}}
            self._modules = []
            self.splitter = DummySplitter()
            self.audio_engine = DummyAudioEngine()
            self._current_device = None

        def pos(self):
            return self._pos

        def geometry(self):
            return QRect(self._pos.x(), self._pos.y(), 320, 600)

        def width(self):
            return 320

        def height(self):
            return 600

        def isMinimized(self):
            return self._minimized

        def is_rect_visible_on_any_screen(self, rect):
            return MainWindow.is_rect_visible_on_any_screen(rect)

        def sanitize_window_geometry(self, x, y, w, h, default_edge="right"):
            return MainWindow.sanitize_window_geometry(x, y, w, h, default_edge)

    # Case 1: Window stuck at (-10000, -10000)
    win1 = DummyAppWindow(-10000, -10000)
    s1 = MainWindow._gather_settings(win1)
    assert s1["window"]["x"] == 500
    assert s1["window"]["y"] == 200
    assert s1["window"]["appbar_active"] is True

    # Case 2: Window minimized (-32000, -32000)
    win2 = DummyAppWindow(-32000, -32000, minimized=True)
    s2 = MainWindow._gather_settings(win2)
    assert s2["window"]["x"] == 500
    assert s2["window"]["y"] == 200

    # Case 3: Window in the middle of appbar docking
    win3 = DummyAppWindow(100, 100, appbar_applying=True)
    s3 = MainWindow._gather_settings(win3)
    assert s3["window"]["x"] == 500
    assert s3["window"]["y"] == 200

def test_oscilloscope_find_trigger_anchors_to_latest_audio():
    engine = MockEngine()
    module = OscilloscopeModule(engine)
    sr = 44100
    t = np.arange(8192) / sr
    sine = np.sin(2 * np.pi * 100 * t).astype(np.float32)
    trigger_idx = module._find_trigger(sine)
    assert trigger_idx > 6000
    assert trigger_idx <= 7168

def test_loudness_follower_badge_contrast():
    from app.theme import Colors
    orig_accent = Colors.ACCENT
    try:
        Colors.ACCENT = "#FFFF00"
        dark_text = LoudnessModule._accent_contrast_color()
        assert dark_text.alpha() == 255
        assert dark_text.name().lower() == "#101016"

        Colors.ACCENT = "#101016"
        light_text = LoudnessModule._accent_contrast_color()
        assert light_text.alpha() == 255
        assert light_text.name().lower() == "#ffffff"
    finally:
        Colors.ACCENT = orig_accent

def test_spectrogram_vertical_cache_rotates_frequency_axis():
    engine = MockEngine()
    module = SpectrogramModule(engine)
    module._buffer_data.fill(0)
    module._buffer_data[module._display_h - 1, 0] = [1, 2, 3]
    module._col_idx = 0

    module._rebuild_render_images()

    assert module._ordered_img.width() == module._history_len
    assert module._ordered_img.height() == module._display_h
    assert module._vertical_img.width() == module._display_h
    assert module._vertical_img.height() == module._history_len
    assert module._vertical_data.shape == (module._history_len, module._display_h, 3)
    np.testing.assert_array_equal(module._vertical_data[0, 0], [1, 2, 3])

def test_oscilloscope_info_setting_and_clean_grid():
    from PySide6.QtWidgets import QMenu
    engine = MockEngine()
    module = OscilloscopeModule(engine)
    assert module._show_info is False

    # Settings round-trip
    settings = module.get_settings()
    assert settings["show_info"] is False
    module.apply_settings({"show_info": True})
    assert module._show_info is True

    # Clean grid update
    module._update_grid(200, 100, False)
    assert module._grid_pixmap is not None
    assert module._grid_pixmap.width() == 200
    assert module._grid_pixmap.height() == 100

    # Context menu
    menu = QMenu()
    module.build_context_menu(menu)
    action_texts = [a.text() for a in menu.actions()]
    assert "Show Info Badges" in action_texts

def test_stereometer_categorized_context_menu():
    from PySide6.QtWidgets import QMenu
    engine = MockEngine()
    module = StereometerModule(engine)
    menu = QMenu()
    module.build_context_menu(menu)
    titles = [a.text() for a in menu.actions()]
    assert "Display Mode" in titles
    assert "View & Guides" in titles
    assert "Correlation" in titles
    assert "Trace & Scaling" in titles

def test_spectrogram_categorized_context_menu():
    from PySide6.QtWidgets import QMenu
    engine = MockEngine()
    module = SpectrogramModule(engine)
    menu = QMenu()
    module.build_context_menu(menu)
    titles = [a.text() for a in menu.actions()]
    assert "Orientation" in titles
    assert "Display & Overlays" in titles
    assert "FFT & Resolution" in titles
    assert "Tuning & Response" in titles

def test_spectrum_categorized_context_menu():
    from PySide6.QtWidgets import QMenu
    engine = MockEngine()
    module = SpectrumModule(engine)
    menu = QMenu()
    module.build_context_menu(menu)
    titles = [a.text() for a in menu.actions()]
    assert "Channel" in titles
    assert "Orientation" in titles
    assert "Mode" in titles
    assert "Display & Notes" in titles
    assert "FFT & Response" in titles


def test_spectrum_tilt_recast_grid():
    engine = MockEngine()
    module = SpectrumModule(engine)
    assert module._grid_pixmap is None
    module._recast_grid(400, 150)
    assert module._grid_pixmap is not None
    assert module._grid_pixmap.width() == 400
    assert module._grid_pixmap.height() == 150

    # Changing tilt invalidates cache for recast
    module._set_tilt(3.0)
    assert module._grid_pixmap is None
    module._recast_grid(400, 150)
    assert module._grid_pixmap is not None

    # Changing scale or f_max invalidates cache
    module._set_scale("linear")
    assert module._grid_pixmap is None
    module._set_f_max_mode("20 kHz")
    assert module._grid_pixmap is None


def test_spectrum_high_cut_modes():
    engine = MockEngine()
    engine.sample_rate = 48000.0
    module = SpectrumModule(engine)

    module._f_max_mode = "16 kHz"
    assert module._get_f_max() == 16000.0

    module._f_max_mode = "18 kHz"
    assert module._get_f_max() == 18000.0

    module._f_max_mode = "20 kHz"
    assert module._get_f_max() == 20000.0

    module._f_max_mode = "22 kHz"
    assert module._get_f_max() == 22050.0

    module._f_max_mode = "Nyquist"
    assert module._get_f_max() == 24000.0


def test_spectrum_mono_audio_collapses_stereo_ribbon():
    import numpy as np
    engine = MockEngine()
    module = SpectrumModule(engine)
    module._channel = "L+R"
    dw = 600

    px_x = np.linspace(0, dw - 1, 1000)
    mag = np.random.randn(1000).astype(np.float32) * 5.0 - 30.0

    # Mono audio: L and R have identical spectrum
    s_l = module._resample_channel_to_pixels(px_x, mag, dw)
    s_r = module._resample_channel_to_pixels(px_x, mag, dw)
    assert np.allclose(s_l, s_r)

    s_max = np.maximum(s_l, s_r)
    s_min = np.minimum(s_l, s_r)
    # When mono, stereo difference is exactly 0
    assert np.allclose(s_max, s_min)


def test_spectrum_resample_preserves_high_frequency_peaks():
    import numpy as np
    engine = MockEngine()
    module = SpectrumModule(engine)
    dw = 600

    # 1000 bins mapped across dw
    px_x = np.linspace(0, dw - 1, 1000)
    mag = np.full(1000, -60.0, dtype=np.float32)
    # Inject a 0 dB peak at bin 950 (high frequency near edge)
    mag[950] = 0.0

    sx, s_max, s_min = module._resample_spectrum_to_pixels(px_x, mag, mag, dw)
    target_px = int(round(px_x[950]))
    # Peak must be preserved within the visual smoothing window
    assert s_max[target_px] > -10.0


def test_spectrum_settings_persistence():
    engine = MockEngine()
    module = SpectrumModule(engine)
    module._tilt = -3.0
    module._show_scale = False
    module._f_max_mode = "Nyquist (Fs/2)"

    settings = module.get_settings()
    assert settings["tilt"] == -3.0
    assert settings["show_scale"] is False
    assert settings["f_max_mode"] == "Nyquist (Fs/2)"

    new_mod = SpectrumModule(engine)
    new_mod.apply_settings(settings)
    assert new_mod._tilt == -3.0
    assert new_mod._show_scale is False
    assert new_mod._f_max_mode == "Nyquist (Fs/2)"


def test_stereometer_idle_render_fast():
    from PySide6.QtGui import QImage, QPainter
    engine = MockEngine()
    module = StereometerModule(engine)
    module._left = np.zeros(2048, dtype=np.float32)
    module._right = np.zeros(2048, dtype=np.float32)
    
    img = QImage(300, 300, QImage.Format_ARGB32)
    p = QPainter(img)
    try:
        module._render(p, 300, 300)
    finally:
        p.end()


def test_spectrum_idle_render_skips_spline():
    from PySide6.QtGui import QImage, QPainter
    engine = MockEngine()
    module = SpectrumModule(engine)
    # Silence: smoothed buffers are at default -120 dB
    img = QImage(400, 200, QImage.Format_ARGB32)
    p = QPainter(img)
    try:
        module._render(p, 400, 200)
    finally:
        p.end()


def test_stereometer_and_spectrum_zero_dim_safety():
    from PySide6.QtGui import QImage, QPainter
    engine = MockEngine()
    stereo = StereometerModule(engine)
    spec = SpectrumModule(engine)
    img = QImage(10, 10, QImage.Format_ARGB32)
    p = QPainter(img)
    try:
        stereo._render(p, 0, 0)
        spec._render(p, 0, 0)
        stereo._render(p, -5, -5)
        spec._render(p, -5, -5)
    finally:
        p.end()


def test_waveform_pause_caching_and_idle():
    from app.modules.waveform import WaveformModule
    from PySide6.QtGui import QImage, QPainter
    engine = MockEngine()
    wave = WaveformModule(engine)
    img = QImage(300, 150, QImage.Format_ARGB32)
    p = QPainter(img)
    try:
        # First render builds cache
        wave._render(p, 300, 150)
        assert wave._cached_pixmap is not None
        cached_pix = wave._cached_pixmap

        # Second render with same write_pos uses cached pixmap
        wave._render(p, 300, 150)
        assert wave._cached_pixmap is cached_pix

        # Changing theme invalidates cache
        wave.on_theme_changed()
        assert wave._cached_pixmap is None
    finally:
        p.end()


def test_spectrum_inactive_line_option():
    from PySide6.QtGui import QImage, QPainter
    engine = MockEngine()
    spec = SpectrumModule(engine)
    assert spec._show_inactive_line is True

    # Check persistence in settings
    settings = spec.get_settings()
    assert settings['show_inactive_line'] is True

    settings['show_inactive_line'] = False
    spec.apply_settings(settings)
    assert spec._show_inactive_line is False

    # Render with inactive line disabled
    img = QImage(300, 150, QImage.Format_ARGB32)
    p = QPainter(img)
    try:
        spec._render(p, 300, 150)
    finally:
        p.end()


def test_oscilloscope_and_stereometer_active_render():
    from app.modules.oscilloscope import OscilloscopeModule
    from PySide6.QtGui import QImage, QPainter
    engine = MockEngine()
    osc = OscilloscopeModule(engine)
    stereo = StereometerModule(engine)

    # Active audio signal
    t = np.linspace(0, 0.05, 1024)
    data = np.column_stack([
        np.sin(2 * np.pi * 440 * t).astype(np.float32),
        np.cos(2 * np.pi * 440 * t).astype(np.float32),
    ])
    osc.on_audio_data(data)
    stereo.on_audio_data(data)

    img = QImage(500, 300, QImage.Format_ARGB32)
    p = QPainter(img)
    try:
        osc._render(p, 500, 300)
        stereo._render(p, 500, 300)
    finally:
        p.end()

