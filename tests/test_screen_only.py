"""A shoot with no camera rush — a documentation screencast, filmed screen-only.

The camera feeds the wide and close-up shots, the face correction and the startup offset.
Without one, each of those has to step aside rather than fail: the screen rush already
carries the webcam in a corner, baked in by OBS, so the video is complete without it.
"""

import pytest

from screencast.config import load
from screencast.episode import Episode, MissingInput
from screencast.montage import force_screen_only
from screencast.sync import camera_offset

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


def test_a_shoot_without_a_camera_file_says_so(tmp_path):
    assert _episode(tmp_path, "screen.mkv").has_face is False


def test_a_shoot_with_one_is_unchanged(tmp_path):
    assert _episode(tmp_path, "screen.mkv", "face.mkv").has_face is True


def test_a_camera_that_does_not_exist_has_no_offset(tmp_path):
    # the fallback path measures file durations, which would mean ffprobe on a missing file
    assert camera_offset(_episode(tmp_path, "screen.mkv")) == 0.0


def test_every_segment_is_pinned_to_the_screen_shot():
    # the prompt asks for it; this is what makes it true even when the model ignores it,
    # since a stray "serre" would send the render to a camera file that is not there
    edl = {"timeline": [{"scene": "serre"}, {"scene": "large"}, {"scene": "ecran"}]}
    assert [s["scene"] for s in force_screen_only(edl)["timeline"]] == ["ecran"] * 3


def test_pinning_survives_a_timeline_that_never_mentions_a_scene():
    assert force_screen_only({"timeline": [{}]})["timeline"][0]["scene"] == "ecran"


def _screen_only(tmp_path, *files):
    ep = _episode(tmp_path, *files)
    ep.screen_only.write_text("no camera rush for this shoot\n")
    return ep


def test_a_missing_camera_rush_is_an_error_not_a_screen_only_shoot(tmp_path):
    # the failure this guards: a two-camera shoot whose rush was moved or archived would
    # otherwise render as a screen-only video and report success
    with pytest.raises(MissingInput, match="webcam rush"):
        _episode(tmp_path, "screen.mkv").need_face()


def test_a_declared_screen_only_shoot_passes(tmp_path):
    _screen_only(tmp_path, "screen.mkv").need_face()  # does not raise


def test_a_shoot_with_a_camera_passes(tmp_path):
    _episode(tmp_path, "screen.mkv", "face.mkv").need_face()  # does not raise


def test_the_marker_wins_over_a_camera_file_that_is_there(tmp_path):
    # re-creating an episode with --no-cam must not half-switch: the marker decides
    assert _screen_only(tmp_path, "screen.mkv", "face.mkv").has_face is False
