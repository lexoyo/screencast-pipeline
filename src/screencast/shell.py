"""One way to run an external command, and one way to log.

The old code did it three ways — a returncode checked by hand here, `check=True` there,
a bare try/except elsewhere — so a failure surfaced differently depending on which stage
hit it. Everything goes through `run()` now: it logs the command, and a failure raises
with the tail of stderr attached, which is the part that actually says what went wrong.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path


class ToolError(Exception):
    """An external tool failed, or isn't installed."""


_log_file: Path | None = None


def set_log_file(path: Path) -> None:
    global _log_file
    _log_file = path
    path.parent.mkdir(parents=True, exist_ok=True)


def log(msg: str) -> None:
    """Print to the terminal, append to the episode's log.

    Both matter: the terminal is for the person watching a seven-minute render, the file
    is what tells you six months later which ffmpeg settings produced a given video
    (media-agent rule #5).
    """
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)
    if _log_file is not None:
        with _log_file.open("a") as fh:
            fh.write(f"[{time.strftime('%F %T')}] {msg}\n")


def require(tool: str) -> str:
    """Resolve an external binary or fail with a message naming what's missing."""
    found = shutil.which(tool) or (tool if Path(tool).is_file() else None)
    if not found:
        raise ToolError(f"{tool} not found — run ./install.sh to set the toolchain up")
    return found


def run(
    cmd: list[str | Path],
    *,
    capture: bool = False,
    stdin_text: str | None = None,
    allow_fail: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run a command. Raises ToolError on failure unless allow_fail is set.

    `allow_fail` is for the ffmpeg measurement passes: loudnorm and signalstats write
    their results to stderr and exit non-zero by design, since they render no output.
    """
    argv = [str(c) for c in cmd]
    proc = subprocess.run(
        argv,
        input=stdin_text,
        capture_output=capture or stdin_text is not None,
        text=True,
    )
    if proc.returncode != 0 and not allow_fail:
        tail = (proc.stderr or "").strip().splitlines()[-12:]
        detail = "\n  ".join(tail) if tail else "(no stderr)"
        raise ToolError(f"{argv[0]} failed (exit {proc.returncode}):\n  {detail}")
    return proc


def ffprobe_duration(path: Path) -> float:
    """Duration in seconds, 0.0 if the file can't be probed."""
    proc = run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
        capture=True,
        allow_fail=True,
    )
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return 0.0


def ffmpeg(args: list[str | Path], *, allow_fail: bool = False, quiet: bool = True):
    """ffmpeg with the flags we always want: no banner, errors only, overwrite."""
    base: list[str | Path] = ["ffmpeg", "-y", "-hide_banner"]
    base += ["-loglevel", "error"] if quiet else ["-nostats"]
    return run(base + args, capture=not quiet, allow_fail=allow_fail)
