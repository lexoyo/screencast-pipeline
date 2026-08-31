"""The vocabulary whisper gets wrong. Every case below was observed on a real take."""

from screencast.glossary import as_prompt, corrections, fix, parse

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
