import pytest
import numpy as np
from unittest.mock import MagicMock
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QRect
from PySide6.QtGui import QImage, QPainter
from app.modules.loudness_meter import LoudnessModule
from app.modules.vu_meter import VUMeterModule, VU_STYLE_NAMES
from app.modules.oscilloscope import OscilloscopeModule
from app.modules.spectrogram import SpectrogramModule
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

def test_vu_clip_led_follows_vu_zero_not_sample_peak():
    engine = MockEngine()
    module = VUMeterModule(engine)
    module._rise_coeff = 1.0

    t = np.arange(4096) / 44100.0
    tone = np.sin(2 * np.pi * 1000 * t).astype(np.float32)
    stereo = np.column_stack([tone, tone])

    module.on_audio_data(stereo)

    assert module._needle_l < 0.0
    assert module._needle_r < 0.0
    assert module._peak_lit_l
    assert module._peak_lit_r
    assert not module._clip_lit_l
    assert not module._clip_lit_r

def test_vu_clip_led_lights_at_vu_zero():
    engine = MockEngine()
    module = VUMeterModule(engine)
    module._rise_coeff = 1.0

    stereo = np.ones((1024, 2), dtype=np.float32)

    module.on_audio_data(stereo)

    assert module._needle_l == 0.0
    assert module._needle_r == 0.0
    assert module._clip_lit_l
    assert module._clip_lit_r

def test_vu_settings_coerce_malformed_user_values():
    engine = MockEngine()
    module = VUMeterModule(engine)
    module.apply_settings({
        "channel": "Nope",
        "cal_offset": "bad",
        "style": len(VU_STYLE_NAMES) + 20,
        "show_peak": "off",
        "show_clip": "yes",
    })

    assert module._channel == "L+R"
    assert module._cal_offset == 0.0
    assert module._style == 0
    assert module._show_peak is False
    assert module._show_clip is True

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
