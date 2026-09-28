#!/usr/bin/env bash
# Cuts a Keelokit release from main (docs/releasing.md):
#
#   scripts/release.sh 0.5.1
#
# Turns CHANGELOG.md's "## Unreleased" heading into "## 0.5.1 — <today>", sets the version in
# .claude-plugin/plugin.json, runs the plugin's checks, commits "release: 0.5.1", and pushes main
# and then `release`. The Release workflow tags v0.5.1 on that push, and the Claude plugin
# directory picks the version up from `release`.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

fail() { echo "release: $*" >&2; exit 1; }

version=${1:-}
[[ $version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail "usage: scripts/release.sh X.Y.Z"
current=$(python3 -c 'import json; print(json.load(open(".claude-plugin/plugin.json"))["version"])')
python3 - "$current" "$version" <<'EOF' || fail "$version must be greater than $current"
import sys
old, new = (tuple(map(int, v.split("."))) for v in sys.argv[1:])
sys.exit(0 if new > old else 1)
EOF

[ "$(git rev-parse --abbrev-ref HEAD)" = main ] || fail "run it on main"
[ -z "$(git status --porcelain)" ] || fail "the working tree has uncommitted changes"
git fetch -q origin main release --tags
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] || fail "main differs from origin/main; pull or push first"
git merge-base --is-ancestor origin/release HEAD || fail "origin/release is not an ancestor of main"
! git rev-parse -q --verify "refs/tags/v$version" >/dev/null || fail "tag v$version already exists"

heading=$(grep -m1 -E '^## Unreleased( — .+)?$' CHANGELOG.md) \
  || fail "CHANGELOG.md has no '## Unreleased' section with this release's notes"
title=${heading#"## Unreleased"}
python3 - "$heading" "## $version — $(date +%F)$title" "$version" <<'EOF'
import json, re, sys
heading, new_heading, version = sys.argv[1:]
log = open("CHANGELOG.md").read()
body = log.split(heading + "\n", 1)[1].split("\n## ", 1)[0]
if not body.strip():
    sys.exit("release: the Unreleased section is empty")
open("CHANGELOG.md", "w").write(log.replace(heading + "\n", new_heading + "\n", 1))
path = ".claude-plugin/plugin.json"
text = open(path).read()
text, n = re.subn(r'"version": "[^"]*"', f'"version": "{version}"', text, count=1)
assert n == 1 and json.loads(text)["version"] == version
open(path, "w").write(text)
EOF

python3 -m unittest discover -s tests -q
if command -v claude >/dev/null; then claude plugin validate . --strict; fi

git commit -q -am "release: $version"
git push origin main
git push origin HEAD:release
echo "release: pushed $version. The Release workflow tags v$version; the directory scans it from 'release'."
# docs/releasing.md step 6. It can't be done here: CI would upgrade from a tag that doesn't exist yet.
previous=$(git tag --merged HEAD --list 'v*' --sort=-v:refname | grep -vx "v$version" | head -1 || true)
if [ -z "$previous" ] || ! git diff --quiet "$previous" HEAD -- template copier.yml; then
  echo "release: $version changed the template since ${previous:-the first release}. Once v$version exists," \
    "point the 'update from' row of .github/workflows/ci.yml at it on main (step 6);" \
    "tests/test_release.py fails until then."
fi
