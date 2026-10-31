#!/usr/bin/env bash
# The CI pipeline, run locally. The pre-push hook runs it; so does every agent before it says
# "done". Integration tests and the real-stack E2E (E2E-2) get a throwaway PostgreSQL in Docker,
# never your dev database. Mutation testing (MUT-1) runs here too when critical code changed.
#
#   pnpm verify                typecheck/test/build/e2e only for packages changed since origin/main
#                              (and their dependents), and only the steps the change calls for
#                              (.keelokit/verify-routing.toml: docs only ⇒ seconds); format only the
#                              changed files; the audit reuses a green result for the same lockfile
#                              for 24 h
#   pnpm verify --all          everything, like CI (refuses to start on a loaded machine)
#   pnpm verify --keep-going   do not stop at the first red: run every independent step and list all
#                              the reds at the end (one fix round instead of one run per cause)
#   pnpm verify --preflight    minutes, not an hour: tools, secret scan, format, lint, typecheck,
#                              doctor. Run it before a long --all
#   pnpm verify --since REF    compare with REF instead of origin/main (a branch agent runs only its
#                              own part; the integrator runs the full one). Never sealed
#   pnpm verify --use-seal     the pre-push hook: skip the run when this exact commit already passed
#
# The local gate decides; the CI audits (nightly and by hand, docs/ci.md): the steps below are the
# CI's jobs, and .keelokit/verify-map.toml says which is which (the doctor checks it, CI-2).
# One verify runs per machine at a time (the lock below), so parallel sessions don't starve each
# other into timeouts that aren't bugs. `VERIFY_LOCK_WAIT=<seconds>` (default 1800) bounds the wait.
#
# What it leaves in the git directory (docs/verify.md): keelokit-verify.state (running / pass / fail,
# the step and the pid, so a run that was cut is noticed), .log (the whole output), .seal (the commit
# that passed), .history (one JSON line per run). Exit codes decide, never log text:
# a verify killed by a signal exits non-zero and says so.
#
# Tools the CI uses must exist here too: a missing gitleaks or semgrep fails the run, because a
# warning that scrolls by let two fake tokens reach main. To skip one knowingly:
# KEELOKIT_ALLOW_MISSING="semgrep" (names, space separated).
set -euo pipefail

all=false keep_going=false preflight=false use_seal=false base=origin/main since=false
while [ $# -gt 0 ]; do
  case $1 in
    --all) all=true ;;
    --keep-going) keep_going=true ;;
    --preflight) preflight=true ;;
    --use-seal) use_seal=true ;;
    --since)
      case ${2:-} in '' | -*) echo '--since needs a ref (a branch, tag or commit)' >&2; exit 2 ;; esac
      base=$2
      since=true
      shift
      ;;
    -h | --help) sed -n '2,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1 (see: pnpm verify --help)" >&2; exit 2 ;;
  esac
  shift
done
requested_all=$all

cd "$(git rev-parse --show-toplevel)"
common=$(cd "$(git rev-parse --git-common-dir)" && pwd)
lock="$common/keelokit-verify.lock"
log="$common/keelokit-verify.log"
state="$common/keelokit-verify.state"
seal="$common/keelokit-verify.seal"
history="$common/keelokit-verify.history"
tools=.keelokit/bin/verify_tools.py

head_sha=$(git rev-parse HEAD 2>/dev/null || echo none)
base_sha() { git rev-parse --verify --quiet "$base" 2>/dev/null || echo none; }
tree_clean() { [ -z "$(git status --porcelain 2>/dev/null)" ]; }

# The seal: the commit that passed, the base it passed against, a clean tree. Anything different
# (a new commit, a rebase that moved the base, an edit) and the run happens again.
if $use_seal && [ "${KEELOKIT_NO_SEAL:-}" != 1 ] && ! $since && [ -f "$seal" ]; then
  git fetch --quiet origin main 2>/dev/null || true
  seal_head=$(sed -n 's/^head=//p' "$seal")
  seal_base=$(sed -n 's/^base=//p' "$seal")
  seal_level=$(sed -n 's/^level=//p' "$seal")
  if [ "$seal_head" = "$head_sha" ] && [ "$seal_base" = "$(base_sha)" ] && tree_clean &&
    { [ "$seal_level" = all ] || ! $requested_all; }; then
    echo "verify: commit ${head_sha%"${head_sha#???????}"} already passed a ${seal_level} verify against $(base_sha | cut -c1-7) on $(sed -n 's/^date=//p' "$seal"); nothing changed since, so it is not repeated."
    exit 0
  fi
fi

mark=$(date +%s)
current_step=starting
steps_log=
ran=0 skipped=0
failed=
child=
set -m 2>/dev/null || true # each background job gets its own process group, so a signal reaches its children

write_state() { # key=value lines, replaced atomically
  printf 'state=%s\npid=%s\nstep=%s\nsince=%s\nhead=%s\nlevel=%s\nrc=%s\nlog=%s\n' \
    "$1" "$$" "$current_step" "$mark" "$head_sha" "$($requested_all && echo all || echo changed)" "${2:-}" "$log" \
    >"$state.$$" && mv "$state.$$" "$state"
}
say() { printf '%s\n' "$*" | tee -a "$log"; }
step() {
  now=$(date +%s)
  [ "$current_step" = starting ] || steps_log="$steps_log$((now - step_start))|$current_step
"
  current_step=$1
  step_start=$now
  ran=$((ran + 1))
  printf '\n\033[1m▶ %s\033[0m\n' "$*" | tee -a "$log"
  write_state running
}
step_start=$mark
skip() { # a step this change doesn't call for
  skipped=$((skipped + 1))
  say "▷ $1 — not needed for this change"
}

# run [--must] CMD…: output to the terminal and the log; killable by a signal; with --keep-going a
# red is recorded and the run goes on (unless the step is a prerequisite: --must).
run() {
  must=false
  [ "${1:-}" = --must ] && { must=true; shift; }
  { "$@" 2>&1 | tee -a "$log"; } &
  child=$!
  rc=0
  wait "$child" || rc=$?
  child=
  if [ "$rc" -ne 0 ]; then
    if $keep_going && ! $must; then
      failed="$failed
$current_step"
      say "✖ $current_step failed (exit $rc) — going on, --keep-going"
      return 0
    fi
    return "$rc"
  fi
}

DB=
finish() {
  rc=$?
  trap - EXIT
  [ -z "$child" ] || kill -TERM -- "-$child" 2>/dev/null || true
  [ "$current_step" = starting ] || steps_log="$steps_log$(($(date +%s) - step_start))|$current_step
"
  if [ "$rc" -eq 0 ]; then write_state pass 0; else write_state fail "$rc"; fi
  [ -z "$DB" ] || docker rm -f "$DB" >/dev/null 2>&1 || true
  if [ -n "$steps_log" ] && [ -f "$tools" ]; then
    printf '%s' "$steps_log" | python3 "$tools" table 2>/dev/null || true
    [ "$rc" -eq 0 ] || python3 "$tools" causes "$log" 2>/dev/null || true
    $preflight || python3 "$tools" record "$history" "$([ "$rc" -eq 0 ] && echo pass || echo fail)" "$rc" "$head_sha" \
      "$($requested_all && echo all || echo changed)" "$steps_log" "$failed" "$log" 2>/dev/null || true
  fi
  rm -rf "$lock"
  exit "$rc"
}
on_signal() {
  echo "verify: stopped by signal $1 at step '$current_step' (exit $2)" | tee -a "$log" >&2
  exit "$2"
}

# One verify per machine at a time. A preflight is cheap and doesn't wait.
if ! $preflight; then
  waited=0
  until mkdir "$lock" 2>/dev/null; do
    holder=$(cat "$lock/pid" 2>/dev/null || true)
    # A holder that died (or never wrote its pid) leaves a lock nobody will release.
    if { [ -n "$holder" ] && ! kill -0 "$holder" 2>/dev/null; } ||
      { [ -z "$holder" ] && [ -n "$(find "$lock" -maxdepth 0 -mmin +1 2>/dev/null)" ]; }; then
      rm -rf "$lock"
      continue
    fi
    [ "$waited" -eq 0 ] && echo "Another verify is running on this machine (pid ${holder:-?}, in $(cat "$lock/where" 2>/dev/null || echo '?')): waiting for it."
    if [ "$waited" -ge "${VERIFY_LOCK_WAIT:-1800}" ]; then
      echo "Gave up after ${waited}s waiting for the verify lock ($lock). If nothing is running, delete it."
      exit 1
    fi
    sleep 5
    waited=$((waited + 5))
  done
  echo $$ >"$lock/pid"
  pwd >"$lock/where"
fi
: >"$log"
trap finish EXIT
trap 'on_signal TERM 143' TERM
trap 'on_signal INT 130' INT
trap 'on_signal HUP 129' HUP
write_state running

# A full run of an hour must not start on a machine that is already struggling (a Mac went down
# twice under load). VERIFY_FORCE=1 starts anyway.
machine_busy() {
  load=$(awk '{print $1}' /proc/loadavg 2>/dev/null || uptime | sed 's/.*load averages*: *//' | awk '{gsub(",", "", $1); print $1}')
  cores=$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 1)
  [ -n "$load" ] && awk -v l="$load" -v c="$cores" -v f="${VERIFY_MAX_LOAD_FACTOR:-1.5}" 'BEGIN { exit !(l > c * f) }' &&
    { echo "the load average is $load on $cores cores"; return 0; }
  heavy=$(pgrep -fl 'jest|vitest|gradle|playwright test' 2>/dev/null | grep -v 'verify.sh' | head -3 || true)
  [ -z "$heavy" ] || { echo "another test run is going: $(printf '%s' "$heavy" | tr '\n' ';')"; return 0; }
  return 1
}
if $requested_all && ! $preflight && [ "${VERIFY_FORCE:-}" != 1 ]; then
  if why=$(machine_busy); then
    echo "verify --all will not start: $why. An hour-long run on a busy machine ends in a timeout or an out-of-memory kill that looks like a bug." >&2
    echo 'Wait, or VERIFY_FORCE=1 pnpm verify --all.' >&2
    exit 3
  fi
fi

if git remote get-url origin >/dev/null 2>&1; then
  step 'Up to date with origin/main (GIT-1)'
  git fetch --quiet origin main || true
  if git rev-parse --verify --quiet origin/main >/dev/null &&
    ! git merge-base --is-ancestor origin/main HEAD; then
    echo 'origin/main has commits this branch lacks: git fetch && git rebase origin/main'
    exit 1
  fi
fi

# What the CI uses must be here too (see the header).
allowed=" ${KEELOKIT_ALLOW_MISSING:-} "
need_tool() { # need_tool NAME INSTALL-HINT
  command -v "$1" >/dev/null && return 0
  case $allowed in *" $1 "*) echo "($1 not installed; skipped on purpose: KEELOKIT_ALLOW_MISSING)"; return 1 ;; esac
  echo "verify: $1 is not installed, and the CI runs it. $2" >&2
  echo "To skip it knowingly: KEELOKIT_ALLOW_MISSING=$1 pnpm verify" >&2
  exit 4
}

plan=$(python3 "$tools" plan $($requested_all && echo --all) --base "$base" || echo all)
[ -n "$plan" ] || plan=all # no answer (no python helper, an old checkout) means everything, as before routing existed
want() { case " $plan " in *" all "*) return 0 ;; *" $1 "*) return 0 ;; esac; return 1; }
case " $plan " in *" all "*) ;; *) say "Plan for this change: ${plan:-nothing beyond the always-on steps} (.keelokit/verify-routing.toml; --all runs everything)." ;; esac

if need_tool gitleaks '`brew install gitleaks`'; then
  step 'Secret scan (gitleaks)'
  if git rev-parse --verify --quiet origin/main >/dev/null; then
    run gitleaks git --log-opts='origin/main..HEAD' --redact --no-banner
  else
    run gitleaks git --redact --no-banner
  fi
fi
semgrep_ok=false
if want sast && need_tool semgrep '`brew install semgrep`'; then semgrep_ok=true; fi

# Root manifests and the base tsconfig reach every package: a change there means everything.
# `git diff` and pnpm's `[$base]` see tracked files only, so a file git doesn't track is a
# change too: an untracked manifest means everything, any other untracked file its package.
manifests='package.json pnpm-lock.yaml pnpm-workspace.yaml tsconfig.base.json'
if ! $all && git rev-parse --verify --quiet "$base" >/dev/null; then
  for f in $manifests; do
    if [ -e "$f" ] && ! git ls-files --error-unmatch -- "$f" >/dev/null 2>&1; then
      echo "$f is not tracked by git (git add it), so it can't be compared with $base: running everything."
      all=true
    fi
  done
  # shellcheck disable=SC2086 # $manifests is a fixed list of plain names
  git diff --quiet "$base" -- $manifests || all=true
else
  all=true
fi
scope=(-r)
if ! $all; then
  # '!{.}': a root-only change (docs, backlog) matches the root package, whose scripts recurse.
  scope=(--filter "...[$base]" --filter '!{.}')
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
  echo "Affected packages only (since $base); \`pnpm verify --all\` runs everything."
fi
affected() { $all || pnpm "${scope[@]}" ls --depth -1 --parseable | grep -q "/$1\$"; }

has_api=false
[ -f apps/api/package.json ] && has_api=true

if $has_api && ! $preflight; then
  step 'Prisma client'
  run --must pnpm --filter ./apps/api prisma:generate
fi

fmt_changed() { printf '%s\n' "$fmt_files" | tr '\n' '\0' | xargs -0 pnpm exec prettier --check --cache --ignore-unknown; }
if want format; then
  step 'Format'
  fmt_files=
  fmt_all=$all
  if ! $all; then
    # Changed and untracked files only. A change to a formatter or linter config can reclassify any
    # file, so those (like the root manifests above) mean everything.
    changed=$({ git diff --name-only --diff-filter=d "$base"; git ls-files --others --exclude-standard; } | sort -u)
    if printf '%s\n' "$changed" | grep -Eq '(^|/)(\.prettier|prettier\.config|\.editorconfig|eslint\.config)'; then
      echo 'A formatter or linter config changed: checking every file.'
      fmt_all=true
    else
      fmt_files=$changed
    fi
  fi
  if $fmt_all; then
    run pnpm format:check
  elif [ -n "$fmt_files" ]; then
    run fmt_changed
  else
    echo '(no changed files to format)'
  fi
else skip 'Format'; fi
if want lint; then
  step 'Lint'
  run pnpm lint --cache
else skip 'Lint'; fi
if want typecheck; then
  step 'Typecheck'
  run pnpm "${scope[@]}" --if-present run typecheck
else skip 'Typecheck'; fi
step 'Harness doctor'
run python3 .keelokit/bin/doctor.py --ci

if $preflight; then
  [ -z "$failed" ] || { say; say "Preflight found reds in:$failed"; exit 1; }
  say
  say "✔ preflight passed: tools, secret scan, format, lint, typecheck and doctor are clean. It does not run tests, build or e2e: \`pnpm verify\` still does."
  exit 0
fi

if want unit; then
  step 'Unit tests'
  run pnpm "${scope[@]}" --if-present run test
else skip 'Unit tests'; fi

# E2E-2 walks web/mobile against the real API: it runs when the app or the API changed.
stack_apps='' # a plain list: macOS's bash 3.2 rejects empty arrays under `set -u`
if want e2e-stack; then
  for app in web mobile; do
    [ -f "apps/$app/playwright.stack.config.ts" ] || continue
    if affected apps/api || affected "apps/$app"; then stack_apps="$stack_apps ./apps/$app"; fi
  done
fi

db=false
if $has_api && { { want integration && affected apps/api; } || [ -n "$stack_apps" ]; }; then
  if command -v docker >/dev/null && docker info >/dev/null 2>&1; then
    step 'Throwaway PostgreSQL (migrated, seeded)'
    image=$(grep -m1 'image:' docker-compose.yml | awk '{print $2}')
    DB=$(docker run -d --rm -e POSTGRES_USER=app -e POSTGRES_PASSWORD=app -e POSTGRES_DB=app \
      -p 127.0.0.1::5432 "$image")
    port=$(docker port "$DB" 5432/tcp | head -1 | cut -d: -f2)
    export DATABASE_URL="postgresql://app:app@localhost:$port/app"
    until docker exec "$DB" pg_isready -U app -d app -h 127.0.0.1 >/dev/null 2>&1; do sleep 1; done
    sleep 2 # the image restarts once after its init scripts
    until docker exec "$DB" pg_isready -U app -d app -h 127.0.0.1 >/dev/null 2>&1; do sleep 1; done
    run --must pnpm --filter ./apps/api prisma:migrate:deploy
    run --must pnpm --filter ./apps/api db:seed
    db=true
  else
    echo '(Docker not running — integration and real-stack E2E skipped here; CI runs them.)'
  fi
fi

if $db && want integration && affected apps/api; then
  step 'Integration tests (real PostgreSQL)'
  run pnpm --filter ./apps/api test:integration
fi

if want build; then
  step 'Build'
  run pnpm "${scope[@]}" --if-present run build
else skip 'Build'; fi
if want e2e; then
  step 'End-to-end journeys'
  run pnpm "${scope[@]}" --if-present run e2e
else skip 'End-to-end journeys'; fi
if $db; then
  for app in $stack_apps; do
    step "End-to-end on the real stack ($app)"
    run pnpm --filter "$app" run e2e:stack
  done
fi

# MUT-1: the CI's mutation job. Only when critical code changed on this branch (all of it with --all).
if want mutation && [ -f scripts/mutation.sh ]; then
  critical=--changed
  $all && critical=
  if [ -n "$(python3 .keelokit/bin/doctor.py --critical $critical 2>/dev/null)" ]; then
    step 'Mutation testing (critical code)'
    if $all; then run bash scripts/mutation.sh --all; else run bash scripts/mutation.sh; fi
  fi
fi

# SAST-1: the CI's Semgrep job.
if $semgrep_ok; then
  step 'Static analysis (Semgrep)'
  run semgrep scan --config p/typescript --config p/react --config p/secrets --error --metrics=off --quiet
fi

# Date bombs: a test that passes today and fails when the calendar moves puts main red with no code
# change. With faketime installed, `--all` reruns the unit tests a year ahead; the nightly CI does it
# too. Optional by design (it needs libfaketime), so a missing tool is a note, not a failure.
if $requested_all && ! $since; then
  if command -v faketime >/dev/null; then
    step 'Clock a year ahead (date bombs)'
    FAKETIME_DONT_FAKE_MONOTONIC=1 run faketime -f '+365d' pnpm "${scope[@]}" --if-present run test
  else
    echo '(faketime not installed — the date-bomb rerun is skipped here; the nightly CI runs it.)'
  fi
fi

if want audit; then
  step 'Dependency audit'
  # A green audit holds for the same lockfile for 24 h (advisories appear over time, so it expires);
  # `--all` and CI always run it.
  audit_stamp="$(git rev-parse --git-dir)/keelokit-audit-ok"
  lock_id=$(git hash-object pnpm-lock.yaml 2>/dev/null || echo none)
  if ! $all && [ -f "$audit_stamp" ] && [ "$(cat "$audit_stamp")" = "$lock_id" ] &&
    [ -n "$(find "$audit_stamp" -mmin -1440 2>/dev/null)" ]; then
    echo '(same lockfile as the last green audit, less than 24 h ago: skipped; `pnpm verify --all` runs it)'
  else
    run python3 .keelokit/bin/audit.py
    [ "$lock_id" = none ] || [ -n "$failed" ] || printf '%s' "$lock_id" >"$audit_stamp"
  fi
else skip 'Dependency audit'; fi

if [ -n "$failed" ]; then
  say
  say "✖ verify found reds in:$failed"
  say "  (each one ran to its end because of --keep-going; fix them all, then run once more)"
  exit 1
fi

if ! $since && tree_clean; then
  printf 'head=%s\nbase=%s\nlevel=%s\ndate=%s\n' "$head_sha" "$(base_sha)" "$($requested_all && echo all || echo changed)" "$(date -u +%FT%TZ)" >"$seal"
fi
printf '\n\033[32m✔ verify passed\033[0m (%s steps ran, %s not needed for this change)\n' "$ran" "$skipped" | tee -a "$log"
