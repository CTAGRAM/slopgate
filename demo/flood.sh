#!/usr/bin/env bash
# Open real pull requests on the demo repo, one after another, and watch the gate handle them live
# (dashboard at /, 3D pipeline at /sim, or demo/watch.py in another terminal).
#
#   demo/flood.sh              # 4 PRs, 15 s apart: spam, fix, injection, slop
#   demo/flood.sh 8 10         # 8 PRs, 10 s apart, kinds cycled
#   demo/flood.sh 3 5 spam     # 3 spam PRs, 5 s apart
set -euo pipefail

count="${1:-4}"
gap="${2:-15}"
only="${3:-}"
kinds=(spam fix injection slop)
here="$(cd "$(dirname "$0")" && pwd)"

for ((i = 0; i < count; i++)); do
  kind="${only:-${kinds[i % ${#kinds[@]}]}}"
  printf '\033[1m[%d/%d]\033[0m opening a \033[36m%s\033[0m PR on %s ... ' "$((i + 1))" "$count" "$kind" "${DEMO_REPO:-CTAGRAM/slopgate-demo}"
  url="$("$here/open-pr.sh" "$kind" 2>/dev/null | tail -1)"
  echo "$url"
  if ((i < count - 1)); then sleep "$gap"; fi
done
echo "Done. Close the demo PRs later with: demo/cleanup.sh"
