# Keelokit — working agreement for this repo

This repo is Keelokit itself: a Claude Code plugin and the Copier template it generates projects
from. The projects' own agreement is `template/AGENTS.md.jinja`; don't mix the two.

## Layout

```
.claude-plugin/   plugin.json (name, version, description), marketplace.json, icon.svg
skills/ agents/ workflows/ hooks/ references/   the plugin
template/ copier.yml                 the project template (rendered from `template/`)
tests/            unit tests for the guard, doctor, dashboard, workflows and verify.sh's scope
scripts/          test-template.sh (generates projects and runs their checks), release.sh
docs/             design.md (how the pieces fit), releasing.md (how a version ships)
```

## Commands

| What | Command |
|---|---|
| Everything CI checks, locally (the pre-push hook runs it) | `scripts/verify.sh` |
| Guard, doctor, dashboard, workflow and verify tests | `python3 -m unittest discover -s tests` (test_verify.py needs pnpm, test_first_commit.py uv, the dashboard layout test playwright's Chromium) |
| Plugin manifests | `claude plugin validate . --strict` |
| A generated project, end to end | `scripts/test-template.sh '["api","web"]'` (see its header) |

## Keelokit on Keelokit

This repo runs on its own harness (`.keelokit/`, adopted 2026-09-28): `docs/context/`, `backlog/`,
the doctor in CI, the guard in your Claude sessions. Once per clone, `git config core.hooksPath
.githooks` turns on the git hooks (the guard before a commit, `scripts/verify.sh` before a push).
`/keelokit` says where things stand; stories are built with `/keelokit:build-story`, one at a time.
None of this ships in the plugin: `scripts/package.sh` leaves it out.

## Where the truth is

A story's state is asked of `ledger.py`, never of memory or of a handoff file (`backlog/next.md`, a
coordinator's notes, another session's report): it reads git. The session start prints its summary.

| Question | Ask |
|---|---|
| Is X done, since when, in which version? | `python3 .keelokit/bin/ledger.py show X` |
| What do I take? | `python3 .keelokit/bin/ledger.py next` |
| Is someone on it? | `python3 .keelokit/bin/ledger.py show X` (its branches and sessions) |
| Why did it end up this way? | `python3 .keelokit/bin/ledger.py show X` (commit bodies, addenda, escapes, findings) |
| What went into 0.15? | `python3 .keelokit/bin/ledger.py --release v0.15.0` |
| What is under way in the harbor? | `/harbor:log` |
| Is the record healthy? | `python3 .keelokit/bin/ledger.py check` |

## Releases

Read `docs/releasing.md` before anything that touches versions, tags or the `release` branch.
In short:

- Work lands on `main`. User-facing changes get a line under `## Unreleased` in `CHANGELOG.md`.
- Never change `version` in `.claude-plugin/plugin.json`, push to `release` or create tags by
  hand. A release is `scripts/release.sh X.Y.Z`, and only when the user asks for one.
- The Claude plugin directory tracks `release` and scans the whole repo. A new scan finding gets a
  real fix or a line in the submission notes, never a rewording just to get past the scanner.
