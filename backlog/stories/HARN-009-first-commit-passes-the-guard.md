+++
id = "HARN-009"
epic = "HARN"
title = "The first commit of a generated project passes its own guard"
wave = 8
depends_on = []
touches = ["template/.github/workflows/ci.yml.jinja", "scripts/test-template.sh", "tests/test_first_commit.py"]
dimensions = ["dx", "config"]
origin = "harbor:2026-11-02"
+++
## Context
Running Harbor against a project generated with 0.11.0: project-new commits after `pnpm install`, whose `prepare` turns the git hooks on, so the guard's pre-commit (QA-4) reads every template file as added and blocks the `continue-on-error` set to true in the ci-report job (since ad61f68). An agent can't use allowTamper. scripts/test-template.sh didn't see it: it commits before the install.

Does NOT do: loosen QA-4 (no exception by comment). The line goes: download-artifact@v4 with a pattern that matches nothing succeeds.

## User story
As someone starting a product with /keelokit:project-new, I want its first commit to go through, so that the run doesn't stop on a check the template itself trips.

## Acceptance criteria
```gherkin
Scenario: [S1] The first commit of a new product passes the guard
  Given a project generated with every app
  When the hooks are on and the whole tree is committed
  Then the commit succeeds

Scenario: [S2] The commit that adopts the harness passes the guard
  Given an existing repo with the harness installed
  When the hooks are on and .keelokit/ is committed
  Then the commit succeeds
```

## Testable units
| Unit | Test type | File |
|---|---|---|
| the template rendered and committed with the hooks on | integration (copier, git) | tests/test_first_commit.py |
| the same after `pnpm install` | end to end | scripts/test-template.sh |

## Definition of done
`scripts/verify.sh` green, every scenario covered by a test named `test_HARN_009_S<n>_…`,
`Story:` trailer on the completing commit.
