"""
Spectrogram Module: Scrolling time-frequency display (numpy-accelerated).
"""

import numpy as np
from PySide6.QtGui import QPainter, QColor, QImage, QPen
from PySide6.QtCore import Qt, QRect, QRectF

from app.base_module import BaseModule
from app.modules import register_module
from app.theme import Colors, Fonts
from app.dsp.fft import compute_fft, fft_frequencies, map_frequencies_to_pixels
from app.dsp import accel as dsp_accel




@register_module("spectrogram", "Spectrogram", category="Spectral")
class SpectrogramModule(BaseModule):

    def __init__(self, audio_engine, parent=None):
        self._fft_size = 2048
        self._scale = "logarithmic"
        self._orientation = "Horizontal"
        self._tilt = 0.0
        self._mode = "Classic"
        self._colormap = "Theme"
        self._show_piano = False
        self._show_freq = True
        self._loop = False
        self._display_h = 256
        self._history_len = 512
        self._db_floor = -90.0
        self._history = np.zeros((self._history_len, self._display_h), dtype=np.float32)
        self._col_idx = 0
        self._lut = dsp_accel.build_colormap(Colors.HEATMAP_STOPS)
        self._speed = 1.0
        self._last_rendered_idx = 0
        # Pre-allocate buffer data and image
        self._buffer_data = np.zeros((self._display_h, self._history_len, 3), dtype=np.uint8)
        self._buffer_img = QImage(self._buffer_data.data, self._history_len, self._display_h,
                                  self._history_len * 3, QImage.Format_RGB888)
        self._ordered_data = None
        self._ordered_img = None
        self._vertical_data = None
        self._vertical_img = None
        self._image_cache_idx = -1
        self.module_key = "spectrogram"
        super().__init__(audio_engine, title="Spectrogram", parent=parent)
        self.canvas.set_render_func(self._render)

    def on_theme_changed(self):
        cmap = getattr(self, "_colormap", "Theme")
        if cmap == "Black-Blue-Red":
            stops = [
                (0.0, "#000000"),
                (0.5, "#0000FF"),
                (1.0, "#FF0000")
            ]
            self._lut = dsp_accel.build_colormap(stops)
        else:
            self._lut = dsp_accel.build_colormap(Colors.HEATMAP_STOPS)
        # Recolor entire history buffer with new LUT
        self._recolor_buffer()

    def _set_colormap(self, name):
        self._colormap = name
        self.on_theme_changed()

    def _recolor_buffer(self):
        """Recolor the entire buffer_data from history using current LUT."""
        try:
            dsp_accel.apply_colormap(
                self._history, self._lut, self._buffer_data,
                0, self._history_len, self._history_len
            )
            self._invalidate_image_cache()
        except (IndexError, ValueError):
            pass  # Shape mismatch during transition — safe to ignore

    def _rebuild_buffer(self):
        """Rebuild the QImage buffer, preserving data integrity."""
        self._buffer_data = np.zeros((self._display_h, self._history_len, 3), dtype=np.uint8)
        self._buffer_img = QImage(self._buffer_data.data, self._history_len, self._display_h,
                                  self._history_len * 3, QImage.Format_RGB888)
        self._invalidate_image_cache()
        # Re-apply history data to buffer
        self._recolor_buffer()

    def _invalidate_image_cache(self):
        self._ordered_data = None
        self._ordered_img = None
        self._vertical_data = None
        self._vertical_img = None
        self._image_cache_idx = -1

    def _rebuild_render_images(self):
        head = self._col_idx % self._history_len
        if head == 0:
            ordered = np.ascontiguousarray(self._buffer_data)
        else:
            ordered = np.ascontiguousarray(
                np.concatenate((self._buffer_data[:, head:], self._buffer_data[:, :head]), axis=1)
            )

        vertical = np.ascontiguousarray(np.rot90(ordered, k=3))

        self._ordered_data = ordered
        self._ordered_img = QImage(
            self._ordered_data.data,
            self._history_len,
            self._display_h,
            self._history_len * 3,
            QImage.Format_RGB888,
        )
        self._vertical_data = vertical
        self._vertical_img = QImage(
            self._vertical_data.data,
            self._display_h,
            self._history_len,
            self._display_h * 3,
            QImage.Format_RGB888,
        )
        self._image_cache_idx = self._col_idx

    def _ensure_render_images(self):
        if self._image_cache_idx != self._col_idx or self._ordered_img is None or self._vertical_img is None:
            self._rebuild_render_images()

    def get_settings(self):
        return {
            "fft_size": self._fft_size,
            "scale": self._scale,
            "orientation": self._orientation,
            "tilt": self._tilt,
            "mode": self._mode,
            "show_piano": self._show_piano,
            "show_freq": self._show_freq,
            "speed": self._speed,
            "db_floor": self._db_floor,
            "colormap": getattr(self, "_colormap", "Theme")
        }

    def apply_settings(self, settings):
        self._fft_size = settings.get("fft_size", self._fft_size)
        self._scale = settings.get("scale", self._scale)
        self._orientation = settings.get("orientation", self._orientation)
        self._tilt = float(settings.get("tilt", self._tilt))
        self._mode = settings.get("mode", self._mode)
        self._show_piano = settings.get("show_piano", self._show_piano)
        self._show_freq = settings.get("show_freq", self._show_freq)
        self._speed = float(settings.get("speed", self._speed))
        self._db_floor = float(settings.get("db_floor", self._db_floor))
        
        old_cmap = getattr(self, "_colormap", "Theme")
        self._colormap = settings.get("colormap", old_cmap)
        if self._colormap != old_cmap:
            self.on_theme_changed()
            
        # Re-initialize history if FFT size changed
        self._set_fft(self._fft_size)

    def build_context_menu(self, menu):
        from PySide6.QtGui import QActionGroup
        
        # Orientation
        om = menu.addMenu("Orientation")
        og = QActionGroup(self)
        for o in ["Horizontal", "Vertical"]:
            a = om.addAction(o)
            a.setCheckable(True)
            a.setChecked(o == self._orientation)
            a.triggered.connect(lambda checked, t=o: setattr(self, "_orientation", t))
            og.addAction(a)

        # Display & Overlays
        dom = menu.addMenu("Display & Overlays")
        cm = dom.addMenu("Colormap")
        cg = QActionGroup(self)
        for c in ["Theme", "Black-Blue-Red"]:
            a = cm.addAction(c)
            a.setCheckable(True)
            a.setChecked(c == getattr(self, "_colormap", "Theme"))
            a.triggered.connect(lambda checked, t=c: self._set_colormap(t))
            cg.addAction(a)

        dom.addSeparator()
        a_piano = dom.addAction("Piano Overlay")
        a_piano.setCheckable(True)
        a_piano.setChecked(self._show_piano)
        a_piano.triggered.connect(lambda checked: setattr(self, "_show_piano", checked))

        a_freq = dom.addAction("Frequency Lines")
        a_freq.setCheckable(True)
        a_freq.setChecked(self._show_freq)
        a_freq.triggered.connect(lambda checked: setattr(self, "_show_freq", checked))

        # FFT & Resolution
        res_m = menu.addMenu("FFT & Resolution")
        fm = res_m.addMenu("FFT Size")
        fg = QActionGroup(self)
        for f in [1024, 2048, 4096, 8192]:
            a = fm.addAction(str(f))
            a.setCheckable(True)
            a.setChecked(f == self._fft_size)
            a.triggered.connect(lambda checked, t=f: self._set_fft(int(t)))
            fg.addAction(a)

        scm = res_m.addMenu("Scale")
        scg = QActionGroup(self)
        for s in ["Mel", "Logarithmic", "Linear"]:
            a = scm.addAction(s)
            a.setCheckable(True)
            a.setChecked(s.lower() == self._scale)
            a.triggered.connect(lambda checked, t=s: setattr(self, "_scale", t.lower()))
            scg.addAction(a)

        mm = res_m.addMenu("Mode")
        mg = QActionGroup(self)
        for m in ["Sharper", "Sharp", "Classic"]:
            a = mm.addAction(m)
            a.setCheckable(True)
            a.setChecked(m == self._mode)
            a.triggered.connect(lambda checked, t=m: setattr(self, "_mode", t))
            mg.addAction(a)

        # Tuning & Response
        tm_sub = menu.addMenu("Tuning & Response")
        sm = tm_sub.addMenu("Speed")
        sg = QActionGroup(self)
        for s in [1, 2, 4, 8]:
            a = sm.addAction(f"{s}x")
            a.setCheckable(True)
            a.setChecked(int(self._speed) == s)
            a.triggered.connect(lambda checked, v=s: setattr(self, "_speed", float(v)))
            sg.addAction(a)

        flm = tm_sub.addMenu("Floor (Sensitivity)")
        flg = QActionGroup(self)
        for f in [-120, -90, -70, -50]:
            a = flm.addAction(f"{f} dB")
            a.setCheckable(True)
            a.setChecked(int(self._db_floor) == f)
            a.triggered.connect(lambda checked, v=f: setattr(self, "_db_floor", float(v)))
            flg.addAction(a)

        tm = tm_sub.addMenu("Tilt")
        tg = QActionGroup(self)
        for t in [-20, -10, 0, 10, 20]:
            a = tm.addAction(str(t))
            a.setCheckable(True)
            a.setChecked(abs(t - self._tilt) < 0.1)
            a.triggered.connect(lambda checked, v=t: setattr(self, "_tilt", float(v)))
            tg.addAction(a)

    def _set_fft(self, size):
        self._fft_size = size
        self._history = np.zeros((self._history_len, self._display_h), dtype=np.float32)
        self._col_idx = 0
        self._last_rendered_idx = 0
        self._rebuild_buffer()

    def _get_window(self):
        if self._mode == "Sharper": return "blackmanharris"
        if self._mode == "Sharp": return "blackman"
        return "hann"

    def on_audio_data(self, data: np.ndarray):
        sig = (data[:, 0] + data[:, 1]) * 0.5 if data.shape[1] > 1 else data[:, 0]
        
        n_steps = int(self._speed)
        step_size = max(1, len(sig) // n_steps)
        
        freqs = fft_frequencies(self._fft_size, self.audio_engine.sample_rate)
        n_bins = min(self._fft_size // 2, len(freqs))
        px = map_frequencies_to_pixels(freqs[:n_bins], self._display_h, self._scale)
        px_int = np.clip(px.astype(np.int32), 0, self._display_h - 1)
        
        for s in range(n_steps):
            start = s * step_size
            end = start + self._fft_size
            
            if start + self._fft_size > len(sig):
                chunk = sig[-self._fft_size:]
            else:
                chunk = sig[start:end]
            
            if len(chunk) < self._fft_size:
                # Pad with zeros if signal is shorter than FFT size
                padded = np.zeros(self._fft_size, dtype=np.float32)
                padded[:len(chunk)] = chunk
                chunk = padded
                
            mag = compute_fft(chunk, self._fft_size, window=self._get_window())

            if abs(self._tilt) > 0.1:
                mag = mag + np.linspace(-self._tilt, self._tilt, len(mag))

            db_min, db_max = self._db_floor, 0.0
            norm = np.clip((mag - db_min) / (db_max - db_min), 0, 1)

            column = dsp_accel.generate_spectrogram_column(
                norm.astype(np.float32), px_int, n_bins, self._display_h
            )

            idx = self._col_idx % self._history_len
            self._history[idx] = column
            self._col_idx += 1

    def _render(self, painter, w, h):
        if self._col_idx < 1: return

        # Colormap new columns since last render (capped to prevent freeze)
        if self._last_rendered_idx < self._col_idx:
            # Cap catch-up to history_len to avoid freeze after minimization
            start_idx = max(self._last_rendered_idx, self._col_idx - self._history_len)
            
            dsp_accel.apply_colormap(
                self._history, self._lut, self._buffer_data,
                start_idx, self._col_idx, self._history_len
            )
            
            self._last_rendered_idx = self._col_idx
        
        # Draw spectrogram image
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        if self._orientation == "Horizontal":
            head = self._col_idx % self._history_len
            if head == 0:
                painter.drawImage(QRect(0, 0, w, h), self._buffer_img)
            else:
                total_cols = self._history_len
                len_1 = total_cols - head
                w_1 = int(w * (len_1 / total_cols))
                painter.drawImage(
                    QRect(0, 0, w_1, h),
                    self._buffer_img,
                    QRect(head, 0, len_1, self._display_h),
                )
                painter.drawImage(
                    QRect(w_1, 0, w - w_1, h),
                    self._buffer_img,
                    QRect(0, 0, head, self._display_h),
                )
        else:
            self._ensure_render_images()
            painter.drawImage(QRect(0, 0, w, h), self._vertical_img)

        # Frequency overlay lines
        if self._show_freq:
            painter.setFont(Fonts.small())
            for gf in [100, 500, 1000, 5000, 10000]:
                if self._orientation == "Horizontal":
                    fy = h - map_frequencies_to_pixels(
                        np.array([gf]), h, self._scale)[0]
                    if 0 < fy < h:
                        painter.setPen(QPen(QColor(255, 255, 255, 40), 1))
                        painter.drawLine(0, int(fy), w, int(fy))
                        lb = f"{gf}" if gf < 1000 else f"{gf // 1000}k"
                        from PySide6.QtGui import QFontMetrics
                        fm = QFontMetrics(Fonts.small())
                        tw = fm.horizontalAdvance(lb) + 12
                        painter.setFont(self.get_responsive_font(Fonts.small, tw, 12, lb))
                        self.draw_text_badge(painter, QRectF(6, fy - 10, tw, 12), Qt.AlignLeft, lb, QColor(255, 255, 255, 150))
                else:
                    fx = map_frequencies_to_pixels(np.array([gf]), w, self._scale)[0]
                    if 0 < fx < w:
                        painter.setPen(QPen(QColor(255, 255, 255, 38), 1))
                        painter.drawLine(int(fx), 0, int(fx), h)
                        if h > 36 and w > 120:
                            lb = f"{gf}" if gf < 1000 else f"{gf // 1000}k"
                            from PySide6.QtGui import QFontMetrics
                            fm = QFontMetrics(Fonts.small())
                            tw = fm.horizontalAdvance(lb) + 12
                            painter.setFont(self.get_responsive_font(Fonts.small, tw, 12, lb))
                            self.draw_text_badge(
                                painter,
                                QRectF(fx - tw / 2, h - 16, tw, 12),
                                Qt.AlignCenter,
                                lb,
                                QColor(255, 255, 255, 145),
                            )

        if self._show_piano:
            self._draw_piano(painter, w, h)

    def _draw_piano(self, painter, w, h):
        notes = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
        black = {1, 3, 6, 8, 10}
        for octave in range(1, 9):
            for ni, note in enumerate(notes):
                freq = 440.0 * 2 ** ((octave - 4) + (ni - 9) / 12.0)
                if freq < 20 or freq > 20000:
                    continue
                col = QColor(0, 0, 0, 100) if ni in black else QColor(255, 255, 255, 60)
                painter.setPen(QPen(col, 1))
                if self._orientation == "Horizontal":
                    fy = h - map_frequencies_to_pixels(
                        np.array([freq]), h, self._scale)[0]
                    if 0 < fy < h:
                        painter.drawLine(w - 20, int(fy), w, int(fy))
                else:
                    fx = map_frequencies_to_pixels(np.array([freq]), w, self._scale)[0]
                    if 0 < fx < w:
                        painter.drawLine(int(fx), 0, int(fx), min(20, h))
