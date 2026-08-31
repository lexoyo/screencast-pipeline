"""One way to run an external command, and one way to log.

The old code did it three ways — a returncode checked by hand here, `check=True` there,
a bare try/except elsewhere — so a failure surfaced differently depending on which stage
hit it. Everything goes through `run()` now: it logs the command, and a failure raises
with the tail of stderr attached, which is the part that actually says what went wrong.
"""

from __future__ import annotations

import os
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
    passthrough_stderr: bool = False,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a command. Raises ToolError on failure unless allow_fail is set.

    `allow_fail` is for the ffmpeg measurement passes: loudnorm and signalstats write
    their results to stderr and exit non-zero by design, since they render no output.
    """
    argv = [str(c) for c in cmd]
    wants_stdout = capture or stdin_text is not None
    if shutil.which(argv[0]) is None and not Path(argv[0]).is_file():
        # Otherwise subprocess raises FileNotFoundError, which no caller catches: whisper
        # missing ended a run in a raw traceback after a minute of audio work, and the
        # music step's "not fatal" handler only ever looked for ToolError.
        raise ToolError(f"{argv[0]}: not found — install it, or fix its path in config.env")
    proc = subprocess.run(
        argv,
        input=stdin_text,
        stdout=subprocess.PIPE if wants_stdout else None,
        # A model call takes minutes; capturing its stderr would hold back everything it
        # says about itself until the end, leaving the terminal silent throughout.
        stderr=None if passthrough_stderr else (subprocess.PIPE if wants_stdout else None),
        text=True,
        env={**os.environ, **env} if env else None,
    )
    if proc.returncode != 0 and not allow_fail:
        tail = (proc.stderr or "").strip().splitlines()[-12:]
        detail = "\n  ".join(tail) if tail else "(no stderr)"
        raise ToolError(f"{argv[0]} failed (exit {proc.returncode}):\n  {detail}")
    return proc


def brain(command: str, prompt: str, work: Path | None = None, step: str = "") -> str:
    """One call to the model: prompt on stdin, answer on stdout.

    Its stderr is deliberately NOT captured. A montage call runs for minutes, and
    capturing would hold back everything the wrapper says — which model is answering,
    what it costs — until the call ends, leaving the terminal silent throughout.

    The wrapper is told where the episode lives, so its trace of the exchange lands in
    `work/brain/<step>/` next to everything else about that episode, and its lines go
    into the same `log.md` as the ffmpeg commands. An edit and the model that decided it
    stay in one place.
    """
    env = {}
    if work is not None:
        env["BRAIN_LOG"] = str(work / "brain" / (step or "appel"))
    if _log_file is not None:
        env["BRAIN_LOG_FILE"] = str(_log_file)
    proc = run([command, "-p"], stdin_text=prompt, passthrough_stderr=True, env=env or None)
    return proc.stdout


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


def loudness_lufs(path: Path, start: float = 0.0, duration: float | None = None) -> float | None:
    """Integrated loudness of a file, or of one stretch of it.

    The stretch matters: a track's average says little about the six seconds actually used
    under a card, because a piece of music starts quietly. Measuring the whole file put the
    first real intro 7 dB below its target.

    LUFS rather than RMS: it is what "as loud as the voice" means to an ear, and the unit
    the audio target in config.env is already expressed in.
    """
    args: list[str | Path] = ["ffmpeg", "-hide_banner", "-nostats"]
    if start:
        args += ["-ss", str(start)]
    if duration:
        args += ["-t", str(duration)]
    args += ["-i", path, "-af", "ebur128=framelog=quiet", "-f", "null", "-"]
    proc = run(args, capture=True, allow_fail=True)
    for line in reversed((proc.stderr or "").splitlines()):
        if "I:" in line and "LUFS" in line:
            try:
                return float(line.split("I:")[1].split("LUFS")[0].strip())
            except (IndexError, ValueError):
                return None
    return None
