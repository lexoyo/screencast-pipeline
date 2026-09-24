"""The audio master pass of the melt render.

Written after the first full melt render of the 23/09 take: -15.8 LUFS against -16, and
peaks at +1.5 dBFS once AAC had encoded a mix MLT's limiter had held at -1.5. The target
and the ceiling come from config.env, and the ceiling is checked AFTER the encode.
"""

from types import SimpleNamespace

from screencast.master import loudnorm_filter, next_ceiling, parse_ebur128, parse_loudnorm
from screencast.shotcut import melt_command

SUMMARY = """
[Parsed_ebur128_0 @ 0x7f4680004ac0] t: 19.9 TARGET:-23 LUFS    M: -14.1 S: -15.0
[Parsed_ebur128_0 @ 0x7f4680004ac0] Summary:

  Integrated loudness:
    I:         -15.4 LUFS
    Threshold: -25.5 LUFS

  Loudness range:
    LRA:         5.2 LU
    Threshold: -35.5 LUFS
    LRA low:   -18.5 LUFS
    LRA high:  -13.4 LUFS

  True peak:
    Peak:       -1.4 dBFS
"""

MEASURED = {"input_i": "-15.82", "input_tp": "-1.20", "input_lra": "7.80",
            "input_thresh": "-26.10", "target_offset": "0.05"}


def test_the_summary_is_read_not_the_running_meter():
    assert parse_ebur128(SUMMARY) == {"I": -15.4, "LRA": 5.2, "TP": -1.4}


def test_the_second_pass_is_fed_the_first_ones_measurement():
    graph = loudnorm_filter(-16.0, -1.5, 11.0, MEASURED)
    assert graph.startswith("loudnorm=I=-16.0:TP=-1.50:LRA=11.0")
    assert "measured_I=-15.82" in graph and "measured_TP=-1.20" in graph
    assert "offset=0.05" in graph and graph.endswith("linear=true")


def test_the_measurement_block_is_the_last_json_in_stderr():
    text = 'noise {"a": 1}\n[Parsed_loudnorm_0]\n{\n "input_i" : "-15.82"\n}\n'
    assert parse_loudnorm(text) == {"input_i": "-15.82"}


def test_an_overshoot_lowers_the_next_ceiling_by_itself_and_a_margin():
    # AAC put the peak at -0.9 against a -1.5 ceiling: aim 0.6 + 0.3 lower
    assert round(next_ceiling(-1.5, -1.5, -0.9), 2) == -2.4


def test_melt_hands_the_mix_over_lossless():
    # an AAC out of melt would be encoded twice, and its overshoot measured as programme
    cfg = SimpleNamespace(melt_bin="melt-7", out_fps=30, draft_crf=20)
    cmd = [str(c) for c in melt_command(SimpleNamespace(cfg=cfg), "p.mlt", "mix.mkv")]
    assert "acodec=pcm_f32le" in cmd and "f=matroska" in cmd
    assert not any(c.startswith("acodec=aac") for c in cmd)
