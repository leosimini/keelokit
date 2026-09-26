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
- `bin/guard.py` — one guard, two callers: Claude Code's PreToolUse hook and git's pre-commit.
- `rules.local.toml`, `exceptions.toml` — the project's own rules, and dated deviations.

## What `doctor` checks — and what it can't

It checks that each MUST rule has an enforcer and that the enforcer looks alive: a test file
that names the rule and has active tests, a lint rule that is on, a CI job with real steps and no
`continue-on-error`, a git hook that is installed, a config line that is present. It checks
exceptions (complete, not expired), `docs/context` (files present, no vague phrases, every gap
tracked), and the backlog (well-formed stories, declared dimensions, scenario ids, no two
stories of a wave touching the same paths, every scenario of a done story cited by an active
test title). A story is done when a commit on `main` carries `Story: <ID>`.

It can't tell whether a test really fails when its rule breaks. That is the reviewer's and the
verifier's job, and what `/keelokit:bugbash` tightens when a bug gets through. The guard is a speed
bump for agents, not a sandbox; the git hooks and CI are the backstop.

## Lifecycle

| Stage | Skill | Human decides |
|---|---|---|
| New product | `kickstart`: intake → PRD → stack → skeleton → backlog | context, scope, stack deviations, story order |
| Existing repo | `adopt`: intake → `.keelokit/` + rule mapping → diagnosis → backlog | each exception |
| Build | `build`: contract → verifier's tests → builder → reviewer → verifier walks the app → land | product rules the story doesn't define |
| Quality | `bugbash`: lenses per dimension → validation → root-cause fixes → a new check per escape | pending product decisions |
| Keep up | `upgrade`, `doctor` | rule changes, exceptions |

Reserved for the human always: production deploys, money, legal, deleting data.

## Testing Keelokit itself

- `tests/` — unit tests for the guard and doctor (`python3 -m unittest discover -s tests`).
- `scripts/test-template.sh` — generates projects (several app combinations, adopt mode, an
  upgrade from the previous tag) and runs `pnpm verify --all` on each. CI runs both.

## Ideas, not promises

Things that might come if they prove useful in real projects: measuring whether agents follow
the skills (evals), deploying web and sites from CI, per-package caching.
