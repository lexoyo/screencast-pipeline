"""The whole Shotcut project, built end to end with the probes stubbed out.

The other tests check its pieces. This one checks that they still assemble: a well-formed
document, the tracks in the order the transitions index them, the slides and the music
wired in. It pins the project as it is, so a cleanup that moves code around cannot
change what melt plays without a test saying so.
"""

from types import SimpleNamespace
from xml.dom import minidom

import pytest

from screencast import shotcut
from screencast.episode import Episode
from screencast.slideplan import build as build_layout
from screencast.timeline import parse

CHANNEL = {"name": "Alex Hoyau", "handle": "@AlexHoyau", "programme_label": "Au programme"}


def _episode(tmp_path, *, music: bool, face: bool = True) -> Episode:
    (tmp_path / "screen.mkv").write_bytes(b"")
    if face:
        (tmp_path / "face.mkv").write_bytes(b"")
    else:
        (tmp_path / ".screen-only").write_text("no camera\n")
    cfg = SimpleNamespace(
        screen_file="screen.mkv", face_file="face.mkv", mic_from_face=False,
        out_w=1920, out_h=1080, out_fps=30, zoom_scale=1.4, music=music, audio_lufs=-16.0,
    )
    return Episode(root=tmp_path, cfg=cfg)


@pytest.fixture
def probes(monkeypatch):
    monkeypatch.setattr(shotcut, "ffprobe_duration", lambda _path: 120.0)
    monkeypatch.setattr(shotcut, "ffprobe_dimensions", lambda _path: (1920, 1080))
    monkeypatch.setattr(shotcut, "camera_offset", lambda _ep: 0.5)
    monkeypatch.setattr(shotcut, "loudness_lufs", lambda *_: -20.0)
    drawn = []

    def render(kind, values, out, **_):
        drawn.append(kind)
        return out

    monkeypatch.setattr(shotcut.slides, "render", render)
    return drawn


def _plan():
    return parse({
        "language": "fr",
        "metadata": {"intro": {"title": "Un titre"}, "outro": {"title": "À bientôt"},
                     "chapters": [{"at": 20, "label": "Premier"}]},
        "timeline": [
            {"start": 0.0, "end": 30.0, "drop": False, "scene": "large"},
            {"start": 30.0, "end": 40.0, "drop": True, "scene": "large", "reason": "fumble"},
            {"start": 40.0, "end": 80.0, "drop": False, "scene": "ecran",
             "list_item": {"n": 1, "label": "Le rendu"}},
            {"start": 80.0, "end": 110.0, "drop": False, "scene": "serre"},
        ],
    })


def _tractor(xml: str):
    doc = minidom.parseString(xml)  # raises on a malformed project
    tractor = doc.getElementsByTagName("tractor")[0]
    tracks = [t.getAttribute("producer") for t in tractor.getElementsByTagName("track")]
    transitions = [
        (t.getAttribute("mlt_service"),
         {p.getAttribute("name"): p.firstChild.data for p in t.getElementsByTagName("property")})
        for t in tractor.getElementsByTagName("transition")
    ]
    return doc, tracks, transitions


def test_a_project_with_slides_and_music_assembles(tmp_path, probes):
    ep = _episode(tmp_path, music=True)
    for kind in ("intro", "outro"):
        (ep.work / "music" / kind).mkdir(parents=True)
        (ep.work / "music" / kind / "track.mp3").write_bytes(b"")
    plan = _plan()
    layout = build_layout(plan, plan.kept, channel=CHANNEL)

    doc, tracks, transitions = _tractor(shotcut.build(ep, plan, layout))

    assert tracks == ["black", "track_ecran", "track_large", "track_serre", "track_slides",
                      "track_audio", "track_music"]
    # the transitions index the tracks above: blends for the four picture tracks, then the
    # voice and the music mixed onto the background
    assert [(s, p["b_track"]) for s, p in transitions] == [
        ("frei0r.cairoblend", "1"), ("frei0r.cairoblend", "2"), ("frei0r.cairoblend", "3"),
        ("frei0r.cairoblend", "4"), ("mix", "5"), ("mix", "6"),
    ]
    assert sorted(probes) == sorted([c.kind for c in layout.cards]
                                    + [o.kind for o in layout.overlays])
    # the music under a card lands at the speech level: -16 target over a -20 measurement
    music = [p for p in doc.getElementsByTagName("producer")
             if p.getAttribute("id").startswith("music")]
    assert len(music) == 2
    assert 'name="level">4.0<' in music[0].toxml()
    # the list card blurs only the clips behind it, on their own producers
    assert any("_list0" in p.getAttribute("id") for p in doc.getElementsByTagName("chain"))


def test_a_screen_only_project_keeps_every_track(tmp_path, probes):
    ep = _episode(tmp_path, music=False, face=False)
    plan = _plan()

    _, tracks, transitions = _tractor(shotcut.build(ep, plan, None))

    assert tracks == ["black", "track_ecran", "track_large", "track_serre", "track_audio"]
    assert [(s, p["b_track"]) for s, p in transitions][-1] == ("mix", "4")
    assert probes == []
