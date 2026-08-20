"""Locating the rushes inside an episode folder."""

from pathlib import Path

from screencast.config import load
from screencast.episode import Episode

MINIMAL = """
WHISPER_BIN="/opt/whisper.cpp/build/bin/whisper-cli"
WHISPER_MODEL="$HOME/models/whisper/ggml-small.bin"
SCREEN_FILE="screen.mkv"
FACE_FILE="face.mkv"
"""


def _episode(tmp_path, *files):
    config = tmp_path / "config.env"
    config.write_text(MINIMAL)
    root = tmp_path / "take_montage"
    root.mkdir()
    for name in files:
        (root / name).write_bytes(b"")
    return Episode(root=root, cfg=load(config))


def test_the_configured_name_is_used_when_it_exists(tmp_path):
    ep = _episode(tmp_path, "screen.mkv", "face.mkv")
    assert ep.screen.name == "screen.mkv"
    assert ep.face.name == "face.mkv"


def test_another_container_is_found_without_being_told(tmp_path):
    # OBS writes mkv for the screen and mp4 for Source Record: a run used to stop dead
    # on "missing input: face.mkv" when the file was right there as face.mp4
    ep = _episode(tmp_path, "screen.mkv", "face.mp4")
    assert ep.face.name == "face.mp4"


def test_both_rushes_can_differ_from_the_configured_names(tmp_path):
    ep = _episode(tmp_path, "screen.mov", "face.webm")
    assert ep.screen.name == "screen.mov"
    assert ep.face.name == "face.webm"


def test_unrelated_files_are_not_mistaken_for_a_rush(tmp_path):
    ep = _episode(tmp_path, "screen.mkv", "face.mkv", "screen.srt", "face.txt")
    assert ep.screen.suffix == ".mkv"
    assert ep.face.suffix == ".mkv"


def test_a_genuinely_missing_rush_keeps_the_configured_name_for_the_error(tmp_path):
    # the message must name what was looked for, not an empty glob result
    ep = _episode(tmp_path, "screen.mkv")
    assert ep.face.name == "face.mkv"
    assert not ep.face.exists()
