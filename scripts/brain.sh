#!/usr/bin/env bash
# Le « cerveau » du pipeline, derrière n'importe quel modèle.
#
# Le pipeline appelle `$CLAUDE_BIN -p` avec le prompt sur stdin et lit la réponse sur
# stdout. Ce script offre exactement cette interface, et la sert avec opencode (donc
# OpenRouter) plutôt qu'avec Claude. Pour l'utiliser, dans config.env :
#
#   CLAUDE_BIN="$HOME/_/screencast-pipeline/scripts/brain.sh"
#
# Le modèle se choisit dans config.env (BRAIN_MODEL, quelques exemples y sont listés).
# Vide ou absent = opencode reprend le dernier modèle utilisé dans son TUI. La variable
# d'environnement gagne, pour essayer un modèle le temps d'un run :
#   BRAIN_MODEL=openrouter/z-ai/glm-5.2 ./screencast run <ep>
set -euo pipefail

# config.env n'est lu que par le Python du pipeline, jamais sourcé : sans ces lignes,
# un BRAIN_MODEL écrit là-bas n'arriverait pas jusqu'ici.
config="$(dirname "$(dirname "$(readlink -f "$0")")")/config.env"
if [ -z "${BRAIN_MODEL:-}" ] && [ -f "$config" ]; then
  # dernière ligne BRAIN_MODEL=..., commentaire de fin de ligne ôté, guillemets ôtés
  BRAIN_MODEL="$(grep -E '^[[:space:]]*BRAIN_MODEL=' "$config" | tail -1 |
                 cut -d= -f2- | sed 's/#.*//; s/["'"'"']//g' | xargs)"
fi

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
errors = []
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        continue
    if event.get("type") == "error":
        # opencode ecrit ses erreurs dans le flux, pas sur stderr : sans ca, un modele
        # inconnu ou un quota depasse ressemble a une reponse vide.
        detail = (event.get("error") or {}).get("data", {}).get("message", "?")
        errors.append(str(detail))
        continue
    part = event.get("part") or {}
    if event.get("type") == "text" and part.get("type") == "text":
        parts[part.get("id")] = part.get("text", "")

answer = "".join(parts.values())
if not answer.strip():
    hint = " ; ".join(errors) or "reponse vide"
    print(f"brain.sh: opencode n a rien renvoye ({hint}). Le modele doit s ecrire "
          f"provider/modele, p.ex. openrouter/z-ai/glm-5.2.", file=sys.stderr)
    sys.exit(1)
sys.stdout.write(answer)
'
