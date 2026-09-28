+++
id = "HARN-001"
epic = "HARN"
title = "Mutation testing for the guard and the doctor"
wave = 1
depends_on = []
touches = ["scripts/mutation.sh", ".github/workflows/mutation.yml", ".keelokit/critical.toml", ".keelokit/exceptions.toml"]
dimensions = ["dx", "packaging"]
invariants = []
+++
## Context
MUT-1 asks that critical code keep a mutation score; Keelokit's own Python has no mutation tool,
so the rule has a dated exception until 2027-01-31 (`.keelokit/exceptions.toml`). The guard and
the doctor decide what an agent may do and whether a rule still has its check: a test suite that
misses a changed condition there lets a whole class of bug through.

Does NOT do: mutation testing of the dashboard or of the template's TypeScript (that has
`scripts/mutation.sh` with Stryker already).

## User story
As the maintainer, I want a mutation score for the guard and the doctor, so that I know their tests
would notice a broken check.

## Acceptance criteria
```gherkin
Scenario: [S1] The critical areas are declared
  Given .keelokit/critical.toml
  Then it names the guard and the doctor (both copies) as critical areas with their paths

Scenario: [S2] One command gives the score
  When a contributor runs scripts/mutation.sh
  Then mutmut runs the unit tests against mutants of the critical areas and prints the score per area
  And it exits non-zero when a score is below mutation_break

Scenario: [S3] CI runs it without slowing every push
  Then a mutation workflow runs it weekly and by hand, and the doctor sees the 'mutation' job

Scenario: [S4] The exception goes away
  Then .keelokit/exceptions.toml no longer has MUT-1 and the doctor reports no MUT-1 error
```

## Testable units
| Unit | Test type | File |
|---|---|---|
| mutation.sh exits by score | unit | tests/test_mutation.py |
| critical areas and exception | unit (doctor) | tests/test_doctor.py |

## Definition of done
`scripts/verify.sh` green, every scenario covered by a test titled with its id, `Story: HARN-001`
trailer on the completing commit, addendum if the result differs.
