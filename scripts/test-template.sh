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
    --update-from) from=${2:?--update-from needs a tag}; shift ;;
    -*) echo "unknown option: $1" >&2; exit 2 ;;
    *) apps=$1 ;;
  esac
  shift
done

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
dir=$work/demo
step() { printf '\n\033[1m▶ %s\033[0m\n' "$*"; }

# Copier keeps existing files, so this stub context stands in for what /keelokit:intake writes
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
else
  step "Generate $apps"
  "${copier[@]}" copy --vcs-ref HEAD --defaults "${data[@]}" "$keelokit" "$dir"
fi
commit_all generated

cd "$dir"
step 'Install'
pnpm install
pnpm -r --if-present e2e:install
pnpm verify --all
