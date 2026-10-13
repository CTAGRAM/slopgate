#!/usr/bin/env bash
# Close the PRs that demo/flood.sh opened. Keeps #2-#6, the showcase PRs the dashboard links to.
# Closing only: branches and comments stay, so nothing is lost.
set -euo pipefail
REPO="${DEMO_REPO:-CTAGRAM/slopgate-demo}"
keep=" 2 3 4 5 6 "
gh pr list -R "$REPO" --state open --limit 200 --json number,headRefName \
  --jq '.[] | select(.headRefName | startswith("demo-")) | .number' |
  while read -r n; do
    if [[ "$keep" == *" $n "* ]]; then continue; fi
    gh pr close "$n" -R "$REPO" --comment "Closed by demo/cleanup.sh after a live SlopGate demo." >/dev/null
    echo "closed #$n"
  done
