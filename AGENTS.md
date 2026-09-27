# Keelokit — working agreement for this repo

This repo is Keelokit itself: a Claude Code plugin and the Copier template it generates projects
from. The projects' own agreement is `template/AGENTS.md.jinja`; don't mix the two.

## Layout

```
.claude-plugin/   plugin.json (name, version, description), marketplace.json, icon.svg
skills/ agents/ workflows/ hooks/ references/   the plugin
template/ copier.yml                 the project template (rendered from `template/`)
tests/            unit tests for the guard and doctor
scripts/          test-template.sh (generates projects and runs their checks), release.sh
docs/             design.md (how the pieces fit), releasing.md (how a version ships)
```

## Commands

| What | Command |
|---|---|
| Guard, doctor, dashboard and workflow tests | `python3 -m unittest discover -s tests` |
| Plugin manifests | `claude plugin validate . --strict` |
| A generated project, end to end | `scripts/test-template.sh '["api","web"]'` (see its header) |

## Releases

Read `docs/releasing.md` before anything that touches versions, tags or the `release` branch.
In short:

- Work lands on `main`. User-facing changes get a line under `## Unreleased` in `CHANGELOG.md`.
- Never change `version` in `.claude-plugin/plugin.json`, push to `release` or create tags by
  hand. A release is `scripts/release.sh X.Y.Z`, and only when the user asks for one.
- The Claude plugin directory tracks `release` and scans the whole repo. A new scan finding gets a
  real fix or a line in the submission notes, never a rewording just to get past the scanner.
