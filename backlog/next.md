# Next sessions

Where things stand after 0.8.1 (2026-09-28), and what's left, in the order to take it. Not a
story file: the doctor and the dashboard read only `stories/`.

## Where things stand

- **0.8.1 is out**: tag `v0.8.1`, GitHub Release with `keelokit-plugin.zip`, `release` branch
  pushed, CI green on `main` (its upgrade test starts from v0.8.1).
- **keelokit.com** is live with 0.8.1: "startups", the new crew rule, the keel lead in a personal
  voice, no "card" line, and screenshots of the Fleetly sample. The version and the zip link come
  from the latest GitHub release by themselves.
- The screenshot generator lives in the keelokit.com repo, `tools/dashboard-shots/` (sample
  project `fixture.py` + `shots.py`; see its docstring).

## For Leo, by hand

- [ ] Press **Publish** for 0.8.1 at claude.ai/directory/manage (auto-publish is off).

## Bug bash 2026-09-27: open findings

None. Fixed on `main` after 0.8.1 (in `## Unreleased`): LOG-303, LOG-304, A11Y-4, UX-5, PKG-3,
LOG-3. A11Y-101 is not a bug (an Artifact without GitHub has no URL a browser can open).

## Bug bash 2026-09-27: decisions still open

Each has its options and a recommendation under `## Pending decisions` in the report: CPY-5,
I18N-3, UX-4, UX-3, A11Y-3, INT-101, LOG-205, LOG-206, LOG-211, INT-201, DOC-201, DOC-202.
The SEC ones were decided on 2026-09-28 and are done.

## Stories (backlog/stories)

- [ ] **HARN-001** (wave 1): mutation testing for the guard and the doctor (lifts the MUT-1
  exception, which expires 2027-01-31).
- [ ] **HARN-003** (wave 1): an exception scoped to some paths, honoured by the guard (GAP-001).
- [ ] **HARN-002** (wave 2): the lint enforcer check reads what a config really enables (LOG-209).
- [ ] **HARN-004** (wave 3): the hooks stop running the project's own `.keelokit/bin` code
  unchecked (SEC-3, options B or C).

## Smaller things

- [x] README screenshots (`docs/assets/dashboard-{en,es}.webp`) show Fleetly (2026-10-03).
- [ ] SEC-6: to keep the dashboard link out of a public repo, the link would move to a git-ignored
  local file (option B). `state.toml` can't be ignored, since it also holds the gates.
- [ ] Next release: a bug bash first (`/keelokit:check-bugbash`), then `scripts/release.sh`.
