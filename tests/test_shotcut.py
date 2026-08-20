"""The music track of the Shotcut project.

Written after a real episode crashed here: `_volume_filter` was still reading a
`Bed.volume` that had stopped existing when levels moved to measured LUFS. No test built a
project *with* music, so nothing caught it — the whole run went through, then died on the
last stage with the render already done.
"""

from pathlib import Path

from screencast.music import Bed
from screencast.shotcut import _music_producers, _music_track, _volume_filter

INTRO = Bed(start=0.0, end=6.0, track=Path("/m/intro.mp3"), source_offset=0.0, gain_db=4.4)
BED = Bed(start=30.0, end=36.0, track=Path("/m/bed.mp3"), source_offset=0.0, gain_db=-13.6)
BED2 = Bed(start=60.0, end=64.0, track=Path("/m/bed.mp3"), source_offset=6.0, gain_db=-12.0)


def test_a_gain_is_written_as_decibels_unchanged():
    # it is measured in LUFS against the speech target, so it is already dB
    assert 'name="level">4.4' in _volume_filter(4.4)
    assert 'name="level">-13.6' in _volume_filter(-13.6)


def test_each_bed_carries_its_own_level():
    # the card sits at speech level, the bed under speech far below: one shared filter on
    # the playlist would play the whole track at whichever level came first
    xml = _music_producers([INTRO, BED])
    assert 'name="level">4.4' in xml
    assert 'name="level">-13.6' in xml


def test_two_beds_on_one_file_get_their_own_producer():
    # a filter attaches to a producer in MLT, so sharing one would force a shared level
    xml = _music_producers([BED, BED2])
    assert xml.count('id="music') == 2
    assert xml.count("/m/bed.mp3") == 2


def test_music_producers_carry_no_video():
    assert 'name="video_index">-1' in _music_producers([INTRO])


def test_an_entry_points_at_the_producer_built_from_the_same_bed():
    beds = [INTRO, BED, BED2]
    entries = "\n".join(_music_track(beds))
    producers = _music_producers(beds)
    for index in range(len(beds)):
        assert f'producer="music{index}"' in entries
        assert f'id="music{index}"' in producers


def test_silence_is_held_by_blanks_between_beds():
    rows = _music_track([INTRO, BED])
    assert rows[0].startswith("    <entry")
    assert "<blank" in rows[1]
    assert rows[2].startswith("    <entry")


def test_a_bed_reads_its_own_slice_of_the_file():
    # source_offset is a position inside the mp3, not on the timeline
    row = _music_track([BED2])[1]
    assert 'in="00:00:06.000"' in row
    assert 'out="00:00:10.000"' in row


def test_no_music_means_no_rows():
    assert _music_track([]) == []
    assert _music_producers([]) == ""
