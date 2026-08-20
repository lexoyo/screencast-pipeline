"""Music beds: where they play, and how they overrun the slides."""

from screencast.music import LEAD_IN, TAIL, Bed, beds_for, mix_filter, seed_for
from screencast.slideplan import Card, Overlay, SlidePlan


def _layout(cards=(), overlays=()):
    return SlidePlan(cards=list(cards), overlays=list(overlays))


def test_a_bed_starts_before_the_slide_and_ends_after_it():
    # the overlap is the point: music cut exactly on the picture announces the edit
    layout = _layout(cards=[Card("intro", {}, 10.0, 4.0)])
    bed = beds_for(layout, track_duration=120)[0]
    assert bed.start == 10.0 - LEAD_IN
    assert bed.end == 14.0 + TAIL


def test_a_bed_never_starts_before_the_video():
    # an intro at 0 would otherwise want music at -0.6 s
    layout = _layout(cards=[Card("intro", {}, 0.0, 4.0)])
    assert beds_for(layout, track_duration=120)[0].start == 0.0


def test_slides_close_together_get_one_continuous_bed():
    # two fades crossing sound like a mistake; one stretch sounds deliberate
    layout = _layout(overlays=[
        Overlay("chapter", {}, 10.0, 13.0),
        Overlay("list", {}, 14.0, 17.5),
    ])
    beds = beds_for(layout, track_duration=120)
    assert len(beds) == 1
    assert beds[0].start == 10.0 - LEAD_IN
    assert beds[0].end == 17.5 + TAIL


def test_slides_far_apart_get_separate_beds():
    layout = _layout(overlays=[
        Overlay("chapter", {}, 10.0, 13.0),
        Overlay("chapter", {}, 200.0, 203.0),
    ])
    assert len(beds_for(layout, track_duration=120)) == 2


def test_each_bed_reads_a_different_part_of_the_track():
    # ten slides must not replay the same four bars ten times
    layout = _layout(overlays=[
        Overlay("chapter", {}, 10.0, 13.0),
        Overlay("chapter", {}, 100.0, 103.0),
        Overlay("chapter", {}, 200.0, 203.0),
    ])
    beds = beds_for(layout, track_duration=120)
    assert len({bed.source_offset for bed in beds}) == len(beds)


def test_the_track_is_reused_from_the_start_when_exhausted():
    layout = _layout(overlays=[
        Overlay("chapter", {}, t, t + 3.0) for t in (10.0, 100.0, 200.0, 300.0)
    ])
    beds = beds_for(layout, track_duration=15)
    assert any(bed.source_offset == 0.0 for bed in beds[1:])


def test_a_bed_never_reads_past_the_end_of_the_track():
    layout = _layout(overlays=[Overlay("chapter", {}, t, t + 3.0) for t in (10.0, 60.0, 110.0)])
    duration = 20.0
    for bed in beds_for(layout, duration):
        assert bed.source_offset + bed.duration <= duration


def test_no_slides_means_no_music():
    assert beds_for(_layout(), track_duration=120) == []


def test_the_seed_is_stable_for_a_given_episode():
    # a rerun after a tweak must differ only in what was tweaked, not in its music
    assert seed_for("2026-08-20_montage") == seed_for("2026-08-20_montage")
    assert seed_for("2026-08-20_montage") != seed_for("2026-08-21_montage")


def test_the_mix_keeps_the_speech_track():
    graph, label = mix_filter([Bed(10.0, 15.0, 0.0)])
    assert "[0:a]" in graph, "the speech must be one of the mixed inputs"
    assert label == "[aout]"


def test_each_bed_is_delayed_to_its_position():
    graph, _ = mix_filter([Bed(12.5, 18.0, 0.0)])
    assert "adelay=12500|12500" in graph


def test_no_beds_produces_no_graph():
    assert mix_filter([]) == ("", "")
