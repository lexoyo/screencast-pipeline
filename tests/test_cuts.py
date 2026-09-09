"""Making the model's cuts safe. Both scenarios below come from a real shoot."""

from screencast.cuts import has_measured_silence, pad_inwards, sanitize, snap_to_silence
from screencast.timeline import parse


def _plan(timeline):
    return parse({"language": "fr", "metadata": {}, "timeline": timeline})


def test_a_cut_gets_a_margin_so_the_next_word_keeps_its_attack():
    # "c'est un peu | toutes les — toutes les plateformes": the cut started exactly where
    # "peu" ended, and shaved it down to "p-"
    plan, _ = sanitize(
        _plan([
            {"start": 39.0, "end": 41.32, "drop": False, "scene": "large"},
            {"start": 41.32, "end": 42.14, "drop": True, "scene": "large", "reason": "repeat"},
            {"start": 42.14, "end": 46.0, "drop": False, "scene": "large"},
        ]),
        silences=[],
        pad=0.07,
    )
    cut = next(s for s in plan.timeline if s.drop)
    assert cut.start > 41.32, "the cut must start after the previous word ends"
    assert cut.end < 42.14, "the cut must end before the next word starts"


def test_the_timeline_stays_contiguous_after_padding():
    # time taken back from a cut must return to a neighbour, or the render skips it
    plan, _ = sanitize(
        _plan([
            {"start": 0.0, "end": 10.0, "drop": False, "scene": "large"},
            {"start": 10.0, "end": 12.0, "drop": True, "scene": "large", "reason": "filler"},
            {"start": 12.0, "end": 20.0, "drop": False, "scene": "large"},
        ]),
        silences=[],
    )
    for previous, following in zip(plan.timeline, plan.timeline[1:], strict=False):
        assert following.start == previous.end


def test_a_cut_invented_as_silence_is_refused():
    # "on va dans votre store | et | on tape Jan": the model called 46.92-48.32 a silence.
    # silencedetect measured none there, and the signal peaked at -7.9 dB. A word died.
    plan, notes = sanitize(
        _plan([
            {"start": 40.0, "end": 46.92, "drop": False, "scene": "ecran"},
            {"start": 46.92, "end": 48.32, "drop": True, "scene": "ecran", "reason": "silence"},
            {"start": 48.32, "end": 57.0, "drop": False, "scene": "ecran"},
        ]),
        silences=[{"start": 12.0, "end": 13.0}],  # 67 elsewhere in the video, none here
    )
    assert not any(s.drop for s in plan.timeline), "audible speech must not be deleted"
    assert any("no silence was measured" in n for n in notes)


def test_a_silence_the_signal_confirms_is_still_cut():
    plan, _ = sanitize(
        _plan([
            {"start": 0.0, "end": 10.0, "drop": False, "scene": "large"},
            {"start": 10.0, "end": 12.0, "drop": True, "scene": "large", "reason": "silence"},
            {"start": 12.0, "end": 20.0, "drop": False, "scene": "large"},
        ]),
        silences=[{"start": 9.9, "end": 12.1}],
    )
    assert any(s.drop for s in plan.timeline)


def test_a_cut_too_short_to_hold_a_margin_is_dropped_rather_than_forced():
    plan, notes = sanitize(
        _plan([
            {"start": 0.0, "end": 10.0, "drop": False, "scene": "large"},
            {"start": 10.0, "end": 10.08, "drop": True, "scene": "large", "reason": "filler"},
            {"start": 10.08, "end": 20.0, "drop": False, "scene": "large"},
        ]),
        silences=[],
        pad=0.07,
    )
    assert not any(s.drop for s in plan.timeline)
    assert any("too short" in n for n in notes)


def test_boundaries_snap_onto_a_measured_silence_when_one_is_near():
    # landing inside a real gap is inaudible whatever the timestamp error — free win
    start, end = snap_to_silence(10.0, 12.0, [{"start": 11.9, "end": 12.3}], reach=0.25)
    assert end == 11.9


def test_snapping_ignores_a_silence_that_is_too_far():
    start, end = snap_to_silence(10.0, 12.0, [{"start": 15.0, "end": 16.0}], reach=0.25)
    assert (start, end) == (10.0, 12.0)


def test_padding_returns_none_when_nothing_survives():
    assert pad_inwards(10.0, 10.1, 0.07) is None


def test_measured_silence_needs_to_cover_most_of_the_span():
    assert has_measured_silence(10.0, 12.0, [{"start": 10.0, "end": 11.5}])
    assert not has_measured_silence(10.0, 12.0, [{"start": 10.0, "end": 10.3}])


def test_kept_spans_are_never_touched():
    original = _plan([{"start": 0.0, "end": 10.0, "drop": False, "scene": "ecran"}])
    plan, notes = sanitize(original, silences=[])
    assert plan.timeline == original.timeline
    assert notes == []


# --- spans too short to hold a frame -------------------------------------------------
# A 0.02 s kept span at 30 fps renders as a file with an audio track and NO video stream.
# `concat -c copy` inherits the hole: the picture freezes while the sound goes on. It
# shipped that way once, frozen from 2:02.

def _spans(*rows):
    return parse({"language": "fr", "metadata": {}, "timeline": [
        {"start": a, "end": b, "drop": d, "scene": sc, "reason": ""}
        for a, b, d, sc in rows
    ]})


def test_a_span_shorter_than_a_frame_is_merged_into_the_previous_shot():
    plan = _spans((0.0, 116.98, False, "ecran"),
                  (116.98, 117.00, False, "ecran"),   # 0.02 s — under one frame
                  (117.00, 174.68, False, "ecran"))
    clean, notes = sanitize(plan, [], fps=30)
    assert [(s.start, s.end) for s in clean.timeline] == [(0.0, 117.00), (117.00, 174.68)]
    assert any("under one frame" in n for n in notes)


def test_every_kept_span_can_hold_at_least_one_frame():
    plan = _spans((0.0, 10.0, False, "ecran"),
                  (10.0, 10.01, False, "large"),
                  (10.01, 20.0, False, "ecran"))
    clean, _ = sanitize(plan, [], fps=30)
    assert all(s.drop or s.duration >= 1 / 30 for s in clean.timeline)


def test_the_audio_of_a_merged_span_is_never_lost():
    """Merged, not dropped: under a frame nobody can see which shot it came from, but the
    two hundredths of a second of speech still have to be there."""
    plan = _spans((0.0, 10.0, False, "ecran"),
                  (10.0, 10.02, False, "large"),
                  (10.02, 20.0, False, "ecran"))
    clean, _ = sanitize(plan, [], fps=30)
    assert clean.timeline[-1].end == 20.0
    assert sum(s.duration for s in clean.timeline if not s.drop) == 20.0


def test_a_too_short_span_at_the_very_start_joins_what_follows():
    plan = _spans((0.0, 0.02, False, "large"), (0.02, 20.0, False, "ecran"))
    clean, notes = sanitize(plan, [], fps=30)
    assert [(s.start, s.end) for s in clean.timeline] == [(0.0, 20.0)]
    assert any("very start" in n for n in notes)


def test_the_floor_follows_the_framerate():
    """A frame lasts longer at a lower framerate, so the floor RISES as fps drops: 0.05 s
    holds a frame at 30 fps and holds none at 15."""
    plan = _spans((0.0, 10.0, False, "ecran"),
                  (10.0, 10.05, False, "ecran"),
                  (10.05, 20.0, False, "ecran"))
    at30, _ = sanitize(plan, [], fps=30)
    at15, notes = sanitize(plan, [], fps=15)
    assert len(at30.timeline) == 3      # 0.05 s > 1/30, left alone
    assert len(at15.timeline) == 2      # 0.05 s < 1/15, absorbed
    assert any("under one frame" in n for n in notes)
