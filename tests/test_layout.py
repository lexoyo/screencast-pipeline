"""On-screen text: line breaks and ffmpeg escaping."""

from screencast.layout import escape_filter_path, wrap


def test_wrap_breaks_on_words():
    assert wrap("supprimer les silences", width=12) == ["supprimer", "les silences"]


def test_wrap_keeps_a_short_label_on_one_line():
    assert wrap("le montage", width=24) == ["le montage"]


def test_wrap_never_cuts_inside_a_word():
    # a truncated command name on screen is worse than an overflowing line
    assert wrap("supercalifragilistic", width=8) == ["supercalifragilistic"]


def test_wrap_of_empty_text_is_empty():
    assert wrap("") == []


def test_escape_filter_path_doubles_the_specials():
    # a path crosses the filtergraph parser then the option parser: both need escaping
    assert escape_filter_path("/tmp/a:b.txt") == "/tmp/a\\\\:b.txt"
