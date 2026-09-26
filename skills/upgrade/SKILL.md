---
name: upgrade
description: Bring a Keelokit project up to a newer Keelokit template — house rules, harness scripts, CI, configs — without touching the product's own code. Use when the user says "upgrade keelokit", "update the harness", "actualizá keelokit", "traé la última versión del template", or when doctor/CI shows the harness is behind.
---

# Upgrade — new harness, same product

The template owns infrastructure (CI, lint/format/ts base configs, `scripts/verify.sh`, git
hooks, `.keelokit/` except the project's local rules and exceptions). The product owns its code
(apps' `src/`, e2e, prisma schema and migrations, locale files, packages' `src/`) — Copier never
overwrites those once they exist.

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
