"""
Stereometer Module: Lissajous / Linear / Scaled stereo display with correlation meter.
"""

import numpy as np
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QPixmap, QImage
from PySide6.QtCore import Qt, QPointF, QRectF

from app.base_module import BaseModule
from app.modules import register_module
from app.theme import Colors, Fonts
from app.dsp.correlation import correlation, multiband_correlation
from app.dsp.filters import MultiBandFilter
from app.dsp import accel as dsp_accel


def _tukey_window(n: int, alpha: float = 0.5) -> np.ndarray:
    if n <= 1 or alpha <= 0.0:
        return np.ones(n, dtype=np.float32)
    if alpha >= 1.0:
        return (0.5 - 0.5 * np.cos(2.0 * np.pi * np.arange(n) / (n - 1))).astype(np.float32)
    x = np.arange(n, dtype=np.float64) / (n - 1)
    w = np.ones(n, dtype=np.float64)
    edge = alpha / 2.0
    left_mask = x < edge
    w[left_mask] = 0.5 * (1.0 - np.cos(np.pi * x[left_mask] / edge))
    right_mask = x > (1.0 - edge)
    w[right_mask] = 0.5 * (1.0 - np.cos(np.pi * (1.0 - x[right_mask]) / edge))
    return w.astype(np.float32)


@register_module("stereometer", "Stereometer", category="Stereo & Phase")
class StereometerModule(BaseModule):

    def __init__(self, audio_engine, parent=None):
        self._display_mode = "Linear"
        self._color_mode = "Static"
        self._corr_mode = "Single-Band"
        self._guide_mode = "Rhombus"
        self._zoom = 1.0
        self._auto_zoom = True
        self._auto_zoom_mode = "Padded"
        self._auto_zoom_value = 1.0
        self._trace_style = "Persistence"
        self._show_labels = True
        self._halved_view = False
        self._minimal_mode = False
        self._corr_pos = "Bottom"
        self._rotation = 0
        
        self._width_gain = 1.0
        self._auto_width = True
        self._auto_width_gain = 1.0
        self._persistence = 0.5 
        self._max_dots = 2048
        self._bands_l = None
        self._bands_r = None
        self._buffer = None
        self._scope_pixmap = None
        self._scope_pixmap_key = None
        
        self._left = np.zeros(0, dtype=np.float32)
        self._right = np.zeros(0, dtype=np.float32)
        self._left_xy = np.zeros(0, dtype=np.float32)
        self._right_xy = np.zeros(0, dtype=np.float32)
        self._corr = 0.0
        self._mb_corr = {"low": 0.0, "mid": 0.0, "high": 0.0, "overall": 0.0}
        self._multiband = MultiBandFilter(sample_rate=audio_engine.sample_rate)
        self._corr_peak = 0.0
        self._mb_corr_peak = {}
        self.module_key = "stereometer"
        super().__init__(audio_engine, title="Stereometer", parent=parent)
        self.canvas.set_render_func(self._render)

    def on_theme_changed(self):
        self._clear_scope_persistence()

    def get_settings(self):
        return {
            "display_mode": self._display_mode,
            "color_mode": self._color_mode,
            "corr_mode": self._corr_mode,
            "guide_mode": self._guide_mode,
            "zoom": self._zoom,
            "auto_zoom": self._auto_zoom,
            "auto_zoom_mode": self._auto_zoom_mode,
            "trace_style": self._trace_style,
            "width_gain": self._width_gain,
            "auto_width": self._auto_width,
            "persistence": self._persistence,
            "max_dots": self._max_dots,
            "show_labels": self._show_labels,
            "minimal_mode": self._minimal_mode,
            "halved_view": self._halved_view,
            "corr_pos": self._corr_pos,
            "rotation": self._rotation
        }

    _VALID_DISPLAY_MODES = {"Linear", "Scaled", "Vectorscope", "Lissajous", "XY Oscilloscope"}
    _VALID_COLOR_MODES = {"Static", "Multi-Band", "Multi-Band (RGB)"}
    _VALID_CORR_MODES = {"Single-Band", "Multi-Band"}
    _VALID_GUIDE_MODES = {"None", "Rhombus", "Circle", "Square"}
    _VALID_TRACE_STYLES = {"Persistence", "Instant"}
    _VALID_AUTO_ZOOM_MODES = {"Padded", "Max"}

    def apply_settings(self, settings):
        dm = settings.get("display_mode", self._display_mode)
        if dm == "Vectorscope":
            dm = "Linear"
        self._display_mode = dm if dm in self._VALID_DISPLAY_MODES else "Linear"
        cm = settings.get("color_mode", self._color_mode)
        self._color_mode = cm if cm in self._VALID_COLOR_MODES else "Static"
        crm = settings.get("corr_mode", self._corr_mode)
        self._corr_mode = crm if crm in self._VALID_CORR_MODES else "Single-Band"
        gm = settings.get("guide_mode", self._guide_mode)
        self._guide_mode = gm if gm in self._VALID_GUIDE_MODES else "Rhombus"
        self._zoom = float(settings.get("zoom", self._zoom))
        self._auto_zoom = bool(settings.get("auto_zoom", self._auto_zoom))
        azm = settings.get("auto_zoom_mode", self._auto_zoom_mode)
        self._auto_zoom_mode = azm if azm in self._VALID_AUTO_ZOOM_MODES else "Padded"
        ts = settings.get("trace_style", self._trace_style)
        self._trace_style = ts if ts in self._VALID_TRACE_STYLES else "Persistence"
        self._width_gain = float(settings.get("width_gain", self._width_gain))
        self._auto_width = bool(settings.get("auto_width", self._auto_width))
        self._persistence = float(settings.get("persistence", self._persistence))
        self._max_dots = int(settings.get("max_dots", self._max_dots))
        self._show_labels = bool(settings.get("show_labels", self._show_labels))
        self._minimal_mode = bool(settings.get("minimal_mode", self._minimal_mode))
        self._halved_view = bool(settings.get("halved_view", self._halved_view))
        self._corr_pos = str(settings.get("corr_pos", self._corr_pos))
        self._rotation = int(settings.get("rotation", self._rotation))

    def build_context_menu(self, menu):
        from PySide6.QtGui import QActionGroup
        
        # Display Mode
        dm = menu.addMenu("Display Mode")
        dg = QActionGroup(self)
        for d in ["Linear", "Scaled", "Lissajous", "XY Oscilloscope"]:
            a = dm.addAction(d)
            a.setCheckable(True)
            a.setChecked(d == self._display_mode or (d == "Linear" and self._display_mode == "Vectorscope"))
            a.triggered.connect(lambda checked, t=d: (setattr(self, "_display_mode", t), self._clear_scope_persistence(), self.canvas.update()))
            dg.addAction(a)

        # View & Guides
        vm = menu.addMenu("View & Guides")
        gm = vm.addMenu("Guide Map")
        gg = QActionGroup(self)
        for g in ["None", "Rhombus", "Circle", "Square"]:
            a = gm.addAction(g)
            a.setCheckable(True)
            a.setChecked(g == self._guide_mode)
            a.triggered.connect(lambda checked, t=g: setattr(self, "_guide_mode", t))
            gg.addAction(a)

        rm = vm.addMenu("Rotation")
        rg = QActionGroup(self)
        for r in range(-180, 181, 45):
            label = f"{r}°" if r == 0 else (f"+{r}°" if r > 0 else f"{r}°")
            a = rm.addAction(label)
            a.setCheckable(True)
            a.setChecked(r == self._rotation)
            a.triggered.connect(lambda checked, v=r: (setattr(self, "_rotation", v), self.canvas.update()))
            rg.addAction(a)
        rm.setEnabled(not self._halved_view)

        vm.addSeparator()
        a_min = vm.addAction("Minimal Mode")
        a_min.setCheckable(True)
        a_min.setChecked(self._minimal_mode)
        a_min.triggered.connect(lambda checked: (setattr(self, "_minimal_mode", checked), self.canvas.update()))

        a_lbl = vm.addAction("Show Labels")
        a_lbl.setCheckable(True)
        a_lbl.setChecked(self._show_labels)
        a_lbl.triggered.connect(lambda checked: (setattr(self, "_show_labels", checked), self.canvas.update()))

        a_hlv = vm.addAction("Halved View")
        a_hlv.setCheckable(True)
        a_hlv.setChecked(self._halved_view)
        a_hlv.triggered.connect(lambda checked: (setattr(self, "_halved_view", checked), self.canvas.update()))

        # Correlation
        crm_menu = menu.addMenu("Correlation")
        crg = QActionGroup(self)
        for c in ["Single-Band", "Multi-Band"]:
            a = crm_menu.addAction(c)
            a.setCheckable(True)
            a.setChecked(c == self._corr_mode)
            a.triggered.connect(lambda checked, t=c: setattr(self, "_corr_mode", t))
            crg.addAction(a)

        crm_menu.addSeparator()
        cpm = crm_menu.addMenu("Position")
        cpg = QActionGroup(self)
        for p in ["Top", "Bottom", "Left", "Right"]:
            a = cpm.addAction(p)
            a.setCheckable(True)
            a.setChecked(p == self._corr_pos)
            a.triggered.connect(lambda checked, t=p: setattr(self, "_corr_pos", t))
            cpg.addAction(a)
        cpm.setEnabled(not self._minimal_mode)

        pm = crm_menu.addMenu("Smoothing")
        pg = QActionGroup(self)
        for p, label in [(0.0, "None (Fast)"), (0.5, "Natural"), (0.8, "Smooth"), (0.95, "Slow")]:
            a = pm.addAction(label)
            a.setCheckable(True)
            a.setChecked(abs(p - self._persistence) < 0.01)
            a.triggered.connect(lambda checked, v=p: (setattr(self, "_persistence", v), self.canvas.update()))
            pg.addAction(a)

        # Trace & Scaling
        tm_sub = menu.addMenu("Trace & Scaling")
        zm = tm_sub.addMenu("Zoom")
        zg = QActionGroup(self)

        a_padded = zm.addAction("Auto (Padded)")
        a_padded.setCheckable(True)
        a_padded.setChecked(self._auto_zoom and self._auto_zoom_mode == "Padded")
        a_padded.triggered.connect(lambda checked: self._set_auto_zoom_mode("Padded"))
        zg.addAction(a_padded)

        a_max = zm.addAction("Auto (Max Zoom)")
        a_max.setCheckable(True)
        a_max.setChecked(self._auto_zoom and self._auto_zoom_mode == "Max")
        a_max.triggered.connect(lambda checked: self._set_auto_zoom_mode("Max"))
        zg.addAction(a_max)

        zm.addSeparator()

        for z in [0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0, 4.0, 5.0]:
            a = zm.addAction(f"{z}x")
            a.setCheckable(True)
            a.setChecked(not self._auto_zoom and abs(z - self._zoom) < 0.01)
            a.triggered.connect(lambda checked, v=z: self._set_manual_zoom(v))
            zg.addAction(a)

        wm = tm_sub.addMenu("Width Gain")
        wg = QActionGroup(self)
        auto_w = wm.addAction("Auto")
        auto_w.setCheckable(True)
        auto_w.setChecked(self._auto_width)
        auto_w.triggered.connect(lambda checked: (setattr(self, "_auto_width", checked), self.canvas.update()))
        wg.addAction(auto_w)
        for w in [1.0, 1.2, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0]:
            a = wm.addAction(f"{w}x")
            a.setCheckable(True)
            a.setChecked(not self._auto_width and abs(w - self._width_gain) < 0.01)
            a.triggered.connect(lambda checked, v=w: (setattr(self, "_auto_width", False), setattr(self, "_width_gain", v), self.canvas.update()))
            wg.addAction(a)

        tm = tm_sub.addMenu("Trace Style")
        tg = QActionGroup(self)
        for style in ["Persistence", "Instant"]:
            a = tm.addAction(style)
            a.setCheckable(True)
            a.setChecked(style == self._trace_style)
            a.triggered.connect(lambda checked, v=style: self._set_trace_style(v))
            tg.addAction(a)

        sm = tm_sub.addMenu("Max Dots (Density)")
        sg = QActionGroup(self)
        for d in [256, 512, 1024, 2048, 4096, 8192]:
            a = sm.addAction(str(d))
            a.setCheckable(True)
            a.setChecked(d == self._max_dots)
            a.triggered.connect(lambda checked, v=d: (setattr(self, "_max_dots", v), self.canvas.update()))
            sg.addAction(a)

        cm = tm_sub.addMenu("Color")
        cg = QActionGroup(self)
        for c in ["Static", "Multi-Band", "Multi-Band (RGB)"]:
            a = cm.addAction(c)
            a.setCheckable(True)
            a.setChecked(c == self._color_mode)
            a.triggered.connect(lambda checked, t=c: setattr(self, "_color_mode", t))
            cg.addAction(a)

    def _set_auto_zoom_mode(self, mode):
        self._auto_zoom = True
        self._auto_zoom_mode = mode if mode in self._VALID_AUTO_ZOOM_MODES else "Padded"
        self._clear_scope_persistence()
        self.canvas.update()

    def _set_auto_zoom(self, enabled):
        self._auto_zoom = bool(enabled)
        self._clear_scope_persistence()
        self.canvas.update()

    def _set_manual_zoom(self, value):
        self._auto_zoom = False
        self._zoom = float(value)
        self._clear_scope_persistence()
        self.canvas.update()

    def _set_trace_style(self, style):
        self._trace_style = style if style in self._VALID_TRACE_STYLES else "Persistence"
        self._clear_scope_persistence()
        self.canvas.update()

    def _clear_scope_persistence(self):
        self._scope_pixmap = None
        self._scope_pixmap_key = None

    def on_audio_data(self, data: np.ndarray):
        n = len(data)
        l_raw = data[:, 0].copy()
        r_raw = data[:, 1].copy() if data.shape[1] > 1 else data[:, 0].copy()
        
        # 1. Apply Width Gain (Mid/Side processing)
        mid_raw = (l_raw + r_raw) * 0.5
        side_raw = (l_raw - r_raw) * 0.5

        if self._auto_width:
            abs_m = np.abs(mid_raw)
            abs_s = np.abs(side_raw)
            p_mid = float(np.percentile(abs_m, 95)) if len(abs_m) > 64 else float(np.max(abs_m))
            p_side = float(np.percentile(abs_s, 95)) if len(abs_s) > 64 else float(np.max(abs_s))
            if p_mid > 0.005 and p_side > 0.001:
                target_w = float(np.clip(p_mid / (p_side * 1.6), 1.0, 5.0))
            else:
                target_w = 1.0
            alpha_w = 0.25 if target_w < self._auto_width_gain else 0.08
            self._auto_width_gain += (target_w - self._auto_width_gain) * alpha_w
            active_width = self._auto_width_gain
        else:
            active_width = self._width_gain

        if active_width != 1.0:
            side = side_raw * active_width
            l_proc = mid_raw + side
            r_proc = mid_raw - side
        else:
            l_proc, r_proc = l_raw, r_raw

        target_len = max(1024, self._max_dots)
        n_in = len(l_proc)
        l_xy = l_proc - float(np.mean(l_proc))
        r_xy = r_proc - float(np.mean(r_proc))

        if len(self._left) < target_len:
            self._left = np.concatenate([self._left, l_proc])[-target_len:]
            self._right = np.concatenate([self._right, r_proc])[-target_len:]
            self._left_xy = np.concatenate([self._left_xy, l_xy])[-target_len:]
            self._right_xy = np.concatenate([self._right_xy, r_xy])[-target_len:]
        else:
            if n_in >= target_len:
                self._left = l_proc[-target_len:].copy()
                self._right = r_proc[-target_len:].copy()
                self._left_xy = l_xy[-target_len:].copy()
                self._right_xy = r_xy[-target_len:].copy()
            else:
                self._left = np.roll(self._left, -n_in)
                self._left[-n_in:] = l_proc
                self._right = np.roll(self._right, -n_in)
                self._right[-n_in:] = r_proc
                self._left_xy = np.roll(self._left_xy, -n_in)
                self._left_xy[-n_in:] = l_xy
                self._right_xy = np.roll(self._right_xy, -n_in)
                self._right_xy[-n_in:] = r_xy

        if self._color_mode.startswith("Multi-Band"):
            self._bands_l = self._multiband.split(self._left)
            self._bands_r = self._multiband.split(self._right)
        else:
            self._bands_l = None
            self._bands_r = None

        if self._auto_zoom:
            if self._display_mode == "XY Oscilloscope":
                self._update_auto_zoom(self._left_xy, self._right_xy)
            else:
                self._update_auto_zoom(self._left, self._right)
        
        # 3. Smoothed Correlation
        new_corr = correlation(l_raw, r_raw)
        alpha = 1.0 - self._persistence
        if self._persistence == 0: alpha = 1.0
        
        self._corr = self._corr * (1.0 - alpha) + new_corr * alpha
        # Peak/Ghost decay
        self._corr_peak = max(abs(self._corr_peak) * 0.95, abs(self._corr)) * np.sign(self._corr if abs(self._corr) > abs(self._corr_peak) * 0.95 else self._corr_peak)
        # Simplify peak logic: just a slow-following "shadow"
        if not hasattr(self, "_corr_ghost"): self._corr_ghost = self._corr
        self._corr_ghost = self._corr_ghost * 0.9 + self._corr * 0.1
        
        if self._corr_mode == "Multi-Band":
            new_mb = multiband_correlation(
                l_raw, r_raw, self.audio_engine.sample_rate)
            if not hasattr(self, "_mb_corr_ghost"): self._mb_corr_ghost = {}
            for k in new_mb:
                old = self._mb_corr.get(k, 0.0)
                self._mb_corr[k] = old * (1.0 - alpha) + new_mb[k] * alpha
                old_g = self._mb_corr_ghost.get(k, self._mb_corr[k])
                self._mb_corr_ghost[k] = old_g * 0.92 + self._mb_corr[k] * 0.08

    def _update_auto_zoom(self, left, right):
        if len(left) < 2:
            return

        if self._display_mode in ("Vectorscope", "Scaled", "Linear"):
            dx = (right - left) * 0.5
            dy = (left + right) * 0.5
        elif self._display_mode == "XY Oscilloscope":
            dx = left
            dy = right
        else:
            dx = right
            dy = left

        if self._guide_mode == "Circle":
            magnitude = np.sqrt(dx * dx + dy * dy)
        elif self._guide_mode == "Square":
            magnitude = np.maximum(np.abs(dx), np.abs(dy))
        else:
            magnitude = np.abs(dx) + np.abs(dy)

        peak = float(np.percentile(magnitude, 99.0)) if len(magnitude) > 64 else float(np.max(magnitude))
        if peak < 0.0005:
            target = 1.0
        else:
            if getattr(self, "_auto_zoom_mode", "Padded") == "Max":
                target = 0.96 / peak
            else:
                target = 0.68 / peak
            target = max(0.35, min(16.0, target))

        alpha = 0.35 if target < self._auto_zoom_value else 0.12
        self._auto_zoom_value += (target - self._auto_zoom_value) * alpha

    def _effective_zoom(self):
        return self._auto_zoom_value if self._auto_zoom else self._zoom

    def _render(self, painter, w, h):
        corr_size = 28 if not self._minimal_mode else 0
        pos = self._corr_pos
        
        if self._minimal_mode:
            scope_rect = QRectF(0, 0, w, h)
            corr_rect = QRectF(0, 0, 0, 0)
        elif pos == "Bottom":
            scope_rect = QRectF(0, 0, w, h - corr_size)
            corr_rect = QRectF(0, h - corr_size, w, corr_size)
        elif pos == "Top":
            scope_rect = QRectF(0, corr_size, w, h - corr_size)
            corr_rect = QRectF(0, 0, w, corr_size)
        elif pos == "Left":
            scope_rect = QRectF(corr_size, 0, w - corr_size, h)
            corr_rect = QRectF(0, 0, corr_size, h)
        else: # Right
            scope_rect = QRectF(0, 0, w - corr_size, h)
            corr_rect = QRectF(w - corr_size, 0, corr_size, h)

        sw, sh = scope_rect.width(), scope_rect.height()
        sx, sy_off = scope_rect.x(), scope_rect.y()
        
        cx = sx + sw / 2
        
        # Reserve space for labels if they are showing
        margin = 18 if self._show_labels else 4
        
        if self._halved_view:
            cy = sy_off + sh
            radius = min(sw / 2 - margin, sh - margin)
        else:
            cy = sy_off + sh / 2
            radius = min(sw / 2 - margin, sh / 2 - margin)

        if self._trace_style == "Persistence":
            self._render_persistent_scope(w, h, scope_rect, cx, cy, radius)
            if self._scope_pixmap:
                painter.drawPixmap(0, 0, self._scope_pixmap)

        # Rotation / Transformation block
        painter.save()
        if self._rotation != 0 and not self._halved_view:
            painter.translate(cx, cy)
            painter.rotate(self._rotation)
            painter.translate(-cx, -cy)

        self._draw_scope_guides(painter, cx, cy, radius)
        if self._trace_style == "Instant":
            self._draw_scope_traces(painter, self._left, self._right, cx, cy, radius)

        painter.restore()

        # Labels
        if self._show_labels:
            painter.setPen(QColor(Colors.TEXT_DIM))
            
            def draw_rot_text(text, base_angle, dist_offset=12):
                rot = self._rotation if not self._halved_view else 0
                angle_rad = np.radians(base_angle + rot)
                # Calculate position on the circle
                lx = cx + np.cos(angle_rad) * (radius + dist_offset)
                ly = cy + np.sin(angle_rad) * (radius + dist_offset)
                
                # Check if visible in halved view
                if self._halved_view and ly > cy + 2:
                    return

                f_size = 14 if not self._halved_view else 12
                painter.setFont(self.get_responsive_font(Fonts.small, f_size + 4, f_size, text))
                painter.drawText(QRectF(lx - 15, ly - 10, 30, 20), Qt.AlignCenter, text)

            if self._display_mode in ("Vectorscope", "Scaled", "Linear"):
                draw_rot_text("M", -90)
                if not self._halved_view: draw_rot_text("M", 90)
                draw_rot_text("S", 0)
                draw_rot_text("S", 180)
            else:
                x_label = "X" if self._display_mode == "XY Oscilloscope" else "R"
                y_label = "Y" if self._display_mode == "XY Oscilloscope" else "L"
                draw_rot_text(y_label, -90)
                draw_rot_text(x_label, 90 if not self._halved_view else 0) # Adjust for halved view logic
                draw_rot_text(y_label, 180)
                draw_rot_text(x_label, 0)

        # Correlation bar

        # Correlation bar
        if not self._minimal_mode:
            is_vert_corr = pos in ["Left", "Right"]
            margin = 16 if is_vert_corr else 12
            inner_m = 6
            
            bx, by, bw, bh = corr_rect.x(), corr_rect.y(), corr_rect.width(), corr_rect.height()
            
            if is_vert_corr:
                bar_rect = QRectF(bx + inner_m, by + margin, bw - inner_m * 2, bh - margin * 2)
            else:
                bar_rect = QRectF(bx + margin, by + inner_m, bw - margin * 2, bh - inner_m * 2)
                
            painter.fillRect(bar_rect, QColor(Colors.BG_INPUT))
            
            if is_vert_corr:
                mid = bar_rect.y() + bar_rect.height() / 2
                painter.setPen(QPen(QColor(Colors.GRID_BRIGHT), 1))
                painter.drawLine(int(bar_rect.x()), int(mid), int(bar_rect.x() + bar_rect.width()), int(mid))
            else:
                mid = bar_rect.x() + bar_rect.width() / 2
                painter.setPen(QPen(QColor(Colors.GRID_BRIGHT), 1))
                painter.drawLine(int(mid), int(bar_rect.y()), int(mid), int(bar_rect.y() + bar_rect.height()))

            if self._corr_mode == "Single-Band":
                val = self._corr
                ghost = getattr(self, "_corr_ghost", val)
                
                # Ghost
                col_g = QColor(Colors.ACCENT_DIM); col_g.setAlpha(100)
                painter.setBrush(QBrush(col_g)); painter.setPen(Qt.NoPen)
                if is_vert_corr:
                    py = bar_rect.y() + bar_rect.height() * (1.0 - (ghost + 1) / 2.0)
                    painter.drawRoundedRect(QRectF(bar_rect.x() + 2, py - 2, bar_rect.width() - 4, 4), 1, 1)
                else:
                    px = bar_rect.x() + (ghost + 1) / 2 * bar_rect.width()
                    painter.drawRoundedRect(QRectF(px - 2, bar_rect.y() + 2, 4, bar_rect.height() - 4), 1, 1)

                # Active
                col = QColor(Colors.GREEN) if val > 0 else QColor(Colors.RED)
                painter.setBrush(QBrush(col)); painter.setPen(Qt.NoPen)
                if is_vert_corr:
                    py = bar_rect.y() + bar_rect.height() * (1.0 - (val + 1) / 2.0)
                    painter.drawRoundedRect(QRectF(bar_rect.x() + 1, py - 3, bar_rect.width() - 2, 6), 2, 2)
                else:
                    px = bar_rect.x() + (val + 1) / 2 * bar_rect.width()
                    painter.drawRoundedRect(QRectF(px - 3, bar_rect.y() + 1, 6, bar_rect.height() - 2), 2, 2)
            else:
                n_bands = 4
                bands = [("low", Colors.BAND_LOW), ("mid", Colors.BAND_MID), ("high", Colors.BAND_HIGH), ("overall", Colors.ACCENT)]
                
                sub_bw = bar_rect.width() / n_bands
                for j, (name, col_hex) in enumerate(bands):
                    val = self._mb_corr.get(name, 0.0)
                    ghost = getattr(self, "_mb_corr_ghost", {}).get(name, val)
                    sub_x = bar_rect.x() + j * sub_bw
                    
                    painter.fillRect(QRectF(sub_x + 1, bar_rect.y(), sub_bw - 2, bar_rect.height()), QColor(Colors.BG_DARKEST))
                    
                    mid_y = bar_rect.y() + bar_rect.height() / 2
                    painter.setPen(QPen(QColor(Colors.GRID), 0.5))
                    painter.drawLine(int(sub_x + 1), int(mid_y), int(sub_x + sub_bw - 1), int(mid_y))
                    
                    # Ghost
                    col_g = QColor(col_hex); col_g.setAlpha(80)
                    painter.setBrush(QBrush(col_g)); painter.setPen(Qt.NoPen)
                    py_g = bar_rect.y() + bar_rect.height() * (1.0 - (ghost + 1) / 2.0)
                    painter.drawRect(QRectF(sub_x + 2, py_g - 1, sub_bw - 4, 2))

                    # Active
                    painter.setBrush(QBrush(QColor(col_hex)))
                    py = bar_rect.y() + bar_rect.height() * (1.0 - (val + 1) / 2.0)
                    ind_w = max(2.0, sub_bw - 4)
                    ind_x = sub_x + (sub_bw - ind_w) / 2
                    painter.drawRoundedRect(QRectF(ind_x, py - 2, ind_w, 4), 1, 1)

            painter.setPen(QColor(Colors.TEXT_DIM))
            # Consistent Labels for Vertical Scale (+1 top, -1 bottom)
            painter.setFont(self.get_responsive_font(Fonts.small, bw if is_vert_corr else 20, 14, "+1"))
            if is_vert_corr:
                painter.drawText(QRectF(bx, bar_rect.y() - 14, bw, 14), Qt.AlignCenter, "+1")
                painter.drawText(QRectF(bx, bar_rect.y() + bar_rect.height(), bw, 14), Qt.AlignCenter, "-1")
            else:
                # Labels at the ends of the horizontal stretch (but still referring to the vertical scale of the segments)
                painter.drawText(QRectF(bx, bar_rect.y() - 14, 20, 14), Qt.AlignLeft, "+1")
                painter.drawText(QRectF(bx + bw - 20, bar_rect.y() - 14, 20, 14), Qt.AlignRight, "+1")
                painter.drawText(QRectF(bx, bar_rect.y() + bh, 20, 14), Qt.AlignLeft, "-1")
                painter.drawText(QRectF(bx + bw - 20, bar_rect.y() + bh, 20, 14), Qt.AlignRight, "-1")

    def _draw_scope_guides(self, painter, cx, cy, radius):
        painter.setPen(QPen(QColor(Colors.GRID), 0.5))
        painter.drawLine(int(cx), int(cy - radius), int(cx), int(cy + radius))
        painter.drawLine(int(cx - radius), int(cy), int(cx + radius), int(cy))

        painter.setPen(QPen(QColor(Colors.GRID), 1))
        if self._guide_mode == "Rhombus":
            if self._halved_view:
                painter.drawPolygon([QPointF(cx-radius, cy), QPointF(cx, cy-radius), QPointF(cx+radius, cy)])
            else:
                painter.drawPolygon([QPointF(cx, cy-radius), QPointF(cx+radius, cy), QPointF(cx, cy+radius), QPointF(cx-radius, cy)])
        elif self._guide_mode == "Circle":
            if self._halved_view:
                painter.drawArc(int(cx-radius), int(cy-radius), int(radius*2), int(radius*2), 0, 180 * 16)
                painter.drawLine(int(cx-radius), int(cy), int(cx+radius), int(cy))
            else:
                painter.drawEllipse(QPointF(cx, cy), radius, radius)
        elif self._guide_mode == "Square":
            if self._halved_view:
                painter.drawPolyline([QPointF(cx-radius, cy), QPointF(cx-radius, cy-radius), QPointF(cx+radius, cy-radius), QPointF(cx+radius, cy)])
            else:
                painter.drawRect(QRectF(cx - radius, cy - radius, radius * 2, radius * 2))

    def _draw_scope_traces(self, painter, left, right, cx, cy, radius):
        n = len(left)
        if n == 0:
            return

        if self._display_mode == "XY Oscilloscope":
            self._draw_trace(painter, self._left_xy, self._right_xy, cx, cy, radius, QColor(Colors.ACCENT), 220)
            return

        peak = max(float(np.max(np.abs(left))), float(np.max(np.abs(right))))
        if peak < 1e-4:
            painter.save()
            pen_core = QPen(QColor(Colors.ACCENT), 2.0)
            pen_core.setCapStyle(Qt.RoundCap)
            painter.setPen(pen_core)
            painter.setOpacity(0.6)
            painter.drawPoints([QPointF(cx, cy)])
            painter.restore()
            return

        if self._color_mode.startswith("Multi-Band"):
            if self._bands_l is None or self._bands_r is None:
                self._bands_l = self._multiband.split(left)
                self._bands_r = self._multiband.split(right)
            low_l, mid_l, high_l = self._bands_l
            low_r, mid_r, high_r = self._bands_r
            cols = ["#FF3333", "#33FF33", "#3388FF"] if self._color_mode == "Multi-Band (RGB)" else [Colors.BAND_LOW, Colors.BAND_MID, Colors.BAND_HIGH]
            for bl, br, col in zip([low_l, mid_l, high_l], [low_r, mid_r, high_r], cols):
                self._draw_trace(painter, bl, br, cx, cy, radius, QColor(col), 160)
        else:
            self._draw_trace(painter, left, right, cx, cy, radius, QColor(Colors.ACCENT), 200)

    def _render_persistent_scope(self, w, h, scope_rect, cx, cy, radius):
        if w <= 0 or h <= 0 or radius <= 0 or scope_rect.width() <= 0 or scope_rect.height() <= 0:
            return
        key = (
            int(w),
            int(h),
            int(scope_rect.x()),
            int(scope_rect.y()),
            int(scope_rect.width()),
            int(scope_rect.height()),
            int(radius),
            self._display_mode,
            self._guide_mode,
            self._halved_view,
            self._rotation,
        )
        if self._scope_pixmap is None or self._scope_pixmap_key != key:
            self._scope_pixmap = QPixmap(w, h)
            self._scope_pixmap.fill(Qt.transparent)
            self._scope_pixmap_key = key

        p = QPainter(self._scope_pixmap)
        if not p.isActive():
            return
        p.setRenderHint(QPainter.Antialiasing, True)
        fade_alpha = int(np.clip((1.0 - self._persistence) * 160.0 + 16.0, 12, 240))
        if self._color_mode.startswith("Multi-Band"):
            fade_alpha = int(np.clip(fade_alpha * 1.25, 16, 255))
        fade_color = QColor(Colors.BG_MODULE)
        fade_color.setAlpha(fade_alpha)
        p.fillRect(scope_rect, fade_color)
        p.save()
        if self._rotation != 0 and not self._halved_view:
            p.translate(cx, cy)
            p.rotate(self._rotation)
            p.translate(-cx, -cy)
        self._draw_scope_traces(p, self._left, self._right, cx, cy, radius)
        p.restore()
        p.end()

    def _draw_trace(self, painter, left, right, cx, cy, radius, color, alpha):
        n = len(left)
        if n == 0:
            return
        peak = max(float(np.max(np.abs(left))), float(np.max(np.abs(right))))
        if peak < 1e-4:
            painter.save()
            pen_core = QPen(QColor(color), 2.0)
            pen_core.setCapStyle(Qt.RoundCap)
            painter.setPen(pen_core)
            painter.setOpacity(alpha / 255.0)
            painter.drawPoints([QPointF(cx, cy)])
            painter.restore()
            return

        step = max(1, n // self._max_dots)
        
        zoom = self._effective_zoom()
        l_seg = left[::step] * zoom
        r_seg = right[::step] * zoom

        painter.save()
        painter.setOpacity(alpha / 255.0)

        if self._display_mode in ("Vectorscope", "Scaled", "Linear"):
            # 1. Vectorscope / Scaled Point Cloud - Shows Stereo Density
            # Standard M/S: Left on left (-), Right on right (+)
            dx = (r_seg - l_seg) * 0.5
            dy = (l_seg + r_seg) * 0.5

            if self._display_mode == "Scaled":
                # Smooth log companding: lifts quiet samples without creating a hole in the center
                r = np.sqrt(dx * dx + dy * dy)
                r_safe = np.maximum(r, 1e-7)
                scale = np.log10(1.0 + 9.0 * r_safe) / r_safe
                dx = dx * scale
                dy = dy * scale
            
            # Soft-knee limiting to Guide Map
            if self._guide_mode == "Circle":
                mag = np.sqrt(dx**2 + dy**2)
                mask = mag > 0.96
                if np.any(mask):
                    soft_mag = 0.96 + 0.035 * np.tanh((mag[mask] - 0.96) / 0.15)
                    scale = soft_mag / np.maximum(mag[mask], 1e-7)
                    dx[mask] *= scale
                    dy[mask] *= scale
            elif self._guide_mode == "Square":
                mag = np.maximum(np.abs(dx), np.abs(dy))
                mask = mag > 0.96
                if np.any(mask):
                    soft_mag = 0.96 + 0.035 * np.tanh((mag[mask] - 0.96) / 0.15)
                    scale = soft_mag / np.maximum(mag[mask], 1e-7)
                    dx[mask] *= scale
                    dy[mask] *= scale
            else:
                # Rhombus is the standard M/S boundary
                mag = np.abs(dx) + np.abs(dy)
                mask = mag > 0.96
                if np.any(mask):
                    soft_mag = 0.96 + 0.035 * np.tanh((mag[mask] - 0.96) / 0.15)
                    scale = soft_mag / np.maximum(mag[mask], 1e-7)
                    dx[mask] *= scale
                    dy[mask] *= scale
            
            xs = cx + dx * radius
            ys = cy - dy * radius
            
            points = [QPointF(float(x), float(y)) for x, y in zip(xs, ys)]
            if not points: 
                painter.restore()
                return
            
            # Crisp phosphor point cloud (1.0px native antialiasing prevents heavy CPU polygon expansion)
            pen_core = QPen(QColor(color), 1.0)
            painter.setPen(pen_core)
            painter.setOpacity(alpha / 255.0)
            painter.drawPoints(points)

        elif self._display_mode == "XY Oscilloscope":
            dx = l_seg
            dy = r_seg

            if self._guide_mode == "Circle":
                mag = np.sqrt(dx**2 + dy**2)
                mask = mag > 0.96
                if np.any(mask):
                    soft_mag = 0.96 + 0.035 * np.tanh((mag[mask] - 0.96) / 0.15)
                    scale = soft_mag / np.maximum(mag[mask], 1e-7)
                    dx[mask] *= scale
                    dy[mask] *= scale
            else:
                mag = np.maximum(np.abs(dx), np.abs(dy))
                mask = mag > 0.96
                if np.any(mask):
                    soft_mag = 0.96 + 0.035 * np.tanh((mag[mask] - 0.96) / 0.15)
                    scale = soft_mag / np.maximum(mag[mask], 1e-7)
                    dx[mask] *= scale
                    dy[mask] *= scale

            xs = cx + dx * radius
            ys = cy - dy * radius
            points = [QPointF(float(x), float(y)) for x, y in zip(xs, ys)]
            if len(points) < 2:
                painter.restore()
                return

            # Luminous core beam pass (1.0px MiterJoin avoids CPU polygon expansion)
            pen_core = QPen(QColor(color), 1.0)
            pen_core.setJoinStyle(Qt.MiterJoin)
            painter.setPen(pen_core)
            painter.drawPolyline(points)
            
        else:
            # 2. Lissajous (Polyline) - Shows Phase Curves
            dx = right[::step] * zoom
            dy = left[::step] * zoom
            
            # Limiting to Guide Map
            if self._guide_mode == "Circle":
                mag = np.sqrt(dx**2 + dy**2)
                mask = mag > 0.96
                if np.any(mask):
                    soft_mag = 0.96 + 0.035 * np.tanh((mag[mask] - 0.96) / 0.15)
                    scale = soft_mag / np.maximum(mag[mask], 1e-7)
                    dx[mask] *= scale
                    dy[mask] *= scale
            elif self._guide_mode == "Square":
                mag = np.maximum(np.abs(dx), np.abs(dy))
                mask = mag > 0.96
                if np.any(mask):
                    soft_mag = 0.96 + 0.035 * np.tanh((mag[mask] - 0.96) / 0.15)
                    scale = soft_mag / np.maximum(mag[mask], 1e-7)
                    dx[mask] *= scale
                    dy[mask] *= scale
            else:
                mag = np.abs(dx) + np.abs(dy)
                mask = mag > 0.96
                if np.any(mask):
                    soft_mag = 0.96 + 0.035 * np.tanh((mag[mask] - 0.96) / 0.15)
                    scale = soft_mag / np.maximum(mag[mask], 1e-7)
                    dx[mask] *= scale
                    dy[mask] *= scale
            
            xs = cx + dx * radius
            ys = cy - dy * radius
            
            points = [QPointF(float(x), float(y)) for x, y in zip(xs, ys)]
            if len(points) < 2: 
                painter.restore()
                return
            
            # Luminous core beam pass (1.0px MiterJoin avoids CPU polygon expansion)
            pen_core = QPen(QColor(color), 1.0)
            pen_core.setJoinStyle(Qt.MiterJoin)
            painter.setPen(pen_core)
            painter.drawPolyline(points)
            
        painter.restore()
