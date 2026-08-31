"""The one place that answers: how far behind the screen does the camera start?

Both the render and the Shotcut project need this number, and they used to compute it
separately — which meant a fix could land in one and not the other. It lives here now.
"""

from __future__ import annotations

from .episode import Episode
from .obslog import OffsetUnknown, find_offset
from .shell import ffprobe_duration, log


def camera_offset(ep: Episode) -> float:
    """Seconds to subtract from a screen timestamp to land at the same moment on camera.

    Measured from the OBS log when possible. The fallback — the difference in file
    durations — is known to be wrong (it sums the late start and the early stop), so it
    is announced rather than applied quietly.
    """
    if not ep.has_face:
        # Nothing to align: every shot comes from the screen rush, whose timestamps are
        # the reference in the first place.
        return 0.0

    if ep.cfg.face_offset is not None:
        log(f"face/screen offset = {ep.cfg.face_offset:.3f}s (forced in config.env)")
        return ep.cfg.face_offset

    try:
        offset = find_offset(ep.screen)
    except OffsetUnknown as exc:
        fallback = max(0.0, ffprobe_duration(ep.screen) - ffprobe_duration(ep.face))
        log(f"⚠ could not read the OBS log ({exc})")
        log(f"⚠ falling back to the duration difference: {fallback:.3f}s — this OVERSTATES")
        log("⚠ the offset (it adds the early stop to the late start). Lip sync may drift;")
        log("⚠ set FACE_OFFSET in config.env if you know the real value.")
        return fallback

    log(f"face/screen offset = {offset:.3f}s (measured from the OBS log)")
    return offset
