"""The music track of the Shotcut project.

Written after a real episode crashed here: `_volume_filter` was still reading a
`Bed.volume` that had stopped existing when levels moved to measured LUFS. No test built a
project *with* music, so nothing caught it — the whole run went through, then died on the
last stage with the render already done.
"""

from pathlib import Path

from screencast.music import Bed
from screencast.shotcut import (
    Clip,
    _entry,
    _fade_filter,
    _music_producers,
    _music_track,
    _slide_track,
    _volume_filter,
    audio_filters,
    av_filters,
    body_clips,
    hold_last_card,
    parse_chain,
    producer_id,
    split_windows,
)
from screencast.timeline import KeptSegment

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
    # `out` is the last frame played: 4 s from 6 s at 30 fps ends on frame 299
    assert 'out="00:00:09.967"' in row


def test_no_music_means_no_rows():
    assert _music_track([]) == []
    assert _music_producers([]) == ""


def test_a_bed_fades_in_and_out_like_the_export():
    # music.FADE_IN and FADE_OUT: 0.5 s in, 1.2 s out
    xml = _music_producers([INTRO])
    assert 'name="level">0=-60;15=0;143=0;179=-60' in xml


# --- frames, the voice chain, the list cards ---------------------------------------

MEASURED = (
    "highpass=f=80,afftdn=nf=-25:tn=1,loudnorm=I=-16.0:TP=-1.5:LRA=11.0:measured_I=-16.29"
    ":measured_TP={tp}:measured_LRA=8.80:measured_thresh=-26.78:offset=0.28:linear=true"
)


def seg(start, end, scene, final_start):
    return KeptSegment(start=start, end=end, scene=scene, final_start=final_start)


def test_an_entry_ends_on_its_last_frame_not_after_it():
    # MLT's `out` is inclusive: out=1.000 would play 31 frames for a one-second clip, and
    # thirty clips drifted a second against final.mp4
    assert _entry("x", 30, 30, 30) == '    <entry producer="x" in="00:00:01.000" out="00:00:01.967"/>'


def test_the_positional_options_measure_writes_are_named():
    assert parse_chain("eq=brightness=0.011:contrast=1.06,unsharp=3:3:0.3") == [
        ("eq", {"brightness": "0.011", "contrast": "1.06"}),
        ("unsharp", {"luma_msize_x": "3", "luma_msize_y": "3", "luma_amount": "0.3"}),
    ]


def test_the_camera_correction_goes_through_unchanged():
    xml = "".join(av_filters("eq=brightness=0.011:saturation=1.35,unsharp=3:3:0.3"))
    assert "avfilter.eq" in xml and 'name="av.saturation">1.35' in xml
    assert 'name="av.luma_amount">0.3' in xml


def test_loudnorm_that_can_stay_linear_is_a_constant_gain():
    xml = "".join(audio_filters(MEASURED.format(tp="-6.0")))
    assert 'name="level">0.29' in xml
    assert "dynamic_loudness" not in xml
    assert "avfilter.loudnorm" not in xml  # accepted by MLT, and a no-op there


def test_loudnorm_that_cannot_stay_linear_normalises_dynamically_like_ffmpeg():
    # a peak at +1.54 raised by 0.29 dB cannot fit under -1.5: ffmpeg goes dynamic too
    xml = "".join(audio_filters(MEASURED.format(tp="1.54")))
    assert "dynamic_loudness" in xml and 'name="target_loudness">-16.0' in xml
    assert 'name="window">10<' in xml  # 3 s pumps the pauses up
    assert 'name="av.limit">0.8414' in xml
    assert xml.index("avfilter.highpass") < xml.index("avfilter.afftdn") < xml.index("dynamic")


def test_segments_land_where_the_concat_puts_them_with_the_intro_gap():
    kept = [seg(0, 2, "large", 0), seg(3, 4, "ecran", 2), seg(10, 12, "serre", 3)]
    clips = body_clips(kept, fps=30, offset=0.0, has_face=True, mic_from_face=False,
                       gap_after=0, gap_length=6.0)
    video = [c for c in clips if c.track != "audio"]
    assert [(c.track, c.at, c.length) for c in video] == [
        ("large", 0, 60), ("ecran", 240, 30), ("serre", 270, 60)]
    assert [c.src_in for c in video] == [0, 90, 300]


def test_the_words_before_the_camera_started_play_on_its_frozen_first_frame():
    clips = body_clips([seg(0, 2, "large", 0)], fps=30, offset=0.2, has_face=True,
                       mic_from_face=False)
    lead, rest = [c for c in clips if c.track == "large"]
    assert (lead.source, lead.at, lead.length) == ("face_lead", 0, 6)
    assert (rest.source, rest.src_in, rest.at, rest.length) == ("face_v", 0, 6, 54)


def test_a_screen_only_shoot_never_shows_a_camera_track():
    clips = body_clips([seg(0, 2, "large", 0)], fps=30, offset=0.0, has_face=False,
                       mic_from_face=False)
    assert {c.track for c in clips} == {"ecran", "audio"}


def test_a_list_card_cuts_the_shot_and_blurs_only_its_span():
    clip = Clip("ecran", "screen_v", src_in=1000, at=100, length=200)
    before, behind, after = split_windows([clip], [(150, 250)])
    assert (before.at, before.length, before.window) == (100, 50, None)
    assert (behind.at, behind.length, behind.src_in, behind.window) == (150, 100, 1050, 0)
    assert (after.at, after.length, after.src_in) == (250, 50, 1150)
    assert producer_id(behind) == "screen_v_ecran_list0"
    assert producer_id(before) == "screen_v"


def test_the_audio_is_never_cut_by_a_list_card():
    clip = Clip("audio", "screen_a", 0, 0, 300)
    assert split_windows([clip], [(100, 200)]) == [clip]


def test_an_overlay_fades_its_alpha_only():
    xml = _fade_filter(105, 8)
    assert 'name="alpha">0=0;8=1;96=1;104=0' in xml
    assert 'name="level">1<' in xml  # the card must not darken as it fades


def test_the_outro_holds_while_its_music_fades_instead_of_cutting_to_black():
    # cards first (index 0 = intro, 1 = outro), then an overlay ending at the same frame
    entries = [(0, 10.0, 16.0), (1, 100.0, 104.0), (2, 102.0, 104.0)]
    held = hold_last_card(entries, cards=2, video_end=3120, music_end=3162, fps=30)
    assert held[1] == (1, 100.0, 105.4)
    assert held[0] == entries[0]  # the intro sits mid-video
    assert held[2] == entries[2]  # an overlay is never stretched


def test_nothing_is_held_when_the_music_stops_with_the_picture():
    entries = [(0, 100.0, 104.0)]
    assert hold_last_card(entries, cards=1, video_end=3120, music_end=3000, fps=30) == entries


def test_slides_never_overlap_by_a_rounding_frame():
    # 1.02 s rounds to frame 31 and 1.01 s to frame 30: the second slide starts where the
    # first one ends rather than one frame inside it
    rows = _slide_track([(0, 0.0, 1.02), (1, 1.01, 2.0)], fps=30)
    assert "<blank" not in "".join(rows)
    assert 'out="00:00:01.000"' in rows[0]  # frames 0..30
    assert 'out="00:00:00.933"' in rows[1]  # frames 31..59: 29 frames
