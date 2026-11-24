---
name: ship-release
description: Release a version of the product — pick the next semver from what landed since the last tag, write the CHANGELOG entry in words users understand (stories done, bug fixes, what changed for them), tag vX.Y.Z on main after the user says yes, and follow the production deploy, which waits for a person to approve it in GitHub. Use when the user says "release", "sacá una versión", "publicá", "pasemos a producción", "versioná", "ship it", "deploy to production", after a wave or a bug bash, or when the dashboard proposes it.
---

# Ship release — a version people can name, read about and roll back to

The rule is REL-1 (`.keelokit/harness/rules.toml`): production only ever runs a `vX.Y.Z` tag on
`main` that has its `CHANGELOG.md` entry, and a person approves the `production` environment in
GitHub before it deploys. Staging keeps deploying every green `main`. Creating the tag is a
production decision: ask, and wait for a clear yes (execution protocol, "Reserved for the human").

For a developer-facing project (profile: library, CLI, plugin, template) there is no production
environment: the release is the tag, the notes and publishing the package where its users get it
(npm, the plugin directory, a registry) — REL-1 doesn't apply. Everything else below does.

## 1. Ready?

- On `main`, up to date, working tree clean; CI green on the tip (the staging deploy included).
- `python3 .keelokit/bin/doctor.py` passes, and `python3 .keelokit/bin/ci.py health` doesn't alarm
  (a cancelled run is not a green one).
- For a launch (the first production release): `python3 .keelokit/bin/doctor.py --launch` exits 0 —
  `docs/prelaunch-debt-ledger.md` has every finding fixed or decided with a recommendation, and
  nothing under "Needs the owner" is still `needed`. A "known issue" is not a decision (DEBT-1).
- Nothing half-done: every story merged since the last tag is `on-trunk` in the ledger
  (`python3 .keelokit/bin/ledger.py`), and `ledger.py check` reports nothing unattributed; a wave
  that is only partly done is fine — say which stories are in and which wait.
- With a UI (profile trait `ui`): the release walk-through is done (UX-5, `docs/ux-quality.md` §6) —
  the candidate on staging, every journey, every surface and theme, before the owner is told it is
  ready. Any P0 or P1 stops the release until fixed or the owner decides; list what it found
  under the release notes' "For the team".
- A bug bash since the last release is recommended (`docs/bugbash/`); if there is none, say so
  and offer `/keelokit:check-bugbash` first. Blocking findings or pending decisions stop the
  release until the user decides.
- `/keelokit:check-security` recommended before the first production release and before any
  release that touches personal data, auth or payments.

## 2. What goes in, and the version

`git describe --tags --abbrev=0` (none → first release, `v0.1.0`, or `v1.0.0` if the user calls
it a public launch). Since that tag: the stories the ledger has `on-trunk` and in no version yet
(`python3 .keelokit/bin/ledger.py --json`: `state`, `title`; never your own reading of `Story:`
trailers), `fix(…)` commits (bug bash ids in them), and migrations. The version's list of stories is
`ledger.py --release vX.Y.Z` once the tag exists (step 4); a past version's, the same with its tag.

- **major** — something users or other systems rely on changes or goes away: a breaking API
  contract (`packages/shared`), a migration that needs manual steps, a removed feature.
- **minor** — anything new people can do.
- **patch** — fixes and wording only.

## 3. Release notes

Write the entry at the top of `CHANGELOG.md` (create it from the template's if missing), in the
language the product's users read:

```markdown
## 1.3.0 — 2026-10-14

### New
- Patients can move their own appointment from the booking link. (SELF-004)

### Fixed
- Two people could book the last slot at the same time. (INT-1, bug bash 2026-10-10)

### For the team
- Migration `20261012_add_reschedule` runs on deploy; no manual steps.
```

Say what changed for the user, not how it was built. Every line points to its story or finding.

## 4. Ask, then tag

Show the user the version, the notes and what will happen: the tag starts the Release workflow,
which checks the tag and the notes and then **waits for a person to approve** `production` in
GitHub (Actions → the run → Review deployments). If the `production` environment has no required
reviewers yet, say so: the deploy would go out without that approval; `/keelokit:ship-setup`
sets it up.

On a clear yes:
```bash
git commit -am "release: vX.Y.Z" -m "No-story: release" && git tag -a vX.Y.Z -m "vX.Y.Z"
python3 .keelokit/bin/ledger.py --release vX.Y.Z   # the version's stories, from the local tag
git push origin main vX.Y.Z
```
`No-story: release` is the trailer `ledger.py check` asks of every commit after `[ledger] since`; its own `-m`
makes it the last paragraph, the only one git reads trailers from. The notes name exactly the stories `ledger.py --release` lists. If they differ, push nothing: `git tag -d
vX.Y.Z`, fix the notes and show them again.
Mobile apps: bump `version` in the app config and let EAS number the build; store submissions stay
with the human (AGENT-1).

## 5. Follow it

Watch the Release workflow; report when it waits for approval, and when it deployed (the
production `/health`). If it fails, fix forward on `main` and release the next patch — never move
or reuse a tag. Refresh the dashboard (`/keelokit:project-dashboard`).
