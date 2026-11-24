+++
id = "LEDGER-012"
epic = "LEDGER"
title = "Rule LEDGER-1, and the doctor checks that its enforcers are alive"
wave = 17
depends_on = ["LEDGER-011"]
touches = ["template/.keelokit/harness/rules.toml", ".keelokit/harness/rules.toml", ".keelokit/state.toml", "template/.keelokit/bin/doctor.py", ".keelokit/bin/doctor.py", "docs/process-rules.md", "docs/design.md", "tests/test_doctor.py", "docs/escapes.md", "scripts/unit_shard.py", "CHANGELOG.md"]
dimensions = ["logic", "dx", "docs"]
invariants = []
origin = "docs/ledger.md — Mechanisms (LEDGER-1)"
+++
## Context
Keelokit's idea: every rule points to something that checks it, and the doctor says when a rule has lost
its check. The ledger's rule:

```toml
[[rule]]
id = "LEDGER-1"
level = "MUST"
rule = "Attribute every commit that reaches the trunk to a story (Story:, Part-of:) or a category (No-story:), and read the project's state only from ledger.py."
why = "On 2026-11-22 a coordinator reported six trains as never shipped that had been on main for weeks: the state was read from a shallow clone and from hand-kept rows."
enforced_by = ["git-hook:commit-msg", "git-hook:pre-push", "ci:checks", "script:.keelokit/bin/ledger.py"]
```

The doctor checks those enforcers are alive: `commit-msg`, `prepare-commit-msg` and `pre-push` present
and executable in `.githooks/` and `core.hooksPath` pointing there; the CI step of LEDGER-010 present; the
`ledger-snapshot` job present unless `snapshot = ""`; the corrections file valid. It prints the share of
unattributed commits since `since` and, under `warn`, after 3 days in a row with zero (and zero error
differences, at least 20 commits in the window), recommends `enforce = "block"`. `project-new` writes
`enforce = "block"`; `project-adopt` writes `warn` (decision 6 in docs/ledger.md). It never changes `enforce` itself. A dated exception in
`exceptions.toml` turns the rule off, as for any rule.

The CHANGELOG entry of the release that ships phase 2 has `### Upgrading from 0.15.x`: run
`harness-upgrade`, check the CI may write to the repo (workflow permissions), and leave `enforce = "warn"`
until the doctor recommends `block`.

Does NOT do: switch to block by itself.

## User story
As the person responsible for a project, I want the doctor to tell me when any piece that keeps the
ledger complete stops working, and when it is safe to block, so that I never find out from a wrong report.

## Acceptance criteria
```gherkin
Scenario: [S1] Hooks missing
  Given .githooks without commit-msg, or core.hooksPath elsewhere
  Then the doctor reports LEDGER-1 with what is missing

Scenario: [S2] The CI step missing
  Given a workflow without the ledger step
  Then the doctor reports it

Scenario: [S3] The recommendation
  Given enforce = "warn" and 3 days of trunk history, with at least 20 commits, zero unattributed and zero errors
  Then the doctor recommends enforce = "block" and does not change it

Scenario: [S4] An exception
  Given a dated LEDGER-1 exception in exceptions.toml
  Then the doctor does not report the rule's enforcers and lists the exception until it expires

Scenario: [S5] The rule ships
  Then template/.keelokit/harness/rules.toml has LEDGER-1 with the fields above, and docs/process-rules.md lists it
```

## Testable units
| Unit | Test type | File |
|---|---|---|
| LEDGER-1's enforcers, the share, the recommendation, the exception | unit | tests/test_doctor.py |

## Definition of done
`scripts/verify.sh` green, every scenario covered by a test titled with its id, a CHANGELOG line with the
upgrade section, `Story: LEDGER-012` trailer, addendum if the result differs. Then Keelokit 0.16.0 can be
released.

## Addendum — 2026-11-24

Built as specified, with these differences and decisions (none changes a product rule):

- **One line per broken hook, whichever rules need it.** LEDGER-1's `git-hook:commit-msg` and `git-hook:pre-push`
  use the same check as SEC-1 and QA-1, so a fresh clone without `core.hooksPath` (the CI of an adopted repo) gets
  the same "git hook 'X' is not installed" errors as before, no more. A git-hook problem two rules share is now one
  line, the first rule's, ending `(also QA-1, LEDGER-1)` (SEC-1/SEC-2/QA-4's `pre-commit` too). The "not installed"
  message names the missing path. `prepare-commit-msg`, which no other rule names, is checked by LEDGER-1 itself the
  same way. `.githooks/` is checked for each hook calling its `ledger.py` command on a line that isn't a comment;
  a hooks path elsewhere (husky included) passes only when its hook of that name runs the command.
- **The CI is one workflow, read on its own.** The ledger step counts only in a workflow whose `on:` has push or
  pull_request, in a job that can fail the run (no `continue-on-error`, no `if: false`, no dead job it `needs`),
  and only when the run line itself can fail (no `||`, `;` or `&` after it, no `exit` before it). The
  `ledger-config` and `ledger-snapshot` jobs must be in that same workflow: the release workflow's tag-only
  snapshot never stands in (ESC-218, ESC-219).
- **The recommendation reads only the history.** The window is the last 3 days of the trunk ending at its newest
  commit's arrival: the exact `seen` of `moves.toml` for the first-parent commit that brought it, else that
  commit's committer date. `since` counts from when it reached the trunk, and a `since` off the trunk is a LEDGER-1
  error with no share (ESC-220, ESC-221). "Zero error differences" is read as zero differences `block` would
  refuse: under `warn` the attribution codes are warnings, and switching with any of them on the trunk would turn
  the CI red. `enforce` is read as ledger.py reads it (ESC-225).
- **An exception is a warning, as for any rule.** Under a dated LEDGER-1 exception its enforcer problems are
  `warn … (excepted)` lines, not errors, and the exception is listed until it expires; the doctor keeps the debt
  visible the same way it does for every house rule, rather than hiding the lines.
- **The corrections file** stays `check_corrections`' (the `CORRECTION_*` errors), which LEDGER-1 counts among its
  enforcers without a second report.
- **This repo turns the snapshot off.** Keelokit's own CI has no `ledger-config`/`ledger-snapshot` jobs (LEDGER-011
  put them in the template only), so `.keelokit/state.toml` sets `snapshot = ""` (added to `touches`).
- **One test is missing on purpose:** a ledger step with `continue-on-error: true`. The guard (QA-4) refuses that
  literal in a commit, and only a person can approve one with `keelokit.allowTamper`. The code checks it (the
  flow-style and block-style patterns are the same `FLOW_SOFT` and the job-level check the house rules use).
