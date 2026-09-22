#!/usr/bin/env bash
# How many commits landed on origin/main today (UTC). The budget is 4.
# Branches and PRs are free; only squash-merges to main count.
set -euo pipefail
budget=${BUDGET:-4}
git fetch -q origin main
today=$(date -u +%Y-%m-%d)
n=$(git log origin/main --since="$today 00:00 UTC" --format=%h | wc -l | tr -d ' ')
echo "main commits today (UTC): $n / $budget"
[ "$n" -lt "$budget" ] || { echo "budget spent; merge tomorrow"; exit 1; }
