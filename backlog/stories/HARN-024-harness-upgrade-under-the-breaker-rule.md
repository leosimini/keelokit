+++
id = "HARN-024"
epic = "HARN"
title = "A harness upgrade, and an accepted correction, land without RISKY_NO_STORY"
wave = 28
depends_on = ["HARN-022"]
touches = ["skills/harness-upgrade/SKILL.md", "template/.keelokit/bin/ledger.py", ".keelokit/bin/ledger.py", "tests/test_breaker.py", "docs/ledger.md", "docs/escapes.md", "CHANGELOG.md", "backlog/stories/HARN-024-harness-upgrade-under-the-breaker-rule.md"]
dimensions = ["logic", "dx"]
invariants = []
risky = true
+++
## Context
**Blocks the next Keelokit release** (coordinator, 2026-11-28): without it, every project that upgrades as the skill
says fails its CI once risky.toml is on its trunk.

HARN-022's cold breaker, round 18, found it; it predates HARN-022 (HARN-021, ESC-331, ESC-332). `harness-upgrade`
step 6 commits the upgrade with `-m "No-story: harness"`. The template's risky.toml lists `.keelokit/bin/**` and
`.keelokit/harness/**`, and state.toml is always risky, so the upgrade commit is RISKY_NO_STORY, in warn mode too.
Probes: /tmp/breaker18-HARN-022/probes/p2_harness_upgrade_no_story.py (block) and p2b_warn.py (warn).
`ledger.py accept` asks a person to commit `backlog/ledger-corrections.toml`, always risky too, and names no trailer:
check whether it hits the same error.

Direction (the coordinator's): the upgrade gets its own small risky story, created by the skill, that touches
`.keelokit/**`, and closes with a breaker round or a Decision by the configured deciders. The skill tells the PERSON to
write that Decision; the agent never writes one.

Does NOT do: loosen RISKY_NO_STORY for `No-story: harness` commits.

## User story
As a person upgrading Keelokit in a project that has risky.toml, I want the upgrade to land green, so that following
the skill never breaks my CI and the upgrade is still judged like any other risky change.

## Acceptance criteria
```gherkin
Scenario: [S1] An upgrade done as the skill says lands green
  Given a project with risky.toml on its trunk
  When harness-upgrade upgrades it and the person closes the upgrade's story as the skill says
  Then check reports no RISKY_NO_STORY and no BREAKER_* error for the upgrade

Scenario: [S2] An accepted correction lands green
  Given a person accepts a proposed ledger correction
  When they commit it as `ledger.py accept` says
  Then check reports no RISKY_NO_STORY for that commit
```

## Testable units
| Unit | Test type | File |
|---|---|---|
| the upgrade's story and its close | integration (real git) | tests/test_breaker.py |
| the accepted correction's commit | integration (real git) | tests/test_breaker.py |

## Definition of done
`scripts/verify.sh` green, every scenario covered by a test titled with its id, the two ledger.py copies identical,
`Story: HARN-024` on the completing commit, its breaker rounds recorded below.
