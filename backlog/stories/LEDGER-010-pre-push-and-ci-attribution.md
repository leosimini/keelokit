+++
id = "LEDGER-010"
epic = "LEDGER"
title = "Pre-push and CI: nothing unattributed reaches the trunk"
wave = 14
depends_on = ["LEDGER-009"]
touches = ["template/.githooks/pre-push", ".githooks/pre-push", "template/.keelokit/bin/ledger.py", ".keelokit/bin/ledger.py", "template/.github/workflows/ci.yml.jinja", ".github/workflows/ci.yml", "tests/test_ledger.py", "tests/test_verify.py", "tests/test_ci.py", "CHANGELOG.md"]
dimensions = ["logic", "integrity", "ops"]
invariants = ["INV-005", "INV-007"]
origin = "docs/ledger.md — Mechanisms (pre-push and CI); JOUNA's squashed trains"
+++
## Context
A local hook can be skipped (`--no-verify`, a machine without hooks, a swarm helper without the plugin),
so the guarantee lives where work enters the trunk: the pre-push and, behind it, the CI.

`ledger.py prepush` reads git's pre-push lines; for a push to the trunk it runs before the verify (it is
the fast part) and checks the new commits that are not merges:
- each is attributed, or a merge commit of the same push that brings it carries `Story:`, `Part-of:` or
  `No-story:` (a branch from elsewhere without trailers is attributed by the merge that integrates it);
- a commit whose tree equals the tip of an unintegrated origin branch is a squash of it, and must carry
  every `Story:` and `Part-of:` of that branch (`SQUASH_LOST_TRAILERS`). This is the case of JOUNA's
  trains, which entered `main` squashed and lost their stories.

`ledger.py check --ci` does the same in CI: on a pull request over its commits, on a push to the trunk over
the trunk since `[ledger] since`. For each unattributed commit it prints the exact `ledger.py correct`
command. The step goes in the job that already runs the doctor with `fetch-depth: 0`. All three follow
`enforce`: with `warn` they print, with `block` they fail.

**Decided:** INV-007 (docs/ledger.md, "Decisions", 2), already in `docs/context/domain.md`.

Does NOT do: write the snapshot (LEDGER-011); check pushes to branches that are not the trunk.

## User story
As the person responsible for a project, I want nothing unattributed to reach the trunk, whatever machine
or account pushed it, so that the ledger's history is complete.

## Acceptance criteria
```gherkin
Scenario: [S1] An unattributed commit pushed to the trunk
  Then with enforce = "block" the push is refused with UNATTRIBUTED and the commit's hash
  And with enforce = "warn" it goes through and the same text is printed

Scenario: [S2] A merge attributes what it brings
  Given a branch from elsewhere with two commits without trailers
  When it is merged with a merge commit carrying `Part-of: AUTH-005` and pushed
  Then the push goes through

Scenario: [S3] A squash that loses a story
  Given an origin branch with `Part-of: AUTH-006` and `Story: AUTH-007` commits
  And a commit on the trunk with the same tree that carries only `Story: AUTH-007`
  Then SQUASH_LOST_TRAILERS names AUTH-006

Scenario: [S4] A squash that keeps everything
  Given the same squash carrying both trailers
  Then it goes through

Scenario: [S5] CI on the trunk
  Given an unattributed commit on the trunk after `since`
  Then with block the CI step fails and prints the `ledger.py correct` command for that commit

Scenario: [S6] Other branches
  Then a push to a branch that is not the trunk is not checked
```

## Testable units
| Unit | Test type | File |
|---|---|---|
| prepush: attribution, merge coverage, squash detection | unit, local remote | tests/test_ledger.py |
| the pre-push order (attribution before verify) | unit | tests/test_verify.py |
| the CI step exists, with fetch-depth 0 | unit | tests/test_ci.py |

## Definition of done
`scripts/verify.sh` green, every scenario covered by a test titled with its id, INV-005 cited, this repo's
own pre-push and CI get the same step, a CHANGELOG line, `Story: LEDGER-010` trailer, addendum if the
result differs.
