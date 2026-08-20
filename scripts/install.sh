#!/usr/bin/env bash
# Set up the toolchain this harness drives. Fedora.
#
#   ./scripts/install.sh --check     report what is missing, change nothing
#   ./scripts/install.sh             install what is missing, after confirmation
#
# It installs only what is absent. Chromium in particular is NEVER touched: it ships with
# Fedora, it is what renders the slides, and pulling a second copy (via Playwright or
# otherwise) would add Node and 150 MB for a job that `chromium-browser --headless` does
# in under a second.
#
# The three Fedora traps this encodes, each paid for once already:
#   1. The MLT binary is `melt-7`, not `melt` — plain `melt` belongs to an unrelated
#      compression package.
#   2. `ffmpeg-free` ships without H.264. Without the fix, exports come out as 1.3 KB
#      files. `libavcodec-freeworld` from RPM Fusion restores it. Do NOT `dnf swap` to
#      full ffmpeg: it drags GNOME's and Firefox's media stack out with it.
#   3. OBS screen capture on Wayland goes through the XDG portal and opens a picker —
#      a human action, not scriptable. Expect it at the first shoot.
set -euo pipefail

CHECK_ONLY=0
[ "${1:-}" = "--check" ] && CHECK_ONLY=1

WHISPER_DIR="${WHISPER_DIR:-/opt/whisper.cpp}"
MODEL_DIR="${MODEL_DIR:-$HOME/models/whisper}"
MODELS="${MODELS:-small base}"

ok(){ printf '  \033[32m✓\033[0m %-22s %s\n' "$1" "${2:-}"; }
missing(){ printf '  \033[31m✗\033[0m %-22s %s\n' "$1" "${2:-}"; }
note(){ printf '  \033[33m!\033[0m %-22s %s\n' "$1" "${2:-}"; }
title(){ printf '\n\033[1m%s\033[0m\n' "$1"; }

TO_INSTALL=()
need_pkg(){ # need_pkg <binary> <dnf package> <what it does>
  if command -v "$1" >/dev/null 2>&1; then ok "$1" "$(command -v "$1")"
  else missing "$1" "→ dnf install $2   ($3)"; TO_INSTALL+=("$2"); fi
}

title "Video and audio"
need_pkg ffmpeg      ffmpeg-free   "everything: measuring, cutting, rendering"
need_pkg ffprobe     ffmpeg-free   "reading durations"
need_pkg melt-7      mlt           "rendering the Shotcut project"
need_pkg magick      ImageMagick   "thumbnails"

# H.264 is the one that fails silently: the encoder is simply absent and ffmpeg writes a
# file of a few kilobytes. Test the encoder itself rather than trusting the package list.
if command -v ffmpeg >/dev/null 2>&1; then
  if ffmpeg -hide_banner -loglevel error -f lavfi -i testsrc=d=0.1:s=64x64 \
       -c:v libx264 -f null - 2>/dev/null; then
    ok "H.264 encoder" "libx264 works"
  else
    missing "H.264 encoder" "→ dnf install libavcodec-freeworld   (needs RPM Fusion)"
    TO_INSTALL+=("libavcodec-freeworld")
  fi
fi

title "Recording and editing"
need_pkg obs         obs-studio    "recording"
need_pkg shotcut     shotcut       "re-cutting by hand"

title "Slides"
if command -v chromium-browser >/dev/null 2>&1 || command -v chromium >/dev/null 2>&1; then
  ok "chromium" "$(command -v chromium-browser || command -v chromium) — renders the slides"
else
  missing "chromium" "→ dnf install chromium   (already present on stock Fedora)"
  TO_INSTALL+=("chromium")
fi

title "Transcription"
if [ -x "$WHISPER_DIR/build/bin/whisper-cli" ]; then
  ok "whisper.cpp" "$WHISPER_DIR/build/bin/whisper-cli"
else
  missing "whisper.cpp" "→ built from source into $WHISPER_DIR"
fi
for model in $MODELS; do
  if [ -f "$MODEL_DIR/ggml-$model.bin" ]; then ok "model $model" "$MODEL_DIR/ggml-$model.bin"
  else missing "model $model" "→ downloaded into $MODEL_DIR"; fi
done

title "Not installed here — checked only"
for tool in claude sonorita-cli; do
  if command -v "$tool" >/dev/null 2>&1; then ok "$tool" "$(command -v "$tool")"
  else note "$tool" "absent — install it yourself, this script will not"; fi
done

# ---------------------------------------------------------------------------
NEEDS_WHISPER=0
[ -x "$WHISPER_DIR/build/bin/whisper-cli" ] || NEEDS_WHISPER=1
NEEDS_MODELS=0
for model in $MODELS; do [ -f "$MODEL_DIR/ggml-$model.bin" ] || NEEDS_MODELS=1; done

if [ ${#TO_INSTALL[@]} -eq 0 ] && [ $NEEDS_WHISPER -eq 0 ] && [ $NEEDS_MODELS -eq 0 ]; then
  printf '\n\033[32mEverything is in place.\033[0m Run ./screencast doctor to see the config too.\n'
  exit 0
fi

printf '\n\033[1mWhat would be done\033[0m\n'
[ ${#TO_INSTALL[@]} -gt 0 ] && printf '  sudo dnf install %s\n' "${TO_INSTALL[*]}"
[ $NEEDS_WHISPER -eq 1 ] && printf '  build whisper.cpp into %s (needs git, cmake, gcc-c++)\n' "$WHISPER_DIR"
[ $NEEDS_MODELS -eq 1 ] && printf '  download the whisper models into %s (~600 MB)\n' "$MODEL_DIR"

if [ $CHECK_ONLY -eq 1 ]; then
  printf '\n(--check: nothing was changed)\n'
  exit 1
fi

printf '\nProceed? [y/N] '
read -r answer
[ "$answer" = "y" ] || { echo "aborted"; exit 1; }

if [ ${#TO_INSTALL[@]} -gt 0 ]; then
  # RPM Fusion first if anything from it is needed, otherwise dnf cannot find the package.
  if printf '%s\n' "${TO_INSTALL[@]}" | grep -q libavcodec-freeworld; then
    if ! dnf repolist 2>/dev/null | grep -q rpmfusion-free; then
      echo "enabling RPM Fusion (free) — libavcodec-freeworld lives there"
      sudo dnf install -y \
        "https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm"
    fi
  fi
  sudo dnf install -y "${TO_INSTALL[@]}"
fi

if [ $NEEDS_WHISPER -eq 1 ]; then
  echo "building whisper.cpp"
  sudo dnf install -y git cmake gcc-c++
  sudo git clone --depth 1 https://github.com/ggml-org/whisper.cpp "$WHISPER_DIR"
  sudo cmake -B "$WHISPER_DIR/build" -S "$WHISPER_DIR" -DCMAKE_BUILD_TYPE=Release
  sudo cmake --build "$WHISPER_DIR/build" -j --config Release
fi

if [ $NEEDS_MODELS -eq 1 ]; then
  mkdir -p "$MODEL_DIR"
  for model in $MODELS; do
    target="$MODEL_DIR/ggml-$model.bin"
    [ -f "$target" ] && continue
    echo "downloading ggml-$model.bin"
    curl -fL --progress-bar -o "$target" \
      "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-$model.bin"
  done
fi

printf '\n\033[32mDone.\033[0m Now run: ./screencast doctor\n'
