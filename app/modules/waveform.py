"""
Waveform Module: Scrolling waveform display with multi-band coloring and peak history.
"""

import numpy as np
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QPainterPath
from PySide6.QtCore import Qt, QRectF

from app.base_module import BaseModule
from app.modules import register_module
from app.theme import Colors, Fonts
from app.dsp.filters import MultiBandFilter
from app.dsp import accel as dsp_accel


@register_module("waveform", "Waveform", category="Time Domain")
class WaveformModule(BaseModule):

    def __init__(self, audio_engine, parent=None):
        self._channel = "All" if audio_engine.channels > 2 else "L+R"
        self._speed = 2.0
        self._buf_len = 2048  # Pixels of history
        self._max_buf = np.zeros((self._buf_len, audio_engine.channels), dtype=np.float32)
        self._min_buf = np.zeros((self._buf_len, audio_engine.channels), dtype=np.float32)
        self._rms_buf = np.zeros((self._buf_len, audio_engine.channels), dtype=np.float32)
        self._write_pos = 0
        self._display_mode = "Dual" if audio_engine.channels >= 2 else "Overlay"
        self._orientation = "Horizontal"
        self._gain_mode = "Auto Fit"
        self._manual_gain = 1.0
        self._auto_gains = {}
        self.module_key = "waveform"
        super().__init__(audio_engine, title="Waveform", parent=parent)
        self.canvas.set_render_func(self._render)
        self.canvas.set_antialiasing(False)

    def get_settings(self):
        return {
            "channel": self._channel,
            "speed": self._speed,
            "display_mode": self._display_mode,
            "orientation": getattr(self, "_orientation", "Horizontal"),
            "gain_mode": getattr(self, "_gain_mode", "Auto Fit"),
            "manual_gain": getattr(self, "_manual_gain", 1.0),
        }

    def apply_settings(self, settings):
        self._channel = settings.get("channel", self._channel)
        self._speed = float(settings.get("speed", self._speed))
        self._display_mode = settings.get("display_mode", self._display_mode)
        self._orientation = settings.get("orientation", getattr(self, "_orientation", "Horizontal"))
        self._gain_mode = settings.get("gain_mode", getattr(self, "_gain_mode", "Auto Fit"))
        self._manual_gain = float(settings.get("manual_gain", getattr(self, "_manual_gain", 1.0)))

    def build_context_menu(self, menu):
        from PySide6.QtGui import QActionGroup
        cm = menu.addMenu("Channel")
        cg = QActionGroup(self)
        channels = ["All"] if self.audio_engine.channels > 2 else ["L+R"]
        channels += [f"Ch {i+1}" for i in range(self.audio_engine.channels)]
        if self.audio_engine.channels == 2:
            channels = ["L+R", "Left", "Right", "Mid", "Side"]
            
        for c in channels:
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
            
        sm = menu.addMenu("Speed")
        sg = QActionGroup(self)
        for s in [1, 2, 4, 8]:
            a = sm.addAction(f"{s}x")
            a.setCheckable(True)
            a.setChecked(int(self._speed) == s)
            a.triggered.connect(lambda checked, v=s: setattr(self, "_speed", float(v)))
            sg.addAction(a)
            
        dm = menu.addMenu("Display Mode")
        dm.setEnabled(self._channel in ["All", "L+R"])
        dg = QActionGroup(self)
        for d in ["Overlay", "Split", "Dual"]:
            a = dm.addAction(d)
            a.setCheckable(True)
            a.setChecked(self._display_mode == d)
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
        # Consolidate samples into speed-dependent pixel chunks
        n = len(data)
        chunk_size = max(1, int(1024 / self._speed))
        
        # Ensure buffers match engine channel count (in case it changed)
        ch_count = data.shape[1]
        if ch_count != self._max_buf.shape[1]:
            self._max_buf = np.zeros((self._buf_len, ch_count), dtype=np.float32)
            self._min_buf = np.zeros((self._buf_len, ch_count), dtype=np.float32)
            self._rms_buf = np.zeros((self._buf_len, ch_count), dtype=np.float32)
            self._write_pos = 0

        # Use accelerated chunk reduction
        max_chunks, min_chunks, rms_chunks = dsp_accel.waveform_reduce(data, chunk_size)
        n_chunks = len(max_chunks)
        
        for i in range(n_chunks):
            self._max_buf[self._write_pos] = max_chunks[i]
            self._min_buf[self._write_pos] = min_chunks[i]
            self._rms_buf[self._write_pos] = rms_chunks[i]
            self._write_pos = (self._write_pos + 1) % self._buf_len

    def _render(self, painter, w, h):
        is_vert = self._orientation == "Vertical"
        if self._orientation == "Auto":
            is_vert = h > w * 1.2

        n_disp = int(h if is_vert else w)
        if n_disp > self._buf_len: n_disp = self._buf_len
        draw_dim = h if is_vert else w
        
        start = (self._write_pos - n_disp) % self._buf_len
        
        def get_seg(buf):
            if start + n_disp <= self._buf_len:
                return buf[start:start + n_disp]
            else:
                return np.concatenate([buf[start:], buf[:(start + n_disp) % self._buf_len]])

        max_all = get_seg(self._max_buf)
        min_all = get_seg(self._min_buf)
        rms_all = get_seg(self._rms_buf)

        # Map channel selection to indices
        if self._channel == "Left" or self._channel == "Ch 1": channels = [0]
        elif self._channel == "Right" or self._channel == "Ch 2": channels = [1]
        elif self._channel.startswith("Ch "):
            try: channels = [int(self._channel.split()[1]) - 1]
            except: channels = [0]
        elif self._channel == "Mid": 
            maxs = (max_all[:, 0] + max_all[:, 1]) * 0.5
            mins = (min_all[:, 0] + min_all[:, 1]) * 0.5
            rmss = (rms_all[:, 0] + rms_all[:, 1]) * 0.5
            self._draw_wave(painter, maxs, mins, rmss, Colors.ACCENT, (w/2 if is_vert else h/2), (w if is_vert else h), "both", is_vert, draw_dim, trace_key="mid")
            return
        elif self._channel == "Side":
            maxs = (max_all[:, 0] - max_all[:, 1]) * 0.5
            mins = (min_all[:, 0] - min_all[:, 1]) * 0.5
            rmss = np.abs(rms_all[:, 0] - rms_all[:, 1]) * 0.5
            self._draw_wave(painter, maxs, mins, rmss, Colors.ACCENT_PURPLE, (w/2 if is_vert else h/2), (w if is_vert else h), "both", is_vert, draw_dim, trace_key="side")
            return
        else: # L+R or All
            channels = list(range(self.audio_engine.channels))

        colors = [Colors.ACCENT, Colors.ACCENT_PINK, Colors.ACCENT_PURPLE, Colors.BAND_LOW, Colors.BAND_MID, Colors.BAND_HIGH, Colors.METER_MID, Colors.METER_HIGH]
        
        if self._display_mode == "Dual" and len(channels) > 1:
            n_ch = len(channels)
            strip_dim = (w if is_vert else h) / n_ch
            for i, idx in enumerate(channels):
                center = (i + 0.5) * strip_dim
                if i > 0:
                    painter.setPen(QPen(QColor(Colors.GRID), 1))
                    if is_vert: painter.drawLine(int(i * strip_dim), 0, int(i * strip_dim), h)
                    else: painter.drawLine(0, int(i * strip_dim), w, int(i * strip_dim))
                
                if idx < len(max_all[0]):
                    self._draw_wave(painter, max_all[:, idx], min_all[:, idx], rms_all[:, idx], colors[idx % len(colors)], center, strip_dim, "both", is_vert, draw_dim, trace_key=idx)
        elif self._display_mode == "Split" and len(channels) > 1:
            mid_dim = (w if is_vert else h) / 2
            painter.setPen(QPen(QColor(Colors.GRID), 1))
            if is_vert: painter.drawLine(int(mid_dim), 0, int(mid_dim), h)
            else: painter.drawLine(0, int(mid_dim), w, int(mid_dim))
            c0, c1 = channels[0], channels[1]
            if c0 < len(max_all[0]):
                self._draw_wave(painter, max_all[:, c0], min_all[:, c0], rms_all[:, c0], colors[c0 % len(colors)], mid_dim, (w if is_vert else h), "top", is_vert, draw_dim, trace_key=c0)
            if c1 < len(max_all[0]):
                self._draw_wave(painter, max_all[:, c1], min_all[:, c1], rms_all[:, c1], colors[c1 % len(colors)], mid_dim, (w if is_vert else h), "bottom", is_vert, draw_dim, trace_key=c1)
        else:
            mid_dim = (w if is_vert else h) / 2
            painter.setPen(QPen(QColor(Colors.GRID), 1))
            if is_vert: painter.drawLine(int(mid_dim), 0, int(mid_dim), h)
            else: painter.drawLine(0, int(mid_dim), w, int(mid_dim))
            for idx in channels:
                if idx < len(max_all[0]):
                    self._draw_wave(painter, max_all[:, idx], min_all[:, idx], rms_all[:, idx], colors[idx % len(colors)], mid_dim, (w if is_vert else h), "both", is_vert, draw_dim, trace_key=idx)

    def _get_trace_gain(self, maxs, mins, trace_key=0):
        mode = getattr(self, "_gain_mode", "Auto Fit")
        if mode == "Fixed":
            return max(0.05, float(getattr(self, "_manual_gain", 1.0)))

        if len(maxs) < 1 or len(mins) < 1:
            return 1.0

        key = "shared" if mode == "Auto Shared" else trace_key
        peaks = np.maximum(np.abs(maxs), np.abs(mins))
        if len(peaks) > 64:
            peak = float(np.percentile(peaks, 99.5))
        else:
            peak = float(np.max(peaks))

        if peak < 0.0005:
            target = 1.0
        else:
            target = 0.88 / peak
            target = max(0.25, min(32.0, target))

        previous = self._auto_gains.get(key, target)
        alpha = 0.45 if target < previous else 0.14
        gain = previous + (target - previous) * alpha
        self._auto_gains[key] = gain
        return gain

    def _draw_wave(self, painter, maxs, mins, rmss, base_color, center, dim, side="both", vertical=False, draw_dim=None, trace_key=0):
        from PySide6.QtCore import QLineF
        h_factor = dim * 0.45
        draw_dim = draw_dim or len(maxs)
        max_points = 900
        if len(maxs) > max_points:
            step = int(np.ceil(len(maxs) / max_points))
            idx = np.arange(0, len(maxs), step)
            maxs = np.maximum.reduceat(maxs, idx)
            mins = np.minimum.reduceat(mins, idx)
            rmss = np.maximum.reduceat(rmss, idx)
        coord_scale = 0.0 if len(maxs) <= 1 else (draw_dim - 1) / (len(maxs) - 1)
        gain = self._get_trace_gain(maxs, mins, trace_key)
        maxs = np.clip(maxs * gain, -1.0, 1.0)
        mins = np.clip(mins * gain, -1.0, 1.0)
        rmss = np.clip(rmss * gain, 0.0, 1.0)
        
        base_lines = []
        yellow_lines = []
        red_lines = []
        peak_lines = []
        
        for t in range(len(maxs)):
            rms_val = rmss[t] * 2.0
            h_rms = rmss[t] * h_factor
            
            if side == "both":
                vt, vb = center - h_rms, center + h_rms
                pt, pb = center - maxs[t] * h_factor, center - mins[t] * h_factor
            elif side == "top": # or "left" in vertical
                vt, vb = center - h_rms - 1.0, center - 1.0
                pt, pb = center - maxs[t] * h_factor - 1.0, center - 1.0
            else: # bottom or "right" in vertical
                vt, vb = center + 1.0, center + h_rms + 1.0
                pt, pb = center + 1.0, center - mins[t] * h_factor + 1.0
            
            pos = t * coord_scale
            if vertical:
                y = pos
                line = QLineF(vt, y, vb, y)
                peak_line = QLineF(pt, y, pb, y)
            else:
                x = pos
                line = QLineF(x, vt, x, vb)
                peak_line = QLineF(x, pt, x, pb)

            if rms_val > 0.7: red_lines.append(line)
            elif rms_val > 0.3: yellow_lines.append(line)
            else: base_lines.append(line)
            peak_lines.append(peak_line)

        # 1. Draw Peaks
        pc = QColor(base_color); pc.setAlpha(35)
        painter.setPen(QPen(pc, 1))
        painter.drawLines(peak_lines)
        
        # 2. Draw RMS Cores
        if base_lines:
            painter.setPen(QPen(QColor(Colors.METER_LOW), 1))
            painter.drawLines(base_lines)
        if yellow_lines:
            painter.setPen(QPen(QColor(Colors.METER_MID), 1))
            painter.drawLines(yellow_lines)
        if red_lines:
            painter.setPen(QPen(QColor(Colors.METER_HIGH), 1))
            painter.drawLines(red_lines)
