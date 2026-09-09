"""The vocabulary whisper gets wrong. Every case below was observed on a real take."""

from pathlib import Path

from screencast.glossary import as_prompt, corrections, fix, load, parse

TERMS = parse("""
# a comment
Claude Code = Cloudcode, Cloud code
Jan = Djann, Djan
Hugging Face
ffmpeg
open source = opensource
""")


def test_a_phonetic_mistake_is_corrected():
    # the one that started this: "j'ai fait ça avec Cloudcode"
    fixed, changed = fix("j'ai fait ça avec Cloudcode", TERMS)
    assert fixed == "j'ai fait ça avec Claude Code"
    assert changed == [("Cloudcode", "Claude Code")]


def test_a_mistake_spanning_two_words_is_corrected():
    fixed, _ = fix("on utilise Cloud code ici", TERMS)
    assert fixed == "on utilise Claude Code ici"


def test_casing_alone_is_enough_to_be_corrected():
    # no alias needed: case, accents and spacing are normalised away
    fixed, changed = fix("un token hugging face", TERMS)
    assert fixed == "un token Hugging Face"
    assert changed == [("hugging face", "Hugging Face")]


def test_a_term_already_correct_is_left_alone():
    fixed, changed = fix("ça tourne avec ffmpeg", TERMS)
    assert fixed == "ça tourne avec ffmpeg"
    assert changed == []


def test_surrounding_text_and_punctuation_survive():
    fixed, _ = fix("bref, Djann, c'est bien.", TERMS)
    assert fixed == "bref, Jan, c'est bien."


def test_a_word_that_merely_contains_a_term_is_not_touched():
    # "Janvier" must not become "Janvier" mangled into "Jan"+"vier"
    fixed, changed = fix("en Janvier prochain", TERMS)
    assert fixed == "en Janvier prochain"
    assert changed == []


def test_several_corrections_in_one_sentence():
    fixed, changed = fix("Djann marche avec Cloudcode", TERMS)
    assert fixed == "Jan marche avec Claude Code"
    assert len(changed) == 2


def test_the_longest_match_wins():
    # "Cloud code" must be read as a pair, not as two unknown words
    fixed, _ = fix("Cloud code", TERMS)
    assert fixed == "Claude Code"


def test_text_with_nothing_to_fix_is_returned_unchanged():
    assert fix("une phrase ordinaire", TERMS) == ("une phrase ordinaire", [])


def test_an_empty_glossary_changes_nothing():
    assert fix("Cloudcode", {}) == ("Cloudcode", [])


def test_comments_and_blank_lines_are_ignored():
    assert "# a comment" not in TERMS
    assert len(TERMS) == 5


def test_an_entry_with_no_alias_is_still_loaded():
    assert TERMS["Hugging Face"] == []


def test_aliases_are_split_on_commas():
    assert TERMS["Claude Code"] == ["Cloudcode", "Cloud code"]


def test_the_prompt_primes_with_canonical_spellings_only():
    # priming whisper with the mistakes would teach it those
    prompt = as_prompt(TERMS)
    assert "Claude Code" in prompt
    assert "Cloudcode" not in prompt


def test_the_prompt_is_capped():
    # it is prepended to every window; a long one eats the context transcription needs
    long_terms = parse("\n".join(f"Terme{i}" for i in range(200)))
    assert len(as_prompt(long_terms, limit=220)) <= 220


def test_the_lead_in_follows_the_spoken_language():
    # whisper conditions on the prompt as if it preceded the audio: a French sentence over
    # an English take primes the decoder for the wrong language
    assert as_prompt(TERMS, language="en").startswith("This is about ")
    assert as_prompt(TERMS, language="fr").startswith("On parle ici de ")


def test_an_unknown_language_gets_no_lead_in():
    # including "auto": priming in the wrong language is the mistake being avoided, and a
    # default would only pick which shoots get it
    for unknown in ("pt", "auto"):
        prompt = as_prompt(TERMS, language=unknown)
        assert prompt.startswith("Claude Code")
        assert "This is about" not in prompt


def test_an_empty_glossary_gives_no_prompt():
    assert as_prompt({}) == ""


def test_every_alias_maps_to_its_canonical_form():
    table = corrections(TERMS)
    assert table["cloudcode"] == "Claude Code"
    assert table["claudecode"] == "Claude Code"
    assert table["djann"] == "Jan"


def test_a_prompt_over_the_limit_stops_on_a_whole_name():
    # observed: the real glossary overran by 32 characters and primed whisper on "An",
    # half of "Anthropic" — a mangled name is exactly what the prompt is meant to prevent
    long = parse("\n".join(f"Terme{i}" for i in range(40)))
    prompt = as_prompt(long, limit=60)
    assert len(prompt) <= 60
    assert prompt.endswith(".")
    assert all(name.startswith("Terme") and name[5:].isdigit()
               for name in prompt.removeprefix("On parle ici de ").rstrip(".").split(", "))


def test_the_glossary_shipped_with_the_pipeline_primes_on_its_subject():
    # the tail is what a long glossary loses, so the current subject is kept first
    from screencast.glossary import load
    prompt = as_prompt(load())
    assert "Goose" in prompt and "Claude Code" in prompt and "Ollama" in prompt


# --- the glossary on what a MODEL wrote, not on what whisper heard -------------------

def test_a_translation_gets_the_glossary_too():
    """A translation rewrites every sentence from scratch, so a name whisper got wrong can
    come back through the model. "guz-docs.ai" shipped in the English description of a
    video whose French description had it right — it is the install URL of the video."""
    from screencast import glossary
    from screencast.publish import fix_names
    # via load(): fix() reads the normalised index it builds, not a bare dict
    path = Path(__file__).parent / "_glossaire_test.txt"
    path.write_text("goose-docs.ai = guz-docs.ai\nClaude Cowork = Cloud Cowork\n")
    terms = glossary.load(path)
    path.unlink()
    data = fix_names({
        "title": "Goose, the free alternative to Cloud Cowork",
        "description": "We install Goose via guz-docs.ai.",
        "chapters": ["Install via guz-docs.ai", "Use it"],
        "tags": ["goose"],
    }, terms)
    assert data["title"] == "Goose, the free alternative to Claude Cowork"
    assert data["description"] == "We install Goose via goose-docs.ai."
    assert data["chapters"] == ["Install via goose-docs.ai", "Use it"]


def test_fix_names_leaves_non_strings_alone():
    from screencast import glossary
    from screencast.publish import fix_names
    data = fix_names({"n": 3, "flag": True, "rows": [1, 2]}, glossary.load())
    assert data == {"n": 3, "flag": True, "rows": [1, 2]}


def test_an_entry_carries_its_own_reach(tmp_path):
    """A domain name holds no space, so as a WORD count it is 1 — while recognising it
    takes three tokens. It used to work only because "MKV = M K V, em ka vé" pushed the
    matcher's reach to 3 for the whole file: deleting that unrelated line would have
    silently stopped correcting every domain."""
    path = tmp_path / "g.txt"
    path.write_text("goose-docs.ai = guz-docs.ai\n")
    terms = load(path)
    assert fix("install via guz-docs.ai.", terms)[0] == "install via goose-docs.ai."
    assert fix("va sur guz-docs.ai, puis", terms)[0] == "va sur goose-docs.ai, puis"


def test_multi_word_entries_still_reach_across_spaces(tmp_path):
    path = tmp_path / "g.txt"
    path.write_text("Claude Code = Cloud Cowork, Cloudcode\n")
    terms = load(path)
    assert fix("dans Cloud Cowork on peut", terms)[0] == "dans Claude Code on peut"
    assert fix("dans Cloudcode on peut", terms)[0] == "dans Claude Code on peut"
