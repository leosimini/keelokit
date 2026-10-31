#!/usr/bin/env bash
# Reproduce an intermittent test; never "mark it flaky" (FLAKY-1). Runs the command N times, under CPU
# stress and in other time zones if asked, and reports how often it failed, with the first failure's tail.
#
#   .keelokit/bin/flaky.sh [-n 20] [--stress 4] [--tz "UTC Pacific/Auckland America/Sao_Paulo"] -- <command…>
#
#   -n N          runs per condition (default 20)
#   --stress K    run K busy loops beside the test (default 0; try the number of cores)
#   --tz LIST     also run under each time zone in LIST (TZ=…); the date and the clock at the edge of a day are
#                 where a test that "sometimes fails" most often lives (a faketime run: see docs/verify.md)
# Exit 1 when any run failed. The output names the cause to look for: shared data, unawaited work,
# a clock, ordering. A fix keeps the reproduction as a test and logs the guard: escapes.py add.
set -uo pipefail
n=20 stress=0 tzs=""
while [ $# -gt 0 ]; do
  case $1 in
    -n) case ${2:-} in '' | -* | *[!0-9]*) echo '-n needs a number' >&2; exit 2 ;; esac; n=$2; shift ;;
    --stress) case ${2:-} in '' | -* | *[!0-9]*) echo '--stress needs a number' >&2; exit 2 ;; esac; stress=$2; shift ;;
    --tz) case ${2:-} in '' | -*) echo '--tz needs a list of time zones' >&2; exit 2 ;; esac; tzs=$2; shift ;;
    --) shift; break ;;
    -h | --help) sed -n '2,/^set -uo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done
[ $# -gt 0 ] || { echo 'give the test command after --' >&2; exit 2; }

pids=""
cleanup() { [ -z "$pids" ] || kill $pids 2>/dev/null || true; }
trap cleanup EXIT
i=0
while [ "$i" -lt "$stress" ]; do
  (while :; do :; done) &
  pids="$pids $!"
  i=$((i + 1))
done

failures=0 total=0 first=""
for tz in "" $tzs; do
  label=${tz:-default}
  fails=0
  run=1
  while [ "$run" -le "$n" ]; do
    out=$(env ${tz:+TZ=$tz} "$@" 2>&1)
    if [ $? -ne 0 ]; then
      fails=$((fails + 1))
      [ -n "$first" ] || first="[$label, run $run] $(printf '%s' "$out" | tail -15)"
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
  echo "Reproduced: find the cause (shared data, unawaited work, a clock, ordering) and keep this as a test; never a longer timeout, a retry or a skip."
  exit 1
fi
echo "no failure in $total runs. Raise -n, add --stress or --tz before calling it fixed."
