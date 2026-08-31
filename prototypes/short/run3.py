import json, sys
from pathlib import Path
sys.path.insert(0, "/tmp/claude-1000/-home-lexoyo---agents-media-agent/cc9404a9-fc90-435d-90e0-2c09783f32f6/scratchpad")
import short as S

RUSH = Path("/home/lexoyo/2026-08-31 16-41-36.mp4")
SRT = Path("/home/lexoyo/Vidéos/Screencasts/2026-08-31 16-41-36_montage/deliverable/final.en.srt")
OUT = Path("/tmp/claude-1000/-home-lexoyo---agents-media-agent/cc9404a9-fc90-435d-90e0-2c09783f32f6/scratchpad/shorts3")
OUT.mkdir(exist_ok=True)

SPECS = [
    {"n": 1, "start": 132.4, "end": 173.4, "title": "Set any tag name in Silex",
     "shots": [[0, 41, 1813, 0]]},
    {"n": 2, "start": 175.0, "end": 218.0, "title": "Configure a <label> element",
     "shots": [[0, 44, 1888, 40]], "frame": [665, 794]},
    {"n": 3, "start": 260.0, "end": 305.0, "title": "The layer name is not the tag"},
]

cs = S.cues(SRT)
for sp in SPECS:
    start, end = S.snap(cs, sp["start"], sp["end"])
    dur = end - start
    shots = sp.get("shots") or S.plan(RUSH, start, dur)
    out = OUT / f"short{sp['n']}.mp4"
    S.render(RUSH, SRT, start, end, sp["title"], shots, out, frame=sp.get("frame"))
    print(f"short{sp['n']} « {sp['title']} » : rush {start:.1f}→{end:.1f}s ({dur/S.SPEED:.1f}s finales)")
    for a, b, x, y in shots:
        xx, yy = S.keep_off_cam(int(x), int(y))
        print(f"    cadre {a:5.1f}→{b:5.1f}s  ({xx},{yy})")
