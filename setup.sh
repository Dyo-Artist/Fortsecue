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
  if command -v uv >/dev/null 2>&1; then
    uv pip install -e .  # editable install via pyproject.toml
  else
    pip install -e .
  fi
  touch "$STAMP"
fi

# Run linters/tests in a non-fatal way so cloud environments can start
if command -v ruff >/dev/null 2>&1; then
  ruff check . || echo "⚠️ ruff failed (non-fatal in this environment)"
fi

if command -v pytest >/dev/null 2>&1; then
  pytest -q || echo "⚠️ pytest failed (non-fatal in this environment)"
fi
