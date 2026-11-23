+++
id = "LEDGER-015"
epic = "LEDGER"
title = "Corrections can be approved by agents, with an adversarial review, when the person delegates it"
wave = 9
depends_on = ["LEDGER-004"]
touches = ["template/.keelokit/bin/ledger.py", ".keelokit/bin/ledger.py", "workflows/ledger-review-flow.js", "skills/check-health/SKILL.md", "template/.keelokit/bin/guard.py", ".keelokit/bin/guard.py", "template/.keelokit/bin/doctor.py", ".keelokit/bin/doctor.py", "template/.gitignore", "tests/test_ledger.py", "tests/test_guard_corrections.py", "docs/escapes.md", "backlog/stories/LEDGER-004-corrections-and-backfill.md", "tests/test_doctor.py", "tests/test_workflows.py", "docs/design.md", "CHANGELOG.md"]
dimensions = ["logic", "integrity", "security", "dx"]
invariants = ["INV-002", "INV-005", "INV-008"]
origin = "docs/ledger.md — Contracts (Approval modes); Leo, 2026-11-22: reviewing hundreds of rows by hand is too much"
+++
## Context
LEDGER-004 makes a person accept every correction row. For a project adopting the ledger that can be
hundreds of rows (642 stories in JOUNA). Leo decided (2026-11-22) that the person may delegate the
approval to agents, with an adversarial review, without giving up the principle that no single agent
declares a state: the agent that proposes a row is never the one that approves it, and a delegated
approval needs two independent judges who agree after a skeptic tried to refute them. The shape follows
`check-bugbash-flow` (a skeptic reproduces each finding).

**Approval modes** (docs/ledger.md, "Approval modes"), chosen once per project by the person:

```toml
[ledger.approval]
mode = "mixed"                     # human | delegated | mixed
human_for = ["critical", "disagreement", "low-confidence"]   # mixed only
sample = 0.05                      # share of delegated approvals shown to the person for a spot check
```

The `[ledger.approval]` table has the same protection as the corrections file: the Claude hook blocks an
agent from changing it, and a commit that changes it needs `keelokit.allowTamper`. No agent authorizes
itself. Default when absent: `human` (LEDGER-004's behaviour).

**The review of one row**, in the workflow `workflows/ledger-review-flow.js` (run as
`/keelokit:ledger-review-flow`, resumable, at most N agents at once):
1. **Mechanical filter** (`ledger.py review --filter`, no model): the commit is on the trunk, the story
   exists, the row is not a duplicate, the commit's diff touches at least one path of the story's
   `touches` (when it has any), evidence is present. A row that fails is dropped and never approved.
2. **Judge A** reads the story's acceptance criteria, the commit's diff and the evidence, and answers yes or
   no, citing the files and scenarios that prove it.
3. **Judge B**, independent: the same without seeing A's answer, with another prompt (and another model
   when configured).
4. **Skeptic**: given a row both approved, tries to refute it (the commit only grazes the story, belongs to
   another one, or was reverted later).
5. **Decision:** approved only if A and B say yes and the skeptic fails. A disagreement or a refutation is
   not approved: in `mixed` the row goes to the person's queue; in `delegated` it stays pending
   (`PENDING_REVIEW` in `check`; the story is not on the trunk). A story in a critical area
   (`critical.toml`) or with the `integrity` dimension always goes to the person in `mixed`, and is judged
   by Opus in `delegated`.

**The record.** A delegated row has `approver = "delegated:<run id>"`. The verdicts of A, B and the
skeptic, with their reasons, go to `.keelokit/ledger-reviews/<run id>.json`, committed with the rows. The
ledger shows *reconstructed (person)* or *reconstructed (delegated)*. With `sample > 0` the workflow ends
by listing a random sample of the delegated rows for the person; `ledger.py review --reject-sample <run
id>` (a person only) sends every row of that run back to review, as `retract` rows.

`ledger.py backfill --accept --delegated <run id>` is what writes delegated rows. The PreToolUse hook lets
an agent run it only when `[ledger.approval] mode` is `delegated` or `mixed` and the run's review file
exists with the three verdicts per row; `--accept` without `--delegated` stays a person's. Like the rest
of the guard this is a speed bump, not a sandbox; the backstop is that everything is in git, with its
author and its verdicts, and the doctor validates every row (INV-008 still holds: rows are only added).

Does NOT do: change LEDGER-004's human mode; let a proposer approve its own rows; approve a row the
mechanical filter dropped.

## User story
As the person responsible for a project, I want to delegate the review of correction rows to agents that
check each other, and keep for myself only the critical, doubtful and disputed ones, so that adopting the
ledger does not cost me hundreds of manual reviews and the record stays trustworthy.

## Acceptance criteria
```gherkin
Scenario: [S1] The mode is the person's
  When an agent edits [ledger.approval] with a tool or the shell
  Then the Claude hook blocks it
  And a commit that changes it is refused unless keelokit.allowTamper is set

Scenario: [S2] The mechanical filter drops what it can prove wrong
  Given a proposed row whose commit is not on the trunk, or whose diff touches none of the story's paths
  Then the row never reaches a judge and is not approved

Scenario: [S3] Agreement and a failed refutation approve
  Given judges A and B say yes and the skeptic fails to refute
  Then the row is written with approver "delegated:<run id>" and its verdicts are in the review file

Scenario: [S4] Disagreement goes to the person in mixed
  Given A says yes and B says no, with mode = "mixed"
  Then the row is in the person's queue and the story is not on the trunk

Scenario: [S5] Pending in delegated
  Given the skeptic refutes, with mode = "delegated"
  Then the row is not written and `ledger.py check` reports PENDING_REVIEW for that story

Scenario: [S6] Critical stories
  Given a story in a critical area, with mode = "mixed"
  Then its row goes to the person's queue whatever the judges say

Scenario: [S7] The ledger shows who approved
  Then `ledger.py show` says "reconstructed (delegated)" or "reconstructed (person)"

Scenario: [S8] A rejected sample sends the run back
  Given the person rejects one row of a run's sample with `review --reject-sample`
  Then every row of that run gets a retract row and goes back to review

Scenario: [S9] Without delegation nothing changes
  Given no [ledger.approval] table
  Then only a person can accept rows, as in LEDGER-004

Scenario: [S10] The workflow is well formed
  Then workflows/ledger-review-flow.js passes tests/test_workflows.py (literal meta, matching phases, no clock or randomness: the sample is chosen from a hash of the run id)
```

## Testable units
| Unit | Test type | File |
|---|---|---|
| the filter, delegated accept, review file, show's origin, reject-sample, PENDING_REVIEW | unit | tests/test_ledger.py |
| protection of [ledger.approval], the delegated-accept guard | unit | tests/test_guard.py |
| the doctor validates delegated rows against their review file | unit | tests/test_doctor.py |
| the workflow's shape | unit | tests/test_workflows.py |

## Definition of done
`scripts/verify.sh` green, every scenario covered by a test titled with its id, invariants cited,
`docs/design.md` lists the workflow in its table of workflows, `check-health` explains the modes, a
CHANGELOG line, `Story: LEDGER-015` trailer, addendum if the result differs.

## Addendum — 2026-11-23

Decided (smallest option consistent with the story and docs/ledger.md; the coordinator's delegation, decision 7):
- `[ledger.approval]` is read from the trunk's committed `.keelokit/state.toml`, like the stories and the corrections,
  never from the work tree: an agent's uncommitted edit enables nothing. Absent, invalid TOML or an unknown `mode`
  is `human`; `human_for` defaults to all three reasons (an explicit `[]` stays empty); `sample` is a number in
  [0, 1], 0.05 by default.
- The table is protected three ways (S1): the Claude hook blocks an Edit/Write/MultiEdit/NotebookEdit of state.toml
  that changes the parsed `ledger.approval` value in any spelling, or moves the effective trunk (`[ledger] trunk`, else
  `[harbor] trunk`, else main) to a branch whose committed table differs (ESC-112; `/harbor:adopt` writing a trunk
  whose table is the same passes), or whose `old_string` is
  not in the file (ESC-113); it blocks every shell write that names a file `state.toml` (the corrections file's
  reading of a command, ESC-096) and every `ln`, `link`, `cp -l`/`-s` naming state.toml or the corrections file (ESC-111, ESC-119); a tool
  write through a symlink or to a hard link is judged as its target (ESC-110, ESC-119, which also closed the same hole for the corrections file and
  the registry from before this story). The pre-commit hook refuses a staged change of the table (added, removed,
  changed, made invalid, the file deleted) without `keelokit.allowTamper`. Other edits of state.toml pass.
- `ledger.py review --filter` prints JSON (run, mode, human_for, sample, rows with `critical`, dropped with the reason)
  and writes nothing. The run id is `r` + 12 hex of a sha256 of the trunk sha and the kept rows: no clock. Dropped:
  a field missing, kind not backfill/late, commit not a full sha on the trunk, an unknown or unreadable story, a
  story already on the trunk, a duplicate of an active row or of an earlier row, the commit's diff (a merge's against
  its first parent, one `git log` for all rows) touching none of the story's `touches`, and a row an earlier review (on the
  trunk, or in the work tree: failing toward the person) left to the person or pending (ESC-116: judging again until both say yes would launder a disagreement).
  `critical`: the story's touches meet a path of the trunk's critical.toml, or it declares `integrity`; an unreadable
  critical.toml makes every story critical.
- The review file `.keelokit/ledger-reviews/<run>.json` holds the rows with `judge_a`/`judge_b` (`verdict`, `reason`,
  `model`) and `skeptic` (`refuted`, …; required when both said yes). `backfill --accept --delegated <run>` (no
  terminal needed; the guard is the gate) refuses in mode human (S9), for a malformed run id (exit 1), a missing or
  invalid file, missing verdicts, a run already decided, or rows of the run already in the work tree (ESC-117: a
  resumed run appends nothing twice). It re-runs the filter, decides each row itself (never reading a `decision`
  from the file): mixed → critical or low confidence to the person when `human_for` says so, both yes and the
  skeptic failing → approved, otherwise the person (`disagreement`) or pending; delegated → a critical row whose
  three verdicts are not all by an Opus model is pending, otherwise approved or pending. It writes the decisions,
  mode, human_for and sample into the review file, appends the approved rows (approver `delegated:<run>`, today)
  without rewriting a byte, and removes approved and dropped rows from the proposed file: the person's queue and
  the pending rows stay there for `backfill --accept`. The sample is the first ceil(sample × n) approved rows by
  sha256(run + story + commit).
- A `delegated:<run>` row counts only when the trunk's review file of that run recorded mode delegated or mixed,
  holds the row approved by both judges with the refutation failed, ledger.py re-decides it as approved from the
  recorded mode, human_for, confidence and models (and, when the trunk's mode is now mixed, under the trunk's mode too:
  a review cannot record a looser mode than the person keeps, ESC-120), with `critical` and the story's `touches` read
  from the trunk tree where the row first arrived, and the commit's diff touches the story's paths; a delegated `retract` never counts (ESC-114). Else `CORRECTION_INVALID`, naming the run.
  So a project without delegation behaves as in LEDGER-004 (S9). A critical area added later, or a story's touches
  edited later, never turns an approved row invalid (ESC-120).
- The pre-commit hook lets an agent commit the corrections file without allowTamper only when HEAD's table delegates
  (and the staged one is the same), the staged file is HEAD's plus whole new rows (earlier tables unchanged), every
  new row is a backfill/late with approver `delegated:<run>`, and the staged review file of that run recorded HEAD's
  mode and approves it, re-decided from its recorded fields (ESC-115). Mode human: unchanged.
- The guard lets `python3 .keelokit/bin/ledger.py backfill --accept --delegated <run>` through, word for word, only for
  the project's own script with no `cd` in the command (ESC-118), when the trunk's committed table delegates and the
  work tree's review file has the verdicts. `--accept` without `--delegated`, any other word, a wrapper that runs it
  from a string, and `review --reject-sample` stay blocked.
- `review --reject-sample <run>` is a person's (terminal, no CLAUDECODE, `y`): a retract row per active row of the run
  (approver the person) and those rows back in the proposed file (confidence low). Retractions count once committed,
  so the filter drops those stories as on the trunk until then.
- S7: `ledger.py show <ID>` does not exist yet, so the summary says "reconstructed (person)" / "reconstructed
  (delegated)" (es: "reconstruidas (persona)" / "(delegada)") and `--json` gives each story `reconstructed_by`
  (`person`, `delegated` or null). The `correction` object is unchanged (LEDGER-004's test pins it).
- `check` warns `PENDING_REVIEW` once per story a trunk review file left to the person or pending while the story is
  not on the trunk. The doctor's code is unchanged: its CORRECTION_* reporting covers delegated rows (D11 tests).
  `template/.gitignore` and `tests/test_guard.py` stayed as they were (ESC-091: the guard's tests are in
  `tests/test_guard_corrections.py`).
- `workflows/ledger-review-flow.js`: Filter (ledger.py, relayed by a Haiku agent) → judge A and judge B with different
  prompts (B on `args.modelB`), at most `maxParallel` at once → a skeptic for rows both approved → Decide (writes the
  review file, runs the accept, one commit with `No-story: harness`; a resume skips what already happened) → Report.
  Opus judges critical rows in delegated mode.

Known speed-bump limits, as for every QA-4 protection: commits that skip pre-commit (`git stash`, `commit-tree`,
cherry-pick, rebase) and writes that name no protected file; a review file is the agents' own record, so a forged
one that is consistent passes the hook, and the backstop is git (author, verdicts), the sample and the person's
merge. Review and attack: a reviewer and a breaker, two rounds (round 1: ESC-110..118; round 2: ESC-119, ESC-120 and two
regressions of round 1's fixes, the retroactive critical check and the blocked Harbor trunk), each finding reproduced
by the verifier as a failing test and fixed. No third round was run (build-story caps it at two).

