import json
import os
import pytest
from app.settings import SettingsManager

def test_get_settings_path():
    path = SettingsManager.get_settings_path()
    assert path.endswith("settings.json")
    assert "PyDSPMeters" in path

def test_profile_uses_separate_settings_file():
    try:
        SettingsManager.set_profile_name("stream-left")
        path = SettingsManager.get_settings_path()
        assert path.endswith("settings-stream-left.json")
        assert SettingsManager.get_window_title() == "PyDSPMeters - stream-left"
        assert SettingsManager.get_log_filename() == "pydspmeters-stream-left.log"
        assert SettingsManager.get_app_user_model_id().endswith(".stream-left")
    finally:
        SettingsManager.set_profile_name(None)

def test_profile_name_is_sanitized_for_files():
    try:
        SettingsManager.set_profile_name("Stream Left / OBS")
        assert SettingsManager.get_settings_filename() == "settings-Stream-Left-OBS.json"
        assert SettingsManager.get_window_title() == "PyDSPMeters - Stream Left / OBS"
    finally:
        SettingsManager.set_profile_name(None)

def test_save_and_load_settings(tmp_path, monkeypatch):
    # Mock get_settings_path to use a temporary directory
    test_file = tmp_path / "test_settings.json"
    monkeypatch.setattr(SettingsManager, "get_settings_path", lambda: str(test_file))

    settings = {"theme": "Abyss", "gain": 2.0}
    SettingsManager.save(settings)
    
    assert test_file.exists()
    
    loaded = SettingsManager.load()
    assert loaded == settings

def test_load_non_existent_file(tmp_path, monkeypatch):
    test_file = tmp_path / "missing.json"
    monkeypatch.setattr(SettingsManager, "get_settings_path", lambda: str(test_file))
    
    loaded = SettingsManager.load()
    assert loaded == {}

def test_load_corrupt_json(tmp_path, monkeypatch):
    test_file = tmp_path / "corrupt.json"
    test_file.write_text("invalid json {")
    monkeypatch.setattr(SettingsManager, "get_settings_path", lambda: str(test_file))
    
    loaded = SettingsManager.load()
    assert loaded == {}
    error = SettingsManager.get_last_load_error()
    assert error is not None
    assert "line 1" in error.message

def test_load_rejects_non_object_json(tmp_path):
    test_file = tmp_path / "list.json"
    test_file.write_text("[1, 2, 3]")

    loaded = SettingsManager.load_from_file(test_file)

    assert loaded == {}
    assert "top level" in SettingsManager.get_last_load_error().message

def test_save_and_load_profile_file(tmp_path):
    profile_file = tmp_path / "profiles" / "stream.json"
    settings = {
        "window": {"width": 420, "height": 900},
        "modules": [{"key": "vu_meter", "config": {"style": 2}}],
    }

    SettingsManager.save_to_file(profile_file, settings)

    assert profile_file.exists()
    assert SettingsManager.load_from_file(profile_file) == settings


def test_appbar_screenshot_immunity_setting(tmp_path, monkeypatch):
    test_file = tmp_path / "settings_immunity.json"
    monkeypatch.setattr(SettingsManager, "get_settings_path", lambda: str(test_file))

    settings = {
        "window": {
            "appbar_active": True,
            "appbar_edge": "right",
            "appbar_ignore_screenshot_resets": True
        }
    }
    SettingsManager.save(settings)
    loaded = SettingsManager.load()
    assert loaded["window"]["appbar_ignore_screenshot_resets"] is True

