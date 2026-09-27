# Releasing Keelokit

## Where each thing lives

| Ref | What it is | Who reads it |
|---|---|---|
| `main` | Where work lands, always green | Keelokit's own marketplace (`claude plugin marketplace add leosimini/keelokit`) |
| `release` | The last released commit of `main` | The Claude plugin directory, which tracks this branch through a GitHub push webhook |
| `vX.Y.Z` tags | One per release, made by the Release workflow | `project-new`, `project-adopt` and `ship-upgrade`, which fetch the template at `v` + the plugin's `version` |
| GitHub Releases | One per tag, made by the same workflow; its notes are the version's CHANGELOG entry | people reading release notes, and keelokit.com's "Latest release" link |

Three facts shape the process:

- **Every push to `release` is a directory version.** It gets scanned, then published by a
  reviewer or on its own, depending on the plugin's auto-publish setting in
  [claude.ai/directory/manage](https://claude.ai/directory/manage). Pushes to `main` don't reach it.
- **Users only update when `version` changes.** Claude Code compares the `version` in
  `.claude-plugin/plugin.json`, so if the string stays the same, nobody gets the new commits.
  When a plugin updates, users only see "Plugins changed. Run /reload-plugins"; nothing shows
  release notes. `CHANGELOG.md` is the release notes.
- **A version without its tag breaks new projects.** The skills fetch the template at
  `v<version>`. The Release workflow creates that tag on every push to `release`, so the
  version only changes in the release commit, never before.

## While working

- Merge into `main` as usual; CI must be green.
- Add every change a user would notice to `CHANGELOG.md` under `## Unreleased` at the top
  (`## Unreleased — <title>` if the release has a theme). Changes to Keelokit's own tooling
  (its CI, its tests, this document) don't go in.
- If a change needs manual steps in existing projects, add an `### Upgrading from X.Y.x`
  subsection, as 0.5.0 does. `scripts/test-template.sh --update-from` runs those steps.
- Don't touch `version` in `plugin.json`, and don't push to `release` or create tags.

## Cutting a release

1. Check that CI is green on the tip of `main`.
2. Pick the version:
   - **patch** (0.5.1): fixes and wording.
   - **minor** (0.6.0): new skills, agents or rules, template changes, anything with upgrade
     steps.
   - **major**: once there's a 1.0.
3. Run `scripts/release.sh X.Y.Z` on an up-to-date `main`. It does the following:
   - renames `## Unreleased` to `## X.Y.Z — <today>`;
   - sets `version`;
   - runs the unit tests and `claude plugin validate --strict`;
   - commits `release: X.Y.Z`;
   - pushes `main`, then `release`.
4. Check that the **Release** workflow on GitHub created `vX.Y.Z` and its GitHub Release. It fails if the CHANGELOG
   has no entry for the version, if `release` isn't a commit of `main`, or if the tag already
   exists on another commit.
5. In [claude.ai/directory/manage](https://claude.ai/directory/manage), follow the version's
   scan and select **Publish** if auto-publish is off.
6. If the release changed the template, point the "update from" row of `.github/workflows/ci.yml`
   at the new tag on `main`, so the next release tests the upgrade from this one.
7. Review the sites, and take the chance to improve their wording:
   - [keelokit.com](https://keelokit.com) (`leosimini/keelokit.com`, deploys from `main` on
     Vercel). Its "Latest release" line updates by itself, because it reads the `release`
     branch, and links to the version's GitHub Release. If the dashboard changed, regenerate its
     screenshots (`public/img/dashboard/`) and the README's (`docs/assets/dashboard-*.webp`). By hand: the terminal examples in `src/lib/content.ts`, if `verify.sh`,
     `doctor.py`, `guard.py` or the number of rules changed, and the commands, agents, rules
     and CI steps in `src/i18n.ts`.
   - The Keelokit page on [leopoldosimini.com](https://leopoldosimini.com/keelokit)
     (`src/content/pages/{en,es}/keelokit.md`).

## How often

Group changes: a release every few weeks, or sooner for a bug that breaks users. Every version
goes through the directory's scan, and possibly a review, again. The version of a release that
went wrong isn't reused: fix it in `main` and release the next patch.

## Directory scan notes

The directory scans the whole repository, including `template/`. Two findings are expected, and
the submission explains them:

- **Uses a credential from the user's machine** (policy hold). It pairs `FLY_API_TOKEN` in the
  template's CI with any network call in the repo. That token is a GitHub Actions secret of the
  generated project; the plugin never reads it. The README's "Data and network" section says so.
- **Hook output uninspected.** The PreToolUse hook runs `.keelokit/bin/guard.py` from the user's
  project, so the scan can't read it. The guard only blocks (exit 2) or lets the call through
  (exit 0); it never approves.

- **Uses hooks.** Information only.

Instructions for agents working on this repo live in `AGENTS.md`, loaded through
`.claude/CLAUDE.md`. A `CLAUDE.md` at the root would be the plugin's root too, and the directory
flags it because plugins don't load it.

Any new finding needs a real fix or a line in the submission notes. Don't reword files just to
get past the scanner.
