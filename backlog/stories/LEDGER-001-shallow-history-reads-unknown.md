+++
id = "LEDGER-001"
epic = "LEDGER"
title = "With an incomplete history, the doctor and the dashboard say unknown"
wave = 5
depends_on = []
touches = ["template/.keelokit/bin/doctor.py", ".keelokit/bin/doctor.py", "skills/project-dashboard/scripts/dashboard.py", "skills/check-health/SKILL.md", "tests/test_doctor.py", "tests/test_dashboard.py", "CHANGELOG.md"]
dimensions = ["logic", "integrity", "dx"]
invariants = ["INV-005", "INV-006"]
origin = "docs/ledger.md — Why (1); JOUNA incident 2026-11-22"
+++
## Context
`done_story_ids()` reads `git log origin/main` and counts `Story:` trailers. It reports an error only
when `origin/main` is missing. On a shallow clone `origin/main` exists but its history is cut, so the
doctor counts fewer done stories and says nothing: on this repo, *16/20 done* with the full history and
*3/20 done* on a `--depth 30` clone. Cloud sessions clone shallow. The dashboard has the same reader.

This story makes every reader fail closed (docs/ledger.md, "States": a state that depends on missing
history is `unknown`). It does not complete the history; LEDGER-002 does.

Does NOT do: fetch anything; compute new states; change what counts as done (INV-005 stays as it is
until LEDGER-003).

## User story
As whoever reads the project's state (a session, the coordinator, Leo on the dashboard), I want an
incomplete history to read as unknown, so that a number I see is never silently wrong.

## Acceptance criteria
```gherkin
Scenario: [S1] A shallow clone says unknown, never a low count
  Given a repo with 16 done stories, cloned with --depth 30 so that only 3 Story: commits are in it
  When `doctor.py --brief` runs
  Then the backlog line says the count is unknown because the clone is shallow, with the number of
    commits of main it has and the command `git fetch --unshallow origin main`
  And it never prints "3/20"

Scenario: [S2] The full history is as today
  Given the same repo with its full history
  Then `doctor.py --brief` prints "16/20 done" exactly as before

Scenario: [S3] A shallow clone in CI is an error
  Given the variable CI is set and the clone is shallow
  When `doctor.py --ci` runs
  Then it reports an error that names `fetch-depth: 0` and exits non-zero (INV-006)

Scenario: [S4] The dashboard does not show stories as pending for lack of history
  Given a shallow clone
  When the dashboard data is built
  Then no story that a full history would show as done appears as ready or waiting
  And the progress figure reads unknown with the reason

Scenario: [S5] TRACE-1 and INV-1 are not run against an unknown done set
  Given a shallow clone
  Then the doctor does not report missing test citations for stories it cannot tell are done
```

## Testable units
| Unit | Test type | File |
|---|---|---|
| shallow detection (`git rev-parse --is-shallow-repository`), the brief line, the CI error | unit, against a temporary repo cloned with --depth | tests/test_doctor.py |
| the dashboard's progress and story states on a shallow clone | unit | tests/test_dashboard.py |

## Definition of done
`scripts/verify.sh` green, every scenario covered by a test titled with its id, `skills/check-health`
lists the shallow case in its table of problems, a CHANGELOG line under `## Unreleased`, `Story:
LEDGER-001` trailer on the completing commit, addendum if the result differs.
