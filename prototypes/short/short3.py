"""Short 3 : le cadre suit le sujet — les calques, puis les réglages.

La bascule est à +31 s, là où la voix passe de « the names you see in the layers » à
« because here you see in the settings, the tag name ». Deux cadres, une coupe franche.
"""
import subprocess, sys
from pathlib import Path
sys.path.insert(0, ".")
import short as S

RUSH = "/home/lexoyo/2026-08-31 16-41-36.mp4"
SRT = "/home/lexoyo/Vidéos/Screencasts/2026-08-31 16-41-36_montage/deliverable/final.en.srt"
OUT = Path("shorts3/SHORT-3-layer-name.mp4")
start, end = S.snap(S.cues(SRT), 260.0, 305.0)
TITLE = "The layer name is not the tag"

#      début, fin,  x,    y,   w,   h      (même ratio 0.838 pour les deux: 1080x1289)
SHOTS = [(0.0, 31.0,   0,  80, 430, 513),   # le panneau Layers
         (31.0, end-start, 1888, 40, 665, 794)]  # les réglages, tag name

parts, g = [], []
for i, (a, b, x, y, w, h) in enumerate(SHOTS):
    g.append(f"[0:v]trim={start+a}:{start+b},setpts=PTS-STARTPTS,"
             f"crop={w}:{h}:{x}:{y},scale=1080:1289,setsar=1[s{i}]")
    parts.append(f"[s{i}]")
g.append("".join(parts) + f"concat=n={len(parts)}:v=1:a=0[screen]")
g += [
    f"color=c={S.BG}:s=1080x1920:d={end-start}[bg]",
    "[bg][screen]overlay=0:230:shortest=1[b]",
    f"[b]drawtext=fontfile={S.FONT}:text='{TITLE}':fontcolor=white:fontsize=54:x=(w-text_w)/2:y=95[c]",
    f"[c]drawbox=x=(iw-160)/2:y=180:w=160:h=5:color={S.ACCENT}:t=fill[d]",
    f"[d]drawtext=fontfile={S.FONT}:text='{S.CTA}':fontcolor={S.MUTED}:fontsize=32:x=(w-text_w)/2:y=1855[v]",
    f"[0:a]atrim={start}:{end},asetpts=PTS-STARTPTS[a0]",
]
tmp = OUT.with_name("_tmp3.mp4")
subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", RUSH, "-filter_complex", ";".join(g),
                "-map", "[v]", "-map", "[a0]", "-c:v", "libx264", "-preset", "medium",
                "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
                "-r", "30", str(tmp)], check=True)
subs = OUT.with_suffix(".srt")
S.write_srt(S.cues(SRT), start, end, subs)
style = ("FontName=Inter,Fontsize=15,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
         "BorderStyle=1,Outline=2,Shadow=0,Alignment=2,MarginV=26,WrapStyle=0")
subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(tmp), "-filter_complex",
                f"[0:v]setpts=PTS/{S.SPEED},subtitles={subs}:force_style='{style}'[v];"
                f"[0:a]atempo={S.SPEED}[a]", "-map", "[v]", "-map", "[a]", "-c:v", "libx264",
                "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "160k", str(OUT)], check=True)
tmp.unlink(); subs.unlink()
print(f"short 3 : deux cadres, bascule à +31 s ({(end-start)/S.SPEED:.1f}s finales)")
