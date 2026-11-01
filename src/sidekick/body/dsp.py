"""sidekick.body.dsp — health check and reset of the XVF3800 audio DSP ("Reachy Mini Audio")

Overview
    The reSpeaker XVF3800 behind the robot's microphones and speaker can end up in a state
    where USB audio streams carry only zeros and every control read answers "retry" (seen on
    2026-10-26 after repeated USB clients; the vendor changelog for firmware 2.1.4 mentions the
    same symptom after a USB reset). `probe()` reads one parameter and classifies the chip as
    `ok`, `busy`, `absent` or `error`; `reboot()` sends the vendor REBOOT command and waits for
    re-enumeration. `ensure_healthy()` combines both and is run before the daemon is spawned
    (each start of Bobby's service, block #85).
Design
    Uses the SDK's `audio_control_utils` (pyusb) lazily so importing sidekick never touches USB.
    The check must run while no other process holds the control interface, which is why it sits
    in the daemon start path (daemon down) rather than in the connected body. A reboot takes a
    few seconds and does not move the robot; it only restarts the audio chip.
Depends on
    sidekick.log, reachy_mini (lazy).

See Also
--------
    PLAN.md block "[2026-10-26 #13]" (Phase 1 progress: silent microphone root cause).

"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from sidekick.log import Log

PROBE_PARAMETER = "AUDIO_MGR_MIC_GAIN"
REBOOT_PARAMETER = "REBOOT"


@dataclass(frozen=True, slots=True)
class BodyDSPStatus:
    """Result of a probe."""

    kind: str  # ok | busy | absent | error
    firmware: str | None = None
    mic_gain: float | None = None
    detail: str | None = None

    @property
    def ok(self) -> bool:
        """Chip answers normally."""
        return self.kind == "ok"

    def line(self) -> str:
        """One-line summary."""
        parts = [f"audio dsp {self.kind}"]
        if self.firmware:
            parts.append(f"firmware={self.firmware}")
        if self.mic_gain is not None:
            parts.append(f"mic_gain={self.mic_gain:g}")
        if self.detail:
            parts.append(self.detail)
        return " ".join(parts)


def _open() -> Any | None:
    try:
        from reachy_mini.media.audio_control_utils import init_respeaker_usb
    except Exception as exc:  # pragma: no cover - SDK missing
        Log.warning(f"audio control unavailable: {exc!r}")
        return None
    try:
        return init_respeaker_usb()
    except Exception as exc:
        Log.warning(f"audio control open failed: {exc!r}")
        return None


def probe() -> BodyDSPStatus:
    """Read firmware version and one DSP parameter."""
    device = _open()
    if device is None:
        return BodyDSPStatus("absent", detail="no Reachy Mini Audio USB device")
    try:
        try:
            raw = device.read("VERSION")
            firmware = ".".join(str(v) for v in raw[1:]) if raw else None
        except Exception as exc:
            return BodyDSPStatus("error", detail=f"version read failed: {exc!r}")
        try:
            value = device.read(PROBE_PARAMETER)
        except ValueError as exc:
            kind = "busy" if "exceeds" in str(exc) else "error"
            return BodyDSPStatus(kind, firmware=firmware, detail=str(exc))
        except Exception as exc:
            return BodyDSPStatus("error", firmware=firmware, detail=repr(exc))
        gain = float(value[0]) if value else None
        return BodyDSPStatus("ok", firmware=firmware, mic_gain=gain)
    finally:
        try:
            device.close()
        except Exception:
            pass


def reboot(settle_s: float = 6.0) -> bool:
    """Send the vendor REBOOT command and wait for the chip to come back."""
    device = _open()
    if device is None:
        return False
    try:
        device.write(REBOOT_PARAMETER, [1])
        Log.info("audio dsp reboot sent")
    except Exception as exc:
        Log.warning(f"audio dsp reboot failed: {exc!r}")
        return False
    finally:
        try:
            device.close()
        except Exception:
            pass
    time.sleep(settle_s)
    return True


def ensure_healthy(max_reboots: int = 1) -> BodyDSPStatus:
    """Probe; reboot when busy; return the final status."""
    Log.info0()
    status = probe()
    reboots = 0
    while status.kind == "busy" and reboots < max_reboots:
        Log.warning(f"audio dsp not answering ({status.detail}); rebooting it")
        reboots += 1
        if not reboot():
            break
        status = probe()
    if status.ok:
        Log.info(status.line() + (f" after {reboots} reboot(s)" if reboots else ""))
    else:
        Log.warning(status.line())
    return status
