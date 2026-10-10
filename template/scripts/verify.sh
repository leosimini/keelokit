#!/usr/bin/env bash
# The CI pipeline, run locally. The pre-push hook runs it; so does every agent before it says
# "done". Integration tests and the real-stack E2E (E2E-2) get a throwaway PostgreSQL in Docker,
# never your dev database. Mutation testing (MUT-1) is slower and runs apart: `pnpm mutation`.
#
#   pnpm verify         typecheck/test/build/e2e only for packages changed since origin/main
#                       (and their dependents); format only the changed files; lint (cached),
#                       doctor stay repo-wide; the audit reuses a green result for the same
#                       lockfile for 24 h
#   pnpm verify --all   everything, like CI
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

all=false
[ "${1:-}" = --all ] && all=true

step() { printf '\n\033[1m▶ %s\033[0m\n' "$*"; }

if git remote get-url origin >/dev/null 2>&1; then
  step 'Up to date with origin/main (GIT-1)'
  git fetch --quiet origin main || true
  if git rev-parse --verify --quiet origin/main >/dev/null &&
    ! git merge-base --is-ancestor origin/main HEAD; then
    echo 'origin/main has commits this branch lacks: git fetch && git rebase origin/main'
    exit 1
  fi
fi

if command -v gitleaks >/dev/null; then
  step 'Secret scan (gitleaks)'
  if git rev-parse --verify --quiet origin/main >/dev/null; then
    gitleaks git --log-opts='origin/main..HEAD' --redact --no-banner
  else
    gitleaks git --redact --no-banner
  fi
else
  echo '(gitleaks not installed — `brew install gitleaks`. CI still scans.)'
fi

# Root manifests and the base tsconfig reach every package: a change there means everything.
# `git diff` and pnpm's `[origin/main]` see tracked files only, so a file git doesn't track is a
# change too: an untracked manifest means everything, any other untracked file its package.
manifests='package.json pnpm-lock.yaml pnpm-workspace.yaml tsconfig.base.json'
if ! $all && git rev-parse --verify --quiet origin/main >/dev/null; then
  for f in $manifests; do
    if [ -e "$f" ] && ! git ls-files --error-unmatch -- "$f" >/dev/null 2>&1; then
      echo "$f is not tracked by git (git add it), so it can't be compared with origin/main: running everything."
      all=true
    fi
  done
  # shellcheck disable=SC2086 # $manifests is a fixed list of plain names
  git diff --quiet origin/main -- $manifests || all=true
else
  all=true
fi
scope=(-r)
if ! $all; then
  # '!{.}': a root-only change (docs, backlog) matches the root package, whose scripts recurse.
  scope=(--filter '...[origin/main]' --filter '!{.}')
  # This runs on every push and a repo can hold thousands of untracked files (a .venv, generated
  # code): builtins and expansions only, no process per file, and each directory walked up once.
  seen=$'\n' prev=
  while IFS= read -r -d '' f; do
    case $f in */*) d=${f%/*} ;; *) continue ;; esac # a root file: the root package, left out
    [ "$d" = "$prev" ] && continue
    prev=$d
    while [ ! -f "$d/package.json" ]; do
      case $d in */*) d=${d%/*} ;; *) d=. && break ;; esac
    done
    [ "$d" = . ] && continue
    case $seen in *$'\n'"$d"$'\n'*) continue ;; esac
    seen="$seen$d"$'\n'
    scope+=(--filter "...{./$d}")
  done < <(git ls-files -z --others --exclude-standard)
  echo 'Affected packages only (since origin/main); `pnpm verify --all` runs everything.'
fi
affected() { $all || pnpm "${scope[@]}" ls --depth -1 --parseable | grep -q "/$1\$"; }

has_api=false
[ -f apps/api/package.json ] && has_api=true

if $has_api; then
  step 'Prisma client'
  pnpm --filter ./apps/api prisma:generate >/dev/null
fi
step 'Format'
fmt_files=
fmt_all=$all
if ! $all; then
  # Changed and untracked files only. A change to a formatter or linter config can reclassify any
  # file, so those (like the root manifests above) mean everything.
  changed=$({ git diff --name-only --diff-filter=d origin/main; git ls-files --others --exclude-standard; } | sort -u)
  if printf '%s\n' "$changed" | grep -Eq '(^|/)(\.prettier|prettier\.config|\.editorconfig|eslint\.config)'; then
    echo 'A formatter or linter config changed: checking every file.'
    fmt_all=true
  else
    fmt_files=$changed
  fi
fi
if $fmt_all; then
  pnpm format:check
elif [ -n "$fmt_files" ]; then
  printf '%s\n' "$fmt_files" | tr '\n' '\0' | xargs -0 pnpm exec prettier --check --cache --ignore-unknown
else
  echo '(no changed files to format)'
fi
step 'Lint'
pnpm lint --cache
step 'Typecheck'
pnpm "${scope[@]}" --if-present run typecheck
step 'Harness doctor'
python3 .keelokit/bin/doctor.py --ci
step 'Unit tests'
pnpm "${scope[@]}" --if-present run test

# E2E-2 walks web/mobile against the real API: it runs when the app or the API changed.
stack_apps='' # a plain list: macOS's bash 3.2 rejects empty arrays under `set -u`
for app in web mobile; do
  [ -f "apps/$app/playwright.stack.config.ts" ] || continue
  if affected apps/api || affected "apps/$app"; then stack_apps="$stack_apps ./apps/$app"; fi
done

db=false
if $has_api && { affected apps/api || [ -n "$stack_apps" ]; }; then
  if command -v docker >/dev/null && docker info >/dev/null 2>&1; then
    step 'Throwaway PostgreSQL (migrated, seeded)'
    image=$(grep -m1 'image:' docker-compose.yml | awk '{print $2}')
    DB=$(docker run -d --rm -e POSTGRES_USER=app -e POSTGRES_PASSWORD=app -e POSTGRES_DB=app \
      -p 127.0.0.1::5432 "$image")
    trap 'docker rm -f "$DB" >/dev/null' EXIT
    port=$(docker port "$DB" 5432/tcp | head -1 | cut -d: -f2)
    export DATABASE_URL="postgresql://app:app@localhost:$port/app"
    until docker exec "$DB" pg_isready -U app -d app -h 127.0.0.1 >/dev/null 2>&1; do sleep 1; done
    sleep 2 # the image restarts once after its init scripts
    until docker exec "$DB" pg_isready -U app -d app -h 127.0.0.1 >/dev/null 2>&1; do sleep 1; done
    pnpm --filter ./apps/api prisma:migrate:deploy >/dev/null
    pnpm --filter ./apps/api db:seed >/dev/null
    db=true
  else
    echo '(Docker not running — integration and real-stack E2E skipped here; CI runs them.)'
  fi
fi

if $db && affected apps/api; then
  step 'Integration tests (real PostgreSQL)'
  pnpm --filter ./apps/api test:integration
fi

step 'Build'
pnpm "${scope[@]}" --if-present run build
step 'End-to-end journeys'
pnpm "${scope[@]}" --if-present run e2e
if $db; then
  for app in $stack_apps; do
    step "End-to-end on the real stack ($app)"
    pnpm --filter "$app" run e2e:stack
  done
fi
step 'Dependency audit'
# A green audit holds for the same lockfile for 24 h (advisories appear over time, so it expires);
# `--all` and CI always run it.
audit_stamp="$(git rev-parse --git-dir)/keelokit-audit-ok"
lock_id=$(git hash-object pnpm-lock.yaml 2>/dev/null || echo none)
if ! $all && [ -f "$audit_stamp" ] && [ "$(cat "$audit_stamp")" = "$lock_id" ] &&
  [ -n "$(find "$audit_stamp" -mmin -1440 2>/dev/null)" ]; then
  echo '(same lockfile as the last green audit, less than 24 h ago: skipped; `pnpm verify --all` runs it)'
else
  python3 .keelokit/bin/audit.py
  [ "$lock_id" = none ] || printf '%s' "$lock_id" >"$audit_stamp"
fi

printf '\n\033[32m✔ verify passed\033[0m\n'
