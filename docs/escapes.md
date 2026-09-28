# Escapes

Every bug that got past a story's own tests — caught by the reviewer, the breaker, the verifier,
a bug bash, or a user — and the check it left behind so its whole class can't come back. A fix
without a new check only repairs one case. `pnpm doctor` fails on a row with an empty cell; when
nothing can catch the class automatically, write `none — <why>` and propose a review rule.

| Id | Date | Found by | What escaped | Class | Check added |
|---|---|---|---|---|---|
| ESC-001 | 2026-09-27 | check-bugbash | INT-1: with neither main nor origin/main (the template's CI `checks` job, a default shallow checkout of a pull request) the doctor and the dashboard fell back to HEAD, counted the PR's own `Story:` trailers as done (INV-005) and diffed HEAD against itself, so `--scope` and `pnpm mutation` saw nothing changed | consistency | tests/test_doctor.py and tests/test_dashboard.py `INT-1` cases (no main ref: nothing done, `--scope` exits 2, `--critical --changed` takes every critical file); a test that every CI job reading history against main checks out with `fetch-depth: 0` |
| ESC-002 | 2026-09-27 | check-bugbash | LOG-4: the guard's `commit -n` rule matched any short flag containing an n, so `git commit -uno` was blocked as a hook bypass, while spellings git accepts got through: `--no-veri`/`--no-verif`, git's own options before the subcommand (`git -C dir commit -n`, `git -C dir push -f`, `--config-env=core.hooksPath=…`), `core.hookspath` in another case, and `git push -uf`/`-vf`/`--mirror` | consistency | tests/test_guard.py `LOG_4` cases: the grammar case derives commit's and push's short options from `git … -h` and runs every bypass and every legitimate spelling behind each of git's own options (a git option the guard doesn't know fails the test); the oracle case runs each commit for real against a failing pre-commit hook and each push against a remote it would rewrite, and the guard must block exactly the commits that skipped the hook and every push that forced |
