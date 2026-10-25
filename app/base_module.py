"""
Base class for all visualization modules.
Provides a collapsible settings panel, header bar, and audio data hookup.
"""

import time
import traceback

import numpy as np
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QSizePolicy, QMenu, QSplitter,
)
from PySide6.QtCore import Qt, Signal, QSize, QTimer, QElapsedTimer, QPointF
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QFontMetrics, QPolygonF

from app.theme import Colors, Fonts
from app.utils import dsp_executor
from app.utils import perf_stats

try:
    from PySide6.QtOpenGLWidgets import QOpenGLWidget
    _CANVAS_BASE = QOpenGLWidget
except ImportError:
    _CANVAS_BASE = QWidget


MODULE_MIN_WIDTH = 48
MODULE_MIN_CANVAS_HEIGHT = 32
MODULE_MIN_HEIGHT = MODULE_MIN_CANVAS_HEIGHT
MODULE_MIN_HEIGHT_WITH_HEADER = MODULE_MIN_CANVAS_HEIGHT + 26


class ModuleHeader(QFrame):
    """Compact header bar with title and close button."""

    close_requested = Signal()

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setFixedHeight(26)
        self.setObjectName("moduleHeader")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 4, 0)
        layout.setSpacing(4)

        self._title = QLabel(title)
        self._title.setFont(Fonts.header())
        layout.addWidget(self._title)

        layout.addStretch()

        self._close_btn = QPushButton("✕")
        self._close_btn.setFixedSize(22, 22)
        self._close_btn.setToolTip("Remove module")
        self._close_btn.clicked.connect(self.close_requested.emit)
        layout.addWidget(self._close_btn)

        self.update_theme()

    def update_theme(self):
        self.setStyleSheet(f"#moduleHeader {{ background: {Colors.BG_HEADER}; border-bottom: 1px solid {Colors.BORDER}; }}")
        self._title.setStyleSheet(f"color: {Colors.ACCENT}; background: transparent; font-size: 8pt; font-weight: normal;")
        self._close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                color: {Colors.TEXT_DIM};
                font-size: 10pt;
                padding: 0;
            }}
            QPushButton:hover {{ color: {Colors.RED}; }}
        """)

    def set_move_mode(self, enabled: bool, vertical: bool = True):
        self._close_btn.setVisible(not enabled)

    def set_title(self, title: str):
        self._title.setText(title)


class RenderCanvas(_CANVAS_BASE):
    """
    Hardware-accelerated drawing surface for visualizations.
    Uses QOpenGLWidget for GPU rasterization when available, falling back to QWidget.
    Modules set a render callback via set_render_func(fn).
    The callback receives (painter, w, h) with an already-active QPainter.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(MODULE_MIN_WIDTH, MODULE_MIN_CANVAS_HEIGHT)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setAttribute(Qt.WA_OpaquePaintEvent)
        self._render_func = None
        self._antialiasing = True

    def set_render_func(self, func):
        """Set external render callback: func(painter, width, height)."""
        self._render_func = func

    def set_antialiasing(self, enabled: bool):
        self._antialiasing = bool(enabled)

    def paintEvent(self, event):
        painter = QPainter(self)
        if not painter.isActive():
            return
        started = time.perf_counter()
        parent = self.parent()
        module_name = getattr(parent, "module_key", parent.__class__.__name__ if parent else "unknown")
        painter.setRenderHint(QPainter.Antialiasing, self._antialiasing)
        
        painter.fillRect(self.rect(), QColor(Colors.BG_MODULE))
        w, h = self.width(), self.height()
        if self._render_func and w > 0 and h > 0:
            painter.save()
            try:
                self._render_func(painter, w, h)
            except Exception:
                import traceback
                traceback.print_exc()
            finally:
                painter.restore()
        
        # Move Mode Overlay
        if getattr(self.parent(), "_move_mode", False):
            painter.setBrush(QColor(0, 0, 0, 160))
            painter.setPen(Qt.NoPen)
            painter.drawRect(self.rect())
            
            # Dynamic Arrow Scaling & Positioning
            # Match arrows to layout: Vertical Splitter -> Up/Down, Horizontal -> Left/Right
            # RenderCanvas -> BaseModule -> QSplitter
            splitter = self.parent().parentWidget()
            is_vert_splitter = True
            if isinstance(splitter, QSplitter):
                is_vert_splitter = splitter.orientation() == Qt.Vertical
            
            accent = QColor(Colors.ACCENT)
            accent.setAlpha(180)
            painter.setBrush(accent)
            
            if is_vert_splitter:
                # Up/Down arrows
                asize = max(8, min(20, (h - 20) // 3))
                # Draw subtle drop shadow/glow
                painter.setBrush(QColor(0, 0, 0, 100))
                painter.drawPolygon(QPolygonF([QPointF(w/2, 6), QPointF(w/2-asize, 6+asize), QPointF(w/2+asize, 6+asize)]))
                painter.drawPolygon(QPolygonF([QPointF(w/2, h-4), QPointF(w/2-asize, h-4-asize), QPointF(w/2+asize, h-4-asize)]))
                
                painter.setBrush(accent)
                # Up
                painter.drawPolygon(QPolygonF([QPointF(w/2, 5), QPointF(w/2-asize, 5+asize), QPointF(w/2+asize, 5+asize)]))
                # Down
                painter.drawPolygon(QPolygonF([QPointF(w/2, h-5), QPointF(w/2-asize, h-5-asize), QPointF(w/2+asize, h-5-asize)]))
            else:
                # Left/Right arrows
                asize = max(8, min(20, (w - 20) // 3))
                # Shadow
                painter.setBrush(QColor(0, 0, 0, 100))
                painter.drawPolygon(QPolygonF([QPointF(6, h/2), QPointF(6+asize, h/2-asize), QPointF(6+asize, h/2+asize)]))
                painter.drawPolygon(QPolygonF([QPointF(w-4, h/2), QPointF(w-4-asize, h/2-asize), QPointF(w-4-asize, h/2+asize)]))
                
                painter.setBrush(accent)
                # Left
                painter.drawPolygon(QPolygonF([QPointF(5, h/2), QPointF(5+asize, h/2-asize), QPointF(5+asize, h/2+asize)]))
                # Right
                painter.drawPolygon(QPolygonF([QPointF(w-5, h/2), QPointF(w-5-asize, h/2-asize), QPointF(w-5-asize, h/2+asize)]))

            # Responsive Text
            center_w = w - (asize*2 + 15) if not is_vert_splitter else w
            center_h = h - (asize*2 + 15) if is_vert_splitter else h
            if center_w > 30 and center_h > 30:
                painter.setPen(QColor(Colors.TEXT))
                msg = "MOVE MODE\nDouble-Click to Finish"
                painter.setFont(BaseModule.get_responsive_font(Fonts.header, center_w, center_h, msg))
                painter.drawText(self.rect(), Qt.AlignCenter, msg)
            
        perf_stats.record_timing(f"paint.{module_name}", time.perf_counter() - started)
        perf_stats.record_interval(f"paint_interval.{module_name}")
        painter.end()

    def mousePressEvent(self, event):
        if getattr(self.parent(), "_move_mode", False):
            w, h = self.width(), self.height()
            splitter = self.parent().parentWidget()
            if isinstance(splitter, QSplitter) and splitter.orientation() == Qt.Vertical:
                if event.y() < h / 2:
                    self.parent().move_requested.emit(self.parent(), -1)
                else:
                    self.parent().move_requested.emit(self.parent(), 1)
            else:
                if event.x() < w / 2:
                    self.parent().move_requested.emit(self.parent(), -1)
                else:
                    self.parent().move_requested.emit(self.parent(), 1)
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if getattr(self.parent(), "_move_mode", False):
            self.parent().move_mode_exit_requested.emit()
            return
        super().mouseDoubleClickEvent(event)


class BaseModule(QWidget):
    """
    Base class for all visualization modules.
    """

    close_requested = Signal(object)  # emits self
    move_requested = Signal(object, int)  # emits self, direction (-1 or 1)
    move_mode_exit_requested = Signal()
    _async_audio_result_ready = Signal(int, object, object, float)

    def __init__(self, audio_engine, title: str = "Module", parent=None):
        super().__init__(parent)
        self.audio_engine = audio_engine
        self._title = title
        self.setObjectName("baseModule")
        self._move_mode = False
        self.setMinimumSize(MODULE_MIN_WIDTH, MODULE_MIN_HEIGHT)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.header = ModuleHeader(title)
        self.header.close_requested.connect(lambda: self.close_requested.emit(self))
        layout.addWidget(self.header)

        self.canvas = RenderCanvas()
        layout.addWidget(self.canvas)

        self.update_theme()
        self.audio_engine.data_ready.connect(self._handle_audio_data)
        self._render_interval_ms = 16
        self._render_timer = QTimer(self)
        self._render_timer.setTimerType(Qt.PreciseTimer)
        self._render_timer.setInterval(self._render_interval_ms)
        self._render_timer.timeout.connect(self._flush_render_update)
        self._render_timer.start()
        self._last_render_update = QElapsedTimer()
        self._last_render_update.start()
        self._async_audio_enabled = False
        self._async_audio_in_flight = False
        self._async_audio_pending_data = None
        self._async_audio_seq = 0
        self._async_audio_closed = False
        self._async_audio_result_ready.connect(self._handle_async_audio_result)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._render_timer.isActive():
            self._render_timer.start(self._render_interval_ms)

    def hideEvent(self, event):
        super().hideEvent(event)
        self._render_timer.stop()

    def update_theme(self):
        self.setStyleSheet(f"#baseModule {{ background: {Colors.BG_DARK}; border: 1px solid {Colors.BORDER}; border-radius: 4px; }}")
        if hasattr(self, "header"):
            self.header.update_theme()

    def on_theme_changed(self):
        """Hook called when the global color theme changes."""
        pass
            
    def set_move_mode(self, enabled: bool):
        self._move_mode = enabled
        self.header.set_move_mode(enabled)
        self.canvas.update()

    def mouseDoubleClickEvent(self, event):
        if self._move_mode:
            self.move_mode_exit_requested.emit()
        super().mouseDoubleClickEvent(event)

    _font_cache = {}

    @staticmethod
    def get_responsive_font(base_font_func, target_w, target_h, text, max_size=None, min_size=4.0):
        """
        Calculates a high-precision font size that fits constraints.
        Uses floating point sizes for smooth scaling transitions.
        """
        base_font = base_font_func()
        # Get the 'design' size (the size intended at 1.0 scale)
        # We use floating point for the native size to allow sub-pixel scaling
        native_size = base_font.pointSizeF() / Fonts.TEXT_SCALE
        
        if max_size is None:
            max_size = native_size
            
        # Cache key includes the scale for sub-pixel accuracy
        cache_key = (base_font_func.__name__, int(target_w), int(target_h), text, float(max_size), float(min_size), float(Fonts.TEXT_SCALE))
        if cache_key in BaseModule._font_cache:
            return BaseModule._font_cache[cache_key]

        # Start with the ideal scaled size
        ideal_size = max_size * Fonts.TEXT_SCALE
        base_font.setPointSizeF(ideal_size)
        
        # Check if it fits as-is
        m = QFontMetrics(base_font)
        rect = m.boundingRect(text)
        
        if rect.width() <= target_w and rect.height() <= target_h:
            # Fits perfectly at the intended scale
            BaseModule._font_cache[cache_key] = base_font
            return base_font
            
        # If it doesn't fit, we perform a precise binary search for the best float size
        low = min_size * Fonts.TEXT_SCALE
        high = ideal_size
        best_fsize = low
        
        # 10 iterations give us roughly 0.1pt precision which is very smooth
        for _ in range(10):
            mid = (low + high) / 2
            base_font.setPointSizeF(mid)
            m = QFontMetrics(base_font)
            rect = m.boundingRect(text)
            
            if rect.width() <= target_w and rect.height() <= target_h:
                best_fsize = mid
                low = mid
            else:
                high = mid
                
        base_font.setPointSizeF(best_fsize)
        BaseModule._font_cache[cache_key] = base_font
        return base_font

    def self_test(self):
        """Perform a basic health check on the module."""
        issues = []
        if not hasattr(self, 'canvas') or self.canvas is None:
            issues.append("Canvas not initialized")
        if not hasattr(self, 'audio_engine') or self.audio_engine is None:
            issues.append("Audio engine not connected")
        
        if issues:
            print(f"[{self._title}] Self-Test Failed: {', '.join(issues)}")
            return False
        return True

    def build_context_menu(self, menu):
        """Override to add QActions to the module's right-click menu."""
        pass

    @staticmethod
    def draw_text_badge(painter, rect, align, text, text_pen, bg_color=None):
        """Draws text with a rounded, padded background for readability."""
        if bg_color is None:
            bg_color = Colors.with_alpha(Colors.BG_BADGE, getattr(Colors, "BG_BADGE_ALPHA", 180))
            
        fm = QFontMetrics(painter.font())
        if hasattr(rect, 'toRect'):
            rect = rect.toRect()
            
        br = fm.boundingRect(rect, align, text)
        pad_x = int(6 * Fonts.TEXT_SCALE)
        pad_y = int(2 * Fonts.TEXT_SCALE)
        br.adjust(-pad_x, -pad_y, pad_x, pad_y)
        
        painter.save()
        painter.setPen(Qt.NoPen)
        painter.setBrush(bg_color)
        painter.drawRoundedRect(br, int(4 * Fonts.TEXT_SCALE), int(4 * Fonts.TEXT_SCALE))
        
        painter.setPen(text_pen)
        painter.drawText(rect, align, text)
        painter.restore()

    def contextMenuEvent(self, event):
        """Show settings via right-click."""
        menu = QMenu(self)
        
        self.build_context_menu(menu)
        
        if not menu.isEmpty():
            menu.addSeparator()
            
        # Determine orientation for better labels
        parent = self.parentWidget()
        is_vert = False
        if isinstance(parent, QSplitter):
            is_vert = parent.orientation() == Qt.Vertical

        # Movement
        move_menu = menu.addMenu("Move Module")
        if is_vert:
            up_act = move_menu.addAction("Move Up")
            up_act.triggered.connect(lambda: self.move_requested.emit(self, -1))
            down_act = move_menu.addAction("Move Down")
            down_act.triggered.connect(lambda: self.move_requested.emit(self, 1))
        else:
            left_act = move_menu.addAction("Move Left")
            left_act.triggered.connect(lambda: self.move_requested.emit(self, -1))
            right_act = move_menu.addAction("Move Right")
            right_act.triggered.connect(lambda: self.move_requested.emit(self, 1))

        menu.addSeparator()
        mm_act = menu.addAction("Enable Move Mode")
        mm_act.setCheckable(True)
        mm_act.setChecked(self._move_mode)
        mm_act.triggered.connect(self.set_move_mode)
        
        menu.addSeparator()
        remove_action = menu.addAction("Remove Module")
        remove_action.triggered.connect(lambda: self.close_requested.emit(self))
        
        host = self.window()
        hold = getattr(host, "hold_ghost_ui", None)
        release = getattr(host, "release_ghost_ui", None)
        if callable(hold):
            hold()
        try:
            menu.exec(event.globalPos())
        finally:
            if callable(release):
                release()

    def on_audio_data(self, data: np.ndarray):
        """
        Override to process incoming audio data.
        Called on the main thread with shape (block_size, channels).
        """
        pass

    def set_async_audio_processing(self, enabled: bool):
        """Enable latest-only worker-thread processing for this module."""
        self._async_audio_enabled = bool(enabled)

    def process_audio_data(self, data: np.ndarray):
        """
        Override for worker-thread audio processing.
        Must not touch Qt objects. Return render-ready state for apply_audio_result().
        """
        return None

    def apply_audio_result(self, result):
        """Override to apply worker results on the main thread."""
        pass

    def _handle_audio_data(self, data: np.ndarray):
        if self._async_audio_enabled:
            self._queue_async_audio_data(data)
            return

        started = time.perf_counter()
        try:
            self.on_audio_data(data)
        finally:
            module_name = getattr(self, "module_key", self.__class__.__name__)
            perf_stats.record_timing(f"module_audio.{module_name}", time.perf_counter() - started)

    def _queue_async_audio_data(self, data: np.ndarray):
        if self._async_audio_closed:
            return

        self._async_audio_pending_data = data
        if not self._async_audio_in_flight:
            self._start_next_async_audio_job()

    def _start_next_async_audio_job(self):
        data = self._async_audio_pending_data
        self._async_audio_pending_data = None
        if data is None or self._async_audio_closed:
            return

        self._async_audio_in_flight = True
        self._async_audio_seq += 1
        seq = self._async_audio_seq
        future = dsp_executor.submit(self._run_async_audio_job, seq, data)
        future.add_done_callback(self._emit_async_audio_result)

    def _run_async_audio_job(self, seq: int, data: np.ndarray):
        started = time.perf_counter()
        result = self.process_audio_data(data)
        return seq, result, time.perf_counter() - started

    def _emit_async_audio_result(self, future):
        try:
            seq, result, elapsed = future.result()
            error = None
        except Exception as exc:
            seq = self._async_audio_seq
            result = None
            elapsed = 0.0
            error = exc

        if not self._async_audio_closed:
            self._async_audio_result_ready.emit(seq, result, error, elapsed)

    def _handle_async_audio_result(self, seq: int, result, error, elapsed: float):
        self._async_audio_in_flight = False
        module_name = getattr(self, "module_key", self.__class__.__name__)
        perf_stats.record_timing(f"module_audio_worker.{module_name}", elapsed)

        if error is not None:
            print(f"[{self._title}] async audio processing failed:")
            traceback.print_exception(type(error), error, error.__traceback__)
        elif not self._async_audio_closed:
            started = time.perf_counter()
            self.apply_audio_result(result)
            perf_stats.record_timing(
                f"module_audio_apply.{module_name}",
                time.perf_counter() - started,
            )
            self._request_render_update()

        if self._async_audio_pending_data is not None:
            self._start_next_async_audio_job()

    def _request_render_update(self):
        if not self._render_timer.isActive() and self.isVisible():
            self._render_timer.start(self._render_interval_ms)

    def _flush_render_update(self):
        try:
            if self.canvas and self.canvas.isVisible() and self.isVisible():
                self.canvas.update()
                self._last_render_update.restart()
        except RuntimeError:
            pass

    def get_settings(self) -> dict:
        """Override to return a dict of settings to persist."""
        return {}

    def apply_settings(self, settings: dict):
        """Override to apply persisted settings."""
        pass

    def cleanup(self):
        """Called when the module is being removed."""
        self._async_audio_closed = True
        self._async_audio_enabled = False
        self._async_audio_pending_data = None
        self._render_timer.stop()
        try:
            self.audio_engine.data_ready.disconnect(self._handle_audio_data)
        except RuntimeError:
            pass
        except Exception:
            pass
