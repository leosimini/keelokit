#!/usr/bin/env bash
# MUT-1: prove the tests of critical code notice when it breaks. Stryker mutates the files under
# the areas of .keelokit/critical.toml (flips a comparison, drops a statement, swaps + for -) and
# reruns the package's unit tests (its `test` script); a mutant that survives is a bug the suite
# would have shipped. Fails when the mutation score is under `mutation_break`. The HTML report
# lands in <package>/reports/mutation/index.html — read the survivors, then kill them with a test.
#
# Stryker's command runner, not its Vitest plugin: it works with any test script (Vitest, Jest) and
# any Vitest version. The price is no per-test coverage — every mutant reruns the package's whole
# unit suite — so keep critical areas small and their rules pure.
#
#   pnpm mutation         critical files changed since origin/main (what a pull request touches)
#   pnpm mutation --all   every critical file
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

changed=--changed
[ "${1:-}" = --all ] && changed=
files=$(python3 .keelokit/bin/doctor.py --critical $changed)
if [ -z "$files" ]; then
  echo "No critical code ${changed:+changed since origin/main }to mutate (.keelokit/critical.toml)."
  exit 0
fi
threshold=$(python3 -c 'import tomllib
print(tomllib.load(open(".keelokit/critical.toml", "rb")).get("mutation_break", 70))')
stryker=$PWD/node_modules/.bin/stryker

status=0
for pkg in $(printf '%s\n' "$files" | cut -d/ -f1-2 | sort -u); do
  if ! grep -qs '"test":' "$pkg/package.json"; then
    echo "$pkg: no \`test\` script to run against the mutants. Critical areas must live in a" \
      "package with unit tests (apps/<app> or packages/<package>)." >&2
    status=1
    continue
  fi
  printf '\n\033[1m▶ Mutating %s (break under %s%%)\033[0m\n' "$pkg" "$threshold"
  # One throwaway config per package: its critical files, the project's threshold.
  python3 - "$pkg" "$threshold" $files >"$pkg/.stryker.config.json" <<'PY'
import json, sys
pkg, threshold, files = sys.argv[1], int(sys.argv[2]), sys.argv[3:]
print(json.dumps({
    "testRunner": "command",
    "commandRunner": {"command": "pnpm test"},
    "mutate": [f[len(pkg) + 1:] for f in files if f.startswith(pkg + "/")],
    "reporters": ["clear-text", "progress", "html"],
    "htmlReporter": {"fileName": "reports/mutation/index.html"},
    "thresholds": {"high": max(threshold, 80), "low": threshold, "break": threshold},
    "tempDirName": ".stryker-tmp",
    "cleanTempDir": "always",
}, indent=2))
PY
  (cd "$pkg" && "$stryker" run .stryker.config.json) || status=1
  rm -f "$pkg/.stryker.config.json"
done
exit $status
