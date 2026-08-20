"""What is sitting on the GPU, and whether there is room for what we are about to load.

One stage needs the card: music generation, where sonorita-cli loads ~3.1 GB of GGUF into
4 GB of VRAM. That leaves no slack — a browser holding 800 MB is enough to turn a one-minute
generation into an out-of-memory failure, or into a silent fall back to the CPU, which is
worse because it looks like it is working. (whisper.cpp here is built CPU-only:
`GGML_CUDA:BOOL=OFF` in its CMakeCache, so it takes no VRAM at all.)

The check runs *before* the run starts, not at the moment of loading. Closing a browser is
easy; redoing ten minutes of transcription to get back to the point of failure is not.

Everything here degrades to "no opinion" when there is no NVIDIA card: a machine without a
GPU must still be able to run the pipeline, so an absent `nvidia-smi` means no check, not
a failure.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass

from .shell import ToolError

# One line of the Processes table:
# |    0   N/A  N/A      4384      G   /usr/bin/gnome-shell                    412MiB |
PROCESS_LINE = re.compile(
    r"^\|\s+\d+\s+\S+\s+\S+\s+(?P<pid>\d+)\s+(?P<kind>[A-Z+]+)\s+(?P<name>.+?)\s+(?P<mb>\d+)MiB\s*\|$"
)


@dataclass(frozen=True)
class Memory:
    name: str
    total_mb: int
    used_mb: int
    free_mb: int


@dataclass(frozen=True)
class Process:
    pid: int
    kind: str  # G = graphics, C = compute, C+G = both
    name: str
    used_mb: int


def parse_memory(line: str) -> Memory | None:
    """Read one CSV row of `nvidia-smi --query-gpu=name,memory.total,memory.used,memory.free`."""
    parts = [p.strip() for p in line.split(",")]
    if len(parts) < 4:
        return None
    try:
        return Memory(parts[0], int(parts[1]), int(parts[2]), int(parts[3]))
    except ValueError:
        return None


def parse_processes(text: str) -> list[Process]:
    """Read the Processes table of plain `nvidia-smi`.

    Not `--query-compute-apps`: that only lists CUDA contexts, and the memory we are
    fighting for is held by graphics clients — a browser, gnome-shell — which never appear
    there. On this machine the compute-apps query returns an empty list while the table
    shows the real occupants.
    """
    found: list[Process] = []
    for line in text.splitlines():
        match = PROCESS_LINE.match(line.rstrip())
        if match:
            found.append(
                Process(
                    pid=int(match["pid"]),
                    kind=match["kind"],
                    name=match["name"].strip(),
                    used_mb=int(match["mb"]),
                )
            )
    return found


def _smi(args: list[str]) -> str | None:
    if not shutil.which("nvidia-smi"):
        return None
    try:
        proc = subprocess.run(
            ["nvidia-smi", *args], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout if proc.returncode == 0 else None


def memory() -> Memory | None:
    """Current VRAM figures, or None when there is no NVIDIA GPU to ask."""
    out = _smi(
        [
            "--query-gpu=name,memory.total,memory.used,memory.free",
            "--format=csv,noheader,nounits",
        ]
    )
    if not out:
        return None
    for line in out.splitlines():
        parsed = parse_memory(line)
        if parsed:
            return parsed
    return None


def processes() -> list[Process]:
    """Who is holding VRAM right now, biggest first."""
    out = _smi([])
    return sorted(parse_processes(out or ""), key=lambda p: -p.used_mb)


def shortfall(need_mb: int, mem: Memory | None) -> int:
    """How many MB are missing. 0 means there is room — or nothing to check."""
    if mem is None:
        return 0
    return max(0, need_mb - mem.free_mb)


def explain(need_mb: int, what: str, mem: Memory, holders: list[Process]) -> str:
    """The message that names the problem and what to close about it."""
    lines = [
        f"{what} a besoin d'environ {need_mb} Mo de VRAM, il en reste {mem.free_mb} Mo "
        f"libres sur {mem.total_mb} ({mem.name}).",
    ]
    # 32 MB: below that it is the compositor doing its job, not something to close.
    big = [proc for proc in holders if proc.used_mb >= 32]
    if big:
        lines.append("  occupée par :")
        lines += [f"    {proc.used_mb:5d} Mo  {proc.name}  (pid {proc.pid})" for proc in big]
    lines.append("  ferme ce qui n'est pas nécessaire, puis relance.")
    return "\n".join(lines)


def require(need_mb: int, what: str) -> None:
    """Refuse to start when the VRAM is not there. No GPU on the machine = no opinion."""
    mem = memory()
    if not shortfall(need_mb, mem):
        return
    assert mem is not None  # shortfall() only returns > 0 when it read a real figure
    raise ToolError(explain(need_mb, what, mem, processes()))


def describe() -> str:
    """One block for `screencast doctor`."""
    mem = memory()
    if mem is None:
        return "  – gpu          aucun GPU NVIDIA détecté (la musique tournera sur CPU)"
    lines = [f"  ✓ gpu          {mem.name} — {mem.free_mb}/{mem.total_mb} MB libres"]
    for proc in processes():
        if proc.used_mb >= 32:
            lines.append(f"                 {proc.used_mb:5d} MB  {proc.name} (pid {proc.pid})")
    return "\n".join(lines)
