"""Config parsing and validation — a typo must name itself, not crash mid-render."""

import pytest

from screencast.config import ConfigError, load, parse_env_file


def test_parse_strips_quotes_and_trailing_comments():
    parsed = parse_env_file('FORCE_LANG="fr"        # channel is FR first\n')
    assert parsed["FORCE_LANG"] == "fr"


def test_parse_ignores_comments_and_blank_lines():
    parsed = parse_env_file("# a comment\n\nOUT_W=1920\n")
    assert parsed == {"OUT_W": "1920"}


def test_parse_keeps_a_hash_inside_quotes():
    # a colour would be lost if the comment stripper ran before the quote parser
    assert parse_env_file('THEME_BG="#0d1b2a"')["THEME_BG"] == "#0d1b2a"


def test_parse_handles_values_that_look_like_flags():
    assert parse_env_file('SILENCE_DB="-30dB"')["SILENCE_DB"] == "-30dB"


def test_parse_rejects_an_unbalanced_quote():
    with pytest.raises(ConfigError, match="cannot parse"):
        parse_env_file('TITLE="unterminated\n')


MINIMAL = """
WHISPER_BIN="/opt/whisper.cpp/build/bin/whisper-cli"
WHISPER_MODEL="$HOME/models/whisper/ggml-small.bin"
"""


def _write(tmp_path, text):
    path = tmp_path / "config.env"
    path.write_text(text)
    return path


def test_load_applies_defaults(tmp_path):
    cfg = load(_write(tmp_path, MINIMAL))
    assert cfg.out_w == 1920
    assert cfg.mic_source == "screen"
    assert cfg.claude_bin == "claude"


def test_load_expands_home_in_the_brain_command(tmp_path):
    # CLAUDE_BIN may point at a wrapper script; $HOME there must resolve like anywhere else
    cfg = load(_write(tmp_path, MINIMAL + 'CLAUDE_BIN="$HOME/bin/brain.sh"\n'))
    assert "$HOME" not in cfg.claude_bin
    assert cfg.claude_bin.endswith("/bin/brain.sh")


def test_load_expands_home(tmp_path):
    cfg = load(_write(tmp_path, MINIMAL))
    assert "$HOME" not in str(cfg.whisper_model)
    assert cfg.whisper_model.is_absolute()


def test_whisper_dtw_model_strips_the_ggml_wrapping(tmp_path):
    # whisper-cli's -dtw flag wants "small", not "ggml-small.bin"
    cfg = load(_write(tmp_path, MINIMAL))
    assert cfg.whisper_dtw_model == "small"


def test_the_large_variants_are_spelled_with_dots(tmp_path):
    # the file is ggml-large-v3-turbo.bin, the preset is large.v3.turbo, and getting it
    # wrong is `error: unknown DTW preset` + exit(3) — no alignment, no word timings
    text = MINIMAL.replace("ggml-small.bin", "ggml-large-v3-turbo.bin")
    assert load(_write(tmp_path, text)).whisper_dtw_model == "large.v3.turbo"


def test_a_dotted_english_model_is_left_alone(tmp_path):
    # ggml-small.en.bin already matches the preset table
    text = MINIMAL.replace("ggml-small.bin", "ggml-small.en.bin")
    assert load(_write(tmp_path, text)).whisper_dtw_model == "small.en"


def test_missing_required_setting_names_it(tmp_path):
    with pytest.raises(ConfigError, match="WHISPER_MODEL"):
        load(_write(tmp_path, 'WHISPER_BIN="/usr/bin/whisper-cli"\n'))


def test_a_typo_in_a_number_names_the_setting(tmp_path):
    with pytest.raises(ConfigError, match="OUT_W"):
        load(_write(tmp_path, MINIMAL + 'OUT_W="192O"\n'))  # letter O, not zero


def test_bad_mic_source_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match="MIC_SOURCE"):
        load(_write(tmp_path, MINIMAL + 'MIC_SOURCE="webcam"\n'))


def test_bad_pip_corner_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match="PIP_CORNER"):
        load(_write(tmp_path, MINIMAL + 'PIP_CORNER="middle"\n'))


def test_zoom_scale_must_actually_zoom(tmp_path):
    with pytest.raises(ConfigError, match="ZOOM_SCALE"):
        load(_write(tmp_path, MINIMAL + 'ZOOM_SCALE="1.0"\n'))


def test_overrides_win_over_the_file(tmp_path):
    # nouvelle-video.sh knows the real container; config.env only holds a default
    cfg = load(
        _write(tmp_path, MINIMAL + 'SCREEN_FILE="screen.mkv"\n'),
        overrides={"SCREEN_FILE": "screen.mp4"},
    )
    assert cfg.screen_file == "screen.mp4"


def test_empty_overrides_do_not_erase_the_file_value(tmp_path):
    cfg = load(
        _write(tmp_path, MINIMAL + 'SCREEN_FILE="screen.mkv"\n'), overrides={"SCREEN_FILE": ""}
    )
    assert cfg.screen_file == "screen.mkv"


def test_a_missing_config_file_says_what_to_do(tmp_path):
    with pytest.raises(ConfigError, match="config.env.example"):
        load(tmp_path / "nope.env")


def test_music_is_on_unless_turned_off(tmp_path):
    assert load(_write(tmp_path, MINIMAL)).music is True
    assert load(_write(tmp_path, MINIMAL + 'MUSIC="off"\n')).music is False


def test_music_accepts_the_usual_spellings(tmp_path):
    for on in ("on", "true", "YES", "1"):
        assert load(_write(tmp_path, MINIMAL + f'MUSIC="{on}"\n')).music is True
    for off in ("off", "false", "NO", "0"):
        assert load(_write(tmp_path, MINIMAL + f'MUSIC="{off}"\n')).music is False


def test_a_music_value_that_is_neither_names_itself(tmp_path):
    # the failure this avoids: MUSIC="maybe" quietly reading as False, and a video that
    # was meant to have music shipping silent
    with pytest.raises(ConfigError, match="must be on or off"):
        load(_write(tmp_path, MINIMAL + 'MUSIC="maybe"\n'))
