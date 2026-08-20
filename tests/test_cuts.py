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
