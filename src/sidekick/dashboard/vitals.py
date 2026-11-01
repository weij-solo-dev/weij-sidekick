"""sidekick.dashboard.vitals — host vital signs from the standard library (Live's System card)

Overview
    `HostVitals` measures what the Live page's System card says about the machine Bobby's
    brain runs on: the load average against the core count, this process's resident memory,
    CPU share and threads, how late the event loop wakes up, and the Raspberry Pi's SoC
    temperature.
Design
    Standard library only (owner, block #68: no psutil). Resident memory comes from
    `/proc/self/statm` on Linux and from `task_info(MACH_TASK_BASIC_INFO)` through ctypes on
    macOS, else the peak from `getrusage`. The loop lag is measured by a task that sleeps
    `LAG_PERIOD_S` and records how late it woke (the worst of the last `LAG_WINDOW_S`): a
    blocking call on the loop — the thing that makes a voice turn stutter — shows up here
    first. CPU share is process time over wall time between two samples. `sample()` never
    blocks and is cheap enough for the 1 Hz Live push.
Depends on
    stdlib only.

See Also
--------
    AGENTS.md "Dashboard and CLI", PLAN.md blocks "[2026-10-29 #67]", "[2026-10-29 #69]".

"""

from __future__ import annotations

import asyncio
import collections
import ctypes
import ctypes.util
import os
import resource
import sys
import threading
import time
from pathlib import Path
from typing import Any, ClassVar

LAG_PERIOD_S = 0.25
LAG_WINDOW_S = 10.0
PI_THERMAL = Path("/sys/class/thermal/thermal_zone0/temp")


class _TimeValue(ctypes.Structure):
    _fields_ = [("seconds", ctypes.c_int), ("microseconds", ctypes.c_int)]


class _MachTaskBasicInfo(ctypes.Structure):
    _pack_ = 4
    _fields_ = [
        ("virtual_size", ctypes.c_uint64),
        ("resident_size", ctypes.c_uint64),
        ("resident_size_max", ctypes.c_uint64),
        ("user_time", _TimeValue),
        ("system_time", _TimeValue),
        ("policy", ctypes.c_int),
        ("suspend_count", ctypes.c_int),
    ]


MACH_TASK_BASIC_INFO = 20


def resident_mb() -> tuple[float | None, bool]:
    """Resident memory of this process in MB, and whether it is current (False: the peak)."""
    try:
        if sys.platform.startswith("linux"):
            pages = int(Path("/proc/self/statm").read_text().split()[1])
            return pages * os.sysconf("SC_PAGE_SIZE") / 1e6, True
        if sys.platform == "darwin":
            libc = ctypes.CDLL(ctypes.util.find_library("c"))
            task = ctypes.c_uint.in_dll(libc, "mach_task_self_")
            info = _MachTaskBasicInfo()
            count = ctypes.c_uint(ctypes.sizeof(_MachTaskBasicInfo) // 4)
            if (
                libc.task_info(task, MACH_TASK_BASIC_INFO, ctypes.byref(info), ctypes.byref(count))
                == 0
            ):
                return info.resident_size / 1e6, True
    except (OSError, ValueError, AttributeError):
        pass
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return (peak / 1e6 if sys.platform == "darwin" else peak / 1e3), False


def soc_temperature() -> float | None:
    """The SoC temperature in °C where the kernel exposes it (the Raspberry Pi)."""
    try:
        return int(PI_THERMAL.read_text().strip()) / 1000.0
    except (OSError, ValueError):
        return None


class HostVitals:
    """Machine and process vital signs; `start()` runs the event-loop lag probe."""

    shared: ClassVar[HostVitals]

    def __init__(self) -> None:
        self._lags: collections.deque[tuple[float, float]] = collections.deque(maxlen=200)
        self._task: asyncio.Task[None] | None = None
        self._cpu_at = (time.monotonic(), time.process_time())
        self._cpu_share: float | None = None

    async def start(self) -> None:
        """Start the lag probe on the running loop."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._probe(), name="loop-lag-probe")

    async def stop(self) -> None:
        """Stop the lag probe."""
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _probe(self) -> None:
        while True:
            planned = time.monotonic() + LAG_PERIOD_S
            await asyncio.sleep(LAG_PERIOD_S)
            now = time.monotonic()
            self._lags.append((now, max(0.0, now - planned)))

    def loop_lag_ms(self) -> float | None:
        """The worst wake-up delay of the loop over the last `LAG_WINDOW_S` (ms)."""
        cutoff = time.monotonic() - LAG_WINDOW_S
        recent = [lag for at, lag in self._lags if at >= cutoff]
        return round(max(recent) * 1000.0, 1) if recent else None

    def sample(self) -> dict[str, Any]:
        """One reading for the Live page."""
        now, cpu = time.monotonic(), time.process_time()
        then, cpu_then = self._cpu_at
        if now - then >= 0.5:
            self._cpu_share = (cpu - cpu_then) / (now - then)
            self._cpu_at = (now, cpu)
        rss, current = resident_mb()
        try:
            load = os.getloadavg()
        except OSError:
            load = None
        return {
            "load": None if load is None else [round(v, 2) for v in load],
            "cores": os.cpu_count(),
            "rss_mb": None if rss is None else round(rss),
            "rss_current": current,
            "cpu_pct": None if self._cpu_share is None else round(self._cpu_share * 100.0),
            "threads": threading.active_count(),
            "loop_lag_ms": self.loop_lag_ms(),
            "temp_c": soc_temperature(),
        }


HostVitals.shared = HostVitals()
