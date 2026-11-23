#!/usr/bin/env bash
set -euo pipefail

BRANCH="${1:-main}"

git config pull.rebase false
git fetch origin "$BRANCH"
git pull --no-edit origin "$BRANCH"
git push origin "$BRANCH"
echo "Synced local '$BRANCH' cleanly with origin/$BRANCH."
