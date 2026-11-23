+++
id = "LEDGER-006"
epic = "LEDGER"
title = "The doctor, the dashboard and the skills read the ledger"
wave = 11
depends_on = ["LEDGER-005"]
touches = ["template/.keelokit/bin/doctor.py", ".keelokit/bin/doctor.py", "skills/project-dashboard/scripts/dashboard.py", "template/.keelokit/bin/status.py", "skills/coordinate/SKILL.md", "skills/ship-release/SKILL.md", "skills/build-story/SKILL.md", "skills/plan-backlog/SKILL.md", "skills/keelokit/SKILL.md", "skills/check-health/SKILL.md", "skills/project-report/SKILL.md", "tests/test_doctor.py", "tests/test_dashboard.py", "tests/test_process.py", "docs/design.md", "CHANGELOG.md", "docs/ledger.md", "docs/escapes.md"]
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

## Addendum — 2026-11-23

Decided (smallest option consistent with the story and docs/ledger.md; the coordinator's delegation, decision 7):
- One call to `ledger.py --json` per reader run (the doctor keeps its separate `ledger.py check --json` for the
  `CORRECTION_*` report, unchanged). The ledger is asked first: `NO_MAIN` stays only when it exits 2 (no trunk) and
  there is no main either (ESC-138); any other failure, a missing `.keelokit/bin/ledger.py`, an answer outside schema
  1 (stories not a list, `schema` not the number 1, `history` not text, a state that is not a text state of
  docs/ledger.md), `history = "incomplete"` or any story `unknown` make the whole backlog unknown, with the ledger's
  reason: never a lower state (S6, ESC-140, ESC-141). `snapshot:<sha>` counts as known. Fields of the wrong type
  (`branches`, `version`, `wave`, `diffs`) are ignored, not trusted.
- In a cut history every state is unknown, including a story whose `Story:` commit the clone holds: the ledger's
  rule (LEDGER-003). So LEDGER-001's tests changed where they expected that story to stay done (and TRACE-1 to check
  it), and where a shallow origin branch unrelated to main still counted: the doctor now says unknown, as the
  ledger does. The fix named is the ledger's, `ledger.py history --ensure`, in the doctor and the dashboard.
- Records are matched to story files by path, then by id, so `[ledger] id_from` and `stories` work (ESC-139). The
  doctor's done count is the ledger's on-trunk-or-later count, its total the records plus story files with no
  record; ledger-ready stories with no file here join "Next ready". The dashboard lists records with no file here
  from the record (ESC-142). A story file not on the trunk yet (a plan on a branch, a repo with no commit) has no
  record: not done, and ready once every dependency is on the trunk by the ledger (the ledger's own rule applied to
  a file it can't see yet). The doctor's backlog checks still read only `backlog/stories`.
- TRACE-1 and INV-1 skip a story whose record is `reconstructed`; the full report lists them on a line of their own
  (`Reconstructed (approved corrections; TRACE-1 and INV-1 skip them): …`). The brief is unchanged.
- The dashboard: new status `progress` ("In progress" / "En curso", with the branches) for `in-progress` and
  `delivered`; "Done · vX.Y.Z" when the ledger names a version; unknown has its own wording when the cause is the
  ledger, not a cut history. Its history timeline still lists `Story:` commits (events, not states).
- status.py: `in progress elsewhere (ledger): ID (branches)` for in-progress or delivered stories whose branches
  are not checked out here, after the verify line; per-worktree lines give way first so the doctor's backlog line
  stays within the ten (ESC-137).
- Skills: `build-story` step 1 reads `ledger.py show <ID>` and step 7 writes "Decided: … Left out: …" in the
  `Story:` commit's body; `coordinate` checks a landing with `show`; `ship-release` drafts from the `on-trunk`
  stories and confirms with `ledger.py --release vX.Y.Z` on the local tag before pushing it.
- Tests: the input-contract fixture carries ledger.py only where a test reads the backlog's count (those tests run
  the doctor thousands of times). docs/ledger.md and docs/escapes.md joined the touches.

Left as they are: a branch that edits a done story's file to another id is shown done under the new id (the path
matches; the doctor already errors on the file name); the ESC-136 grammar check runs only where python3.11 is
installed. Escape rows ESC-135..142. Review and attack: a reviewer and a breaker, two rounds (round 1: ESC-135..140;
round 2: ESC-141, ESC-142), each finding reproduced first as a failing test. No third round was run (build-story caps it at two).
