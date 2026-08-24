#!/usr/bin/env bash
# Le « cerveau » du pipeline, derrière n'importe quel modèle.
#
# Le pipeline appelle `$CLAUDE_BIN -p` avec le prompt sur stdin et lit la réponse sur
# stdout. Ce script offre exactement cette interface. Dans config.env :
#
#   CLAUDE_BIN="$HOME/_/screencast-pipeline/scripts/brain.sh"
#
# Deux chemins, selon ce qui est réglé dans config.env :
#   BRAIN_API_BASE vide      -> opencode (donc les fournisseurs qu'il a en compte)
#   BRAIN_API_BASE renseigné -> appel direct d'un endpoint OpenAI-compatible
# Dans les deux cas BRAIN_MODEL nomme le modèle ; l'environnement l'emporte sur le
# fichier, pour essayer un modèle le temps d'un run :
#   BRAIN_MODEL=openrouter/z-ai/glm-5.2 ./screencast run montage <ep>
set -euo pipefail

# `-p` veut dire « prompt » chez claude et « password » chez opencode : on l'avale.
for arg in "$@"; do
  case "$arg" in
    -p|--print) ;;
    *) echo "brain.sh: argument inattendu: $arg" >&2; exit 2 ;;
  esac
done

# config.env n'est lu que par le Python du pipeline, jamais sourcé : sans ces lignes,
# une valeur écrite là-bas n'arriverait pas jusqu'ici.
config="$(dirname "$(dirname "$(readlink -f "$0")")")/config.env"
from_config() {  # $1 = nom du réglage ; dernière occurrence, commentaire et guillemets ôtés
  [ -f "$config" ] || return 0
  grep -E "^[[:space:]]*$1=" "$config" | tail -1 | cut -d= -f2- |
    sed 's/#.*//; s/["'"'"']//g' | xargs || true
}
MODEL="${BRAIN_MODEL:-$(from_config BRAIN_MODEL)}"
API_BASE="${BRAIN_API_BASE:-$(from_config BRAIN_API_BASE)}"
API_KEY="${BRAIN_API_KEY:-$(from_config BRAIN_API_KEY)}"

prompt="$(cat)"

if [ -n "$API_BASE" ]; then
  # --- endpoint OpenAI-compatible, appelé directement -------------------------------
  # Pas d'agent, pas d'outils, pas de session : une question, une réponse. Le prompt
  # est passé en JSON par python plutôt que par une interpolation shell — il contient
  # des guillemets, des accolades et des sauts de ligne par milliers.
  python3 -c '
import json, os, sys, urllib.request

base, key, model, prompt = sys.argv[1].rstrip("/"), sys.argv[2], sys.argv[3], sys.stdin.read()
body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}]}).encode()
req = urllib.request.Request(f"{base}/chat/completions", data=body,
                             headers={"Content-Type": "application/json",
                                      "Authorization": f"Bearer {key}"})
try:
    with urllib.request.urlopen(req, timeout=900) as resp:
        data = json.load(resp)
except Exception as exc:
    detail = getattr(exc, "read", lambda: b"")()[:400].decode(errors="replace")
    print(f"brain.sh: {base} a refusé la requête ({exc}) {detail}", file=sys.stderr)
    sys.exit(1)
answer = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
if not answer.strip():
    print(f"brain.sh: réponse vide de {model} ({json.dumps(data)[:300]})", file=sys.stderr)
    sys.exit(1)
sys.stdout.write(answer)
' "$API_BASE" "$API_KEY" "$MODEL" <<< "$prompt"
  exit $?
fi

# --- opencode ----------------------------------------------------------------------
# opencode lit le AGENTS.md et les fichiers du dossier où il tourne. Un dossier vide et
# jetable, donc : le cerveau ne doit voir que ce qui arrive sur stdin.
workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

# Un agent SANS OUTILS, défini dans ce dossier jetable pour n'avoir rien à installer
# chez l'utilisateur. C'est le correctif du premier montage raté : l'agent par défaut
# d'opencode a des outils, alors le modèle a répondu « je vais analyser ce transcript »
# et a rendu la main en attendant de s'en servir, sans jamais écrire le JSON.
mkdir -p "$workdir/.opencode/agent"
cat > "$workdir/.opencode/agent/brain.md" <<'AGENT'
---
description: Repond directement, sans outil
mode: primary
tools:
  bash: false
  edit: false
  write: false
  read: false
  grep: false
  glob: false
  list: false
  patch: false
  todowrite: false
  todoread: false
  webfetch: false
  task: false
---
Tu réponds à la demande directement, dans ton message, en une seule fois.
Tu n'as aucun outil et rien à explorer : tout ce qu'il faut est dans le message.
N'annonce pas ce que tu vas faire — produis le résultat demandé, et rien d'autre.
AGENT

model_arg=()
[ -n "$MODEL" ] && model_arg=(-m "$MODEL")

# --format json : la sortie normale est colorée et précédée d'un en-tête « > build · … »,
# qui finirait dans un fichier .srt. Ici on ne garde que le texte de la réponse.
opencode run --dir "$workdir" --agent brain "${model_arg[@]}" --format json <<< "$prompt" \
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
