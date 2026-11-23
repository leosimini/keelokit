# Arch-specs: a test that reads the source tree

A bug class that bit twice deserves a test that fails on the pattern itself, wherever it is written next. Each arch-spec walks the project's test files (`*.test.*`, `*.spec.*`, and sources under `e2e/`, `fixtures/`, `__tests__/`, `test/`, `tests/`) and fails naming every `file:line` that breaks one rule of [stable-tests.md](../stable-tests.md).

| File | Forbids | Rule |
|---|---|---|
| `no-sleeps-in-specs.arch.test.ts` | sleeping to wait for work: `setTimeout` in a promise, `sleep(500)`, Playwright's `waitForTimeout` | stable-tests 3 |
| `no-literal-dates.arch.test.ts` | a calendar date of 2020–2039 written into a test or a fixture (it becomes a date bomb) | stable-tests 4 |
| `no-inherited-git-env.arch.test.ts` | a test that runs `git` without cleaning `GIT_*` | stable-tests 7 |
| `no-random-test-data.arch.test.ts` | `Math.random`, `crypto.randomUUID`, or `faker` without `faker.seed(n)` in test data | stable-tests 10 |

`_walk.ts` holds the walk and the four checks; each spec runs one check on the project root (the folder with `pnpm-workspace.yaml`) and on two fixtures of its own, one that breaks the rule and one that keeps it.

**In a generated project** they are in `packages/shared/src/arch/` and run with the shared package's tests, so `pnpm verify` runs them; they are green on the template's own code. They belong to the product from then on: allow-list a file in the spec's `ALLOW` with its reason, or a single line with `// arch-allow: <reason>`, and log the class a spec guards in `docs/escapes.md`.

**In a project created before Keelokit 0.15, or an adopted repo,** `copier update` does not add them: a codebase that already breaks a rule would turn red. Copy `_walk.ts` and the spec you need into a package that has Vitest and `@types/node`, run it, read the list, fix or allow-list each hit with a reason, then keep it.
