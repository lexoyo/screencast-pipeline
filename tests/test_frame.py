"""Resolving the output frame against the screen rush.

The 08/09 episode was shot on a 16:10 laptop screen while the pipeline still hard-coded a
16:9 output. `scale=...:force_original_aspect_ratio=increase,crop=...` then quietly cut a
tenth of the height away — the window title bar off the top, the dock off the bottom.
These tests pin the rule that replaced the assumption.
"""

import pytest

from screencast import episode as episode_mod
from screencast.config import ConfigError, load
from screencast.episode import open_episode
from screencast.shotcut import cover_rect, display_aspect
from screencast.slides import DESIGN_W, frame_css

MINIMAL = """
WHISPER_BIN="/opt/whisper.cpp/build/bin/whisper-cli"
WHISPER_MODEL="$HOME/models/whisper/ggml-small.bin"
"""


def _root(tmp_path, extra="", *, with_rush=True):
    config = tmp_path / "config.env"
    config.write_text(MINIMAL + extra)
    root = tmp_path / "take_montage"
    root.mkdir()
    if with_rush:
        (root / "screen.mkv").write_bytes(b"")
    return root, load(config)


def _measuring(monkeypatch, dims):
    monkeypatch.setattr(episode_mod, "ffprobe_dimensions", lambda _path: dims)


def test_an_unset_frame_is_the_rush_at_native_size(tmp_path, monkeypatch):
    root, cfg = _root(tmp_path)
    _measuring(monkeypatch, (2560, 1600))
    ep = open_episode(root, cfg)
    assert (ep.cfg.out_w, ep.cfg.out_h) == (2560, 1600)


def test_a_pinned_width_derives_the_height_from_the_rush(tmp_path, monkeypatch):
    root, cfg = _root(tmp_path, 'OUT_W="1920"\n')
    _measuring(monkeypatch, (2560, 1600))
    ep = open_episode(root, cfg)
    assert (ep.cfg.out_w, ep.cfg.out_h) == (1920, 1200)


def test_a_pinned_height_derives_the_width_from_the_rush(tmp_path, monkeypatch):
    root, cfg = _root(tmp_path, 'OUT_H="1080"\n')
    _measuring(monkeypatch, (2560, 1600))
    ep = open_episode(root, cfg)
    assert (ep.cfg.out_w, ep.cfg.out_h) == (1728, 1080)


def test_both_axes_pinned_is_an_override_and_never_probes(tmp_path, monkeypatch):
    root, cfg = _root(tmp_path, 'OUT_W="1920"\nOUT_H="1080"\n')

    def refuse(_path):
        raise AssertionError("the rush must not be probed when the frame is explicit")

    monkeypatch.setattr(episode_mod, "ffprobe_dimensions", refuse)
    ep = open_episode(root, cfg)
    assert (ep.cfg.out_w, ep.cfg.out_h) == (1920, 1080)


def test_a_derived_dimension_is_rounded_to_an_even_number(tmp_path, monkeypatch):
    # libx264 with yuv420p refuses an odd width or height, and a shoot is not the moment
    # to discover it: 1000 * 1081/1920 is 563.0, which must not reach ffmpeg as 563.
    root, cfg = _root(tmp_path, 'OUT_W="1000"\n')
    _measuring(monkeypatch, (1920, 1081))
    ep = open_episode(root, cfg)
    assert ep.cfg.out_h % 2 == 0


def test_an_odd_frame_written_by_hand_is_refused(tmp_path):
    # Not rounded behind the user's back: a value someone typed is either used or named.
    with pytest.raises(ConfigError, match="even"):
        _root(tmp_path, 'OUT_W="1001"\n')


def test_a_shoot_with_no_screen_rush_keeps_the_old_frame(tmp_path):
    root, cfg = _root(tmp_path, with_rush=False)
    ep = open_episode(root, cfg)
    assert (ep.cfg.out_w, ep.cfg.out_h) == (1920, 1080)


def test_an_unreadable_rush_keeps_the_old_frame(tmp_path, monkeypatch):
    root, cfg = _root(tmp_path)
    _measuring(monkeypatch, None)
    ep = open_episode(root, cfg)
    assert (ep.cfg.out_w, ep.cfg.out_h) == (1920, 1080)


@pytest.mark.parametrize(
    ("width", "height", "design_h", "zoom"),
    [
        (1920, 1080, 1080, "1"),      # the frame the cards were designed for: no zoom
        (2560, 1600, 1200, "1.333333"),
        (3840, 2160, 1080, "2"),
    ],
)
def test_cards_are_drawn_at_the_frame_but_laid_out_at_the_design_width(
    width, height, design_h, zoom
):
    """A card must be redrawn larger, never stretched: 16:9 art on a 16:10 frame."""
    css = frame_css(width, height)
    assert (css["frame_w"], css["frame_h"]) == (width, height)
    assert (css["design_w"], css["design_h"]) == (DESIGN_W, design_h)
    assert css["frame_zoom"] == zoom


@pytest.mark.parametrize(
    ("width", "height", "aspect"),
    [(1920, 1080, (16, 9)), (2560, 1600, (8, 5)), (1920, 1200, (8, 5)), (1080, 1920, (9, 16))],
)
def test_the_shotcut_profile_declares_the_frame_it_actually_has(width, height, aspect):
    assert display_aspect(width, height) == aspect


def test_the_shotcut_rect_reproduces_the_crop_ffmpeg_does():
    """qtblend stretches into its rect, so the rect has to overflow the frame.

    Written as the frame itself, a 16:9 camera on a 16:10 project showed the speaker 11%
    wider in Shotcut than in final.mp4.
    """
    assert cover_rect((1920, 1080), 2560, 1600) == "-142 0 2844 1600 1"


def test_a_source_that_shares_the_frame_aspect_fills_it_exactly():
    assert cover_rect((2560, 1600), 2560, 1600) == "0 0 2560 1600 1"
    assert cover_rect((1920, 1080), 1920, 1080) == "0 0 1920 1080 1"


def test_the_zoom_rect_covers_and_magnifies():
    assert cover_rect((1920, 1080), 2560, 1600, zoom=1.4) == "-711 -320 3982 2240 1"


def test_no_measurable_camera_falls_back_to_the_frame():
    assert cover_rect(None, 2560, 1600) == "0 0 2560 1600 1"
    assert cover_rect((0, 0), 1920, 1080, zoom=1.4) == "-384 -216 2688 1512 1"


def test_an_unmeasurable_rush_keeps_one_whole_shape(tmp_path, monkeypatch):
    """Per-axis fallbacks mixed two shapes: OUT_W=1000 used to give a near-square 1000x1080."""
    root, cfg = _root(tmp_path, 'OUT_W="1000"\n')
    _measuring(monkeypatch, None)
    ep = open_episode(root, cfg)
    assert (ep.cfg.out_w, ep.cfg.out_h) == (1000, 562)


def test_a_frame_past_the_encoder_limit_is_refused(tmp_path):
    with pytest.raises(ConfigError, match="16384"):
        _root(tmp_path, 'OUT_W="100000"\n')


def test_the_crop_warning_names_the_axis_the_camera_actually_loses(tmp_path, monkeypatch, capsys):
    """A 16:9 camera in a 16:10 frame loses its SIDES. Saying "top and bottom" would be
    the same class of defect as the assumption this whole change removed: a message that
    contradicts the filter it describes."""
    root, cfg = _root(tmp_path)
    (root / "face.mkv").write_bytes(b"")
    monkeypatch.setattr(
        episode_mod, "ffprobe_dimensions",
        lambda path: (1920, 1080) if path.name.startswith("face") else (2560, 1600),
    )
    open_episode(root, cfg)
    out = capsys.readouterr().out
    assert "cropped left and right, 5% off each side" in out
