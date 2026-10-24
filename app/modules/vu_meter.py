"""
Classic VU Meter Module: Analog-style needle meter with ballistics.
"""

import math
import numpy as np
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QPainterPath, QLinearGradient, QFont
from PySide6.QtCore import Qt, QPointF, QRectF

from app.base_module import BaseModule
from app.modules import register_module
from app.theme import Colors, Fonts


VU_STYLE_NAMES = [
    "Modern",
    "Classic Dark",
    "LED Bar",
    "Compaq Modern",
    "Compaq Vintage",
    "Tape Deck",
    "Neon Arc",
    "Broadcast Twin",
]
VU_CHANNELS = ["L+R", "Left", "Right", "Mid", "Side"]


@register_module("vu_meter", "VU Meter", category="Level & Dynamics")
class VUMeterModule(BaseModule):

    def __init__(self, audio_engine, parent=None):
        self._pos_l = 0.0
        self._pos_r = 0.0
        self._vel_l = 0.0
        self._vel_r = 0.0
        self._needle_l = -20.0
        self._needle_r = -20.0
        self._target_l = -20.0
        self._target_r = -20.0
        self._peak_lit_l = False
        self._peak_lit_r = False
        self._clip_lit_l = False
        self._clip_lit_r = False
        self._peak_timer_l = 0.0
        self._peak_timer_r = 0.0
        self._clip_timer_l = 0.0
        self._clip_timer_r = 0.0
        self._ms_l = 1e-12
        self._ms_r = 1e-12
        self._peak_threshold = -6.0
        self._clip_threshold = -0.1
        self._cal_offset = 0.0
        self._channel = "L+R" if audio_engine.channels >= 2 else "Left"
        self._style = 0
        self._show_peak = True
        self._show_clip = True
        self._rise_coeff = 0.30
        self._fall_coeff = 0.08
        # Peak hold for LED Bar style
        self._peak_hold_l = -40.0
        self._peak_hold_r = -40.0
        self._peak_hold_decay = 0.02
        self.module_key = "vu_meter"
        super().__init__(audio_engine, title="VU Meter", parent=parent)
        self.canvas.set_render_func(self._render)

    def get_settings(self):
        return {
            "channel": self._channel,
            "cal_offset": self._cal_offset,
            "style": self._style,
            "show_peak": self._show_peak,
            "show_clip": self._show_clip
        }

    def apply_settings(self, settings):
        if not isinstance(settings, dict):
            return
        channel = settings.get("channel", self._channel)
        self._channel = channel if channel in VU_CHANNELS else self._channel
        self._cal_offset = self._coerce_float(settings.get("cal_offset"), self._cal_offset, -60.0, 60.0)
        self._style = self._coerce_style(settings.get("style"), self._style)
        self._show_peak = self._coerce_bool(settings.get("show_peak"), self._show_peak)
        self._show_clip = self._coerce_bool(settings.get("show_clip"), self._show_clip)

    @staticmethod
    def _coerce_bool(value, fallback):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            text = value.strip().lower()
            if text in ("true", "1", "yes", "on"):
                return True
            if text in ("false", "0", "no", "off"):
                return False
        return fallback

    @staticmethod
    def _coerce_float(value, fallback, minimum=None, maximum=None):
        try:
            result = float(value)
        except (TypeError, ValueError):
            return fallback
        if not math.isfinite(result):
            return fallback
        if minimum is not None:
            result = max(minimum, result)
        if maximum is not None:
            result = min(maximum, result)
        return result

    @staticmethod
    def _coerce_style(value, fallback):
        try:
            style = int(value)
        except (TypeError, ValueError):
            return fallback
        return style if 0 <= style < len(VU_STYLE_NAMES) else fallback

    def build_context_menu(self, menu):
        from PySide6.QtGui import QActionGroup
        
        sm = menu.addMenu("Style")
        sg = QActionGroup(self)
        for i, s in enumerate(VU_STYLE_NAMES):
            a = sm.addAction(s)
            a.setCheckable(True)
            a.setChecked(i == self._style)
            a.triggered.connect(lambda checked, idx=i: setattr(self, "_style", idx))
            sg.addAction(a)
            
        cm = menu.addMenu("Channel")
        cg = QActionGroup(self)
        for c in VU_CHANNELS:
            a = cm.addAction(c)
            a.setCheckable(True)
            a.setChecked(c == self._channel)
            a.triggered.connect(lambda checked, t=c: setattr(self, "_channel", t))
            cg.addAction(a)

        calm = menu.addMenu("Calibration (dB)")
        calg = QActionGroup(self)
        for c in [-20, -15, -10, -5, -3, -2, -1, 0, 1, 2, 3, 5, 10, 15, 20]:
            a = calm.addAction(str(c))
            a.setCheckable(True)
            a.setChecked(abs(c - self._cal_offset) < 0.1)
            a.triggered.connect(lambda checked, v=c: setattr(self, "_cal_offset", float(v)))
            calg.addAction(a)
            
        a = menu.addAction("Peak LED")
        a.setCheckable(True)
        a.setChecked(self._show_peak)
        a.triggered.connect(lambda checked: setattr(self, "_show_peak", checked))

        a = menu.addAction("Clip LED")
        a.setCheckable(True)
        a.setChecked(self._show_clip)
        a.triggered.connect(lambda checked: setattr(self, "_show_clip", checked))

    def on_audio_data(self, data: np.ndarray):
        l = data[:, 0]
        r = data[:, 1] if data.shape[1] > 1 else l
        
        # Audio block duration in seconds for integration
        sr = getattr(self.audio_engine, "sample_rate", 44100.0)
        dt = float(len(data)) / float(sr) if sr > 0 else 0.02
        
        # Sample peak in dBFS (without calibration offset)
        pk_l = float(np.max(np.abs(l))) if len(l) > 0 else 0.0
        pk_r = float(np.max(np.abs(r))) if len(r) > 0 else 0.0
        peak_dbfs_l = 20.0 * math.log10(max(pk_l, 1e-10))
        peak_dbfs_r = 20.0 * math.log10(max(pk_r, 1e-10))
        
        # Peak & Clip LED triggers (with 180ms hold timer so flashes are clearly visible)
        hold_time = 0.18
        if peak_dbfs_l >= self._clip_threshold:
            self._clip_timer_l = hold_time
        else:
            self._clip_timer_l = max(0.0, self._clip_timer_l - dt)

        if peak_dbfs_r >= self._clip_threshold:
            self._clip_timer_r = hold_time
        else:
            self._clip_timer_r = max(0.0, self._clip_timer_r - dt)

        if peak_dbfs_l >= self._peak_threshold:
            self._peak_timer_l = hold_time
        else:
            self._peak_timer_l = max(0.0, self._peak_timer_l - dt)

        if peak_dbfs_r >= self._peak_threshold:
            self._peak_timer_r = hold_time
        else:
            self._peak_timer_r = max(0.0, self._peak_timer_r - dt)

        self._clip_lit_l = self._clip_timer_l > 0.0
        self._clip_lit_r = self._clip_timer_r > 0.0
        self._peak_lit_l = self._peak_timer_l > 0.0
        self._peak_lit_r = self._peak_timer_r > 0.0

        if self._channel == "L+R":
            curr_ms_l = float(np.mean(l ** 2)) if len(l) > 0 else 0.0
            curr_ms_r = float(np.mean(r ** 2)) if len(r) > 0 else 0.0
            
            # Fast AC cycle smoothing (15ms window eliminates audio wave ripple without lag)
            alpha_fast = 1.0 - math.exp(-dt / 0.015) if dt < 0.015 else 1.0
            self._ms_l += (curr_ms_l - self._ms_l) * alpha_fast
            self._ms_r += (curr_ms_r - self._ms_r) * alpha_fast
            
            rms_l_db = 10.0 * math.log10(max(self._ms_l, 1e-10))
            rms_r_db = 10.0 * math.log10(max(self._ms_r, 1e-10))
            
            target_l = max(-30.0, min(3.5, rms_l_db + self._cal_offset))
            target_r = max(-30.0, min(3.5, rms_r_db + self._cal_offset))
            self._target_l = target_l
            self._target_r = target_r
            
            # Physical 2nd-order VU needle ballistics (ANSI C16.5 galvanometer)
            f_target_l = max(0.0, min(1.05, (target_l + 20.0) / 23.0))
            f_target_r = max(0.0, min(1.05, (target_r + 20.0) / 23.0))
            
            if getattr(self, "_rise_coeff", 0.30) >= 0.99:
                self._pos_l = f_target_l
                self._pos_r = f_target_r
                self._vel_l = 0.0
                self._vel_r = 0.0
            else:
                omega_n = 15.2
                zeta = 0.70
                accel_l = omega_n**2 * (f_target_l - self._pos_l) - 2.0 * zeta * omega_n * self._vel_l
                accel_r = omega_n**2 * (f_target_r - self._pos_r) - 2.0 * zeta * omega_n * self._vel_r
                self._vel_l += accel_l * dt
                self._vel_r += accel_r * dt
                self._pos_l += self._vel_l * dt
                self._pos_r += self._vel_r * dt
                
                if self._pos_l <= 0.0:
                    self._pos_l = 0.0
                    self._vel_l = max(0.0, self._vel_l)
                elif self._pos_l >= 1.05:
                    self._pos_l = 1.05
                    self._vel_l = min(0.0, self._vel_l)
                    
                if self._pos_r <= 0.0:
                    self._pos_r = 0.0
                    self._vel_r = max(0.0, self._vel_r)
                elif self._pos_r >= 1.05:
                    self._pos_r = 1.05
                    self._vel_r = min(0.0, self._vel_r)
                    
            self._needle_l = self._pos_l * 23.0 - 20.0
            self._needle_r = self._pos_r * 23.0 - 20.0
            
            # Peak hold (for LED Bar and Tape Deck styles)
            decay_step = dt * 14.0
            if self._needle_l > self._peak_hold_l:
                self._peak_hold_l = self._needle_l
            else:
                self._peak_hold_l = max(-20.0, self._peak_hold_l - decay_step)
            if self._needle_r > self._peak_hold_r:
                self._peak_hold_r = self._needle_r
            else:
                self._peak_hold_r = max(-20.0, self._peak_hold_r - decay_step)
        else:
            sig = {"Left": l, "Right": r, "Mid": (l + r) * 0.5, "Side": (l - r) * 0.5}.get(self._channel, l)
            curr_ms = float(np.mean(sig ** 2)) if len(sig) > 0 else 0.0
            alpha_fast = 1.0 - math.exp(-dt / 0.015) if dt < 0.015 else 1.0
            self._ms_l += (curr_ms - self._ms_l) * alpha_fast
            self._ms_r = self._ms_l
            
            rms_db = 10.0 * math.log10(max(self._ms_l, 1e-10)) + self._cal_offset
            target = max(-30.0, min(3.5, rms_db))
            self._target_l = self._target_r = target
            f_target = max(0.0, min(1.05, (target + 20.0) / 23.0))
            
            if getattr(self, "_rise_coeff", 0.30) >= 0.99:
                self._pos_l = self._pos_r = f_target
                self._vel_l = self._vel_r = 0.0
            else:
                omega_n = 15.2
                zeta = 0.70
                accel = omega_n**2 * (f_target - self._pos_l) - 2.0 * zeta * omega_n * self._vel_l
                self._vel_l += accel * dt
                self._pos_l += self._vel_l * dt
                if self._pos_l <= 0.0:
                    self._pos_l = 0.0
                    self._vel_l = max(0.0, self._vel_l)
                elif self._pos_l >= 1.05:
                    self._pos_l = 1.05
                    self._vel_l = min(0.0, self._vel_l)
                self._pos_r = self._pos_l
                self._vel_r = self._vel_l
                
            self._needle_l = self._needle_r = self._pos_l * 23.0 - 20.0
            
            # Mono / selected channel peak & clip LEDs
            pk_sig = float(np.max(np.abs(sig))) if len(sig) > 0 else 0.0
            peak_sig_dbfs = 20.0 * math.log10(max(pk_sig, 1e-10))
            if peak_sig_dbfs >= self._clip_threshold:
                self._clip_timer_l = self._clip_timer_r = hold_time
            if peak_sig_dbfs >= self._peak_threshold:
                self._peak_timer_l = self._peak_timer_r = hold_time
            self._clip_lit_l = self._clip_lit_r = self._clip_timer_l > 0.0
            self._peak_lit_l = self._peak_lit_r = self._peak_timer_l > 0.0
            
            # Peak hold
            decay_step = dt * 14.0
            if self._needle_l > self._peak_hold_l:
                self._peak_hold_l = self._needle_l
            else:
                self._peak_hold_l = max(-20.0, self._peak_hold_l - decay_step)
            self._peak_hold_r = self._peak_hold_l

    def _render(self, painter, w, h):
        if self._style == 2:
            self._render_led_bar(painter, w, h)
            return
        if self._style in (3, 4):
            self._render_compaq(painter, w, h, vintage=self._style == 4)
            return
        if self._style == 5:
            self._render_tape_deck(painter, w, h)
            return
        if self._style == 6:
            self._render_neon_arc(painter, w, h)
            return
        if self._style == 7:
            self._render_broadcast_twin(painter, w, h)
            return
            
        style = self._style
        is_dark = (style == 1)
        is_stereo = (self._channel == "L+R")
        
        # Geometry: Ensure a stable pivot and a non-warped radius
        cx, cy = w / 2, h - 4
        # We cap the radius to ensure it doesn't look stretched in wide windows
        radius = min(w * 0.45, h * 0.95)
        if radius < 15: return

        angle_start, angle_end = 150, 30
        
        # Scale Definitions
        vu_marks = [(-20, "-20"), (-10, "-10"), (-7, "-7"), (-5, "-5"),
                    (-3, "-3"), (-2, ""), (-1, "-1"),
                    (0, "0"), (1, "+1"), (2, "+2"), (3, "+3")]

        if is_dark:
            # Classic Dark: "Recessed Studio" look
            # Draw a subtle background plate
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor("#0a0a12")))
            face_rect = QRectF(cx - radius * 1.1, cy - radius * 1.1, radius * 2.2, radius * 2.2)
            painter.drawPie(face_rect, int(angle_end * 16), int((angle_start - angle_end) * 16))
            
            # Scale Arc
            arc_r = radius * 0.96
            painter.setPen(QPen(QColor("#252535"), 2))
            painter.drawArc(QRectF(cx - arc_r, cy - arc_r, arc_r * 2, arc_r * 2), 
                            int(angle_end * 16), int((angle_start - angle_end) * 16))
            
            # Vintage Marks
            for db, label in vu_marks:
                frac = (db + 20) / 23.0
                angle = math.radians(angle_start - frac * (angle_start - angle_end))
                inner_r, outer_r = radius * 0.88, radius * 0.96
                
                col = QColor("#ff3344") if db >= 0 else QColor("#d0c0a0") # Warm cream
                painter.setPen(QPen(col, 2 if abs(db) % 5 == 0 or db == 0 else 1))
                painter.drawLine(QPointF(cx + inner_r * math.cos(angle), cy - inner_r * math.sin(angle)),
                                 QPointF(cx + outer_r * math.cos(angle), cy - outer_r * math.sin(angle)))
                
                if label:
                    # Adaptive decluttering: Hide minor labels if radius is small
                    if radius < 60 and db not in [-20, 0, 3]: continue
                    if radius < 90 and db not in [-20, -10, 0, 3]: continue
                    if radius < 120 and db in [-7, -3, -1, 1, 2]: continue
                    
                    lr = radius * 0.76
                    lx, ly = cx + lr * math.cos(angle) - 12, cy - lr * math.sin(angle) - 7
                    painter.setFont(self.get_responsive_font(Fonts.vu_scale, 24, 14, label))
                    painter.setPen(col)
                    painter.drawText(QRectF(lx, ly, 24, 14), Qt.AlignCenter, label)
        else:
            # Modern: Minimalist "Floating" look
            arc_r = radius * 0.95
            painter.setPen(QPen(QColor(Colors.GRID), 1))
            painter.drawArc(QRectF(cx - arc_r, cy - arc_r, arc_r * 2, arc_r * 2), 
                            int(angle_end * 16), int((angle_start - angle_end) * 16))
            
            # Red zone highlight
            red_frac = 20.0 / 23.0
            red_a = angle_start - red_frac * (angle_start - angle_end)
            painter.setPen(QPen(QColor(Colors.RED), 2))
            painter.drawArc(QRectF(cx - arc_r, cy - arc_r, arc_r * 2, arc_r * 2), 
                            int(angle_end * 16), int((red_a - angle_end) * 16))

            for db, label in vu_marks:
                frac = (db + 20) / 23.0
                angle = math.radians(angle_start - frac * (angle_start - angle_end))
                inner_r, outer_r = radius * 0.90, radius * 0.95
                
                col = QColor(Colors.RED) if db >= 0 else QColor(Colors.TEXT_DIM)
                painter.setPen(QPen(col, 1.2 if abs(db) % 5 == 0 or db == 0 else 0.6))
                painter.drawLine(QPointF(cx + inner_r * math.cos(angle), cy - inner_r * math.sin(angle)),
                                 QPointF(cx + outer_r * math.cos(angle), cy - outer_r * math.sin(angle)))
                
                if label:
                    # Adaptive decluttering: Hide minor labels if radius is small
                    if radius < 60 and db not in [-20, 0, 3]: continue
                    if radius < 90 and db not in [-20, -10, 0, 3]: continue
                    if radius < 120 and db in [-7, -3, -1, 1, 2]: continue
                    
                    lr = radius * 0.82
                    lx, ly = cx + lr * math.cos(angle) - 12, cy - lr * math.sin(angle) - 7
                    painter.setFont(self.get_responsive_font(Fonts.vu_scale, 24, 14, label))
                    painter.setPen(col)
                    painter.drawText(QRectF(lx, ly, 24, 14), Qt.AlignCenter, label)

        # Labels
        painter.setFont(self.get_responsive_font(Fonts.small, 80, 20, self._channel))
        painter.setPen(QColor(Colors.TEXT_DIM))
        painter.drawText(QRectF(cx - 40, cy - radius * 0.45, 80, 20), Qt.AlignCenter, self._channel)

        # Needles
        needle_vals = [self._needle_l, self._needle_r] if is_stereo else [self._needle_l]
        
        if is_dark:
            # Thick "Physical" Needles
            needle_cols = [QColor("#ff4422"), QColor("#ff8844")] if is_stereo else [QColor("#ff4422")]
            for val, col in zip(needle_vals, needle_cols):
                nf = max(0, min(1, (val + 20) / 23.0))
                na = math.radians(angle_start - nf * (angle_start - angle_end))
                
                # Needle body
                painter.setPen(QPen(col, 2.5))
                nx, ny = cx + radius * 1.05 * math.cos(na), cy - radius * 1.05 * math.sin(na)
                painter.drawLine(QPointF(cx, cy), QPointF(nx, ny))
            
            # Physical Pivot Cap
            painter.setBrush(QBrush(QColor("#222222")))
            painter.setPen(QPen(QColor("#444444"), 1))
            painter.drawEllipse(QPointF(cx, cy), 7, 7)
            painter.setBrush(QBrush(QColor("#111111")))
            painter.drawEllipse(QPointF(cx, cy), 3, 3)
        else:
            # Sleek Modern Needles
            needle_cols = [QColor(Colors.ACCENT), QColor(Colors.ACCENT_PINK)] if is_stereo else [QColor(Colors.ACCENT)]
            for val, col in zip(needle_vals, needle_cols):
                nf = max(0, min(1, (val + 20) / 23.0))
                na = math.radians(angle_start - nf * (angle_start - angle_end))
                
                # Subtle Glow/Shadow for visibility
                if not is_stereo:
                    painter.setPen(QPen(QColor(0, 0, 0, 60), 2.5))
                    sx, sy = cx + radius * 1.05 * math.cos(na), cy - radius * 1.05 * math.sin(na)
                    painter.drawLine(QPointF(cx + 1, cy + 1), QPointF(sx + 1, sy + 1))
                
                painter.setPen(QPen(col, 2))
                nx, ny = cx + radius * 1.05 * math.cos(na), cy - radius * 1.05 * math.sin(na)
                painter.drawLine(QPointF(cx, cy), QPointF(nx, ny))
                
            painter.setBrush(QBrush(needle_cols[0]))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QPointF(cx, cy), 5, 5)

        # PEAK / CLIP status
        painter.setFont(Fonts.small())
        if self._show_peak:
            lit = self._peak_lit_l or self._peak_lit_r
            pc = QColor(Colors.PEAK_LED) if lit else QColor(Colors.BG_INPUT)
            painter.setBrush(QBrush(pc))
            painter.setPen(QPen(QColor(Colors.BORDER), 1))
            painter.drawEllipse(QPointF(12, 12), 4, 4)
            if w > 85:
                painter.setPen(QColor(Colors.TEXT_DIM))
                painter.setFont(self.get_responsive_font(Fonts.small, 40, 12, "PEAK"))
                painter.drawText(QRectF(18, 6, 40, 12), Qt.AlignLeft, "PEAK")
                
        if self._show_clip:
            lit = self._clip_lit_l or self._clip_lit_r
            cc = QColor(Colors.CLIP_LED) if lit else QColor(Colors.BG_INPUT)
            painter.setBrush(QBrush(cc))
            painter.setPen(QPen(QColor(Colors.BORDER), 1))
            painter.drawEllipse(QPointF(w - 12, 12), 4, 4)
            if w > 85:
                painter.setPen(QColor(Colors.TEXT_DIM))
                painter.setFont(self.get_responsive_font(Fonts.small, 40, 12, "CLIP"))
                painter.drawText(QRectF(w - 58, 6, 40, 12), Qt.AlignRight, "CLIP")

    def _draw_corner_status(self, painter, w, h):
        painter.setFont(Fonts.small())
        if self._show_peak:
            lit = self._peak_lit_l or self._peak_lit_r
            painter.setBrush(QBrush(QColor(Colors.PEAK_LED) if lit else QColor(Colors.BG_INPUT)))
            painter.setPen(QPen(QColor(Colors.BORDER), 1))
            painter.drawEllipse(QPointF(12, 12), 4, 4)
            if w > 85:
                painter.setPen(QColor(Colors.TEXT_DIM))
                painter.setFont(self.get_responsive_font(Fonts.small, 40, 12, "PEAK"))
                painter.drawText(QRectF(18, 6, 40, 12), Qt.AlignLeft, "PEAK")

        if self._show_clip:
            lit = self._clip_lit_l or self._clip_lit_r
            painter.setBrush(QBrush(QColor(Colors.CLIP_LED) if lit else QColor(Colors.BG_INPUT)))
            painter.setPen(QPen(QColor(Colors.BORDER), 1))
            painter.drawEllipse(QPointF(w - 12, 12), 4, 4)
            if w > 85:
                painter.setPen(QColor(Colors.TEXT_DIM))
                painter.setFont(self.get_responsive_font(Fonts.small, 40, 12, "CLIP"))
                painter.drawText(QRectF(w - 58, 6, 40, 12), Qt.AlignRight, "CLIP")

    @staticmethod
    def _level_fraction(level, db_min=-40.0, db_max=3.0):
        return max(0.0, min(1.0, (float(level) - db_min) / (db_max - db_min)))

    def _render_tape_deck(self, painter, w, h):
        if w < 50 or h < 40:
            return

        is_stereo = self._channel == "L+R"
        gap = max(4.0, min(10.0, min(w, h) * 0.045))
        if is_stereo:
            if w >= h * 1.45:
                meter_w = (w - gap) * 0.5
                rects = [QRectF(0, 0, meter_w, h), QRectF(meter_w + gap, 0, meter_w, h)]
            else:
                meter_h = (h - gap) * 0.5
                rects = [QRectF(0, 0, w, meter_h), QRectF(0, meter_h + gap, w, meter_h)]
            self._draw_tape_unit(painter, rects[0], self._needle_l, "L", QColor("#1c1a16"))
            self._draw_tape_unit(painter, rects[1], self._needle_r, "R", QColor("#8f2b1f"))
        else:
            self._draw_tape_unit(painter, QRectF(0, 0, w, h), self._needle_l, self._channel, QColor("#1c1a16"))
        self._draw_corner_status(painter, w, h)

    def _draw_tape_unit(self, painter, rect, value, label, needle_col):
        pad = max(4.0, min(10.0, min(rect.width(), rect.height()) * 0.07))
        body = rect.adjusted(pad, pad, -pad, -pad)
        if body.width() < 28 or body.height() < 24:
            return

        grad = QLinearGradient(body.topLeft(), body.bottomRight())
        grad.setColorAt(0.0, QColor("#fff5d5"))
        grad.setColorAt(0.58, QColor("#e2d29f"))
        grad.setColorAt(1.0, QColor("#aa986c"))
        painter.setPen(QPen(QColor("#5f543d"), 1))
        painter.setBrush(QBrush(QColor("#2c281f")))
        painter.drawRoundedRect(body.adjusted(-2, -2, 2, 2), 4, 4)
        painter.setBrush(QBrush(grad))
        painter.drawRoundedRect(body, 3, 3)

        cx = body.center().x()
        cy = body.bottom() - max(5.0, body.height() * 0.12)
        radius = min(body.width() * 0.44, body.height() * 0.88)
        angle_start, angle_end = 150.0, 30.0

        def point(db, r):
            frac = self._level_fraction(db, -20.0, 3.0)
            angle = math.radians(angle_start - frac * (angle_start - angle_end))
            return QPointF(cx + r * math.cos(angle), cy - r * math.sin(angle))

        painter.setPen(QPen(QColor("#5a513c"), 1))
        painter.drawArc(QRectF(cx - radius, cy - radius, radius * 2, radius * 2),
                        int(angle_end * 16), int((angle_start - angle_end) * 16))

        for db, text in [(-20, "-20"), (-10, "-10"), (-7, ""), (-5, "-5"), (-3, ""), (0, "0"), (3, "+3")]:
            major = text != ""
            col = QColor("#a92a20") if db >= 0 else QColor("#2d2a24")
            painter.setPen(QPen(col, 1.5 if major else 0.8))
            painter.drawLine(point(db, radius * (0.82 if major else 0.88)), point(db, radius * 0.98))
            if text and radius > 46:
                pos = point(db, radius * 0.66)
                painter.setFont(self.get_responsive_font(Fonts.vu_scale, 24, 10, text))
                painter.setPen(col)
                painter.drawText(QRectF(pos.x() - 12, pos.y() - 5, 24, 10), Qt.AlignCenter, text)

        end = point(value, radius * 0.96)
        painter.setPen(QPen(needle_col, max(1.3, min(2.4, radius * 0.030))))
        painter.drawLine(QPointF(cx, cy), end)
        painter.setBrush(QBrush(QColor("#2a241a")))
        painter.setPen(QPen(QColor("#f7edcf"), 1))
        painter.drawEllipse(QPointF(cx, cy), max(3.0, radius * 0.055), max(3.0, radius * 0.055))

        painter.setFont(self.get_responsive_font(Fonts.small, 58, 12, f"{label} VU"))
        painter.setPen(QColor("#483f2b"))
        painter.drawText(QRectF(body.left() + 5, body.bottom() - 15, 58, 12), Qt.AlignLeft | Qt.AlignVCenter, f"{label} VU")

    def _render_neon_arc(self, painter, w, h):
        if w < 50 or h < 38:
            return

        is_stereo = self._channel == "L+R"
        cx = w * 0.5
        cy = h - max(12.0, h * 0.14)
        radius = min(w * 0.42, h * 0.72)
        angle_start, angle_end = 155.0, 25.0

        def draw_arc(level, radius_offset, color, width):
            frac = max(0.0, min(1.0, (level + 40.0) / 43.0))
            span = (angle_start - angle_end) * frac
            rect = QRectF(cx - radius + radius_offset, cy - radius + radius_offset,
                          (radius - radius_offset) * 2, (radius - radius_offset) * 2)
            glow = QColor(color)
            glow.setAlpha(55)
            painter.setPen(QPen(glow, width + 5, Qt.SolidLine, Qt.RoundCap))
            painter.drawArc(rect, int(angle_start * 16), int(-span * 16))
            painter.setPen(QPen(QColor(color), width, Qt.SolidLine, Qt.RoundCap))
            painter.drawArc(rect, int(angle_start * 16), int(-span * 16))

        painter.setPen(QPen(QColor(Colors.GRID), 1))
        for r_off in ([0, 9] if is_stereo else [0]):
            rect = QRectF(cx - radius + r_off, cy - radius + r_off, (radius - r_off) * 2, (radius - r_off) * 2)
            painter.drawArc(rect, int(angle_start * 16), int(-(angle_start - angle_end) * 16))

        draw_arc(self._needle_l, 0, QColor(Colors.ACCENT), max(3, min(7, int(radius * 0.045))))
        if is_stereo:
            draw_arc(self._needle_r, 9, QColor(Colors.ACCENT_PINK), max(2, min(5, int(radius * 0.035))))

        for db in [-40, -30, -20, -10, -3, 0, 3]:
            frac = (db + 40.0) / 43.0
            angle = math.radians(angle_start - frac * (angle_start - angle_end))
            inner = radius * 0.87
            outer = radius * 0.96
            col = QColor(Colors.METER_HIGH) if db >= 0 else QColor(Colors.TEXT_DIM)
            painter.setPen(QPen(col, 1))
            painter.drawLine(QPointF(cx + inner * math.cos(angle), cy - inner * math.sin(angle)),
                             QPointF(cx + outer * math.cos(angle), cy - outer * math.sin(angle)))

        label = "L/R" if is_stereo else self._channel.upper()
        painter.setFont(self.get_responsive_font(Fonts.value, 100, 18, label))
        painter.setPen(QColor(Colors.TEXT))
        painter.drawText(QRectF(cx - 50, cy - radius * 0.52, 100, 18), Qt.AlignCenter, label)
        self._draw_corner_status(painter, w, h)

    def _render_broadcast_twin(self, painter, w, h):
        if w < 50 or h < 38:
            return

        if self._channel == "L+R":
            gap = max(4.0, min(10.0, min(w, h) * 0.05))
            if w >= h * 1.25:
                meter_w = (w - gap) * 0.5
                rects = [QRectF(0, 0, meter_w, h), QRectF(meter_w + gap, 0, meter_w, h)]
            else:
                meter_h = (h - gap) * 0.5
                rects = [QRectF(0, 0, w, meter_h), QRectF(0, meter_h + gap, w, meter_h)]
            self._draw_broadcast_face(painter, rects[0], self._needle_l, "L", QColor(Colors.ACCENT))
            self._draw_broadcast_face(painter, rects[1], self._needle_r, "R", QColor(Colors.ACCENT_PINK))
        else:
            self._draw_broadcast_face(painter, QRectF(0, 0, w, h), self._needle_l, self._channel, QColor(Colors.ACCENT))
        self._draw_corner_status(painter, w, h)

    def _draw_broadcast_face(self, painter, rect, value, label, needle_col):
        pad = max(4.0, min(9.0, min(rect.width(), rect.height()) * 0.08))
        face = rect.adjusted(pad, pad, -pad, -pad)
        if face.width() < 24 or face.height() < 24:
            return

        painter.setPen(QPen(QColor(Colors.BORDER), 1))
        painter.setBrush(QBrush(QColor(Colors.BG_INPUT)))
        painter.drawRoundedRect(face, 4, 4)

        cx = face.center().x()
        cy = face.bottom() - face.height() * 0.13
        radius = min(face.width() * 0.48, face.height() * 0.95)
        angle_start, angle_end = 150.0, 30.0
        ticks = [-20, -10, -7, -5, -3, 0, 3]

        for db in ticks:
            frac = (db + 20.0) / 23.0
            angle = math.radians(angle_start - frac * (angle_start - angle_end))
            inner = radius * (0.78 if db in (-20, -10, 0, 3) else 0.86)
            outer = radius * 0.96
            col = QColor(Colors.METER_HIGH) if db >= 0 else QColor(Colors.TEXT_DIM)
            painter.setPen(QPen(col, 1.5 if db in (-20, -10, 0, 3) else 0.8))
            painter.drawLine(QPointF(cx + inner * math.cos(angle), cy - inner * math.sin(angle)),
                             QPointF(cx + outer * math.cos(angle), cy - outer * math.sin(angle)))

        frac = max(0.0, min(1.0, (value + 20.0) / 23.0))
        angle = math.radians(angle_start - frac * (angle_start - angle_end))
        end = QPointF(cx + radius * 0.92 * math.cos(angle), cy - radius * 0.92 * math.sin(angle))
        painter.setPen(QPen(needle_col, max(1.5, min(3.0, radius * 0.025))))
        painter.drawLine(QPointF(cx, cy), end)
        painter.setBrush(QBrush(QColor(Colors.BG_DARKEST)))
        painter.setPen(QPen(QColor(Colors.BORDER), 1))
        painter.drawEllipse(QPointF(cx, cy), 5, 5)

        painter.setFont(self.get_responsive_font(Fonts.small, 70, 16, label))
        painter.setPen(QColor(Colors.TEXT_DIM))
        painter.drawText(QRectF(face.left() + 6, face.top() + 4, 70, 16), Qt.AlignLeft | Qt.AlignVCenter, label)

    def _render_compaq(self, painter, w, h, vintage=False):
        if w < 36 or h < 36:
            return

        is_stereo = self._channel == "L+R"
        if not is_stereo:
            side = min(w, h)
            rect = QRectF((w - side) * 0.5, (h - side) * 0.5, side, side)
            self._draw_compaq_unit(
                painter, rect, self._needle_l, self._channel, vintage,
                self._peak_lit_l, self._clip_lit_l,
            )
            return

        gap = max(4.0, min(10.0, min(w, h) * 0.045))
        if w >= h * 1.45:
            side = min(h, (w - gap) * 0.5)
            total_w = side * 2 + gap
            x = (w - total_w) * 0.5
            y = (h - side) * 0.5
            rects = [QRectF(x, y, side, side), QRectF(x + side + gap, y, side, side)]
        else:
            side = min(w, (h - gap) * 0.5)
            total_h = side * 2 + gap
            x = (w - side) * 0.5
            y = (h - total_h) * 0.5
            rects = [QRectF(x, y, side, side), QRectF(x, y + side + gap, side, side)]

        self._draw_compaq_unit(
            painter, rects[0], self._needle_l, "L", vintage,
            self._peak_lit_l, self._clip_lit_l,
        )
        self._draw_compaq_unit(
            painter, rects[1], self._needle_r, "R", vintage,
            self._peak_lit_r, self._clip_lit_r,
        )

    def _draw_compaq_unit(self, painter, rect, value, label, vintage, peak_lit, clip_lit):
        side = min(rect.width(), rect.height())
        if side < 32:
            return

        outer = rect.adjusted(2, 2, -2, -2)
        inset = max(4.0, side * 0.07)
        face = outer.adjusted(inset, inset, -inset, -inset)

        if vintage:
            bezel = QColor("#151515")
            bezel_hi = QColor("#303030")
            face_col = QColor("#efefe7")
            face_shadow = QColor("#d8d8cf")
            tick_col = QColor("#151515")
            text_col = QColor("#202020")
            dim_col = QColor("#6d6d60")
            red_col = QColor("#b03024")
            needle_col = QColor("#101010")
            block_col = QColor("#e4e4dc")
            knob_col = QColor("#161616")
        else:
            bezel = QColor(Colors.BG_DARKEST)
            bezel_hi = QColor(Colors.BORDER)
            face_col = QColor(Colors.BG_MODULE)
            face_shadow = QColor(Colors.BG_INPUT)
            tick_col = QColor(Colors.TEXT_DIM)
            text_col = QColor(Colors.TEXT)
            dim_col = QColor(Colors.TEXT_DIM)
            red_col = QColor(Colors.METER_HIGH)
            needle_col = QColor(Colors.ACCENT if label != "R" else Colors.ACCENT_PINK)
            block_col = QColor(Colors.BG_HEADER)
            knob_col = QColor(Colors.ACCENT)

        painter.save()
        painter.setPen(QPen(bezel_hi, 1))
        painter.setBrush(QBrush(bezel))
        painter.drawRoundedRect(outer, 4, 4)

        painter.setPen(QPen(face_shadow, 1))
        painter.setBrush(QBrush(face_col))
        painter.drawRoundedRect(face, 5, 5)

        def compaq_font(size, bold=False):
            f = QFont("Arial", max(5, int(size * Fonts.TEXT_SCALE)))
            f.setBold(bold)
            return f

        block_w = face.width() * 0.34
        block_h = face.height() * 0.28
        block = QRectF(face.right() - block_w - 2, face.bottom() - block_h - 2, block_w, block_h)
        knob = QPointF(block.center().x() + block_w * 0.20, block.center().y() + block_h * 0.10)

        cx = knob.x()
        cy = knob.y()
        radius = max(10.0, min((cx - face.left()) * 0.90, (cy - face.top()) * 0.92))
        angle_start, angle_end = 170.0, 42.0

        def point_at(frac, r):
            angle = math.radians(angle_start - frac * (angle_start - angle_end))
            return QPointF(cx + r * math.cos(angle), cy - r * math.sin(angle))

        scale_end = 0.92
        tick_count = 12 if side >= 120 else 8
        for i in range(tick_count + 1):
            frac = (i / tick_count) * scale_end
            is_major = i in (0, tick_count // 2, tick_count)
            is_mid = i % max(1, tick_count // 4) == 0
            inner = radius * (0.84 if is_major else 0.88 if is_mid else 0.92)
            outer_r = radius * 0.98
            col = red_col if i == tick_count else tick_col
            if not is_major:
                col = QColor(col)
                col.setAlpha(170 if is_mid else 120)
            painter.setPen(QPen(col, 1.3 if is_major else 0.75))
            painter.drawLine(point_at(frac, inner), point_at(frac, outer_r))

        if side >= 82:
            if side < 115:
                label_items = [(scale_end, "100")]
            elif side < 145:
                label_items = [(scale_end * 0.5, "50"), (scale_end, "100")]
            else:
                label_items = [(0.00, "0"), (scale_end * 0.5, "50"), (scale_end, "100")]
            label_w = max(16, min(30, face.width() * 0.19))
            label_h = max(9, min(15, face.height() * 0.11))
            label_r = radius * (0.66 if side >= 120 else 0.58)
            for frac, text in label_items:
                pos = point_at(frac, label_r)
                painter.setFont(compaq_font(label_h * 0.75, True))
                painter.setPen(text_col)
                lx = max(face.left() + 1, min(face.right() - label_w - 1, pos.x() - label_w / 2))
                ly = max(face.top() + 1, min(face.bottom() - label_h - 1, pos.y() - label_h / 2))
                painter.drawText(QRectF(lx, ly, label_w, label_h), Qt.AlignCenter, text)

        painter.setFont(compaq_font(min(18, max(8, face.height() * 0.16)), False))
        painter.setPen(text_col)
        painter.drawText(QRectF(face.left() + 7, face.top() + 7, face.width() * 0.22, 20), Qt.AlignLeft, "A")

        painter.setFont(compaq_font(min(12, max(6, face.height() * 0.09)), True))
        painter.setPen(dim_col)
        painter.drawText(QRectF(face.left() + 6, face.bottom() - 18, face.width() * 0.28, 12), Qt.AlignLeft | Qt.AlignVCenter, label)

        if side >= 105:
            painter.setFont(compaq_font(min(7, max(5, face.height() * 0.055)), True))
            painter.setPen(dim_col)
            painter.drawText(QRectF(face.center().x() - face.width() * 0.10, face.center().y() - 4, face.width() * 0.30, 10), Qt.AlignCenter, "PYDSP")

        frac = max(0.0, min(1.0, (value + 20.0) / 23.0)) * scale_end
        end = point_at(frac, radius * 0.76)
        painter.setPen(QPen(needle_col, max(1.3, side * 0.014)))
        painter.drawLine(knob, end)

        painter.setPen(QPen(face_shadow, 1))
        painter.setBrush(QBrush(block_col))
        painter.drawRoundedRect(block, 5, 5)
        painter.setBrush(QBrush(knob_col))
        painter.setPen(QPen(bezel_hi, 1))
        painter.drawEllipse(knob, max(4, side * 0.034), max(4, side * 0.034))

        if self._show_peak or self._show_clip:
            led_r = max(2.0, min(4.0, side * 0.022))
            led_x = block.left() + max(5, block.width() * 0.18)
            led_y = block.bottom() - max(6, block.height() * 0.24)
            label_x = led_x + led_r * 2 + 3
            show_led_labels = side >= 115 and block.width() > 42
            painter.setFont(compaq_font(6, False))
            if self._show_peak:
                painter.setBrush(QColor(Colors.PEAK_LED) if peak_lit else QColor(Colors.BG_INPUT))
                painter.setPen(QPen(face_shadow, 1))
                painter.drawEllipse(QPointF(led_x, led_y), led_r, led_r)
                if show_led_labels:
                    painter.setPen(dim_col)
                    painter.drawText(QRectF(label_x, led_y - 5, 20, 10), Qt.AlignLeft | Qt.AlignVCenter, "PK")
                led_y -= led_r * 2 + 4
            if self._show_clip:
                painter.setBrush(QColor(Colors.CLIP_LED) if clip_lit else QColor(Colors.BG_INPUT))
                painter.setPen(QPen(face_shadow, 1))
                painter.drawEllipse(QPointF(led_x, led_y), led_r, led_r)
                if show_led_labels:
                    painter.setPen(dim_col)
                    painter.drawText(QRectF(label_x, led_y - 5, 24, 10), Qt.AlignLeft | Qt.AlignVCenter, "CLP")

        painter.restore()

    def _render_led_bar(self, painter, w, h):
        """LED Bar style: Segmented horizontal/vertical bar meter with peak hold."""
        is_stereo = (self._channel == "L+R")
        
        pad = 6
        bar_area_x = pad
        bar_area_w = w - pad * 2
        show_status = h > 34 and (self._show_peak or self._show_clip)
        scale_h = 12
        status_h = 12 if show_status else 0
        status_gap = 2 if show_status else 0
        bottom_reserved = scale_h + status_gap + status_h
        
        # dB range: -40 to +3
        db_min, db_max = -40.0, 3.0
        db_range = db_max - db_min
        
        # VU scale marks
        vu_ticks = [-40, -30, -20, -10, -7, -5, -3, 0, 3]
        
        # Segment count adapts to width
        n_segments = max(12, min(60, int(bar_area_w / 4)))
        seg_gap = max(1, int(bar_area_w / n_segments * 0.15))
        seg_w = (bar_area_w - (n_segments - 1) * seg_gap) / n_segments
        if seg_w < 2:
            seg_w = 2
            seg_gap = 1
        
        if is_stereo:
            # Two bars stacked
            bar_h = max(4, (h - pad * 3 - bottom_reserved) / 2)
            bar_y_l = pad
            bar_y_r = pad + bar_h + pad
            scale_y = bar_y_r + bar_h + 2
            
            self._draw_led_bar_single(painter, bar_area_x, bar_y_l, bar_area_w, bar_h,
                                       self._needle_l, self._peak_hold_l, n_segments, seg_w, seg_gap,
                                       db_min, db_max)
            self._draw_led_bar_single(painter, bar_area_x, bar_y_r, bar_area_w, bar_h,
                                       self._needle_r, self._peak_hold_r, n_segments, seg_w, seg_gap,
                                       db_min, db_max)
            
            # Channel labels
            painter.setFont(self.get_responsive_font(Fonts.small, 14, bar_h, "L"))
            painter.setPen(QColor(Colors.TEXT_DIM))
            painter.drawText(QRectF(bar_area_x - 2, bar_y_l, 14, bar_h), Qt.AlignVCenter | Qt.AlignLeft, "L")
            painter.drawText(QRectF(bar_area_x - 2, bar_y_r, 14, bar_h), Qt.AlignVCenter | Qt.AlignLeft, "R")
        else:
            # Single centered bar
            bar_h = max(6, h - pad * 2 - bottom_reserved)
            bar_y = pad
            scale_y = bar_y + bar_h + 2
            
            self._draw_led_bar_single(painter, bar_area_x, bar_y, bar_area_w, bar_h,
                                       self._needle_l, self._peak_hold_l, n_segments, seg_w, seg_gap,
                                       db_min, db_max)

        # Scale labels
        painter.setFont(Fonts.small())
        for db in vu_ticks:
            frac = (db - db_min) / db_range
            tx = bar_area_x + frac * bar_area_w
            lbl = f"{db}" if db <= 0 else f"+{db}"
            
            # Adaptive decluttering
            if bar_area_w < 200 and db not in [-40, -20, 0, 3]:
                continue
            if bar_area_w < 350 and db in [-30, -7, -5]:
                continue
            
            painter.setPen(QColor(Colors.RED) if db >= 0 else QColor(Colors.TEXT_DIM))
            painter.setFont(self.get_responsive_font(Fonts.small, 28, 12, lbl))
            if scale_y + scale_h <= h - status_h - status_gap:
                painter.drawText(QRectF(tx - 14, scale_y, 28, scale_h), Qt.AlignCenter, lbl)
        
        # PEAK / CLIP LEDs
        if show_status:
            led_y = h - pad - 6
            painter.setFont(Fonts.small())
            if self._show_peak:
                lit = self._peak_lit_l or self._peak_lit_r
                pc = QColor(Colors.PEAK_LED) if lit else QColor(Colors.BG_INPUT)
                painter.setBrush(QBrush(pc))
                painter.setPen(QPen(QColor(Colors.BORDER), 1))
                painter.drawRoundedRect(QRectF(bar_area_x, led_y, 6, 6), 1, 1)
                if w > 85:
                    painter.setPen(QColor(Colors.TEXT_DIM))
                    painter.setFont(self.get_responsive_font(Fonts.small, 30, 10, "PK"))
                    painter.drawText(QRectF(bar_area_x + 9, led_y - 2, 30, 10), Qt.AlignLeft, "PK")
                    
            if self._show_clip:
                lit = self._clip_lit_l or self._clip_lit_r
                cc = QColor(Colors.CLIP_LED) if lit else QColor(Colors.BG_INPUT)
                painter.setBrush(QBrush(cc))
                painter.setPen(QPen(QColor(Colors.BORDER), 1))
                painter.drawRoundedRect(QRectF(w - pad - 6, led_y, 6, 6), 1, 1)
                if w > 85:
                    painter.setPen(QColor(Colors.TEXT_DIM))
                    painter.setFont(self.get_responsive_font(Fonts.small, 30, 10, "CLP"))
                    painter.drawText(QRectF(w - pad - 38, led_y - 2, 30, 10), Qt.AlignRight, "CLP")

    def _draw_led_bar_single(self, painter, x, y, total_w, bar_h, level, peak_hold,
                              n_segments, seg_w, seg_gap, db_min, db_max):
        """Draw a single LED bar with gradient segments and peak hold indicator."""
        db_range = db_max - db_min
        level_frac = max(0, min(1, (level - db_min) / db_range))
        peak_frac = max(0, min(1, (peak_hold - db_min) / db_range))
        lit_segments = int(level_frac * n_segments)
        peak_seg = int(peak_frac * n_segments)
        
        # 0dB threshold segment
        zero_seg = int(((0.0 - db_min) / db_range) * n_segments)
        
        for i in range(n_segments):
            sx = x + i * (seg_w + seg_gap)
            frac = i / n_segments
            
            # Determine segment color by position
            if i >= zero_seg:
                # Red zone (≥ 0 dB)
                seg_color = QColor(Colors.METER_HIGH)
            elif frac > 0.65:
                # Yellow/warning zone
                seg_color = QColor(Colors.METER_MID)
            else:
                # Green/normal zone
                seg_color = QColor(Colors.METER_LOW)
            
            if i < lit_segments:
                # Lit segment
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(seg_color))
                painter.drawRoundedRect(QRectF(sx, y, seg_w, bar_h), 1, 1)
                
                # Subtle inner glow highlight at top
                glow = QColor(255, 255, 255, 40)
                painter.fillRect(QRectF(sx + 1, y + 1, seg_w - 2, max(1, bar_h * 0.25)), glow)
            elif i == peak_seg and peak_hold > db_min + 2:
                # Peak hold marker
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(seg_color))
                painter.drawRoundedRect(QRectF(sx, y, seg_w, bar_h), 1, 1)
            else:
                # Unlit segment — dim outline
                dim = QColor(seg_color)
                dim.setAlpha(25)
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(dim))
                painter.drawRoundedRect(QRectF(sx, y, seg_w, bar_h), 1, 1)
