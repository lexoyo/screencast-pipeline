"""The edit decision list: parsing what the model returned, and laying out what survives."""

import pytest

from screencast.silences import parse_silencedetect
from screencast.timeline import TimelineError, parse


def _edl(timeline, metadata=None):
    return {"language": "fr", "metadata": metadata or {}, "timeline": timeline}


def test_kept_segments_are_laid_end_to_end():
    plan = parse(
        _edl(
            [
                {"start": 0, "end": 10, "drop": False, "scene": "large"},
                {"start": 10, "end": 15, "drop": True, "scene": "large", "reason": "filler"},
                {"start": 15, "end": 25, "drop": False, "scene": "ecran"},
            ]
        )
    )
    kept = plan.kept
    assert [(k.start, k.final_start) for k in kept] == [(0, 0.0), (15, 10.0)]
    assert kept[-1].final_end == 20.0
    assert plan.final_duration == 20.0


def test_zero_length_spans_are_skipped():
    # a span where the model wrote the same timestamp twice would render an empty clip
    plan = parse(
        _edl(
            [
                {"start": 0, "end": 5, "drop": False, "scene": "large"},
                {"start": 5, "end": 5, "drop": False, "scene": "large"},
            ]
        )
    )
    assert len(plan.kept) == 1


def test_legacy_scene_names_are_translated():
    # EDLs produced before the three-shot rename still sit in old episode folders
    plan = parse(_edl([{"start": 0, "end": 5, "drop": False, "scene": "screencast"}]))
    assert plan.kept[0].scene == "ecran"


def test_an_unknown_scene_falls_back_to_the_wide_shot():
    plan = parse(_edl([{"start": 0, "end": 5, "drop": False, "scene": "drone"}]))
    assert plan.kept[0].scene == "large"


def test_chapters_are_sorted_by_time():
    plan = parse(
        _edl(
            [{"start": 0, "end": 5, "drop": False, "scene": "large"}],
            {"chapters": [{"at": 30, "label": "second"}, {"at": 2, "label": "first"}]},
        )
    )
    assert [c.label for c in plan.metadata.chapters] == ["first", "second"]


def test_list_item_is_parsed_when_present():
    plan = parse(
        _edl(
            [
                {
                    "start": 0,
                    "end": 5,
                    "drop": False,
                    "scene": "large",
                    "list_item": {"n": 3, "label": "Le rendu"},
                },
            ]
        )
    )
    assert plan.kept[0].list_item.n == "3"


def test_an_empty_list_item_is_dropped():
    plan = parse(
        _edl(
            [
                {"start": 0, "end": 5, "drop": False, "scene": "large", "list_item": {}},
            ]
        )
    )
    assert plan.kept[0].list_item is None


def test_an_empty_timeline_is_an_error():
    # rendering would fail much later with a confusing ffmpeg message
    with pytest.raises(TimelineError, match="decided nothing"):
        parse(_edl([]))


def test_silencedetect_pairs_starts_and_ends():
    text = (
        "[silencedetect @ 0x1] silence_start: 12.5\n"
        "[silencedetect @ 0x1] silence_end: 13.4 | silence_duration: 0.9\n"
    )
    assert parse_silencedetect(text) == [{"start": 12.5, "end": 13.4}]


def test_silencedetect_drops_a_silence_still_open_at_the_end():
    text = "silence_start: 1.0\nsilence_end: 2.0\nsilence_start: 9.0\n"
    assert parse_silencedetect(text) == [{"start": 1.0, "end": 2.0}]


def test_silencedetect_on_a_file_with_no_silence():
    assert parse_silencedetect("frame= 100 fps=50") == []
