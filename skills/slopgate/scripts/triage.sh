#!/usr/bin/env bash
# Triage one pull request and print JSON.
#   scripts/triage.sh https://github.com/OWNER/REPO/pull/N [--apply]
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "usage: $0 https://github.com/OWNER/REPO/pull/N [--apply]" >&2
  exit 2
fi
if ! command -v uv >/dev/null; then
  echo "uv is required: https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
fi

here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/../../.." && pwd)"

# Inside the SlopGate repository: run the local checkout. Anywhere else: fetch it with uvx.
if grep -qs '^name = "slopgate"' "$root/pyproject.toml"; then
  exec uv run --quiet --project "$root" slopgate triage "$@" --json
fi
exec uvx --quiet --from "${SLOPGATE_SOURCE:-git+https://github.com/CTAGRAM/slopgate}" slopgate triage "$@" --json
