"""
PyDSPMeters: Entry Point
Modular real-time audio visualization utility.
"""

from PySide6.QtWidgets import QApplication, QSplashScreen, QLabel
from PySide6.QtCore import Qt, QTimer, QRectF, QPoint
from PySide6.QtGui import QPainter, QColor, QLinearGradient, QFont, QPen, QIcon
import sys
import os
import ctypes
import glob

from app.theme import build_stylesheet, Colors, Fonts, apply_theme
from app.settings import SettingsManager
from app.utils.logging_utils import setup_logging, setup_global_exception_handler

# --- Application Configuration ---
# Set this to the name of your icon file. It will survive Nuitka packaging.
# If left empty, the app will automatically try to find a .ico in its directory.
APP_ICON_NAME = "icon.ico" 
# ---------------------------------

class CustomSplashScreen(QSplashScreen):
    """Splash screen with branding and progress."""
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
        self.setFixedSize(450, 280)
        self._progress = 0
        self._display_progress = 0.0
        self._status = "Initializing core components..."
        self._pulse = 0.0
        self._pulse_dir = 1
        
        # Smoothed colors for theme transitions
        self._current_colors = {
            "ACCENT": QColor(Colors.ACCENT),
            "ACCENT_DIM": QColor(Colors.ACCENT_DIM),
            "BG_DARKEST": QColor(Colors.BG_DARKEST),
            "BORDER": QColor(Colors.BORDER)
        }
        
        # Center on screen
        screen = QApplication.primaryScreen().geometry()
        self.move(screen.center() - self.rect().center())
        
        # Animation timer
        self._timer = QTimer(self)
        self._timer.setInterval(16) # ~60fps
        self._timer.timeout.connect(self._animate)
        self._timer.start()
        
    def set_progress(self, val, status=None):
        self._progress = val
        if status:
            self._status = status
        self.update()
        QApplication.processEvents()

    def _animate(self):
        # Lerp progress
        diff = self._progress - self._display_progress
        if abs(diff) > 0.1:
            self._display_progress += diff * 0.1
        else:
            self._display_progress = float(self._progress)
            
        # Idle pulse
        self._pulse += 0.02 * self._pulse_dir
        if self._pulse > 1.0 or self._pulse < 0.0:
            self._pulse_dir *= -1
            self._pulse = max(0.0, min(1.0, self._pulse))
            
        # Lerp colors towards current global theme
        changed = False
        lerp_speed = 0.05
        for key in self._current_colors:
            target = QColor(getattr(Colors, key))
            current = self._current_colors[key]
            
            if current != target:
                r = current.red() + (target.red() - current.red()) * lerp_speed
                g = current.green() + (target.green() - current.green()) * lerp_speed
                b = current.blue() + (target.blue() - current.blue()) * lerp_speed
                a = current.alpha() + (target.alpha() - current.alpha()) * lerp_speed
                self._current_colors[key] = QColor(int(r), int(g), int(b), int(a))
                changed = True
        
        if changed or abs(diff) > 0.01:
            self.update()

    def paintEvent(self, event):
        with QPainter(self) as p:
            p.setRenderHint(QPainter.Antialiasing)
            
            c = self._current_colors
            
            # Draw background gradient
            rect = self.rect()
            bg_grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
            bg_grad.setColorAt(0, c["BG_DARKEST"])
            bg_grad.setColorAt(1, c["BG_DARKEST"].lighter(110))
            p.fillRect(rect, bg_grad)
            
            # Subtle accent glow / border
            p.setPen(QPen(c["BORDER"], 1))
            p.drawRect(rect.adjusted(0, 0, -1, -1))
            
            # Glow behind logo
            glow = QLinearGradient(rect.center() - QPoint(180, 0), rect.center() + QPoint(180, 0))
            glow_col = QColor(c["ACCENT"])
            glow_col.setAlpha(35)
            glow.setColorAt(0, Qt.transparent)
            glow.setColorAt(0.5, glow_col)
            glow.setColorAt(1, Qt.transparent)
            p.fillRect(rect.adjusted(0, 105, 0, -115), glow)

            # Logo Text
            p.setPen(c["ACCENT"])
            f = Fonts.header()
            f.setPointSize(32)
            f.setLetterSpacing(QFont.AbsoluteSpacing, 4)
            f.setWeight(QFont.Black)
            p.setFont(f)
            # Pulse the logo opacity
            col = c["ACCENT"]
            col.setAlpha(int(200 + 55 * self._pulse))
            p.setPen(col)
            p.drawText(rect.adjusted(0, -25, 0, 0), Qt.AlignCenter, "PYDSPMETERS")
            
            # Subtitle
            p.setPen(QColor(Colors.TEXT_DIM))
            f.setPointSize(10)
            f.setLetterSpacing(QFont.AbsoluteSpacing, 1)
            f.setBold(False)
            f.setWeight(QFont.Normal)
            p.setFont(f)
            p.drawText(rect.adjusted(0, 30, 0, 0), Qt.AlignCenter, "MODULAR AUDIO ANALYZER")
            
            # Version
            f.setPointSize(8)
            p.setFont(f)
            p.setPen(QColor(Colors.BORDER_ACCENT))
            p.drawText(rect.adjusted(0, 0, -15, -15), Qt.AlignBottom | Qt.AlignRight, "v1.2.14.0")

            # Status (placed ABOVE progress bar)
            p.setPen(QColor(Colors.TEXT_DIM))
            f.setPointSize(9)
            p.setFont(f)
            p.drawText(rect.adjusted(50, 0, -50, -65), Qt.AlignBottom | Qt.AlignLeft, self._status)
            
            # Progress bar container
            bar_rect = QRectF(50, 230, 350, 6)
            p.setBrush(QColor(Colors.BG_DARK))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(bar_rect, 3, 3)
            
            # Progress bar fill
            if self._display_progress > 0:
                progress_rect = QRectF(50, 230, 350 * (self._display_progress / 100), 6)
                grad = QLinearGradient(progress_rect.topLeft(), progress_rect.topRight())
                grad.setColorAt(0, c["ACCENT_DIM"])
                grad.setColorAt(1, c["ACCENT"])
                p.setBrush(grad)
                p.drawRoundedRect(progress_rect, 3, 3)


def main():
    # Initialize Logging and Global Exception Handling as early as possible
    setup_logging()
    setup_global_exception_handler()
    import logging
    from app.dsp import accel as dsp_accel
    profile = SettingsManager.get_profile_name()
    if profile:
        logging.info(f"Launch profile active: {profile}")
    logging.info(f"DSP accelerator active: {dsp_accel.is_accelerated()}")

    # Handle Ctrl+C (SIGINT)
    import signal, sys
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    # High-DPI support
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    # OpenGL GPU surface format (disable vsync swap stall)
    try:
        from PySide6.QtGui import QSurfaceFormat
        fmt = QSurfaceFormat()
        fmt.setSwapInterval(0)
        QSurfaceFormat.setDefaultFormat(fmt)
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setApplicationName(SettingsManager.get_window_title())
    
    # Override default Python taskbar icon if a .ico is found or in settings
    if sys.platform == "win32":
        try:
            myappid = SettingsManager.get_app_user_model_id()
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except Exception:
            pass
            
    # Try to load icon robustly (survives Nuitka packaging)
    base_dir = os.path.dirname(os.path.abspath(__file__))
    icon_path = ""
    
    if APP_ICON_NAME:
        target_path = os.path.join(base_dir, APP_ICON_NAME)
        if os.path.exists(target_path):
            icon_path = target_path
            
    if not icon_path:
        icos = glob.glob(os.path.join(base_dir, "*.ico"))
        if icos:
            icon_path = icos[0]
            
    if icon_path and os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    
    # Initialize theme
    apply_theme("Midnight")
    
    # Show Splash immediately
    splash = CustomSplashScreen()
    splash.setWindowTitle(SettingsManager.get_window_title())
    splash.show()
    app.processEvents()
    
    # Now do heavier imports
    splash.set_progress(20, "Loading UI modules...")
    app.processEvents()
    from app.window_manager import MainWindow
    
    splash.set_progress(40, "Initializing Audio Engine...")
    app.processEvents()
    from app.audio_engine import AudioEngine
    engine = AudioEngine(sample_rate=44100, block_size=1024)

    splash.set_progress(60, "Restoring workspace...")
    app.processEvents()
    
    app.processEvents()
    app.setStyleSheet(build_stylesheet())
    app.processEvents()
    window = MainWindow(engine, splash=splash)
    app.processEvents()
    
    splash.set_progress(90, "Starting real-time streams...")
    app.processEvents()

    # Wait for window to be ready
    def finalize():
        # Prepare layout and dock if needed BEFORE showing
        window.finish_loading()
        app.processEvents()
        
        # First ensure window is shown and rendered
        window.show()
        app.processEvents()
        
        # Then fade out or finish splash
        splash.set_progress(100, "Ready")
        app.processEvents()
        
        # Give it one more beat to ensure MainWindow is fully painted
        QTimer.singleShot(200, lambda: splash.finish(window))

    QTimer.singleShot(100, finalize)

    sys.exit(app.exec())


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        import os
        os._exit(0)
