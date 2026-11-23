+++
id = "LEDGER-005"
epic = "LEDGER"
title = "ledger.py show, next and check, with the why of every story"
wave = 10
depends_on = ["LEDGER-015"]
touches = ["template/.keelokit/bin/ledger.py", ".keelokit/bin/ledger.py", "tests/test_ledger.py", "docs/design.md", "CHANGELOG.md"]
dimensions = ["logic", "dx", "docs"]
invariants = []
origin = "docs/ledger.md — Contracts (commands, difference codes); premortem failure 6"
+++
## Context
The rework that started this epic comes from decisions and failed attempts nobody wrote down: a state
alone does not say why. `show` gathers the why from the places it already lives, so a new session asks
instead of investigating (docs/ledger.md, "`ledger.py` commands").

- `show <ID> [--full]`: state and date (exact or approximate), commits with their subject and
  `Claude-Session:`, version, environments, branches, the story file and its *Addendum* headings, and the
  why: bodies of its `Story:` and `Part-of:` commits, rows of `docs/escapes.md` and findings in
  `docs/bugbash/` that name the id or arrive through a `Finding:` trailer on its commits, attempts
  (`Dropped:` commits on any remote branch), corrections. At most 60 lines; paths, not long contents.
- `next`: `ready` stories that are not `in-progress`, by wave and id.
- `check [--ci] [--json]`: every difference of docs/ledger.md, "Exit codes and difference codes", with its
  level and exit code.
- `--release vX.Y.Z`: the stories that entered that version (the commits between the previous tag and it).

Does NOT do: change any state; read Harbor (LEDGER-013) or swarm branches (LEDGER-014); enforce anything.

## User story
As a session that starts without context, I want one command that tells me a story's state and why it
ended up that way, so that I don't redo work or investigations someone already did.

## Acceptance criteria
```gherkin
Scenario: [S1] show gathers the why
  Given a done story whose Story: commit has a body, whose file has an Addendum, and a row of docs/escapes.md that names it
  When `ledger.py show <ID>` runs
  Then the output has the body, the addendum heading and the escape row, each with its path

Scenario: [S2] show lists an abandoned attempt
  Given a `Dropped: <ID>` commit on an origin branch with its reason
  Then show lists it as an earlier attempt with the reason and the branch

Scenario: [S3] show finds findings through Finding:
  Given a commit of the story with `Finding: LOG-303` and a bug-bash report that has LOG-303
  Then show lists LOG-303 with the report's path

Scenario: [S4] next excludes work in progress
  Given two ready stories, one of them with a Part-of: branch
  Then next lists only the other

Scenario: [S5] check finds an unknown id
  Given a trailer `Story: NOPE-001` on the trunk
  Then check reports UNKNOWN_STORY and exits 1

Scenario: [S6] check warns about a stale branch
  Given an in-progress branch with no commit for more than stale_days
  Then check reports STALE_BRANCH as a warning and exits 0

Scenario: [S7] --release
  Given tags v1.0.0 and v1.1.0 and two Story: commits between them
  Then `--release v1.1.0` lists exactly those two stories

Scenario: [S8] show is bounded
  Given a story with more than 60 lines of material
  Then show prints at most 60 lines and says how to see the rest (--full)
```

## Testable units
| Unit | Test type | File |
|---|---|---|
| show's sources, its bound, next, check's codes and exit, --release | unit, synthetic repos | tests/test_ledger.py |

## Definition of done
`scripts/verify.sh` green, every scenario covered by a test titled with its id, a CHANGELOG line,
`Story: LEDGER-005` trailer, addendum if the result differs.
