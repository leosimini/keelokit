# Arch-specs: a test that reads the source tree

A bug class that bit twice deserves a test that fails on the pattern itself, wherever it is written next. Copy the one you need into the package it guards (`packages/shared/src/arch/` or `apps/<app>/src/arch/`), adjust `ROOT`, `GLOBS` and the allowlist, and log it as the guard of the class: `.keelokit/bin/escapes.py add --guard arch-spec --check "<file>"`.

| File | Forbids | Rule |
|---|---|---|
| `no-sleeps-in-specs.arch.test.ts` | `setTimeout`-based sleeps in tests | stable-tests 3 |
| `no-literal-dates.arch.test.ts` | a fixed calendar date in a test or a fixture outside an allowlist (it becomes a date bomb) | stable-tests 4 |
| `no-inherited-git-env.arch.test.ts` | a test that runs `git` without cleaning `GIT_*` | stable-tests 7 |

They are templates, not part of the generated project: adding them blindly to a codebase that already breaks the rule would turn the suite red. Run one, read the list, fix or allowlist each hit with a reason, then keep it.
