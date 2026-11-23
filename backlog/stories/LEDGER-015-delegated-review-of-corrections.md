+++
id = "LEDGER-015"
epic = "LEDGER"
title = "Corrections can be approved by agents, with an adversarial review, when the person delegates it"
wave = 9
depends_on = ["LEDGER-004"]
touches = ["template/.keelokit/bin/ledger.py", ".keelokit/bin/ledger.py", "workflows/ledger-review-flow.js", "skills/check-health/SKILL.md", "template/.keelokit/bin/guard.py", ".keelokit/bin/guard.py", "template/.keelokit/bin/doctor.py", ".keelokit/bin/doctor.py", "template/.gitignore", "tests/test_ledger.py", "tests/test_guard.py", "tests/test_doctor.py", "tests/test_workflows.py", "docs/design.md", "CHANGELOG.md"]
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
