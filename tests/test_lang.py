"""The deliverable's two languages — the pair that used to be guessed in three places."""

from screencast import lang
from screencast.config import load

MINIMAL = '''
WHISPER_BIN="/opt/whisper.cpp/build/bin/whisper-cli"
WHISPER_MODEL="$HOME/models/whisper/ggml-small.bin"
'''


def _write(tmp_path, text):
    path = tmp_path / "config.env"
    path.write_text(text)
    return path


def test_the_second_language_of_a_french_video_is_english():
    assert lang.target("fr") == "en"


def test_the_second_language_of_an_english_video_is_french():
    # The Silex docs shoot in English: translating them to English produced a duplicate
    # metadata file and no French one, on a documentation set whose FR mirror is required.
    assert lang.target("en") == "fr"


def test_an_undetected_language_falls_back_rather_than_naming_a_file_auto():
    assert lang.spoken("auto") == "en"
    assert lang.spoken("") == "en"
    assert lang.target("auto") == "fr"


def test_a_links_heading_is_written_in_the_language_of_its_description():
    assert lang.links_label("en") == "Projects mentioned"
    assert lang.links_label("fr") == "Projets mentionnés"


def test_forcing_auto_means_no_forced_language(tmp_path):
    # `--lang auto` asks whisper to decide; if "auto" leaked through as a language it would
    # be written into lang.txt and end up as the name of a subtitle file.
    cfg = load(_write(tmp_path, MINIMAL + 'FORCE_LANG="auto"\n'))
    assert cfg.forced_lang == ""


def test_a_forced_language_is_kept(tmp_path):
    assert load(_write(tmp_path, MINIMAL + 'FORCE_LANG="en"\n')).forced_lang == "en"


def test_the_harness_language_wins_over_the_model():
    # the EDL field is asked for in a prompt and validated nowhere; FORCE_LANG and lang.txt
    # are measured
    assert lang.resolve("fr", "en") == "fr"


def test_the_model_fills_in_when_the_harness_does_not_know():
    assert lang.resolve("auto", "fr") == "fr"
    assert lang.resolve("", "fr") == "fr"


def test_neither_knowing_falls_back_rather_than_inventing():
    assert lang.resolve("auto", "auto") == "en"
    assert lang.resolve("", "") == "en"


def test_a_french_shoot_whose_edl_forgot_the_language_stays_french():
    # the regression this pins: a missing "language" made target() say "fr", so French
    # metadata was translated into French and UPLOAD.md named the wrong primary subtitle
    spoken = lang.resolve("fr", "auto")
    assert spoken == "fr"
    assert lang.target(spoken) == "en"
    assert lang.links_label(spoken) == "Projets mentionnés"
