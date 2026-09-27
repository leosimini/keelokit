# How Keelokit is built

This describes Keelokit as it is. For how to use it, see the [README](../README.md).

## Three places

| Place | What lives there | How it changes |
|---|---|---|
| **The plugin** (this repo, installed in Claude Code) | skills, agents, the hooks that call each project's guard | `claude plugin update` |
| **The template** (`copier.yml` + `template/`, same repo, tagged) | the monorepo skeleton and the house harness in `.keelokit/` | a project runs `/keelokit:upgrade` (Copier's 3-way merge) |
| **A project** (generated or adopted) | its code, `docs/context/`, `docs/prd.md`, `backlog/`, `.keelokit/answers.yml`, local rules and exceptions | by the people and agents working on it |

The template owns infrastructure; the product owns its code. `copier.yml` lists which is which
(`_skip_if_exists`), so an upgrade brings new rules and CI without rewriting product files.

## The house harness (`template/.keelokit/`)

- `harness/rules.toml` — every rule with its reason and its enforcers.
- `harness/execution-protocol.md` — how agents work, what "done" means, what waits for the human.
- `harness/stack.md` — the stack and why.
- `bin/doctor.py` — harness health (below).
- `critical.toml` — the project's critical areas and the mutation score they must keep (the
  product owns it; the template ships one example area).
- `bin/guard.py` — one guard, two callers: Claude Code's PreToolUse hook and git's pre-commit.
- `rules.local.toml`, `exceptions.toml` — the project's own rules, and dated deviations.

## What `doctor` checks — and what it can't

It checks that each MUST rule has an enforcer and that the enforcer looks alive: a test file
that names the rule and has active tests, a lint rule that is on, a CI job with real steps and no
`continue-on-error`, a git hook that is installed, a config line that is present. It checks
exceptions (complete, not expired), `docs/context` (files present, no vague phrases, every gap
tracked, every invariant with an id and a class), critical areas (their paths exist), the
backlog (well-formed stories, declared dimensions, scenario ids, no two stories of a wave
touching the same paths or the same critical area, a story in a critical area declaring
`integrity` and its invariants, every scenario and invariant of a done story cited by an active
test title) and the escape log (every row names the check it left). A story is done when a
commit on `main` carries `Story: <ID>`.

`doctor --scope <ID>` checks one branch before review: files outside `touches`, a critical area
the story didn't declare, and acceptance tests edited outside a `test(<ID>): …` commit.
`doctor --critical [--changed]` lists the critical files that `scripts/mutation.sh` mutates.

It can't tell whether a test really fails when its rule breaks. For critical code, mutation
testing measures exactly that (MUT-1); everywhere else it is the reviewer's and the verifier's
job, and what `/keelokit:bugbash` tightens when a bug gets through. The guard is a speed
bump for agents, not a sandbox; the git hooks and CI are the backstop.

## Lifecycle

| Stage | Skill | Human decides |
|---|---|---|
| New product | `kickstart`: intake → PRD → stack → skeleton → backlog | context, scope, stack deviations, story order |
| Existing repo | `adopt`: intake → `.keelokit/` + rule mapping → diagnosis → backlog | each exception |
| Build | `build`: contract → verifier's tests → builder → reviewer + breaker → verifier walks the app → rebase, breaker again if main moved → land | product rules the story doesn't define, new invariants |
| Quality | `bugbash`: lenses per dimension → validation → root-cause fixes → a new check per escape | pending product decisions |
| Keep up | `upgrade`, `doctor` | rule changes, exceptions |

Reserved for the human always: production deploys, money, legal, deleting data.

## Bugs come in classes

A bug bash that keeps finding bugs means the build loop lets whole kinds of bug through. Each
kind has a mechanism aimed at it. Everything here works for any product: the product says what
is critical (its invariants and areas), and the harness decides how that gets proven.

| Why bugs escaped | Mechanism | Checked by |
|---|---|---|
| The builder read the spec the same way it wrote the code | The verifier writes the acceptance tests from the story before any code; the builder can't edit them (VERIFY-2) | `doctor --scope`: acceptance tests changed only in `test(<ID>): …` commits |
| One review at the end, for everything | A cold reviewer per story (light mode too) and a breaker that runs attacks (full mode), before landing, and again on the combination when main moved (REVIEW-1) | Review: inferential, and doctor says so |
| Money, limits and notices tested with one happy case | Invariants with ids and classes in `domain.md`; each class calls for one kind of test: property, concurrency with `race()` on the real DB, replay, transition table, fixed clock (INV-1) | Doctor: every invariant of a done story cited by an active test; the verifier and reviewer check it's the right kind |
| Hermetic E2E green while the real API disagreed | The critical journeys again in `e2e/stack/`, against the real API and PostgreSQL, in `pnpm verify` and CI (E2E-2) | CI job `e2e-stack`; lint forbids `page.route` there |
| Screens only looked at when the wave ended | The verifier saves screenshots per scenario and state for every story that touches a screen | Review |
| Parallel stories collided in shared code | Critical areas (`critical.toml`): stories touching one go one at a time, in full mode (CRIT-1) | Doctor: area overlap in a wave, `integrity` required |
| A fix repaired one case and the class came back | Every escape gets a failing test first (by the verifier), a fix, and a check for its class, logged in `docs/escapes.md` (ESC-1); bug bashes compare against it | Doctor: every escape row names its check |
| Text promised what the code didn't do | Every promise in copy points to a test of that behaviour (COPY-1) | Review |
| Green tests that couldn't fail | Mutation testing on critical code, with a score that fails CI (MUT-1) | CI job `mutation`; `scripts/test-template.sh` proves a suite that can't fail is rejected |

Mutation testing uses Stryker's command runner (each mutant reruns the package's `test` script).
It is slower than a per-test runner, but it works with Vitest and Jest of any version: Stryker's
Vitest plugin (10.0) runs no tests per mutant under Vitest 5 and reports every mutant as
survived. So critical areas are kept small and their rules pure.

Not done yet, on purpose: native E2E on a device or emulator (Maestro). The mobile journeys run
on Expo web, which covers the app's logic and screens but not native modules, permissions or
the OS lifecycle. A Maestro job needs a native build and an emulator in CI (about 20–40 minutes
per run) and only earns that once a product depends on native behaviour. Until then that part
is the `mobile` lens of the bug bash, on a real device.

## Testing Keelokit itself

- `tests/` — unit tests for the guard and doctor (`python3 -m unittest discover -s tests`).
- `scripts/test-template.sh` — generates projects (several app combinations, adopt mode, an
  upgrade from the previous tag), runs `pnpm verify --all` on each (integration tests and the
  real-stack E2E included), then `pnpm mutation --all`, and checks that a suite that can't fail
  is rejected. CI runs both.

## Ideas, not promises

Things that might come if they prove useful in real projects: measuring whether agents follow
the skills (evals), deploying web and sites from CI, per-package caching, a Maestro job for
native mobile journeys, and Stryker's per-test runner once it supports Vitest 5.
