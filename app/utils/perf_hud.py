"""
Real-time Performance Profiler Window.
Standalone compact diagnostic tool for render times, audio latency, and RAM.
"""

import sys
import time
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy,
)
from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import QPainter, QColor, QPen, QFont

from app.utils import perf_stats


def _get_process_ram_mb() -> float:
    """Retrieve current process Working Set RAM in MiB."""
    if sys.platform == "win32":
        try:
            import ctypes
            import ctypes.wintypes as wt

            class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("cb", wt.DWORD),
                    ("PageFaultCount", wt.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            counters = PROCESS_MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(counters)
            kernel32 = ctypes.WinDLL("kernel32.dll")
            kernel32.GetCurrentProcess.restype = wt.HANDLE
            handle = kernel32.GetCurrentProcess()
            psapi = ctypes.WinDLL("psapi.dll")
            psapi.GetProcessMemoryInfo.argtypes = [
                wt.HANDLE,
                ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
                wt.DWORD,
            ]
            if psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                return float(counters.WorkingSetSize) / (1024.0 * 1024.0)
        except Exception:
            pass
    else:
        try:
            import resource
            usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            if sys.platform == "darwin":
                return float(usage) / (1024.0 * 1024.0)
            return float(usage) / 1024.0
        except Exception:
            pass
    return 0.0


class ModuleMetricsCanvas(QWidget):
    """Clean table canvas for module render stats and frame budget gauges."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumHeight(140)
        self._rows = []
        mono_family = "Consolas" if sys.platform == "win32" else "monospace"
        self._mono_font = QFont(mono_family, 9)
        self._header_font = QFont(mono_family, 8)
        self._header_font.setBold(True)

    def set_data(self, rows):
        self._rows = rows
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        if not p.isActive():
            return
        p.setRenderHint(QPainter.Antialiasing, True)

        w, h = self.width(), self.height()
        bg = QColor("#0e1015")
        border = QColor("#1c202a")

        p.setPen(QPen(border, 1))
        p.setBrush(bg)
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 4, 4)

        # Header Row
        p.setFont(self._header_font)
        p.setPen(QColor("#38bdf8"))
        p.drawText(QRectF(12, 8, 105, 14), Qt.AlignLeft | Qt.AlignVCenter, "MODULE")
        p.drawText(QRectF(120, 8, 65, 14), Qt.AlignCenter, "AVG")
        p.drawText(QRectF(190, 8, 65, 14), Qt.AlignCenter, "PEAK")
        p.drawText(QRectF(260, 8, 45, 14), Qt.AlignCenter, "FPS")
        p.drawText(QRectF(315, 8, w - 325, 14), Qt.AlignLeft | Qt.AlignVCenter, "LOAD (16.6ms)")

        # Separator line
        p.setPen(QPen(border, 1))
        p.drawLine(8, 26, w - 8, 26)

        # Module Rows
        budget_ms = 16.667
        row_y = 33

        if not self._rows:
            p.setFont(self._mono_font)
            p.setPen(QColor("#475569"))
            p.drawText(QRectF(0, row_y + 15, w, 20), Qt.AlignCenter, "Waiting for render cycles...")
            p.end()
            return

        for m_key, avg_ms, max_ms, fps in self._rows:
            if row_y > h - 18:
                break

            # Module name
            p.setFont(self._mono_font)
            p.setPen(QColor("#e2e8f0"))
            p.drawText(QRectF(12, row_y, 105, 15), Qt.AlignLeft | Qt.AlignVCenter, m_key)

            # Avg ms
            if avg_ms > 8.0:
                p.setPen(QColor("#ef4444"))
            elif avg_ms > 3.5:
                p.setPen(QColor("#f59e0b"))
            else:
                p.setPen(QColor("#10b981"))
            p.drawText(QRectF(120, row_y, 65, 15), Qt.AlignCenter, f"{avg_ms:.2f} ms")

            # Max ms
            p.setPen(QColor("#64748b"))
            p.drawText(QRectF(190, row_y, 65, 15), Qt.AlignCenter, f"{max_ms:.1f} ms")

            # FPS
            p.setPen(QColor("#38bdf8"))
            p.drawText(QRectF(260, row_y, 45, 15), Qt.AlignCenter, f"{fps:.0f}")

            # Load Bar
            bar_x = 315
            bar_w = max(30, w - bar_x - 55)
            bar_h = 6
            bar_y = row_y + 4

            p.fillRect(QRectF(bar_x, bar_y, bar_w, bar_h), QColor("#171a22"))

            fraction = min(1.0, avg_ms / budget_ms)
            fill_w = max(1.0, bar_w * fraction) if avg_ms > 0.05 else 0.0

            if avg_ms > 8.0:
                gauge_col = QColor("#ef4444")
            elif avg_ms > 3.5:
                gauge_col = QColor("#f59e0b")
            else:
                gauge_col = QColor("#10b981")

            if fill_w > 0:
                p.fillRect(QRectF(bar_x, bar_y, fill_w, bar_h), gauge_col)

            # Percentage label
            pct = (avg_ms / budget_ms) * 100.0
            p.setPen(QColor("#64748b"))
            p.drawText(QRectF(bar_x + bar_w + 6, row_y, 45, 15), Qt.AlignLeft | Qt.AlignVCenter, f"{pct:.0f}%")

            row_y += 20

        p.end()


class PerformanceHUD(QWidget):
    """Compact standalone performance profiler window."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.Window
            | Qt.WindowTitleHint
            | Qt.WindowSystemMenuHint
            | Qt.WindowMinMaxButtonsHint
            | Qt.WindowCloseButtonHint
        )
        self.setWindowTitle("PyDSPMeters Profiler")
        self.setObjectName("PerfProfilerWindow")
        self.resize(460, 260)
        self.setMinimumSize(380, 180)

        self._stats_data = {}
        self._last_snapshot_time = time.perf_counter()
        self._last_paint_counts = {}
        self._module_fps = {}
        self._is_paused = False
        self._always_on_top = False

        self._init_ui()

        # Update at 4Hz (250ms) for negligible profiling overhead
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._refresh_stats)

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(6)

        # Top Bar: Summary Stats on the left, clean buttons on the right
        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(0, 0, 0, 0)
        top_bar.setSpacing(6)

        self.stats_summary = QLabel("RAM: -- | Audio: -- | Total: --")
        self.stats_summary.setObjectName("summaryStats")
        top_bar.addWidget(self.stats_summary, 1)

        self.pin_btn = QPushButton("Pin")
        self.pin_btn.setCheckable(True)
        self.pin_btn.setToolTip("Always on Top")
        self.pin_btn.setObjectName("toolBtn")
        self.pin_btn.clicked.connect(self._toggle_always_on_top)
        top_bar.addWidget(self.pin_btn)

        self.reset_btn = QPushButton("Reset")
        self.reset_btn.setToolTip("Reset peak timings")
        self.reset_btn.setObjectName("toolBtn")
        self.reset_btn.clicked.connect(self._reset_metrics)
        top_bar.addWidget(self.reset_btn)

        self.pause_btn = QPushButton("Pause")
        self.pause_btn.setCheckable(True)
        self.pause_btn.setObjectName("toolBtn")
        self.pause_btn.clicked.connect(self._toggle_pause)
        top_bar.addWidget(self.pause_btn)

        root.addLayout(top_bar)

        # Main Module Table Canvas
        self.canvas = ModuleMetricsCanvas(self)
        root.addWidget(self.canvas, 1)

        self.setStyleSheet("""
            QWidget#PerfProfilerWindow {
                background-color: #090a0f;
                color: #e2e8f0;
            }
            QLabel#summaryStats {
                color: #94a3b8;
                font-size: 11px;
                font-family: 'Consolas', 'Courier New', monospace;
            }
            QPushButton#toolBtn {
                background-color: #141720;
                color: #94a3b8;
                border: 1px solid #232836;
                border-radius: 3px;
                padding: 3px 8px;
                font-size: 11px;
            }
            QPushButton#toolBtn:hover {
                background-color: #1d2230;
                color: #f1f5f9;
                border-color: #333d54;
            }
            QPushButton#toolBtn:checked {
                background-color: #0284c7;
                color: #ffffff;
                border-color: #38bdf8;
            }
        """)

    def _toggle_always_on_top(self):
        self._always_on_top = self.pin_btn.isChecked()
        pos = self.pos()
        self.setWindowFlag(Qt.WindowStaysOnTopHint, self._always_on_top)
        self.show()
        self.move(pos)

    def _toggle_pause(self):
        self._is_paused = self.pause_btn.isChecked()
        self.pause_btn.setText("Resume" if self._is_paused else "Pause")

    def _reset_metrics(self):
        perf_stats.reset()
        self._last_paint_counts.clear()
        self._refresh_stats()

    def showEvent(self, event):
        super().showEvent(event)
        perf_stats.set_enabled(True)
        self._last_snapshot_time = time.perf_counter()
        self._last_paint_counts.clear()
        self._timer.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._timer.stop()
        perf_stats.set_enabled(False)

    def _refresh_stats(self):
        if self._is_paused:
            return

        now = time.perf_counter()
        dt = max(1e-4, now - self._last_snapshot_time)
        self._last_snapshot_time = now

        snap = perf_stats.snapshot()
        timings = snap.get("timings", {})
        self._stats_data = snap

        # Top summary stats
        ram_mb = _get_process_ram_mb()
        audio_timing = timings.get("audio.drain_queue", {})
        audio_avg = audio_timing.get("avg_ms", 0.0)
        audio_drain_interval = timings.get("audio.drain_interval", {})
        audio_rate = (1000.0 / audio_drain_interval["avg_ms"]) if audio_drain_interval.get("avg_ms", 0.0) > 0.0 else 0.0

        # Per-module paint stats
        module_rows = []
        total_paint_avg = 0.0
        for k, v in timings.items():
            if k.startswith("paint."):
                m_key = k[len("paint."):]
                prev_c = self._last_paint_counts.get(m_key, v["count"])
                cnt_diff = max(0, v["count"] - prev_c)
                fps = cnt_diff / dt
                self._module_fps[m_key] = fps
                self._last_paint_counts[m_key] = v["count"]

                avg_ms = v.get("avg_ms", 0.0)
                max_ms = v.get("max_ms", 0.0)
                total_paint_avg += avg_ms
                module_rows.append((m_key, avg_ms, max_ms, fps))

        module_rows.sort(key=lambda item: item[1], reverse=True)
        self.canvas.set_data(module_rows)

        # Format summary
        budget_pct = (total_paint_avg / 16.667) * 100.0
        self.stats_summary.setText(
            f"RAM: {ram_mb:.0f}MB  |  Audio: {audio_avg:.2f}ms ({audio_rate:.0f}b/s)  |  "
            f"Paint: {total_paint_avg:.1f}ms ({budget_pct:.0f}%)"
        )
