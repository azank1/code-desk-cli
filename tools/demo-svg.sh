#!/usr/bin/env bash
# Rebuild docs/demo/signed-handoffs.svg from a fresh run of the example (needs `desk` on PATH: uv run).
set -euo pipefail
cd "$(dirname "$0")/.."
tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
FORCE_COLOR=1 examples/signed-handoffs/demo.sh > "$tmp" 2>&1
python3 tools/term-svg.py "$tmp" docs/demo/signed-handoffs.svg --title "desk · signed hand-offs"
echo "wrote docs/demo/signed-handoffs.svg"
