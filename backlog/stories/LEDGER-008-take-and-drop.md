+++
id = "LEDGER-008"
epic = "LEDGER"
title = "ledger.py take and drop: the story a worktree works on, and abandoned attempts"
wave = 12
depends_on = ["LEDGER-007"]
touches = ["template/.keelokit/bin/ledger.py", ".keelokit/bin/ledger.py", "template/.keelokit/bin/verify_tools.py", "template/.githooks/pre-push", "skills/build-story/SKILL.md", "template/.keelokit/harness/agent-brief.md", "tests/test_ledger.py", "tests/test_landing.py", "CHANGELOG.md"]
dimensions = ["logic", "dx"]
invariants = []
origin = "docs/ledger.md — commands (take, drop); premortem failures 3 and 4"
+++
## Context
Two findings of the premortem shaped this story. Cloud sessions work on an assigned branch
(`claude/<name>`) and Harbor vessels on names like `claude/carga-001`, so the story cannot come from the
branch name. And Keelokit's pre-push runs a full `pnpm verify` on every branch push except `wip/`, so
"taking" a story must not push anything.

- `take <ID>` checks that the story exists and is not on the trunk, enables `extensions.worktreeConfig`,
  and writes `git config --worktree keelokit.story <ID>`: each worktree of a clone has its own. If another
  origin branch already has `Part-of:` for that story, it warns and does not refuse (without Harbor,
  in-progress is a signal; LEDGER-013 delegates to Harbor's lock when there is one). `take --clear`
  removes it.
- `drop <ID> --motivo "…"` makes an empty commit `drop(<ID>): <reason>` with the reason in the body and
  the trailer `Dropped: <ID>`, and pushes it to `archive/<id>-<YYYYMMDD>`. The pre-push runs no verify for
  `archive/`, as for `wip/` (`verify_tools.py` learns a list of unverified prefixes). If that push is
  refused (a session allowed to push only its own branch), it pushes the commit on the current branch
  instead. Then it clears `keelokit.story`.
- `build-story` runs `take` at step 1, `drop` when it gives a story up, and `take --clear` once landed.
  The agent brief says the same.

Does NOT do: write the Part-of: trailer (LEDGER-009); lock anything (Harbor's HRB-2).

## User story
As a session that starts or abandons a story, I want my worktree to know which story it works on and an
abandoned attempt to stay readable, so that my commits are attributed whatever my branch is called, and
the next session sees what I tried.

## Acceptance criteria
```gherkin
Scenario: [S1] take is per worktree
  Given two worktrees of one clone
  When `take AUTH-001` runs in the first
  Then the first has keelokit.story = AUTH-001 and the second has none

Scenario: [S2] take refuses a story already on the trunk
  Given AUTH-001 is on-trunk
  Then `take AUTH-001` exits 1 and says so

Scenario: [S3] take warns about another branch
  Given an origin branch with Part-of: AUTH-002
  Then `take AUTH-002` sets the config and warns, naming that branch

Scenario: [S4] drop pushes to archive without a verify
  When `drop AUTH-002 --motivo "the API it needs is not there yet"` runs
  Then a commit with `Dropped: AUTH-002` and that reason reaches origin archive/auth-002-<date>
  And the pre-push ran no verify for it
  And `ledger.py show AUTH-002` lists it as an earlier attempt with the reason

Scenario: [S5] drop without permission for archive/
  Given the push to archive/ is refused
  Then the commit is pushed on the current branch and show still finds it

Scenario: [S6] drop and landing clear the story
  Then after drop, and after build-story lands, keelokit.story is unset in that worktree
```

## Testable units
| Unit | Test type | File |
|---|---|---|
| take, take --clear, drop, the fallback push | unit, local remote | tests/test_ledger.py |
| the pre-push's unverified prefixes (wip/, archive/) | unit | tests/test_landing.py |

## Definition of done
`scripts/verify.sh` green, every scenario covered by a test titled with its id, a CHANGELOG line,
`Story: LEDGER-008` trailer, addendum if the result differs.
