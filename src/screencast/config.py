"""Read and validate config.env once, at startup.

The old pipeline read settings straight out of the environment at the point of use
(`int(env("OUT_W", "1920"))`), so a typo in config.env surfaced as an unreadable
traceback seven minutes into a render. Here everything is parsed and checked before
any work starts, and a bad value names itself.
"""

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass, fields
from pathlib import Path


class ConfigError(Exception):
    """A setting is missing, malformed, or points at something that isn't there."""


def parse_env_file(text: str) -> dict[str, str]:
    """Parse the shell-ish `KEY="value"   # comment` format of config.env.

    Kept deliberately dumb: config.env is sourced by shell scripts too, so it must stay
    valid shell. We only support what that overlap allows — no expansion of other
    variables, no multi-line values. `$HOME` is the one exception, expanded below.
    """
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if not key.isidentifier():
            continue
        try:
            parts = shlex.split(val, comments=True)
        except ValueError as exc:  # unbalanced quote
            raise ConfigError(f"config.env: cannot parse line {raw!r} ({exc})") from exc
        out[key] = parts[0] if parts else ""
    return out


@dataclass(frozen=True)
class Config:
    # -- tools
    whisper_bin: Path
    whisper_model: Path
    claude_bin: str
    melt_bin: str
    sonorita_bin: str
    force_lang: str

    # -- inputs
    screen_file: str
    face_file: str
    mic_source: str

    # -- audio targets
    audio_lufs: float
    audio_tp: float
    audio_lra: float

    # -- face image target
    face_luma_target: float
    face_offset: float | None

    # -- framing
    pip_scale: float
    pip_margin: int
    pip_corner: str
    zoom_scale: float

    # -- list cards
    list_blur: float
    list_darken: float
    list_fade: float
    list_font: Path

    # -- silence removal
    silence_db: str
    silence_min: float
    silence_pad: float

    # -- output
    out_w: int
    out_h: int
    out_fps: int
    draft_crf: int

    @property
    def whisper_dtw_model(self) -> str:
        """whisper-cli's -dtw flag wants the bare model name: ggml-small.bin -> small."""
        return self.whisper_model.name.removeprefix("ggml-").removesuffix(".bin")

    @property
    def mic_from_face(self) -> bool:
        return self.mic_source == "face"


def _get(raw: dict[str, str], key: str, default: str | None = None) -> str:
    val = raw.get(key, "")
    if val == "":
        if default is None:
            raise ConfigError(f"config.env: {key} is required but missing or empty")
        return default
    return val


def _num(raw: dict[str, str], key: str, default: str, cast, unit: str = "") -> float | int:
    val = _get(raw, key, default)
    try:
        return cast(val)
    except ValueError as exc:
        want = "a whole number" if cast is int else "a number"
        raise ConfigError(f"config.env: {key}={val!r} is not {want}{unit}") from exc


def load(config_path: Path, overrides: dict[str, str] | None = None) -> Config:
    """Load config.env, apply overrides, validate.

    `overrides` exists for one case: nouvelle-video.sh knows which container OBS actually
    produced (.mkv/.mp4/.mov) and must win over the default written in config.env.
    """
    if not config_path.is_file():
        raise ConfigError(f"{config_path} not found — copy config.env.example to config.env first")
    raw = parse_env_file(config_path.read_text())
    for key, val in (overrides or {}).items():
        if val:
            raw[key] = val

    # $HOME is the only expansion we support; paths in config.env use it routinely.
    def path_of(key: str, default: str | None = None) -> Path:
        return Path(os.path.expandvars(_get(raw, key, default))).expanduser()

    mic_source = _get(raw, "MIC_SOURCE", "screen")
    if mic_source not in ("screen", "face"):
        raise ConfigError(f"config.env: MIC_SOURCE={mic_source!r} must be 'screen' or 'face'")

    pip_corner = _get(raw, "PIP_CORNER", "br")
    if pip_corner not in ("br", "bl", "tr", "tl"):
        raise ConfigError(f"config.env: PIP_CORNER={pip_corner!r} must be one of br/bl/tr/tl")

    cfg = Config(
        whisper_bin=path_of("WHISPER_BIN"),
        whisper_model=path_of("WHISPER_MODEL"),
        claude_bin=_get(raw, "CLAUDE_BIN", "claude"),
        melt_bin=_get(raw, "MELT_BIN", "melt-7"),
        sonorita_bin=_get(raw, "SONORITA_BIN", "sonorita-cli"),
        force_lang=_get(raw, "FORCE_LANG", ""),
        screen_file=_get(raw, "SCREEN_FILE", "screen.mkv"),
        face_file=_get(raw, "FACE_FILE", "face.mkv"),
        mic_source=mic_source,
        audio_lufs=_num(raw, "AUDIO_LUFS", "-16", float),
        audio_tp=_num(raw, "AUDIO_TP", "-1.5", float),
        audio_lra=_num(raw, "AUDIO_LRA", "11", float),
        face_luma_target=_num(raw, "FACE_LUMA_TARGET", "120", float),
        face_offset=(float(raw["FACE_OFFSET"]) if raw.get("FACE_OFFSET") else None),
        pip_scale=_num(raw, "PIP_SCALE", "0.22", float),
        pip_margin=_num(raw, "PIP_MARGIN", "28", int),
        pip_corner=pip_corner,
        zoom_scale=_num(raw, "ZOOM_SCALE", "1.4", float),
        list_blur=_num(raw, "LIST_BLUR", "26", float),
        list_darken=_num(raw, "LIST_DARKEN", "-0.14", float),
        list_fade=_num(raw, "LIST_FADE", "0.3", float),
        list_font=path_of("LIST_FONT", "/usr/share/fonts/rsms-inter-fonts/InterDisplay-Black.ttf"),
        silence_db=_get(raw, "SILENCE_DB", "-30dB"),
        silence_min=_num(raw, "SILENCE_MIN", "0.6", float),
        silence_pad=_num(raw, "SILENCE_PAD", "0.15", float),
        out_w=_num(raw, "OUT_W", "1920", int),
        out_h=_num(raw, "OUT_H", "1080", int),
        out_fps=_num(raw, "OUT_FPS", "30", int),
        draft_crf=_num(raw, "DRAFT_CRF", "20", int),
    )

    if cfg.zoom_scale <= 1.0:
        raise ConfigError(f"config.env: ZOOM_SCALE={cfg.zoom_scale} must be greater than 1")
    if cfg.out_w <= 0 or cfg.out_h <= 0 or cfg.out_fps <= 0:
        raise ConfigError("config.env: OUT_W, OUT_H and OUT_FPS must all be positive")
    return cfg


def describe(cfg: Config) -> str:
    """One line per setting — what `scast doctor` prints."""
    return "\n".join(f"  {f.name:18s} {getattr(cfg, f.name)}" for f in fields(cfg))
