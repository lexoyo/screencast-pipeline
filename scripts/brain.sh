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
# BRAIN_MODEL nomme le modèle ; l'environnement l'emporte sur le fichier, pour essayer
# un modèle le temps d'un run :
#   BRAIN_MODEL=openrouter/z-ai/glm-5.2 ./screencast run montage <ep>
# BRAIN_LOG nomme un dossier où archiver chaque échange (prompt, réponse, flux brut).
set -euo pipefail

here="$(dirname "$(readlink -f "$0")")"

# `-p` veut dire « prompt » chez claude et « password » chez opencode : on l'avale.
for arg in "$@"; do
  case "$arg" in
    -p|--print) ;;
    *) echo "brain.sh: argument inattendu: $arg" >&2; exit 2 ;;
  esac
done

# config.env n'est lu que par le Python du pipeline, jamais sourcé : sans ces lignes,
# une valeur écrite là-bas n'arriverait pas jusqu'ici.
config="$(dirname "$here")/config.env"
from_config() {  # $1 = nom du réglage ; dernière occurrence, commentaire et guillemets ôtés
  [ -f "$config" ] || return 0
  local raw
  raw="$(grep -E "^[[:space:]]*$1=" "$config" | tail -1 | cut -d= -f2- |
         sed 's/#.*//; s/["'"'"']//g' | xargs || true)"
  echo "${raw//\$HOME/$HOME}"   # même expansion que côté Python, et elle seule
}
MODEL="${BRAIN_MODEL:-$(from_config BRAIN_MODEL)}"
API_BASE="${BRAIN_API_BASE:-$(from_config BRAIN_API_BASE)}"
API_KEY="${BRAIN_API_KEY:-$(from_config BRAIN_API_KEY)}"
LOGDIR="${BRAIN_LOG:-$(from_config BRAIN_LOG)}"
VARIANT="${BRAIN_VARIANT:-$(from_config BRAIN_VARIANT)}"

LOGFILE="${BRAIN_LOG_FILE:-}"   # le log.md de l'épisode, quand le pipeline nous le dit
say() {
  echo "brain: $*" >&2
  [ -n "$LOGFILE" ] && echo "[$(date '+%F %T')] brain: $*" >> "$LOGFILE" || true
}

prompt="$(cat)"
started=$(date +%s)

# Un sous-dossier par appel : le prompt exact, la réponse exacte, le flux du fournisseur.
# C'est ce qui permet de comparer deux modèles sur un prompt identique, et de savoir six
# mois plus tard qui a écrit le titre d'une vidéo.
archive=""
if [ -n "$LOGDIR" ]; then
  archive="$LOGDIR"
  [ -e "$archive/prompt.txt" ] && archive="$LOGDIR-$(date +%H%M%S)" || true
  mkdir -p "$archive"
  printf '%s' "$prompt" > "$archive/prompt.txt"
  { echo "date    $(date -Is)"; echo "modele  ${MODEL:-<défaut opencode>}"
    echo "voie    ${API_BASE:-opencode}"; echo "prompt  ${#prompt} octets"; } > "$archive/meta.txt"
fi
say "${MODEL:-le modèle par défaut} — prompt $(( ${#prompt} / 1024 )) Ko${archive:+, trace dans $archive}"

fin() {  # durée + rappel de l'archive, quel que soit le chemin pris
  say "$(( $(date +%s) - started )) s"
  [ -n "$archive" ] && { echo "duree   $(( $(date +%s) - started )) s" >> "$archive/meta.txt"; } || true
}

if [ -n "$API_BASE" ]; then
  # --- endpoint OpenAI-compatible, appelé directement -------------------------------
  # Pas d'agent, pas d'outils, pas de session : une question, une réponse.
  set +e
  python3 "$here/brain-http.py" "$API_BASE" "$API_KEY" "$MODEL" <<< "$prompt" \
    | tee ${archive:+"$archive/reponse.txt"}
  code=${PIPESTATUS[0]}
  set -e
  fin
  exit "$code"
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
# L'effort de raisonnement. Le choix fait dans le TUI d'opencode ne vaut que pour le TUI :
# ici il faut le dire explicitement, sinon c'est le réglage par défaut du fournisseur.
[ -n "$VARIANT" ] && model_arg+=(--variant "$VARIANT")

# --format json : la sortie normale est colorée et précédée d'un en-tête « > build · … »,
# qui finirait dans un fichier .srt. Le flux complet est archivé tel quel quand BRAIN_LOG
# est réglé — c'est là que se lisent les erreurs du fournisseur et le détail des jetons.
# Les logs d'opencode lui-même : dans l'archive quand il y en a une, à l'écran sinon.
oclog="${archive:+$archive/opencode.log}"
oclog="${oclog:-/dev/stderr}"

set +e
opencode run --dir "$workdir" --agent brain "${model_arg[@]}" --format json <<< "$prompt" \
    2> "$oclog" \
  | tee ${archive:+"$archive/flux-opencode.jsonl"} \
  | BRAIN_LOG_FILE="$LOGFILE" python3 "$here/brain-parse.py" \
  | tee ${archive:+"$archive/reponse.txt"}
code=${PIPESTATUS[2]}
set -e
fin
exit "$code"
