"""Lightweight runtime timing counters for profiling builds."""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass


@dataclass
class _Timing:
    count: int = 0
    total_s: float = 0.0
    max_s: float = 0.0

    def add(self, seconds: float) -> None:
        self.count += 1
        self.total_s += seconds
        if seconds > self.max_s:
            self.max_s = seconds


@dataclass
class _Counter:
    count: int = 0
    total: float = 0.0
    max_value: float = 0.0

    def add(self, value: float) -> None:
        self.count += 1
        self.total += value
        if value > self.max_value:
            self.max_value = value


_lock = threading.Lock()
_timings: defaultdict[str, _Timing] = defaultdict(_Timing)
_counters: defaultdict[str, _Counter] = defaultdict(_Counter)
_last_event_at: dict[str, float] = {}
_enabled = False


def set_enabled(enabled: bool) -> None:
    global _enabled
    with _lock:
        _enabled = bool(enabled)
        if _enabled:
            _timings.clear()
            _counters.clear()
            _last_event_at.clear()


def is_enabled() -> bool:
    return _enabled


def reset() -> None:
    with _lock:
        _timings.clear()
        _counters.clear()
        _last_event_at.clear()


def record_timing(name: str, seconds: float) -> None:
    if not _enabled:
        return
    if seconds < 0:
        return
    with _lock:
        _timings[name].add(seconds)


def record_count(name: str, value: float = 1.0) -> None:
    if not _enabled:
        return
    with _lock:
        _counters[name].add(value)


def record_interval(name: str) -> None:
    if not _enabled:
        return
    now = time.perf_counter()
    with _lock:
        last = _last_event_at.get(name)
        _last_event_at[name] = now
        if last is not None:
            _timings[name].add(now - last)


def snapshot() -> dict[str, dict[str, dict[str, float]]]:
    with _lock:
        timings = {
            name: {
                "count": timing.count,
                "total_s": timing.total_s,
                "avg_ms": (timing.total_s / timing.count) * 1000.0 if timing.count else 0.0,
                "max_ms": timing.max_s * 1000.0,
            }
            for name, timing in _timings.items()
        }
        counters = {
            name: {
                "count": counter.count,
                "total": counter.total,
                "avg": counter.total / counter.count if counter.count else 0.0,
                "max": counter.max_value,
            }
            for name, counter in _counters.items()
        }
    return {"timings": timings, "counters": counters}
