# Next sessions

What Leo does by hand, and what's left, in the order to take it. Not a story file: the doctor and the
dashboard read only `stories/`. Where things stand is not kept here: ask `python3 .keelokit/bin/ledger.py`
(`show <ID>` for one story, `--release vX.Y.Z` for a version).

## For Leo, by hand

- [ ] Press **Publish** for 0.8.3 at claude.ai/directory/manage (auto-publish is off).
- [ ] GitHub repo description (Settings → About): `Stop agents from calling buggy code "done": a
  Claude Code plugin where separate agents test, review and try to break every story, and each bug
  leaves a check. By Leopoldo Simini.`
- [ ] GitHub profile: name "Leopoldo Simini", bio mentioning Keelokit, pin the repo, profile README
  (`leosimini/leosimini`).
- [ ] Launch, in order (drafts in `backlog/launch.md`): blog post under your name → Show HN →
  r/ClaudeCode and r/ClaudeAI → LinkedIn. awesome-claude-code form from 2026-10-10.

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

- [ ] **LEDGER-001..015** (waves 5–19): the ledger. Design, decisions for Leo and the launch
  order in `docs/ledger.md`; build one story at a time, starting with LEDGER-001.
- [ ] **FLEET-001..006** (waves 20–25): lessons from the JOUNA fleet, in `docs/fleet-lessons.md` with the
  build order (FLEET-001 and 003 right after LEDGER-002).

## Smaller things

- [x] README screenshots (`docs/assets/dashboard-{en,es}.webp`) show Fleetly (2026-10-03).
- [ ] SEC-6: to keep the dashboard link out of a public repo, the link would move to a git-ignored
  local file (option B). `state.toml` can't be ignored, since it also holds the gates.
- [ ] Next release: a bug bash first (`/keelokit:check-bugbash`), then `scripts/release.sh`.
