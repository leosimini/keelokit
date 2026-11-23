#!/usr/bin/env bash
# This repo's gates, run locally: the pre-push hook runs it, and so does every agent before it says
# "done". CI runs the same checks (.github/workflows/ci.yml); the template's end-to-end test is
# slower and stays in CI (scripts/test-template.sh runs it by hand).
set -euo pipefail
# A git hook runs this with GIT_DIR (absolute in a linked worktree) and friends exported. Every test that
# runs git in a throwaway repo would inherit them and act on this repository instead: on 2026-11-23 they
# committed fixtures to it and pushed them to origin's main (ESC-090). Git finds the repo from the
# working directory without them.
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_COMMON_DIR GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES GIT_PREFIX GIT_NAMESPACE
cd "$(git rev-parse --show-toplevel)"
step() { printf '\n\033[1m▶ %s\033[0m\n' "$*"; }

if git remote get-url origin >/dev/null 2>&1; then
  step 'Up to date with origin/main (GIT-1)'
  git fetch --quiet origin main || true
  if git rev-parse --verify --quiet origin/main >/dev/null && ! git merge-base --is-ancestor origin/main HEAD; then
    echo 'origin/main has commits this branch lacks: git fetch && git rebase origin/main (or merge it)'
    exit 1
  fi
fi

if command -v gitleaks >/dev/null; then
  step 'Secret scan (SEC-1)'
  if git rev-parse --verify --quiet origin/main >/dev/null; then
    gitleaks git --log-opts='origin/main..HEAD' --redact --no-banner
  else
    gitleaks git --redact --no-banner
  fi
else
  echo '(gitleaks not installed — `brew install gitleaks`. CI still scans.)'
fi

step 'Unit tests: guard, doctor, dashboard, workflows (QA-1)'
python3 -m unittest discover -s tests -q

if command -v claude >/dev/null; then
  step 'Plugin manifests'
  claude plugin validate . --strict
fi

step 'The plugin zip a release attaches'
scripts/package.sh HEAD "$(mktemp -d)/keelokit-plugin.zip"

step 'Harness doctor'
python3 .keelokit/bin/doctor.py --ci
