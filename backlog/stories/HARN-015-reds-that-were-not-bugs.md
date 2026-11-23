+++
id = "HARN-015"
epic = "HARN"
title = "The reds that weren't bugs: defaults, known causes and stable-test rules"
wave = 14
depends_on = ["HARN-014"]
touches = ["template/scripts/verify.sh", "template/.keelokit/bin/verify_tools.py", "agents/verifier.md", "template/.keelokit/harness/execution-protocol.md", "template/apps/api/vitest.integration.config.ts", "tests/test_verify_operativo.py"]
dimensions = ["dx"]
origin = "harbor:2026-11-02"
+++
## Context
A monorepo built with Keelokit logged every red of its verify and why (JOUNA's verify playbook). Most weren't bugs: a worker out of heap, a hook timing out on a busy machine, two specs sharing rows, an unbuilt workspace package, an error thrown after the tests passed, a reused database name. Keelokit named only a few of them, and its integration specs ran in parallel against one database.

Does NOT do: per-worker database copies (later, when a suite gets long).

## User story
As whoever reads a red verify, I want the common non-bug causes named and prevented, so that a red means a bug more often.

## Acceptance criteria
```gherkin
Scenario: [S1] Verify gives Node a bigger heap unless one is chosen
  Given NODE_OPTIONS without a heap size, or with one
  When pnpm verify runs
  Then 4 GB is added in the first case, the chosen size kept in the second

Scenario: [S2] The reds that were not bugs are known causes
  Given a log with one of those failures
  When verify_tools.py causes reads it
  Then it names the cause and where to look

Scenario: [S3] Integration files run one at a time
  Given the template's API
  When its integration config is read
  Then fileParallelism is off

Scenario: [S4] The verifier writes tests that stay green
  Given agents/verifier.md
  When mode A
  Then it lists the rules: own data, global tables, no sleep, fixed clock, final state, teardown, every consumer
```

## Testable units
| Unit | Test type | File |
|---|---|---|
| verify.sh, verify_tools.py, configs and texts | unit and fixture runs | tests/test_verify_operativo.py |

## Definition of done
`scripts/verify.sh` green, every scenario covered by a test named `test_HARN_015_S<n>_…`,
`Story:` trailer on the completing commit.
