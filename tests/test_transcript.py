"""Reading subtitles back, and the links block appended to the description."""

from screencast.transcript import links_section, parse_srt

SRT = """1
00:00:00,000 --> 00:00:04,120
Bonjour et bienvenue

2
00:00:04,120 --> 00:00:09,500
aujourd'hui je vais vous parler
de Jan

3
00:01:02,000 --> 00:01:05,750
c'est parti
"""


def test_cues_are_read_with_their_timings():
    cues = parse_srt(SRT)
    assert len(cues) == 3
    assert cues[0].start == 0.0
    assert cues[0].end == 4.12


def test_a_cue_on_two_lines_becomes_one_string():
    # subtitles wrap for the screen; a document does not care
    assert parse_srt(SRT)[1].text == "aujourd'hui je vais vous parler de Jan"


def test_minutes_and_hours_are_read_correctly():
    assert parse_srt(SRT)[2].start == 62.0


def test_a_malformed_block_is_skipped_not_fatal():
    broken = SRT + "\n4\nnot a timestamp\nsome text\n"
    assert len(parse_srt(broken)) == 3


def test_an_empty_file_gives_no_cues():
    assert parse_srt("") == []


def test_the_links_block_is_timestamped_and_ordered():
    block = links_section([
        {"at": 120, "name": "Shotcut", "url": "https://shotcut.org"},
        {"at": 30, "name": "Jan", "url": "https://jan.ai"},
    ])
    lines = block.splitlines()
    assert lines[1].startswith("0:30")
    assert lines[2].startswith("2:00")


def test_a_link_without_a_url_is_still_listed():
    # the model is told to leave a URL empty rather than invent one; knowing what to
    # search for is most of the value, and a wrong link ships unchecked
    block = links_section([{"at": 10, "name": "un outil obscur", "url": ""}])
    assert "un outil obscur" in block
    assert "http" not in block


def test_no_links_means_no_block():
    assert links_section([]) == ""
