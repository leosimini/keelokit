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
- Round 7 · head ec74f2f1c8bf480168fff2f68064138caa78326a · 3 findings: ESC-381 (HIGH, two of them), ESC-382 (HIGH) · fixed in the commit after d39941b; 2 LOW to HARN-023
  A new agent, cold, 9 attacks, each finding run by the builder too. Reproduced: (HIGH) build-story's own flow — a
  round, then `git merge --no-ff origin/main`, then Story: — is BREAKER_STALE (with a trailer) or RISKY_NO_STORY
  (without one, at base too) whenever another closed story changed the same risky file on main: merge_own_hits reads
  `git log --cc --name-only`, which names files merged cleanly from both sides; (MEDIUM) a merge whose resolution takes
  the other parent's version of a risky file undoes a reviewed fix unseen (the same `--cc`, the other way round);
  (HIGH) a `merge -s ours` of a risky post-close commit, landed and then reverted, makes revert_status count that commit
  as reverted while its change stays on the trunk, hiding RISKY_AFTER_CLOSE. LOW: a Decision after a squash landing
  turns the warnings into BREAKER_STALE (its head resolves to nothing); parse_trailers and breaker_record still split
  with str.splitlines (a U+2028 forges a Swarm-Task trailer). Held: 34 touches × 8 patterns, a real revert of reviewed
  work, git_lines, the screen on every path, attributing_merges, the authors reuse. The builder stopped; the coordinator
  decided each fix (a merge's own change from `git merge-tree`; merge reverts path by path).
- Round 8 · head 1db12ad430ae0c4cd5db2cca0981f41e71031682 · 4 findings: ESC-383 (two HIGH), ESC-384 (HIGH), ESC-385 · fixed in the commit after 043094e; 1 LOW to HARN-023
  A new agent, cold, 9 attacks, scratch clones only; each finding run by the builder too. Reproduced: (HIGH) one old
  merge of unrelated histories makes `git merge-tree --stdin` stop the whole batch, so with the whole history every
  later risky-path merge fails closed (RISKY_NO_STORY and BREAKER_STALE on build-story's own landing; the pull request
  check, which excludes the trunk, passes); (HIGH) reverting another story's reviewed risky commit under `Part-of:` of
  any closed story is exempt (the exemption reads "not reached by this story's close" as "unreviewed"); (HIGH)
  reverting a fix a re-close reviewed is exempt under the same story (only the earliest close is asked); (MEDIUM) the
  pull request check reads only the pull request's own merges for BREAKER_STALE, so a risky trunk merge the last round
  never saw passes it and fails on the trunk. LOW: a newline in a story title forges a line in `show`. Held: the
  merge walk against base on 3000 random graphs, merge-tree and diff-tree parsing for clean, conflicted,
  identical-parent and ancestor-parent merges, the other output paths. The builder stopped; the coordinator decided:
  the revert exemption goes (a revert of a risky change is itself a risky change), merge-tree allows unrelated
  histories and retries merge by merge, the pull request reads the trunk's own-change merges.
- Round 9 · head 76a6bf9252cc4836505cd3f2184fc2136934f47d · 3 findings: ESC-386 (HIGH), ESC-387, ESC-388 · fixed in the commit after 3670f61
  A new agent, cold, 9 attacks, scratch clones only; each finding run by the builder too. Reproduced: (HIGH, a
  regression from base) git merge-tree follows renames, so a `No-story:` edit at a non-risky path that a risky story
  renamed into a risky path lands in the risky file as "automatic", and both checks pass (base's combined diff
  caught it); (MEDIUM) two merges with the same parents and tree collapse into one diff-tree header, so a recreated
  merge that brings back a risky change hides behind the original when its sha sorts first (the trunk passes, the
  pull request fails); (MEDIUM) a later `Story:` commit on a branch that does not reach the first close anchors the
  round's head check and BREAKER_STALE on itself, clearing STALE for a risky commit no round saw, and turning a correct
  story's round into a bad entry. Held: 200k fuzzed touches, diff-tree echo format, the revert and merge-revert reading,
  the screen, the authors reuse, attributing_merges. The builder stopped; the coordinator decided each fix.
- Round 10 · head 71dc136a7edae7650fb6f68c970555e0596ad626 · 2 findings (1 HIGH, 1 MEDIUM), fixed (ESC-389)
  A new agent, cold, 9 attacks, scratch clones only; each finding run by the builder too. Reproduced: (HIGH) the rename
  check runs `git diff-tree -M` with the default rename limit (1000), so a commit with more than 1000 inexact renames
  hides a rename into a risky path that git's merge (a higher limit, only the sources the other side changed) still
  follows: an edit at the old path lands in the risky file and both checks pass (caught at 5 renames, missed at 1100);
  (MEDIUM) once any risky rename exists on either side, every risky path that differs from every parent counts, so a
  clean sync merge of a risky file both sides edited is BREAKER_STALE when the other side also renamed an unrelated
  risky file (build-story's own flow). Held: fake reverts by blob id, unknown ids in trailers, the screen under C and
  C.UTF-8, the two copies, the pull request and the trunk agreeing. The builder stopped; the coordinator decided: rename
  detection is gone, a per-path rename-free 3-way merge decides what a merge brings of its own.
- Round 11 · head ceba4eaaabd36c8381249c3e8c68217653174992 · 4 findings (1 HIGH, 2 MEDIUM, 1 LOW), fixed (ESC-390; the LOW one in HARN-023)
  A new agent, cold, scratch clones only; each HIGH and MEDIUM finding run by the builder too. Reproduced: (HIGH) the
  per-path check decodes diff-tree's path names with replacement characters and then asks `ls-tree` for that name, so
  a risky path that is not valid UTF-8 reads as absent everywhere and never counts: round 9's rename carry into
  `0002_\xffseed.sql` passes both checks, on the trunk and in a pull request (caught before ESC-389); (MEDIUM) the
  per-path merge is not git's: a mode change on one side with an edit on the other, or a `merge=union` attribute,
  merges cleanly in git and has no result here, so build-story's own clean sync merge is BREAKER_STALE; (MEDIUM)
  `git merge-file` and git's merge (ort, histogram) disagree on some clean text merges (4 in 3000 fuzzed), with the
  same false BREAKER_STALE; (LOW, to HARN-023) a cost per risky path per merge (600 paths: 5.0 s against 0.2 s).
  Held: symlinks, gitlinks, delete against edit, add/add and binaries fail closed; no single merge base and octopus
  fail closed; newlines, tabs, leading dashes and glob characters in paths; hash-object with no filters; the two
  copies; the round 9 and 10 tests. The builder stopped; the coordinator decided: path names stay raw bytes, and
  the per-path merge applies only where a rename can fill a path (absent at the base or in a parent); a file present
  everywhere is judged by git's merge alone.
- Round 12 · head 58632d85489b5cb6000afdf4eecbfbf38e9a119c · 3 findings (1 MEDIUM, 2 LOW), the MEDIUM accepted, the LOWs to HARN-023
  A new agent, cold, scratch clones only; the MEDIUM finding run by the builder too. Reproduced: (MEDIUM) a clean sync
  merge reads as BREAKER_STALE, in the pull request and on the trunk, when one side renamed a risky file to another
  risky path (with or without an edit) and the other side edited it: the new path is absent at the base and in a
  parent, and the rename-free per-path merge disagrees with git, which carries the edit along the rename (since
  ESC-389); (LOW, to HARN-023) raw_pair_states' parse cost; (LOW, to HARN-023, older than this story) a directory
  symlink hides a migration from the path rule. Held: no rename carry into an existing risky file (git's merge does no
  break detection), directory renames conflict and count, octopus fails closed, the raw parser, the pull request and
  the trunk agreeing, the round 9 to 11 tests. The builder stopped. The MEDIUM finding: accepted: fail-closed
  limitation, documented (coordinator decision, 2026-11-28); pinned by a test, in design.md, ledger.md and
  build-story, and in HARN-023 for a fix that does not depend on rename detection.
- Round 13 · head 0b3f225d9e1bfed462d3652add7cda2db578fef7 · 3 findings (1 HIGH, 1 MEDIUM, 1 LOW), fixed (ESC-391, ESC-392; the LOW one in HARN-023)
  A new agent, cold, scratch clones only, told the accepted limitation; the HIGH and MEDIUM findings run by the
  builder too. Reproduced: (HIGH) `pair_diffs` looks for a merge's diff-tree header at the start of every field,
  path fields included, and git allows a newline in a path: a risky file named "<auto tree> <merge tree>\n<path>" of
  another listed merge, present at the base and in both parents (so only the merge-tree diff judges it), swallows a
  merge's own change, on the trunk and in a pull request; (MEDIUM) under `enforce = "warn"` an id with no story file
  in the trailer (`Part-of: AUTH-001, ZZZ-999`, or `Part-of: ZZZ-999`) counts as an open story, so RISKY_AFTER_CLOSE
  and RISKY_NO_STORY give way to an UNKNOWN_STORY warning and the risky change lands with exit 0 (the RISKY_NO_STORY
  half older than this story); (LOW, to HARN-023, older than this story) `release_only` exempts any `*/package.json`.
  Held: the merge listing (-s ours, the other parent's version), per_path_own's absent states, raw_pair_states and the
  other parsers, the screen, RISKY_AFTER_CLOSE ordering, same-arrival commits, squash and revert re-closes. The
  builder stopped; the coordinator decided: git output carrying paths is read by position only, a risky path with a
  control character makes the merge its own, and an id with no story file never counts as an open story.
- Round 14 · head 00f2d160767f2f09b21dfb1ffd5daf793b151213 · 2 findings (1 MEDIUM, 1 LOW), fixed (ESC-393)
  A new agent, cold, scratch clones only, told the accepted limitation, pointed at the parsers and the trailer ids; the
  MEDIUM finding run by the builder too. Reproduced: (MEDIUM) in a pull request the known ids are the trunk's stories
  plus the head's, so an id whose story file the pull request itself deletes still counts as an open story there:
  under `enforce = "warn"` the pull request exits 0 with only UNKNOWN_STORY and STALE_BRANCH warnings, and once merged
  the trunk reports RISKY_NO_STORY (the pull request and the trunk disagree; ESC-392's hole on the pull request path);
  (LOW, to HARN-023) the control-character fallback flags non-risky conflicted paths. Held: raw_pair_states,
  merge_trees, the C-quoted text parsers, DEL and C1 controls, NUL in messages, ids in other case, lookalikes and
  zero-width forms, the mixed trailer, a closed story's file deleted after its close, the full test_breaker suite. The
  builder stopped; the coordinator decided: a pull request knows the story ids at its head only, and the LOW finding
  is fixed here too (only a risky conflicted path counts; the globs classify any name).
- Round 15 · head 4629bef8ec1fb6e3cc4d8a22672d89e4af68c065 · 2 findings (1 HIGH, 1 MEDIUM), fixed (ESC-394, ESC-395)
  A new agent, cold, scratch clones only, told the accepted limitation; each finding run by the builder too.
  Reproduced: (HIGH) `git merge-tree` reads `.gitattributes` from the work tree, and `.gitattributes` is no risky
  path: a `No-story: docs` commit adding `**/migrations/** merge=union` makes a conflict on a risky file merge
  "cleanly", so build-story's sync merge that unions a reviewed fix back into the old line passes the pull request and
  the trunk, and a BREAKER_STALE already on the trunk clears once the file is committed later, or only sits in a local
  work tree; (MEDIUM) a conflicted path counts only when `glob_regex` matches a risky glob, but git's `:(glob)`
  pathspecs read a directory (`infra`), a trailing slash (`infra/`) and a class (`infra/[a-z]*.bin`) more widely:
  `risky_commits` sees `infra/blob.bin` as risky while a sync merge resolving a binary conflict on it by keeping the
  branch's bytes (dropping main's reviewed fix) is not counted, on the trunk and in a pull request. Held: the pull
  request's known ids, re.DOTALL, risky conflicted paths only, directory renames, non-UTF-8 conflicted names, the full
  test_breaker suite. The builder stopped; the coordinator decided: git's merge read with no attributes (a
  non-empty info/attributes fails closed), `.gitattributes` always risky, a union-merged sync merge accepted as a
  second fail-closed limitation, and every risky-path verdict from git's own pathspec.
- Round 16 · head 112702f0f96538049ee48d245b15ce254563e79f · 5 findings (2 MEDIUM, 1 LOW-MEDIUM, 2 LOW), fixed (ESC-396)
  A new agent, cold, scratch clones only, told both accepted limitations, pointed at git configuration and path
  classification; the MEDIUM and LOW-MEDIUM findings run by the builder too. Reproduced: (MEDIUM) `log.diffMerges`
  (first-parent, combined, dense-combined) changes what `git log -m` lists, so merge_own_hits never sees a sync
  merge that keeps the branch's version of a risky file: the pull request and the trunk pass where the baseline is
  BREAKER_STALE (`rule_adds` reads `-m` the same way); (MEDIUM) the system attributes file (`/etc/gitattributes`)
  still steers git's merge with no warning (no `GIT_ATTR_NOSYSTEM`); (LOW-MEDIUM) `merge.default` from config or
  `GIT_CONFIG_COUNT` turns an own-change merge into a clean one; (LOW, to HARN-023, older than this story)
  `GIT_LITERAL_PATHSPECS=1` turns every risky pathspec literal; (LOW, to HARN-023) a reversed class range in
  risky.toml crashes `check`. Held: round 15's fixes, `**/.gitattributes` matching, git's pathspec in every verdict
  path, the parents' trees in risky_paths_of, the two copies. The builder stopped; the coordinator decided: one
  hermetic environment for every git read, explicit flags and pins over config, a local merge or diff driver fails
  closed (MERGE_CONFIG); both LOW findings fixed here too.
- Round 17 · head 76e7f8d92754c02247437cbc0d8158ed40f95f18 · 4 findings (1 MEDIUM, 1 LOW-MEDIUM, 2 LOW), fixed (ESC-397)
  A new agent, cold, scratch clones only, told both accepted limitations, pointed at everything outside the committed
  content; the MEDIUM and LOW-MEDIUM findings run by the builder too. Reproduced: (MEDIUM) `merge_config` reads
  `git config --local --includes`, which never reads `$GIT_DIR/config.worktree` (on with `extensions.worktreeConfig`,
  which the ledger itself turns on for `keelokit.story`), while git's merge does; and the `merge.default=text` pin
  makes git look for a user-defined driver named `text` first, so `merge.text.driver` in `config.worktree` runs inside
  the ledger's merge-tree and a hand-made union reads as automatic: exit 0 where the baseline is BREAKER_STALE, in a
  linked worktree too; (LOW-MEDIUM) `merge_config` fails closed on any `merge.*` key, also ones merge-tree never reads
  (`merge.ff`, `merge.tool`, `merge.log`, `merge.conflictStyle`), so build-story's clean flow gets RISKY_AFTER_CLOSE and
  BREAKER_STALE errors; (LOW, to HARN-023) a local `trailer.separators` changes which story a commit names; (LOW, to
  HARN-023) local replace refs and a FIFO at `info/attributes`. Held: round 16's fixes, 30 other repository-local
  keys, the linked worktree's verdict, the two copies, the full test_breaker suite. The builder stopped; the
  coordinator decided: no merge.default pin, git's own view of every config scope scanned for steering keys only, the
  LOW findings fixed here too, and the threat model written down (design.md, "Who decides").
