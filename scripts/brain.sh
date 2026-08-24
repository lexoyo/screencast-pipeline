#!/usr/bin/env bash
# Le « cerveau » du pipeline, derrière n'importe quel modèle.
#
# Le pipeline appelle `$CLAUDE_BIN -p` avec le prompt sur stdin et lit la réponse sur
# stdout. Ce script offre exactement cette interface, et la sert avec opencode (donc
# OpenRouter) plutôt qu'avec Claude. Pour l'utiliser, dans config.env :
#
#   CLAUDE_BIN="$HOME/_/screencast-pipeline/scripts/brain.sh"
#
# Sans BRAIN_MODEL, opencode reprend le dernier modèle utilisé (celui de son TUI).
# Pour en imposer un le temps d'un run :
#   BRAIN_MODEL=openrouter/z-ai/glm-5.2 ./screencast run <ep>
set -euo pipefail

# `-p` veut dire « prompt » chez claude et « password » chez opencode : on l'avale.
for arg in "$@"; do
  case "$arg" in
    -p|--print) ;;
    *) echo "brain.sh: argument inattendu: $arg" >&2; exit 2 ;;
  esac
done

# opencode lit le AGENTS.md et les fichiers du dossier où il tourne. Un dossier vide et
# jetable, donc : le cerveau ne doit voir que ce qui arrive sur stdin.
workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

# --format json : la sortie normale est colorée et précédée d'un en-tête « > build · … »,
# qui finirait dans un fichier .srt. Ici on ne garde que le texte de la réponse.
model_arg=()
[ -n "${BRAIN_MODEL:-}" ] && model_arg=(-m "$BRAIN_MODEL")

opencode run --dir "$workdir" "${model_arg[@]}" --format json \
  | python3 -c '
import json, sys

parts = {}   # id -> texte ; un part émis plusieurs fois (streaming) ne compte qu une fois
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        continue
    part = event.get("part") or {}
    if event.get("type") == "text" and part.get("type") == "text":
        parts[part.get("id")] = part.get("text", "")
sys.stdout.write("".join(parts.values()))
'
