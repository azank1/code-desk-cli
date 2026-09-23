#!/usr/bin/env bash
# Signed hand-offs, end to end, in a few seconds. No model, no network.
#
#   uv run examples/signed-handoffs/demo.sh        (from the repo root)
#
# Two desks share one thread. Each hand-off passes its gate only when the
# session's receipt carries a valid signature from a key the office trusts.
# The sessions here are scripted stand-ins so the demo runs anywhere; with a
# real harness the receipt comes from a hook that fires when the session ends.
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
DESK_BIN=${DESK_BIN:-desk}
command -v "$DESK_BIN" >/dev/null || { echo "desk not on PATH; run: uv run $0" >&2; exit 2; }
command -v ssh-keygen >/dev/null || { echo "needs ssh-keygen (OpenSSH 8.1+)" >&2; exit 2; }

W=$(mktemp -d)
[ "${KEEP:-}" ] || trap 'rm -rf "$W"' EXIT
cp "$HERE/office.yaml" "$HERE/verify-receipt" "$W/"
cd "$W"
mkdir -p .office/roles receipts .keys
echo "# planner" > .office/roles/planner.md
echo "# builder" > .office/roles/builder.md
if [ -n "${NO_COLOR:-}" ] || { [ ! -t 1 ] && [ -z "${FORCE_COLOR:-}" ]; }; then B= D= G= R= X=; else B=$'\e[1m' D=$'\e[2m' G=$'\e[32m' R=$'\e[31m' X=$'\e[0m'; fi

desk() { command "$DESK_BIN" "$@"; }  # `command`: never recurse into this function
say() { printf '\n%s# %s%s\n' "$D" "$*" "$X"; }
note() { printf '  %s\n' "$*"; }
shown() { local a out=; for a in "$@"; do [[ $a == *" "* ]] && a="\"$a\""; out+="$a "; done; printf '%s' "${out% }"; }
UNEXPECTED=0
# accept|refuse <cmd...>: run it, show it, and check it came out the way the demo says it will
accept() { printf '%s$ %s%s\n' "$B" "$(shown "$@")" "$X"; if "$@"; then :; else echo "UNEXPECTED: refused"; UNEXPECTED=1; fi; }
refuse() { printf '%s$ %s%s\n' "$B" "$(shown "$@")" "$X"; if "$@"; then echo "UNEXPECTED: accepted"; UNEXPECTED=1; fi; }

for who in planner builder stranger; do
  ssh-keygen -q -t ed25519 -N '' -C "$who@office" -f ".keys/$who"
done
for who in planner builder; do  # the office trusts its own two desks, not the stranger
  printf '%s@office namespaces="desk-receipt" %s\n' "$who" "$(cat ".keys/$who.pub")"
done > .office/allowed_signers

seal() {  # seal <desk> <files...>: what a session-end hook does, as a stand-in
  local who=$1; shift
  local out="receipts/$who-$(od -An -N2 -tx1 /dev/urandom | tr -d ' \n').json"
  python3 - "$who" "$@" > "$out" <<'PY'
import datetime, hashlib, json, sys, uuid
who, files = sys.argv[1], sys.argv[2:]
print(json.dumps({
    "desk": who,
    "session": str(uuid.uuid4()),
    "sealed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    "files": {f: "sha256:" + hashlib.sha256(open(f, "rb").read()).hexdigest() for f in files},
}, indent=2))
PY
  ssh-keygen -q -Y sign -f ".keys/$who" -n desk-receipt "$out" 2>/dev/null
  echo "$out"
}

# ---------------------------------------------------------------------------
say "session 1: the planner desk writes the plan; its session ends and a receipt is sealed"
cat > PLAN.md <<'EOF'
1. test_slug.py: lowercase, runs of non-alphanumerics become one hyphen, no edge hyphens
2. slug.py: slugify(text) until the tests pass
EOF
R1=$(seal planner PLAN.md)
note "wrote PLAN.md"
note "sealed $R1 (signed by planner@office)"

say "hand-off 1: the gate 'planned' wants the plan and a receipt"
accept desk deliver slug engineer plan --evidence PLAN.md
refuse desk deliver slug engineer receipt

say "someone edits the receipt after it was signed"
sed 's/planner/builder/' "$R1" > receipts/edited.json && cp "$R1.sig" receipts/edited.json.sig
refuse desk deliver slug engineer receipt --evidence receipts/edited.json

say "a key the office does not trust signs a receipt of its own"
RS=$(seal stranger PLAN.md)
refuse desk deliver slug engineer receipt --evidence "$RS"

say "the planner's real receipt"
accept desk deliver slug engineer receipt --evidence "$R1"
accept desk deliver slug owner go --note "plan reads right"

# ---------------------------------------------------------------------------
say "session 2: the builder desk, a separate session, builds what the plan says"
cat > test_slug.py <<'EOF'
import unittest

from slug import slugify


class Slug(unittest.TestCase):
    def test_lowercase(self):
        self.assertEqual(slugify("Hello World"), "hello-world")

    def test_runs_collapse(self):
        self.assertEqual(slugify("a -- b!!c"), "a-b-c")

    def test_no_edge_hyphens(self):
        self.assertEqual(slugify("  Ship it! "), "ship-it")
EOF
cat > slug.py <<'EOF'
import re


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
EOF
R2=$(seal builder slug.py test_slug.py)
note "wrote slug.py, test_slug.py"
note "sealed $R2 (signed by builder@office)"

say "hand-off 2: can the planner's receipt be reused for this gate?"
refuse desk deliver slug engineer receipt --evidence "$R1"

say "the office runs the tests itself, then takes the builder's receipt"
accept desk deliver slug engineer tests-green --evidence "python3 -m unittest"
accept desk deliver slug engineer receipt --evidence "$R2"
accept desk deliver slug owner accept --note "shipped"

# ---------------------------------------------------------------------------
say "anyone with the repo can re-check every link"
accept desk verify

say "one byte changes in an accepted receipt"
cp "$R1" "$W/r1.bak" && printf ' ' >> "$R1"
refuse desk verify
cp "$W/r1.bak" "$R1"
say "restored; the chain holds again"
accept desk verify

echo
if [ "$UNEXPECTED" -eq 0 ]; then
  printf '%severy hand-off came out as expected: 4 links accepted, 4 bad hand-offs refused, 1 tampered link caught%s\n' "$G" "$X"
else
  printf '%ssomething came out differently than this demo expects%s\n' "$R" "$X"
fi
exit "$UNEXPECTED"
