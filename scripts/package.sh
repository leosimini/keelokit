#!/usr/bin/env bash
# Builds the zip people install Keelokit from (Claude Code: /plugin install from a file; claude.ai:
# Customize → Plugins → Upload), and checks it the way claude.ai's upload does:
#
#   scripts/package.sh [ref] [out.zip]      # defaults: HEAD, dist/keelokit-plugin.zip
#
# The zip holds the plugin at its root — .claude-plugin/, skills/, agents/, workflows/, hooks/,
# references/, and the project template (template/ + copier.yml) that project-new, project-adopt
# and harness-upgrade use — plus README, CHANGELOG and LICENSE. It leaves out what only this
# repository needs: its CI (.github/), its tests and scripts, its own Keelokit harness and project
# docs (.keelokit/, docs/context, docs/bugbash, docs/security, docs/escapes.md, docs/diagnosis.md, backlog/), and its working agreement. The
# Release workflow attaches it to every GitHub Release as keelokit-plugin.zip.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

ref=${1:-HEAD}
out=${2:-dist/keelokit-plugin.zip}
fail() { echo "package: $*" >&2; exit 1; }

git rev-parse -q --verify "$ref^{commit}" >/dev/null || fail "no such commit: $ref"
mkdir -p "$(dirname "$out")"
out=$(cd "$(dirname "$out")" && pwd)/$(basename "$out")
rm -f "$out"

git archive --format=zip -o "$out" "$ref" -- . \
  ':(exclude).github' ':(exclude).claude' ':(exclude).keelokit' ':(exclude)tests' ':(exclude)scripts' \
  ':(exclude)docs/context' ':(exclude)docs/bugbash' ':(exclude)docs/security' ':(exclude)docs/escapes.md' ':(exclude)docs/diagnosis.md' ':(exclude)backlog' ':(exclude)AGENTS.md' \
  ':(exclude).gitignore' ':(exclude).githooks' ':(exclude).gitleaks.toml' ':(exclude).semgrepignore'

python3 - "$out" <<'EOF'
import json, re, sys, zipfile
path = sys.argv[1]
z = zipfile.ZipFile(path)
names = z.namelist()
def fail(msg):
    sys.exit(f"package: {msg}")
if ".claude-plugin/plugin.json" not in names:
    fail("no .claude-plugin/plugin.json at the zip's root")
version = json.loads(z.read(".claude-plugin/plugin.json"))["version"]
unsafe = [n for n in names if not re.fullmatch(r"[A-Za-z0-9._/@+-]+", n)]
if unsafe:
    fail(f"paths claude.ai rejects: {unsafe[:5]}")
for n in names:
    if re.fullmatch(r"(skills/[^/]+/SKILL|agents/[^/]+)\.md", n):
        m = re.search(r"(?m)^description:(.*)$", z.read(n).decode())
        if m and re.search(r"<[^>]+>", m.group(1)):
            fail(f"{n}: a description with tag-like text")
for need in ("skills/keelokit/SKILL.md", "hooks/hooks.json", "copier.yml", "template/"):
    if not any(x == need or x.startswith(need) for x in names):
        fail(f"missing {need}")
skills = sorted({n.split("/")[1] for n in names if n.startswith("skills/") and n.count("/") >= 2})
print(f"package: {path} — Keelokit {version}, {len(names)} entries, {len(skills)} skills")
EOF
