#!/bin/zsh
set -euo pipefail

# Mirror this app into a subdirectory of the existing my-Mac repository.
# The source directory remains the working copy; ~/my-Mac is the push mirror.

SOURCE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MIRROR_DIR="${MIRROR_DIR:-$HOME/my-Mac}"
REMOTE="${MIRROR_REMOTE:-git@github.com:shazhengzhong/my-Mac.git}"
BRANCH="${MIRROR_BRANCH:-main}"
PREFIX="english-speaking-practice"
MESSAGE="${1:-sync english-speaking-practice $(date '+%Y-%m-%d %H:%M:%S')}"

if [[ ! -d "$MIRROR_DIR/.git" ]]; then
  echo "Cloning $REMOTE -> $MIRROR_DIR"
  git clone "$REMOTE" "$MIRROR_DIR"
fi

# Refuse to mix unrelated local edits in the mirror.
if [[ -n "$(git -C "$MIRROR_DIR" status --porcelain)" ]]; then
  echo "Mirror has uncommitted changes; aborting before sync:"
  git -C "$MIRROR_DIR" status --short
  exit 1
fi

# Pick up commits from the logistics project or other mirrors.
git -C "$MIRROR_DIR" pull --rebase --autostash origin "$BRANCH"

# Keep secrets, local data, build toolchains, and generated binaries out of Git.
RSYNC_EXCLUDES=(
  --exclude='.git/'
  --exclude='.env'
  --exclude='.venv/'
  --exclude='.DS_Store'
  --exclude='__pycache__/'
  --exclude='*.pyc'
  --exclude='*.pyo'
  --exclude='*.sqlite3'
  --exclude='*.bak'
  --exclude='var/'
  --exclude='private_media/'
  --exclude='staticfiles/'
  --exclude='android-shell/toolchain/'
  --exclude='android-shell/build/'
  --exclude='android-shell/keystore/'
  --exclude='*.apk'
  --exclude='static/tts-audition/'
  --exclude='static/phonics-audition/'
)

mkdir -p "$MIRROR_DIR/$PREFIX"
rsync -a --delete "${RSYNC_EXCLUDES[@]}" \
  "$SOURCE_DIR/" "$MIRROR_DIR/$PREFIX/"

git -C "$MIRROR_DIR" add -A -- "$PREFIX"

# Safety gate: stop before committing anything that looks private or huge.
BAD="$(git -C "$MIRROR_DIR" diff --cached --name-only -- "$PREFIX" | grep -E \
  '(^|/)\.env$|\.sqlite3$|\.keystore$|(^|/)private_media/|(^|/)var/|android-shell/toolchain/|\.apk$' || true)"
if [[ -n "$BAD" ]]; then
  echo "Refusing to commit sensitive paths:"
  print -r -- "$BAD"
  git -C "$MIRROR_DIR" reset -- "$PREFIX" >/dev/null
  exit 1
fi

while IFS= read -r file; do
  [[ -f "$MIRROR_DIR/$file" ]] || continue
  bytes="$(stat -f%z "$MIRROR_DIR/$file")"
  if (( bytes > 10485760 )); then
    echo "Refusing to commit a file larger than 10 MB: $file ($bytes bytes)"
    git -C "$MIRROR_DIR" reset -- "$PREFIX" >/dev/null
    exit 1
  fi
done < <(git -C "$MIRROR_DIR" diff --cached --name-only -- "$PREFIX")

if git -C "$MIRROR_DIR" diff --cached --quiet -- "$PREFIX"; then
  echo "No changes to sync."
  exit 0
fi

git -C "$MIRROR_DIR" commit -m "$MESSAGE" \
  -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"

if ! git -C "$MIRROR_DIR" push origin "$BRANCH"; then
  git -C "$MIRROR_DIR" pull --rebase --autostash origin "$BRANCH"
  git -C "$MIRROR_DIR" push origin "$BRANCH"
fi

echo "Synced: https://github.com/shazhengzhong/my-Mac/tree/main/$PREFIX"
