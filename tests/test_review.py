"""Reading the edit as text. Every case below is taken from a real shoot."""

from screencast.review import (
    attach_words,
    check_bookends,
    check_cut,
    collect,
    completes_a_sentence,
    dangles,
    ends_sentence,
    longest_run,
    normalize,
    repeat_is_real,
)
from screencast.timeline import parse


def _plan(timeline, metadata=None):
    return parse({"language": "fr", "metadata": metadata or {}, "timeline": timeline})


def _words(pairs):
    """(text, start, end) triples -> the shape words.json has."""
    return [{"text": t, "start": s, "end": e} for t, s, e in pairs]


# ---- attributing words to spans


def test_every_word_lands_in_exactly_one_span():
    plan = _plan([
        {"start": 0.0, "end": 2.0, "drop": False, "scene": "large"},
        {"start": 2.0, "end": 4.0, "drop": True, "scene": "large", "reason": "filler"},
        {"start": 4.0, "end": 6.0, "drop": False, "scene": "large"},
    ])
    words = _words([("a", 0.1, 0.5), ("b", 1.9, 2.3), ("c", 3.0, 3.4), ("d", 5.0, 5.5)])
    buckets = attach_words(plan.timeline, words)
    assert sum(len(b) for b in buckets) == len(words)
    # "b" straddles the boundary; its middle is at 2.1, so it belongs to the cut
    assert [w["text"] for w in buckets[1]] == ["b", "c"]


def test_a_timeline_out_of_order_does_not_scramble_the_attribution():
    # one EDL on disk is non-monotonic. A bisect over unsorted starts does not fail — it
    # gave a 17-second cut 1600 words, which is how this was found.
    plan = _plan([
        {"start": 10.0, "end": 12.0, "drop": True, "scene": "large", "reason": "filler"},
        {"start": 0.0, "end": 10.0, "drop": False, "scene": "large"},
    ])
    buckets = attach_words(plan.timeline, _words([("tard", 11.0, 11.5), ("tot", 1.0, 1.5)]))
    assert [w["text"] for w in buckets[0]] == ["tard"]
    assert [w["text"] for w in buckets[1]] == ["tot"]


def test_the_context_of_a_cut_is_the_kept_text_on_either_side():
    plan = _plan([
        {"start": 0.0, "end": 2.0, "drop": False, "scene": "large"},
        {"start": 2.0, "end": 3.0, "drop": True, "scene": "large", "reason": "repeat"},
        {"start": 3.0, "end": 5.0, "drop": False, "scene": "large"},
    ])
    _, cuts = collect(plan, _words([("avant", 1.0, 1.5), ("coupe", 2.4, 2.6), ("apres", 4.0, 4.5)]))
    assert len(cuts) == 1
    assert cuts[0].text == "coupe"
    assert [w["text"] for w in cuts[0].before] == ["avant"]
    assert [w["text"] for w in cuts[0].after] == ["apres"]


# ---- does the reason describe what was removed?


def test_elision_does_not_hide_a_repetition():
    # whisper wrote the first one "qu'il": "il enregistre une image, il enregistre la caméra"
    assert normalize("qu'il") == normalize("il") == "il"
    assert normalize("d'aller") == "aller"
    assert normalize("aujourd'hui") == "aujourd'hui", "a long prefix is a word, not an elision"


def test_a_repetition_is_found_even_when_it_is_not_flush_with_the_cut():
    assert longest_run(["il", "enregistre"], ["qu", "il", "enregistre", "une", "image"]) == 2


def _cut(removed, before=(), after=(), reason="repeat", start=10.0, end=11.0):
    plan = _plan([
        {"start": 0.0, "end": start, "drop": False, "scene": "large"},
        {"start": start, "end": end, "drop": True, "scene": "large", "reason": reason},
        {"start": end, "end": end + 10, "drop": False, "scene": "large"},
    ])
    step = 0.2
    words = (
        _words([(w, 1.0 + i * step, 1.2 + i * step) for i, w in enumerate(before)])
        + _words([(w, start + 0.1 + i * step, start + 0.2 + i * step)
                  for i, w in enumerate(removed)])
        + _words([(w, end + 0.1 + i * step, end + 0.2 + i * step)
                  for i, w in enumerate(after)])
    )
    return collect(plan, words)[1][0]


def test_a_real_repeat_is_left_alone():
    # "c'est un peu toutes les — toutes les plateformes"
    cut = _cut(["toutes", "les"], before=["un", "peu"], after=["toutes", "les", "plateformes"])
    assert repeat_is_real(cut)
    assert check_cut(cut) == []


def test_a_repeat_that_is_said_only_once_is_reported():
    cut = _cut(["donc", "la", "dans", "screencast", "en", "fait"],
               before=["harness", "pour", "mes", "captures"],
               after=["j'ai", "fait", "ca", "avec", "claude"])
    assert not repeat_is_real(cut)
    assert [i.severity for i in check_cut(cut)] == ["à revoir"]


def test_a_filler_carrying_a_whole_sentence_is_reported():
    # "Le scheduleur, donc c'est ce que je vous ai dit." — ten words, two seconds, content
    cut = _cut(["Le", "scheduleur,", "donc", "c'est", "ce", "que", "je", "vous", "ai", "dit."],
               reason="filler", start=10.0, end=12.0)
    assert [i.severity for i in check_cut(cut)] == ["à revoir"]


def test_a_false_start_that_was_carried_to_the_end_is_reported_as_such():
    # "Salut tout le monde, alors une petite vidéo un peu méta quoi." — said, not abandoned
    cut = _cut(["Salut", "tout", "le", "monde,", "alors", "une", "petite", "video", "un", "peu", "meta", "quoi."],
               reason="falsestart", start=10.0, end=13.3)
    assert "phrase terminée" in check_cut(cut)[0].what


def test_a_short_punctuated_tic_stays_a_filler():
    # "Et voilà." is a sentence by the letter and a filler by the ear
    cut = _cut(["Et", "voila."], reason="filler", start=10.0, end=11.3)
    assert completes_a_sentence(cut.words)
    assert check_cut(cut) == []


def test_trailing_dots_mark_an_abandoned_phrase_not_a_finished_one():
    # "permet d'écrire du..." is exactly what a false start looks like
    assert not ends_sentence("du...")
    assert not ends_sentence("cette…")
    assert ends_sentence("dit.")
    cut = _cut(["cette...", "Trust", "and", "execute,", "oui,", "oui,", "oui,"],
               reason="falsestart", start=10.0, end=13.6)
    assert check_cut(cut) == []


def test_a_cut_with_no_speech_in_it_is_never_reported():
    # a 159 s cut containing no words removes no content, whatever label it carries
    cut = _cut([], reason="filler", start=10.0, end=169.0)
    assert check_cut(cut) == []


def test_a_cut_that_removes_a_minute_of_speech_stops_the_run():
    cut = _cut(["et"] * 40, reason="fumble", start=10.0, end=80.0)
    assert [i.severity for i in check_cut(cut)] == ["bloquant"]


# ---- the cards


def test_a_take_with_no_card_is_reported_because_it_also_has_no_music():
    plan = _plan([{"start": 0.0, "end": 5.0, "drop": False, "scene": "large"}])
    assert check_bookends(plan)[0].what == "aucun carton intro ni outro"


def test_both_cards_present_is_silent():
    plan = _plan(
        [{"start": 0.0, "end": 5.0, "drop": False, "scene": "large"}],
        metadata={"intro": {"title": "Goose"}, "outro": {"title": "Merci"}},
    )
    assert check_bookends(plan) == []


# ---- junctions the cut leaves hanging


def test_a_cut_that_takes_away_what_the_last_word_introduced_is_reported():
    # "Revenons à Goose si | Donc Goose, vous activez ce que vous voulez." — the "si"
    # dangles, and the capital on "Donc" is why the first version of this check missed it
    cut = _cut(["j'y", "arrive."], before=["Revenons", "a", "Goose", "si"],
               after=["Donc", "Goose,", "vous", "activez"], reason="fumble")
    assert dangles(cut) == "si"
    assert "en suspens" in check_cut(cut)[0].what


def test_a_conjunction_can_end_the_kept_text_because_the_next_words_chain_on():
    # "on l'installe alors | là non voilà c'est flathub" reads perfectly
    cut = _cut(["euh"], before=["on", "l'installe", "alors"], after=["la", "non", "voila"])
    assert dangles(cut) == ""


def test_a_comma_is_a_pause_not_a_dangling_word():
    cut = _cut(["euh"], before=["en", "HTML", "ou", "quoi,"], after=["ca", "me", "fait"])
    assert dangles(cut) == ""
