#!/usr/bin/env bash
# The CI pipeline, run locally. The pre-push hook runs it; so does every agent before it says
# "done". Integration tests get a throwaway PostgreSQL in Docker, never your dev database.
#
#   pnpm verify         typecheck/test/build/e2e only for packages changed since origin/main
#                       (and their dependents); lint, format, doctor and audit stay repo-wide
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
scope=(-r)
if ! $all && git rev-parse --verify --quiet origin/main >/dev/null &&
  git diff --quiet origin/main -- package.json pnpm-lock.yaml pnpm-workspace.yaml tsconfig.base.json; then
  # '!{.}': a root-only change (docs, backlog) matches the root package, whose scripts recurse.
  scope=(--filter '...[origin/main]' --filter '!{.}')
  echo 'Affected packages only (since origin/main); `pnpm verify --all` runs everything.'
else
  all=true
fi
affected() { $all || pnpm "${scope[@]}" ls --depth -1 --parseable | grep -q "/$1\$"; }

has_api=false
[ -f apps/api/package.json ] && has_api=true

if $has_api; then
  step 'Prisma client'
  pnpm --filter ./apps/api prisma:generate >/dev/null
fi
step 'Format'
pnpm format:check
step 'Lint'
pnpm lint
step 'Typecheck'
pnpm "${scope[@]}" --if-present run typecheck
step 'Harness doctor'
python3 .keelokit/bin/doctor.py --ci
step 'Unit tests'
pnpm "${scope[@]}" --if-present run test

if $has_api && affected apps/api; then
  if command -v docker >/dev/null && docker info >/dev/null 2>&1; then
    step 'Integration tests (throwaway PostgreSQL)'
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
    pnpm --filter ./apps/api test:integration
  else
    echo '(Docker not running — integration tests skipped here; CI runs them.)'
  fi
fi

step 'Build'
pnpm "${scope[@]}" --if-present run build
step 'End-to-end journeys'
pnpm "${scope[@]}" --if-present run e2e
step 'Dependency audit'
pnpm audit --audit-level=high

printf '\n\033[32m✔ verify passed\033[0m\n'
