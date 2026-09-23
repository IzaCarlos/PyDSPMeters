"""
Oscilloscope Module: Real-time waveform display with zero-crossing trigger.
"""

import numpy as np
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QLinearGradient, QFontMetrics
from PySide6.QtCore import Qt, QRectF, QPointF

from app.base_module import BaseModule
from app.modules import register_module
from app.theme import Colors, Fonts
from app.dsp import accel as dsp_accel


@register_module("oscilloscope", "Oscilloscope", category="Time Domain")
class OscilloscopeModule(BaseModule):

    def __init__(self, audio_engine, parent=None):
        self._waveform_l = np.zeros(8192, dtype=np.float32)
        self._waveform_r = np.zeros(8192, dtype=np.float32)
        self._display_samples = 1024
        self._channel = "L+R"
        self._display_mode = "Dual" if audio_engine.channels >= 2 else "Overlay"
        self._orientation = "Horizontal"
        self._gain_mode = "Auto Fit"
        self._manual_gain = 1.0
        self._auto_gains = {}
        self._grid_pixmap = None
        self._last_grid_key = None
        self._show_info = False
        self._sample_indices = np.arange(len(self._waveform_l), dtype=np.float32)
        self.module_key = "oscilloscope"
        super().__init__(audio_engine, title="Oscilloscope", parent=parent)
        self.canvas.set_render_func(self._render)

    def get_settings(self):
        return {
            "display_samples": self._display_samples,
            "channel": self._channel,
            "display_mode": getattr(self, "_display_mode", "Overlay"),
            "orientation": getattr(self, "_orientation", "Horizontal"),
            "gain_mode": getattr(self, "_gain_mode", "Auto Fit"),
            "manual_gain": getattr(self, "_manual_gain", 1.0),
            "show_info": getattr(self, "_show_info", False),
        }

    def apply_settings(self, settings):
        self._display_samples = settings.get("display_samples", self._display_samples)
        self._channel = settings.get("channel", self._channel)
        self._display_mode = settings.get("display_mode", getattr(self, "_display_mode", "Overlay"))
        self._orientation = settings.get("orientation", getattr(self, "_orientation", "Horizontal"))
        self._gain_mode = settings.get("gain_mode", getattr(self, "_gain_mode", "Auto Fit"))
        self._manual_gain = float(settings.get("manual_gain", getattr(self, "_manual_gain", 1.0)))
        self._show_info = bool(settings.get("show_info", getattr(self, "_show_info", False)))

    def build_context_menu(self, menu):
        from PySide6.QtGui import QActionGroup
        cm = menu.addMenu("Channel")
        cg = QActionGroup(self)
        for c in ["L+R", "Left", "Right", "Mid", "Side"]:
            a = cm.addAction(c)
            a.setCheckable(True)
            a.setChecked(c == self._channel)
            a.triggered.connect(lambda checked, ch=c: setattr(self, "_channel", ch))
            cg.addAction(a)
            
        om = menu.addMenu("Orientation")
        og = QActionGroup(self)
        for o in ["Auto", "Horizontal", "Vertical"]:
            a = om.addAction(o)
            a.setCheckable(True)
            a.setChecked(o == getattr(self, "_orientation", "Horizontal"))
            a.triggered.connect(lambda checked, v=o: setattr(self, "_orientation", v))
            og.addAction(a)

        dm = menu.addMenu("Display Mode")
        dm.setEnabled(self._channel == "L+R")
        dg = QActionGroup(self)
        for d in ["Overlay", "Dual"]:
            a = dm.addAction(d)
            a.setCheckable(True)
            a.setChecked(d == getattr(self, "_display_mode", "Overlay"))
            a.triggered.connect(lambda checked, v=d: setattr(self, "_display_mode", v))
            dg.addAction(a)

        gm = menu.addMenu("Amplitude")
        gg = QActionGroup(self)
        gain_items = [
            ("Auto Fit", "Auto Fit", None),
            ("Auto Shared", "Auto Shared", None),
            ("0.5x", "Fixed", 0.5),
            ("1x", "Fixed", 1.0),
            ("2x", "Fixed", 2.0),
            ("5x", "Fixed", 5.0),
            ("10x", "Fixed", 10.0),
        ]
        for label, mode, gain in gain_items:
            a = gm.addAction(label)
            a.setCheckable(True)
            a.setChecked(self._gain_action_checked(mode, gain))
            a.triggered.connect(lambda checked, m=mode, g=gain: self._set_gain_mode(m, g))
            gg.addAction(a)

        zm = menu.addMenu("Zoom Samples")
        zg = QActionGroup(self)
        for z in [256, 512, 1024, 2048, 4096, 8192]:
            a = zm.addAction(str(z))
            a.setCheckable(True)
            a.setChecked(z == self._display_samples)
            a.triggered.connect(lambda checked, zv=z: setattr(self, "_display_samples", zv))
            zg.addAction(a)

        menu.addSeparator()
        info_act = menu.addAction("Show Info Badges")
        info_act.setCheckable(True)
        info_act.setChecked(getattr(self, "_show_info", False))
        info_act.triggered.connect(lambda checked: setattr(self, "_show_info", checked))

    def _gain_action_checked(self, mode, gain):
        if mode != getattr(self, "_gain_mode", "Auto Fit"):
            return False
        if gain is None:
            return True
        return abs(float(gain) - getattr(self, "_manual_gain", 1.0)) < 0.01

    def _set_gain_mode(self, mode, gain=None):
        self._gain_mode = mode
        if gain is not None:
            self._manual_gain = float(gain)
        self._auto_gains.clear()

    def on_audio_data(self, data: np.ndarray):
        n = len(data)
        if n <= 0:
            return
        buf_len = len(self._waveform_l)
        
        if n >= buf_len:
            self._waveform_l[:] = data[-buf_len:, 0]
            if data.shape[1] > 1:
                self._waveform_r[:] = data[-buf_len:, 1]
            else:
                self._waveform_r[:] = data[-buf_len:, 0]
        else:
            self._waveform_l[:-n] = self._waveform_l[n:]
            self._waveform_l[-n:] = data[:, 0]
            r = data[:, 1] if data.shape[1] > 1 else data[:, 0]
            self._waveform_r[:-n] = self._waveform_r[n:]
            self._waveform_r[-n:] = r

    def _find_trigger(self, data):
        """Find zero-crossing trigger point near the end of the buffer for lowest latency."""
        search_limit = len(data) - self._display_samples
        if search_limit <= 0:
            return 0.0

        subset = data[:search_limit]
        crossings = np.where((subset[:-1] <= 0) & (subset[1:] > 0))[0]

        if len(crossings) > 0:
            idx = crossings[-1]
            y0, y1 = subset[idx], subset[idx + 1]
            if abs(y1 - y0) > 1e-6:
                frac = -y0 / (y1 - y0)
                return float(idx + frac)
            return float(idx)
        return float(search_limit)

    def _get_channels(self):
        l, r = self._waveform_l, self._waveform_r
        if self._channel == "Left": return [l]
        if self._channel == "Right": return [r]
        if self._channel == "Mid": return [(l + r) * 0.5]
        if self._channel == "Side": return [(l - r) * 0.5]
        return [l, r]

    def _is_vertical(self, w, h):
        if self._orientation == "Auto":
            return h > w * 1.2
        return self._orientation == "Vertical"

    def _update_grid(self, w, h, is_vert):
        from PySide6.QtGui import QPixmap, QPen
        self._grid_pixmap = QPixmap(w, h)
        self._grid_pixmap.fill(Qt.transparent)
        
        painter = QPainter(self._grid_pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        
        grid_col = QColor(Colors.GRID)
        grid_col.setAlpha(55)
        strong_col = QColor(Colors.GRID)
        strong_col.setAlpha(120)
        minor_col = QColor(Colors.GRID)
        minor_col.setAlpha(25)

        # Subtle background divisions
        painter.setPen(QPen(minor_col, 1, Qt.DotLine))
        num_x = 8 if w >= 80 else 4
        num_y = 8 if h >= 80 else 4
        for i in range(1, num_x):
            x = int(w * i / num_x)
            painter.drawLine(x, 0, x, h)
        for i in range(1, num_y):
            y = int(h * i / num_y)
            painter.drawLine(0, y, w, y)

        # Center axes
        painter.setPen(QPen(grid_col, 0.75))
        mid_x = int(w / 2)
        mid_y = int(h / 2)
        painter.drawLine(0, mid_y, w, mid_y)
        painter.drawLine(mid_x, 0, mid_x, h)

        # Reticle ticks along center axes
        tick_len = 3
        for i in range(1, num_x):
            x = int(w * i / num_x)
            painter.drawLine(x, mid_y - tick_len, x, mid_y + tick_len)
        for i in range(1, num_y):
            y = int(h * i / num_y)
            painter.drawLine(mid_x - tick_len, y, mid_x + tick_len, y)

        # Scope corner brackets
        cs = 8
        painter.setPen(QPen(strong_col, 1.5))
        painter.drawLine(0, 0, cs, 0); painter.drawLine(0, 0, 0, cs) # TL
        painter.drawLine(w, 0, w - cs, 0); painter.drawLine(w, 0, w, cs) # TR
        painter.drawLine(0, h, cs, h); painter.drawLine(0, h, 0, h - cs) # BL
        painter.drawLine(w, h, w - cs, h); painter.drawLine(w, h, w, h - cs) # BR
        
        painter.end()
        self._last_grid_key = (w, h, is_vert)

    def _render(self, painter, w, h):
        is_vert = self._is_vertical(w, h)
        grid_key = (w, h, is_vert)
        if grid_key != self._last_grid_key or self._grid_pixmap is None:
            self._update_grid(w, h, is_vert)
            
        if self._grid_pixmap:
            painter.drawPixmap(0, 0, self._grid_pixmap)

        display_chans = self._get_channels()
        colors = [Colors.ACCENT, Colors.ACCENT_PINK]
        mode = getattr(self, "_display_mode", "Overlay")
        
        if is_vert:
            if mode == "Dual" and len(display_chans) > 1:
                n_ch = len(display_chans)
                ch_w = w / n_ch
                for idx, ch in enumerate(display_chans):
                    cx = ch_w * (idx + 0.5)
                    self._draw_lane(painter, cx, w, h, idx, vertical=True)
                    self._draw_trace(painter, ch, w, h, cx, ch_w * 0.45, colors[idx % 2], vertical=True, trace_key=idx)
            else:
                mid_x = w / 2
                for idx, ch in enumerate(display_chans):
                    self._draw_trace(painter, ch, w, h, mid_x, w * 0.45, colors[idx % 2], vertical=True, trace_key=idx)
        else:
            if mode == "Dual" and len(display_chans) > 1:
                n_ch = len(display_chans)
                ch_h = h / n_ch
                for idx, ch in enumerate(display_chans):
                    cy = ch_h * (idx + 0.5)
                    self._draw_lane(painter, cy, w, h, idx, vertical=False)
                    self._draw_trace(painter, ch, w, h, cy, ch_h * 0.45, colors[idx % 2], vertical=False, trace_key=idx)
            else:
                mid_y = h / 2
                for idx, ch in enumerate(display_chans):
                    self._draw_trace(painter, ch, w, h, mid_y, h * 0.45, colors[idx % 2], vertical=False, trace_key=idx)

        if getattr(self, "_show_info", False):
            self._draw_status(painter, w, h, is_vert, len(display_chans), mode)

    def _draw_lane(self, painter, center, w, h, idx, vertical=False):
        col = QColor(Colors.GRID_BRIGHT)
        col.setAlpha(80)
        painter.setPen(QPen(col, 1, Qt.DashLine))
        if vertical:
            painter.drawLine(int(center), 0, int(center), h)
        else:
            painter.drawLine(0, int(center), w, int(center))

        if w < 70 or h < 42:
            return
        label = "L" if idx == 0 else "R"
        painter.setFont(Fonts.small())
        color = QColor(Colors.ACCENT if idx == 0 else Colors.ACCENT_PINK)
        color.setAlpha(150)
        if vertical:
            rect = QRectF(center - 10, 5, 20, 14)
        else:
            rect = QRectF(6, center - 7, 20, 14)
        self.draw_text_badge(painter, rect, Qt.AlignCenter, label, color)

    def _draw_status(self, painter, w, h, is_vert, channel_count, mode):
        if w < 110 or h < 40:
            return
        painter.setFont(Fonts.small())
        channel = self._channel
        if channel == "L+R" and channel_count > 1:
            channel = f"L+R {mode}"
        if getattr(self, "_gain_mode", "Auto Fit") == "Fixed":
            gain_label = f"{getattr(self, '_manual_gain', 1.0):g}x"
        elif getattr(self, "_gain_mode", "Auto Fit") == "Auto Shared":
            gain_label = "auto shared"
        else:
            gain_label = "auto"
        sample_text = f"{self._display_samples} smp  {gain_label}"
        fm = QFontMetrics(painter.font())
        left_w = fm.horizontalAdvance(channel) + 14
        right_w = fm.horizontalAdvance(sample_text) + 14
        self.draw_text_badge(
            painter,
            QRectF(6, h - 18, min(left_w, max(32, w - 12)), 14),
            Qt.AlignLeft | Qt.AlignVCenter,
            channel,
            QColor(Colors.TEXT_DIM),
        )
        self.draw_text_badge(
            painter,
            QRectF(max(6, w - right_w - 6), 5, right_w, 14),
            Qt.AlignCenter,
            sample_text,
            QColor(Colors.ACCENT),
        )

    def _get_trace_gain(self, samples, trace_key=0):
        mode = getattr(self, "_gain_mode", "Auto Fit")
        if mode == "Fixed":
            return max(0.05, float(getattr(self, "_manual_gain", 1.0)))

        if len(samples) < 2:
            return 1.0

        key = "shared" if mode == "Auto Shared" else trace_key
        abs_samples = np.abs(samples)
        if len(abs_samples) > 64:
            peak = float(np.percentile(abs_samples, 99.5))
        else:
            peak = float(np.max(abs_samples))

        if peak < 0.0005:
            target = 1.0
        else:
            target = 0.86 / peak
            target = max(0.25, min(32.0, target))

        previous = self._auto_gains.get(key, target)
        alpha = 0.45 if target < previous else 0.16
        gain = previous + (target - previous) * alpha
        self._auto_gains[key] = gain
        return gain

    def _draw_trace(self, painter, ch, w, h, center, factor, color, vertical=False, trace_key=0):
        long_axis = h if vertical else w
        num_points = min(self._display_samples, int(long_axis))
        if num_points < 2 or len(ch) < 2:
            return

        gain_mode_str = getattr(self, "_gain_mode", "Auto Fit")
        gain_mode_id = 2 if gain_mode_str == "Fixed" else (1 if gain_mode_str == "Auto Shared" else 0)
        key = "shared" if gain_mode_id == 1 else trace_key
        prev_gain = self._auto_gains.get(key, 1.0)
        manual_gain = float(getattr(self, "_manual_gain", 1.0))

        vals, new_gain = dsp_accel.prepare_oscilloscope_trace(
            ch, self._display_samples, num_points, gain_mode_id, manual_gain, prev_gain
        )
        self._auto_gains[key] = new_gain

        actual_pts = len(vals)
        if actual_pts < 2:
            return

        t_coords = np.linspace(0, long_axis, actual_pts)
        v_coords = center - vals * factor

        if vertical:
            points = [QPointF(v_coords[i], t_coords[i]) for i in range(actual_pts)]
        else:
            points = [QPointF(t_coords[i], v_coords[i]) for i in range(actual_pts)]

        gc = QColor(color)
        gc.setAlpha(40)
        painter.setPen(QPen(gc, 3.0))
        painter.drawPolyline(points)

        painter.setPen(QPen(QColor(color), 1.5))
        painter.drawPolyline(points)

