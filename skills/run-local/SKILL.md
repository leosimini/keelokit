---
name: run-local
description: Run the product's Expo app and its API on this Mac, on an Android phone or an iOS Simulator, in one command — the script checks what the Mac is missing, shows it all at once, installs it after one yes, starts the database and the API, launches the app, and when a step fails keeps the error so Claude can read it, propose the fix and try again. Only for projects the profile marks `mobile`; macOS only for now. Use when the user says "run local", "correrlo local", "corré la app", "levantá el entorno local", "probalo en mi teléfono", "abrilo en el simulador", "no me anda el build", "run-local", after project-new's skeleton, or when the dashboard shows the local environment not set up.
---

# Run local — the app and its API on a phone or a simulator

The work is done by `.keelokit/bin/run-local.sh`, which every Keelokit project carries (new or
adopted) and which runs without Claude and without the plugin: `bash .keelokit/bin/run-local.sh`
(`pnpm run run:local` in generated projects). This skill runs it, reads what it leaves behind when
something fails, and repairs. Solo macOS: on another system the script says so and stops.

Settings live in the `[local]` block of `.keelokit/profile.toml`; whatever it leaves out, the script
detects from the repo. Messages come in the project's language (`[dashboard] lang`).

**Never**, without the user's yes for that exact thing: kill a process, stop a container, delete or
regenerate `ios/` or `android/`, uninstall the app from a phone, edit a tracked native folder. Never
type, print or commit a credential, and never write values into an `.env` yourself: the script
copies `.env.example` into the gitignored `.env`; real keys are the user's.

## 1. See where it stands

No `.keelokit/` folder: the project isn't a Keelokit one yet, so there is no script to run. Say so and
offer `/keelokit:project-adopt` (it adds only `.keelokit/`, the script included); come back here after.

Read `[local]` in `.keelokit/profile.toml` and the profile's `traits`. No `mobile` trait: say there
is no app to run here and stop. Then:

- **No `[local]` block** (adopted repos, or a project from before this existed):
  `bash .keelokit/bin/run-local.sh detect` prints what the repo shows, as JSON, with the keys it is
  not sure of in `uncertain`. Show it in plain words (where the app is, how it installs, where the
  API and the database are) and ask only about the uncertain keys, once. With the user's yes, write
  the block (or let `run-local.sh doctor` write it) and tell them to correct by hand whatever is
  wrong. Two Expo apps: ask which. Never write a guess without showing it.
- **In an adopted repo** the script also creates `.local-dev/` (logs, `last-error.txt`) and adds it to
  `.gitignore`: ask before, once, and say what it is.
- **Block present:** `bash .keelokit/bin/run-local.sh doctor --check` says whether it is coherent
  (the app is where it says, the manager exists, the folders exist). Fix a wrong key with the user.

## 2. Diagnose, then run

1. `bash .keelokit/bin/run-local.sh doctor --no-install` lists everything the Mac is missing at
   once and installs nothing. Show the list in plain words (Homebrew installs, an Android SDK, Xcode
   you can't install for them, a `sudo` prompt). Xcode, a phone with USB debugging on, and
   Expo Go on an Android phone are the user's to do.
2. Ask which target: **Android phone**, **iOS simulator**, or only the **API and database**
   (`android`, `ios`, `backend`). One at a time; the script shuts other simulators down.
3. After the user accepts the list, run the target with `--yes`:
   `bash .keelokit/bin/run-local.sh <target> --yes`. The first native build takes 10–20 minutes:
   say so. Metro keeps running in it: run it where the user can see it, or in the background and
   watch its log in `.local-dev/logs/`.

The script chooses between Expo Go and a development build (`client` in `[local]`: `auto`,
`expo-go`, `dev-client`) and says which and why. In a simulator build it can remove capabilities a
simulator can't run (Sign in with Apple, associated domains, push) from the generated `ios/`: it
shows the list and asks once. It never does it to a git-tracked `ios/` or for a phone; for a phone
without a developer certificate, explain what is missing and stop.

## 3. When it fails

The failed step's log tail is in `.local-dev/last-error.txt`; the whole log in `.local-dev/logs/`.
The script already repairs a few known causes once (a different signature on the phone, port 8081
taken, Gradle out of memory, CocoaPods' index). For the rest:

1. Read `last-error.txt`, then the log around the first real error, not the last line.
2. Say in one sentence what broke and **propose** the fix. Wait for the yes if it kills a process,
   stops a container, removes something or reinstalls native folders. Otherwise apply it.
3. Run the same target again. After **two** repairs of the same run, stop: say what was tried and
   what is left, and don't keep going.
4. If a failure repeats across projects, suggest adding it to `repair()` in the template's
   `run-local.sh`. A local edit to the project's copy is overwritten by `/keelokit:harness-upgrade`.

## 4. After it

If the app opened and reached the API, say so and how to stop it
(`bash .keelokit/bin/run-local.sh stop` asks before stopping the API and the database; the data
stays). If `[local]` was just written, refresh the dashboard (`/keelokit:project-dashboard`), which
shows "Local environment: ready".

## What is tested and what is not

Tested with simulated commands: detection on three project shapes, the coherence check, the
diagnosis, and the questions before anything is killed or edited. This version launched an app on the
iOS simulator, on an Intel Mac with Xcode 26, in a project Keelokit did not generate (not yet one
the template made). **Never tested:** a real Android phone, Expo Go on a phone, Apple Silicon. Say so when it
matters, and read the failure instead of assuming the path works.
