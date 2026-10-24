"""
Spectrum Analyzer Module: FFT-based frequency display with accumulation buffer.
"""

import numpy as np
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QPainterPath
from PySide6.QtCore import Qt, QRectF, QPointF

from app.base_module import BaseModule
from app.modules import register_module
from app.theme import Colors, Fonts
from app.dsp.fft import (
    compute_fft, fft_frequencies, map_frequencies_to_pixels,
    detect_peak_frequency, hz_to_note_name, apply_tilt,
)


@register_module("spectrum", "Spectrum Analyzer")
class SpectrumModule(BaseModule):

    def __init__(self, audio_engine, parent=None):
        self._fft_size = 4096
        self._scale = "logarithmic"
        self._mode = "FFT"
        self._orientation = "Horizontal"
        self._channel = "L+R"
        self._smoothing = 0.85
        self._show_note = True
        self._show_floating_note = False
        # Accumulation buffers
        self._acc_buf_l = np.zeros(max(16384, self._fft_size * 2), dtype=np.float32)
        self._acc_buf_r = np.zeros(max(16384, self._fft_size * 2), dtype=np.float32)
        self._smoothed_l = np.full(self._fft_size // 2 + 1, -120.0, dtype=np.float64)
        self._smoothed_r = np.full(self._fft_size // 2 + 1, -120.0, dtype=np.float64)
        self._peak_freq = 0.0
        self._peak_db = -120.0
        self._smooth_peak_freq = 0.0
        self._smooth_peak_db = -120.0
        self._peak_history = []
        self._speed = 1.0
        self._tilt = 4.5  # dB/octave tilt for balance
        self._show_scale = True
        self._f_max_mode = "20 kHz"
        self._grid_pixmap = None
        self.module_key = "spectrum"
        super().__init__(audio_engine, title="Spectrum", parent=parent)
        self.canvas.set_render_func(self._render)

    def on_theme_changed(self):
        self._grid_pixmap = None

    def _get_f_max(self):
        sr = getattr(self.audio_engine, "sample_rate", 44100.0)
        nyquist = sr * 0.5
        mode = getattr(self, "_f_max_mode", "20 kHz")
        if mode == "16 kHz":
            return min(16000.0, nyquist)
        elif mode == "18 kHz":
            return min(18000.0, nyquist)
        elif mode == "20 kHz":
            return min(20000.0, nyquist)
        elif mode in ("Nyquist (Fs/2)", "Nyquist"):
            return nyquist
        elif mode == "22 kHz":
            return min(22050.0, nyquist)
        return min(20000.0, nyquist)

    def _set_tilt(self, v):
        self._tilt = float(v)
        self._grid_pixmap = None

    def _set_scale(self, s):
        self._scale = s
        self._grid_pixmap = None

    def _set_f_max_mode(self, mode):
        self._f_max_mode = mode
        self._grid_pixmap = None

    def _set_show_scale(self, show):
        self._show_scale = bool(show)
        self._grid_pixmap = None

    def _set_orientation(self, o):
        self._orientation = o
        self._grid_pixmap = None

    def get_settings(self):
        return {
            "fft_size": self._fft_size,
            "scale": self._scale,
            "orientation": getattr(self, "_orientation", "Horizontal"),
            "mode": self._mode,
            "channel": self._channel,
            "smoothing": self._smoothing,
            "show_note": self._show_note,
            "show_floating_note": self._show_floating_note,
            "speed": self._speed,
            "tilt": self._tilt,
            "show_scale": self._show_scale,
            "f_max_mode": self._f_max_mode,
        }

    def apply_settings(self, settings):
        self._set_fft_size(settings.get("fft_size", self._fft_size))
        self._scale = settings.get("scale", self._scale)
        self._orientation = settings.get("orientation", getattr(self, "_orientation", "Horizontal"))
        self._mode = settings.get("mode", self._mode)
        self._channel = settings.get("channel", self._channel)
        self._smoothing = float(settings.get("smoothing", self._smoothing))
        self._show_note = settings.get("show_note", self._show_note)
        self._show_floating_note = settings.get("show_floating_note", self._show_floating_note)
        self._speed = float(settings.get("speed", self._speed))
        self._tilt = float(settings.get("tilt", self._tilt))
        self._show_scale = bool(settings.get("show_scale", self._show_scale))
        self._f_max_mode = settings.get("f_max_mode", self._f_max_mode)
        self._grid_pixmap = None

    def build_context_menu(self, menu):
        from PySide6.QtGui import QActionGroup
        
        # Channel & Orientation
        cm = menu.addMenu("Channel")
        cg = QActionGroup(self)
        for c in ["L+R", "Left", "Right", "Mid", "Side"]:
            a = cm.addAction(c)
            a.setCheckable(True)
            a.setChecked(c == self._channel)
            a.triggered.connect(lambda checked, t=c: setattr(self, "_channel", t))
            cg.addAction(a)

        om = menu.addMenu("Orientation")
        og = QActionGroup(self)
        for o in ["Auto", "Horizontal", "Vertical"]:
            a = om.addAction(o)
            a.setCheckable(True)
            a.setChecked(o == getattr(self, "_orientation", "Horizontal"))
            a.triggered.connect(lambda checked, t=o: self._set_orientation(t))
            og.addAction(a)

        mm = menu.addMenu("Mode")
        mg = QActionGroup(self)
        for m in ["FFT", "Color Bars", "Both"]:
            a = mm.addAction(m)
            a.setCheckable(True)
            a.setChecked(m == self._mode)
            a.triggered.connect(lambda checked, t=m: setattr(self, "_mode", t))
            mg.addAction(a)

        # Display & Notes
        dnm = menu.addMenu("Display & Notes")
        a_note = dnm.addAction("dB/Hz/Note Info")
        a_note.setCheckable(True)
        a_note.setChecked(self._show_note)
        a_note.triggered.connect(lambda checked: setattr(self, "_show_note", checked))

        a_fp = dnm.addAction("Floating Note Peak")
        a_fp.setCheckable(True)
        a_fp.setChecked(self._show_floating_note)
        a_fp.setEnabled(self._show_note)
        a_fp.triggered.connect(lambda checked: setattr(self, "_show_floating_note", checked))

        a_scale = dnm.addAction("Side dB Scale")
        a_scale.setCheckable(True)
        a_scale.setChecked(self._show_scale)
        a_scale.triggered.connect(lambda checked: self._set_show_scale(checked))

        # FFT & Response
        frm = menu.addMenu("FFT & Response")
        fm = frm.addMenu("FFT Size")
        fg = QActionGroup(self)
        for f in [1024, 2048, 4096, 8192, 16384, 32768]:
            a = fm.addAction(str(f))
            a.setCheckable(True)
            a.setChecked(f == self._fft_size)
            a.triggered.connect(lambda checked, t=f: self._set_fft_size(int(t)))
            fg.addAction(a)

        scm = frm.addMenu("Scale")
        scg = QActionGroup(self)
        for s in ["Mel", "Logarithmic", "Linear"]:
            a = scm.addAction(s)
            a.setCheckable(True)
            a.setChecked(s.lower() == self._scale)
            a.triggered.connect(lambda checked, t=s: self._set_scale(t.lower()))
            scg.addAction(a)

        hcm = frm.addMenu("High Frequency Cut")
        hcg = QActionGroup(self)
        for hc in ["16 kHz", "18 kHz", "20 kHz", "22 kHz", "Nyquist (Fs/2)"]:
            a = hcm.addAction(hc)
            a.setCheckable(True)
            a.setChecked(hc == self._f_max_mode)
            a.triggered.connect(lambda checked, t=hc: self._set_f_max_mode(t))
            hcg.addAction(a)

        sm_speed = frm.addMenu("Speed")
        sg_speed = QActionGroup(self)
        for s in [1, 2, 4]:
            a = sm_speed.addAction(f"{s}x")
            a.setCheckable(True)
            a.setChecked(int(self._speed) == s)
            a.triggered.connect(lambda checked, v=s: setattr(self, "_speed", float(v)))
            sg_speed.addAction(a)

        sm = frm.addMenu("Smoothing")
        sg = QActionGroup(self)
        for sm_val in [0, 50, 75, 85, 95, 98, 99]:
            a = sm.addAction(f"{sm_val}%")
            a.setCheckable(True)
            a.setChecked(abs(sm_val/100.0 - self._smoothing) < 0.01)
            a.triggered.connect(lambda checked, v=sm_val: setattr(self, "_smoothing", v / 100.0))
            sg.addAction(a)

        tm = frm.addMenu("Slope (Tilt)")
        tg = QActionGroup(self)
        for t_val in [-6.0, -4.5, -3.0, -1.5, 0.0, 1.5, 3.0, 4.5, 6.0]:
            a = tm.addAction(f"{t_val:g} dB/oct")
            a.setCheckable(True)
            a.setChecked(abs(t_val - self._tilt) < 0.1)
            a.triggered.connect(lambda checked, v=t_val: self._set_tilt(v))
            tg.addAction(a)

    def _set_fft_size(self, size):
        self._fft_size = size
        n = size // 2 + 1
        self._smoothed_l = np.full(n, -120.0, dtype=np.float64)
        self._smoothed_r = np.full(n, -120.0, dtype=np.float64)
        min_buf = max(16384, size * 2)
        if len(self._acc_buf_l) < min_buf:
            old_l, old_r = self._acc_buf_l, self._acc_buf_r
            self._acc_buf_l = np.zeros(min_buf, dtype=np.float32)
            self._acc_buf_r = np.zeros(min_buf, dtype=np.float32)
            copy_n = min(len(old_l), min_buf)
            self._acc_buf_l[-copy_n:] = old_l[-copy_n:]
            self._acc_buf_r[-copy_n:] = old_r[-copy_n:]
        self._grid_pixmap = None

    def _resample_channel_to_pixels(self, px_x, mag, dw):
        pixel_count = max(2, int(dw))
        screen_x = np.arange(pixel_count, dtype=np.float32)
        base = np.interp(screen_x, px_x, mag, left=mag[0], right=mag[-1])
        
        px_indices = np.clip(np.round(px_x).astype(np.int32), 0, pixel_count - 1)
        peak = np.full(pixel_count, -120.0, dtype=np.float32)
        np.maximum.at(peak, px_indices, mag.astype(np.float32))
        
        has_bins = peak > -119.0
        out = np.where(has_bins, np.maximum(base, peak), base)
        
        # Smooth high-frequency bin transitions so anti-aliasing / codec cliffs don't droop abruptly
        kernel = np.array([0.25, 0.50, 0.25], dtype=np.float32)
        smooth = np.convolve(out, kernel, mode='same')
        smooth[0], smooth[-1] = out[0], out[-1]
        out = np.maximum(smooth, out)
        return out

    def _resample_spectrum_to_pixels(self, px_x, mag_max, mag_min, dw):
        s_max = self._resample_channel_to_pixels(px_x, mag_max, dw)
        s_min = self._resample_channel_to_pixels(px_x, mag_min, dw)
        screen_x = np.arange(max(2, int(dw)), dtype=np.float32)
        return screen_x, s_max, s_min

    def on_audio_data(self, data: np.ndarray):
        l = data[:, 0]
        r = data[:, 1] if data.shape[1] > 1 else l
        
        is_stereo = self._channel == "L+R"
        
        if is_stereo:
            sig_l, sig_r = l, r
        else:
            sig_l = {"Left": l, "Right": r, "Mid": (l+r)*0.5, "Side": (l-r)*0.5}.get(self._channel, l)
            sig_r = sig_l

        n = len(sig_l)
        buf_len = len(self._acc_buf_l)
        if n >= buf_len:
            self._acc_buf_l[:] = sig_l[-buf_len:]
            self._acc_buf_r[:] = sig_r[-buf_len:]
        else:
            self._acc_buf_l = np.roll(self._acc_buf_l, -n)
            self._acc_buf_l[-n:] = sig_l
            self._acc_buf_r = np.roll(self._acc_buf_r, -n)
            self._acc_buf_r[-n:] = sig_r

        n_steps = int(self._speed)
        step_size = n // n_steps if n_steps > 1 else n
        
        freqs_temp = fft_frequencies(self._fft_size, self.audio_engine.sample_rate)
        a = 1.0 - self._smoothing
        
        for s in range(n_steps):
            offset = (n_steps - 1 - s) * step_size
            start_idx = len(self._acc_buf_l) - self._fft_size - offset
            end_idx = len(self._acc_buf_l) - offset
            if start_idx < 0: start_idx = 0
            if end_idx <= start_idx: continue
                
            seg_l = self._acc_buf_l[start_idx:end_idx]
            if len(seg_l) < self._fft_size:
                seg_l = np.pad(seg_l, (self._fft_size - len(seg_l), 0))
            
            mag_l = compute_fft(seg_l, self._fft_size)
            mag_l = apply_tilt(mag_l, freqs_temp, self._tilt)
            
            nb = min(len(mag_l), len(self._smoothed_l))
            self._smoothed_l[:nb] = self._smoothed_l[:nb] * self._smoothing + mag_l[:nb] * a
            
            if is_stereo:
                seg_r = self._acc_buf_r[start_idx:end_idx]
                if len(seg_r) < self._fft_size:
                    seg_r = np.pad(seg_r, (self._fft_size - len(seg_r), 0))
                mag_r = compute_fft(seg_r, self._fft_size)
                mag_r = apply_tilt(mag_r, freqs_temp, self._tilt)
                self._smoothed_r[:nb] = self._smoothed_r[:nb] * self._smoothing + mag_r[:nb] * a
            else:
                self._smoothed_r[:nb] = self._smoothed_l[:nb]

        freqs = fft_frequencies(self._fft_size, self.audio_engine.sample_rate)
        # Use the max of L and R for peak detection
        mag_max = np.maximum(self._smoothed_l[:len(freqs)], self._smoothed_r[:len(freqs)])
        self._peak_freq, self._peak_db = detect_peak_frequency(mag_max, freqs)
            
        # Smoothing for peak detection
        if self._peak_db > -90:
            self._peak_history.append(self._peak_freq)
            if len(self._peak_history) > 30:
                self._peak_history.pop(0)
                
            target_freq = float(np.median(self._peak_history))
            alpha = 0.05
            self._smooth_peak_freq += (target_freq - self._smooth_peak_freq) * alpha
            self._smooth_peak_db += (self._peak_db - self._smooth_peak_db) * 0.15
        else:
            self._peak_history.clear()
            self._smooth_peak_db = -120.0

    def _recast_grid(self, w: int, h: int):
        if w <= 0 or h <= 0:
            return
        from PySide6.QtGui import QPixmap, QPainter, QPen, QColor, QPainterPath
        from PySide6.QtCore import Qt, QRectF
        
        pixmap = QPixmap(w, h)
        pixmap.fill(Qt.transparent)
        p = QPainter(pixmap)
        if not p.isActive():
            return
        p.setRenderHint(QPainter.Antialiasing, True)
        
        is_vertical = getattr(self, "_orientation", "Horizontal") == "Vertical"
        if getattr(self, "_orientation", "Horizontal") == "Auto":
            is_vertical = h > w * 1.1

        db_min, db_max = -90.0, 0.0
        mb = 16
        if is_vertical:
            dh = w - mb
            dw = h
        else:
            dh = h - mb
            dw = w
            
        f_min = 20.0
        f_max = self._get_f_max()
        scale = getattr(self, "_scale", "logarithmic")
        tilt = float(getattr(self, "_tilt", 4.5))
        show_scale = getattr(self, "_show_scale", True)

        p.setFont(Fonts.small())

        # 1. Frequency dotted grid lines
        grid_freqs = [50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000]
        for gf in grid_freqs:
            if gf > f_max:
                continue
            px = map_frequencies_to_pixels(np.array([gf], dtype=np.float64), dw, scale, f_min=f_min, f_max=f_max)[0]
            if 0 < px <= dw:
                p.setPen(QPen(QColor(Colors.GRID), 1, Qt.DotLine))
                if is_vertical:
                    py = min(h - 1, max(1, h - px))
                    p.drawLine(0, int(py), int(dh), int(py))
                    if h > 100:
                        lb = f"{gf}" if gf < 1000 else f"{gf//1000}k"
                        p.setFont(self.get_responsive_font(Fonts.small, mb, 14, lb))
                        self.draw_text_badge(p, QRectF(dh + 2, min(py - 7, h - 16), mb - 4, 14), Qt.AlignLeft | Qt.AlignVCenter, lb, QColor(Colors.TEXT_DIM))
                else:
                    draw_x = min(int(px), int(dw - 1))
                    p.drawLine(draw_x, 0, draw_x, int(dh))
                    if w > 100:
                        lb = f"{gf}" if gf < 1000 else f"{gf//1000}k"
                        from PySide6.QtGui import QFontMetrics
                        fm = QFontMetrics(Fonts.small())
                        tw = fm.horizontalAdvance(lb) + 12
                        p.setFont(self.get_responsive_font(Fonts.small, tw, 14, lb))
                        badge_x = max(2, min(px - tw / 2, dw - tw - 2))
                        self.draw_text_badge(p, QRectF(badge_x, dh + 2, tw, 14), Qt.AlignCenter, lb, QColor(Colors.TEXT_DIM))

        # 2. Amplitude grid lines (curved upwards with tilt)
        n_pts = max(10, int(dw // 4))
        grid_x = np.linspace(0, dw - 1, n_pts)
        
        if scale == "linear":
            sample_freqs = f_min + (grid_x / max(1.0, dw - 1.0)) * (f_max - f_min)
        elif scale == "mel":
            mel_min = 2595.0 * np.log10(1.0 + f_min / 700.0)
            mel_max = 2595.0 * np.log10(1.0 + f_max / 700.0)
            mel_vals = mel_min + (grid_x / max(1.0, dw - 1.0)) * (mel_max - mel_min)
            sample_freqs = 700.0 * (10.0 ** (mel_vals / 2595.0) - 1.0)
        else: # logarithmic
            log_min = np.log10(max(f_min, 1.0))
            log_max = np.log10(f_max)
            log_vals = log_min + (grid_x / max(1.0, dw - 1.0)) * (log_max - log_min)
            sample_freqs = 10.0 ** log_vals

        tilt_offsets = np.log2(np.clip(sample_freqs, 20.0, None) / 1000.0) * tilt

        db_lines = list(range(-80, 1, 10))
        for db in db_lines:
            levels = db + tilt_offsets
            fracs = (levels - db_min) / (db_max - db_min)
            
            p.setPen(QPen(QColor(Colors.GRID), 1, Qt.DotLine))
            path = QPainterPath()
            started = False
            
            for i in range(n_pts):
                frac = fracs[i]
                if is_vertical:
                    x_pos = dh * frac
                    y_pos = h - grid_x[i]
                    in_bounds = (0 <= x_pos <= dh) and (0 <= y_pos <= h)
                    pt = QPointF(x_pos, y_pos)
                else:
                    x_pos = grid_x[i]
                    y_pos = dh * (1.0 - frac)
                    in_bounds = (0 <= x_pos <= dw) and (0 <= y_pos <= dh)
                    pt = QPointF(x_pos, y_pos)
                
                if in_bounds:
                    if not started:
                        path.moveTo(pt)
                        started = True
                    else:
                        path.lineTo(pt)
                else:
                    if started:
                        p.drawPath(path)
                        path = QPainterPath()
                        started = False
                        
            if started:
                p.drawPath(path)

        # 3. Numeric amplitude scale markings on the side
        if show_scale:
            p.setFont(Fonts.small())
            scale_color = QColor(Colors.TEXT_DIM)
            scale_color.setAlpha(170)
            p.setPen(scale_color)
            
            major_dbs = [-18, -36, -54, -72] if (dh < 140) else [-10, -20, -30, -40, -50, -60, -70, -80]
            
            for db in major_dbs:
                frac = (db - db_min) / (db_max - db_min)
                if is_vertical:
                    x_pos = dh * frac
                    if 15 < x_pos < dh - 15:
                        txt = f"{db}"
                        p.drawText(QRectF(x_pos - 16, h - mb + 2, 32, 14), Qt.AlignCenter, txt)
                else:
                    y_pos = dh * (1.0 - frac)
                    if 10 < y_pos < dh - 10:
                        txt = f"{db}"
                        p.drawText(QRectF(4, y_pos - 7, 28, 14), Qt.AlignLeft | Qt.AlignVCenter, txt)

        p.end()
        self._grid_pixmap = pixmap

    def _render(self, painter, w, h):
        if w <= 0 or h <= 0:
            return
        from PySide6.QtCore import QSize
        if self._grid_pixmap is None or self._grid_pixmap.size() != QSize(w, h):
            self._recast_grid(w, h)
            
        if self._grid_pixmap:
            painter.drawPixmap(0, 0, self._grid_pixmap)

        is_vertical = getattr(self, "_orientation", "Horizontal") == "Vertical"
        if getattr(self, "_orientation", "Horizontal") == "Auto":
            is_vertical = h > w * 1.1

        db_min, db_max = -90.0, 0.0
        mb = 16
        if is_vertical:
            dh = w - mb
            dw = h
        else:
            dh = h - mb
            dw = w

        if dw <= 0 or dh <= 0:
            return

        sr = getattr(self.audio_engine, "sample_rate", 44100.0)
        f_max = self._get_f_max()
        cache_key = (self._fft_size, int(sr), int(dw), self._scale, float(f_max))
        if getattr(self, "_freq_cache_key", None) != cache_key:
            freqs = fft_frequencies(self._fft_size, sr)
            mask = (freqs >= 20.0) & (freqs <= f_max)
            px_x = map_frequencies_to_pixels(freqs[mask], dw, self._scale, f_min=20.0, f_max=f_max)
            self._freq_cache_key = cache_key
            self._cached_freqs = freqs
            self._cached_mask = mask
            self._cached_px_x = px_x
        else:
            freqs = self._cached_freqs
            mask = self._cached_mask
            px_x = self._cached_px_x

        mag_l_filtered = self._smoothed_l[mask]
        mag_r_filtered = self._smoothed_r[mask]
        nb = len(px_x)
        if nb < 2:
            return

        peak_db = max(float(np.max(mag_l_filtered)), float(np.max(mag_r_filtered)))
        if peak_db <= -89.0:
            # Idle / silence: below the -90 dB baseline.
            # Skip resampling, cubic spline generation, and fill paths completely!
            return

        screen_x = np.arange(int(dw), dtype=np.float32)
        mag_l_screen = self._resample_channel_to_pixels(px_x, mag_l_filtered, dw)
        if self._channel == "L+R":
            mag_r_screen = self._resample_channel_to_pixels(px_x, mag_r_filtered, dw)
            mag_max_screen = np.maximum(mag_l_screen, mag_r_screen)
            mag_min_screen = np.minimum(mag_l_screen, mag_r_screen)
        else:
            mag_max_screen = mag_l_screen
            mag_min_screen = mag_l_screen

        if self._mode in ("Color Bars", "Both"):
            n_bars = 64
            bw = max(2, dw / n_bars - 1)
            bar_vals = np.zeros(n_bars)
            for b in range(n_bars):
                xs, xe = b / n_bars * len(screen_x), (b + 1) / n_bars * len(screen_x)
                bar_mask = (screen_x >= xs) & (screen_x < xe)
                if np.any(bar_mask):
                    bar_vals[b] = np.max(mag_max_screen[bar_mask])
                else:
                    idx = min(len(mag_max_screen) - 1, max(0, int(round(xs))))
                    bar_vals[b] = mag_max_screen[idx]

            for b in range(n_bars):
                xs = b / n_bars * dw
                ff = max(0, min(1, (bar_vals[b] - db_min) / (db_max - db_min)))
                bh = ff * dh
                hf = b / n_bars
                col = QColor(Colors.BAND_LOW if hf < 0.33 else
                             Colors.BAND_MID if hf < 0.66 else Colors.BAND_HIGH)
                col.setAlpha(180)
                if is_vertical:
                    painter.fillRect(QRectF(0, h - xs - bw, bh, bw), QBrush(col))
                else:
                    painter.fillRect(QRectF(xs + 1, dh - bh, bw, bh), QBrush(col))

        if self._mode in ("FFT", "Both"):
            target_pts = min(350, max(60, int(dw) // 3))
            step = max(1, len(screen_x) // target_pts)
            pts_max, pts_min = [], []
            for i in range(0, len(screen_x), step):
                frac_max = max(0, min(1, (mag_max_screen[i] - db_min) / (db_max - db_min)))
                frac_min = max(0, min(1, (mag_min_screen[i] - db_min) / (db_max - db_min)))
                if is_vertical:
                    pts_max.append(QPointF(dh * frac_max, h - screen_x[i]))
                    pts_min.append(QPointF(dh * frac_min, h - screen_x[i]))
                else:
                    pts_max.append(QPointF(screen_x[i], dh * (1.0 - frac_max)))
                    pts_min.append(QPointF(screen_x[i], dh * (1.0 - frac_min)))
            
            # Ensure the endpoint reaches the exact right bezel edge
            if len(screen_x) > 0 and (len(screen_x) - 1) % step != 0:
                last_i = len(screen_x) - 1
                frac_max = max(0, min(1, (mag_max_screen[last_i] - db_min) / (db_max - db_min)))
                frac_min = max(0, min(1, (mag_min_screen[last_i] - db_min) / (db_max - db_min)))
                if is_vertical:
                    pts_max.append(QPointF(dh * frac_max, h - screen_x[last_i]))
                    pts_min.append(QPointF(dh * frac_min, h - screen_x[last_i]))
                else:
                    pts_max.append(QPointF(screen_x[last_i], dh * (1.0 - frac_max)))
                    pts_min.append(QPointF(screen_x[last_i], dh * (1.0 - frac_min)))
            
            def create_spline(points):
                path = QPainterPath()
                if not points: return path
                path.moveTo(points[0])
                if len(points) >= 4:
                    path.lineTo(points[1])
                    for i in range(1, len(points) - 2):
                        p0, p1, p2, p3 = points[i - 1], points[i], points[i + 1], points[i + 2]
                        cp1x = p1.x() + (p2.x() - p0.x()) / 6.0
                        cp1y = p1.y() + (p2.y() - p0.y()) / 6.0
                        cp2x = p2.x() - (p3.x() - p1.x()) / 6.0
                        cp2y = p2.y() - (p3.y() - p1.y()) / 6.0
                        path.cubicTo(cp1x, cp1y, cp2x, cp2y, p2.x(), p2.y())
                    path.lineTo(points[-1])
                else:
                    for p in points[1:]: path.lineTo(p)
                return path

            if len(pts_max) >= 2:
                path_max = create_spline(pts_max)
                path_min = create_spline(pts_min)
                
                if self._channel == "L+R":
                    # Ribbon fill for Stereo Width
                    ribbon = QPainterPath(path_max)
                    ribbon.lineTo(pts_min[-1])
                    for p in reversed(pts_min[:-1]): ribbon.lineTo(p)
                    ribbon.closeSubpath()
                    
                    # 1. Base fill below the minimum curve (to maintain visual weight)
                    bg_fill = QPainterPath(path_min)
                    if is_vertical:
                        bg_fill.lineTo(0, pts_min[-1].y()); bg_fill.lineTo(0, pts_min[0].y()); bg_fill.closeSubpath()
                    else:
                        bg_fill.lineTo(pts_min[-1].x(), dh); bg_fill.lineTo(pts_min[0].x(), dh); bg_fill.closeSubpath()
                    bc = QColor(Colors.ACCENT); bc.setAlpha(20)
                    painter.fillPath(bg_fill, QBrush(bc))

                    # 2. Vibrant ribbon fill for the stereo difference
                    fc = QColor(Colors.ACCENT_PINK); fc.setAlpha(65)
                    painter.fillPath(ribbon, QBrush(fc))
                    
                    # 3. Glow pen for the max curve (matching mono mode's intensity)
                    gc_glow = QColor(Colors.ACCENT); gc_glow.setAlpha(40)
                    painter.setPen(QPen(gc_glow, 3.5))
                    painter.drawPath(path_max)
                    painter.setPen(QPen(QColor(Colors.ACCENT), 1.5))
                    painter.drawPath(path_max)
                else:
                    # Standard solid mono fill
                    fp = QPainterPath(path_max)
                    if is_vertical:
                        fp.lineTo(0, pts_max[-1].y()); fp.lineTo(0, pts_max[0].y()); fp.closeSubpath()
                    else:
                        fp.lineTo(pts_max[-1].x(), dh); fp.lineTo(pts_max[0].x(), dh); fp.closeSubpath()
                        
                    fc = QColor(Colors.ACCENT); fc.setAlpha(15)
                    painter.fillPath(fp, QBrush(fc))
                    
                    gc = QColor(Colors.ACCENT); gc.setAlpha(30)
                    painter.setPen(QPen(gc, 3.0)); painter.drawPath(path_max)
                    painter.setPen(QPen(QColor(Colors.ACCENT), 1.2)); painter.drawPath(path_max)

        if self._show_note and self._smooth_peak_db > -80:
            note = hz_to_note_name(self._smooth_peak_freq)
            txt = f"{note}  {self._smooth_peak_freq:.0f}Hz  {self._smooth_peak_db:.1f}dB"
            painter.setFont(Fonts.value())
            from PySide6.QtGui import QFontMetrics
            fm = QFontMetrics(painter.font())
            tw = fm.horizontalAdvance(txt) + 20
            
            if w > 80:
                if self._show_floating_note:
                    px = map_frequencies_to_pixels(np.array([self._smooth_peak_freq]), dw, self._scale, f_min=20.0, f_max=f_max)[0]
                    frac = max(0, min(1, (self._smooth_peak_db - db_min) / (db_max - db_min)))
                    if is_vertical:
                        py = h - px
                        px_screen = dh * frac
                        bx = max(10, min(w - tw - 10, px_screen - tw/2))
                        by = max(10, min(h - 30, py - 25))
                        cx, cy = px_screen, py
                    else:
                        py_screen = dh * (1.0 - frac)
                        bx = max(10, min(w - tw - 10, px - tw/2))
                        by = max(10, min(dh - 30, py_screen - 25))
                        cx, cy = px, py_screen

                    painter.setFont(self.get_responsive_font(Fonts.value, tw, 22, txt))
                    self.draw_text_badge(painter, QRectF(bx, by, tw, 22), Qt.AlignCenter, txt, QColor(Colors.ACCENT))
                    
                    painter.setPen(Qt.NoPen); painter.setBrush(QColor(Colors.ACCENT))
                    painter.drawEllipse(QPointF(cx, cy), 3, 3)
                else:
                    self.draw_text_badge(painter, QRectF(w - tw - 10, 10, tw, 22), Qt.AlignRight, txt, QColor(Colors.ACCENT))
