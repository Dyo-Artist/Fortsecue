#!/usr/bin/env bash
set -euo pipefail

FILES=""
[[ -f pyproject.toml ]] && FILES="$FILES pyproject.toml"
[[ -f requirements.txt ]] && FILES="$FILES requirements.txt"
[[ -f requirements-dev.txt ]] && FILES="$FILES requirements-dev.txt"
[[ -f uv.lock ]] && FILES="$FILES uv.lock"
[[ -f poetry.lock ]] && FILES="$FILES poetry.lock"

if [[ -n "$FILES" ]]; then
  HASH=$(cat $FILES | sha256sum | cut -d' ' -f1)
else
  HASH="no-deps"
fi

STAMP=".cache/deps.${HASH}.stamp"
if [[ -f "$STAMP" ]]; then
  echo "✅ Dependencies up to date (hash $HASH), skipping installation"
else
  echo "📦 Installing dependencies (hash $HASH)"
  mkdir -p .cache
  rm -f .cache/deps.*.stamp
  pip install -U pip wheel
  pip install -r requirements.txt
  touch "$STAMP"
fi

# Run linters/tests after installation
ruff check .
pytest -q
