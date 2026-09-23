import json
import os
import re
import sys
import threading
from dataclasses import dataclass
from json import JSONDecodeError

SETTINGS_FILE = "settings.json"
APP_NAME = "PyDSPMeters"
APP_USER_MODEL_ID = "pydspmeters.app.1.0"
PROFILE_ENV_VAR = "PYDSPMETERS_PROFILE"
PROFILE_ARGS = ("--profile", "--instance", "--instance-name")


# Module-level compilation checks to ensure Nuitka catches it
IS_NUITKA = "__compiled__" in globals()
IS_PYINSTALLER = getattr(sys, 'frozen', False)
IS_COMPILED = IS_NUITKA or IS_PYINSTALLER

class SettingsManager:
    """Manages application settings persistence using a JSON file."""

    _profile_name_override = None
    _last_load_error = None

    @dataclass(frozen=True)
    class LoadError:
        path: str
        message: str

    @staticmethod
    def _profile_from_argv(argv=None):
        argv = list(sys.argv if argv is None else argv)
        for index, arg in enumerate(argv[1:], start=1):
            for option in PROFILE_ARGS:
                if arg == option and index + 1 < len(argv):
                    value = argv[index + 1].strip()
                    return value if value and not value.startswith("-") else None
                prefix = option + "="
                if arg.startswith(prefix):
                    value = arg[len(prefix):].strip()
                    return value or None
        return None

    @staticmethod
    def _safe_profile_slug(name):
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", name.strip()).strip(".-_")
        return slug[:64]

    @classmethod
    def set_profile_name(cls, name):
        """Override the current launch profile. Primarily useful in tests."""
        if name is None:
            cls._profile_name_override = None
            return
        cls._profile_name_override = str(name).strip() or None

    @classmethod
    def get_profile_name(cls):
        if cls._profile_name_override is not None:
            return cls._profile_name_override

        profile = cls._profile_from_argv()
        if not profile:
            profile = os.environ.get(PROFILE_ENV_VAR, "").strip()
        return profile or None

    @classmethod
    def get_profile_slug(cls):
        profile = cls.get_profile_name()
        if not profile:
            return None
        return cls._safe_profile_slug(profile) or None

    @classmethod
    def get_window_title(cls):
        profile = cls.get_profile_name()
        return APP_NAME if not profile else f"{APP_NAME} - {profile}"

    @classmethod
    def get_app_user_model_id(cls):
        slug = cls.get_profile_slug()
        return APP_USER_MODEL_ID if not slug else f"{APP_USER_MODEL_ID}.{slug.lower()}"

    @classmethod
    def get_settings_filename(cls):
        slug = cls.get_profile_slug()
        return SETTINGS_FILE if not slug else f"settings-{slug}.json"

    @classmethod
    def get_log_filename(cls):
        slug = cls.get_profile_slug()
        return "pydspmeters.log" if not slug else f"pydspmeters-{slug}.log"

    @staticmethod
    def get_system_app_data_dir():
        """Helper to get the standard OS-specific config directory."""
        if sys.platform == "win32":
            base = os.environ.get("APPDATA")
            if not base or not os.path.isabs(base):
                base = os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
        elif sys.platform == "darwin":
            base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
        else:
            base = os.environ.get("XDG_CONFIG_HOME")
            if not base or not os.path.isabs(base):
                base = os.path.join(os.path.expanduser("~"), ".config")
                
        return os.path.join(base, APP_NAME)

    @staticmethod
    def get_app_data_dir():
        """
        Returns the appropriate config directory.
        Defaults to AppData/Roaming, but if the app is run from a USB drive
        or if settings already exist next to the .exe, it uses portable mode.
        """
        app_dir = None
        settings_file = SettingsManager.get_settings_filename()
        
        if IS_COMPILED:
            if IS_PYINSTALLER:
                exe_dir = os.path.dirname(os.path.realpath(sys.executable))
            else:
                exe_dir = os.path.dirname(os.path.realpath(sys.argv[0]))
                
            # Check if we should use portable mode
            is_portable = False
            
            # 1. Do settings already exist here? (User preference)
            if (
                os.path.exists(os.path.join(exe_dir, SETTINGS_FILE))
                or os.path.exists(os.path.join(exe_dir, settings_file))
            ):
                is_portable = True
            else:
                # 2. Is it on a USB/Removable drive?
                if sys.platform == "win32":
                    import ctypes
                    drive = os.path.splitdrive(exe_dir)[0] + "\\"
                    # 2 = DRIVE_REMOVABLE
                    if ctypes.windll.kernel32.GetDriveTypeW(drive) == 2:
                        is_portable = True
                elif sys.platform == "darwin" and exe_dir.startswith("/Volumes/"):
                    is_portable = True
                elif sys.platform.startswith("linux") and (exe_dir.startswith("/media/") or exe_dir.startswith("/run/media/")):
                    is_portable = True
                    
            if is_portable:
                app_dir = exe_dir
            
        if app_dir is not None:
            try:
                os.makedirs(app_dir, exist_ok=True)
                # Ensure the directory is actually writable (e.g. read-only USB)
                if not os.access(app_dir, os.W_OK):
                    raise OSError("Directory is read-only")
            except OSError:
                import logging
                logging.warning(f"Portable directory {app_dir} is not writable. Falling back to system path.")
                app_dir = None

        if app_dir is None:
            app_dir = SettingsManager.get_system_app_data_dir()
            try:
                os.makedirs(app_dir, exist_ok=True)
                if not os.access(app_dir, os.W_OK):
                    raise OSError("System directory is read-only")
            except OSError:
                import tempfile
                app_dir = os.path.join(tempfile.gettempdir(), APP_NAME)
                try:
                    os.makedirs(app_dir, exist_ok=True)
                except OSError:
                    pass  # Absolute worst-case scenario, but we tried, go fix your shit my guy jesus.

        return app_dir

    @classmethod
    def get_settings_path(cls):
        return os.path.join(cls.get_app_data_dir(), cls.get_settings_filename())

    @classmethod
    def load(cls):
        path = cls.get_settings_path()
        return cls.load_from_file(path)

    @classmethod
    def load_from_file(cls, path):
        path = os.fspath(path)
        cls._last_load_error = None
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    settings = json.load(f)
                if not isinstance(settings, dict):
                    cls._last_load_error = cls.LoadError(
                        path,
                        "Settings files must contain a JSON object at the top level.",
                    )
                    return {}
                return settings
            except JSONDecodeError as e:
                cls._last_load_error = cls.LoadError(
                    path,
                    f"Malformed JSON at line {e.lineno}, column {e.colno}: {e.msg}",
                )
            except Exception as e:
                cls._last_load_error = cls.LoadError(path, str(e))
                print(f"Error loading settings: {e}")
        return {}

    @classmethod
    def get_last_load_error(cls):
        return cls._last_load_error

    _save_lock = threading.Lock()

    @classmethod
    def save(cls, settings):
        """
        Saves settings to disk using a thread-safe, atomic write strategy.
        """
        path = cls.get_settings_path()
        cls.save_to_file(path, settings)

    @classmethod
    def save_to_file(cls, path, settings):
        """
        Saves settings to a specific JSON path using the same atomic strategy.
        """
        path = os.fspath(path)
        with cls._save_lock:
            try:
                directory = os.path.dirname(os.path.abspath(path))
                if directory:
                    os.makedirs(directory, exist_ok=True)
                # Save to a temporary file first to prevent corruption if the app crashes during write
                temp_path = path + ".tmp"
                with open(temp_path, "w", encoding="utf-8") as f:
                    json.dump(settings, f, indent=4)
                
                # Atomic replace
                if os.path.exists(path):
                    os.replace(temp_path, path)
                else:
                    os.rename(temp_path, path)
                return True
            except Exception as e:
                import logging
                logging.error(f"Settings: Failed to save to {path}: {e}")
                return False
