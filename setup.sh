#!/usr/bin/env bash
set -euo pipefail

FILES=""
[[ -f pyproject.toml ]] && FILES="$FILES pyproject.toml"
for f in requirements*.txt; do
  [[ -e "$f" ]] && FILES="$FILES $f"
done
[[ -f uv.lock ]] && FILES="$FILES uv.lock"
[[ -f poetry.lock ]] && FILES="$FILES poetry.lock"

if [[ -n "$FILES" ]]; then
  HASH=$(cat $FILES | sha256sum | cut -d' ' -f1)
else
  HASH="no-deps"
fi

STAMP=".cache/deps.${HASH}.stamp"
if [[ -f "$STAMP" ]]; then
  echo "Dependencies up to date (hash $HASH), skipping installation"
else
  echo "Installing dependencies (hash $HASH)"
  mkdir -p .cache
  rm -f .cache/deps.*.stamp
  if command -v uv >/dev/null 2>&1; then
    uv pip install --system -r requirements.txt
  else
    pip install -r requirements.txt
  fi
  touch "$STAMP"
fi

ruff check .
python -m pytest
