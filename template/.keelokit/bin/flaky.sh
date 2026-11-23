#!/usr/bin/env bash
# Reproduce an intermittent test; never "mark it flaky" (FLAKY-1, references/stable-tests.md rule 9).
# Runs the command N times, under CPU load and in other time zones if asked, and reports every failing
# run with its seed, time zone and load, then the first failure's tail.
#
#   .keelokit/bin/flaky.sh [-n 20] [--stress 4] [--tz "UTC Pacific/Auckland"] [--seed 1] -- <command…>
#
#   -n N          runs per condition (default 20)
#   --stress K    run K busy loops beside the test (default 0; try the number of cores)
#   --tz LIST     also run N times under each time zone in LIST (TZ=…): the date and the clock at the
#                 edge of a day are where a test that "sometimes fails" most often lives
#   --seed S      the first run's seed (default 1); run r gets FLAKY_SEED=S+r-1 and FLAKY_RUN=r, so a
#                 seeded generator in the test replays a failing run exactly
# Exit 1 when any run failed, 2 on a usage error. A fix keeps the reproduction as a test and logs the
# class's guard in docs/escapes.md.
set -uo pipefail
n=20 stress=0 tzs="" seed=1
# A decimal number (08 is eight: bash would read it as octal and stop counting), or exit 2.
number() { case ${2:-} in '' | -* | *[!0-9]*) echo "$1 needs a number" >&2; exit 2 ;; esac; }
while [ $# -gt 0 ]; do
  case $1 in
    -n) number -n "${2:-}"; n=$((10#$2)); shift ;;
    --stress) number --stress "${2:-}"; stress=$((10#$2)); shift ;;
    --seed) number --seed "${2:-}"; seed=$((10#$2)); shift ;;
    --tz) case ${2:-} in '' | -*) echo '--tz needs a list of time zones' >&2; exit 2 ;; esac; tzs=$2; shift ;;
    --) shift; break ;;
    -h | --help) sed -n '2,/^set -uo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done
[ $# -gt 0 ] || { echo 'give the test command after --' >&2; exit 2; }
[ "$n" -gt 0 ] || { echo '-n needs a number above 0' >&2; exit 2; }
# A misspelled zone would run under UTC and pass without testing the edge: refuse it. No glob expansion.
set -f
zoneinfo=${TZDIR:-/usr/share/zoneinfo}
for tz in $tzs; do
  [ ! -d "$zoneinfo" ] || [ -f "$zoneinfo/$tz" ] || { echo "--tz: unknown time zone: $tz (not in $zoneinfo)" >&2; exit 2; }
done

# The one-minute load average, or ? where neither Linux nor macOS gives it.
loadavg() {
  if [ -r /proc/loadavg ]; then cut -d' ' -f1 /proc/loadavg
  else sysctl -n vm.loadavg 2>/dev/null | tr -d '{}' | awk '{print $1}' | grep . || echo '?'
  fi
}

pids=""
cleanup() { [ -z "$pids" ] || kill $pids 2>/dev/null || true; }
trap cleanup EXIT
trap 'exit 130' INT TERM
i=0
while [ "$i" -lt "$stress" ]; do
  (while :; do :; done) &
  pids="$pids $!"
  i=$((i + 1))
done

failures=0 total=0 first=""
for tz in "" $tzs; do
  label=${tz:-default}
  fails=0 run=1
  while [ "$run" -le "$n" ]; do
    s=$((seed + run - 1))
    out=$(env ${tz:+TZ=$tz} FLAKY_SEED="$s" FLAKY_RUN="$run" "$@" 2>&1 </dev/null)
    if [ $? -ne 0 ]; then
      fails=$((fails + 1))
      echo "failed: run=$run seed=$s tz=$label stress=$stress loadavg=$(loadavg)"
      [ -n "$first" ] || first="[run=$run seed=$s tz=$label] $(printf '%s' "$out" | tail -15)"
    fi
    run=$((run + 1))
  done
  total=$((total + n))
  failures=$((failures + fails))
  echo "$label: $fails of $n runs failed"
done
if [ "$failures" -gt 0 ]; then
  echo "$failures of $total runs failed. First failure:"
  printf '%s\n' "$first"
  echo "Reproduced: find the cause (shared data, unawaited work, a clock, random data, ordering) and keep this as a test; never a longer timeout, a retry or a skip."
  exit 1
fi
echo "no failure in $total runs. Raise -n, add --stress or --tz before calling it fixed."
