"""
Window Manager: Main application window with compact title bar,
module management, snapping logic, and theme switching.
"""

import math
import time
import logging
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QMenu, QComboBox, QPushButton, QLabel, QFrame, QApplication,
    QSizePolicy, QWidgetAction, QGraphicsOpacityEffect,
)
from PySide6.QtCore import Qt, QPoint, QRect, QRectF, QSize, Signal, QTimer, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QAction, QColor, QCursor, QIcon, QActionGroup

from app.theme import (
    Colors, Fonts, build_stylesheet, THEME_PRESETS, THEME_GROUPS,
    apply_theme, current_theme_name,
)
from app.audio_engine import AudioEngine
from app.base_module import BaseModule, MODULE_MIN_HEIGHT, MODULE_MIN_WIDTH
from app.modules import MODULE_REGISTRY
from app.settings import SettingsManager
from app.utils import perf_stats

# Ensure all modules register themselves
from app.modules import oscilloscope, loudness_meter, vu_meter  # noqa
from app.modules import stereometer, spectrum, spectrogram, waveform  # noqa


class SkeletonLoadingOverlay(QWidget):
    """Skeleton loading overlay displaying module wireframe placeholders and shimmer based on settings."""

    def __init__(self, parent=None, modules=None, vertical=True):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._opacity = 1.0
        parsed_keys = []
        raw_modules = modules if modules is not None else ["loudness", "stereometer", "spectrum"]
        for m in raw_modules:
            if isinstance(m, str):
                parsed_keys.append(m)
            elif isinstance(m, dict):
                k = m.get("key")
                if k and isinstance(k, str):
                    parsed_keys.append(k)
        if not parsed_keys:
            parsed_keys = ["loudness", "stereometer", "spectrum"]
        self._modules = parsed_keys
        self._vertical = vertical
        self._status = "Initializing core components..."
        
        self._colors = {
            "BG_DARKEST": QColor(Colors.BG_DARKEST),
            "BG_INPUT": QColor(Colors.BG_INPUT),
            "ACCENT": QColor(Colors.ACCENT),
            "TEXT_DIM": QColor(Colors.TEXT_DIM),
            "BORDER": QColor(Colors.BORDER)
        }
        
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._animate)
        self._timer.start(16)
        import time
        self._birth = time.time()

    def set_status(self, text):
        self._status = text
        self.update()

    def _animate(self):
        changed = False
        lerp_speed = 0.05
        for key in self._colors:
            target = QColor(getattr(Colors, key, "#222222"))
            current = self._colors[key]
            if current != target:
                r = current.red() + (target.red() - current.red()) * lerp_speed
                g = current.green() + (target.green() - current.green()) * lerp_speed
                b = current.blue() + (target.blue() - current.blue()) * lerp_speed
                self._colors[key] = QColor(int(r), int(g), int(b))
                changed = True
        
        if changed or self._opacity > 0:
            self.update()

    def paintEvent(self, event):
        from PySide6.QtGui import QPainter, QLinearGradient, QPen
        import time
        with QPainter(self) as p:
            p.setRenderHint(QPainter.Antialiasing)
            
            # Base dark background
            bg = QColor(self._colors["BG_DARKEST"])
            bg.setAlpha(int(255 * self._opacity))
            p.fillRect(self.rect(), bg)
            
            total_rect = self.rect()
            w, h = total_rect.width(), total_rect.height()
            if w < 30 or h < 30:
                return

            # Title bar area offset
            top_offset = 26
            content_rect = QRectF(4, top_offset + 4, max(1, w - 8), max(1, h - top_offset - 8))
            
            num_slots = max(1, len(self._modules))
            elapsed = time.time() - self._birth
            
            mod_titles = {
                "loudness": "LOUDNESS",
                "stereometer": "STEREOMETER",
                "spectrum": "SPECTRUM",
                "oscilloscope": "OSCILLOSCOPE",
                "spectrogram": "SPECTROGRAM",
                "waveform": "WAVEFORM",
                "peak": "PEAK METER",
                "vu_meter": "VU METER",
            }

            def _card_title(item):
                if isinstance(item, str):
                    k = item
                elif isinstance(item, dict):
                    k = str(item.get("key", "MODULE"))
                else:
                    k = str(item)
                return mod_titles.get(k.lower(), k.upper())

            p.setOpacity(self._opacity)

            # Draw skeleton cards
            if self._vertical:
                slot_h = content_rect.height() / num_slots
                for idx, m_key in enumerate(self._modules):
                    slot_rect = QRectF(content_rect.x(), content_rect.y() + idx * slot_h + 2,
                                       content_rect.width(), max(4, slot_h - 4))
                    self._draw_skeleton_card(p, slot_rect, _card_title(m_key), elapsed, idx)
            else:
                slot_w = content_rect.width() / num_slots
                for idx, m_key in enumerate(self._modules):
                    slot_rect = QRectF(content_rect.x() + idx * slot_w + 2, content_rect.y(),
                                       max(4, slot_w - 4), content_rect.height())
                    self._draw_skeleton_card(p, slot_rect, _card_title(m_key), elapsed, idx)

            # Status footer
            if h >= 100 and w >= 120:
                p.setFont(Fonts.small())
                p.setPen(QColor(self._colors["TEXT_DIM"]))
                status_rect = QRectF(10, h - 22, w - 20, 16)
                p.drawText(status_rect, Qt.AlignCenter, str(self._status).upper())

    def _draw_skeleton_card(self, p, rect, title, elapsed, idx):
        from PySide6.QtGui import QLinearGradient, QPen
        
        # Base card
        card_bg = QColor(self._colors["BG_INPUT"])
        card_bg.setAlpha(120)
        p.setPen(QPen(QColor(self._colors["BORDER"]), 1))
        p.setBrush(card_bg)
        p.drawRoundedRect(rect, 4, 4)

        # Shimmer gradient sweep
        shimmer_phase = ((elapsed * 1.2 + idx * 0.3) % 2.0) - 0.5
        gw = rect.width() if rect.width() > rect.height() else rect.height()
        start_x = rect.x() + shimmer_phase * gw
        grad = QLinearGradient(start_x, rect.y(), start_x + 80, rect.y() + 80)
        shimmer_col = QColor(self._colors["ACCENT"])
        shimmer_col.setAlpha(25)
        grad.setColorAt(0, Qt.transparent)
        grad.setColorAt(0.5, shimmer_col)
        grad.setColorAt(1, Qt.transparent)
        p.setPen(Qt.NoPen)
        p.setBrush(grad)
        p.drawRoundedRect(rect, 4, 4)

        # Skeleton badge title
        if rect.width() >= 60 and rect.height() >= 30:
            p.setFont(Fonts.small())
            text_col = QColor(self._colors["ACCENT"])
            text_col.setAlpha(160)
            p.setPen(text_col)
            badge_rect = QRectF(rect.x() + 8, rect.y() + 6, rect.width() - 16, 16)
            p.drawText(badge_rect, Qt.AlignLeft | Qt.AlignVCenter, title)

            # Skeleton wireframe bars/lines
            p.setPen(QPen(QColor(self._colors["BORDER"]), 1, Qt.DotLine))
            mid_y = rect.y() + rect.height() * 0.5
            p.drawLine(int(rect.x() + 10), int(mid_y), int(rect.right() - 10), int(mid_y))

    def fade_out(self):
        self._fade_timer = QTimer(self)
        def step():
            self._opacity -= 0.08
            if self._opacity <= 0:
                self._fade_timer.stop()
                self.hide()
                if self.parent() and hasattr(self.parent(), "_on_overlay_finished"):
                    self.parent()._on_overlay_finished()
                self.deleteLater()
                return
            self.update()
        self._fade_timer.timeout.connect(step)
        self._fade_timer.start(16)


LoadingOverlay = SkeletonLoadingOverlay


def _icon_btn(text, tooltip, size=22):
    btn = QPushButton(text)
    btn.setFixedSize(size, size)
    btn.setToolTip(tooltip)
    btn.setObjectName("titleBarButton")
    return btn


class TitleBar(QFrame):
    def __init__(self, parent_window, parent=None):
        super().__init__(parent)
        self._window = parent_window
        self._drag_pos = None
        self.setFixedHeight(28)
        self.setObjectName("titleBar")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 0, 4, 0)
        layout.setSpacing(2)

        self.logo = QLabel("DSP")
        self.logo.setFont(Fonts.header())
        layout.addWidget(self.logo)

        layout.addStretch()

        self.add_btn = _icon_btn("+", "Add module")
        layout.addWidget(self.add_btn)

        self.layout_btn = _icon_btn("▥", "Layout toggle")
        layout.addWidget(self.layout_btn)

        self.gear_btn = _icon_btn("⚙", "Settings")
        layout.addWidget(self.gear_btn)

        self.move_btn = _icon_btn("✥", "Toggle Move Mode")
        self.move_btn.setCheckable(True)
        layout.insertWidget(layout.indexOf(self.add_btn) + 1, self.move_btn)

        self.min_btn = _icon_btn("─", "Minimize")
        self.min_btn.clicked.connect(self._window.showMinimized)
        layout.addWidget(self.min_btn)

        self.close_btn = _icon_btn("×", "Close")
        self.close_btn.clicked.connect(self._window.close)
        layout.addWidget(self.close_btn)
        
        self.update_theme()

    def update_theme(self):
        self.setStyleSheet(f"#titleBar {{ background: {Colors.BG_DARKEST}; border-bottom: 1px solid {Colors.BORDER}; }}")
        self.logo.setStyleSheet(f"color: {Colors.ACCENT}; background: transparent; font-size: 10pt; font-weight: bold;")
        
        btn_style = f"""
            QPushButton#titleBarButton {{ 
                background: transparent; border: none; color: {Colors.TEXT_DIM}; 
                font-size: 10pt; padding: 0; margin: 0; min-height: 0px; min-width: 0px; 
            }} 
            QPushButton#titleBarButton:hover {{ color: {Colors.ACCENT}; }}
            QPushButton#titleBarButton:checked {{ color: {Colors.ACCENT}; background: {Colors.BG_HEADER}; border-radius: 2px; }}
        """
        
        for b in [self.add_btn, self.layout_btn, self.gear_btn, self.min_btn, self.move_btn]:
            b.setStyleSheet(btn_style)
            
        self.close_btn.setStyleSheet(f"QPushButton#titleBarButton {{ background: transparent; border: none; color: {Colors.TEXT_DIM}; "
                                     f"font-size: 10pt; padding: 0; margin: 0; min-height: 0px; min-width: 0px; }} "
                                     f"QPushButton#titleBarButton:hover {{ color: {Colors.RED}; }}")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self._window.pos()

    def mouseMoveEvent(self, event):
        if self._drag_pos and event.buttons() & Qt.LeftButton:
            self._window.move(
                event.globalPosition().toPoint() - self._drag_pos
            )
            self._window.snap_to_edge()

    def mouseReleaseEvent(self, event):
        if self._drag_pos:
            self._window.snap_to_edge()
            self._drag_pos = None


class ResizeGrip(QWidget):
    """Bottom-right resize grip."""

    def __init__(self, parent_window):
        super().__init__(parent_window)
        self._window = parent_window
        self.setFixedSize(14, 14)
        self.setCursor(Qt.SizeFDiagCursor)
        self._drag_pos = None

    def paintEvent(self, event):
        from PySide6.QtGui import QPainter, QPen
        p = QPainter(self)
        if not p.isActive():
            return
        p.setPen(QPen(QColor(Colors.TEXT_DIM), 1))
        for i in range(3):
            p.drawPoint(12 - i * 4, 12)
            p.drawPoint(12, 12 - i * 4)
        p.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event):
        if self._drag_pos and event.buttons() & Qt.LeftButton:
            delta = event.globalPosition().toPoint() - self._drag_pos
            self._drag_pos = event.globalPosition().toPoint()
            self._window.resize(
                max(60, self._window.width() + delta.x()),
                max(40, self._window.height() + delta.y()),
            )
            self._window.snap_to_edge()


class WelcomeDialog(QFrame):
    """Themed welcome box with startup tips."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(320, 200)
        self.setObjectName("welcomeDialog")
        self.setAttribute(Qt.WA_StyledBackground, True)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)
        
        title = QLabel("Welcome to PyDSPMeters")
        title.setStyleSheet(f"color: {Colors.ACCENT}; font-size: 14pt; font-weight: bold; background: transparent;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        
        tips = QLabel(
            "• <b>Right-click</b> anywhere for settings\n"
            "• <b>Double-click</b> titles to hide/show\n"
            "• <b>Move Mode</b> (✥) to rearrange layout\n"
            "• <b>AppBar Mode</b> to dock to screen edge"
        )
        tips.setStyleSheet(f"color: {Colors.TEXT}; font-size: 9pt; background: transparent;")
        tips.setWordWrap(True)
        layout.addWidget(tips)
        
        layout.addStretch()
        
        btn = QPushButton("Got it!")
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(self.fade_out_anim)
        layout.addWidget(btn, 0, Qt.AlignCenter)
        
        self.update_theme()
        
        # Center in parent
        if parent:
            self.move(parent.rect().center() - self.rect().center())

    def update_theme(self):
        self.setStyleSheet(f"""
            #welcomeDialog {{ 
                background: {Colors.BG_DARK}; 
                border: 2px solid {Colors.BORDER_ACCENT}; 
                border-radius: 8px;
            }}
            QLabel {{ color: {Colors.TEXT}; }}
            QPushButton {{
                background: {Colors.ACCENT_DIM};
                color: {Colors.TEXT_BRIGHT};
                border: none;
                padding: 6px 20px;
                font-weight: bold;
                border-radius: 4px;
            }}
            QPushButton:hover {{ background: {Colors.ACCENT}; }}
        """)

    def fade_out_anim(self):
        from PySide6.QtWidgets import QGraphicsOpacityEffect
        from PySide6.QtCore import QPropertyAnimation
        self.eff = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.eff)
        self.anim = QPropertyAnimation(self.eff, b"opacity")
        self.anim.setDuration(250)
        self.anim.setStartValue(1.0)
        self.anim.setEndValue(0.0)
        self.anim.finished.connect(self.deleteLater)
        self.anim.start()


class MainWindow(QMainWindow):
    """
    Main application window. Frameless, always-on-top,
    with module management, themes, and edge snapping.
    """

    SNAP_THRESHOLD = 20

    def __init__(self, audio_engine: AudioEngine, splash=None):
        super().__init__()
        self.audio_engine = audio_engine
        self._splash = splash
        self._settings = SettingsManager.load()
        self._theme_load_warning = None
        self.setWindowTitle(SettingsManager.get_window_title())

        self.setWindowFlags(
            Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMinimumSize(40, 40)
        
        # Detect First Run
        self._is_first_run = not self._settings
        
        if self._is_first_run:
            # Polished default layout for first-time users
            self.resize(650, 250)
            self._layout_vertical = False # Side-by-side bar
            self._show_headers = False
            self._auto_hide_ui = True
            default_modules = ["loudness", "stereometer", "spectrum"]
            
            # Setup initial settings object
            self._settings = {
                "window": {
                    "width": 650, "height": 250,
                    "vertical_layout": False,
                    "show_headers": False,
                    "auto_hide_ui": True,
                    "divider_width": 4, "divider_opacity": 100
                },
                "modules": default_modules,
                "ui": {"theme": "Midnight", "text_scale": 1.0}
            }
        else:
            win_s = self._settings.get("window", {})
            self.resize(win_s.get("width", 300), win_s.get("height", 650))
            self._layout_vertical = win_s.get("vertical_layout", True)
            self._show_headers = win_s.get("show_headers", True)
            self._auto_hide_ui = win_s.get("auto_hide_ui", False)
        
        # Loading Overlay (Skeleton wireframes + early layout)
        saved_mods = self._settings.get("modules", ["loudness", "stereometer", "spectrum"])
        self._loading_overlay = SkeletonLoadingOverlay(self, modules=saved_mods, vertical=self._layout_vertical)
        self._loading_overlay.resize(self.size())
        self._loading_overlay.raise_()
        self._loading_overlay.show()

        # Central widget
        central = QWidget()
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Title bar
        self.title_bar = TitleBar(self)
        main_layout.addWidget(self.title_bar)

        # Module splitter
        self.splitter = QSplitter(Qt.Vertical)
        self.splitter.setVisible(False)
        self.splitter.setHandleWidth(4)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.splitterMoved.connect(lambda *_: QTimer.singleShot(0, self._sanitize_splitter_sizes))
        main_layout.addWidget(self.splitter)
        
        self._layout_vertical = True
        self._update_ui_styles()

        # Resize grip
        self._grip = ResizeGrip(self)

        # Module list
        self._modules: list[BaseModule] = []
        self._move_mode_active = False

        # Connect title bar buttons
        self.title_bar.add_btn.clicked.connect(self._show_add_menu)
        self.title_bar.layout_btn.clicked.connect(self._toggle_layout)
        self.title_bar.gear_btn.clicked.connect(self._show_gear_menu)
        self.title_bar.move_btn.clicked.connect(self._toggle_move_mode)

        # Performance Profiler HUD
        self._perf_hud = None
        from PySide6.QtGui import QKeySequence, QShortcut
        self._perf_shortcut = QShortcut(QKeySequence("Ctrl+F3"), self)
        self._perf_shortcut.activated.connect(self.toggle_perf_hud)
        self._perf_shortcut_f3 = QShortcut(QKeySequence("F3"), self)
        self._perf_shortcut_f3.activated.connect(self.toggle_perf_hud)

        # Window & AppBar settings
        win_s = self._settings.get("window", {})
        self._appbar_edge = win_s.get("appbar_edge", "right")
        self._appbar_saved = win_s.get("appbar_active", False)
        self._appbar_ignore_screenshot_resets = win_s.get("appbar_ignore_screenshot_resets", True)
        self._appbar_active = False # Will be restored in finish_loading or docked early
        self._appbar_registered_hwnd = None

        raw_w = win_s.get("width", 320)
        raw_h = win_s.get("height", 600)
        raw_x = win_s.get("x")
        raw_y = win_s.get("y")
        x, y, w, h = self.sanitize_window_geometry(raw_x, raw_y, raw_w, raw_h, self._appbar_edge)
        self.resize(w, h)
        self.move(x, y)
        self._last_valid_normal_pos = (x, y)
        self._last_valid_normal_size = (w, h)
        
        self._layout_vertical = win_s.get("vertical_layout", True)
        if not self._layout_vertical:
            self.splitter.setOrientation(Qt.Horizontal)
            self.title_bar.layout_btn.setText("▤")
        
        # Apply UI settings
        ui_s = self._settings.get("ui", {})
        Fonts.TEXT_SCALE = ui_s.get("text_scale", 1.0)
        initial_theme = ui_s.get("theme", "Midnight")
        if initial_theme not in THEME_PRESETS:
            self._theme_load_warning = f"The saved theme '{initial_theme}' is not available. Falling back to Midnight."
            initial_theme = "Midnight"
        apply_theme(initial_theme, ui_s.get("color_overrides", {}))
        app = QApplication.instance()
        if app:
            app.setStyleSheet(build_stylesheet())
        
        self._show_headers = win_s.get("show_headers", True)
        self._auto_hide_ui = win_s.get("auto_hide_ui", False)
        self._appbar_callback_msg = 0
        self._appbar_taskbar_msg = 0
        self._appbar_repair_pending = False
        self._appbar_repair_force = False
        self._appbar_applying = False
        self._appbar_fullscreen_active = False
        self._appbar_health_failures = 0
        self._appbar_last_rect = None
        self._appbar_deep_repair_pending = False
        self._appbar_watchdog_timer = QTimer(self)
        self._appbar_watchdog_timer.setInterval(30000)
        self._appbar_watchdog_timer.timeout.connect(self._verify_appbar)
        self._loading_settings = True
        self._is_ready = False
        self._ghost_hover_ready = False
        self._ghost_ui_floating = None
        self._ghost_ui_visible = None
        self._ghost_hover_inside = False
        self._ghost_update_pending = False
        self._ghost_menu_depth = 0
        self._ghost_fade_anims = {}
        self._ghost_fade_duration_ms = 100
        self._update_ghost_mode()

        if self._appbar_saved:
            self._appbar_active = True
            self.show()
            self._apply_appbar()
            self._start_appbar_watchdog()
        
        # Divider settings (must be after apply_theme to use correct BORDER color)
        self._divider_width = win_s.get("divider_width", 4)
        self.splitter.setHandleWidth(int(math.ceil(self._divider_width)))
        self._set_divider_opacity(win_s.get("divider_opacity", 100))

        # Audio settings
        audio_s = self._settings.get("audio", {})
        self.audio_engine.gain_multiplier = audio_s.get("gain", 1.0)
        self.audio_engine.channels = audio_s.get("channels", 2)
        self._target_device_id = audio_s.get("device_full_id") # Persistent identifier
        self._current_device = audio_s.get("device_index") # Fallback index
        
        # Modules
        module_items = self._settings.get("modules")
        
        # Autosave Timer (every 60 seconds)
        self._autosave_timer = QTimer(self)
        self._autosave_timer.timeout.connect(self._periodic_save)
        self._autosave_timer.start(60000)
        
        if module_items is None:
            module_items = ["spectrum", "stereometer", "loudness"]
            
        for i, item in enumerate(module_items):
            m_key = item if isinstance(item, str) else item.get("key")
            m_config = {} if isinstance(item, str) else item.get("config", {})
            
            if self._splash:
                self._splash.set_progress(60 + int(30 * (i / len(module_items))), f"Loading {m_key}...")
                QApplication.processEvents()
            if hasattr(self, "_loading_overlay") and self._loading_overlay:
                self._loading_overlay.set_status(f"Loading {m_key}...")
                QApplication.processEvents()
            
            logging.info(f"UI: Loading module '{m_key}'")
            self.add_module(m_key, m_config)
            
        # Start audio stream (with slight delay to avoid startup clicks)
        QTimer.singleShot(500, self._start_audio_stream)
        QTimer.singleShot(800, self._show_config_load_warnings)

    def finish_loading(self):
        """Finalize UI layout and restore persistent state."""
        self._loading_settings = False
        self.splitter.setVisible(True)
        
        saved_sizes = self._settings.get("splitter_sizes", [])
        self._apply_module_size_constraints()
        if saved_sizes and len(saved_sizes) == self.splitter.count():
            self._sanitize_splitter_sizes(saved_sizes)
        else:
            # Fair distribution if no saved sizes or mismatch
            total = self.splitter.width() if not self._layout_vertical else self.splitter.height()
            count = self.splitter.count()
            if count > 0:
                self._sanitize_splitter_sizes([total // count] * count)
        
        if hasattr(self, "_loading_overlay") and self._loading_overlay:
            self._loading_overlay.fade_out()
        else:
            self._maybe_enable_ghost_hover()
        
        # Restore appbar after window is fully laid out (if not already active from early dock)
        if getattr(self, "_appbar_saved", False) and not getattr(self, "_appbar_active", False):
            # Immediate toggle during startup to avoid 'pushed down' glitch
            # Slight delay to ensure window handle is fully established and mapped
            self._toggle_appbar(True, delay=100)

        # Show Welcome if first run
        if getattr(self, "_is_first_run", False):
            self.welcome = WelcomeDialog(self)
            self.welcome.show()
            self.welcome.raise_()

    def _start_audio_stream(self):
        """Find best device match and start the audio stream."""
        self._refresh_devices()
        best_index = None
        
        # Try to match by full_id first
        if self._target_device_id:
            for d in self._devices:
                if d["full_id"] == self._target_device_id:
                    best_index = d["index"]
                    break
        
        # Fallback to index if valid
        if best_index is None and self._current_device is not None:
            if any(d["index"] == self._current_device for d in self._devices):
                best_index = self._current_device
        
        self._current_device = best_index
        self.audio_engine.error_occurred.connect(self._on_audio_error)
        
        logging.info(f"Audio: Attempting to start engine with device index {best_index}")
        self.audio_engine.start(best_index)
        self._is_ready = True
        self._maybe_enable_ghost_hover()

    #  Device Management

    def _refresh_devices(self):
        self._devices = AudioEngine.list_devices()

    def _select_device(self, device_index, full_id=None):
        self._current_device = device_index
        self._target_device_id = full_id
        self.audio_engine.start(device_index)

    def _select_channels(self, count):
        self.audio_engine.channels = count
        self.audio_engine.start(self._current_device, count)
        # Refresh all modules to adapt to new channel count
        for m in self._modules:
            if hasattr(m, "on_channels_changed"):
                m.on_channels_changed()
            m.update()

    #  Gear Menu (Device + Theme)

    def _show_gear_menu(self):
        from PySide6.QtWidgets import QWidgetAction, QSlider, QHBoxLayout, QLineEdit
        from PySide6.QtGui import QIntValidator
        menu = QMenu(self)
        
        def add_slider_setting(m, label, min_v, max_v, current_v, callback, is_float=False, step=1):
            action = QWidgetAction(self)
            widget = QWidget()
            layout = QHBoxLayout(widget)
            layout.setContentsMargins(10, 2, 10, 2)
            lbl = QLabel(label); lbl.setFixedWidth(100)
            
            scale = int(1 / step) if step != 1 and not is_float else 1
            
            slider = QSlider(Qt.Horizontal)
            slider.setRange(int(min_v * scale), int(max_v * scale))
            if is_float:
                slider.setValue(int(current_v * 100))
            else:
                slider.setValue(int(current_v * scale))
            slider.setFixedWidth(110)
            
            def format_val(v):
                if is_float: return str(v)
                real_v = v / scale
                return f"{real_v:g}" if step != 1 else str(int(real_v))
                
            val_edit = QLineEdit(format_val(slider.value()))
            val_edit.setFixedWidth(35); val_edit.setAlignment(Qt.AlignCenter)
            if step == 1 and not is_float:
                val_edit.setValidator(QIntValidator(min_v, max_v))
                
            def on_slider(v):
                val_edit.setText(format_val(v))
                if is_float: callback(v / 100.0)
                else: callback(v / scale)
                
            def on_edit():
                try:
                    text_v = float(val_edit.text())
                    if is_float:
                        v = int(text_v)
                        v = max(int(min_v), min(int(max_v), v))
                        slider.setValue(v); callback(v / 100.0)
                    else:
                        v = int(text_v * scale)
                        v = max(int(min_v * scale), min(int(max_v * scale), v))
                        slider.setValue(v); callback(v / scale)
                except: pass
                
            slider.valueChanged.connect(on_slider); val_edit.editingFinished.connect(on_edit)
            layout.addWidget(lbl); layout.addWidget(slider); layout.addWidget(val_edit)
            action.setDefaultWidget(widget); m.addAction(action)

        # 0. Current Engine Status
        for line in self.audio_engine.get_status_list():
            act = menu.addAction(line)
            act.setEnabled(False)
        menu.addSeparator()

        # 1. Device Management (Lazy loaded on hover)
        dev_menu = menu.addMenu("Audio Device")
        def populate_devices():
            if not dev_menu.isEmpty():
                return
            if not getattr(self, "_devices", None):
                self._refresh_devices()
            apis = {}
            for d in self._devices:
                apis.setdefault(d["hostapi"], []).append(d)
            for api_name, devs in apis.items():
                api_submenu = dev_menu.addMenu(api_name)
                for d in devs:
                    act = QAction(d["name"], self)
                    act.setCheckable(True)
                    act.setChecked(self._current_device == d["index"])
                    act.triggered.connect(lambda checked, i=d["index"], fid=d["full_id"]: self._select_device(i, fid))
                    api_submenu.addAction(act)
            dev_menu.addSeparator()
            rescan_act = dev_menu.addAction("Rescan Audio Devices")
            def rescan():
                self._refresh_devices()
                dev_menu.clear()
                populate_devices()
            rescan_act.triggered.connect(rescan)

        dev_menu.aboutToShow.connect(populate_devices)

        chan_menu = menu.addMenu("Channels")
        for c in [1, 2]:
            act = QAction("Mono" if c == 1 else "Stereo", self)
            act.setCheckable(True); act.setChecked(self.audio_engine.channels == c)
            act.triggered.connect(lambda checked, count=c: self._select_channels(count))
            chan_menu.addAction(act)

        menu.addSeparator()

        # 2. Main Application Settings
        add_slider_setting(menu, "Input Overdrive:", 0, 200, self.audio_engine.gain_multiplier, 
                           lambda v: setattr(self.audio_engine, "gain_multiplier", v), is_float=True)
        add_slider_setting(menu, "Global Label Scale:", 25, 300, Fonts.TEXT_SCALE, 
                           self._update_text_scale, is_float=True)
        
        menu.addSeparator()

        # 3. Appearance & UI (Lazy loaded on hover)
        theme_menu = menu.addMenu("Theme Presets")
        def populate_themes():
            if not theme_menu.isEmpty():
                return
            current = current_theme_name()
            for group_name, theme_names in THEME_GROUPS.items():
                group_sub = theme_menu.addMenu(group_name)
                for name in theme_names:
                    if name not in THEME_PRESETS and not name.endswith(" [!]"):
                        continue
                    act = QAction(name, self)
                    act.setCheckable(True)
                    act.setChecked(name == current)
                    act.triggered.connect(lambda checked, n=name: self._apply_theme(n))
                    group_sub.addAction(act)

        theme_menu.aboutToShow.connect(populate_themes)

        headers_act = menu.addAction("Show Module Headers")
        headers_act.setCheckable(True)
        headers_act.setChecked(self._show_headers)
        headers_act.triggered.connect(self._toggle_headers)

        ghost_act = menu.addAction("Auto-Hide Title Bar")
        ghost_act.setCheckable(True)
        ghost_act.setChecked(self._auto_hide_ui)
        ghost_act.triggered.connect(self._toggle_ghost_mode)
        
        move_mode_act = menu.addAction("Enable Move Mode")
        move_mode_act.setCheckable(True)
        move_mode_act.setChecked(getattr(self, "_move_mode_active", False))
        move_mode_act.triggered.connect(self._toggle_move_mode)
        
        appbar_menu = menu.addMenu("Dock as App Bar")
        toggle_act = appbar_menu.addAction("Enable App Bar")
        toggle_act.setCheckable(True)
        toggle_act.setChecked(self._appbar_active)
        toggle_act.triggered.connect(self._toggle_appbar)
        repair_act = appbar_menu.addAction("Repair App Bar")
        repair_act.setEnabled(self._appbar_active)
        repair_act.triggered.connect(self._manual_repair_appbar)
        
        appbar_menu.addSeparator()
        immune_act = appbar_menu.addAction("Prevent Screenshot Resets (Win+Shift+S)")
        immune_act.setCheckable(True)
        immune_act.setChecked(getattr(self, "_appbar_ignore_screenshot_resets", True))
        immune_act.triggered.connect(lambda checked: setattr(self, "_appbar_ignore_screenshot_resets", bool(checked)))
        
        appbar_menu.addSeparator()
        edge_group = QActionGroup(self)
        for edge in ["left", "right", "top", "bottom"]:
            a = appbar_menu.addAction(edge.capitalize())
            a.setCheckable(True)
            a.setChecked(edge == self._appbar_edge)
            a.triggered.connect(lambda checked, e=edge: self._set_appbar_edge(e))
            edge_group.addAction(a)
        
        menu.addSeparator()

        # 4. Unified Divider Settings
        add_slider_setting(menu, "Divider Width:", 0, 12, getattr(self, "_divider_width", self.splitter.handleWidth()), self._set_divider_width, step=0.5)
        add_slider_setting(menu, "Divider Opacity:", 0, 100, self._settings.get("window", {}).get("divider_opacity", 100), self._set_divider_opacity)

        menu.addSeparator()
        profile_menu = menu.addMenu("Settings Profiles")
        export_act = profile_menu.addAction("Save Profile as JSON...")
        export_act.triggered.connect(self._export_profile)
        import_act = profile_menu.addAction("Load Profile from JSON...")
        import_act.triggered.connect(self._import_profile)

        menu.addSeparator()
        perf_act = menu.addAction("Performance Profiler (Ctrl+F3)")
        perf_act.setCheckable(True)
        perf_act.setChecked(self._perf_hud is not None and self._perf_hud.isVisible())
        perf_act.triggered.connect(self.toggle_perf_hud)
        
        self.hold_ghost_ui()
        try:
            menu.exec(QCursor.pos())
        finally:
            self.release_ghost_ui()

    def _export_profile(self):
        from PySide6.QtWidgets import QFileDialog, QMessageBox

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Settings Profile",
            "pydspmeters-profile.json",
            "JSON Files (*.json)",
        )
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += ".json"

        if not SettingsManager.save_to_file(path, self._gather_settings()):
            QMessageBox.warning(self, "Profile Save Failed", "Could not save profile. Check the selected folder permissions.")

    def _import_profile(self):
        from PySide6.QtWidgets import QFileDialog, QMessageBox

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Settings Profile",
            "",
            "JSON Files (*.json)",
        )
        if not path:
            return

        settings = SettingsManager.load_from_file(path)
        if not isinstance(settings, dict) or not settings:
            load_error = SettingsManager.get_last_load_error()
            message = "That file does not look like a PyDSPMeters settings profile."
            if load_error:
                message = f"Could not load profile:\n{load_error.message}"
            QMessageBox.warning(self, "Profile Load Failed", message)
            return

        try:
            self._apply_profile_settings(settings)
            SettingsManager.save(self._gather_settings())
        except Exception as e:
            QMessageBox.warning(self, "Profile Load Failed", f"Could not apply profile:\n{e}")

    def toggle_perf_hud(self):
        """Toggle the standalone performance diagnostics window."""
        if self._perf_hud is None:
            from app.utils.perf_hud import PerformanceHUD
            self._perf_hud = PerformanceHUD()
            self._position_perf_hud()
            self._perf_hud.show()
            self._perf_hud.raise_()
            self._perf_hud.activateWindow()
        elif self._perf_hud.isVisible():
            self._perf_hud.hide()
        else:
            self._perf_hud.show()
            self._perf_hud.raise_()
            self._perf_hud.activateWindow()

    def _position_perf_hud(self):
        if not self._perf_hud:
            return
        screen = self.screen() or QApplication.primaryScreen()
        if not screen:
            return
        avail = screen.availableGeometry()
        hud_w = self._perf_hud.width()
        hud_h = self._perf_hud.height()

        # Place adjacent to main window without covering it
        edge = getattr(self, "_appbar_edge", "right")
        if edge == "right" or self.pos().x() > avail.center().x():
            target_x = max(avail.left() + 20, self.pos().x() - hud_w - 20)
        elif edge == "left":
            target_x = min(avail.right() - hud_w - 20, self.pos().x() + self.width() + 20)
        else:
            target_x = avail.left() + max(20, (avail.width() - hud_w) // 2)

        if edge == "top":
            target_y = min(avail.bottom() - hud_h - 20, self.pos().y() + self.height() + 20)
        elif edge == "bottom":
            target_y = max(avail.top() + 20, self.pos().y() - hud_h - 20)
        else:
            target_y = max(avail.top() + 30, min(avail.bottom() - hud_h - 30, self.pos().y() + 40))

        self._perf_hud.move(target_x, target_y)

    def _apply_profile_settings(self, settings: dict):
        if getattr(self, "_move_mode_active", False):
            self._toggle_move_mode(False)

        if getattr(self, "_appbar_active", False):
            self._appbar_active = False
            self._stop_appbar_watchdog()
            self._release_appbar()

        self._settings = settings
        win_s = settings.get("window", {})
        ui_s = settings.get("ui", {})
        audio_s = settings.get("audio", {})

        self._show_headers = win_s.get("show_headers", True)
        self._auto_hide_ui = win_s.get("auto_hide_ui", False)
        self._appbar_edge = win_s.get("appbar_edge", "right")
        self._appbar_saved = win_s.get("appbar_active", False)
        self._appbar_active = False

        if "width" in win_s or "height" in win_s or "x" in win_s or "y" in win_s:
            raw_w = win_s.get("width", self.width())
            raw_h = win_s.get("height", self.height())
            raw_x = win_s.get("x", self.pos().x())
            raw_y = win_s.get("y", self.pos().y())
            x, y, w, h = self.sanitize_window_geometry(raw_x, raw_y, raw_w, raw_h, self._appbar_edge)
            self.resize(w, h)
            self.move(x, y)
            self._last_valid_normal_pos = (x, y)
            self._last_valid_normal_size = (w, h)

        self._layout_vertical = win_s.get("vertical_layout", True)
        self.splitter.setOrientation(Qt.Vertical if self._layout_vertical else Qt.Horizontal)
        self.title_bar.layout_btn.setText("▥" if self._layout_vertical else "▤")

        Fonts.TEXT_SCALE = ui_s.get("text_scale", 1.0)
        theme_name = ui_s.get("theme", "Midnight")
        if theme_name not in THEME_PRESETS:
            self._theme_load_warning = f"The profile theme '{theme_name}' is not available. Falling back to Midnight."
            theme_name = "Midnight"
        apply_theme(theme_name, ui_s.get("color_overrides", {}))
        app = QApplication.instance()
        if app:
            app.setStyleSheet(build_stylesheet())

        self.audio_engine.gain_multiplier = audio_s.get("gain", 1.0)
        self.audio_engine.channels = audio_s.get("channels", 2)
        self._target_device_id = audio_s.get("device_full_id")
        self._current_device = audio_s.get("device_index")

        self._loading_settings = True
        for module in list(self._modules):
            self.remove_module(module)

        module_items = settings.get("modules") or ["spectrum", "stereometer", "loudness"]
        for item in module_items:
            m_key = item if isinstance(item, str) else item.get("key")
            m_config = {} if isinstance(item, str) else item.get("config", {})
            self.add_module(m_key, m_config)
        self._loading_settings = False

        for module in self._modules:
            module.header.setVisible(self._show_headers)
            if hasattr(module, "on_theme_changed"):
                module.on_theme_changed()
            module.update_theme()
            module.canvas.update()

        self._refresh_devices()
        best_index = None
        if self._target_device_id:
            for d in self._devices:
                if d["full_id"] == self._target_device_id:
                    best_index = d["index"]
                    break
        if best_index is None and self._current_device is not None:
            if any(d["index"] == self._current_device for d in self._devices):
                best_index = self._current_device
        self._current_device = best_index
        self.audio_engine.start(best_index, self.audio_engine.channels)

        self._divider_width = win_s.get("divider_width", 4)
        self.splitter.setHandleWidth(int(math.ceil(self._divider_width)))
        self._set_divider_opacity(win_s.get("divider_opacity", 100))

        saved_sizes = settings.get("splitter_sizes", [])
        self._apply_module_size_constraints()
        if saved_sizes and len(saved_sizes) == self.splitter.count():
            self._sanitize_splitter_sizes(saved_sizes)
        elif self.splitter.count() > 0:
            total = self.splitter.height() if self._layout_vertical else self.splitter.width()
            self._sanitize_splitter_sizes([total // self.splitter.count()] * self.splitter.count())

        self._update_ui_styles()
        self._update_ghost_mode()
        self._update_appbar_ui()
        if self._appbar_saved:
            self._toggle_appbar(True, delay=100)

    def _toggle_headers(self, show: bool):
        self._show_headers = show
        for m in self._modules:
            m.header.setVisible(show)

    def _toggle_ghost_mode(self, enabled: bool):
        self._auto_hide_ui = enabled
        self._update_ghost_mode()

    def _update_text_scale(self, scale):
        from app.theme import build_stylesheet
        Fonts.TEXT_SCALE = scale
        app = QApplication.instance()
        if app:
            app.setStyleSheet(build_stylesheet())
        for m in self._modules:
            m.update_theme()
            m.canvas.update()

    def _toggle_move_mode(self, enabled=None):
        if enabled is None:
            enabled = not self._move_mode_active
        self._move_mode_active = enabled
        self.title_bar.move_btn.setChecked(enabled)
        
        # Disable interaction risky buttons
        self.title_bar.add_btn.setEnabled(not enabled)
        self.title_bar.layout_btn.setEnabled(not enabled)
        
        if enabled:
            self.title_bar.add_btn.setToolTip("Locked during Move Mode")
            self.title_bar.layout_btn.setToolTip("Locked during Move Mode")
        else:
            self.title_bar.add_btn.setToolTip("Add module")
            # Only re-enable layout if NOT docked
            self.title_bar.layout_btn.setEnabled(not getattr(self, "_appbar_active", False))
            self._update_layout_tooltip()

        for m in self._modules:
            m.set_move_mode(enabled)

    def _apply_theme(self, name: str):
        if name.endswith(" [!]"):
            from PySide6.QtWidgets import QMessageBox
            from app.theme import INVALID_THEMES
            real_name = name[:-4]
            error_msg = INVALID_THEMES.get(real_name, "Unknown error")
            box = QMessageBox(self)
            box.setWindowTitle("Invalid Theme")
            box.setText(f"The theme '{real_name}' has malformed data in themes.json:\n\n{error_msg}")
            box.setIcon(QMessageBox.Warning)
            box.setStyleSheet(f"QMessageBox {{ background-color: {Colors.BG_DARK}; color: {Colors.TEXT}; }} QPushButton {{ background: {Colors.BG_HEADER}; color: {Colors.ACCENT}; border: 1px solid {Colors.BORDER}; padding: 4px 12px; }}")
            box.exec()
            return

        apply_theme(name, self._settings.get("ui", {}).get("color_overrides", {}))
        app = QApplication.instance()
        if app:
            app.setStyleSheet(build_stylesheet())
        self._update_ui_styles()
        for m in self._modules:
            if hasattr(m, "on_theme_changed"):
                m.on_theme_changed()
            m.update_theme() # New helper or manual update
        self._update_ghost_mode()

    def _on_audio_error(self, message):
        from PySide6.QtWidgets import QMessageBox
        # Use a non-blocking notification if possible, but for critical capture issues,
        # a message box is clearer when "nothing is happening".
        box = QMessageBox(self)
        box.setWindowTitle("Audio Engine Error")
        box.setText(message)
        box.setIcon(QMessageBox.Warning)
        # Style it slightly to match theme
        box.setStyleSheet(f"QMessageBox {{ background-color: {Colors.BG_DARK}; color: {Colors.TEXT}; }} QPushButton {{ background: {Colors.BG_HEADER}; color: {Colors.ACCENT}; border: 1px solid {Colors.BORDER}; padding: 4px 12px; }}")
        box.show()

    def _update_ui_styles(self):
        # Title Bar & Buttons
        if hasattr(self, "title_bar"):
            self.title_bar.update_theme()
        
        # Splitter handle
        self._set_divider_opacity(self._settings.get("window", {}).get("divider_opacity", 100))

    def _set_divider_width(self, w):
        self._divider_width = w
        self.splitter.setHandleWidth(int(math.ceil(w)))
        # Re-apply opacity/style because margin depends on width
        self._set_divider_opacity(self._settings.get("window", {}).get("divider_opacity", 100))
        
    def _set_divider_opacity(self, alpha_pct):
        win_s = self._settings.setdefault("window", {})
        win_s["divider_opacity"] = alpha_pct
        
        w = getattr(self, "_divider_width", self.splitter.handleWidth())
        if w <= 0:
            self.splitter.setStyleSheet("""
                QSplitter { background: transparent; }
                QSplitter::handle { background: transparent; margin: 0px; }
            """)
            return
            
        # 1. Parse base color from theme
        b_hex = Colors.BORDER
        if b_hex.startswith("#") and len(b_hex) == 9:
            c = QColor()
            c.setAlpha(int(b_hex[1:3], 16))
            c.setRed(int(b_hex[3:5], 16))
            c.setGreen(int(b_hex[5:7], 16))
            c.setBlue(int(b_hex[7:9], 16))
        else:
            c = QColor(b_hex)
            
        actual_alpha_pct = alpha_pct
        if w > 0 and w < 1.0:
            actual_alpha_pct = alpha_pct * w
            
        c.setAlpha(int(c.alpha() * actual_alpha_pct / 100))
        color_str = f"rgba({c.red()}, {c.green()}, {c.blue()}, {c.alpha()})"
        
        h_c = QColor(Colors.ACCENT)
        h_c.setAlpha(int(h_c.alpha() * actual_alpha_pct / 100))
        hover_str = f"rgba({h_c.red()}, {h_c.green()}, {h_c.blue()}, {h_c.alpha()})"

        m_val = 1 if w >= 3 else 0
        if self.splitter.orientation() == Qt.Vertical:
            margin = f"{m_val}px 40px"
        else:
            margin = f"40px {m_val}px"
            
        bg_c = QColor(Colors.BG_DARKEST)
        bg_rgba = f"rgba({bg_c.red()}, {bg_c.green()}, {bg_c.blue()}, {bg_c.alpha()})"

        self.splitter.setStyleSheet(f"""
            QSplitter {{
                background: {bg_rgba};
            }}
            QSplitter::handle {{
                background-color: {color_str if c.alpha() > 0 else "transparent"};
                margin: {margin};
                border-radius: 2px;
            }}
            QSplitter::handle:hover {{
                background-color: {hover_str};
            }}
        """)

    def _update_ghost_mode(self):
        started = time.perf_counter()
        self._ghost_update_pending = False
        # Ghost mode active if manually toggled OR if it's a 'Ghost/Glass/Transparent' theme
        theme = current_theme_name()
        is_transparent = "Transparent" in theme or "Glass" in theme
        ghost_active = self._auto_hide_ui or is_transparent
        
        main_layout = self.centralWidget().layout()
        if main_layout:
            if ghost_active:
                if self._ghost_ui_floating is not True or self.title_bar.parentWidget() != self:
                    main_layout.removeWidget(self.title_bar)
                    self.title_bar.setParent(self)
                    self.title_bar.raise_()
                    self._ghost_ui_floating = True
                target_geometry = QRect(0, 0, self.width(), 28)
                if self.title_bar.geometry() != target_geometry:
                    self.title_bar.setGeometry(target_geometry)
            else:
                if self._ghost_ui_floating is not False or self.title_bar.parentWidget() != self.centralWidget():
                    self.title_bar.setParent(self.centralWidget())
                    main_layout.insertWidget(0, self.title_bar)
                    self._ghost_ui_floating = False
                    
        show = not ghost_active or self._ghost_menu_depth > 0 or (self._ghost_hover_ready and self._ghost_hover_inside)
        if self._ghost_ui_visible is not show:
            self._fade_ghost_widget(self.title_bar, "title_bar", show)
            self._fade_ghost_widget(self._grip, "resize_grip", show)
            self._ghost_ui_visible = show
        perf_stats.record_timing("window.ghost_mode_update", time.perf_counter() - started)

    def _fade_ghost_widget(self, widget, key, visible):
        if widget is None:
            return

        anim = self._ghost_fade_anims.pop(key, None)
        if anim is not None:
            anim.stop()

        was_visible = widget.isVisible()
        effect = widget.graphicsEffect()
        if not isinstance(effect, QGraphicsOpacityEffect):
            if was_visible == visible:
                return
            effect = QGraphicsOpacityEffect(widget)
            widget.setGraphicsEffect(effect)
            effect.setOpacity(1.0 if was_visible else 0.0)

        if visible:
            widget.setVisible(True)

        start = effect.opacity() if was_visible else 0.0
        end = 1.0 if visible else 0.0
        if abs(start - end) < 0.01:
            effect.setOpacity(end)
            widget.setVisible(visible)
            return

        fade = QPropertyAnimation(effect, b"opacity", self)
        fade.setDuration(self._ghost_fade_duration_ms)
        fade.setStartValue(start)
        fade.setEndValue(end)
        fade.setEasingCurve(QEasingCurve.OutCubic)

        def finish():
            if not visible:
                widget.setVisible(False)
            effect.setOpacity(end)
            self._ghost_fade_anims.pop(key, None)

        fade.finished.connect(finish)
        self._ghost_fade_anims[key] = fade
        fade.start()

    def hold_ghost_ui(self):
        self._ghost_menu_depth += 1
        self._schedule_ghost_mode_update()

    def release_ghost_ui(self):
        self._ghost_menu_depth = max(0, self._ghost_menu_depth - 1)
        self._ghost_hover_inside = self.rect().contains(self.mapFromGlobal(QCursor.pos()))
        self._schedule_ghost_mode_update()

    def _schedule_ghost_mode_update(self):
        if self._ghost_update_pending:
            return
        self._ghost_update_pending = True
        QTimer.singleShot(16, self._update_ghost_mode)

    def enterEvent(self, event):
        if self._ghost_hover_ready:
            self._ghost_hover_inside = True
            self._schedule_ghost_mode_update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self._ghost_hover_ready:
            self._ghost_hover_inside = self.rect().contains(self.mapFromGlobal(QCursor.pos()))
            self._schedule_ghost_mode_update()
        super().leaveEvent(event)

    #  App Bar

    def nativeEvent(self, event_type, message):
        import sys
        if sys.platform != "win32":
            return False, 0
        if getattr(self, "_appbar_applying", False):
            return False, 0
        try:
            import ctypes.wintypes as wt

            msg = wt.MSG.from_address(int(message))
            WM_ACTIVATE = 0x0006
            WM_ACTIVATEAPP = 0x001C
            WM_SETTINGCHANGE = 0x001A
            WM_DISPLAYCHANGE = 0x007E
            WM_POWERBROADCAST = 0x0218

            if msg.message in (WM_ACTIVATE, WM_ACTIVATEAPP):
                if int(msg.wParam) != 0:
                    self._rescue_window_if_offscreen()
            elif msg.message == WM_POWERBROADCAST:
                QTimer.singleShot(1500, self._on_display_or_power_changed)
            elif self._appbar_taskbar_msg and msg.message == self._appbar_taskbar_msg:
                self._schedule_appbar_repair(delay=1000, force_register=True)
            elif self._appbar_callback_msg and msg.message == self._appbar_callback_msg:
                self._handle_appbar_callback(int(msg.wParam), int(msg.lParam))
            elif msg.message in (WM_SETTINGCHANGE, WM_DISPLAYCHANGE):
                QTimer.singleShot(1200, self._on_display_or_power_changed)
        except Exception:
            return False, 0
        return False, 0

    def _on_display_or_power_changed(self):
        """Handle screen resolution changes or waking from sleep."""
        if getattr(self, "_appbar_active", False) or getattr(self, "_appbar_saved", False):
            if not getattr(self, "_appbar_fullscreen_active", False):
                self._schedule_appbar_repair(delay=0, force_register=True)
        else:
            self._rescue_window_if_offscreen()

    def _is_snipping_tool_active(self):
        import sys
        if sys.platform != "win32":
            return False
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            if hwnd:
                length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                buf = ctypes.create_unicode_buffer(length + 1)
                ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
                t = buf.value.lower()
                if "snipping" in t or "screen clipping" in t or "snip & sketch" in t:
                    return True
        except Exception:
            pass
        return False

    def _handle_appbar_callback(self, notification, value):
        ABN_STATECHANGE = 0
        ABN_POSCHANGED = 1
        ABN_FULLSCREENAPP = 2
        ABN_WINDOWARRANGE = 3

        if notification == ABN_FULLSCREENAPP:
            fullscreen_active = bool(value)
            self._appbar_fullscreen_active = fullscreen_active
            self._set_appbar_topmost(not fullscreen_active)
            if fullscreen_active:
                return
            if getattr(self, "_appbar_ignore_screenshot_resets", False):
                return
            self._schedule_appbar_repair(delay=1200, force_register=True)
            return

        if notification == ABN_POSCHANGED:
            if getattr(self, "_appbar_ignore_screenshot_resets", True):
                if self._is_snipping_tool_active() or self._appbar_geometry_matches():
                    return
            self._schedule_appbar_repair(delay=250, force_register=False)
        elif notification in (ABN_STATECHANGE, ABN_WINDOWARRANGE):
            if getattr(self, "_appbar_ignore_screenshot_resets", True) and self._is_snipping_tool_active():
                return
            self._schedule_appbar_repair(delay=700, force_register=False)

    def _toggle_appbar(self, checked, delay=100):
        self._appbar_active = checked
        if checked:
            self._start_appbar_watchdog()
            # Need a slight delay to ensure window is mapped and geometry is stable
            if delay > 0:
                QTimer.singleShot(delay, self._apply_appbar)
            else:
                self._apply_appbar()
        else:
            self._stop_appbar_watchdog()
            self._release_appbar()
            
        self._update_appbar_ui()

    def _start_appbar_watchdog(self):
        if not self._appbar_watchdog_timer.isActive():
            self._appbar_watchdog_timer.start()

    def _stop_appbar_watchdog(self):
        if self._appbar_watchdog_timer.isActive():
            self._appbar_watchdog_timer.stop()
        self._appbar_repair_pending = False
        self._appbar_repair_force = False
        self._appbar_fullscreen_active = False
        self._appbar_deep_repair_pending = False

    def _verify_appbar(self):
        if not getattr(self, "_appbar_active", False):
            if self.pos().x() <= -5000 or self.pos().y() <= -5000:
                self._rescue_window_if_offscreen()
            self._stop_appbar_watchdog()
            return
        if getattr(self, "_appbar_fullscreen_active", False):
            return
        if getattr(self, "_appbar_ignore_screenshot_resets", True) and self._is_snipping_tool_active():
            return
        if self._appbar_health_ok():
            self._appbar_health_failures = 0
            return

        self._appbar_health_failures += 1
        if self._appbar_health_failures >= 4:
            self._rescue_window_if_offscreen()
            self._appbar_health_failures = 0
        elif self._appbar_health_failures >= 2:
            self._schedule_appbar_deep_repair(delay=250)
        else:
            self._schedule_appbar_repair(delay=0, force_register=True)

    def _schedule_appbar_repair(self, delay=250, force_register=False):
        if not getattr(self, "_appbar_active", False):
            return
        self._appbar_repair_force = self._appbar_repair_force or force_register
        if self._appbar_repair_pending:
            return
        self._appbar_repair_pending = True
        QTimer.singleShot(delay, self._repair_appbar)

    def _repair_appbar(self):
        self._appbar_repair_pending = False
        force_register = self._appbar_repair_force
        self._appbar_repair_force = False
        if not getattr(self, "_appbar_active", False):
            return
        if getattr(self, "_appbar_ignore_screenshot_resets", True) and self._is_snipping_tool_active():
            return
        if force_register:
            self._release_appbar(restore_window=False)
        self._apply_appbar()

    def _manual_repair_appbar(self):
        if not getattr(self, "_appbar_active", False):
            self._toggle_appbar(True, delay=0)
            return
        self._appbar_health_failures = 0
        self._schedule_appbar_deep_repair(delay=0)

    def _appbar_health_ok(self):
        if not getattr(self, "_appbar_active", False):
            return True
        if not self.isVisible():
            return False
        geom = self.geometry()
        if geom.x() <= -5000 or geom.y() <= -5000:
            return False
        if not self._appbar_geometry_matches():
            return False
        import sys
        if sys.platform == "win32":
            try:
                import ctypes
                hwnd = int(self._appbar_registered_hwnd or int(self.winId()))
                if hwnd and not ctypes.windll.user32.IsWindow(hwnd):
                    return False
            except Exception:
                pass
        return True

    def _appbar_geometry_matches(self):
        current = self.geometry()
        if current.x() <= -5000 or current.y() <= -5000:
            return False
        rect = self._appbar_last_rect or self.geometry()
        current = self.geometry()
        tolerance = 3
        return (
            abs(current.x() - rect.x()) <= tolerance
            and abs(current.y() - rect.y()) <= tolerance
            and abs(current.width() - rect.width()) <= tolerance
            and abs(current.height() - rect.height()) <= tolerance
        )

    def _schedule_appbar_deep_repair(self, delay=250):
        if not getattr(self, "_appbar_active", False):
            return
        if self._appbar_deep_repair_pending:
            return
        self._appbar_deep_repair_pending = True
        QTimer.singleShot(delay, self._deep_repair_appbar)

    def _deep_repair_appbar(self):
        self._appbar_deep_repair_pending = False
        if not getattr(self, "_appbar_active", False):
            return
        self._release_appbar(restore_window=False)
        self._appbar_registered_hwnd = None
        self._appbar_last_rect = None
        self._appbar_health_failures = 0
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.show()
        QApplication.processEvents()
        self._apply_appbar()

    def _update_appbar_ui(self):
        """Sync UI components with AppBar state."""
        is_docked = getattr(self, "_appbar_active", False)
        
        # Lock/Unlock layout button
        self.title_bar.layout_btn.setEnabled(not is_docked)
        
        if is_docked:
            self.title_bar.layout_btn.setToolTip("Layout locked while docked to edge")
        else:
            self._update_layout_tooltip()

    def _set_appbar_edge(self, edge):
        self._appbar_edge = edge
        if self._appbar_active:
            self._release_appbar()
            self._apply_appbar()

    def _set_appbar_topmost(self, enabled):
        import sys
        if sys.platform != "win32":
            return
        try:
            import ctypes

            hwnd = int(self._appbar_registered_hwnd or int(self.winId()))
            HWND_TOPMOST = -1
            HWND_NOTOPMOST = -2
            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002
            SWP_NOACTIVATE = 0x0010
            flags = SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE
            insert_after = HWND_TOPMOST if enabled else HWND_NOTOPMOST
            ctypes.windll.user32.SetWindowPos(hwnd, insert_after, 0, 0, 0, 0, flags)
        except Exception as e:
            logging.debug(f"AppBar: Failed to update topmost state: {e}")

    def _apply_appbar(self):
        """Dock the window to the chosen screen edge."""
        import sys
        
        if self.pos().x() <= -5000 or self.pos().y() <= -5000:
            screen = QApplication.primaryScreen()
        else:
            screen = self.screen() or QApplication.screenAt(self.geometry().center()) or QApplication.primaryScreen()
        if not screen: return
        sg = screen.geometry()
        if sg.width() <= 0 or sg.height() <= 0:
            return
        thickness = self.width() if self._appbar_edge in ("left", "right") else self.height()
        thickness = max(40, thickness)
        
        if self._appbar_edge == "left":
            target_rect = QRect(sg.left(), sg.top(), thickness, sg.height())
        elif self._appbar_edge == "right":
            target_rect = QRect(sg.right() - thickness + 1, sg.top(), thickness, sg.height())
        elif self._appbar_edge == "top":
            target_rect = QRect(sg.left(), sg.top(), sg.width(), thickness)
        else:
            target_rect = QRect(sg.left(), sg.bottom() - thickness + 1, sg.width(), thickness)
            
        if sys.platform == "win32":
            self._apply_appbar_win32(thickness, sg, target_rect)
        else:
            self.setGeometry(target_rect)
            if sys.platform == "linux":
                # Ensure xprop runs AFTER setGeometry so the window is mapped
                QTimer.singleShot(100, lambda: self._apply_appbar_linux(target_rect))

    def _apply_appbar_win32(self, thickness, sg, target_rect):
        try:
            import ctypes
            import ctypes.wintypes as wt
            self._appbar_applying = True

            # Set flags before first registration; doing it on every refresh can recreate the handle.
            if self._appbar_registered_hwnd is None:
                self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
                self.show()
                QApplication.processEvents()

            ABM_NEW = 0x00000000
            ABM_QUERYPOS = 0x00000002
            ABM_SETPOS = 0x00000003
            ABM_ACTIVATE = 0x00000006
            ABM_WINDOWPOSCHANGED = 0x00000009
            ABE_LEFT, ABE_TOP, ABE_RIGHT, ABE_BOTTOM = 0, 1, 2, 3

            class APPBARDATA(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wt.DWORD), ("hWnd", wt.HWND), ("uCallbackMessage", wt.UINT),
                    ("uEdge", wt.UINT), ("rc", wt.RECT), ("lParam", ctypes.c_long),
                ]

            edge_map = {"left": ABE_LEFT, "top": ABE_TOP, "right": ABE_RIGHT, "bottom": ABE_BOTTOM}
            uEdge = edge_map.get(self._appbar_edge, ABE_RIGHT)

            hwnd = int(self.winId())
            abd = APPBARDATA()
            abd.cbSize = ctypes.sizeof(APPBARDATA)
            abd.hWnd = hwnd
            abd.uEdge = uEdge

            if uEdge == ABE_LEFT:
                abd.rc = wt.RECT(sg.left(), sg.top(), sg.left() + thickness, sg.bottom())
            elif uEdge == ABE_RIGHT:
                abd.rc = wt.RECT(sg.right() - thickness, sg.top(), sg.right(), sg.bottom())
            elif uEdge == ABE_TOP:
                abd.rc = wt.RECT(sg.left(), sg.top(), sg.right(), sg.top() + thickness)
            elif uEdge == ABE_BOTTOM:
                abd.rc = wt.RECT(sg.left(), sg.bottom() - thickness, sg.right(), sg.bottom())

            # Windows AppBar Trick: Register off-screen (-10k) then Query/Set position.
            # This bypasses the 'Workspace Avoidance' logic that would otherwise push the window down
            # when it reserves the space it's already sitting in.
            shell32 = ctypes.windll.shell32
            user32 = ctypes.windll.user32
            if not self._appbar_callback_msg:
                self._appbar_callback_msg = user32.RegisterWindowMessageW("PyDSPMetersAppBarMessage")
            if not self._appbar_taskbar_msg:
                self._appbar_taskbar_msg = user32.RegisterWindowMessageW("TaskbarCreated")
            abd.uCallbackMessage = self._appbar_callback_msg

            registered_new = False
            if self._appbar_registered_hwnd and self._appbar_registered_hwnd != hwnd:
                self._release_appbar_win32(restore_window=False)

            if self._appbar_registered_hwnd != hwnd:
                result = shell32.SHAppBarMessage(ABM_NEW, ctypes.byref(abd))
                if not result:
                    logging.warning("AppBar: ABM_NEW returned 0; attempting position update anyway.")
                self._appbar_registered_hwnd = hwnd
                registered_new = True

            if registered_new:
                # Send to Narnia immediately via direct Win32 call (bypasses Qt event queue)
                # SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOZORDER = 0x0001 | 0x0010 | 0x0004 = 0x0015
                user32.SetWindowPos(hwnd, 0, -10000, -10000, 0, 0, 0x0015)
                QApplication.processEvents()
            
            # Query and set the reserved space
            shell32.SHAppBarMessage(ABM_QUERYPOS, ctypes.byref(abd))
            shell32.SHAppBarMessage(ABM_SETPOS, ctypes.byref(abd))
            shell32.SHAppBarMessage(ABM_ACTIVATE, ctypes.byref(abd))

            final_rect = QRect(abd.rc.left, abd.rc.top,
                               abd.rc.right - abd.rc.left, abd.rc.bottom - abd.rc.top)
            if final_rect.width() <= 10 or final_rect.height() <= 10:
                final_rect = target_rect

            self._appbar_last_rect = QRect(final_rect)
            
            # Whiplash back to the reserved space
            self.setGeometry(final_rect)
            self.show()
            QApplication.processEvents()
            if not getattr(self, "_appbar_fullscreen_active", False):
                self._set_appbar_topmost(True)
            shell32.SHAppBarMessage(ABM_WINDOWPOSCHANGED, ctypes.byref(abd))
            self._appbar_health_failures = 0
            
        except Exception as e:
            logging.error(f"AppBar: Failed to dock (Win32): {e}")
            self._appbar_health_failures += 1
            self.setGeometry(target_rect)
            self.show()
            if self._appbar_health_failures >= 4:
                self._release_appbar_win32(restore_window=True)
                self.setGeometry(target_rect)
                self.show()
        finally:
            self._appbar_applying = False
            if self.pos().x() <= -5000 or self.pos().y() <= -5000:
                self.setGeometry(target_rect)
                self.show()

    def _apply_appbar_linux(self, rect):
        import subprocess
        try:
            hwnd = str(int(self.winId()))
            l, r, t, b = 0, 0, 0, 0
            lsy, ley, rsy, rey, tsx, tex, bsx, bex = 0, 0, 0, 0, 0, 0, 0, 0
            
            if self._appbar_edge == "left":
                l = rect.width(); lsy = rect.top(); ley = rect.bottom()
            elif self._appbar_edge == "right":
                r = rect.width(); rsy = rect.top(); rey = rect.bottom()
            elif self._appbar_edge == "top":
                t = rect.height(); tsx = rect.left(); tex = rect.right()
            elif self._appbar_edge == "bottom":
                b = rect.height(); bsx = rect.left(); bex = rect.right()

            strut = f"{l}, {r}, {t}, {b}"
            strut_partial = f"{l}, {r}, {t}, {b}, {lsy}, {ley}, {rsy}, {rey}, {tsx}, {tex}, {bsx}, {bex}"
            
            subprocess.run(["xprop", "-id", hwnd, "-f", "_NET_WM_WINDOW_TYPE", "32a", "-set", "_NET_WM_WINDOW_TYPE", "_NET_WM_WINDOW_TYPE_DOCK"], capture_output=True)
            subprocess.run(["xprop", "-id", hwnd, "-f", "_NET_WM_STATE", "32a", "-set", "_NET_WM_STATE", "_NET_WM_STATE_ABOVE, _NET_WM_STATE_STICKY"], capture_output=True)
            subprocess.run(["xprop", "-id", hwnd, "-f", "_NET_WM_STRUT", "32c", "-set", "_NET_WM_STRUT", strut], capture_output=True)
            subprocess.run(["xprop", "-id", hwnd, "-f", "_NET_WM_STRUT_PARTIAL", "32c", "-set", "_NET_WM_STRUT_PARTIAL", strut_partial], capture_output=True)
        except Exception as e:
            print(f"[AppBar] Linux xprop failed: {e}")

    def _release_appbar(self, restore_window=True):
        """Release the appbar reservation."""
        import sys
        if sys.platform == "win32":
            self._release_appbar_win32(restore_window=restore_window)
        elif sys.platform == "linux":
            self._release_appbar_linux(restore_window=restore_window)

    def _release_appbar_win32(self, restore_window=True):
        try:
            import ctypes
            import ctypes.wintypes as wt

            ABM_REMOVE = 0x00000001

            class APPBARDATA(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wt.DWORD), ("hWnd", wt.HWND), ("uCallbackMessage", wt.UINT),
                    ("uEdge", wt.UINT), ("rc", wt.RECT), ("lParam", ctypes.c_long),
                ]

            abd = APPBARDATA()
            abd.cbSize = ctypes.sizeof(APPBARDATA)
            abd.hWnd = int(self._appbar_registered_hwnd or int(self.winId()))
            ctypes.windll.shell32.SHAppBarMessage(ABM_REMOVE, ctypes.byref(abd))
            self._appbar_registered_hwnd = None
            self._appbar_last_rect = None
            self._appbar_health_failures = 0
            
            # Restore standard window flags to ensure taskbar visibility and correct behavior
            if restore_window:
                self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
                self.show()
                self._rescue_window_if_offscreen()
        except Exception as e:
            print(f"[AppBar] Failed to release (Win32): {e}")

    def _release_appbar_linux(self, restore_window=True):
        import subprocess
        try:
            hwnd = str(int(self.winId()))
            subprocess.run(["xprop", "-id", hwnd, "-remove", "_NET_WM_STRUT"], capture_output=True)
            subprocess.run(["xprop", "-id", hwnd, "-remove", "_NET_WM_STRUT_PARTIAL"], capture_output=True)
            subprocess.run(["xprop", "-id", hwnd, "-remove", "_NET_WM_WINDOW_TYPE"], capture_output=True)
            
            # Restore standard window flags
            if restore_window:
                self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
                self.show()
        except Exception as e:
            print(f"[AppBar] Failed to release (Linux): {e}")

    #  Module Management

    def _module_minimum_extent(self):
        return MODULE_MIN_HEIGHT if self.splitter.orientation() == Qt.Vertical else MODULE_MIN_WIDTH

    def _apply_module_size_constraints(self):
        count = self.splitter.count()
        if count <= 0:
            self.setMinimumSize(40, 40)
            return

        for i in range(count):
            widget = self.splitter.widget(i)
            if widget is None:
                continue
            widget.setMinimumSize(MODULE_MIN_WIDTH, MODULE_MIN_HEIGHT)
            self.splitter.setCollapsible(i, False)

        handle_total = max(0, count - 1) * max(0, self.splitter.handleWidth())
        if self.splitter.orientation() == Qt.Vertical:
            title_h = 28 if self.title_bar.parentWidget() == self.centralWidget() and self.title_bar.isVisible() else 0
            self.setMinimumSize(MODULE_MIN_WIDTH, title_h + count * MODULE_MIN_HEIGHT + handle_total)
        else:
            self.setMinimumSize(count * MODULE_MIN_WIDTH + handle_total, max(40, MODULE_MIN_HEIGHT))

    def _sanitize_splitter_sizes(self, sizes=None):
        count = self.splitter.count()
        if count <= 0:
            return

        sizes = list(self.splitter.sizes() if sizes is None else sizes)
        if len(sizes) != count:
            total = self.splitter.height() if self.splitter.orientation() == Qt.Vertical else self.splitter.width()
            sizes = [max(self._module_minimum_extent(), total // count)] * count

        min_extent = self._module_minimum_extent()
        total = max(sum(sizes), min_extent * count)
        sizes = [max(min_extent, int(s)) for s in sizes]
        overflow = sum(sizes) - total

        if overflow > 0:
            for i in sorted(range(count), key=lambda idx: sizes[idx], reverse=True):
                room = sizes[i] - min_extent
                take = min(room, overflow)
                sizes[i] -= take
                overflow -= take
                if overflow <= 0:
                    break

        self.splitter.setSizes(sizes)

    def _show_add_menu(self):
        menu = QMenu(self)
        for key, info in MODULE_REGISTRY.items():
            action = QAction(info["display_name"], self)
            action.triggered.connect(lambda checked, k=key: self.add_module(k))
            menu.addAction(action)
        self.hold_ghost_ui()
        try:
            menu.exec(QCursor.pos())
        finally:
            self.release_ghost_ui()

    def add_module(self, module_key: str, config: dict = None):
        if module_key not in MODULE_REGISTRY:
            return
        cls = MODULE_REGISTRY[module_key]["class"]
        module = cls(self.audio_engine)
        module.module_key = module_key # Store for saving
        logging.info(f"Module '{module_key}' (internal: {cls.__name__}) initialized.")
        module.close_requested.connect(self.remove_module)
        module.move_requested.connect(self._move_module)
        module.move_mode_exit_requested.connect(lambda: self._toggle_move_mode(False))
        
        # Self-test for stability
        module.self_test()
        
        if config:
            module.apply_settings(config)
            
        # Apply header visibility
        module.header.setVisible(self._show_headers)
        
        self.splitter.addWidget(module)
        self._modules.append(module)
        self._apply_module_size_constraints()
        
        # Ensure new module is visible
        if self._loading_settings:
            return # Don't redistribute while loading, we'll set sizes once at the end
            
        sizes = self.splitter.sizes()
        if len(sizes) > 1:
            total = sum(sizes)
            if total > 0:
                # Manual add: Try to give new module a fair share without flattening everyone
                # We give the new module 1/Nth of the space, and reduce others proportionally
                new_share = total // len(sizes)
                remaining = total - new_share
                old_total = sum(sizes[:-1])
                if old_total > 0:
                    new_sizes = [int(s * remaining / old_total) for s in sizes[:-1]]
                    new_sizes.append(new_share)
                    # Adjust for rounding errors
                    diff = total - sum(new_sizes)
                    new_sizes[0] += diff
                    self._sanitize_splitter_sizes(new_sizes)
                else:
                    self._sanitize_splitter_sizes([total // len(sizes)] * len(sizes))
            else:
                self._sanitize_splitter_sizes([100] * len(sizes))

    def remove_module(self, module: BaseModule):
        if module in self._modules:
            self._modules.remove(module)
            module.cleanup()
            module.setParent(None)
            module.deleteLater()
            self._apply_module_size_constraints()
            self._sanitize_splitter_sizes()

    def _move_module(self, module, direction):
        idx = self.splitter.indexOf(module)
        new_idx = idx + direction
        if 0 <= new_idx < self.splitter.count():
            # In QSplitter, insertWidget moves the widget if it's already there
            self.splitter.insertWidget(new_idx, module)
            # Sync internal list order so it saves correctly
            if module in self._modules:
                self._modules.pop(self._modules.index(module))
                self._modules.insert(new_idx, module)
            self._apply_module_size_constraints()
            self._sanitize_splitter_sizes()

    def _toggle_layout(self):
        if getattr(self, "_appbar_active", False):
            return
            
        self._layout_vertical = not self._layout_vertical
        if self._layout_vertical:
            self.splitter.setOrientation(Qt.Vertical)
            self.title_bar.layout_btn.setText("▥")
            self.title_bar.layout_btn.setToolTip("Switch to Horizontal layout")
        else:
            self.splitter.setOrientation(Qt.Horizontal)
            self.title_bar.layout_btn.setText("▤")
            self.title_bar.layout_btn.setToolTip("Switch to Vertical layout")
        self._apply_module_size_constraints()
        self._sanitize_splitter_sizes()
            
    def _update_layout_tooltip(self):
        if self._layout_vertical:
            self.title_bar.layout_btn.setToolTip("Switch to Horizontal layout")
        else:
            self.title_bar.layout_btn.setToolTip("Switch to Vertical layout")
            
        # Refresh divider style to update margins and respect opacity
        self._set_divider_opacity(self._settings.get("window", {}).get("divider_opacity", 100))

    #  Snapping
    
    def snap_to_edge(self):
        screen = QApplication.primaryScreen()
        if not screen:
            return
        
        avail = screen.availableGeometry()
        full = screen.geometry()
        x, y = self.pos().x(), self.pos().y()
        w, h = self.width(), self.height()
        t = self.SNAP_THRESHOLD

        #  Horizontal Snapping (Position & Size)
        
        # Snap width to full/avail width
        if abs(w - avail.width()) < t:
            w = avail.width()
        elif abs(w - full.width()) < t:
            w = full.width()

        # Snap X position
        # Prioritize 'avail' (above taskbar) but allow 'full' (behind taskbar)
        for rect in [avail, full]:
            if abs(x - rect.left()) < t:
                x = rect.left()
                break
            if abs(x + w - rect.right()) < t:
                x = rect.right() - w
                break

        # Center horizontal
        cx = full.left() + full.width() // 2
        if abs(x + w // 2 - cx) < t:
            x = cx - w // 2

        #  Vertical Snapping (Position & Size)
        
        # Snap height to full/avail height
        if abs(h - avail.height()) < t:
            h = avail.height()
        elif abs(h - full.height()) < t:
            h = full.height()

        # Snap Y position
        for rect in [avail, full]:
            if abs(y - rect.top()) < t:
                y = rect.top()
                break
            if abs(y + h - rect.bottom()) < t:
                y = rect.bottom() - h
                break

        # Apply changes
        if (w, h) != (self.width(), self.height()):
            self.resize(w, h)
        self.move(x, y)

    #  Window Geometry Sanitization & Recovery

    @classmethod
    def is_rect_visible_on_any_screen(cls, rect: QRect, min_overlap: int = 20) -> bool:
        """Check if a QRect has sufficient visible overlap on any connected screen."""
        if rect.x() <= -5000 or rect.y() <= -5000 or rect.width() <= 0 or rect.height() <= 0:
            return False
        app = QApplication.instance()
        screens = app.screens() if app else []
        if not screens:
            return True
        for s in screens:
            inter = rect.intersected(s.geometry())
            req_w = min(min_overlap, max(5, rect.width() // 2))
            req_h = min(min_overlap, max(5, rect.height() // 2))
            if inter.width() >= req_w and inter.height() >= req_h:
                return True
        return False

    @classmethod
    def sanitize_window_geometry(cls, x, y, w, h, default_edge="right"):
        """Clamp window position and dimensions to safe, visible coordinates."""
        min_w = MODULE_MIN_WIDTH
        min_h = MODULE_MIN_HEIGHT
        w = max(min_w, min(int(w or 320), 7680))
        h = max(min_h, min(int(h or 600), 4320))

        app = QApplication.instance()
        screen = app.primaryScreen() if app else None
        avail = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)

        if x is None or y is None:
            if default_edge == "left":
                return avail.left(), avail.top(), w, avail.height()
            elif default_edge == "right":
                return avail.right() - w + 1, avail.top(), w, avail.height()
            elif default_edge == "top":
                return avail.left(), avail.top(), avail.width(), h
            elif default_edge == "bottom":
                return avail.left(), avail.bottom() - h + 1, avail.width(), h
            else:
                return (
                    avail.left() + max(0, (avail.width() - w) // 2),
                    avail.top() + max(0, (avail.height() - h) // 2),
                    w,
                    h,
                )

        try:
            x = int(x)
            y = int(y)
        except (ValueError, TypeError):
            x = avail.right() - w + 1
            y = avail.top()

        target_rect = QRect(x, y, w, h)
        if cls.is_rect_visible_on_any_screen(target_rect):
            return x, y, w, h

        # If offscreen or limbo, place safely on primary screen
        if default_edge == "right":
            return avail.right() - w + 1, avail.top(), w, min(h, avail.height())
        elif default_edge == "left":
            return avail.left(), avail.top(), w, min(h, avail.height())
        elif default_edge == "top":
            return avail.left(), avail.top(), min(w, avail.width()), h
        elif default_edge == "bottom":
            return avail.left(), avail.bottom() - h + 1, min(w, avail.width()), h
        else:
            return (
                avail.left() + max(0, (avail.width() - w) // 2),
                avail.top() + max(0, (avail.height() - h) // 2),
                min(w, avail.width()),
                min(h, avail.height()),
            )

    def _rescue_window_if_offscreen(self):
        """Immediately pull window back to a visible screen if stuck in off-screen limbo."""
        if getattr(self, "_appbar_applying", False) or self.isMinimized():
            return
        x, y = self.pos().x(), self.pos().y()
        w, h = self.width(), self.height()
        if x <= -5000 or y <= -5000 or not self.is_rect_visible_on_any_screen(QRect(x, y, w, h)):
            logging.warning(f"WindowManager: Window was offscreen at ({x}, {y}). Rescuing to screen.")
            if getattr(self, "_appbar_active", False) or getattr(self, "_appbar_saved", False):
                self._appbar_active = True
                self._apply_appbar()
            else:
                nx, ny, nw, nh = self.sanitize_window_geometry(x, y, w, h, self._appbar_edge)
                self.setGeometry(nx, ny, nw, nh)
                self.showNormal()
                self.raise_()
                self.activateWindow()

    #  Events

    def moveEvent(self, event):
        super().moveEvent(event)
        x, y = self.pos().x(), self.pos().y()
        if (
            not self.isMinimized()
            and x > -5000
            and y > -5000
            and not getattr(self, "_appbar_applying", False)
            and self.is_rect_visible_on_any_screen(self.geometry())
        ):
            self._last_valid_normal_pos = (x, y)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        w, h = self.width(), self.height()
        if (
            not self.isMinimized()
            and self.pos().x() > -5000
            and not getattr(self, "_appbar_applying", False)
        ):
            self._last_valid_normal_size = (w, h)

        self._grip.move(
            self.width() - self._grip.width() - 2,
            self.height() - self._grip.height() - 2,
        )
        if hasattr(self, "title_bar") and self.title_bar.parentWidget() == self:
            self.title_bar.setGeometry(0, 0, self.width(), 28)
            
        if hasattr(self, "_loading_overlay") and self._loading_overlay and self._loading_overlay.isVisible():
            try:
                self._loading_overlay.resize(self.size())
            except:
                self._loading_overlay = None

        # Re-apply appbar on resize (debounced to avoid lag)
        if getattr(self, "_appbar_active", False) and getattr(self, "_is_ready", False):
            if not hasattr(self, "_appbar_resize_timer"):
                self._appbar_resize_timer = QTimer(self)
                self._appbar_resize_timer.setSingleShot(True)
                self._appbar_resize_timer.timeout.connect(self._apply_appbar)
            self._appbar_resize_timer.start(200)

    def changeEvent(self, event):
        super().changeEvent(event)
        from PySide6.QtCore import QEvent
        if event.type() in (QEvent.ActivationChange, QEvent.WindowStateChange):
            if not self.isMinimized():
                self._rescue_window_if_offscreen()

    def showEvent(self, event):
        super().showEvent(event)
        self._rescue_window_if_offscreen()

    def _on_overlay_finished(self):
        self._loading_overlay = None
        self._maybe_enable_ghost_hover()

    def _maybe_enable_ghost_hover(self):
        if self._ghost_hover_ready:
            return
        if getattr(self, "_loading_overlay", None) is not None:
            return
        if not getattr(self, "_is_ready", False):
            return
        self._ghost_hover_ready = True
        self._ghost_hover_inside = self.rect().contains(self.mapFromGlobal(QCursor.pos()))
        self._schedule_ghost_mode_update()

    def _show_config_load_warnings(self):
        from PySide6.QtWidgets import QMessageBox
        from app import theme as theme_module

        messages = []
        settings_error = SettingsManager.get_last_load_error()
        if settings_error:
            messages.append(f"Settings file was ignored:\n{settings_error.path}\n{settings_error.message}")
        if getattr(theme_module, "CUSTOM_THEME_LOAD_ERROR", None):
            messages.append(f"Custom themes were ignored:\n{theme_module.CUSTOM_THEME_LOAD_ERROR}")
        if self._theme_load_warning:
            messages.append(self._theme_load_warning)

        if not messages:
            return

        box = QMessageBox(self)
        box.setWindowTitle("Configuration Warning")
        box.setText("\n\n".join(messages))
        box.setIcon(QMessageBox.Warning)
        box.setStyleSheet(f"QMessageBox {{ background-color: {Colors.BG_DARK}; color: {Colors.TEXT}; }} QPushButton {{ background: {Colors.BG_HEADER}; color: {Colors.ACCENT}; border: 1px solid {Colors.BORDER}; padding: 4px 12px; }}")
        self._config_warning_box = box
        box.show()

    def contextMenuEvent(self, event):
        self._show_gear_menu()

    def _gather_settings(self):
        """Prepare all current settings in a dictionary for saving."""
        cur_x = self.pos().x()
        cur_y = self.pos().y()
        cur_w = self.width()
        cur_h = self.height()

        if (
            self.isMinimized()
            or cur_x <= -5000
            or cur_y <= -5000
            or getattr(self, "_appbar_applying", False)
            or not self.is_rect_visible_on_any_screen(QRect(cur_x, cur_y, cur_w, cur_h))
        ):
            if hasattr(self, "_last_valid_normal_pos") and self._last_valid_normal_pos:
                save_x, save_y = self._last_valid_normal_pos
            elif "x" in self._settings.get("window", {}) and self._settings["window"]["x"] > -5000:
                save_x = self._settings["window"]["x"]
                save_y = self._settings["window"]["y"]
            else:
                save_x, save_y, _, _ = self.sanitize_window_geometry(cur_x, cur_y, cur_w, cur_h, self._appbar_edge)

            if hasattr(self, "_last_valid_normal_size") and self._last_valid_normal_size:
                save_w, save_h = self._last_valid_normal_size
            else:
                save_w, save_h = cur_w, cur_h
        else:
            save_x, save_y = cur_x, cur_y
            save_w, save_h = cur_w, cur_h

        is_appbar_active = getattr(self, "_appbar_active", False) or getattr(self, "_appbar_saved", False)

        return {
            "window": {
                "x": save_x,
                "y": save_y,
                "width": save_w,
                "height": save_h,
                "vertical_layout": self._layout_vertical,
                "show_headers": self._show_headers,
                "auto_hide_ui": self._auto_hide_ui,
                "appbar_edge": self._appbar_edge,
                "appbar_active": is_appbar_active,
                "appbar_ignore_screenshot_resets": getattr(self, "_appbar_ignore_screenshot_resets", True),
                "divider_width": getattr(self, "_divider_width", self.splitter.handleWidth()),
                "divider_opacity": self._settings.get("window", {}).get("divider_opacity", 100)
            },
            "audio": {
                "device_index": self._current_device,
                "device_full_id": getattr(self, "_target_device_id", None),
                "gain": self.audio_engine.gain_multiplier,
                "channels": self.audio_engine.channels
            },
            "ui": {
                "theme": current_theme_name(),
                "text_scale": Fonts.TEXT_SCALE,
                "color_overrides": self._settings.get("ui", {}).get("color_overrides", {})
            },
            "modules": [{"key": m.module_key, "config": m.get_settings()} for m in self._modules],
            "splitter_sizes": self.splitter.sizes()
        }

    def _periodic_save(self):
        """Autosave settings in the background."""
        if self._is_ready: # Only save once fully loaded
            self._rescue_window_if_offscreen()
            # Gathering must happen on the main thread as it accesses UI components
            settings = self._gather_settings()
            
            # Offload the actual disk I/O to a background thread to prevent any UI stutter
            import threading
            thread = threading.Thread(target=SettingsManager.save, args=(settings,), daemon=True)
            thread.start()

    def closeEvent(self, event):
        """Handle application exit: Save settings and try clean quit."""
        if hasattr(self, "_autosave_timer") and self._autosave_timer:
            self._autosave_timer.stop()

        if hasattr(self, "_perf_hud") and self._perf_hud:
            try:
                self._perf_hud.close()
            except Exception:
                pass

        settings = self._gather_settings()
        SettingsManager.save(settings)

        self.audio_engine.stop()
        # Release appbar on close
        if self._appbar_active:
            self._appbar_active = False
            self._stop_appbar_watchdog()
            self._release_appbar()
        event.accept()
        QApplication.instance().quit()
        
        # Safety fallback: if the process is still alive in 500ms, force it out.
        import os
        QTimer.singleShot(500, lambda: os._exit(0))
