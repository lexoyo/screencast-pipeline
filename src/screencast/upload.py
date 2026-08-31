"""The step-by-step for publishing, written into the deliverable.

Nothing here uploads anything, ever — that is Alex's call, every time, on every video.
What it does is remove the searching: the exact fields to fill, in the order YouTube asks
for them, with direct links to the pages where each setting lives. Those settings are
buried three menus deep and move around; a checklist that names them is worth more than
remembering where they were last time.
"""

from __future__ import annotations

from pathlib import Path

STUDIO = "https://studio.youtube.com"


def build(deliverable: Path, title: str, chapters: list[tuple[str, str]], language: str,
          channel_name: str = "", translated: str = "") -> str:
    """The publishing checklist for one finished video."""
    files = sorted(p.name for p in deliverable.glob("*") if p.is_file())
    subtitles = [f for f in files if f.endswith(".srt")]
    others = [f for f in subtitles if not f.endswith(f".{language}.srt")]

    lines = [
        f"# Publier — {title}",
        "",
        f"Tout est dans ce dossier : `{deliverable}`",
        "",
        "Rien n'a été envoyé nulle part. Cette liste sert à ne rien chercher.",
        "",
        "## 1. Téléverser la vidéo",
        "",
        f"→ {STUDIO}/channel/UC/videos/upload",
        "",
        "- glisser **final.mp4**",
        "- **titre** et **description** : copier depuis `metadata.txt` — le titre est la",
        "  première ligne, la description suit. Les chapitres sont déjà dedans, au format",
        "  que YouTube reconnaît (le premier à 0:00, sinon il ignore tout le jeu).",
        "- **miniature** : à faire, elle n'est pas produite par le pipeline.",
        "- **public** : « Non, ce n'est pas conçu pour les enfants ».",
        "",
        "## 2. Les sous-titres",
        "",
        "Dans l'onglet **Sous-titres** de la vidéo, pas dans les paramètres de la chaîne.",
        "",
        f"- langue de la vidéo : **{language}**",
        f"- téléverser `final.{language}.srt` (« sans minutage » — le fichier porte le sien)",
    ]
    for extra in others:
        code = extra.split(".")[-2]
        lines.append(f"- ajouter la langue **{code}** et téléverser `{extra}`")
    if translated:
        code = translated.split(".")[-2]
        lines += [
            "",
            "Dans la même page, chaque langue ajoutée a **son titre et sa description** :",
            f"les coller depuis `{translated}`. C'est ce que lit un spectateur qui arrive",
            f"d'une recherche en **{code}** — pas les sous-titres.",
        ]
    lines += [
        "",
        "## 3. Vérifier avant de publier",
        "",
        "- lire `QC.md` : il liste ce que la relecture a trouvé, et ce qui bloquerait",
        "  l'envoi (titre trop long, chapitres que YouTube ignorerait)",
        "- les chapitres apparaissent sous la barre de lecture (sinon : le premier n'est",
        "  pas à 0:00, ou il y en a moins de trois)",
        "- les liens de la description sont cliquables et mènent où il faut",
        "- lancer la lecture 10 secondes : image, son, et le premier carton",
        "",
        "## 4. Après publication",
        "",
        "- coller l'URL dans le handoff correspondant, avec le titre et la description",
        "  réellement retenus",
        "- pour un contenu Silex : l'annonce publique passe par **chris**, pas d'ici",
        "",
        "---",
        "",
        "## Dans le dossier",
        "",
    ]
    described = {
        "final.mp4": "la vidéo à publier",
        "project.mlt": "le projet Shotcut, si tu veux remonter (garde les rushes à côté)",
        "metadata.txt": "titre, description, liens, tags, chapitres",
        "QC.md": "ce que la relecture a trouvé, à lire avant de publier",
    }
    if translated:
        described[translated] = "les mêmes, traduits — pour la version par langue de la plateforme"
    for name in files:
        if name.endswith(".srt"):
            note = "sous-titres"
        elif name.startswith("transcript."):
            note = "le transcript rédigé, avec les liens — pour un billet ou le forum"
        else:
            note = described.get(name, "")
        lines.append(f"- `{name}`" + (f" — {note}" if note else ""))

    if chapters:
        lines += ["", "## Chapitres", ""]
        lines += [f"- {stamp} {label}" for stamp, label in chapters]

    return "\n".join(lines) + "\n"
