import subprocess, sys
from pathlib import Path
sys.path.insert(0, ".")
import short as S

RUSH = "/home/lexoyo/2026-08-31 16-41-36.mp4"
SRT = "/home/lexoyo/Vidéos/Screencasts/2026-08-31 16-41-36_montage/deliverable/final.en.srt"
OUT = Path("shorts3/SHORT-3-layer-name.mp4")
F = S.FONT
start, end = S.snap(S.cues(SRT), 260.0, 305.0)
dur = end - start
TITLE = "The layer name is not the tag"

g = [
    f"color=c={S.BG}:s=1080x1920:d={dur}[bg]",
    f"[0:v]trim={start}:{end},setpts=PTS-STARTPTS,crop=430:300:0:80,scale=1080:754[layers]",
    f"[0:v]trim={start}:{end},setpts=PTS-STARTPTS,crop=660:300:1900:130,scale=1080:491[props]",
    "[bg][layers]overlay=0:250:shortest=1[a]",
    "[a][props]overlay=0:1040[b]",
    f"[b]drawbox=x=0:y=1015:w=1080:h=4:color={S.ACCENT}@0.6:t=fill[c]",
    f"[c]drawtext=fontfile={F}:text='{TITLE}':fontcolor=white:fontsize=54:x=(w-text_w)/2:y=95[d]",
    f"[d]drawbox=x=(iw-160)/2:y=180:w=160:h=5:color={S.ACCENT}:t=fill[e]",
    f"[e]drawtext=fontfile={F}:text='{S.CTA}':fontcolor={S.MUTED}:fontsize=32:x=(w-text_w)/2:y=1855[v]",
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
print(f"short 3 : rush {start:.1f}→{end:.1f}s  ({dur/S.SPEED:.1f}s finales), deux vignettes")
