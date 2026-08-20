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
    plan = _plan(timeline, {"chapters": [{"at": 0, "label": "Installer"}, {"at": 50, "label": "Utiliser"}]})
    layout = build(plan, plan.kept, channel=CHANNEL)
    programme = next(o for o in layout.overlays if o.kind == "plan")
    assert (programme.start, programme.end) == (20.0, 28.0)


def test_the_panel_shows_the_chapter_labels():
    # the panel and the bands read from the SAME list, so the video never promises
    # "Installer Jan" and captions the same passage "Installation"
    timeline = [{"start": 0.0, "end": 30.0, "drop": False, "scene": "large", "plan": True}]
    plan = _plan(timeline, {
        "chapters": [{"at": 1, "label": "Installer"}, {"at": 50, "label": "Utiliser"},
                     {"at": 90, "label": "Gérer les modèles"}],
    })
    layout = build(plan, plan.kept, channel=CHANNEL)
    panel = next(o for o in layout.overlays if o.kind == "plan")
    assert panel.values["chapters"] == ["Installer", "Utiliser", "Gérer les modèles"]


def test_a_card_takes_its_wording_from_the_chapter_list():
    # one list seen three times: the panel, the band and the card must not say three
    # different things about the same passage
    timeline = [
        {"start": 0.0, "end": 10.0, "drop": False, "scene": "large", "plan": True},
        {"start": 10.0, "end": 200.0, "drop": False, "scene": "ecran"},
        {"start": 200.0, "end": 220.0, "drop": False, "scene": "ecran",
         "list_item": {"n": 2, "label": "libellé concurrent"}},
    ]
    plan = _plan(timeline, {"chapters": [{"at": 0, "label": "Installer Jan"}, {"at": 50, "label": "L'utiliser au quotidien"}]})
    layout = build(plan, plan.kept, channel=CHANNEL)
    card = next(o for o in layout.overlays if o.kind == "list")
    assert card.values["label"] == "L'utiliser au quotidien"


def test_a_card_too_close_to_the_panel_is_not_shown():
    # it would only repeat what the viewer read seconds ago, while hiding the speaker
    timeline = [
        {"start": 0.0, "end": 10.0, "drop": False, "scene": "large", "plan": True},
        {"start": 10.0, "end": 20.0, "drop": False, "scene": "ecran",
         "list_item": {"n": 1, "label": "Installer"}},
    ]
    plan = _plan(timeline, {"chapters": [{"at": 0, "label": "Installer"}, {"at": 50, "label": "Utiliser"}]})
    layout = build(plan, plan.kept, channel=CHANNEL, list_card_min_gap=30.0)
    assert not any(o.kind == "list" for o in layout.overlays)


def test_a_card_far_enough_from_the_panel_is_shown():
    timeline = [
        {"start": 0.0, "end": 10.0, "drop": False, "scene": "large", "plan": True},
        {"start": 10.0, "end": 200.0, "drop": False, "scene": "ecran"},
        {"start": 200.0, "end": 230.0, "drop": False, "scene": "ecran",
         "list_item": {"n": 1, "label": "Installer"}},
    ]
    plan = _plan(timeline, {"chapters": [{"at": 0, "label": "Installer"}, {"at": 50, "label": "Utiliser"}]})
    layout = build(plan, plan.kept, channel=CHANNEL, list_card_min_gap=30.0)
    assert any(o.kind == "list" for o in layout.overlays)


def test_a_card_is_capped_and_does_not_last_the_whole_segment():
    # it hides the speaker: a 40-second segment must not mean 40 seconds behind a card
    timeline = [
        {"start": 0.0, "end": 200.0, "drop": False, "scene": "large"},
        {"start": 200.0, "end": 240.0, "drop": False, "scene": "ecran",
         "list_item": {"n": 1, "label": "Installer"}},
    ]
    plan = _plan(timeline, {"chapters": [{"at": 0, "label": "Installer"}]})
    layout = build(plan, plan.kept, channel=CHANNEL, list_card_seconds=3.5)
    card = next(o for o in layout.overlays if o.kind == "list")
    assert card.duration == 3.5


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


def test_a_chapter_band_carries_no_number():
    # the panel is numbered (01, 02, 03 = announced points) and there are always more
    # chapters than points: a band reading "02 Installation" eleven seconds after a panel
    # promising "02 Utiliser le chat" makes the viewer conflate two different lists
    plan = _plan(BODY, {"chapters": [{"at": 30, "label": "Installation"}]})
    layout = build(plan, plan.kept, channel=CHANNEL)
    band = next(o for o in layout.overlays if o.kind == "chapter")
    assert "number" not in band.values
    assert band.values["title"] == "Installation"


def test_a_chapter_right_after_the_intro_card_is_dropped():
    # it repeats what the card just said
    plan = _plan(BODY, {"intro": {"title": "Un titre"},
                        "chapters": [{"at": 1, "label": "Trop tôt"}]})
    layout = build(plan, plan.kept, channel=CHANNEL, intro_seconds=4.0, chapter_min_gap=8.0)
    assert not any(o.kind == "chapter" for o in layout.overlays)


def test_a_chapter_butting_against_the_programme_panel_is_dropped():
    timeline = [
        {"start": 0.0, "end": 20.0, "drop": False, "scene": "large"},
        {"start": 20.0, "end": 30.0, "drop": False, "scene": "large", "plan": True},
        {"start": 30.0, "end": 120.0, "drop": False, "scene": "ecran"},
    ]
    plan = _plan(timeline, {"chapters": [{"at": 31, "label": "Juste après"}]})
    layout = build(plan, plan.kept, channel=CHANNEL, chapter_min_gap=8.0)
    assert not any(o.kind == "chapter" for o in layout.overlays)


def test_a_chapter_far_from_everything_is_kept():
    timeline = [
        {"start": 0.0, "end": 20.0, "drop": False, "scene": "large", "plan": True},
        {"start": 20.0, "end": 200.0, "drop": False, "scene": "ecran"},
    ]
    plan = _plan(timeline, {"chapters": [{"at": 120, "label": "Loin"}]})
    layout = build(plan, plan.kept, channel=CHANNEL, chapter_min_gap=8.0)
    assert any(o.kind == "chapter" for o in layout.overlays)


def test_no_chapter_band_where_a_card_already_named_that_chapter():
    # the card IS the chapter announcement, louder; a band six seconds later repeating the
    # same words is noise — seen at 4:50 and 4:56 on a real take
    timeline = [
        {"start": 0.0, "end": 100.0, "drop": False, "scene": "large"},
        {"start": 100.0, "end": 130.0, "drop": False, "scene": "ecran",
         "list_item": {"n": 2}},
    ]
    plan = _plan(timeline, {"chapters": [{"at": 5, "label": "Installer"},
                                         {"at": 101, "label": "Utiliser le chat"}]})
    layout = build(plan, plan.kept, channel=CHANNEL)
    bands = [o.values["title"] for o in layout.overlays if o.kind == "chapter"]
    assert "Utiliser le chat" not in bands
