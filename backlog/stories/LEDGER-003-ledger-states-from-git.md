+++
id = "LEDGER-003"
epic = "LEDGER"
title = "ledger.py computes every story's state from git"
wave = 7
depends_on = ["LEDGER-002"]
touches = ["template/.keelokit/bin/ledger.py", ".keelokit/bin/ledger.py", "tests/test_ledger.py", "tests/test_doctor.py", "docs/design.md", "skills/project-new/SKILL.md", "skills/project-adopt/SKILL.md", "docs/context/domain.md", "CHANGELOG.md"]
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

## Addendum — 2026-11-23

Decided (smallest option consistent with docs/ledger.md; the coordinator's delegation, decision 7):
- `ledger.py` prints the summary (at most 10 lines, labels and state names in `[dashboard] lang`: `es` or English);
  `ledger.py --json` prints schema 1. Exit 0 with no difference, 1 with any entry in `diffs`, 2 for the environment:
  not a git repo, a trunk that does not resolve or is not a branch name, a git call that fails during the read, a story
  file that cannot be read and has no EPIC-NNN prefix in its name.
- The trunk ref is `origin/<trunk>`, else `<trunk>`, never HEAD. Stories are read from the trunk's tree, not the
  working tree (the fact behind `defined`); a duplicate id keeps the first path in sorted order. `since` must look like
  a sha (7–64 hex) or it is ignored.
- `on-trunk`: the oldest non-reverted `Story:` commit by trunk arrival. `since` is the committer date (UTC) of the
  first-parent trunk commit that brought it, `since_exact = false`, and null below `on-trunk`.
- Reverts: `This reverts commit <full sha>.` and git's `-m 1` form (`, reversing changes made to …`). Reverting a merge
  (on the first-parent chain or inside a branch) reverts every commit reachable from it and not from its first parent;
  a reverted revert does not count. An
  abbreviated sha in a revert body is not resolved (git always writes the full one).
- Tags: `v<N>(.<N>)*` with an optional `-rc.<N>`, in version order (rc before its final), peeled fully. Only a final
  tag makes `in-version`; the first rc tag containing the commit is the new key `candidate`. Other `v*` tags are ignored.
- `environments` holds the deploy branch's head sha when it contains the commit, else null (also when the branch
  does not exist).
- `branches`: every origin branch whose history off the trunk reaches a `Part-of:` commit, listed whatever the state;
  `in-progress` only when nothing higher holds; `stale` from the newest `Part-of:` commit's committer date.
- A dependency with no such story is not met; a dependency whose state is unknown makes the dependent unknown,
  settled over the whole graph. While any story file is unreadable, a dependency id with no readable record is
  unknown too (the file may hold it), and a readable story wins a duplicate id over an unreadable one.
- Fail closed: a shallow boundary with a missing parent under the trunk, the `v*` tags, the deploy branches or any
  origin branch makes the history `incomplete`, every state `unknown` with the reason (`history --ensure` as the fix),
  and `HISTORY_INCOMPLETE` (error when `CI` is set, else warning). A story blob absent from a partial clone is never
  fetched lazily (in a partial clone one `rev-list --objects --missing=print` finds them): that story is `unknown`
  with the reason, its id from the file name's EPIC-NNN prefix; an unreadable file without one exits 2. A shallow
  origin branch unrelated to the trunk also makes the history incomplete: broader than needed, never a wrong state,
  and `history --ensure` clears it.
- New keys in schema 1: `candidate`, `reason`, `path`. `unattributed` counts trunk commits after `since` with none of
  `Story:`/`Part-of:`/`No-story:` and not brought by a merge that carries one; no `since` gives 0.
- The doctor does not read `[ledger]` (ledger.py does), so its input-contract test lists it as not read, like `[dashboard]`
  and `[run]`; tests/test_doctor.py joined the touches for that line.

Measured: 9 git calls per read whatever the number of stories (one more with a nested tag, two more in a shallow
clone); the branches holding each `Part-of:` commit come from one pass over the commits off the trunk (2 000
branches along a 10 000-commit chain under the budget); this repo
reads in about 0.1 s, the 10 000-commit, 700-story fixture well under the 2 s budget.

Escape rows ESC-063..065 and ESC-080..084 are in docs/escapes.md. Left out: commit 4135645 (the first implementation)
lacks its `Part-of:` trailer and was not rewritten; nothing reads the ledger yet (the doctor and the dashboard move
to it in LEDGER-006).
