+++
id = "FLEET-003"
epic = "FLEET"
title = "Tests that stay green: stable-tests rules, arch-specs and flaky.sh reach main, with JOUNA's two rules"
wave = 22
depends_on = []
touches = ["references/stable-tests.md", "references/arch-specs/README.md", "references/arch-specs/_walk.ts", "references/arch-specs/no-inherited-git-env.arch.test.ts", "references/arch-specs/no-literal-dates.arch.test.ts", "references/arch-specs/no-sleeps-in-specs.arch.test.ts", "references/arch-specs/no-random-test-data.arch.test.ts", "template/.keelokit/bin/flaky.sh", "agents/verifier.md", "agents/reviewer.md", "skills/build-story/SKILL.md", "copier.yml", "scripts/test-template.sh", "tests/test_scripts.py", "CHANGELOG.md"]
dimensions = ["logic", "dx", "docs"]
invariants = []
origin = "docs/fleet-lessons.md — lessons 1 and 6; the unmerged branch claude/orquestador-y-verify (2026-10-31)"
+++
## Context
Every intermittent test stops a whole train. JOUNA's six in one night (`evi-005`, `orgweb-003`, `VOL-004`,
`staging-seed`, `StudentDetailScreen`, fixed dates) each had a mechanical cause. Keelokit already wrote the
rules for most of them, but on a branch that never reached `main`: `claude/orquestador-y-verify` has
`references/stable-tests.md` (nine rules), arch-specs that walk the source tree and fail on a forbidden
pattern (`no-literal-dates`, `no-sleeps-in-specs`, `no-inherited-git-env`) and
`template/.keelokit/bin/flaky.sh` (reproduce an intermittent red under stress and clock edges).

This story brings those three pieces to `main` (only these; the branch's orchestrator design and the rest
stay a separate decision) and adds the two rules JOUNA's night shows are missing:

- **Rule 10 — test data is deterministic.** No random names, emails or amounts that can collide with
  words the code reacts to (`evi-005`: a random name that sometimes contained "fee"). Seeded generators
  or fixed fixtures only. Arch-spec `no-random-test-data` fails on `Math.random`, `faker` without a fixed
  seed, and `crypto.randomUUID` in test files outside an allow-list of id helpers.
- **Rule 11 — an absence is asserted in one place.** "This route is closed", "this button is hidden":
  JOUNA's commonest seam (4 trains, ~14 specs) was a test asserting a route was closed while another piece
  opened it. Such assertions live in one registry the project keeps (for example
  `e2e/closed-routes.ts`), read by every spec, so the piece that opens a route changes one line in the
  same branch and nobody's test breaks behind its back.

The verifier and the reviewer read `stable-tests.md`; `build-story` points the spec-test writer to it;
the arch-specs ship in the template's test setup (copier) and run in `pnpm verify`.

Does NOT do: merge the rest of `claude/orquestador-y-verify`; skip, retry or quarantine any test (FLAKY-1).

## User story
As a session whose train waits on the slowest test, I want the classes of intermittent test made
impossible to write, so that a red means a real bug.

## Acceptance criteria
```gherkin
Scenario: [S1] The rules are on main
  Then references/stable-tests.md has the nine rules plus rules 10 and 11, and the verifier and reviewer cite it

Scenario: [S2] Literal dates fail
  Given a spec with a hard-coded future date
  Then the no-literal-dates arch-spec fails, naming the file and line

Scenario: [S3] Random test data fails
  Given a spec using Math.random to build a name
  Then the no-random-test-data arch-spec fails; with a seeded generator it passes

Scenario: [S4] Sleeps fail
  Given a spec that sleeps to wait for work
  Then the no-sleeps-in-specs arch-spec fails

Scenario: [S5] flaky.sh reproduces
  When `.keelokit/bin/flaky.sh -n 20 --stress 4 --tz "UTC Pacific/Auckland" -- <command>` runs a test that fails at a clock edge
  Then it reports the failing runs with their seed, timezone and load

Scenario: [S6] A generated project gets them
  Then scripts/test-template.sh generates a project whose verify runs the arch-specs, green on the template's own code
```

## Testable units
| Unit | Test type | File |
|---|---|---|
| flaky.sh's options | unit | tests/test_scripts.py |
| each arch-spec on a failing and a passing fixture | arch-spec tests (Vitest) | references/arch-specs/*.arch.test.ts |
| the template wiring | end to end | scripts/test-template.sh |

## Definition of done
`scripts/verify.sh` and `scripts/test-template.sh` green, every scenario covered by a test titled with its
id, a CHANGELOG line, `Story: FLEET-003` trailer, addendum if the result differs.
