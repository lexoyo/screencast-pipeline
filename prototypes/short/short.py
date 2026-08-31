"""Shorts verticaux taillés dans le RUSH, pas dans le montage.

Le montage est en 1920x1080, le rush en 2560x1440 : cadrer serré dans le premier revient
à zoomer une image déjà réduite. On travaille donc sur l'original, où les coordonnées de
la webcam relevées dans la scène OBS s'appliquent en plus directement, sans conversion.

Le cadre suit l'action par paliers, et chaque palier se VALIDE sur une image fixe avant
qu'une seule seconde de vidéo ne soit encodée : un cadre est fixe pendant toute sa durée,
une frame suffit donc à le juger.
"""
import subprocess, sys, json
from pathlib import Path
import numpy as np

OUT_W, OUT_H = 1080, 1920
SRC_W, SRC_H = 2560, 1440
CAM = (1958, 1038, 480, 360)        # scène OBS: centre (2197.5,1217.5), bounds 640x360
FRAME_W, FRAME_H = 747, 892         # sans la webcam, la vignette gagne 240 px de haut
BG, ACCENT, MUTED = "0x1a1a2e", "0x8873fe", "0xa6a0c8"
CTA = "docs.silex.me/designer/structure/semantic-html"
FONT = "/usr/share/fonts/rsms-inter-vf-fonts/InterVariable.ttf"
GW, GH, FPS = 160, 90, 4
MIN_HOLD, SPEED = 6.0, 1.15
MOVE_MIN = 420       # px: en deçà, le cadre reste où il est plutôt que de sautiller

def diffs(video, start, dur):
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", str(start), "-t", str(dur), "-i", str(video),
         "-vf", f"fps={FPS},scale={GW}:{GH},format=gray", "-f", "rawvideo", "-"],
        capture_output=True, check=True).stdout
    f = np.frombuffer(raw, np.uint8).reshape(-1, GH, GW).astype(np.int16)
    d = np.abs(np.diff(f, axis=0))
    x, y, w, h = CAM                                  # la webcam bouge toujours: pas l'action
    d[:, int(y/SRC_H*GH):int((y+h)/SRC_H*GH)+1, int(x/SRC_W*GW):int((x+w)/SRC_W*GW)+1] = 0
    return d

def box(block):
    """La boîte englobante de l'activité, pas son centre de gravité.

    Le barycentre tirait le cadre vers le milieu d'une liste déroulante et laissait un
    tiers de l'image en blanc, tout en coupant le bord opposé. Ce qu'on veut, c'est la
    zone qui CONTIENT ce qui bouge.
    """
    hot = block >= np.percentile(block, 96)
    ys, xs = np.nonzero(hot)
    if len(xs) == 0:
        return None
    x0, x1 = xs.min()/GW*SRC_W, (xs.max()+1)/GW*SRC_W
    y0, y1 = ys.min()/GH*SRC_H, (ys.max()+1)/GH*SRC_H
    return x0, y0, x1, y1

def frame_for(b):
    """Une fenêtre FRAME_W x FRAME_H qui couvre la boîte, collée aux bords si besoin."""
    x0, y0, x1, y1 = b
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    x = int(max(0, min(cx - FRAME_W / 2, SRC_W - FRAME_W)))
    y = int(max(0, min(cy - FRAME_H / 2, SRC_H - FRAME_H)))
    # si l'action touche un bord, on s'y colle plutôt que de centrer sur du vide
    if x1 > SRC_W - 60: x = SRC_W - FRAME_W
    if x0 < 60: x = 0
    # La fenêtre webcam est incrustée dans l'écran par OBS : un cadre qui mord dessus
    # affiche le visage deux fois, dont une tronquée. On remonte le cadre au-dessus.
    cx, cy, cw, ch = CAM
    if x + FRAME_W > cx and y + FRAME_H > cy:
        y = min(y, cy - FRAME_H)
        if y < 0:                      # pas la place au-dessus: on se décale à gauche
            y = max(0, min(cy - FRAME_H, SRC_H - FRAME_H))
            x = min(x, max(0, cx - FRAME_W))
    return x, y

def plan(video, start, dur, window=5.0):
    d = diffs(video, start, dur)
    step = int(window * FPS)
    shots = []
    for i in range(0, len(d), step):
        block = d[i:i+step].sum(axis=0).astype(float)
        if block.sum() < 3000:
            continue
        b = box(block)
        if b is None:
            continue
        x, y = frame_for(b)
        t = i / FPS
        if shots and abs(x - shots[-1][2]) < MOVE_MIN and abs(y - shots[-1][3]) < MOVE_MIN:
            continue
        shots.append([t, None, x, y])
    if not shots:
        shots = [[0.0, None, (SRC_W-FRAME_W)//2, (SRC_H-FRAME_H)//2]]
    shots[0][0] = 0.0
    for i, s in enumerate(shots):
        s[1] = shots[i+1][0] if i+1 < len(shots) else dur
    merged = []
    for s in shots:
        if merged and s[1] - s[0] < MIN_HOLD:
            merged[-1][1] = s[1]
        else:
            merged.append(s)
    if len(merged) > 1:
        longest = max(merged, key=lambda s: s[1]-s[0])
        if merged[0] is not longest and merged[0][1]-merged[0][0] < 0.25*dur:
            merged[1][0] = merged[0][0]; merged.pop(0)
    return merged

def keep_off_cam(x, y):
    """Le cadre est collé en haut de l'écran, et ne mord jamais sur la webcam.

    Décision d'Alex : le haut de l'interface — barre d'outils, onglets, en-tête du panneau
    — doit rester visible, et ce qui tombe hors cadre en bas n'a pas d'importance. Centrer
    verticalement sur l'activité coupait systématiquement ce haut-là.
    """
    y = 0
    cx, cy, cw, ch = CAM
    if x + FRAME_W > cx and y + FRAME_H > cy:
        y = max(0, min(y, cy - FRAME_H))
    return x, y


def compose(video, t, x, y, title, out, subtitle=""):
    """Une image de validation : exactement la composition du short, à l'instant t."""
    x, y = keep_off_cam(x, y)
    g = [
        f"color=c={BG}:s={OUT_W}x{OUT_H}[bg]",
        f"[0:v]crop={FRAME_W}:{FRAME_H}:{x}:{y},scale={OUT_W}:1290[screen]",
        "[bg][screen]overlay=0:230:shortest=1[b]",
        f"[b]drawtext=fontfile={FONT}:text='{title}':fontcolor=white:fontsize=58:x=(w-text_w)/2:y=95[c]",
        f"[c]drawbox=x=(iw-160)/2:y=180:w=160:h=5:color={ACCENT}:t=fill[d]",
        f"[d]drawtext=fontfile={FONT}:text='{subtitle}':fontcolor=white:fontsize=50:"
        f"x=(w-text_w)/2:y=1660:shadowcolor=black:shadowx=3:shadowy=3[e]",
        f"[e]drawtext=fontfile={FONT}:text='{CTA}':fontcolor={MUTED}:"
        f"fontsize=32:x=(w-text_w)/2:y=1855[out]",
    ]
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(t), "-i", str(video),
                    "-filter_complex", ";".join(g), "-map", "[out]", "-frames:v", "1",
                    str(out)], check=True)

SRT_OFFSET = 6.0   # le montage a inséré un carton: srt(montage) = rush + 6


def cues(srt):
    def secs(ts):
        h, m, rest = ts.split(":"); s, ms = rest.split(",")
        return int(h)*3600 + int(m)*60 + int(s) + int(ms)/1000
    out = []
    for b in Path(srt).read_text().strip().split("\n\n"):
        L = b.split("\n")
        if len(L) >= 3:
            a, _, z = L[1].partition(" --> ")
            out.append((secs(a) - SRT_OFFSET, secs(z) - SRT_OFFSET, " ".join(L[2:]).strip()))
    return out


def snap(cs, start, end):
    return (min(cs, key=lambda c: abs(c[0]-start))[0], min(cs, key=lambda c: abs(c[1]-end))[1])


def write_srt(cs, start, end, out):
    def stamp(t):
        t = max(0.0, t) / SPEED
        return f"{int(t//3600):02d}:{int((t%3600)//60):02d}:{int(t%60):02d},{int(round((t-int(t))*1000)):03d}"
    blocks = [f"{i}\n{stamp(a-start)} --> {stamp(min(z,end)-start)}\n{t}"
              for i, (a, z, t) in enumerate((c for c in cs if c[1] > start and c[0] < end), 1)]
    Path(out).write_text("\n\n".join(blocks) + "\n")


def render(video, srt, start, end, title, shots, out, frame=None, sub=''):
    fw, fh = frame or (FRAME_W, FRAME_H)
    graph, parts = [], []
    for i, (a, b, x, y) in enumerate(shots):
        cx, cy, _, _ = CAM
        y = int(y)
        if int(x) + fw > cx and y + fh > cy:
            y = max(0, min(y, cy - fh))
        x = int(x)
        graph.append(f"[0:v]trim={start+a}:{start+b},setpts=PTS-STARTPTS,"
                     f"crop={fw}:{fh}:{x}:{y},scale={OUT_W}:1289[s{i}]")
        parts.append(f"[s{i}]")
    graph.append("".join(parts) + f"concat=n={len(parts)}:v=1:a=0[screen]")
    graph += [
        f"color=c={BG}:s={OUT_W}x{OUT_H}:d={end-start}[bg]",
        "[bg][screen]overlay=0:230:shortest=1[b]",
        f"[b]drawtext=fontfile={FONT}:text='{title}':fontcolor=white:fontsize=58:x=(w-text_w)/2:y=95[c]",
        f"[c]drawbox=x=(iw-160)/2:y=180:w=160:h=5:color={ACCENT}:t=fill[d]",
        f"[d]drawtext=fontfile={FONT}:text='{CTA}':fontcolor={MUTED}:fontsize=32:"
        f"x=(w-text_w)/2:y=1855[v]",
        f"[0:a]atrim={start}:{end},asetpts=PTS-STARTPTS[a0]",
    ]
    tmp = Path(out).with_name("_tmp_" + Path(out).name)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-filter_complex",
                    ";".join(graph), "-map", "[v]", "-map", "[a0]", "-c:v", "libx264",
                    "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "160k", "-r", "30", str(tmp)], check=True)
    subs = Path(out).with_suffix(".srt")
    write_srt(cues(srt), start, end, subs)
    style = ("FontName=Inter,Fontsize=15,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
             "BorderStyle=1,Outline=2,Shadow=0,Alignment=2,MarginV=26,WrapStyle=0")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(tmp), "-filter_complex",
                    f"[0:v]setpts=PTS/{SPEED},subtitles={subs}:force_style='{style}'[v];"
                    f"[0:a]atempo={SPEED}[a]", "-map", "[v]", "-map", "[a]", "-c:v", "libx264",
                    "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "160k", str(out)], check=True)
    tmp.unlink()


if __name__ == "__main__":
    a = json.loads(sys.argv[1])
    rush = Path("/home/lexoyo/2026-08-31 16-41-36.mp4")
    start, dur = a["start"], a["end"] - a["start"]
    shots = a.get('shots') or plan(rush, start, dur)
    out = Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
    print(f"{len(shots)} cadrage(s) pour {dur:.1f}s de rush :")
    for i, (t0, t1, x, y) in enumerate(shots, 1):
        mid = start + (t0 + t1) / 2
        png = out / f"cadre{i}.png"
        compose(rush, mid, x, y, a["title"], png, a.get("sub", ""))
        print(f"  cadre {i} : {t0:5.1f} → {t1:5.1f}s  fenêtre ({x},{y})  -> {png.name}")
