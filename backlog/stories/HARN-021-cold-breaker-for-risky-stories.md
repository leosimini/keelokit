+++
id = "HARN-021"
epic = "HARN"
title = "A risky story closes only after cold breaker rounds, recorded in its file and checked by the ledger"
wave = 4
depends_on = []
touches = ["template/.keelokit/bin/ledger.py", ".keelokit/bin/ledger.py", "template/.keelokit/risky.toml", ".keelokit/risky.toml", "copier.yml", "skills/build-story/SKILL.md", "agents/breaker.md", "skills/harness-upgrade/SKILL.md", "template/.keelokit/harness/execution-protocol.md", "template/AGENTS.md.jinja", "tests/test_breaker.py", "tests/test_copier.py", "scripts/unit_shard.py", "docs/design.md", "docs/ledger.md", "docs/escapes.md", "README.md", "README.es.md", "CHANGELOG.md", "backlog/stories/HARN-021-cold-breaker-for-risky-stories.md"]
dimensions = ["logic", "integrity", "dx", "security"]
invariants = ["INV-007"]
risky = true
+++
## Context
On the night of 2026-11-24 five stories in a row (LEDGER-010, LEDGER-011, HARN-004, LEDGER-013 and Harbor's
HRB-2 and HRB-3) passed their builder's own adversarial review with real bugs left, several HIGH. Each time a
fresh-context subagent found them: it was given only the code, the diff and the invariants, never the builder's
conclusions, and asked to report only what it reproduced, with a repro script. What worked:

1. a cold brief (the story, the diff, the invariants; nothing the builder concluded);
2. reproduced findings only;
3. each fix starts with a test that fails before it;
4. a NEW cold breaker on each new head, until a round is clean or a round cap;
5. the rounds recorded.

Until now this was a habit of one coordinator. This story makes it the rule for risky stories, in Keelokit and in
every generated project, and makes skipping it visible.

Decided (Leo, 2026-11-24, "hacela obligatoria"; the coordinator delegated the design):
- **Risky** is configured per project in `.keelokit/risky.toml` (product-owned, `_skip_if_exists`; the template
  ships defaults): a story is risky when its front matter says `risky = true`, when one of its `dimensions` is in
  the file's `dimensions`, when one of its `touches` meets the file's `paths`, or when a commit of the story on the
  trunk changes such a path. The front matter can only add risk: there is no `risky = false`.
- The rounds are recorded in the story file, `## Breaker rounds`, one line per round (head, findings, fixes, or
  `clean`) and, when the cap is hit with findings left, a person's `Decision` line.
- The ledger enforces it (it already knows what closed a story and since when, reads the trunk's committed
  rules, and its two copies are one file): `check` gives `BREAKER_MISSING` (error) and `BREAKER_UNRESOLVED`
  (warning). The doctor is left as it is.
- History is exempt by position, never by editing old stories: the rule holds for `Story:` commits that the first
  commit to bring `risky.toml` to the trunk does not reach (or its `since`), and after `[ledger] since` when set.

Does NOT do: verify that a round really happened (the line is a record, like a trailer); check a push to the trunk
in the pre-push hook (the pull request and the trunk's CI do); protect `risky.toml` with the guard (a pull request
is judged by the base's file, so it cannot loosen its own rules); change the doctor.

## User story
As a person who delegates building to agents, I want every risky story to pass cold breaker rounds before it
closes, recorded where the next session reads, and the ledger to say when one closed without them, so that the
builder's own review is never the last check on code that decides what reaches the trunk.

## Acceptance criteria
```gherkin
Scenario: [S1] What makes a story risky
  Given .keelokit/risky.toml with paths, dimensions and a round cap
  Then a story is risky by `risky = true`, by a listed dimension, by a touch that meets a path (a file, a directory
  that holds one, a glob) or by a trunk commit of it that changes such a path, and not otherwise
  And `ledger.py risky <ID>` says whether and why, and the round cap

Scenario: [S2] The template ships the defaults, the product owns them
  Then template/.keelokit/risky.toml has paths for hooks, the harness, CI workflows, scripts, migrations and auth,
  the security, auth, integrity and data dimensions and rounds = 3; copier.yml lists it under _skip_if_exists

Scenario: [S3] A risky story closed with no round is an error
  Given a risky story whose Story: commit reaches the trunk after the rule holds
  When its file has no `## Breaker rounds` entry
  Then `ledger.py check` reports BREAKER_MISSING at error level, naming the story, the reason and the fix

Scenario: [S4] The last round decides
  Given a risky story closed with recorded rounds
  Then a clean last round passes; a last round with findings and no person's Decision after it, or more rounds
  than the cap with no Decision, is BREAKER_UNRESOLVED at warning level; a Decision after it clears the warning

Scenario: [S5] Existing history is not flagged
  Given risky stories closed before the commit that brought risky.toml (or before its `since`), or before
  `[ledger] since`, or a trunk with no risky.toml
  Then `check` reports nothing about them, and no story file was edited for it

Scenario: [S6] A pull request is judged as it would land, by the base's rules
  Given a pull request that closes a risky story
  Then `check --ci` reports BREAKER_MISSING for it before it lands, reading risky.toml from the trunk (a pull
  request that empties risky.toml or drops the touches is still judged), and `--rules-ref REV` reads REV's file

Scenario: [S7] A broken record fails closed
  Given a risky.toml that is not TOML or has wrong types
  Then `check` reports BREAKER_CONFIG at error level and every closed story counts as risky
  And an entry under `## Breaker rounds` that is neither a round nor a Decision line is BREAKER_BAD_ENTRY (warning)

Scenario: [S8] The build runs the loop
  Then the build-story skill and the breaker agent describe, for a risky story: a NEW breaker per head with a cold
  brief from the story, the diff and the invariants only; reproduced findings only; each fix starts with a failing
  test; until a clean round or the cap; the round lines; and the person's decision when the cap is hit
```
Every commit that reaches the trunk after `[ledger] since` is still attributed (INV-007): this adds checks, it
removes none.

## Testable units
| Unit | Test type | File |
|---|---|---|
| risky classification, round parsing, check on the trunk and in a pull request, exemption | integration (real git) | tests/test_breaker.py |
| the template's defaults and ownership | unit | tests/test_breaker.py, tests/test_copier.py |
| the skill and agent text | unit | tests/test_breaker.py |

## Definition of done
`scripts/verify.sh` green, every scenario covered by a test titled with its id, the two ledger.py copies identical,
`Story: HARN-021` on the completing commit, this story's own breaker rounds recorded below.

## Addendum — 2026-11-25
What differs from the story as first written, all from the three cold breaker rounds (ESC-311..330):
- The rule holds from the *first* commit that brought `risky.toml` to the trunk; trunk commits that arrived before it
  are exempt; a later add moves nothing. Without `[ledger] since` the rule still holds (S5 said "and after
  `[ledger] since`": it narrows, it is not required).
- `risky.toml` gained `deciders`: the names whose Decision counts. Without it, names with agent or model words,
  digits, or look-alike letters are refused. This repo lists Leo.
- Risk is read from every copy of the story's file, its earlier version, and every commit of the story (on the trunk
  or in the pull request, before the rule too) that git finds changing a risky path; an id whose file is gone is
  judged by its commits. Unknown keys, `..` or a symlinked file fail closed.
- In a pull request `check --ci` reads the base branch's committed state.toml (the whole check, not only the
  breaker's): a pull request can no longer move its trunk or loosen its own `enforce`.
- Round 4, by the coordinator's own breaker: the rule files are always risky; a risky change with no story is
  RISKY_NO_STORY; risk is sticky across every version of the story file; a revert counts by its content, ledger-wide.
- Round 5: story versions are followed through renames; a merge's own add of risky.toml starts the rule; reverts
  match byte for byte; only the first version's `since` counts; `clean` is a round's whole result.
- Round 6: reverts compare blob ids (no binary or `.gitattributes` trick); deciders are NFKC-normalized and non-Latin
  letters need `deciders`; every story-file version is read by its own front-matter id.
- Not covered: a round line is a record, not a proof that the round ran; a person's name in a Decision is not
  verified beyond `deciders`; the pre-push hook does not check breaker rounds (the pull request and the trunk's CI do).

## Breaker rounds
- Round 1 · head 28c0111de7d35a043ebcbbba195eb4a7ef0339b3 · 6 findings: ESC-311 (×2), ESC-312, ESC-313, ESC-314, ESC-315 · fixed in 6f1fcc5
  A fresh agent ran 11 attacks with only the story, the diff and the invariants. Reproduced: a re-add or a side add
  of risky.toml moved the start (MED), a pull request's own state.toml hid its risky story (MED), no `[ledger]
  since` turned the rule off, agent-like names passed as a Decision, and a symlinked risky.toml read as absent.
  Held: multi-id commits, merges, reverts, renames, squash, fuzzed configs, git calls flat in the story count.
- Round 2 · head 6f1fcc564564b27f2d3f5359a762ae36c6780c41 · 8 findings: ESC-316 (HIGH), ESC-317 (HIGH), ESC-318, ESC-319, ESC-320, ESC-321, ESC-322, ESC-323 · fixed in the commit after 5619d93
  A new agent, cold, 12 attacks. Reproduced: a deleted, moved or broken story file hid a closed risky story; a pull
  request's own `[ledger] trunk` switched the pull-request checks off (older than this story, but it voided S6); a
  side add of risky.toml flagged history; `risky` ignored trunk commits; model names as deciders; a string or
  capitalised dimension; unknown keys read as no rule; check 25 times slower at 20k commits.
- Round 3 · head 6309fb48b5016f326e9c5aec2a034582087b3010 · 7 findings: ESC-324 (HIGH), ESC-325 (HIGH), ESC-326 (HIGH), ESC-327, ESC-328, ESC-329, ESC-330 · fixed in 1ebb9a1; the cap (3) is hit, so no round 4 without a person
  A new agent, cold, 17 attacks. Reproduced: a second file with the same id shadowed the risky one; a story's
  commits before the rule, or already on the trunk under a pull request, did not count; rewriting the front matter
  while closing opted out; round 0, 999, duplicates, long fences and HTML comments counted; `o3`, `C1aude`, a
  Cyrillic C as deciders; `..` in a path crashed check. Also noted, kept on purpose: since ESC-317 a pull request's
  attribution is judged by the base's committed `enforce`. Every finding is fixed with a test that failed first,
  but the fixes have not been attacked by a fourth breaker: the last round is not clean, so `check` says
  BREAKER_UNRESOLVED until Leo records a Decision (another round, or land as it is).
- Round 4 · head 1ebb9a11ca4184c3611b72a1276531b568aebdf1 · 5 findings: ESC-331 (HIGH), ESC-332, ESC-333, ESC-334, ESC-335 · fixed in c810182
  Run by the coordinator's own breaker on the PR head (past the cap, at the coordinator's call). Reproduced: deleting
  risky.toml switched the rule off; a risky change in a `No-story:` commit or a sync merge's own resolution was never
  judged; a story planned risky after the rule dropped its risk while closing; a revert by message only reopened a
  story. Held: a PR's own risky.toml edit, Part-of and merge attribution, planned risk, one path-limited git log,
  casefolded deciders, CRLF, broken configs. The coordinator decided each fix (ESC-331..335).
- Round 5 · head c81018280020adc96a08c61e030faf6c339a6e73 · 6 findings: ESC-336 (HIGH), ESC-337 (HIGH), ESC-338, ESC-339, ESC-340, ESC-341 · fixed in 78a6718
  A new agent, cold, 13 attacks. Reproduced: a story file renamed before the close lost its old risk; a risky.toml
  added only by a merge's own resolution never started the rule; patch-id's whitespace blindness let a dedenting
  "revert" count; a NUL in a path crashed check; a later `since` exempted a judged closure; more non-people as
  deciders and a `clean` round listing findings. Held: hunk-by-hunk merge resolutions, partial clones, 22 odd configs
  across every command, 9001-commit runtime (1.4 s vs 0.6 s).
- Round 6 · head 78a6718ad3bf36b70d3d25af0797c8d25ccbbc82 · 4 findings: ESC-342, ESC-343, ESC-344, ESC-345 · fixed in the commit after dd1ad6b; not attacked since
  A new agent, cold, 12 attacks. Reproduced: a binary change "reverted" to other bytes; a PR's own `* -diff`
  attribute faking a revert; look-alike letters of other scripts as deciders; a story re-added under a name without
  its id. Held: risky.toml as a directory, symlink or gitlink; partial clones; 16 odd configs across commands; 8000
  commits (1.6 s vs 0.6 s). Seen, not counted (outside the invariants as written): risky changes under `Part-of:` of a
  story closed before the rule, or of one already closed with rounds; a directory touch under `**/migrations/**`.
