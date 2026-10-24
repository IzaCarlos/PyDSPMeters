import pytest
from PySide6.QtWidgets import QApplication
from app.utils import perf_stats
from app.utils.perf_hud import PerformanceHUD, _get_process_ram_mb

app = QApplication.instance() or QApplication([])


def test_perf_stats_toggle_and_recording():
    perf_stats.set_enabled(False)
    assert not perf_stats.is_enabled()
    perf_stats.record_timing("test.metric", 0.015)
    assert "test.metric" not in perf_stats.snapshot()["timings"]

    perf_stats.set_enabled(True)
    assert perf_stats.is_enabled()
    perf_stats.record_timing("test.metric", 0.015)
    snap = perf_stats.snapshot()
    assert "test.metric" in snap["timings"]
    assert snap["timings"]["test.metric"]["count"] == 1
    assert abs(snap["timings"]["test.metric"]["avg_ms"] - 15.0) < 0.1

    perf_stats.set_enabled(False)


def test_perf_hud_lifecycle():
    hud = PerformanceHUD()
    assert not perf_stats.is_enabled()

    hud.show()
    assert perf_stats.is_enabled()
    assert hud.isVisible()

    # Record some sample stats
    perf_stats.record_timing("paint.spectrum", 0.002)
    perf_stats.record_timing("paint.stereometer", 0.001)
    perf_stats.record_timing("audio.drain_queue", 0.0005)

    hud._refresh_stats()
    assert "paint.spectrum" in hud._stats_data.get("timings", {})

    hud.hide()
    assert not perf_stats.is_enabled()
    assert not hud.isVisible()
    hud.close()


def test_perf_hud_process_ram():
    ram = _get_process_ram_mb()
    # Process memory should be a reasonable positive number (or 0.0 on unsupported)
    assert ram >= 0.0


def test_perf_hud_is_separate_window():
    from PySide6.QtCore import Qt
    hud = PerformanceHUD()
    try:
        assert hud.isWindow()
        assert bool(hud.windowFlags() & Qt.Window)
        assert "Profiler" in hud.windowTitle()
        assert hud.width() >= 360
        assert hud.height() >= 180
    finally:
        hud.close()


def test_perf_hud_controls():
    from PySide6.QtCore import Qt
    hud = PerformanceHUD()
    try:
        hud.show()
        perf_stats.record_timing("paint.test", 0.005)
        hud._refresh_stats()
        assert "paint.test" in hud._stats_data.get("timings", {})

        # Test pause
        hud.pause_btn.setChecked(True)
        hud._toggle_pause()
        assert hud._is_paused
        assert hud.pause_btn.text() == "Resume"

        # Recording while paused should not update displayed snapshot
        perf_stats.record_timing("paint.new_metric", 0.010)
        hud._refresh_stats()
        assert "paint.new_metric" not in hud._stats_data.get("timings", {})

        # Resume
        hud.pause_btn.setChecked(False)
        hud._toggle_pause()
        assert not hud._is_paused
        assert hud.pause_btn.text() == "Pause"

        # Test reset
        hud._reset_metrics()
        assert "paint.test" not in hud._stats_data.get("timings", {})

        # Test pin always on top
        hud.pin_btn.setChecked(True)
        hud._toggle_always_on_top()
        assert hud._always_on_top
        assert bool(hud.windowFlags() & Qt.WindowStaysOnTopHint)

        hud.pin_btn.setChecked(False)
        hud._toggle_always_on_top()
        assert not hud._always_on_top
    finally:
        hud.close()
