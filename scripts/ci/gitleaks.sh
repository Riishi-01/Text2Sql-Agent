#!/usr/bin/env bash

set -e

if ! command -v gitleaks &> /dev/null; then
  echo "ERROR: gitleaks not installed." >&2
  echo "Install options:" >&2
  echo "  brew install gitleaks                                   # macOS" >&2
  echo "  sudo apt-get install gitleaks                           # Debian/Ubuntu" >&2
  echo "  go install github.com/gitleaks/gitleaks/v8@latest       # Go" >&2
  echo "Or download a release: https://github.com/gitleaks/gitleaks/releases" >&2
  exit 1
fi

gitleaks protect --staged --redact
