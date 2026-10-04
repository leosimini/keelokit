# Changelog

## Unreleased — run your app on a phone, an emulator or a simulator

- **`/keelokit:run-local` and `.keelokit/bin/run-local.sh`:** the project's Expo app and its API on
  an Android phone or an iOS simulator, with one command (macOS only). The script looks at what
  the Mac is missing, shows it all at once, installs it after one yes, starts the database and the
  API, and launches the app, one target at a time; each step logs to `.local-dev/logs/` and a
  failure leaves `.local-dev/last-error.txt` for Claude to read, repair and run again (two repairs,
  then it stops). It never kills a process, stops a container or edits a tracked `ios/` without
  asking; for the simulator it can drop capabilities a simulator can't run (Sign in with Apple,
  push) from the generated `ios/`, showing the list first. Settings live in a `[local]` block in
  `profile.toml`, detected from the repo where missing (pnpm, npm or yarn; a backend in any
  folder; the API address variable). Messages follow the project's language, English or Spanish.
  New projects with a mobile app get the block and `pnpm run:local`; `project-adopt` writes the
  block after a yes. A new house rule, RUN-1 (SHOULD, mobile projects), asks for the script and the
  block; the doctor warns when the block is missing, and the dashboard shows the local
  environment. Launched on the iOS simulator and on a Galaxy S20 over USB (Intel Mac). Not tested: Expo Go on a phone, wireless debugging, Apple Silicon.
- **`run-local` does not rebuild what is already installed.** A second `android` or `ios` finds the
  app on the target and the native inputs unchanged since the last successful install (a
  fingerprint: `@expo/fingerprint` when the project has it, else a hash of dependencies, lockfiles,
  app config and tracked native folders), and only starts Metro and opens the app by its link. It
  says which path it took and why; `--rebuild` and `--no-build` force either way, a failed build
  never leaves a stale fingerprint, and `metro` starts only Metro (plus `adb reverse`).
- **Android, for people without a phone and with several.** With no phone connected it offers an
  emulator; with none created it offers to create one, shows that the system image is a 1–2 GB
  download and downloads only after a yes; it boots it in the background and waits for it.
  Several phones are listed with the choice remembered (`--device` overrides), `pair` walks through
  wireless debugging without keeping the address or code, and an emulator or a phone is never shut
  down without asking. When an install fails for lack of storage, it explains it and offers, each
  with its own yes, to uninstall the app and retry, to create a new emulator with an 8 GB data
  partition (`--new-avd`; an installed image is reused without a download), or to cold boot with
  `-wipe-data` (named, with the warning that it erases the emulator's apps and data); with `--yes` it
  stops and lists them. Not tested: the emulator itself and wireless debugging.
- **`run-local` asks what has a real choice, and keeps the test users at hand.**
  - With a phone connected and an emulator available, `android` asks "phone or emulator?" at a terminal
    (default: last time's, kept in `.local-dev/android_target_last`); `--phone` and `--emulator`, or
    `[local] android_target` (`ask`, the default; `auto`; `phone`; `emulator`) answer it, and with
    `--yes` or no terminal it takes the last choice and says how to change it.
  - Before launching it asks "Load the seed data?", recommending it when the database looks empty
    (best effort, through the compose service's `psql`) and saying so when it can't tell; the answer is
    the next default, `--seed` and `--no-seed` answer it, and `--yes` alone never seeds.
  - `users` prints the test accounts the project lists: `[local] users_file`, else `docs/test-users.md`,
    `docs/local-testing.md`, `docs/local-android-testing.md`, a README section (Test users, Demo
    accounts, Usuarios de prueba...), else the credential-looking lines of the last seed's log, as raw
    lines with their source (`--json` too, and in `status --json`). A short block is printed when a
    launch starts and after the seed. It reads only files of the project, never `.env`, and writes
    nothing. The skill asks the same questions with the question tool and maps them to the flags.
- **`run-local` no longer mistakes another project's API for its own.** Something answering on the
  API port is reused only when its working directory or command line is this project's (or its
  compose project publishes the port). Otherwise it says who holds the port, and asks: stop it (only
  with a yes), start this project's API on the next free port (passed to the app through the API URL
  variable and kept in `.local-dev/api_port`), or cancel. With `--yes` or no terminal it takes the
  next free port when the API reads `PORT`, else exits 3 and explains; it never reuses or stops a
  foreign API, and an owner it can't determine counts as foreign. `status --json` has `api.owned`.
- **`run-local` keeps Metro alive when nobody is at a terminal.** Run from Claude, CI or the
  background, Expo read the end of its input and shut Metro down, leaving the app installed with no
  Metro. The command now gets an input that never ends (and Expo Go's one `y` with `--yes`), stopped
  with the command, and if Metro still ends by itself with no Ctrl+C the script says so and exits 1
  with the log, instead of calling it a normal stop.
- **`users` takes the accounts table, not every line that mentions an email or a password.** It finds
  the largest run of consecutive lines with an email, adds the table header, the password sentence
  above it and a password note below it, drops env assignments, shell commands, links and install
  rows, cuts at 15 lines saying where the rest is, and when there is no table of two accounts it
  offers a guess from lines pairing a user with a password and says it is a guess.
- **Expo Go with `--yes`.** When Expo asks to install or update Expo Go on the simulator or phone
  (it downloads the app from Expo), `--yes` answers it and says so; without `--yes` at a terminal Expo
  asks as before. If that prompt is cancelled for lack of a terminal, the run fails with exit 3 and
  explains it, instead of looking like a stop.
- **iOS asks before a link opens the app.** On the simulator's fast path the script says that iOS
  asks "Open in <app>?" (tap Open) and opens the link. Launching the app first was tried on
  hardware: the dev launcher opens but does not reconnect to Metro by itself. Android has no such
  prompt.
- **`run-local` never waits on a menu nobody can answer.** With `--yes` it takes the remembered
  simulator, phone or emulator (else a booted simulator, else the first), says which and how to change
  it, and goes on (it never creates an emulator that way). Without `--yes` and without a terminal it
  gives up after 20 seconds (`RUN_LOCAL_ASK_TIMEOUT`) with exit 4 instead of blocking forever.
- **The rest of the environment.** `[local] services` (redis, mailpit...) start and stop with the
  database. The seed is detected and offered once, never run silently (`seed` runs it by name).
  The JDK follows React Native (17 from 0.73, 11 before) and Node follows `.nvmrc`, `.node-version`
  or `engines`; a Node from nvm is used for the run only and installing one needs a yes. yarn
  (classic and berry), bun, turborepo, nx and lerna are detected, and a root `dev:api`-style script
  is preferred.
- **Readable by Claude and by people.** `doctor --json`, `status [--json]` (what runs, and who holds
  each port), `logs [step]`, `clean` (lists what it would delete with sizes and asks per group;
  never touches what git tracks or anything outside the project), `--help` for every command,
  documented exit codes (3: only a person can fix it; 4: a question was declined), and the repair
  table is one block of data at the top of the script.
- Upgrading from 0.8.x: `/keelokit:harness-upgrade` brings the script. `profile.toml` is the
  project's, so a mobile project gets no `[local]` block from it: run `/keelokit:run-local` to
  detect and write one, or the doctor keeps warning (RUN-1).

- **Fixed (template): a generated mobile app no longer crashes at startup on a phone.** The shared
  translator used `Intl.PluralRules`, which Hermes (React Native's engine) does not have, so the app
  died with "undefined cannot be used as a constructor" on a simulator or phone while the tests and the
  web export passed. It now uses `Intl.PluralRules` when it exists and, otherwise, `one` for exactly 1
  and `other` for the rest (English and Spanish), with a test that removes `Intl.PluralRules`.
  `packages/shared/src` belongs to the product, so `harness-upgrade` does not bring it: an existing
  project applies the same change by hand (the new `pluralSelector` in `i18n.ts`). A locale with more
  plural categories still needs a polyfill or a library on native.

## 0.8.3 — 2026-10-03 — a description that says what sets Keelokit apart

- The plugin's description says what sets it apart: no agent calls its own code done, and every
  bug leaves a check.

## 0.8.2 — 2026-10-03 — new projects pass their audit, and a dashboard that puts first what comes first

- **New projects pass `verify` again.** Three high advisories with no fixed version upstream
  (in Expo, Jest and Astro dependencies) were failing every new project's dependency audit. The
  audit (`.keelokit/bin/audit.py`, in `verify` and CI) now fails on advisories that have a fix and
  lists the ones that don't yet; they start failing once upstream ships one. `harness-upgrade`
  brings it to existing projects.
- The dashboard's next step puts first what comes first: a blocking question before approving the
  context, and harness errors before any stage once the harness is in place (LOG-303).
- A bug bash under way shows on the dashboard and the report as running, with its findings so far,
  before its report exists (UX-5).
- Doctor keeps warning about a done story that touches a critical area without `integrity`; it used
  to go silent once the story merged (LOG-304).
- Document links in the report no longer sit inside the row that opens them, and each says which
  file it opens to a screen reader (A11Y-4).
- The guard's message for deleting or touching an `.env` file says that, not "don't write" (LOG-3).
- Two runs of `scripts/test-template.sh` on one machine take turns installing browsers (PKG-3).

## 0.8.1 — 2026-09-28 — a stricter guard, safer links and workflows, and accessibility fixes

- **Security:** the guard knows more kinds of keys (npm, GitLab, JWT, Azure storage) and catches a
  key split across two edits. Before a commit, it now scans each staged file whole, so a key split
  across two commits is also caught (SEC-1). `harness-upgrade` brings the new guard.
- **Security:** a link in a project document can't point outside the project in the dashboard or the
  report: `/etc/passwd` or a `../..` chain shows as plain text (SEC-4).
- **Security:** the bug bash workflow passes to its agents, marked as data and never as
  instructions, everything the repository says and every finding earlier agents wrote (SEC-5).
- The README says plainly what opening a repo with Keelokit on means: the plugin's hooks run the
  project's own `.keelokit/bin` code, so open only repos whose `.keelokit/` you trust (SEC-3). It
  also says the dashboard's link is saved in `.keelokit/state.toml` (SEC-6).
- The report writes dates in its language: "28 sep 2026" or "Sep 28, 2026" (I18N-5).
- Keyboard focus is visible everywhere on the dashboard and the report, including the blue band
  (A11Y-102). A screen reader announces "Copied" when you copy a command from the report (A11Y-6).
- Fixed: security reviews and bug bashes write their scope under a `## Scope` heading, where the
  dashboard reads the report's commit (DOC-203). `harness-upgrade` names every harness file the
  project keeps, `profile.toml` and `critical.toml` included (DOC-102). The plugin describes itself
  with one sentence in both manifests (CPY-4). The report's review pill uses a palette colour (UI-3).

## 0.8.0 — 2026-09-28 — a live dashboard, a report to share, the plugin ready to install

- **A lighter, live dashboard, built to spend as few tokens as possible.** `/keelokit:project-dashboard`
  is now the page you work from: where the project is, the next step and its command to copy, what
  waits for you (approvals and the decisions bug bashes and security reviews left, with the
  recommended option), the development waves with every story linked to its file, health and
  environments, links to the project's documents. It is published once as a shell with its design
  and kept current through the artifact's database: a refresh writes one small data document from
  a file, so the page never goes through the chat again — a refresh costs a small fraction of the
  tokens a full page did (the shell is about 20 KB, published once; the data about 8 KB, written
  without passing through the conversation) — and an open page updates by itself, keeping what you
  had open. Where the session has no database, the same page is published whole.
- **Status report to share or export:** `/keelokit:project-report` generates the complete,
  read-only page — every stage with its documents, bug bashes and security reviews with their
  findings, environments, decisions and history — as an Artifact you can share or a standalone
  HTML file. It has no buttons that send requests: it's for reading.
- **Every release carries the plugin ready to install:** `keelokit-plugin.zip`, attached to its
  GitHub Release, with the manifest at the zip's root and only the plugin inside (skills, agents,
  hooks, references and the project template — not the repository's CI, tests or scripts). Upload
  it in Claude (*Customize → Plugins → Upload*). The README and keelokit.com link to the latest
  one. *Source code (zip)* stays the whole repository, not the file to upload.
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
- Fixed (DX-8): `doctor.py --scope` with no story id printed `No story  in backlog/stories` and
  exited 1; now it prints its usage and exits 2, as does an unknown mode or a stray argument.
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
- Fixed (INT-202): the doctor reported an ERROR for every `.md` under `backlog/stories/` without
  `+++` front matter, so an adopted repo that already kept its own tickets or a README there failed
  `doctor --ci` over files Keelokit never wrote, while the dashboard skipped them without a word.
  A file whose first line isn't `+++` is now not a story: a warning names it and both leave it out.
  One that opens with `+++` is still a story, and an ERROR when its front matter doesn't parse;
  front matter that closes at the end of the file now parses, as it does in the dashboard, and
  `doctor --scope <ID>` says why it found no story. Already in 0.7.1; `harness-upgrade` brings the
  new doctor.
- Fixed (DOC-1): `rules.toml` lists the guard as an enforcer of REL-1 (production only from a
  tag), but the guard never named REL-1: its docstring left it out and its production-deploy block
  cited only AGENT-1. That block now cites `AGENT-1/REL-1` and says production goes out from a
  `vX.Y.Z` tag through CI, and the docstring lists REL-1. Already in 0.7.1; `harness-upgrade`
  brings the new guard.
- Fixed (PKG-101): the generated Release workflow's check that `CHANGELOG.md` has the tag's entry
  matched the version as a prefix, so tagging `v0.7.1` passed with only a `## 0.7.10` (or
  `## 0.7.1-rc.1`) entry and went on to the production deploy. It now needs the heading
  `/keelokit:ship-release` writes, `## X.Y.Z — <date>`, as Keelokit's own release does; an entry
  written by hand without ` — <date>` no longer counts. Already in 0.7.0; `harness-upgrade` brings
  the new `.github/workflows/release.yml`.
- Fixed (DX-4, DX-5): a product name starting with a digit ("3D Store") stopped `project-new` and
  `project-adopt` at copier with a traceback, because the slug derived from it started with a
  digit, which copier's own check rejects; accented letters became dashes ("Peña" → `pe-a`). The
  slug now folds accents (`pena`, `strasse`, `lodz`) and puts `app-` in front of a digit or of a
  name with no Latin letters (`app-3d-store`), and `project-new` lets copier derive it. Already in
  0.7.1; affects new projects only (an existing project keeps its slug).
- Fixed (DX-2, NFR-3): the dashboard drew a full "new product" page for a `--root` that doesn't
  exist (or is a file), and crashed with a traceback when it couldn't write its page (a read-only
  checkout, a folder where the page goes). Now the first exits 2 and the second 1, each with one
  line naming the path and, for a write, pointing at `--out` or `--json`. Already in 0.7.1.
- Fixed (CPY-6): the dashboard had no singular, so a count of one read "1 exceptions recorded",
  "Of 1 rules", "1 open questions" or "1 historias" (and the same for errors, stories, waves,
  epics, steps and environments). Every count now agrees with its number, in English and Spanish.
  Already in 0.7.1.
- Fixed (I18N-1): a Spanish dashboard spliced the doctor's English into its own sentences: profile
  drift read "El perfil del proyecto quedó desactualizado: the repo shows `web` (apps/web) but the
  profile doesn't list it", and the health block showed the doctor's output as if it were the
  page's text. The page now reads the drift back into the trait and the path and says it in its
  own language, and the health block quotes the doctor's output as a log, under a caption that says
  it is in English (and marked `lang="en"` for screen readers). Already in 0.7.0;
  `claude plugin update` brings the new dashboard.
- Fixed (I18N-2): the dashboard found what it reads in the documents only by their English names,
  so a PRD written in Spanish showed "0 métricas · 0 en el alcance · 0 afuera" and no metrics or
  scope blocks, a Spanish bug bash or security report lost its pending decisions (and its "Decide"
  button) and could show a sha from the wrong section, a decision record with `Estado: Aceptada`
  (or `## Estado`) showed no status, and a `docs/stack.md` that says `Aplicaciones:` showed no apps.
  Each one is now found by its name in English or Spanish (`Métricas de éxito`, `Alcance`,
  `Dentro`, `Afuera`/`Fuera`, `Decisiones pendientes`, `Estado`, `Aplicaciones`), whatever the
  page's language, ignoring case and accents. A heading has to match whole words, so a
  `**Integrations:**` list inside Scope no longer counts as in scope, and a bold sub-label inside
  In or Out (`**Buyers**`) keeps its bullets there. Already in 0.7.1; `claude plugin update` brings
  the new dashboard.
- Fixed (UX-1): before a backlog existed (an adopted repo at intake, a new project before its
  stories, or every gate approved with no stories yet), the dashboard's "N harness errors to review"
  item and its "fix the harness" next step linked to the Build section, which the page only draws
  once there are stories, so the link went nowhere. The doctor's output now has its own Harness
  health section until there is a backlog (inside Build after that), and both links open it. In an
  adopted repo, the decisions card's ADRs linked to a Stack stage only new projects have; they now
  open their file. Already in 0.7.0; `claude plugin update` brings the new dashboard.
- Fixed (UX-2): the dashboard's "Build wave N in parallel" button sent `/keelokit:build-story` with
  only a count, which build-story spends on the first wave with ready stories, so with two waves
  ready the wave 2 button built wave 1; the next step's hint had the same count. Both now send the
  wave's stories by id (`/keelokit:build-story AUTH-002 AUTH-003`), and `build-story` takes several
  ids of one wave and builds exactly those in parallel. Already in 0.7.0; `claude plugin update`
  brings the new dashboard and skill.
- Fixed (UI-1): on a phone (320 px) a long story id, a blocked story's "Waits for …", the project
  name or a long word in a title, command or value pushed the dashboard and the report sideways, and
  the report's short facts squeezed their value to nothing. Every text now wraps inside its box, at
  any width. Already in 0.6.0; `claude plugin update` brings the new dashboard.
- Fixed (UI-2): in the report's backlog, with the view switched to "by epic", a link to a story
  landed on its hidden "by wave" copy and nothing opened. A link to a story now opens it in the view
  showing, and switches views when it points into the other. Already in 0.6.0.
- Fixed (A11Y-2): in the light theme the dashboard's secondary text, its "Not started" and review
  pills and its MUST tags were below WCAG AA contrast (3.5–4.3:1), "Not started" in dark too, and in
  both themes the eyebrows, stage numbers and labels on the blue band and its in-progress pill
  (2.6–4.0:1). All of it now reaches 4.5:1. Already in 0.6.0; `claude plugin update` brings the fix.

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
