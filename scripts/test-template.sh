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

# LEDGER-011.S7, the gate of the ledger's phase 2: in a copy of the generated project with a local remote, a session
# takes a story, commits with the ledger's git hooks (Part-of: comes by itself), lands with Story:, the CI's snapshot
# records the push, a tag is pushed, the deploy job moves deploy/production, and `ledger.py show` reaches in-production
# with nobody writing a state. Only git and python3: it runs before the install. The commit hooks are the template's
# own prepare-commit-msg and commit-msg (the guard and the verify are checked elsewhere in this script).
ledger_walk() (
  step 'LEDGER-011.S7 the ledger walk: take, commit, land with Story:, snapshot, tag, deploy → in-production'
  unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_COMMON_DIR
  w=$work/walk
  mkdir -p "$w/hooks"
  git init -q --bare -b main "$w/origin.git"
  git clone -q "$dir" "$w/session"
  cd "$w/session"
  git config user.name t && git config user.email t@t
  git remote set-url origin "file://$w/origin.git"
  cp .githooks/prepare-commit-msg .githooks/commit-msg "$w/hooks/"
  git config core.hooksPath "$w/hooks"
  since=$(git rev-parse HEAD)
  git push -q origin main
  mkdir -p backlog/stories
  printf '[ledger]\nsince = "%s"\n' "$since" >.keelokit/state.toml
  printf '+++\nid = "WALK-001"\nepic = "WALK"\ntitle = "The walk"\nwave = 1\ndepends_on = []\n+++\n# The walk\n' \
    >backlog/stories/WALK-001-walk.md
  git add -A && git commit -qm 'docs: plan WALK-001' -m 'No-story: docs'
  git push -q origin main
  python3 .keelokit/bin/ledger.py take WALK-001
  echo one >walk.txt && git add walk.txt && git commit -qm 'feat: the walk, first half'
  git log -1 --format=%B | grep -qx 'Part-of: WALK-001' || { echo 'the hook did not write Part-of: WALK-001' >&2; exit 1; }
  echo two >>walk.txt && git add walk.txt
  git commit -qm 'feat: the walk' -m 'Decided: nothing to decide; it walks.' -m 'Story: WALK-001'
  before=$(git rev-parse origin/main) after=$(git rev-parse HEAD)
  git push -q origin main
  # The CI: a full clone, the snapshot job, the tag's release run and its deploy job.
  git clone -q "file://$w/origin.git" "$w/ci"
  (cd "$w/ci" && KEELOKIT_SNAPSHOT_AT=1767225600 python3 .keelokit/bin/ledger.py snapshot --run walk.1 --push "$before..$after")
  git tag -a v0.1.0 -m v0.1.0 && git push -q origin v0.1.0
  (cd "$w/ci" && git fetch -q --tags origin && python3 .keelokit/bin/ledger.py deploy production "$(git rev-parse 'v0.1.0^{commit}')")
  git fetch -q origin
  out=$(python3 .keelokit/bin/ledger.py show WALK-001)
  echo "$out"
  grep -q 'in-production' <<<"$out" || { echo 'WALK-001 did not reach in-production' >&2; exit 1; }
  grep -q '2026-01-01T00:00:00Z (exact)' <<<"$out" || { echo "WALK-001's arrival is not the snapshot's exact time" >&2; exit 1; }
  # Nobody wrote a state: the story file is as planned and no commit after the plan touched backlog/.
  [ -z "$(git log --format=%H "$since.." -- backlog/ | sed 1d)" ] || { echo 'a commit after the plan wrote backlog/' >&2; exit 1; }
  ! grep -qi 'state' backlog/stories/WALK-001-walk.md || { echo 'the story file holds a state' >&2; exit 1; }
  python3 .keelokit/bin/ledger.py take --clear
)

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
  # FLEET-003.S6, checked below: what the update did to the arch-specs, against the project as generated at $from
  # (committed just above). A project from 0.15.0 on already has them; one from before has none (ESC-187).
  arch_changes=$(git -C "$dir" status --porcelain --untracked-files=all -- packages/shared/src/arch)
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
  # 0.11.0: happy-dom 21.0.4 (two high advisories with a fix in 20.x; the audit turns red until it is bumped).
  [ -f "$dir/apps/web/package.json" ] && (cd "$dir/apps/web" && npm pkg set devDependencies.happy-dom=^21.0.4)
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
ledger_walk

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
git add -A && { git diff --cached --quiet || git -c user.name=t -c user.email=t@t commit -qm 'pnpm install' -m 'No-story: harness'; }
# project-new commits after the install, when `prepare` has turned the hooks on: the first commit of
# the whole tree must get past the guard (HARN-009). The tree is clean here, so an orphan branch
# replays that commit with the same files, and main is checked out again unchanged.
step 'First commit with the hooks on, as project-new makes it'
[ "$(git config core.hooksPath)" = .githooks ] || { echo 'pnpm install did not turn the git hooks on' >&2; exit 1; }
[ -z "$(git status --porcelain)" ] || { echo 'the tree is not clean after the install commit' >&2; exit 1; }
git checkout -q --orphan first-commit
git -c user.name=t -c user.email=t@t commit -qm 'first commit, hooks on' -m 'No-story: harness'
git checkout -q main
git branch -q -D first-commit
# PKG-3: browser installs take apt's machine-wide lock and write the shared pnpm store, so two
# runs on one machine take turns here (flock where it exists: Linux; elsewhere they don't wait).
lock="${TMPDIR:-/tmp}/keelokit-e2e-install.lock"
if command -v flock >/dev/null; then
  flock "$lock" pnpm -r --workspace-concurrency=1 --if-present e2e:install
else
  pnpm -r --workspace-concurrency=1 --if-present e2e:install
fi
# The scanners (gitleaks, semgrep) are the CI's own jobs; this script checks the template's pipeline, and a
# missing scanner now fails verify on purpose, so it is skipped knowingly here.
export KEELOKIT_ALLOW_MISSING="${KEELOKIT_ALLOW_MISSING:-gitleaks semgrep}"
pnpm verify --all

# The arch-specs ran inside verify, green on the template's own code; a planted date must turn them red.
if [ -n "$from" ]; then
  # copier.yml leaves the arch-specs out of an update: an existing codebase must not turn red.
  step 'FLEET-003.S6 an update neither adds nor removes the arch-specs'
  [ -z "$arch_changes" ] || { printf 'copier update changed packages/shared/src/arch:\n%s\n' "$arch_changes" >&2; exit 1; }
else
  step 'FLEET-003.S6 arch-specs run in verify and catch a planted literal date'
  for spec in no-literal-dates no-sleeps-in-specs no-random-test-data no-inherited-git-env; do
    [ -f "packages/shared/src/arch/$spec.arch.test.ts" ] || { echo "missing arch-spec $spec" >&2; exit 1; }
  done
  planted=packages/shared/src/planted.test.ts
  printf '%s\n' "import { expect, it } from 'vitest';" "it('is due', () => expect('2031-05-01').toBeTruthy());" >"$planted"
  if out=$(pnpm --filter ./packages/shared test 2>&1); then
    echo 'a planted literal date passed the arch-specs' >&2; exit 1
  fi
  grep -qF "$planted:2" <<<"$out" || { printf 'the arch-spec did not name %s:2\n%s\n' "$planted" "$out" >&2; exit 1; }
  rm "$planted"
  pnpm --filter ./packages/shared test >/dev/null
fi

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
