#!/usr/bin/env bash
set -euo pipefail

OWNER="${1:-CactysFedya}"
REPO="${2:-plyctl}"
VISIBILITY="${3:-public}"
SSH_URL="git@github.com:${OWNER}/${REPO}.git"

if ! command -v gh >/dev/null 2>&1; then
  echo "GitHub CLI is required: https://cli.github.com/" >&2
  exit 1
fi

gh auth status

if gh repo view "$OWNER/$REPO" >/dev/null 2>&1; then
  echo "GitHub repository already exists: $OWNER/$REPO"
else
  gh repo create "$OWNER/$REPO" \
    "--$VISIBILITY" \
    --description="High-performance typed runtime for local and distributed streaming graphs"
fi

git branch -M main
if git remote get-url origin >/dev/null 2>&1; then
  git remote set-url origin "$SSH_URL"
else
  git remote add origin "$SSH_URL"
fi

git push -u origin main

echo "Repository: https://github.com/$OWNER/$REPO"
