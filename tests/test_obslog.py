"""Reading the real start times out of an OBS log.

The fixtures are trimmed from actual logs — including the midnight case, which is what
broke the first implementation on a real shoot.
"""

import pytest

from screencast.obslog import OffsetUnknown, parse_log

SIMPLE = """\
01:20:57.454: ==== Recording Start ====
01:20:57.454: [ffmpeg muxer: 'simple_file_output'] Writing file '/home/x/Videos/take.mkv'...
01:20:57.642: [mp4 output: 'Source Record'] Writing Hybrid MP4/MOV file '/home/x/Videos/cam/take cam.mp4'...
01:31:58.321: Output 'Source Record': stopping
01:31:58.842: Output 'simple_file_output': stopping
"""


def test_offset_is_the_gap_between_the_two_starts():
    assert parse_log(SIMPLE, "take.mkv") == pytest.approx(0.188, abs=0.001)


# An evening session runs past midnight: the earlier lines have a LARGER clock value than
# the later ones. Comparing timestamps instead of file order gave 81367 s on a real log.
CROSSES_MIDNIGHT = """\
23:54:35.000: ==== Recording Start ====
23:54:35.100: [ffmpeg muxer: 'simple_file_output'] Writing file '/home/x/Videos/early.mkv'...
23:54:35.300: [mp4 output: 'Source Record'] Writing Hybrid MP4/MOV file '/home/x/Videos/cam/early cam.mp4'...
23:59:00.000: Output 'simple_file_output': stopping
01:20:57.454: ==== Recording Start ====
01:20:57.454: [ffmpeg muxer: 'simple_file_output'] Writing file '/home/x/Videos/late.mkv'...
01:20:57.642: [mp4 output: 'Source Record'] Writing Hybrid MP4/MOV file '/home/x/Videos/cam/late cam.mp4'...
"""


def test_a_log_that_crosses_midnight_still_reads_correctly():
    assert parse_log(CROSSES_MIDNIGHT, "late.mkv") == pytest.approx(0.188, abs=0.001)


def test_the_right_take_is_picked_when_a_log_holds_several():
    assert parse_log(CROSSES_MIDNIGHT, "early.mkv") == pytest.approx(0.200, abs=0.001)


FALSE_START = """\
01:20:53.000: [ffmpeg muxer: 'simple_file_output'] Writing file '/home/x/Videos/aborted.mkv'...
01:20:53.150: [mp4 output: 'Source Record'] Writing Hybrid MP4/MOV file '/home/x/Videos/cam/aborted cam.mp4'...
01:20:55.951: Output 'Source Record': stopping
01:20:57.454: [ffmpeg muxer: 'simple_file_output'] Writing file '/home/x/Videos/real.mkv'...
01:20:57.642: [mp4 output: 'Source Record'] Writing Hybrid MP4/MOV file '/home/x/Videos/cam/real cam.mp4'...
"""


def test_a_false_start_before_the_real_take_is_not_picked_up():
    # two-second aborted take, then the real one — exactly what a session log looks like
    assert parse_log(FALSE_START, "real.mkv") == pytest.approx(0.188, abs=0.001)


def test_an_unknown_recording_is_an_error_not_a_guess():
    with pytest.raises(OffsetUnknown, match="no 'Writing file' line"):
        parse_log(SIMPLE, "someone-elses-take.mkv")


NO_CAMERA = """\
01:20:57.454: [ffmpeg muxer: 'simple_file_output'] Writing file '/home/x/Videos/take.mkv'...
01:31:58.842: Output 'simple_file_output': stopping
"""


def test_a_take_shot_without_source_record_is_an_error():
    # shooting with the filter disabled produces no camera file at all; say so
    with pytest.raises(OffsetUnknown, match="no Source Record"):
        parse_log(NO_CAMERA, "take.mkv")


IMPLAUSIBLE = """\
01:20:57.454: [ffmpeg muxer: 'simple_file_output'] Writing file '/home/x/Videos/take.mkv'...
03:45:00.000: [mp4 output: 'Source Record'] Writing Hybrid MP4/MOV file '/home/x/Videos/cam/other cam.mp4'...
"""


def test_an_absurd_gap_is_refused_rather_than_applied():
    # a misread that shifts the picture by two hours must never reach the render
    with pytest.raises(OffsetUnknown, match="implausible"):
        parse_log(IMPLAUSIBLE, "take.mkv")
