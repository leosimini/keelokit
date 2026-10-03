#!/usr/bin/env bash
# Generates a project from this checkout (uncommitted changes included) and runs its pipeline.
#
#   scripts/test-template.sh '["api","web"]' [--postgis]   new product → pnpm verify --all
#   scripts/test-template.sh --adopt                        existing repo → only .keelokit/ added
#   scripts/test-template.sh '["api","web"]' --update-from v0.4.0
#                                                           generate at tag, update to HEAD, verify
set -euo pipefail

keelokit=$(cd "$(dirname "$0")/.." && pwd)
copier=(uvx copier==9.18.2)
apps='["api","web"]' postgis=false adopt=false from=
while [ $# -gt 0 ]; do
  case $1 in
    --postgis) postgis=true ;;
    --adopt) adopt=true ;;
    --update-from)
      case ${2:-} in ''|-*) echo '--update-from needs a tag' >&2; exit 2 ;; esac
      from=$2; shift ;;
    -*) echo "unknown option: $1" >&2; exit 2 ;;
    *) apps=$1 ;;
  esac
  shift
done

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
dir=$work/demo
step() { printf '\n\033[1m▶ %s\033[0m\n' "$*"; }

# Copier keeps existing files, so this stub context stands in for what /keelokit:plan-intake writes
# (doctor fails on an empty docs/context/).
stub_context() {
  mkdir -p "$dir/docs/context"
  for f in product domain constraints environments; do
    printf '# %s\n\nStub written by scripts/test-template.sh.\n' "$f" >"$dir/docs/context/$f.md"
  done
  printf '# Gaps\n\n| Id | File | Missing | Owner | Question | Blocking |\n|---|---|---|---|---|---|\n' \
    >"$dir/docs/context/gaps.md"
}

commit_all() { git -C "$dir" add -A && git -C "$dir" -c user.name=t -c user.email=t@t commit -qm "$1"; }

mkdir -p "$dir"
git -C "$dir" init -q -b main
stub_context

if $adopt; then
  step 'Adopt: harness-only install into an existing repo'
  printf '{\n  "name": "legacy-app",\n  "private": true\n}\n' >"$dir/package.json"
  printf '# Legacy app\n' >"$dir/README.md"
  commit_all 'existing repo'
  "${copier[@]}" copy --vcs-ref HEAD --defaults --data project_name=Legacy --data mode=harness \
    "$keelokit" "$dir"
  outside=$(git -C "$dir" status --porcelain --untracked-files=all | grep -v ' \.keelokit/' || true)
  if [ -n "$outside" ]; then
    printf 'adopt touched files outside .keelokit/:\n%s\n' "$outside" >&2
    exit 1
  fi
  step 'Adopt: run-local.sh arrives with the harness and is clean in a repo without Expo'
  [ -f "$dir/.keelokit/bin/run-local.sh" ]
  out=$(cd "$dir" && bash .keelokit/bin/run-local.sh doctor --check)
  echo "$out"
  grep -q 'no Expo app' <<<"$out"
  (cd "$dir" && python3 .keelokit/bin/doctor.py --brief && { python3 .keelokit/bin/doctor.py || true; })
  printf '\n\033[32m✔ adopt ok\033[0m\n'
  exit 0
fi

data=(--data project_name=Demo --data "apps=$apps" --data "postgis=$postgis")
if [ -n "$from" ]; then
  step "Generate at $from"
  "${copier[@]}" copy --vcs-ref "$from" --defaults "${data[@]}" "$keelokit" "$dir"
  commit_all "generated at $from"
  step 'Update to HEAD'
  (cd "$dir" && "${copier[@]}" update -a .keelokit/answers.yml --vcs-ref HEAD --defaults --conflict rej)
  rejects=$(find "$dir" -name '*.rej' -not -path '*/node_modules/*')
  if [ -n "$rejects" ]; then
    printf 'update left conflicts:\n%s\n' "$rejects" >&2
    exit 1
  fi
  # The "Upgrading" steps from CHANGELOG.md that touch product-owned files, done as a human would.
  for spec in "$dir"/apps/*/e2e/*.spec.ts; do
    [ -f "$spec" ] && ! grep -q 'E2E-1' "$spec" &&
      { printf '%s\n' '// Enforces house rule E2E-1.'; cat "$spec"; } >"$spec.tmp" && mv "$spec.tmp" "$spec"
  done
  # 0.5.0: fast-check for the property tests, and the real-stack E2E scripts (E2E-2).
  (cd "$dir/packages/shared" && npm pkg set devDependencies.fast-check=^4.10.2)
  if [ -f "$dir/apps/api/package.json" ]; then
    (cd "$dir/apps/api" && npm pkg set devDependencies.fast-check=^4.10.2)
    api_url='http://localhost:${E2E_API_PORT:-3100}'
    [ -f "$dir/apps/web/package.json" ] && (cd "$dir/apps/web" && npm pkg set \
      "scripts.e2e:stack=pnpm --dir ../api build && VITE_API_URL=$api_url vite build && playwright test -c playwright.stack.config.ts")
    [ -f "$dir/apps/mobile/package.json" ] && (cd "$dir/apps/mobile" && npm pkg set \
      "scripts.e2e=EXPO_PUBLIC_API_URL=http://api.test expo export --platform web --clear && playwright test" \
      "scripts.e2e:stack=pnpm --dir ../api build && EXPO_PUBLIC_API_URL=$api_url expo export --platform web --clear && playwright test -c playwright.stack.config.ts")
  fi
else
  step "Generate $apps"
  "${copier[@]}" copy --vcs-ref HEAD --defaults "${data[@]}" "$keelokit" "$dir"
fi
commit_all generated

# run-local.sh (RUN-1) needs no install, no Docker and no emulator: the [local] block the template
# wrote must be coherent and agree with what the script detects in the generated repo.
if [[ $apps == *mobile* ]]; then
  step 'run-local: [local] is coherent and matches the detection'
  [ -f "$dir/.keelokit/bin/run-local.sh" ]
  if [ -z "$from" ]; then
    (cd "$dir" && bash .keelokit/bin/run-local.sh doctor --check)
    (cd "$dir" && bash .keelokit/bin/run-local.sh detect | python3 -c '
import json, sys
d = json.load(sys.stdin)
want = {"mobile_dir": "apps/mobile", "pm": "pnpm"}
if "api" in sys.argv[1]:
    want.update(api_dir="apps/api", db_service="postgres")
bad = {k: (d[k], v) for k, v in want.items() if d[k] != v}
sys.exit(f"detection disagrees with [local]: {bad}" if bad else 0)' "$apps")
  fi
fi

cd "$dir"
step 'Install'
pnpm install
# pnpm-lock.yaml is part of the project: commit it, as project-new does, so verify compares it.
git add -A && { git diff --cached --quiet || git -c user.name=t -c user.email=t@t commit -qm 'pnpm install'; }
# PKG-3: browser installs take apt's machine-wide lock and write the shared pnpm store, so two
# runs on one machine take turns here (flock where it exists: Linux; elsewhere they don't wait).
lock="${TMPDIR:-/tmp}/keelokit-e2e-install.lock"
if command -v flock >/dev/null; then
  flock "$lock" pnpm -r --workspace-concurrency=1 --if-present e2e:install
else
  pnpm -r --workspace-concurrency=1 --if-present e2e:install
fi
pnpm verify --all

# MUT-1 must bite: the template's critical example passes, and the same code under a suite that
# can't fail is rejected.
step 'Mutation testing (critical code)'
pnpm mutation --all
spec=packages/shared/src/allocate.test.ts
if [ -f "$spec" ]; then
  cp "$spec" "$work/allocate.test.ts"
  printf '%s\n' "import { expect, it } from 'vitest';" "import { allocate } from './allocate.js';" \
    "it('returns parts', () => expect(allocate(1, [1])).toHaveLength(1));" >"$spec"
  if pnpm mutation --all >/dev/null 2>&1; then
    echo 'a suite that cannot fail passed mutation testing' >&2
    exit 1
  fi
  cp "$work/allocate.test.ts" "$spec"
  echo 'a suite that cannot fail was rejected ✔'
fi
