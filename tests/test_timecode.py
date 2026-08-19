"""Timecodes and chapter remapping — the things that break without telling you."""

import pytest

from screencast.timecode import mlt_timecode, remap_to_final, srt_timecode, youtube_timecode


def test_mlt_timecode_pads_every_field():
    assert mlt_timecode(0) == "00:00:00.000"
    assert mlt_timecode(1.5) == "00:00:01.500"
    assert mlt_timecode(61.25) == "00:01:01.250"
    assert mlt_timecode(3661.007) == "01:01:01.007"


def test_mlt_timecode_clamps_negative():
    # a lead-in computed from a sync offset can go slightly negative; MLT rejects that
    assert mlt_timecode(-3) == "00:00:00.000"


def test_srt_uses_a_comma():
    # players reject an SRT cue that separates milliseconds with a dot
    assert srt_timecode(61.25) == "00:01:01,250"


def test_youtube_timecode_drops_the_hour_when_there_is_none():
    # YouTube silently ignores a chapter written 0:01:05 on a video under an hour
    assert youtube_timecode(65) == "1:05"
    assert youtube_timecode(0) == "0:00"
    assert youtube_timecode(599) == "9:59"


def test_youtube_timecode_keeps_the_hour_past_one():
    assert youtube_timecode(3725) == "1:02:05"


@pytest.fixture
def kept():
    """Two surviving segments: source 0-10 and 20-30, laid end to end in the cut."""
    return [
        {"start": 0.0, "end": 10.0, "final_start": 0.0, "final_end": 10.0},
        {"start": 20.0, "end": 30.0, "final_start": 10.0, "final_end": 20.0},
    ]


def test_remap_inside_a_kept_segment(kept):
    assert remap_to_final(5.0, kept) == 5.0
    assert remap_to_final(25.0, kept) == 15.0


def test_remap_snaps_forward_when_the_marker_landed_in_a_cut(kept):
    # 15s was removed; the chapter must open the NEXT topic, not close the previous one
    assert remap_to_final(15.0, kept) == 10.0


def test_remap_past_the_end_returns_the_end(kept):
    assert remap_to_final(999.0, kept) == 20.0


def test_remap_with_nothing_kept_is_zero():
    assert remap_to_final(42.0, []) == 0.0


def test_remap_at_an_exact_boundary_belongs_to_the_later_segment(kept):
    # the ranges are half-open, so 10.0 is not inside the first segment
    assert remap_to_final(10.0, kept) == 10.0
