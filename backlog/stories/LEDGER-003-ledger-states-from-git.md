+++
id = "LEDGER-003"
epic = "LEDGER"
title = "ledger.py computes every story's state from git"
wave = 7
depends_on = ["LEDGER-002"]
touches = ["template/.keelokit/bin/ledger.py", ".keelokit/bin/ledger.py", "tests/test_ledger.py", "docs/design.md", "skills/project-new/SKILL.md", "skills/project-adopt/SKILL.md", "docs/context/domain.md", "CHANGELOG.md"]
dimensions = ["logic", "integrity", "data", "dx", "nfr"]
invariants = ["INV-005"]
origin = "docs/ledger.md — Contracts (Configuration, States, --json)"
+++
## Context
The core of the ledger: one reader of the facts, which every other tool will use (LEDGER-006). It reads
`[ledger]` from `.keelokit/state.toml` (docs/ledger.md, "Configuration"), finds the stories by the
`stories` glob with the id from the front matter or from the file name (`id_from`), and computes the
states of docs/ledger.md, "States", except the ones that need Harbor (`delivered`) or corrections
(LEDGER-004).

Facts read, each with a fixed number of git calls:
- the trunk's log with trailers and bodies (`Story:`, reverts: `This reverts commit <sha>.`), and for each
  `Story:` commit the first-parent commit of the trunk that brought it, whose committer date is the
  approximate arrival (`since_exact = false`);
- `git log --remotes=origin --not <trunk> --source` for `Part-of:` on any remote branch → `in-progress`,
  with the `stale` signal after `stale_days`;
- `v*` tags in order, as commit ranges → `in-version` (the first tag containing the commit);
- `origin/deploy/staging` and `origin/deploy/production`, when present → `in-staging`, `in-production`.

It prints a summary of at most 10 lines, or `--json` (schema 1). It fails closed: with an incomplete
history every state that depends on it is `unknown`, with the reason.

**Decided (docs/ledger.md, "Decisions", 1):** INV-005 becomes *a story is on the trunk iff a commit
reachable from the trunk carries its `Story:` trailer, or an approved correction names it, and no revert of
that commit is on the trunk.* This story rewrites INV-005 in `docs/context/domain.md` and implements the
revert part; LEDGER-004 implements the corrections part.

`project-new` writes `[ledger] since` = the first commit; `project-adopt` writes it = the adoption commit.

Does NOT do: write anything; read Harbor or Swarm (LEDGER-013, 014); `show`, `next`, `check`
(LEDGER-005); corrections (LEDGER-004).

## User story
As any tool or session that needs a story's state, I want one reader that derives it from facts, so that
every answer is the same and none depends on someone remembering to update it.

## Acceptance criteria
```gherkin
Scenario: [S1] A Story: commit on the trunk
  Given a commit with `Story: AUTH-001` reachable from the trunk
  Then AUTH-001 is on-trunk with that commit's hash and an approximate date

Scenario: [S2] A tag that contains it
  Given a tag v1.2.0 that contains that commit
  Then AUTH-001 is in-version with v1.2.0

Scenario: [S3] Work in progress on any branch
  Given an origin branch named claude/xyz with a commit `Part-of: AUTH-002` not on the trunk
  Then AUTH-002 is in-progress with that branch

Scenario: [S4] A revert
  Given a revert of AUTH-001's Story: commit on the trunk
  Then AUTH-001 is ready, marked reverted

Scenario: [S5] Dependencies
  Given AUTH-003 depends on AUTH-004
  Then AUTH-003 is defined while AUTH-004 is not on-trunk, and ready once it is

Scenario: [S6] Incomplete history
  Given a shallow clone
  Then the states that depend on history are unknown, with the reason, and the summary says so

Scenario: [S7] Ids from file names
  Given `id_from = "filename"` and story files without front matter named UXC-113-something.md
  Then UXC-113 is read with its title from the first heading

Scenario: [S8] Another trunk
  Given `[harbor] trunk = "develop"`
  Then the states are measured against develop

Scenario: [S9] Deploy branches
  Given origin/deploy/production contains AUTH-001's commit
  Then AUTH-001 is in-production

Scenario: [S10] The budget
  Given a synthetic repo with 10 000 commits and 700 stories
  Then `ledger.py --json` finishes in under 2 seconds and makes a number of git calls that does not grow with the stories
```

## Testable units
| Unit | Test type | File |
|---|---|---|
| each state and its precedence, reverts, dependencies, ids from file names, trunk | unit, synthetic repos built by the test with a local remote | tests/test_ledger.py |
| the JSON schema 1 keys | unit | tests/test_ledger.py |
| the performance budget and the number of git calls | unit | tests/test_ledger.py |

## Definition of done
`scripts/verify.sh` green, every scenario covered by a test titled with its id, INV-005 cited by a test,
`docs/design.md` gains a short "The ledger" section pointing to docs/ledger.md, the two skills write
`[ledger] since`, a CHANGELOG line, `Story: LEDGER-003` trailer, addendum if the result differs.
