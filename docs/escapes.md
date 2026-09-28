# Escapes

Every bug that got past a story's own tests — caught by the reviewer, the breaker, the verifier,
a bug bash, or a user — and the check it left behind so its whole class can't come back. A fix
without a new check only repairs one case. `pnpm doctor` fails on a row with an empty cell; when
nothing can catch the class automatically, write `none — <why>` and propose a review rule.

| Id | Date | Found by | What escaped | Class | Check added |
|---|---|---|---|---|---|
| ESC-001 | 2026-09-27 | check-bugbash | INT-1: with neither main nor origin/main (the template's CI `checks` job, a default shallow checkout of a pull request) the doctor and the dashboard fell back to HEAD, counted the PR's own `Story:` trailers as done (INV-005) and diffed HEAD against itself, so `--scope` and `pnpm mutation` saw nothing changed | consistency | tests/test_doctor.py and tests/test_dashboard.py `INT-1` cases (no main ref: nothing done, `--scope` exits 2, `--critical --changed` takes every critical file); a test that every CI job reading history against main checks out with `fetch-depth: 0` |
| ESC-002 | 2026-09-27 | check-bugbash | LOG-1 (and SEC-2 of the same bash): the guard's Bash path never checked the text a command writes into a file, so `echo 'it.skip(…)' >> a.test.ts`, a here-document, `sed -i '1i // eslint-disable'` or `python3 -c "open('.env','a').write(…)"` passed the PreToolUse hook that blocks the same text from Edit/Write (the pre-commit hook still caught tampering once staged) | consistency | tests/test_guard.py `LOG1` cases: every TAMPER and SECRETS pattern (a pattern without a sample fails) and every .env name must hit its own rule through every shell writer (redirect, tee, here-document and -string, sed -i, sed/perl addresses, awk) and through every interpreter in `guard.INTERPRETERS` (an interpreter without a writer sample fails) on every way of handing it code (inline flag, `--eval=`, `npx`, here-document, here-string, stdin pipe); reads (`.env` included), prose, the harness and removals (`s///`, `/re/d`, `grep -v`, `.replace(x, '')`) must pass. New write routes outside those lists still need a line there |
