+++
id = "LEDGER-006"
epic = "LEDGER"
title = "The doctor, the dashboard and the skills read the ledger"
wave = 11
depends_on = ["LEDGER-005"]
touches = ["template/.keelokit/bin/doctor.py", ".keelokit/bin/doctor.py", "skills/project-dashboard/scripts/dashboard.py", "template/.keelokit/bin/status.py", "skills/coordinate/SKILL.md", "skills/ship-release/SKILL.md", "skills/build-story/SKILL.md", "skills/plan-backlog/SKILL.md", "skills/keelokit/SKILL.md", "skills/check-health/SKILL.md", "skills/project-report/SKILL.md", "tests/test_doctor.py", "tests/test_dashboard.py", "tests/test_process.py", "docs/design.md", "CHANGELOG.md", "docs/ledger.md"]
dimensions = ["logic", "integrity", "dx", "docs"]
invariants = ["INV-005"]
origin = "docs/ledger.md — The principle (one reader)"
+++
## Context
Today at least four places read `Story:` trailers on their own: the doctor, the dashboard, the skills
`coordinate` and `ship-release` (in prose), and Harbor. A fix in one does not reach the others. This
story makes Keelokit's own readers ask `ledger.py` (Harbor follows in its own plan).

- The doctor takes done stories from the ledger, corrections included. TRACE-1 and INV-1 skip
  reconstructed stories, which predate those rules, and the doctor lists them apart (decision 5 in
  docs/ledger.md, accepted).
- The dashboard takes states, version and in-progress from `ledger.py --json`, and shows unknown when the
  ledger does.
- `status.py` adds what is in progress on other machines (from the ledger), next to the local worktrees.
- `build-story` runs `ledger.py show <ID>` at step 1 to see earlier attempts and findings, and at step 7
  writes the body of the `Story:` commit (what was decided, what was left out). `coordinate` checks a
  landing with `show` instead of grepping `git log`. `ship-release` lists a version's stories with
  `--release`. `plan-backlog` takes "done" from the ledger. `keelokit` routes with it. `check-health` and
  `project-report` read it.

Does NOT do: change Harbor (its own plan); enforce trailers (phase 2).

## User story
As anyone who reads the project's state through any Keelokit tool, I want them all to give the same
answer, so that the dashboard, the doctor and a session never disagree.

## Acceptance criteria
```gherkin
Scenario: [S1] The doctor and the ledger agree
  Given any repo
  Then the done count of `doctor.py --brief` equals the number of stories the ledger has on-trunk or later

Scenario: [S2] Reconstructed stories don't trip TRACE-1
  Given a story done only through an accepted backfill row, with no test citing its scenarios
  Then the doctor reports no TRACE-1 error for it and lists it among reconstructed stories

Scenario: [S3] The dashboard shows another machine's work
  Given an origin branch with Part-of: for a story, pushed from elsewhere
  Then the dashboard shows that story as in progress

Scenario: [S4] ship-release uses --release
  Then the ship-release skill builds the list of a version's stories with `ledger.py --release`

Scenario: [S5] build-story asks before starting
  Then the build-story skill runs `ledger.py show <ID>` before the contract and writes a body on the Story: commit

Scenario: [S6] Unknown stays unknown
  Given an incomplete history
  Then the doctor, the dashboard and status.py all say unknown, never a lower state
```

## Testable units
| Unit | Test type | File |
|---|---|---|
| the doctor's done set from the ledger, reconstructed stories and TRACE-1 | unit | tests/test_doctor.py |
| the dashboard's states, in-progress, unknown | unit | tests/test_dashboard.py |
| the skills' text names the ledger's commands | unit | tests/test_process.py |

## Definition of done
`scripts/verify.sh` green, every scenario covered by a test titled with its id, INV-005 cited, a
CHANGELOG line, `Story: LEDGER-006` trailer, addendum if the result differs.
