#!/usr/bin/env bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
HOOK="$REPO_ROOT/.git/hooks/pre-commit"
SOURCE="$SCRIPT_DIR/gitleaks.sh"

if [ -e "$HOOK" ] && [ ! -L "$HOOK" ]; then
  echo "ERROR: $HOOK already exists and is not a symlink." >&2
  echo "Remove it first if you want to install the gitleaks hook:" >&2
  echo "  rm $HOOK" >&2
  exit 1
fi

chmod +x "$SOURCE"
ln -sf "$SOURCE" "$HOOK"

echo "Installed pre-commit hook:"
echo "  $HOOK -> $SOURCE"
echo
echo "Audit your full history with:"
echo "  gitleaks detect --source $REPO_ROOT --no-banner"
echo
echo "Test the hook:"
echo "  git commit --allow-empty -m 'gitleaks hook test'"
