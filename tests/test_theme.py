import pytest
from app.theme import Colors, apply_theme, build_stylesheet, THEME_PRESETS
from app.theme import _valid_hex_color, _validate_heatmap_stops

def test_apply_theme_midnight():
    apply_theme("Midnight")
    assert Colors.BG_DARKEST == THEME_PRESETS["Midnight"]["BG_DARKEST"]
    assert Colors.ACCENT == THEME_PRESETS["Midnight"]["ACCENT"]

def test_apply_theme_abyss():
    apply_theme("Abyss")
    assert Colors.BG_DARKEST == THEME_PRESETS["Abyss"]["BG_DARKEST"]
    assert Colors.ACCENT == THEME_PRESETS["Abyss"]["ACCENT"]

def test_apply_theme_with_overrides():
    apply_theme("Midnight", overrides={"ACCENT": "#FFFFFF"})
    assert Colors.ACCENT == "#FFFFFF"
    # Ensure other values are still from Midnight
    assert Colors.BG_DARKEST == THEME_PRESETS["Midnight"]["BG_DARKEST"]

def test_apply_invalid_theme_does_nothing():
    apply_theme("Midnight")
    old_bg = Colors.BG_DARKEST
    apply_theme("NonExistentTheme")
    assert Colors.BG_DARKEST == old_bg

def test_build_stylesheet_contains_colors():
    apply_theme("Midnight")
    ss = build_stylesheet()
    assert Colors.BG_DARKEST in ss
    assert Colors.TEXT in ss
    assert "QMainWindow" in ss

def test_color_q_returns_qcolor():
    from PySide6.QtGui import QColor
    qc = Colors.q("#FF0000")
    assert isinstance(qc, QColor)
    assert qc.name().upper() == "#FF0000"

def test_with_alpha_returns_transparent_color():
    qc = Colors.with_alpha("#FF0000", 128)
    assert qc.alpha() == 128

def test_theme_hex_validation_rejects_partial_colors():
    assert _valid_hex_color("#00d4ff")
    assert _valid_hex_color("#05000000")
    assert not _valid_hex_color("#12")
    assert not _valid_hex_color("00d4ff")

def test_heatmap_validation_reports_bad_stops():
    assert _validate_heatmap_stops([[0.0, "#000000"], [1.0, "#ffffff"]]) is None
    assert "position" in _validate_heatmap_stops([[1.2, "#ffffff"]])
    assert "color" in _validate_heatmap_stops([[0.5, "ffffff"]])
