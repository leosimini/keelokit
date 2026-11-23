+++
id = "FLEET-003"
epic = "FLEET"
title = "Tests that stay green: stable-tests rules, arch-specs and flaky.sh reach main, with JOUNA's two rules"
wave = 22
depends_on = []
touches = ["references/stable-tests.md", "references/arch-specs/README.md", "references/arch-specs/_walk.ts", "references/arch-specs/no-inherited-git-env.arch.test.ts", "references/arch-specs/no-literal-dates.arch.test.ts", "references/arch-specs/no-sleeps-in-specs.arch.test.ts", "references/arch-specs/no-random-test-data.arch.test.ts", "template/.keelokit/bin/flaky.sh", "agents/verifier.md", "agents/reviewer.md", "skills/build-story/SKILL.md", "copier.yml", "scripts/test-template.sh", "tests/test_scripts.py", "CHANGELOG.md", "template/packages/shared/src/arch/_walk.ts", "template/packages/shared/src/arch/no-inherited-git-env.arch.test.ts", "template/packages/shared/src/arch/no-literal-dates.arch.test.ts", "template/packages/shared/src/arch/no-sleeps-in-specs.arch.test.ts", "template/packages/shared/src/arch/no-random-test-data.arch.test.ts", "template/packages/shared/package.json.jinja", "template/packages/shared/tsconfig.build.json", "backlog/stories/FLEET-003-tests-that-stay-green.md"]
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

## Addendum — 2026-11-23
- **New projects only.** The arch-specs ship in `template/packages/shared/src/arch/` (byte-identical copies of
  `references/arch-specs/*.ts`, checked by a test) and run with the shared package's tests in `pnpm verify`.
  `copier.yml` excludes that folder on `copier update` (`_copier_operation == 'update'`): an existing project that
  already breaks a rule would turn red, and its `packages/shared/package.json` (product-owned) lacks `@types/node`.
  The product owns them once generated; later template fixes to them do not reach existing projects (copy from
  `references/arch-specs/`). `flaky.sh` and the `tsconfig.build.json` exclude do arrive by update.
- `touches` grew by the template copies, shared's `package.json.jinja` (`@types/node`) and `tsconfig.build.json`
  (keeps `src/arch` out of `dist`). `_walk.ts` carries `/// <reference types="node" />` because TypeScript 6 adds
  no types by default.
- `flaky.sh` gained `--seed` (run r gets `FLAKY_SEED=S+r-1`), a `failed:` line per failing run with seed, zone,
  stress and load average, decimal-only numbers and a refusal of unknown zones.
- Arch-spec scope: test files plus sources and JSON under e2e, fixtures, __fixtures__, __tests__, __mocks__, mocks,
  test, tests, testing, test-utils; hidden folders, `tmp` and symlinks are never walked; a line that pins the clock
  (`setSystemTime`, Playwright `clock.install`) may hold a literal date.
- Escapes ESC-053..055 (flaky.sh false green on input parsing; walker isolation; arch-spec coverage gaps) could not
  be committed to `docs/escapes.md`: the guard's SEC-1 flags the existing ESC-052 row (an example URL) whenever the
  file is staged. The rows are recorded here until a human allow-lists ESC-052 or rewords it:
  ESC-053 consistency — tests/test_scripts.py `FLEET_003_S5_counts_and_seeds_are_decimal_never_octal`,
  `FLEET_003_S5_an_unknown_zone_is_refused_before_any_run`; ESC-054 isolation — no-literal-dates
  `FLEET-003.S2 the walker skips hidden and tmp folders and never follows a symlink`; ESC-055 consistency — the
  fixture tests in references/arch-specs/*.arch.test.ts.
- Not done: the rest of `claude/orquestador-y-verify`; the closed-routes registry itself (rule 11 is a rule for
  projects, not code in the template); no mechanical check for rule 11.
