"""Music beds: where they play, how loud, and which track they read."""

from pathlib import Path

import pytest

from screencast.music import (
    BED_LUFS_OFFSET,
    FADE_OUT,
    LEAD_IN,
    TAIL,
    Bed,
    mix_filter,
    plan_beds,
    seed_for,
    target_for,
    with_gains,
    write_prompts,
)
from screencast.slideplan import Card, Overlay, SlidePlan

TRACKS = {"intro": Path("/m/intro.mp3"), "outro": Path("/m/outro.mp3"), "bed": Path("/m/bed.mp3")}


def _layout(cards=(), overlays=()):
    return SlidePlan(cards=list(cards), overlays=list(overlays))


def test_a_card_reads_its_track_from_the_beginning():
    # the opening of a track is a real beginning; a slice from the middle is not
    layout = _layout(cards=[Card("intro", {}, 0.0, 4.0)])
    bed = plan_beds(layout, TRACKS, bed_duration=60)[0]
    assert bed.source_offset == 0.0
    assert bed.track == TRACKS["intro"]


def test_music_overruns_the_slide_on_both_sides():
    layout = _layout(cards=[Card("intro", {}, 10.0, 4.0)])
    bed = plan_beds(layout, TRACKS, bed_duration=60)[0]
    assert bed.start == 10.0 - LEAD_IN
    assert bed.end == 14.0 + TAIL


def test_music_never_starts_before_the_video():
    layout = _layout(cards=[Card("intro", {}, 0.0, 4.0)])
    assert plan_beds(layout, TRACKS, bed_duration=60)[0].start == 0.0


def test_overlays_close_together_share_one_continuous_bed():
    layout = _layout(
        overlays=[
            Overlay("chapter", {}, 10.0, 13.0),
            Overlay("list", {}, 14.0, 17.5),
        ]
    )
    beds = plan_beds(layout, TRACKS, bed_duration=60)
    assert len(beds) == 1
    assert beds[0].end == 17.5 + TAIL


def test_each_overlay_bed_reads_a_different_part_of_the_track():
    layout = _layout(overlays=[Overlay("chapter", {}, t, t + 3.0) for t in (10.0, 100.0, 200.0)])
    beds = plan_beds(layout, TRACKS, bed_duration=120)
    assert len({b.source_offset for b in beds}) == len(beds)


def test_the_bed_track_is_rewound_when_exhausted():
    layout = _layout(overlays=[Overlay("chapter", {}, t, t + 3.0) for t in (10, 100, 200, 300)])
    beds = plan_beds(layout, TRACKS, bed_duration=12)
    assert any(b.source_offset == 0.0 for b in beds[1:])


def test_no_bed_reads_past_the_end_of_its_track():
    layout = _layout(overlays=[Overlay("chapter", {}, t, t + 3.0) for t in (10, 60, 110)])
    duration = 20.0
    for bed in plan_beds(layout, TRACKS, duration):
        if bed.track == TRACKS["bed"]:
            assert bed.source_offset + bed.duration <= duration


def test_a_missing_track_produces_no_music_rather_than_a_crash():
    # generation can fail; the video must still render, silent
    layout = _layout(cards=[Card("intro", {}, 0.0, 4.0)])
    assert plan_beds(layout, {}, bed_duration=60) == []


def test_no_slides_means_no_music():
    assert plan_beds(_layout(), TRACKS, bed_duration=60) == []


def test_the_seed_is_stable_per_episode_and_per_vibe():
    # a rerun must reuse the same music; the intro and the bed must not be the same track
    assert seed_for("take/Screencast Intro") == seed_for("take/Screencast Intro")
    assert seed_for("take/Screencast Intro") != seed_for("take/Screencast Bed")


def test_the_mix_keeps_the_speech_track():
    graph = mix_filter([Bed(10.0, 15.0, Path("/m/bed.mp3"), 0.0, 0.0)])
    assert "[0:a]" in graph
    assert "normalize=0" in graph, "normalising would duck the voice under the music"


def test_each_bed_is_delayed_to_its_position():
    graph = mix_filter([Bed(12.5, 18.0, Path("/m/bed.mp3"), 0.0, 0.0)])
    assert "adelay=12500|12500" in graph


def test_the_fade_out_lands_inside_the_bed():
    bed = Bed(10.0, 12.0, Path("/m/bed.mp3"), 0.0, 0.0)
    graph = mix_filter([bed])
    assert f"afade=t=out:st={max(0.0, bed.duration - FADE_OUT)}" in graph


def test_no_beds_produces_no_graph():
    assert mix_filter([]) == ""


def test_the_sung_lines_are_substituted_into_the_prompts(tmp_path):
    written = write_prompts(tmp_path / "p", {"intro": "Mon titre chanté", "outro": "À bientôt"})
    intro = next(written.glob("*intro*.md")).read_text()
    outro = next(written.glob("*outro*.md")).read_text()
    assert "Mon titre chanté" in intro
    assert "À bientôt" in outro
    assert "$lyrics" not in intro


def test_the_bed_prompt_is_copied_untouched(tmp_path):
    # it is instrumental: there is nothing to sing, and no placeholder to fill
    written = write_prompts(tmp_path / "p", {"intro": "x", "outro": "y"})
    bed = next(written.glob("*bed*.md")).read_text()
    assert "[instrumental]" in bed
    assert "x" not in bed.split("---")[-1]


def test_cards_are_louder_than_beds():
    # nobody speaks over a card; the bed sits well under the voice
    layout = _layout(
        cards=[Card("intro", {}, 0.0, 4.0)], overlays=[Overlay("chapter", {}, 100.0, 103.0)]
    )
    beds = with_gains(plan_beds(layout, TRACKS, 60), TRACKS, -16.0, lambda *_: -14.0)
    card = next(b for b in beds if b.track == TRACKS["intro"])
    bed = next(b for b in beds if b.track == TRACKS["bed"])
    assert bed.gain_db == pytest.approx(card.gain_db + BED_LUFS_OFFSET)


def test_a_quiet_stretch_is_pushed_up_and_a_loud_one_down():
    # the point of targeting a level: a fixed multiplier put the first real intro at
    # -27.7 LUFS against a body at -16
    layout = _layout(cards=[Card("intro", {}, 0.0, 4.0)])
    quiet = with_gains(plan_beds(layout, TRACKS, 60), TRACKS, -16.0, lambda *_: -28.0)
    assert quiet[0].gain_db == pytest.approx(12.0)
    loud = with_gains(plan_beds(layout, TRACKS, 60), TRACKS, -16.0, lambda *_: -10.0)
    assert loud[0].gain_db == pytest.approx(-6.0)


def test_the_gain_is_measured_on_the_stretch_played_not_the_whole_file():
    # a track's average says little about the six seconds used under a card: measuring the
    # file put the first real intro at -23 LUFS against a target of -16
    layout = _layout(cards=[Card("intro", {}, 0.0, 4.0)])
    seen = []

    def measure(track, start, duration):
        seen.append((start, duration))
        return -20.0

    with_gains(plan_beds(layout, TRACKS, 60), TRACKS, -16.0, measure)
    assert seen == [(0.0, 4.0 + TAIL)]


def test_a_stretch_that_could_not_be_measured_gets_no_gain():
    layout = _layout(cards=[Card("intro", {}, 0.0, 4.0)])
    beds = with_gains(plan_beds(layout, TRACKS, 60), TRACKS, -16.0, lambda *_: None)
    assert beds[0].gain_db == 0.0


def test_the_target_depends_on_which_track_it_is():
    layout = _layout(
        cards=[Card("intro", {}, 0.0, 4.0)], overlays=[Overlay("chapter", {}, 100.0, 103.0)]
    )
    beds = plan_beds(layout, TRACKS, 60)
    card = next(b for b in beds if b.track == TRACKS["intro"])
    bed = next(b for b in beds if b.track == TRACKS["bed"])
    assert target_for(card, TRACKS, -16.0) == -16.0
    assert target_for(bed, TRACKS, -16.0) == -34.0
