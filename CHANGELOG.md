# Changelog

## Unreleased

- **The bug bash runs as a workflow** where Claude Code can run them: `check-bugbash` starts
  `keelokit:check-bugbash-flow`, which fixes the procedure's shape in code — lenses from the
  profile at most four at a time, every finding reproduced by an independent skeptic (two for
  P0/P1), a completeness critic that sends more rounds while it finds gaps, merge by root cause,
  fixes one at a time each checked by an agent that didn't write it (undone if rejected), and the
  report. Its work stays out of the conversation, `/workflows` shows it live, and a run cut short
  resumes. Without workflows the skill runs the same steps as before.
- Finding prefixes for developer-facing lenses: `DX`, `DOC`, `PKG`.
- Fixed (INT-1): without `main` or `origin/main` the doctor and the dashboard took HEAD for main, so a
  pull request's own `Story:` trailers counted as done in CI and `doctor --scope` and `pnpm mutation`
  saw nothing changed. Now nothing counts as done and the doctor reports it, `--scope` exits 2 and
  `--critical --changed` takes every critical file. The generated CI's `checks` job fetches full
  history (`fetch-depth: 0`) so the doctor sees `origin/main`; `harness-upgrade` brings it.
- Fixed (LOG-4): the guard blocked `git commit -uno` (and any short flag with an n in it) as
  `commit -n`, and let through hook bypasses and force-pushes git accepts in other spellings:
  `--no-veri`/`--no-verif`, git's own options before the subcommand (`git -C dir commit -n`,
  `git -C dir push -f`, `git --config-env=core.hooksPath=… commit`), `core.hookspath` in any case,
  and `git push -uf`/`-vf`/`--mirror`. It now reads git's option grammar: n (or push's f) counts
  only as an option letter of a bundle, not as another option's value, `-n` after `--` is a path,
  and every prefix git accepts for `--no-verify` and `--mirror` is blocked (`--no-verify-signatures`
  and `--force-with-lease` pass). Already in 0.7.1; `harness-upgrade` brings the new guard.
- Fixed (DX-6): the guard exited 0 without a word when called with a mode it doesn't know, and
  crashed with exit 1 on hook input it couldn't read (empty or non-JSON stdin, JSON nested past
  Python's recursion limit, a `tool_input` that isn't an object), which Claude Code doesn't block
  on. Now both block (exit 2) and say why, as does any check that fails, so the guard ends in
  exactly 0 or 2. Already in 0.7.1; `harness-upgrade` brings the new guard.
- Fixed (DX-7): without python3 only the SessionStart hook said so; the PreToolUse hook failed on
  every call with a bare `exec: python3: not found` (exit 127) and the git pre-commit hook stopped
  the commit with the same unexplained error. Now PreToolUse turns off with Keelokit's message, as
  SessionStart does, and pre-commit stops the commit saying python3 is missing. Already in 0.7.1;
  `claude plugin update` brings the hook and `harness-upgrade` the new `.githooks/pre-commit`.
- Fixed (INT-2, LOG-2): a hand-edited `.keelokit/state.toml` that wasn't valid TOML, or an exception
  whose `expires` wasn't a date, crashed the doctor with a traceback in every mode, the SessionStart
  `--brief` included; so did a value of the wrong kind in any file it reads (`wave = "1"`,
  `gates = "…"`, a number or a date where a list goes), and a string where a list goes
  (`traits = "ui"`, `paths = "src"`) was read letter by letter. It also crashed on any file it reads
  saved in another encoding than UTF-8 (a `state.toml` or a story saved as Latin-1) or turned into a
  directory, an enforcer pointing at a directory (`test:apps/web`, `file:apps#x`) or an absolute
  glob (`test:/tmp/*`), and a critical area outside the repo (`paths = ["/etc/hostname"]` crashed
  `--critical`); an absolute or `..` path in an enforcer or `when` was looked up outside the repo.
  Now each is an ERROR naming the file, the key or the path, the value or entry is left out,
  `--brief` still prints its summary and `--ci` exits 1. Already in 0.7.1; `harness-upgrade` brings
  the new doctor.
- Fixed (CPY-1): the doctor's fix-it lines named commands the repo might not have: `--brief` ended
  with "run `pnpm doctor`" and a missing git hook said "run pnpm install", even in an adopted repo
  with no package.json. Worse, pnpm has its own `doctor` command, so that line never ran Keelokit's
  doctor in a generated project either: it printed nothing and exited 0. The doctor now says
  `python3 .keelokit/bin/doctor.py`, and for a missing hook names the repo's own install step (its
  package manager, when a package.json script sets the hooks up), the hooks path when the repo
  ships the hook, or what to add; the guard's `core.hooksPath` block says to ask a human. The docs
  and skills say `pnpm run doctor` (generated projects) or `python3 .keelokit/bin/doctor.py`.
  Already in 0.7.1; `harness-upgrade` brings the new doctor, guard and harness docs. Files the
  product owns keep the old wording: `README.md`, `docs/escapes.md`, `backlog/README.md`,
  `.keelokit/exceptions.toml`, `.keelokit/critical.toml`, `.keelokit/rules.local.toml` and, if you
  kept the example, `packages/shared/src/allocate.test.ts`. Find them with
  `git grep -n 'pnpm doctor'` and say `pnpm run doctor` (or `python3 .keelokit/bin/doctor.py`).
- Fixed (NFR-1): the doctor compared every pair of pending stories to find wave clashes, and
  searched every test title once per done story, so a backlog of a few thousand stories slowed
  every mode, the SessionStart `--brief` and the dashboard included (2000 stories in one wave: 8 s).
  It now indexes each wave's paths and critical areas and reads the test titles once: 2000 stories
  take 0.2 s. The dashboard also grouped its stories by scanning the whole backlog once per wave,
  per epic and per bug bash run (8000 stories in one-story waves: 6.8 s); it now groups them in one
  pass (2 s, most of it the doctor). Same findings and the same page as before. Already in 0.7.1;
  `harness-upgrade` brings the new doctor, and `claude plugin update` the new dashboard.
- Fixed (LOG-202): the doctor read a `ci:<job>` enforcer in one spelling only. A workflow whose jobs
  weren't indented by exactly two spaces had every job reported as missing; a job switched off with
  `if: false` (or `if: ${{ false }}`) and one with `continue-on-error: ${{ true }}` (or `True`,
  `'true'`, `"${{ true }}"`) passed as alive; and a two-space key outside `jobs:` (`push:` under
  `on:`) was taken for a job. It now reads jobs only under `jobs:`, at the indent the file uses,
  flags a job that never runs, and reads `true`/`false` in any case, bare or as `${{ true }}`, each
  unquoted or in single or double quotes. The guard blocks `continue-on-error` in the same
  spellings. A computed expression (`${{ 0 }}`, `${{ !true }}`) is still read as not constant. Already in 0.7.1; `harness-upgrade` brings the new
  doctor and guard. A job with `if: false` that enforces a rule is now an ERROR: remove the `if:` or
  register an exception with /keelokit:check-health.
- Fixed (LOG-207, LOG-208): the doctor took a `git-hook:<name>` enforcer as alive when any file of
  that name existed in the hooks path or in `.husky/`, whatever `core.hooksPath` said. An empty or
  non-executable hook, which git never runs or which checks nothing, a stray `.husky/<name>` while
  the hooks path points elsewhere or isn't set, and husky v9 (`core.hooksPath .husky/_`) before its
  install, or with `.husky/<name>` missing, all passed. It now looks only where git runs hooks
  (`core.hooksPath`, else the `.git/hooks` that linked worktrees share, which it used to miss) and
  asks for a non-empty, executable file, plus `.husky/<name>` under husky v9. Already in 0.7.1;
  `harness-upgrade` brings the new doctor. A hook it now reports is one git doesn't run: make it
  executable, install it (`core.hooksPath`, or the package manager's install for husky), or map or
  except the rule with /keelokit:check-health.
- Fixed (LOG-302): `pnpm verify` compared the root manifests with origin/main through `git diff`,
  which sees tracked files only, so a `pnpm-lock.yaml` git didn't track (a first commit made before
  `pnpm install`) read as unchanged and verify checked only the affected packages, while the
  lockfile never reached origin. pnpm's `[origin/main]` filter has the same blind spot, so a new file
  not yet added to git left its package out. Now an untracked root manifest runs everything and
  names the file, and every other untracked file adds its package (and its dependents), in one
  pass that starts no process per file, so a `.venv` or generated tree doesn't slow every push.
  `project-new` commits everything after `pnpm install`. Already in 0.7.1; `harness-upgrade` brings
  the new `scripts/verify.sh`.

## 0.7.1 — 2026-09-27

- The plugin uploads to claude.ai (Customize → Plugins → Upload): the template's file names no
  longer carry Copier conditions like `{% if 'api' in apps %}` — claude.ai rejects paths with `{`,
  `%`, `'` or spaces. The conditions moved to `_exclude` in `copier.yml`; generated projects and
  `harness-upgrade` are unchanged. A test keeps every path in the repo plain.
- claude.ai's upload also rejects skill descriptions with anything that looks like a tag:
  `project-new`'s said "quiero construir <idea>". A test keeps descriptions plain.

## 0.7.0 — 2026-09-27 — ship it

- **The project's profile** (`.keelokit/profile.toml`): what the project is (`kind`: web product,
  mobile app, API service, library, CLI, plugin, static site) and its `traits` (UI, web, mobile,
  API, database, hosted, languages, personal data, payments, developer-facing). Diagnosed, not
  assumed: `project-new` generates only what the product needs and doesn't scaffold apps for a
  library, CLI or plugin; `project-adopt` reads it from the code. House rules declare what they
  `needs` and the doctor applies only those that fit — a plugin isn't held to UI, database or
  deploy rules. It keeps up as the project grows: `plan-intake` and `build-story` update it, and
  the doctor warns when the repo shows something it doesn't list (a first migration, a new app, a
  deploy config). The bug bash picks its lenses from it — data model, contracts and screens for a
  product; developer experience, docs and packaging (three new dimensions: `dx`, `docs`,
  `packaging`) for something developers use — and `check-security`, `ship-setup`, `ship-release`
  and the dashboard follow it too.
- **`/keelokit:ship-release`**: versions of the product. Picks the next semver from what landed,
  writes release notes users understand (each line tied to its story or finding), tags `vX.Y.Z`
  on `main` after the user's yes, and follows the deploy. New house rule **REL-1**: production
  only runs a tag on `main` with its `CHANGELOG.md` entry, after a person approves the
  `production` environment in GitHub. The template gains `.github/workflows/release.yml` (checks
  the tag and the notes, then deploys the API to Fly.io behind that approval) and `CHANGELOG.md`.
- **`/keelokit:ship-setup`**: staging and production for people who have never deployed.
  Writes `docs/deploy.md` with a checklist per environment, does what needs none of the user's
  credentials (Fly.io apps and config, GitHub environments with production approval, deploy
  tokens piped into GitHub secrets), walks the user through the rest, and verifies each step.
- **`/keelokit:check-security`**: security and privacy in depth — a map of the personal data
  (`docs/privacy/data-map.md`), the privacy law of each market, a threat model of the critical
  journeys, dependency, image and staging (OWASP ZAP) scans, and checks for personal data in logs,
  export and deletion, retention and encryption. Report in `docs/security/<date>/report.md`.
- **Built with Keelokit ♥**: projects carry a small credit by default — a badge in the README and
  a line at the foot of the public site (`visible`), just the badge and an invisible generator tag
  (`quiet`), or nothing (`off`). It's never asked up front and never touches the app's screens;
  the dashboard's footer shows the level and changes it. Adopted repos start without it.
- **`/keelokit:harness-upgrade`** (was `ship-upgrade`): the same skill, named for what it does —
  maintenance of the harness, not of the app.
- The dashboard adds **Environments** (each one's checklist from `docs/deploy.md`), **Security and
  privacy** (each review's findings, pending decisions and the stories it created), **What we
  found** for adopted repos (the stack, CI and hosting `project-adopt` detected, and how the house
  rules map onto the repo), and a notice when the project's harness is older than the plugin.

### Upgrading from 0.6.x

- `/keelokit:ship-upgrade` is now `/keelokit:harness-upgrade`; run it to bring REL-1, the release
  workflow and `CHANGELOG.md` into the project.
- `/keelokit:harness-upgrade` adds `.keelokit/profile.toml` from the project's apps; add
  `personal-data` or `payments` to its `traits` if they apply (`/keelokit:check-health` helps).
- REL-1's deploy job uses the GitHub environment `production`: give it required reviewers and its
  own `FLY_API_TOKEN` (the production app's deploy token). `/keelokit:ship-setup` does both.

## 0.6.0 — 2026-09-27 — the dashboard

- **Commands grouped by area.** Every skill now carries a prefix, so the `/keelokit:` menu lists
  them together: `project-new` (was `kickstart`), `project-adopt` (`adopt`), `project-dashboard`
  (new), `plan-intake` (`intake`), `plan-backlog` (`backlog`), `build-story` (`build`),
  `check-bugbash` (`bugbash`), `check-health` (`doctor`), `ship-upgrade` (`upgrade`). `/keelokit`
  stays the entry point, and asking in words ("kickstart a new product", "build the next
  story") still reaches the right skill.
- **Dashboard** (`/keelokit:project-dashboard`): one branded page, in the user's language, with every
  stage of project-new or project-adopt, its status and approval date, and — at the stage waiting for
  approval — what to check, with the documents rendered inline: context and open gaps, the PRD's
  scope and metrics, the stack, the backlog by development wave and by epic. It shows what waits
  for the user, the next step with a command to copy, and the difference between building one
  story at a time and several in parallel. It is rebuilt from the repo every time, so a paused
  run shows where it stopped. Published as an Artifact when the session can, otherwise a local
  HTML file; its look is fixed in `skills/project-dashboard/references/design.md`.
- project-new, project-adopt, plan-backlog and build-story refresh the dashboard at every gate, never ask for an
  approval without showing what it covers, explain each term of art (PRD, stack, epic, story,
  development wave, worktree) the first time it comes up, and say "olas de desarrollo" in Spanish.
- project-new writes `docs/stack.md` (the apps chosen and why) at the stack gate.
- **Run decisions, taken once**: at the start, project-new and project-adopt ask for the run mode —
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
- A light/dark theme button (an icon) in the dashboard's top bar (remembered per viewer), and the page
  follows `[dashboard] lang` (`es`, `es-AR`, `Español`… all work) and marks its language.
- The dashboard takes the look of keelokit.com (Cormorant Garamond, Karla, Fragment Mono; the
  foam and sea palette) and opens only what matters now: the stage in progress, the wave with
  work left; everything else collapses to a one-line summary.

### Upgrading from 0.5.x

- Use the new command names; the old ones no longer exist. `/keelokit:ship-upgrade` (the old
  `/keelokit:upgrade`) brings the project's `AGENTS.md` and harness files to the new names.
- `.keelokit/state.toml` may gain `[run]` and `[dashboard]` tables; the gate keys (`intake`,
  `product`, `stack`, `skeleton`, `adopt`, `backlog`) don't change.

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
