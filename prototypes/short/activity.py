"""Où se passe l'action, sans rien savoir du logiciel filmé.

Le cadre d'un short ne peut pas être fixe : sur 45 secondes l'attention se déplace d'un
panneau à l'autre. Il ne peut pas non plus suivre le curseur en continu — c'est ce que
font les outils de reframe pour un visage qui marche, et transposé à une interface ça
donne un cadre qui tremble. Les outils d'auto-zoom de screencast procèdent par paliers :
un cadre tenu quelques secondes, puis une transition vers le suivant.

La zone d'action se déduit des pixels qui changent entre deux images. Le curseur seul en
fait bouger très peu ; une liste qui s'ouvre, un panneau qui se remplit, un champ qu'on
édite en font bouger beaucoup. Aucune connaissance de l'application n'est nécessaire.
"""
import subprocess, sys, json
import numpy as np

GW, GH = 192, 108          # la grille d'analyse, volontairement grossière
FPS = 4

def activity(video, start, duration, exclude=None):
    """Une carte d'activité par pas de temps, en grille GW x GH."""
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", str(start), "-t", str(duration), "-i", str(video),
         "-vf", f"fps={FPS},scale={GW}:{GH},format=gray", "-f", "rawvideo", "-"],
        capture_output=True, check=True).stdout
    frames = np.frombuffer(raw, np.uint8).reshape(-1, GH, GW).astype(np.int16)
    diffs = np.abs(np.diff(frames, axis=0))
    if exclude:                      # la webcam bouge en permanence : elle n'est pas l'action
        x, y, w, h = exclude
        gx, gy = int(x/1920*GW), int(y/1080*GH)
        gw, gh = int(w/1920*GW)+1, int(h/1080*GH)+1
        diffs[:, gy:gy+gh, gx:gx+gw] = 0
    return diffs

def windows(diffs, seconds=3.0):
    """Le centre de gravité de l'activité, fenêtre par fenêtre."""
    step = int(seconds * FPS)
    out = []
    for i in range(0, len(diffs), step):
        block = diffs[i:i+step].sum(axis=0).astype(float)
        if block.sum() < 1:
            out.append(None); continue
        block[block < np.percentile(block, 90)] = 0     # le bruit de fond ne vote pas
        ys, xs = np.nonzero(block)
        if len(xs) == 0:
            out.append(None); continue
        w = block[ys, xs]
        cx = float((xs * w).sum() / w.sum()) / GW * 1920
        cy = float((ys * w).sum() / w.sum()) / GH * 1080
        out.append((i / FPS, cx, cy, float(block.sum())))
    return out

if __name__ == "__main__":
    video, start, dur = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
    d = activity(video, start, dur, exclude=(1468, 778, 360, 270))
    for w in windows(d):
        if w is None:
            print("  (rien)"); continue
        t, cx, cy, mass = w
        print(f"  t+{t:5.1f}s   centre ≈ ({cx:6.0f}, {cy:5.0f})   activité {mass:9.0f}")


MIN_HOLD = 4.0        # un cadre tenu moins longtemps se lit comme un clignotement
SAME_SHOT = 320.0     # px : en deçà, c'est le même cadre qui respire, pas un autre

def shots(win, duration, min_mass=3000.0):
    """Les paliers de cadrage : (début, fin, centre). Le cadre saute, il ne glisse pas."""
    out = []
    for w in win:
        if w is None or w[3] < min_mass:
            continue                       # trop peu d'activité pour déplacer le cadre
        t, cx, cy, _ = w
        if out and abs(cx - out[-1][2]) < SAME_SHOT and abs(cy - out[-1][3]) < SAME_SHOT:
            continue                       # même zone : on prolonge le palier courant
        out.append([t, None, cx, cy])
    if not out:
        return [(0.0, duration, 960.0, 540.0)]
    out[0][0] = 0.0
    for i, s in enumerate(out):
        s[1] = out[i + 1][0] if i + 1 < len(out) else duration
    # un palier trop court est absorbé par le précédent
    merged = []
    for s in out:
        if merged and s[1] - s[0] < MIN_HOLD:
            merged[-1][1] = s[1]
        else:
            merged.append(s)
    # Un cadre d'ouverture bref part presque toujours sur une activité de transition — un
    # scroll, une fenêtre qui se ferme — pendant que la voix annonce déjà le vrai sujet.
    # Il vaut mieux ouvrir directement sur le cadre où le gros de l'extrait se passe.
    if len(merged) > 1:
        longest = max(merged, key=lambda s: s[1] - s[0])
        if merged[0] is not longest and (merged[0][1] - merged[0][0]) < 0.25 * duration:
            merged[1][0] = merged[0][0]
            merged.pop(0)
    return [(a, b, cx, cy) for a, b, cx, cy in merged]
