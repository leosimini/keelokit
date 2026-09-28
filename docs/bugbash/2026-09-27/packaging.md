# packaging

Lens: packaging. Scope: full, HEAD 19b332e (branch `claude/vigilant-hamilton-u202mw`, 2 commits
ahead of main = origin/main = origin/release = tag v0.7.1 = fca160c). All work done in scratch
clones/clones under the session scratchpad; `/home/user/keelokit` itself was never modified
(read-only) except for creating this file.

### PKG-1 · A naive zip of the working copy ships this repo's private planning dump and the packager's local file paths (P2)
- **Persona / context:** claude.ai user uploading the plugin as a zip (Customize → Plugins →
  Upload), sha 19b332e.
- **Steps:**
  1. On a machine where the maintainer/dev has ever run the test suite and the dashboard locally
     (both are documented, ordinary things to do — `python3 -m unittest discover -s tests`,
     `/keelokit:project-dashboard`), the working copy on disk has `tests/__pycache__/*.pyc`,
     `template/.keelokit/bin/__pycache__/*.pyc` and `.keelokit/out/dashboard.html`, none of them
     tracked by git (`.gitignore`: `__pycache__/`, and `.keelokit/out/.gitignore`: `*`).
  2. Nothing in README.md, README.es.md, AGENTS.md or docs/ tells a claude.ai-upload user to
     package with `git archive` (or equivalent) rather than zipping the folder they have —
     `grep -rn -i "zip\|upload" README.md README.es.md docs/*.md AGENTS.md` returns nothing.
  3. Reproduced: `cp -a /home/user/keelokit/. $SCRATCH/workingcopy/keelokit/ && rm -rf
     $SCRATCH/workingcopy/keelokit/.git && cd $SCRATCH/workingcopy && zip -r -X
     keelokit-workingcopy.zip keelokit`, then `unzip -Z1 keelokit-workingcopy.zip`.
- **Expected:** "nothing private ships" (dimensions.md, `packaging` row); the plugin's own test
  (`tests/test_paths.py`) exists specifically because claude.ai's upload is a real, documented
  path (README section on install is silent about it, but the CHANGELOG's 0.7.1 entry and
  `docs/releasing.md`'s directory-scan notes confirm the plugin is meant to be uploadable).
- **Observed:** the zip contains `keelokit/tests/__pycache__/test_guard.cpython-311.pyc`,
  `keelokit/template/.keelokit/bin/__pycache__/doctor.cpython-311.pyc` and
  `keelokit/.keelokit/out/dashboard.html`. The `.pyc` files embed the packager's absolute local
  path: `python3 -c "import marshal; f=open('tests/__pycache__/test_guard.cpython-311.pyc','rb');
  f.read(16); print(marshal.load(f).co_filename)"` prints `/home/user/keelokit/tests/test_guard.py`.
  `.keelokit/out/dashboard.html` is a full static render of this project's own
  `docs/context/*.md` — product plan, personas, domain glossary, all six invariants, and the
  open gaps table naming the maintainer by first name ("Leo") next to unresolved questions
  (GAP-001..003) — none of that is something a person zipping "the plugin" to upload it means to
  publish as part of the plugin payload.
- **Evidence:** `$SCRATCH/pkgdir/workingcopy-paths.txt` lines 73-78, 90-92 (see the run log);
  `.keelokit/out/dashboard.html:265` renders the GAP table with "Leo" as owner; the `.pyc`
  `co_filename` command output above.
- **Where:** `.gitignore`, `.keelokit/out/.gitignore`, `tests/test_paths.py` (only checks
  `git ls-files`, so it can't see this).
- **Root cause (probable):** the project has a real, if undocumented, "package for claude.ai
  upload" step, but nothing defines or enforces it — a plain `zip -r` of a used working copy is
  the path of least resistance and it includes every gitignored build/output artifact.
- **Class:** isolation.
- **Should have been caught by:** dimensions.md's `packaging` automatic check
  ("Build/validate the package in CI") — but CI only validates the git-tracked tree
  (`actions/checkout`), never a zip of a working copy, so this path has no automatic check at all.
- **Proposed fix:** document (README or a short "packaging for upload" note) that the zip must
  come from `git archive` (or a clean `git clone`), not the working directory; optionally have
  `tests/test_paths.py` or a release step assert `.keelokit/out/` and `__pycache__/` are excluded
  from any zip a maintainer builds for submission.

### PKG-2 · The "no tag-like text" and path-safety tests don't cover every description that ships to claude.ai (P2)
- **Persona / context:** claude.ai user uploading the plugin zip; also the maintainer relying on
  CI as the packaging gate before a release.
- **Steps:**
  1. Read `tests/test_paths.py` (`python3 -m unittest discover -s tests` is the documented,
     CI-enforced packaging gate per AGENTS.md and `.github/workflows/ci.yml`'s `unit` job).
  2. It walks only `skills/*/SKILL.md` and `agents/*.md` for a `description:` line and rejects
     `<...>`-shaped text in it.
  3. `.claude-plugin/plugin.json`'s `description`, `.claude-plugin/marketplace.json`'s top-level
     and per-plugin `description`, and `workflows/check-bugbash-flow.js`'s exported
     `meta.description` are never inspected by this test, or by any other test in `tests/` —
     confirmed with `grep -rn "description" tests/*.py`.
- **Expected:** every string claude.ai's plugin-upload validator inspects should be covered by
  the automatic check that exists precisely to keep the upload from being rejected (the CHANGELOG
  0.7.1 entry: "claude.ai's upload also rejects skill descriptions with anything that looks like
  a tag... A test keeps descriptions plain").
- **Observed:** none of these four fields currently contain tag-like text (checked by hand — this
  is a coverage gap, not a live violation), but a future edit to any of them (e.g. copying an
  example like `<idea>` into `marketplace.json`'s description, which is exactly the kind of typo
  the 0.7.1 CHANGELOG entry says already happened once in a SKILL.md) would pass
  `python3 -m unittest discover -s tests` and `claude plugin validate . --strict` (confirmed:
  both pass today) and only fail at claude.ai's own upload/scan time.
- **Evidence:** `tests/test_paths.py` source (`ROOT.glob("skills/*/SKILL.md")`,
  `ROOT.glob("agents/*.md")` only); `grep -rn "description" tests/*.py` shows no other hit;
  `claude plugin validate . --strict` output ("Validation passed", names only
  `marketplace.json`, i.e. it doesn't scan for tag-like text either).
- **Where:** `tests/test_paths.py:22-27`.
- **Class:** consistency (the packaging gate and the actual upload validator disagree on what
  they check).
- **Should have been caught by:** dimensions.md's `packaging` automatic check ("version ↔
  CHANGELOG check" / manifest validation) — it validates JSON syntax and the version/CHANGELOG
  pair but not this).
- **Proposed fix:** extend `test_descriptions_have_no_tags` to also read
  `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` (both `description` fields) and
  `workflows/*.js`'s `meta.description`.

### PKG-3 · `scripts/test-template.sh` corrupts itself when run twice on one machine — the exact concurrency the bug-bash procedure asks for (P2)
- **Persona / context:** contributor / bug-bash packaging lens following this repo's own
  instructions ("Run at most two template runs concurrently... one api+web run takes about
  2m40s"), sha 19b332e, two clones of the same checkout, both on the container's single
  filesystem and single `pnpm` global store.
- **Steps:**
  1. `cd $SCRATCH/keelokit && bash scripts/test-template.sh '["api","web","mobile","site"]'
     --postgis` in the background.
  2. At the same time, generate a second project from `gh:leosimini/keelokit` at `v0.7.1` and run
     `pnpm install && pnpm -r --if-present e2e:install` in it (the "newcomer" journey, run
     concurrently as the packaging lens's own instructions permit — two template-ish runs on one
     host).
  3. Both jobs reach their `playwright install --with-deps --only-shell chromium` step at close
     to the same time.
- **Expected:** either both installs succeed (the docs say two concurrent template runs are
  supported: distinct `E2E_*` ports are the only stated precaution), or a clear, actionable
  failure ("another install/apt-get is running, retry").
- **Observed:** the first job's `apps/mobile` `e2e:install` failed with
  `E: Could not get lock /var/lib/apt/lists/lock. It is held by process 2664 (apt-get)` (the
  second job's own `playwright install --with-deps` holding the system-wide apt lock at the same
  moment); the same job's very next workspace, `apps/web`, then crashed — not with an apt error,
  but with `Error: Cannot find module './utilsBundle'` inside
  `node_modules/.pnpm/playwright-core@1.63.0/.../coreBundle.js`, aborting the whole
  `test-template.sh` run (exit code from `pnpm -r ... e2e:install`, propagated by `set -euo
  pipefail`). Re-running the identical `'["api","web","mobile","site"]' --postgis` command alone
  (no concurrent job) went past `e2e:install` cleanly and reached the unit-test stage
  ("harness healthy", all workspace unit tests passing) with no apt or module errors — isolating
  the cause to the concurrent run, not the app mix or PostGIS.
- **Evidence:** `$SCRATCH/logs/allapps-postgis.log` (failing, concurrent run) vs
  `$SCRATCH/logs/allapps-postgis-retry.log` (same command, solo, clean past the same step); the
  apt lock message names a live concurrent `apt-get` PID at the moment of failure.
- **Where:** `scripts/test-template.sh` (`pnpm -r --workspace-concurrency=1 --if-present
  e2e:install`, which shells into `playwright install --with-deps`, i.e. `apt-get`, and into the
  shared global `pnpm` store) — this is CI-invisible because `.github/workflows/ci.yml`'s
  `template` job runs each matrix row on its own isolated runner, so two rows never share a
  filesystem or apt lock.
- **Root cause (probable):** `playwright install --with-deps` calls system `apt-get`, which takes
  a single machine-wide lock; a second concurrent caller either fails outright (mobile's case) or
  — worse — gets far enough to race the first on the shared pnpm content-addressable store,
  corrupting the just-extracted `playwright-core` package for a sibling workspace in the *other*
  process (web's case). Nothing in `test-template.sh` serializes or locks around this, and the
  failure it produces (`Cannot find module './utilsBundle'`) gives no hint that the real cause
  was a concurrent installer, not a broken template.
- **Class:** isolation (two independent runs are not actually independent).
- **Should have been caught by:** the `packaging` dimension's own instructions for running this
  lens locally, which explicitly recommend two concurrent `test-template.sh`-shaped runs and only
  warn about port collisions — not about this.
- **Proposed fix:** either serialize the OS-level `playwright install --with-deps` step across
  concurrent `test-template.sh` invocations on one host (a flock on a fixed path), or drop
  `--with-deps` and install the OS packages once outside the loop, or at minimum catch this
  failure mode and re-run once with a clearer message. Until then, the bug-bash instructions
  should say two concurrent runs are unsafe when both reach `e2e:install` at the same time.

### PKG-101 · release.yml's CHANGELOG-entry check accepts a tag whose own version has no entry, if a longer version number that starts with the same digits does (P1)
- **Persona / context:** Maintainer (Leo) cutting a release of a generated product, or any user of
  a Keelokit-generated project running `/keelokit:ship-release`; round-3 packaging lens, HEAD
  `19b332e`, apps combo `["api","web"]` (same job is byte-identical across every combo rendered —
  see Covered).
- **Steps:**
  1. Render the template at HEAD: `uvx copier==9.18.2 copy --vcs-ref HEAD --defaults --data
     project_name=X --data apps='["api","web"]' <clone> out/apiweb` and open
     `out/apiweb/.github/workflows/release.yml`.
  2. Its `check` job's only gate (comment: "Tag on main, with release notes") is:
     `version="${GITHUB_REF_NAME#v}"; ... grep -q "^## $version" CHANGELOG.md || { echo
     "::error::CHANGELOG.md has no '## $version' entry"; exit 1; }` (`release.yml.jinja:24-29`).
  3. Replayed that exact shell logic against a CHANGELOG written in the format
     `skills/ship-release/SKILL.md` (step 3) tells the agent to use (`## 1.3.0 — 2026-10-14`):
     with a file containing only `## 0.7.10 — 2026-10-14` (no `## 0.7.1` entry at all) and tagging
     `v0.7.1`:
     ```
     version="0.7.1"
     grep -q "^## $version" CHANGELOG.md && echo MATCHED || echo "no match"
     ```
     prints `MATCHED`.
- **Expected:** REL-1 / INV-001 / the job's own name ("Tag on main, with release notes") — the tag
  `v0.7.1` must be rejected unless `CHANGELOG.md` has *its own* `## 0.7.1` entry; a `## 0.7.10`
  entry is not that. This repo's own equivalent gate gets this right: the fast-gate verify command
  in `AGENTS.md` uses `f"\n## {v} — "` (an exact version immediately followed by the em-dash
  separator), which does not have this problem — confirmed the same test data does **not**
  spuriously match that pattern.
- **Observed:** `grep -q "^## $version"` is a prefix match with no right-hand boundary, so any
  `CHANGELOG.md` entry whose version starts with the tag's version string (`0.7.1` is a prefix of
  `0.7.10`, `0.7.100`, `0.7.1-rc.1`, etc.) satisfies the check. A tag `v0.7.1` pushed when the
  CHANGELOG's newest (or only) entry is actually `## 0.7.10 — …` — e.g. a version bumped in the
  wrong entry, or two people racing a release — passes `check` and `deploy-production` proceeds
  to wait for approval and deploy, even though `v0.7.1` has no release notes of its own. The
  inverse direction (tagging the longer version when only the shorter one's entry exists) is
  correctly rejected — confirmed with the same harness — so this is specifically a one-way false
  pass, not a total absence of checking.
- **Evidence:** command + output above (`MATCHED`), run against
  `/tmp/CHANGELOG_test.md`; control run with a real gap (`## Unreleased` + `## 0.7.0`, tagging
  `v0.7.1`) correctly printed "no match"; `out/*/.github/workflows/release.yml` for all nine
  rendered combos (`api`, `web`, `mobile`, `site`, `apiweb`, `apimobile`, `apisite`, `all`,
  `all_postgis`) contain the byte-identical `check` job, confirmed with `diff`.
- **Where:** `template/.github/workflows/release.yml.jinja:29` (also present verbatim in every
  rendered `out/*/.github/workflows/release.yml`).
- **Root cause (probable):** `grep -q "^## $version"` anchors only the left edge of the match; it
  needs the right edge anchored too (end of the version token) to avoid matching a longer version
  string that happens to start with the same digits — the same problem the plugin's own
  `f"\n## {v} — "` check already solves by requiring the em-dash separator right after `{v}`, a
  fix this workflow does not reuse.
- **Class:** consistency (INV-001: "a release tag vX.Y.Z points at a commit of main whose
  CHANGELOG has *its* entry" — a tag can pass this gate while pointing at a CHANGELOG whose actual
  matching entry is absent).
- **Should have been caught by:** dimensions.md's `packaging` automatic check ("version ↔
  CHANGELOG check") — but that check (this repo's `AGENTS.md` Verify command) is written once for
  Keelokit's own CHANGELOG and was never asked to also validate the *template's* copy of the same
  logic that every generated product ships and relies on.
- **Proposed fix:** anchor the right edge too, e.g. `grep -qE "^## ${version}( |$)"` or reuse the
  em-dash-anchored form the plugin's own verify command already uses
  (`grep -q "^## ${version} — "`), matching the exact format `skills/ship-release/SKILL.md`
  instructs the agent to write.

## Covered

- Archive contents: `git archive --format=zip HEAD` (267 tracked paths, none unsafe) and a
  `zip -r` of a clean working copy including gitignored artifacts (287 paths) — see PKG-1.
- Path safety: every path in the git archive matches `tests/test_paths.py`'s `SAFE` regex;
  spot-checked for `{ } % ' ` and spaces by hand as well (none found).
- Description scan for tag-like text: `plugin.json`, `marketplace.json`, every `skills/*/SKILL.md`
  and `agents/*.md`, and `workflows/check-bugbash-flow.js`'s `meta` — none currently violate the
  rule, but see PKG-2 for the coverage gap.
- What ships: `.keelokit/state.toml` (has the live dashboard artifact URL — already reported as
  SEC-6, not repeated here), `docs/context/*.md` and `.claude/CLAUDE.md` (tracked and intended to
  be public — this is Keelokit's own dogfooded context, not a leak); `.keelokit/out/dashboard.html`
  and `__pycache__` (gitignored, not in `git archive`, but present on disk — see PKG-1).
- Generated projects via `scripts/test-template.sh`: `["mobile"]` (pass), `["site"]` (pass),
  `["api","web","mobile","site"] --postgis` (pass when run alone; corrupted by a concurrent run —
  PKG-3), `--update-from v0.7.1` (pass, no `.rej`, no manual "Upgrading from" steps needed since
  none exist between 0.7.0/0.7.1 and HEAD), `--update-from v0.7.0` (pass, matches CI's own matrix
  row's app mix closely enough — same outcome).
- Newcomer journey against the real, public tag: `uvx copier==9.18.2 copy --vcs-ref v0.7.1
  --defaults ... gh:leosimini/keelokit demo` succeeds against the actual GitHub repo (not a local
  clone), confirming the template at the currently-released tag is fetchable and complete.
- Plugin install/uninstall/reinstall in an isolated `HOME`/`CLAUDE_CONFIG_DIR`:
  `claude plugin marketplace add`, `claude plugin install keelokit@keelokit`, installing twice
  (idempotent, exit 0), `claude plugin uninstall`, uninstalling twice (clean, documented CLI
  error, exit 1 — not a Keelokit bug). `claude plugin validate . --strict` passes.
- Version/tag/CHANGELOG consistency: `plugin.json` (0.7.1), `CHANGELOG.md`'s `## 0.7.1 — ...`
  heading, tag `v0.7.1`, `origin/main` and `origin/release` all resolve to `fca160c` — consistent,
  matches INV-001.
- `scripts/release.sh` end-to-end in a scratch clone with a local bare `origin` (never the real
  remote): confirmed it refuses to run off `main`, refuses with no `## Unreleased` section,
  refuses when local `main` isn't pushed, and — once main was fast-forwarded to include this
  branch's `Unreleased` entry and pushed to the scratch bare origin — correctly bumped the
  version, rewrote the CHANGELOG heading, ran the unit tests and `claude plugin validate
  --strict`, committed `release: 0.7.2`, and pushed `main` then `release` to the scratch origin
  only. It does not create tags itself (that's `.github/workflows/release.yml`, read but not run,
  since it needs GitHub Actions/`gh`).
- `.github/workflows/ci.yml` and `release.yml` read in full and cross-checked against
  `docs/releasing.md` and the baseline; no discrepancy found beyond what's already known (the
  `update from` row still points at v0.7.0, which is expected until the next release per
  `docs/releasing.md` step 6).

### Round 3 (packaging lens, gap-fill)

- Rendered `template/.github/workflows/ci.yml.jinja` and `release.yml.jinja` at HEAD (`19b332e`)
  via `uvx copier==9.18.2 copy --vcs-ref HEAD --defaults` for nine combinations: `["api"]`,
  `["web"]`, `["mobile"]`, `["site"]`, `["api","web"]`, `["api","mobile"]`, `["api","site"]`,
  `["api","web","mobile","site"]`, and the last with `postgis=true`; plus `["api","web"]` with
  `credit=off` to confirm `credit` never leaks into either workflow (`diff` against the plain
  `["api","web"]` render: identical).
- Parsed every rendered `ci.yml`/`release.yml` with PyYAML and walked every job's `needs:` list,
  confirming each name resolves to a job that exists in that same render (all 9 combos, both
  files) — no dangling `needs`.
- Ran `actionlint` (built from source, `v1.7.12`, with `shellcheck` 0.9.0 installed so its
  embedded shell linting actually runs, confirmed via `-verbose` before/after) against all 18
  rendered files: zero errors or warnings on any combo.
- Confirmed job existence tracks app membership correctly: `integration`/`deploy-staging` exist
  only when `api` is present; `e2e-stack` exists only when `api` is combined with `web` or
  `mobile` (present for `apiweb`, `apimobile`, `all`; absent for `api`-only and `apisite`) and is
  included in `deploy-staging`'s `needs` exactly when it exists (`needs: [integration, build, e2e,
  sast]` for `api`-only vs `needs: [integration, build, e2e, e2e-stack, sast]` once `e2e-stack`
  exists); `postgis=true` only swaps the `postgres:16` service image for `postgis/postgis:16-3.4`
  in `integration`/`e2e-stack`, nothing else differs (`diff` of `all` vs `all_postgis`).
- Replayed `release.yml.jinja`'s `check` job shell logic (`git merge-base --is-ancestor`, the
  `grep -q "^## $version"` CHANGELOG check) against the entry format
  `skills/ship-release/SKILL.md` §3 instructs the agent to write (`## 1.3.0 — 2026-10-14`) — found
  PKG-101; the "no entry at all" baseline case (`## Unreleased` only) correctly fails the check.
- On a freshly `copier`-generated `["api","web"]` project with no intake docs and no git repo
  (simulating "gates still pending, no Story: commits"), ran `python3
  .keelokit/bin/doctor.py --ci` exactly as the `checks` job's step does: it correctly reports
  ERROR and exits 1 (git hooks not installed, `docs/context/*.md` missing) — `INV-006` holds.
  Reproduced the **true** first-CI-push happy path by (a) running plain `pnpm install` (which the
  project's own `prepare` script uses to set `core.hooksPath=.githooks`, confirmed with `git
  config core.hooksPath` before/after) followed by `pnpm install --frozen-lockfile` against the
  lockfile it generated (both succeed, matching the `checks` job's own command), and (b) adding
  the five `docs/context/*.md` placeholder files that `/keelokit:project-new`'s gate 1 (intake)
  writes *before* gate 4 runs `copier copy` (per `skills/project-new/SKILL.md` §§0-4): with both
  in place, `doctor.py --ci` exits 0 ("harness healthy") — so a newcomer who follows the
  documented gate order (intake before skeleton) does get a green first CI push; the only way to
  reproduce a red one is to skip the documented intake step, which is not what the journey asks
  for.
- Confirmed "deploying web and sites from CI" (i.e. no `deploy-staging`/`deploy-production` job
  at all for a `web`-only, `mobile`-only or `site`-only product with no `api`) is a documented,
  intentional gap, not a bug: `docs/design.md` §"Ideas, not promises" lists it explicitly as not
  yet built. Not filed as a finding.

## Not covered

- `--update-from v0.5.0` and other older tags (only v0.7.1 and v0.7.0 were run, per the focus).
- Actually running `.github/workflows/release.yml` (needs GitHub Actions / a real `gh` token);
  only read and cross-checked against `scripts/release.sh`'s behavior.
- The Claude plugin directory's real scan/publish step (`claude.ai/directory/manage`) — no access
  from this environment.
- A from-scratch install of the plugin via the real `leosimini/keelokit` marketplace shorthand
  (network-based `claude plugin marketplace add leosimini/keelokit`, as opposed to a local
  directory) — only the local-directory form was exercised, though the Copier fetch from
  `gh:leosimini/keelokit` (same network path) was confirmed to work.
- A second, isolated repro of the newcomer journey's own `pnpm install`/`playwright install` at
  v0.7.1 in true isolation (my first attempt ran concurrently with the PKG-3 repro and hit the
  same corruption; not re-run standalone for time, but PKG-3's solo retry stands in as the
  isolation evidence for the underlying mechanism).
- `KEELOKIT_TEMPLATE=gh:<fork>/keelokit` (fork) persona — not exercised.
- (Round 3) Actually running the rendered `ci.yml`/`release.yml` on GitHub Actions itself (no
  Actions runner in this environment) — validated by rendering + `actionlint`/`shellcheck` +
  YAML-graph analysis + replaying the shell logic locally instead.
- (Round 3) `--update-from` combined with a mid-way `apps` change (e.g. generate `["web"]`, then
  `copier update` to `["api","web"]`) to see whether `ci.yml`'s API-only jobs appear correctly
  after an upgrade rather than only at first generation — not exercised (time).
- (Round 3) The `mobile`+`site`, `web`+`mobile`, and other non-`api` two-app combinations —
  only `api`-paired combinations and the single-app renders were checked, since `e2e-stack` and
  `deploy-staging` (the only conditionally-rendered jobs) both key off `api`'s presence, which the
  checked combinations already cover both sides of.
- (Round 3) Whether `/keelokit:ship-release`'s free-text CHANGELOG-writing step is itself
  reliable at producing an exact `## X.Y.Z — <date>` heading (vs., e.g., leaving the `##
  Unreleased` heading in place above/below the new entry) — no agent run was replayed, only the
  shell-side consumption of the format the skill documents.
