# Changelog

## Unreleased

- **Dashboard** (`/keelokit:dashboard`): one branded page, in the user's language, with every
  stage of kickstart or adopt, its status and approval date, and — at the stage waiting for
  approval — what to check, with the documents rendered inline: context and open gaps, the PRD's
  scope and metrics, the stack, the backlog by development wave and by epic. It shows what waits
  for the user, the next step with a command to copy, and the difference between building one
  story at a time and several in parallel. It is rebuilt from the repo every time, so a paused
  run shows where it stopped. Published as an Artifact when the session can, otherwise a local
  HTML file; its look is fixed in `skills/dashboard/references/design.md`.
- Kickstart, adopt, backlog and build refresh the dashboard at every gate, never ask for an
  approval without showing what it covers, explain each term of art (PRD, stack, epic, story,
  development wave, worktree) the first time it comes up, and say "olas de desarrollo" in Spanish.
- Kickstart writes `docs/stack.md` (the apps chosen and why) at the stack gate.
- **Run decisions, taken once**: at the start, kickstart and adopt ask for the run mode —
  *stage by stage* or *automatic* (goes on alone and stops only where a person is required: the
  interview and blocking gaps, the PRD, a stack deviation, accounts, and what the execution
  protocol reserves for the human) — and for how stories are built (one at a time or up to N in
  parallel). Both live in `[run]` in `.keelokit/state.toml`; no skill asks again or changes them
  on its own. Automatic approvals are recorded as `"<date> auto"` and shown on the dashboard.
- The dashboard shows the project type (greenfield or brownfield) and every decision taken (run
  and build mode, apps, decision records), a **Bug bashes** section (each run's findings, what was
  fixed, the check it left, pending decisions and the stories it fed into the backlog, traced by
  a new optional story field `origin`) and a **History** of stories, bug bashes and approvals.
- **Ask Claude** on the dashboard: action buttons (approve, ask for changes, answer a gap, build
  a story or a wave, run a bug bash, add a feature…) fill a box that can be sent to the Claude
  session watching the page, or copied into any chat.
- A light/dark theme toggle in the dashboard's top bar (remembered per viewer), and the page
  follows `[dashboard] lang` (`es`, `es-AR`, `Español`… all work) and marks its language.
- The dashboard takes the look of keelokit.com (Cormorant Garamond, Karla, Fragment Mono; the
  foam and sea palette) and opens only what matters now: the stage in progress, the wave with
  work left; everything else collapses to a one-line summary.

## 0.5.0 — 2026-09-27 — bugs come in classes

Aimed at the kinds of bug that kept reaching bug bashes: races on limits, side effects sent
twice, totals that don't add up, parallel stories colliding in shared code, E2E green against a
mocked API, text that promises what the code doesn't do, and suites that can't fail.

- **Invariants** with ids and classes in `docs/context/domain.md` (`[INV-001] … — class: limit`),
  a catalogue of classes and the test each calls for (`references/invariants.md`), stories that
  list the invariants they keep, and the `integrity` dimension. INV-1: doctor fails when a done
  story's invariant has no active test citing it.
- **Critical areas** in `.keelokit/critical.toml`: a story touching one declares `integrity`, is
  built in full mode, and never shares a wave with another story of the same area (CRIT-1).
- **Mutation testing** of critical code: `pnpm mutation` (Stryker, command runner) and a CI job
  that fails under `mutation_break` (MUT-1). `scripts/test-template.sh` proves a suite that can't
  fail is rejected.
- **Real-stack E2E**: `e2e/stack/` journeys against the real API and PostgreSQL, in `pnpm verify`
  and a new CI job `e2e-stack`; lint forbids network mocks there (E2E-2).
- **Breaker** agent: attacks each story's branch before landing (double submits, N parallel
  requests, replays, other tenants, window edges, copy promises), and the combination with main
  when main moved during the story (REVIEW-1). The reviewer now runs in light mode too, checks
  invariants and copy promises (COPY-1), and runs `doctor --scope`.
- **Acceptance tests stay the verifier's**: `doctor --scope` fails when a story's acceptance tests
  change outside a `test(<ID>): …` commit (VERIFY-2).
- **Escape log** `docs/escapes.md`: every bug that got past a story's tests, found in build or in
  a bug bash, with the check it left for its class (ESC-1).
- Template: `allocate()` in `packages/shared` with property tests (fast-check) as the example of a
  critical rule, and `race()` in `apps/api/src/testing` for concurrency tests.
- Mobile `e2e` exports with `--clear`: Metro reused the previous export's `EXPO_PUBLIC_API_URL`,
  so a hermetic run after a real-stack one (or the reverse) called the wrong API.
- Intake asks where amounts move, what must happen once, which limits two people could pass, and
  whose data could leak; backlog proposes critical areas; bug bash gets an `integrity` lens.

### Upgrading from 0.4.x

`copier update` brings the rules, CI, scripts and the new product files (`critical.toml`,
`docs/escapes.md`, `allocate.ts`, `race.ts`, the `e2e/stack/` specs). The product's own
`package.json` files are never rewritten, so add by hand:

1. `pnpm --filter ./packages/shared add -D fast-check` (and `--filter ./apps/api` if you have it).
2. With an API and a web app, in `apps/web/package.json`:
   `"e2e:stack": "pnpm --dir ../api build && VITE_API_URL=http://localhost:${E2E_API_PORT:-3100} vite build && playwright test -c playwright.stack.config.ts"`
3. With an API and a mobile app, in `apps/mobile/package.json`: add `--clear` to `expo export`
   in the `e2e` script (Metro kept the previous export's `EXPO_PUBLIC_API_URL`), and add:
   `"e2e:stack": "pnpm --dir ../api build && EXPO_PUBLIC_API_URL=http://localhost:${E2E_API_PORT:-3100} expo export --platform web --clear && playwright test -c playwright.stack.config.ts"`
4. Write the product's invariants in `docs/context/domain.md` and its critical areas in
   `.keelokit/critical.toml`, or delete the example area if you drop `allocate.ts`.
5. `pnpm install && pnpm verify --all && pnpm mutation --all`.

## 0.4.2 — 2026-09-27

- Plugin icon at `.claude-plugin/icon.svg` for the Claude plugin directory.
- `references/dimensions.md`: the API bug-bash lens is worded as a plain request per role, so the
  directory's lint no longer reads it as a shell pattern.

## 0.4.1 — 2026-09-26

- E2E browsers install one app at a time, in generated projects' CI and in Keelokit's own:
  parallel installs collided on Ubuntu's package lock when a project had both web and mobile.

## 0.4.0 — 2026-09-26 — first public version

- `/keelokit:kickstart`: intake → PRD → stack → a generated pnpm monorepo (NestJS + Prisma, Vite +
  React, Expo, Astro, shared contracts and design tokens) with CI and git hooks → first backlog.
- `/keelokit:adopt`: the harness on an existing repo — only `.keelokit/`, house rules mapped to the
  checks the repo already has, dated exceptions for the rest.
- `/keelokit:intake`, `/keelokit:backlog`, `/keelokit:build` (verifier writes the acceptance tests first,
  builder, cold reviewer, verification in the running app; `--light` for small changes),
  `/keelokit:bugbash`, `/keelokit:doctor`, `/keelokit:upgrade`, `/keelokit`.
- House rules where each rule points to what checks it; `doctor` checks those checks are alive,
  that story status comes from `Story:` trailers on `main`, and that every scenario of a done
  story is cited by an active test.
- One guard for Claude Code and git's pre-commit: secrets, `.env` files, applied migrations,
  bypassing hooks, silencing tests, production deploys.
- Unit tests for the guard and doctor; `scripts/test-template.sh` and CI generate projects and run
  their full checks.
