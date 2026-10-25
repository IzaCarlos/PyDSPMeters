"""
Logging and Exception Handling Utilities.
Provides global exception hooks and a stylized crash dialog.
"""

import sys
import os
import logging
import traceback
import subprocess
import threading
from datetime import datetime
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QTextEdit, QFrame, QApplication
)
from PySide6.QtCore import Qt, QTimer

from app.theme import Colors, Fonts, build_stylesheet
from app.settings import SettingsManager

# --- Configuration ---
LOG_FILENAME = SettingsManager.get_log_filename()
LOG_PATH = os.path.join(SettingsManager.get_app_data_dir(), LOG_FILENAME)

def setup_logging():
    """Initialize the logging system."""
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    # Formatter
    formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # File Handler
    try:
        file_handler = logging.FileHandler(LOG_PATH, mode='w', encoding='utf-8')
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.DEBUG)
        logger.addHandler(file_handler)
    except Exception as e:
        print(f"Failed to initialize file logging: {e}")

    # Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)
    logger.addHandler(console_handler)

    logging.info(f"Logging initialized. Log file: {LOG_PATH}")
    logging.info(f"Platform: {sys.platform} | Python: {sys.version}")

class CrashDialog(QDialog):
    """Stylized dialog shown when a fatal error occurs."""
    def __init__(self, exc_type, exc_value, exc_traceback):
        super().__init__()
        self.setWindowTitle(f"System Interruption - {SettingsManager.get_window_title()}")
        self.setFixedSize(600, 450)
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        # Format the traceback
        tb_list = traceback.format_exception(exc_type, exc_value, exc_traceback)
        self.tb_text = "".join(tb_list)
        
        self.setWindowOpacity(0.0)
        self._fade_timer = QTimer(self)
        self._fade_timer.timeout.connect(self._fade_step)
        self._fade_timer.start(20)
        
        self._init_ui(exc_type.__name__, str(exc_value))
        
    def _fade_step(self):
        op = self.windowOpacity()
        if op < 1.0:
            self.setWindowOpacity(min(1.0, op + 0.08))
        else:
            self._fade_timer.stop()
        
    def _init_ui(self, err_type, err_msg):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Main container (glass-like)
        container = QFrame()
        container.setObjectName("container")
        container.setStyleSheet(f"""
            QFrame#container {{
                background-color: {Colors.BG_DARKEST};
                border: 1px solid {Colors.ACCENT};
                border-radius: 8px;
            }}
        """)
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(30, 30, 30, 30)
        container_layout.setSpacing(20)
        
        # Header
        header = QLabel("UNEXPECTED SYSTEM INTERRUPTION")
        header_font = Fonts.header()
        header_font.setPointSize(16)
        header.setFont(header_font)
        header.setStyleSheet(f"color: {Colors.ACCENT}; letter-spacing: 2px;")
        container_layout.addWidget(header, alignment=Qt.AlignCenter)
        
        # Error Info
        info_layout = QVBoxLayout()
        info_layout.setSpacing(5)
        
        type_label = QLabel(f"Type: {err_type}")
        type_label.setStyleSheet(f"color: {Colors.TEXT_BRIGHT}; font-weight: bold;")
        info_layout.addWidget(type_label)
        
        msg_label = QLabel(err_msg)
        msg_label.setWordWrap(True)
        msg_label.setStyleSheet(f"color: {Colors.TEXT};")
        info_layout.addWidget(msg_label)
        
        container_layout.addLayout(info_layout)
        
        # Traceback view
        self.tb_view = QTextEdit()
        self.tb_view.setReadOnly(True)
        self.tb_view.setPlainText(self.tb_text)
        self.tb_view.setStyleSheet(f"""
            QTextEdit {{
                background-color: {Colors.BG_INPUT};
                border: 1px solid {Colors.BORDER};
                border-radius: 4px;
                color: {Colors.TEXT_DIM};
                font-family: 'Cascadia Code', 'Consolas', monospace;
                font-size: 8pt;
            }}
        """)
        container_layout.addWidget(self.tb_view)
        
        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(15)
        
        log_btn = QPushButton("Open Log & Close")
        log_btn.setCursor(Qt.PointingHandCursor)
        log_btn.setMinimumHeight(40)
        log_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {Colors.ACCENT_DIM};
                color: white;
                font-weight: bold;
                border: none;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: {Colors.ACCENT};
            }}
        """)
        log_btn.clicked.connect(self._open_log_and_exit)
        
        close_btn = QPushButton("Close Application")
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setMinimumHeight(40)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {Colors.BG_SETTINGS};
                color: {Colors.TEXT};
                border: 1px solid {Colors.BORDER};
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: {Colors.BG_INPUT};
                border-color: {Colors.TEXT_DIM};
            }}
        """)
        close_btn.clicked.connect(self.reject)
        
        btn_layout.addWidget(log_btn)
        btn_layout.addWidget(close_btn)
        
        container_layout.addLayout(btn_layout)
        
        # Bottom Note
        note = QLabel(f"A detailed log has been saved to: {LOG_FILENAME}")
        note.setAlignment(Qt.AlignCenter)
        note.setStyleSheet(f"color: {Colors.TEXT_DIM}; font-size: 7pt;")
        container_layout.addWidget(note)
        
        layout.addWidget(container)

    def _open_log_and_exit(self):
        """Open the log file location and exit."""
        if sys.platform == "win32":
            subprocess.Popen(f'explorer /select,"{LOG_PATH}"')
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", LOG_PATH])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(LOG_PATH)])
        
        self.accept()

def _cleanup_appbar_win32():
    """Attempt to unregister any active App Bar (used during crashes)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes

        class APPBARDATA(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND),
                ("uCallbackMessage", wintypes.UINT), ("uEdge", wintypes.UINT),
                ("rc", wintypes.RECT), ("lParam", wintypes.LPARAM),
            ]
        
        # We don't have the hWnd here easily, but we can try to find our window
        # For now, if we can't find it, we just hope the OS cleans up 
        # (usually it does when the process dies, but sometimes it hangs)
        # To be safe, we try to find any window with our title
        hwnd = ctypes.windll.user32.FindWindowW(None, SettingsManager.get_window_title())
        if hwnd:
            abd = APPBARDATA()
            abd.cbSize = ctypes.sizeof(APPBARDATA)
            abd.hWnd = hwnd
            ctypes.windll.shell32.SHAppBarMessage(1, ctypes.byref(abd)) # ABM_REMOVE = 1
            logging.info("AppBar: Successfully unregistered during crash cleanup.")
    except Exception as e:
        logging.error(f"AppBar: Failed to cleanup during crash: {e}")

def global_exception_hook(exc_type, exc_value, exc_traceback):
    """Handle unhandled exceptions."""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    # Log the error
    logging.critical("Unhandled Exception occurred:", exc_info=(exc_type, exc_value, exc_traceback))

    # Attempt to cleanup AppBar so it doesn't leave a hole in the workspace
    _cleanup_appbar_win32()

    # Show the crash dialog
    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)
        from app.theme import apply_theme
        apply_theme("Midnight")
        app.setStyleSheet(build_stylesheet())

    dialog = CrashDialog(exc_type, exc_value, exc_traceback)
    dialog.exec()
    
    # Clean exit
    sys.exit(1)

def threading_exception_hook(args):
    """Handle unhandled exceptions in threads (e.g. Audio Engine)."""
    global_exception_hook(args.exc_type, args.exc_value, args.exc_traceback)

def setup_global_exception_handler():
    """Connect the hooks to the system."""
    sys.excepthook = global_exception_hook
    # threading.excepthook is available in Python 3.8+
    if hasattr(threading, 'excepthook'):
        threading.excepthook = threading_exception_hook
