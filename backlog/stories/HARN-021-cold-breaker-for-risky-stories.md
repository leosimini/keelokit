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

## Breaker rounds
- Round 1 · head 28c0111de7d35a043ebcbbba195eb4a7ef0339b3 · 6 findings: ESC-311 (×2), ESC-312, ESC-313, ESC-314, ESC-315 · fixed in the commit after fec8dcb
  A fresh agent ran 11 attacks with only the story, the diff and the invariants. Reproduced: a re-add or a side add
  of risky.toml moved the start (MED), a pull request's own state.toml hid its risky story (MED), no `[ledger]
  since` turned the rule off, agent-like names passed as a Decision, and a symlinked risky.toml read as absent.
  Held: multi-id commits, merges, reverts, renames, squash, fuzzed configs, git calls flat in the story count.
