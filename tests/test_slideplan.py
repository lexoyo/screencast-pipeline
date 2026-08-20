"""Where the slides land on the edited timeline."""

from screencast.slideplan import Overlay, build, resolve_conflicts
from screencast.timeline import parse

CHANNEL = {"name": "Alex Hoyau", "handle": "@AlexHoyau", "programme_label": "Au programme"}


def _plan(timeline, metadata=None):
    return parse({"language": "fr", "metadata": metadata or {}, "timeline": timeline})


BODY = [
    {"start": 0.0, "end": 60.0, "drop": False, "scene": "large"},
    {"start": 60.0, "end": 70.0, "drop": True, "scene": "large", "reason": "fumble"},
    {"start": 70.0, "end": 120.0, "drop": False, "scene": "ecran"},
]


def test_an_intro_pushes_every_chapter_back_by_its_own_length():
    # the whole point of cards: they ADD time, where a cut removes it
    plan = _plan(BODY, {"intro": {"title": "Un titre"},
                        "chapters": [{"at": 10, "label": "Premier"}]})
    layout = build(plan, plan.kept, channel=CHANNEL, intro_seconds=4.0)
    chapter = next(o for o in layout.overlays if o.kind == "chapter")
    assert chapter.start == 14.0  # 10 s into the body, plus the 4 s intro
    assert layout.body_offset == 4.0


def test_without_an_intro_nothing_is_shifted():
    plan = _plan(BODY, {"chapters": [{"at": 10, "label": "Premier"}]})
    layout = build(plan, plan.kept, channel=CHANNEL)
    assert next(o for o in layout.overlays if o.kind == "chapter").start == 10.0
    assert layout.total_added == 0.0


def test_a_chapter_marker_that_fell_in_a_cut_moves_to_what_follows():
    plan = _plan(BODY, {"chapters": [{"at": 65, "label": "Dans la coupe"}]})
    layout = build(plan, plan.kept, channel=CHANNEL)
    # 60-70 was cut, so the marker opens the next surviving segment
    assert next(o for o in layout.overlays if o.kind == "chapter").start == 60.0


def test_the_outro_starts_after_the_body_not_after_the_rush():
    plan = _plan(BODY, {"outro": {"title": "Merci"}})
    layout = build(plan, plan.kept, channel=CHANNEL, outro_seconds=4.0)
    outro = next(c for c in layout.cards if c.kind == "outro")
    assert outro.start == 110.0  # 120 s of rush minus the 10 s cut
    assert layout.total_added == 4.0


def test_no_programme_overlay_when_nothing_was_announced():
    # if the speaker never announces one, showing a panel would be inventing it
    plan = _plan(BODY, {"chapters": [{"at": 10, "label": "Premier"}]})
    layout = build(plan, plan.kept, channel=CHANNEL)
    assert not any(o.kind == "plan" for o in layout.overlays)


def test_the_programme_lasts_exactly_the_sentence_that_announces_it():
    timeline = [
        {"start": 0.0, "end": 20.0, "drop": False, "scene": "large"},
        {"start": 20.0, "end": 28.0, "drop": False, "scene": "large", "plan": True},
    ]
    plan = _plan(timeline, {"chapters": [{"at": 40, "label": "Un"}]})
    layout = build(plan, plan.kept, channel=CHANNEL)
    programme = next(o for o in layout.overlays if o.kind == "plan")
    assert (programme.start, programme.end) == (20.0, 28.0)


def test_two_overlays_never_share_a_moment():
    # observed for real: the model tagged one segment as BOTH the programme announcement
    # and a list point, drawing a panel and a blurred card on top of each other
    timeline = [
        {"start": 0.0, "end": 30.0, "drop": False, "scene": "large"},
        {"start": 30.0, "end": 38.0, "drop": False, "scene": "large",
         "plan": True, "list_item": {"n": 3, "label": "Gérer les modèles"}},
    ]
    plan = _plan(timeline, {"chapters": [{"at": 5, "label": "Un"}]})
    layout = build(plan, plan.kept, channel=CHANNEL)
    for first, second in zip(layout.overlays, layout.overlays[1:], strict=False):
        assert second.start >= first.end, f"{first.kind} overlaps {second.kind}"


def test_the_more_specific_overlay_wins_a_conflict():
    conflict = [
        Overlay("chapter", {}, 10.0, 13.0),
        Overlay("plan", {}, 10.0, 18.0),
    ]
    kept = resolve_conflicts(conflict)
    programme = next(o for o in kept if o.kind == "plan")
    assert (programme.start, programme.end) == (10.0, 18.0)


def test_a_displaced_overlay_is_trimmed_rather_than_dropped():
    kept = resolve_conflicts([Overlay("plan", {}, 10.0, 14.0), Overlay("chapter", {}, 12.0, 20.0)])
    chapter = next(o for o in kept if o.kind == "chapter")
    assert chapter.start == 14.0  # pushed after the programme, still shown


def test_an_overlay_left_with_a_flash_is_dropped():
    # under a second on screen reads as a glitch, not as information
    kept = resolve_conflicts([Overlay("plan", {}, 10.0, 20.0), Overlay("chapter", {}, 19.5, 20.2)])
    assert [o.kind for o in kept] == ["plan"]


def test_a_chapter_overlay_never_runs_past_the_body():
    plan = _plan(BODY, {"chapters": [{"at": 119, "label": "Tout à la fin"}]})
    layout = build(plan, plan.kept, channel=CHANNEL, chapter_overlay=3.0)
    body_end = sum(seg.duration for seg in plan.kept)
    assert next(o for o in layout.overlays if o.kind == "chapter").end <= body_end
