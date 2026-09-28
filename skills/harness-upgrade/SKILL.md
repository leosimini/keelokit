---
name: harness-upgrade
description: Maintenance of the harness, not of the app — bring a Keelokit project up to a newer Keelokit version: the house rules, the doctor and the guard, CI, git hooks and base configs, merged with Copier on a branch, without touching the product's code (apps, migrations, E2E, translations). Use when the user says "upgrade keelokit", "update the harness", "actualizá keelokit", "actualizá el harness", "traé la última versión del template", after `claude plugin update`, or when the dashboard or doctor shows the harness is behind the plugin.
---

# Harness upgrade — new harness, same product

A project keeps its own copy of the harness: the version of the Keelokit template it was generated
from (`_commit` in `.keelokit/answers.yml`). Updating the plugin doesn't change that copy; this
skill does. Say it that way to the user: it brings Keelokit's new rules and checks into the
project, on a branch, and never rewrites their product.

The template owns infrastructure (CI, lint/format/ts base configs, `scripts/verify.sh`, git
hooks, `.keelokit/` except the project's own choices: `rules.local.toml`, `exceptions.toml`,
`critical.toml` and `profile.toml`). The product owns its code (apps' `src/`, e2e, prisma schema
and migrations, locale files, packages' `src/`) and its knowledge (`docs/context/`, `docs/prd.md`,
`docs/escapes.md`, `backlog/`, `README.md`, `CHANGELOG.md`) — Copier never overwrites those once
they exist.

1. Working tree clean (`git status`), on a branch: `git switch -c chore/keelokit-upgrade`.
2. See where you are: `grep _commit .keelokit/answers.yml`. Pick the target tag (latest by default).
3. Run:
   ```bash
   uvx copier==9.18.2 update -a .keelokit/answers.yml --defaults --conflict rej --vcs-ref <tag>
   ```
   `-a .keelokit/answers.yml` is required (Keelokit keeps its answers there). If `_src_path` in that
   file is a local path, the project can only upgrade from that machine — point it at the git
   source (`gh:<owner>/keelokit`) first.
4. Resolve every `*.rej`: keep the project's intent, take the template's structure; delete the
   `.rej` files. Read the Keelokit CHANGELOG entries between the two versions for what changed and
   why.
5. `pnpm install`, then `pnpm verify --all` and `python3 .keelokit/bin/doctor.py`. New house rules
   may fail on purpose: meet them, or register an exception with the user's approval.
6. Commit `chore: upgrade Keelokit <from> → <to>` and report: rules added/changed, conflicts
   resolved, and anything the user must decide.
