+++
id = "HARN-022"
epic = "HARN"
title = "The last breaker round decides past the cap, risky work after a close needs a story, and LEDGER-014's low findings"
wave = 26
depends_on = ["HARN-021", "LEDGER-014"]
touches = ["template/.keelokit/bin/ledger.py", ".keelokit/bin/ledger.py", "skills/build-story/SKILL.md", "agents/breaker.md", "skills/plan-backlog/SKILL.md", "template/.keelokit/harness/execution-protocol.md", "tests/test_breaker.py", "tests/test_ledger_swarm.py", "tests/test_ledger.py", "scripts/unit_shard.py", "docs/design.md", "docs/ledger.md", "docs/escapes.md", "CHANGELOG.md", "backlog/stories/HARN-022-breaker-cap-and-residuals.md"]
dimensions = ["logic", "integrity", "security", "dx"]
invariants = ["INV-007"]
risky = true
+++
## Context
HARN-021 made cold breaker rounds the rule for risky stories, and LEDGER-014 taught the ledger Swarm's deliveries.
Both landed with residuals the coordinator listed on 2026-11-25 (Leo's standing authorization of 2026-11-23/24):

- **The cap.** A story whose rounds went past the cap stayed `BREAKER_UNRESOLVED` until a person wrote a
  `Decision`, even when a later round was clean. A clean last round is the evidence the loop exists for; the cap is
  the point where the build stops and asks, not a debt the record keeps.
- **HARN-021, round 6, seen and not counted:** (1) a risky change committed under `Part-of:` (or `Story:`) of a story
  already closed — before the rule, or with its rounds — was never judged: the rounds of the closed story did not see
  it, and the story is not closed again; (2) a story touching a directory (`apps/api`) did not meet a glob that lives
  beneath it (`**/migrations/**`).
- **LEDGER-014, the coordinator's final breaker (low):** (1) `attributing_merges` walked each merge of an arrival
  group separately: O(merges × group); (2) a shallow clone kept a snapshot's `in-progress` delivery after it was
  merged and reverted; (3) Unicode format characters (bidi overrides, zero-width) and line/paragraph separators
  reached the terminal in authors and subjects; (4) `show` asked git for authors twice.

Decided (the coordinator delegated the design):
- **A.** The last recorded round decides, whatever its number: clean → resolved. Not clean → `BREAKER_UNRESOLVED`
  until another round is clean or a person's `Decision` follows it; the warning says which (below the cap: the next
  round; at or past it: a person). The cap stays where the build must stop and ask.
- **B1.** `RISKY_AFTER_CLOSE` (error), the sibling of `RISKY_NO_STORY`: after the rule's start, a commit (or a merge's
  own resolution) that changes a risky path, names stories, and every story it names was already closed by a live
  `Story:` commit that landed earlier (a strictly earlier arrival on the trunk; for a pull request, any trunk close).
  A change after the close is new work: it names an open story, which then needs its own rounds. Commits of the same
  landing as the close (the closing branch's own later commits) are part of that close, judged by its rounds. Chosen
  over "a reopening that needs its own round line" because a round line cannot be tied to a later commit (its head
  is often not on the trunk after a squash), and the fix is the same either way: a story with rounds.
- **B2.** A touch whose last part has no extension (`apps/api`, `.github`, `scripts`) or ends in `/` names a
  directory: it meets every glob that can match a path beneath it. A touch with an extension stays a file.

Does NOT do: change the verdicts of HARN-021 or LEDGER-014 (their last rounds were not clean; Leo decides them), edit
their story files, or verify that a round ran.

## User story
As the person who decides when the breaker loop stops, I want a clean last round to close a risky story whatever its
number, every risky change after a close to need a story with rounds, and the ledger's swarm reading to stay fast,
current and terminal-safe, so that the record says what the code went through and nothing slips past it.

## Acceptance criteria
```gherkin
Scenario: [S1] (A) The last round decides, past the cap too
  Given a risky story closed with more rounds than the cap
  When its last round is clean
  Then check reports nothing about it, with no Decision
  When its last round left findings and the cap is reached
  Then BREAKER_UNRESOLVED says a person decides (another round, or land as it is), and a Decision after it clears it
  When its last round left findings below the cap
  Then BREAKER_UNRESOLVED says the next round runs (a person's Decision also clears it)

Scenario: [S2] (A) The build is told
  Then build-story, the breaker agent, design.md, ledger.md, the execution protocol and the story template say the
  last round decides and the cap is where the build stops and asks

Scenario: [S3] (B1) Risky work after a close needs an open story
  Given a story closed on the trunk (before the rule, or after it with its rounds)
  When a later landing brings a commit, or a merge's own resolution, under its Part-of:/Story: that changes a risky path
  Then check reports RISKY_AFTER_CLOSE at error level, on the trunk and in a pull request
  And a commit that also names an open story, the closing branch's own later commits, a reverted close, and a change
  to no risky path are not reported

Scenario: [S4] (B2) A directory touch meets the globs beneath it
  Given risky.toml with `**/migrations/**`
  Then a story touching `apps/api` or `apps/api/` is risky, and one touching `apps/api/page.ts` is not

Scenario: [S5] (C1) Finding a delivery's story is near-linear
  Given an arrival group of 2000 attributing merges over a 20 000-commit side chain
  Then attributing_merges reads the graph a number of times proportional to the group, not merges × group

Scenario: [S6] (C2) A shallow clone re-checks a snapshot's in-progress delivery
  Given a snapshot taken while a delivery was in progress, then the delivery merged and reverted
  Then a depth-3 clone reading the snapshot does not show it in-progress

Scenario: [S7] (C3) No format character reaches the terminal
  Then bidi overrides (U+202E, U+2066..2069), zero-width characters and U+2028/2029 in an author, a subject or any
  other free text show or check prints are replaced, on the swarm path and on the trunk's subjects

Scenario: [S8] (C4) show asks git for authors once
  Then `show` and `show --json` make one `git log --no-mailmap` call
```
Every commit after `[ledger] since` is still attributed (INV-007): this adds a check, it removes none.

## Testable units
| Unit | Test type | File |
|---|---|---|
| the last round decides, the cap's message | integration (real git) | tests/test_breaker.py |
| RISKY_AFTER_CLOSE on the trunk and in a pull request | integration (real git) | tests/test_breaker.py |
| directory touches | integration (real git) | tests/test_breaker.py |
| the process text | unit | tests/test_breaker.py |
| attributing_merges' cost (graph reads counted) | unit | tests/test_ledger_swarm.py |
| shallow snapshot re-check, format characters, one authors call | integration (real git) | tests/test_ledger_swarm.py |

## Definition of done
`scripts/verify.sh` green, every scenario covered by a test titled with its id, the two ledger.py copies identical,
`Part-of: HARN-022` on every commit and `Story: HARN-022` on the completing one, this story's breaker rounds recorded
below.

## Breaker rounds
- Round 1 · head c73efb63428d4e8d20e8aa985ed51e206e060a7b · 4 findings: ESC-356, ESC-357, ESC-358, ESC-359 · fixed in the commit after b677096
  A fresh agent, cold, 10 attacks. Reproduced: the closing branch's later commit landed by fast-forward read as
  RISKY_AFTER_CLOSE on the trunk though its pull request was clean; a newline in a story file name forged a `check`
  line; the one-pass merge walk's memory grew with the square of the commits when every one was wanted; a snapshot's
  in-progress delivery survived a squash landing in a shallow clone. Held: the merge walk against the old one on 6000
  random graphs, shallow clones at depth 1/2/3/6 across commands, the screen's callers, the authors reuse, the
  directory globs, the last-round verdict. Seen, not counted: `next` and `--release` printed titles raw (screened
  with ESC-357); `glob_regex` reads `[...]` literally where git reads a class (older than this story).
- Round 2 · head 4d5c0c63fc39d58c28169397bafe56371e65f585 · 5 findings: ESC-360, ESC-361, ESC-362, ESC-363, ESC-364 · fixed in the commit after 93154f0
  A new agent, cold, 9 attacks. Reproduced: the closing branch landed by rebase read as RISKY_AFTER_CLOSE on the
  trunk while its pull request was clean; `./`, `/` and `.` as touches met nothing; with a wide frontier the merge
  walk's memory still grew faster than linear; `risky` and the session summary printed format characters raw; a
  branch named with U+2028, U+2029 or U+0085 broke every command (older than this story). Held: the merge walk
  against base on 6000 random graphs with several SWARM_MERGES values, multi-id, revert and merge/squash landings,
  every screened output path, the snapshot re-check, the authors reuse. Kept on purpose: at most SWARM_BITS ×
  SWARM_PASSES (4096) pieces per arrival are attributed through merges (information only, as SWARM_MERGES).
- Round 3 · head 7c18f960bcbac5deca2f1c51fe7872ca9bd6335f · 4 findings: ESC-365, ESC-366, ESC-367, ESC-368 · fixed in the commit after 51decaa; the cap (3) is hit, so no round 4 without a person
  A new agent, cold, 10 attacks. Reproduced: a `No-story:` commit between the close and a fix the round saw read as
  RISKY_AFTER_CLOSE after a rebase landing; a fix after the round was recorded passed the pull request and a merge
  landing and failed only after a fast-forward (the landing decided); `apps/v1.2/.` counted as a file; the pre-push
  hook printed branch names raw. Held: the merge walk against base on 3000 random graphs, with budgets 1..4 and many
  passes; every screened output path of show, check, next, --release, risky, history and attribution; a story renamed
  after a rebase landing; git_lines; the authors reuse; the cap verdict. Every finding is fixed with a test that failed
  first (RISKY_AFTER_CLOSE now has one rule for every landing and the pull request; every write to the terminal is
  screened), but the fixes have not been attacked by a fourth breaker: the last round is not clean, so `check` says
  BREAKER_UNRESOLVED until a person records a Decision (another round, or land as it is).
- Round 4 · head 185749e6f7db2ebcc032134f0f6530c4970f877c · 4 findings: ESC-369 (HIGH), ESC-370, ESC-371, ESC-372 · fixed in the commit after c4241b2
  Run by the coordinator's own breaker on the PR head, past the cap at the coordinator's call. Reproduced: renaming
  the story file hid RISKY_AFTER_CLOSE (the recording commit was looked for by the current path); a revert of a
  reviewed fix after the close was exempt; a clean last round never had to see the code that lands (a risky commit
  after its head, a head that is no commit of the close); `.` and `..` inside a touch. Held: round parsing, a Decision
  followed by a clean round, UNKNOWN_STORY on a mixed trailer, ordinary post-close commits, the screen, fail-closed
  exit codes. The coordinator decided each fix (ESC-369..372).
- Round 5 · head 2b1dc5e2fe7a96d9d558719ef891e9a63c702699 · 5 findings: ESC-373, ESC-374, ESC-375, ESC-376, ESC-378 (and ESC-377 seen) · fixed in the commit after ea5d1f8
  A new agent, cold, 9 attacks, at the coordinator's call after round 4. Reproduced (each run by the builder too):
  RISKY_AFTER_CLOSE trusted the commit recording the last round without asking that round's head to reach the change;
  a "revert" of a sha that is no commit made git fail and the revert check believed the message; change_ids still
  split git's raw output with str.splitlines; BREAKER_STALE read every path-limited merge as a risky change; build-story
  step 7.1 rebases after the rounds, and a squash lands new commits, so ESC-371's reachability makes a clean round a bad
  entry (and the message says it "left findings"). Held: the merge walk against base on 5000 random graphs, the copies,
  the screen on a non-UTF-8 id. Past the cap and not clean, so the builder stopped; the coordinator decided each fix
  (merge main after the rounds instead of rebasing; STALE covers the Story: commit; clearer messages), then round 6.
- Round 6 · head 8be6b367759ee7f85a4e41e6c1d81fbb461d177a · 2 findings: ESC-379 (HIGH), ESC-380 · fixed in the commit after 023eaf6
  A new agent, cold, 9 attacks. Reproduced: a risky commit of the story that landed before the close outside its
  ancestry (a parallel delivery) was judged by nothing; a round resolved by a Decision covered risky commits made after
  its head. Held: a story built exactly as build-story says, checked as a pull request and on the trunk; reverts of
  every kind; multi-id, unknown and lowercase ids; 36 touch spellings; the merge walk against base on 3000 random
  graphs; 14 hostile characters through every output; one authors call in show.
