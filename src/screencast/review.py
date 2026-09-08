"""Read the edit as text, before paying for the render.

The montage brain decides from the words and nothing else — no video, no audio. So the
one place its decision can be checked cheaply is the words: reassemble what the video
will say once the cuts are applied, put back next to it what disappeared, and look.

Today that check happens by watching `final.mp4`, which costs a render, a second
transcription, the music, and fourteen minutes of attention. It is also the wrong medium:
a decision taken on text is verified on a picture. Twice, on the same rush, two different
models cut a passage Alex wanted to keep, and both times it was found by watching the
result.

Two passes, as in `qc`, because they catch different things.

**Mechanical checks** compare each cut against the reason the model gave for it. That is
verifiable without asking anybody: a cut labelled `repeat` whose words appear nowhere
around it is not a repetition, and a `filler` that contains a finished sentence is not a
filler. This is the same trick `cuts.has_measured_silence` already plays on the audio —
it refuses a `silence` the signal never measured. Here the evidence is the transcript
instead of the waveform.

**An editorial pass** is a separate process reading the assembled text, for what no rule
can decide: does a cut remove a result, a conclusion, a step of a procedure — and does a
junction leave a sentence broken.

Neither pass judges the words themselves. The text is whisper's, not Alex's: a spelling
that looks wrong is a transcription artefact, and correcting it is not this stage's job.
"""

from __future__ import annotations

import bisect
import json
import textwrap
from dataclasses import dataclass
from math import ceil
from pathlib import Path

from .episode import Episode
from .qc import ORDER, Issue, blocking, editorial
from .shell import log
from .timecode import youtube_timecode
from .timeline import Chapter, Edl, Span

# Punctuation stripped before two words are compared. Accents stay: they are part of the
# word in French, and "repete" must not match "répète" by accident.
EDGE_PUNCT = "«»\"'“”‘’.,;:!?…()[]{}—–- "
SENTENCE_END = (".", "!", "?")
# Not a sentence end: trailing dots are how whisper writes a phrase left hanging, which is
# the definition of a false start. Counting them as "finished" accused two real cuts —
# "permet d'écrire du..." and "cette... Trust and execute, oui, oui, oui," — of removing a
# sentence that was precisely never finished.
ELLIPSIS = ("…", "..")

# Thresholds, calibrated on the seven episodes shot so far rather than chosen a priori.
# They do not say whether a cut is good — they say whether the label the model put on it
# describes what it actually removed.
FILLER_MAX_SECONDS = 2.0
FILLER_MAX_WORDS = 6
FALSESTART_MAX_SECONDS = 5.0
FUMBLE_MAX_SECONDS = 15.0
# Past this, a single cut is not an edit any more, it is a section being deleted. This is
# the only mechanical check allowed to stop the run.
SECTION_SECONDS = 30.0

CONTEXT_WORDS = 25
"""How much kept text goes around each cut in the model's payload.

Enough to tell whether the sentence survives the junction, small enough that the whole
payload stays a few thousand tokens — the montage call already costs fifty thousand, and
this one has no reason to."""


@dataclass(frozen=True)
class Cut:
    """One dropped span, with its words and the kept text on either side."""

    span: Span
    words: list[dict]
    before: list[dict]
    after: list[dict]
    final_at: float
    """Where the junction lands in the edited video — the cut itself has no duration there."""

    @property
    def text(self) -> str:
        return " ".join(w["text"] for w in self.words)


def normalize(word: str) -> str:
    """Fold a word to what two occurrences of it have in common.

    French elision is dropped — "qu'il" and "il" are the same word for this purpose. It
    matters: "il enregistre une image, il enregistre la caméra" is a plain repetition that
    went unrecognised because whisper wrote the first one "qu'il". A short prefix before
    the apostrophe is an elision; a long one is a word ("aujourd'hui" is left alone).
    """
    word = word.strip(EDGE_PUNCT).lower()
    head, sep, tail = word.partition("'")
    return tail if sep and tail and len(head) <= 2 else word


def normalized(words: list[dict]) -> list[str]:
    return [n for n in (normalize(w["text"]) for w in words) if n]


def text_of(words: list[dict]) -> str:
    return " ".join(w["text"] for w in words)


def attach_words(spans: list[Span], words: list[dict]) -> list[list[dict]]:
    """Give every word to exactly one span, by the position of its middle.

    Not by containment: after `snap_to_silence` and `pad_inwards` a cut boundary almost
    never falls on a word boundary, so a word straddling one would be either counted
    twice or lost. The midpoint is arbitrary but total — every word lands somewhere, and
    nowhere else.
    """
    if not spans:
        return []
    # Sorted view rather than the timeline as given: `timeline.check` rejects a
    # non-monotonic EDL at the montage stage, but this stage also reads EDLs already on
    # disk, and one of those is out of order. A bisect over unsorted starts does not fail
    # — it silently attributes 1600 words to a 17-second cut, which is how this was found.
    order = sorted(range(len(spans)), key=lambda i: spans[i].start)
    starts = [spans[i].start for i in order]
    buckets: list[list[dict]] = [[] for _ in spans]
    for word in words:
        middle = (word["start"] + word["end"]) / 2
        rank = min(max(bisect.bisect_right(starts, middle) - 1, 0), len(order) - 1)
        buckets[order[rank]].append(word)
    return buckets


def collect(plan: Edl, words: list[dict]) -> tuple[list[list[dict]], list[Cut]]:
    """The words of each span, and the cuts with their surrounding kept text."""
    buckets = attach_words(plan.timeline, words)

    cursor = 0.0
    final_at: list[float] = []
    for span in plan.timeline:
        final_at.append(cursor)
        if not span.drop and span.duration > 0:
            cursor += span.duration

    cuts: list[Cut] = []
    for index, span in enumerate(plan.timeline):
        if not span.drop:
            continue
        before: list[dict] = []
        for previous in range(index - 1, -1, -1):
            if plan.timeline[previous].drop:
                continue
            before = buckets[previous] + before
            if len(before) >= CONTEXT_WORDS:
                break
        after: list[dict] = []
        for following in range(index + 1, len(plan.timeline)):
            if plan.timeline[following].drop:
                continue
            after = after + buckets[following]
            if len(after) >= CONTEXT_WORDS:
                break
        cuts.append(
            Cut(
                span=span,
                words=buckets[index],
                before=before[-CONTEXT_WORDS:],
                after=after[:CONTEXT_WORDS],
                final_at=final_at[index],
            )
        )
    return buckets, cuts


# ---- mechanical checks: does the reason describe what was removed?


def _common_prefix(a: list[str], b: list[str]) -> int:
    count = 0
    for left, right in zip(a, b, strict=False):
        if left != right:
            break
        count += 1
    return count


def longest_run(needle: list[str], haystack: list[str]) -> int:
    """Length of the longest stretch of `needle` appearing verbatim in `haystack`."""
    if not needle or not haystack:
        return 0
    best = 0
    previous = [0] * (len(haystack) + 1)
    for word in needle:
        current = [0] * (len(haystack) + 1)
        for j, other in enumerate(haystack, start=1):
            if word == other:
                current[j] = previous[j - 1] + 1
                best = max(best, current[j])
        previous = current
    return best


def repeat_is_real(cut: Cut, ratio: float = 0.5) -> bool:
    """A repetition restarts: what was removed is also said in the kept text around it.

    "c'est un peu toutes les — toutes les plateformes" removes "toutes les", and "toutes
    les" is exactly how the kept text resumes.

    Searched anywhere in the context, not just against the boundary. A restart is rarely
    flush: "il enregistre une image, il enregistre la caméra" repeats "il enregistre" two
    words away from the cut, and an aligned comparison called that a false label — it is
    not, it is a repetition with a tail. Both real cuts this check first accused were of
    that shape.
    """
    removed = normalized(cut.words)
    if not removed:
        return False
    context = normalized(cut.before) + normalized(cut.after)
    return longest_run(removed, context) >= max(1, ceil(len(removed) * ratio))


def ends_sentence(text: str) -> bool:
    """Does this word close a sentence? An ellipsis does the opposite."""
    text = text.rstrip("»\"')")
    return not text.endswith(ELLIPSIS) and text.endswith(SENTENCE_END)


def completes_a_sentence(words: list[dict]) -> bool:
    """Does the removed text carry a finished sentence?

    A hesitation is abandoned — that is what makes it one. A stretch that opens, closes
    and punctuates is a thought that was expressed, and removing it removes content,
    whatever label the model put on it.
    """
    return any(ends_sentence(word["text"]) for word in words)


# Below this, a punctuated fragment is still a tic: "Et voilà.", "Il faut dire ce qu'il y
# a." are sentences by the letter and filler by the ear. The check earns its keep on
# "Le scheduleur, donc c'est ce que je vous ai dit." — ten words, two seconds, and content.
SENTENCE_MIN_SECONDS = 1.5
SENTENCE_MIN_WORDS = 5


def carries_content(cut: Cut) -> bool:
    """A finished sentence, long enough that removing it removes something."""
    return (
        cut.span.duration > SENTENCE_MIN_SECONDS
        and len(cut.words) >= SENTENCE_MIN_WORDS
        and completes_a_sentence(cut.words)
    )


def check_cut(cut: Cut) -> list[Issue]:
    """Everything verifiable about one cut, without asking a model."""
    where = f"coupe {youtube_timecode(cut.span.start)}"
    seconds = cut.span.duration
    reason = cut.span.reason
    issues: list[Issue] = []

    hanging = dangles(cut)
    if hanging:
        issues.append(Issue(
            "à revoir", where,
            f"le raccord laisse « {hanging} » en suspens",
            "la coupe emporte ce que ce mot introduisait — le montage dira la phrase tronquée",
        ))

    if not cut.words:
        # Nothing was said in there: whatever the label, no content left with it. The
        # audio side of this — is the silence real — is `cuts.has_measured_silence`, and
        # it has already run by the time we get here.
        return issues

    if seconds > SECTION_SECONDS:
        issues.append(Issue(
            "bloquant", where,
            f"{seconds:.0f} s de parole retirées d'un coup ({reason or 'sans motif'})",
            "à cette durée ce n'est plus une hésitation coupée, c'est une séquence supprimée",
        ))

    if reason == "repeat" and not repeat_is_real(cut):
        issues.append(Issue(
            "à revoir", where,
            "motif « repeat » mais rien de semblable autour",
            "le passage n'est dit qu'une fois — la répétition invoquée n'existe pas",
        ))

    if reason == "filler":
        over = []
        if seconds > FILLER_MAX_SECONDS:
            over.append(f"{seconds:.1f} s")
        if len(cut.words) > FILLER_MAX_WORDS:
            over.append(f"{len(cut.words)} mots")
        if over:
            issues.append(Issue(
                "à revoir", where,
                f"motif « filler » pour {' et '.join(over)}",
                f"au-delà de {FILLER_MAX_SECONDS:.0f} s ou {FILLER_MAX_WORDS} mots "
                "ce n'est plus un tic de langage",
            ))
        elif carries_content(cut):
            issues.append(Issue(
                "à revoir", where,
                "motif « filler » sur une phrase terminée",
                "une phrase ponctuée est du propos, pas un remplissage",
            ))

    if reason == "falsestart":
        if seconds > FALSESTART_MAX_SECONDS:
            issues.append(Issue(
                "à revoir", where,
                f"motif « falsestart » pour {seconds:.1f} s",
                f"un faux départ est abandonné vite, {FALSESTART_MAX_SECONDS:.0f} s au plus",
            ))
        elif carries_content(cut):
            issues.append(Issue(
                "à revoir", where,
                "motif « falsestart » sur une phrase terminée",
                "un faux départ n'est pas mené jusqu'au point final",
            ))

    if reason == "fumble" and FUMBLE_MAX_SECONDS < seconds <= SECTION_SECONDS:
        issues.append(Issue(
            "à revoir", where,
            f"motif « fumble » pour {seconds:.0f} s",
            "vérifier que la fin de la séquence — le résultat — n'est pas dedans",
        ))

    return issues


def check_bookends(plan: Edl) -> list[Issue]:
    """The intro and outro cards, checked before the render rather than after.

    Omitting them is allowed by `montage.md` — "when the take does not deserve one" — and
    one model omitted both, so the video started on the first sentence and stopped on the
    last. No card also means no jingle, hence no music at all, and none of that is visible
    anywhere but in the finished file. It is a remark, not a fault: the prompt permits it.
    """
    missing = [name for name, card in (("intro", plan.metadata.intro),
                                       ("outro", plan.metadata.outro)) if card is None]
    if not missing:
        return []
    return [Issue(
        "à revoir", "cartons", f"aucun carton {' ni '.join(missing)}",
        "sans carton il n'y a pas de jingle, donc pas de musique — à confirmer si c'est voulu",
    )]


def mechanical(plan: Edl, cuts: list[Cut]) -> list[Issue]:
    return check_bookends(plan) + [issue for cut in cuts for issue in check_cut(cut)]


# Words a French sentence cannot end on. When the kept text stops on one of these, the
# cut took away what it introduced and the join is audibly broken — "Revenons à Goose si"
# followed by "Donc Goose, vous activez ce que vous voulez". Capitalisation is no help
# here: whisper capitalises after a pause, so the next word looked like a fresh sentence
# and the junction passed unnoticed into a rendered video.
DANGLING = frozenset([
    # subordinators and interrogatives
    "si", "que", "qui", "quoi", "dont", "parce", "puisque", "lorsque", "quand", "comme",
    # prepositions
    "pour", "par", "dans", "de", "du", "des", "a", "au", "aux", "en", "sur", "sous",
    "avec", "sans", "chez", "vers", "entre", "depuis",
    # determiners
    "le", "la", "les", "un", "une", "mon", "ma", "mes", "ton", "ta", "tes", "son", "sa",
    "ses", "ce", "cet", "cette", "ces", "leur", "leurs",
    # pronouns
    "je", "tu", "il", "elle", "on", "nous", "vous", "ils", "elles", "me", "te", "se",
    "lui", "y",
])


def dangles(cut: Cut) -> str:
    """The word left hanging by this cut, if the kept text stops on one."""
    if not cut.before:
        return ""
    last = cut.before[-1]["text"]
    if ends_sentence(last) or last.rstrip("»\"')").endswith(","):
        # A comma is a marked pause: the speaker stopped there on purpose, and the join
        # lands on a breath rather than mid-clause.
        return ""
    return last if normalize(last) in DANGLING else ""


def broken_junctions(cuts: list[Cut]) -> list[Cut]:
    """Cuts that land inside a sentence — where the assembled text may not read.

    Not an issue on its own: a clean join mid-sentence is exactly what a good cut does.
    It is a place to look, so it is handed to the model rather than reported here.
    """
    return [
        cut
        for cut in cuts
        if cut.before
        and cut.after
        and not ends_sentence(cut.before[-1]["text"])
        and not cut.after[0]["text"][:1].isupper()
    ]


# ---- the document


def preview(plan: Edl, buckets: list[list[dict]], cuts: list[Cut], issues: list[Issue]) -> str:
    """The edit, readable top to bottom the way the video plays.

    This is the deliverable of the stage. Everything else — the checks, the model — exists
    to point at a line of it.
    """
    flagged = {issue.where for issue in issues}
    source = plan.timeline[-1].end if plan.timeline else 0.0
    final = plan.final_duration
    removed = sum(c.span.duration for c in cuts)

    out = [
        f"# Le texte monté — {plan.metadata.title or 'sans titre'}",
        "",
        f"{source / 60:.0f} min de rush → {final / 60:.0f} min montées, "
        f"{len(cuts)} coupe(s), {removed:.0f} s retirées "
        f"({removed / source if source else 0:.0%} de la prise).",
        "",
        "Le texte est celui de whisper, pas une citation exacte : les fautes viennent de la",
        "transcription, pas du montage. Ce qui se relit ici, ce sont les coupes.",
        "",
        "Les temps entre crochets sont ceux de la **vidéo montée**. Une coupe porte en plus son",
        "temps dans le **rush** — c'est celui-là qui la désigne dans les contrôles et dans l'EDL.",
        "",
    ]

    if issues:
        counts = {level: sum(1 for i in issues if i.severity == level) for level in ORDER}
        out += [
            "## Contrôles",
            "",
            ", ".join(f"{n} {level}" for level, n in counts.items() if n) + ".",
            "",
        ]
        for issue in sorted(issues, key=lambda i: ORDER.get(i.severity, 9)):
            out.append(f"- **{issue.severity}** — {issue.where} : {issue.what}")
            if issue.fix:
                out.append(f"  - {issue.fix}")
        out.append("")

    out += ["## Le montage", ""]
    chapters: list[Chapter] = list(plan.metadata.chapters)
    cursor = 0.0
    next_chapter = 0
    for span, words in zip(plan.timeline, buckets, strict=True):
        while next_chapter < len(chapters) and chapters[next_chapter].at <= span.start:
            out += ["", f"### {chapters[next_chapter].label}", ""]
            next_chapter += 1
        if span.drop:
            where = f"coupe {youtube_timecode(span.start)}"
            mark = " ⚠" if where in flagged else ""
            out.append(
                f"> ✂ {span.duration:.1f} s · {span.reason or 'sans motif'} · "
                f"rush {youtube_timecode(span.start)}{mark}"
            )
            body = text_of(words) or "(aucune parole)"
            out += ["> " + line for line in textwrap.wrap(body, 88)]
            out.append("")
            continue
        if span.duration <= 0:
            continue
        body = text_of(words)
        if body:
            out.append(f"**[{youtube_timecode(cursor)}]** {span.scene}")
            out += textwrap.wrap(body, 92)
            out.append("")
        cursor += span.duration
    return "\n".join(out).rstrip() + "\n"


def payload(plan: Edl, cuts: list[Cut], flagged: list[Issue]) -> dict:
    """What the model reads: the cuts and their context, never the whole transcript."""
    by_where: dict[str, list[str]] = {}
    for issue in flagged:
        by_where.setdefault(issue.where, []).append(issue.what)
    broken = {id(cut) for cut in broken_junctions(cuts)}
    return {
        "title": plan.metadata.title,
        "chapters": [
            {"at": youtube_timecode(c.at), "label": c.label} for c in plan.metadata.chapters
        ],
        "final_duration_seconds": round(plan.final_duration),
        "cuts": [
            {
                "at": youtube_timecode(cut.span.start),
                "seconds": round(cut.span.duration, 1),
                "reason": cut.span.reason,
                "removed": cut.text,
                "kept_before": text_of(cut.before),
                "kept_after": text_of(cut.after),
                "mid_sentence": id(cut) in broken,
                "mechanical_flags": by_where.get(
                    f"coupe {youtube_timecode(cut.span.start)}", []
                ),
            }
            for cut in cuts
        ],
    }


class ReviewStopped(Exception):
    """A blocking finding, before anything was rendered."""


def run(ep: Episode, plan: Edl, prompts_dir: Path, gate: bool = True) -> None:
    """Reassemble the edit as text, check it, write the preview. Renders nothing."""
    words = json.loads(ep.words.read_text()) if ep.words.is_file() else []
    if not words:
        log("⚠ review: pas de mots horodatés (work/words.json) — relecture impossible")
        return

    buckets, cuts = collect(plan, words)
    issues = mechanical(plan, cuts)

    if cuts:
        log(f"review: {len(cuts)} coupe(s) relues sur le texte, avant le rendu")
        issues += editorial(
            ep.cfg.claude_bin,
            prompts_dir,
            payload(plan, cuts, issues),
            ep.work,
            prompt_name="review.md",
            step="review",
        )

    out = ep.work / "edit-preview.md"
    out.write_text(preview(plan, buckets, cuts, issues))

    stoppers = blocking(issues)
    if not issues:
        log(f"review: rien à signaler -> {out}")
    else:
        log(f"review: {len(issues)} point(s), dont {len(stoppers)} bloquant(s) -> {out}")
        for issue in sorted(issues, key=lambda i: ORDER.get(i.severity, 9))[:8]:
            log(f"  {issue.severity:10s} {issue.where}: {issue.what}")
    if stoppers and gate:
        raise ReviewStopped(
            f"la relecture du montage bloque sur {len(stoppers)} point(s) — {out}\n"
            "  rien n'a été rendu. Relancer le montage (`screencast run montage <ep>`),\n"
            "  ou passer outre avec --no-gate."
        )
