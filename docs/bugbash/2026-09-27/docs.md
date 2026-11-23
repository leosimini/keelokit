# docs

## Scope covered

Line-by-line pass over `skills/build-story/SKILL.md`, `skills/check-health/SKILL.md`,
`skills/harness-upgrade/SKILL.md`, `skills/ship-setup/SKILL.md`, `skills/ship-release/SKILL.md`,
`skills/project-adopt/SKILL.md`, `skills/plan-intake/SKILL.md` (+ `references/question-bank.md`,
`references/context-format.md`), `skills/plan-backlog/SKILL.md` (+ `template/backlog/README.md`),
`skills/keelokit/SKILL.md`, and `agents/verifier.md`, `agents/reviewer.md`, `agents/breaker.md`,
`agents/context-auditor.md`. Every command, flag, rule id, file path and TOML key each names was
checked against `.keelokit/bin/doctor.py`, `.keelokit/bin/guard.py`,
`skills/project-dashboard/scripts/dashboard.py`, `copier.yml`, `template/package.json.jinja`,
`template/.keelokit/harness/rules.toml`, `references/dimensions.md`, `references/invariants.md`
and the relevant `template/` files (release workflow, playwright configs, `allocate.ts`,
`race.ts`, `authz.matrix.ts`, `state.toml` usage).

Confirmed **consistent** (no finding): the model table (all four roles run `sonnet`, matching
each agent file's front matter); the `Story:` trailer format and `done_story_ids()` /
dashboard's git-log parsing; `doctor --scope`'s messages against `check-health`'s fix table;
every rule id cited by these docs (REL-1, VERIFY-2, ARCH-1, DEP-1, CFG-1, AUTHZ-1, E2E-1, E2E-2,
CONTRACT-1, UI-1, I18N-1, SEC-1/2/3, SAST-1, CRIT-1, MUT-1, COPY-1, TRACE-1, INV-1, ESC-1) exists
in `rules.toml`; `docs/context` file formats in `context-format.md` against `doctor.py`'s regexes
(`GAP_ROW_RE`, `INV_DEF_RE`, `INV_CLASS_RE`, the "blocking" cell match); `backlog/README.md`
against `plan-backlog` and `doctor.py`'s `check_backlog`; `pnpm mutation`/`verify --all`/`doctor`
scripts exist as named; `apps/api/src/testing/race.ts`, `packages/shared/src/allocate.ts`,
`apps/api/src/authz/authz.matrix.ts` exist as the invariants reference describes; the `[run]`
TOML keys (`mode`, `build`, `parallel`) used identically across `project-new`, `build-story`,
`project-adopt` and `project-dashboard`; `E2E_PORT`/`E2E_MOBILE_PORT`/`E2E_API_PORT` are real env
vars read by the template's playwright configs; the Release workflow's tag/CHANGELOG check
matches `ship-release`'s promised gate and example entry format.

**Round 3 addendum** (this lens's assigned gap): line-by-line pass over `skills/project-new/SKILL.md`
(its copier command and `--data` keys against `copier.yml`'s questions/validators/defaults, the
`v<version>` lookup, its gate table against `doctor.py`'s `GATES['project']` and
`.keelokit/state.toml`'s `[gates]` key, and the `pnpm install` → `pnpm verify [--all]` →
`pnpm mutation [--all]` sequence against `template/package.json.jinja`, `template/scripts/verify.sh`,
`template/scripts/mutation.sh` and `template/backlog/README.md`), `skills/check-security/SKILL.md`
(its `docs/security/<date>/report.md` format and finding-prefix examples against
`skills/project-dashboard/scripts/dashboard.py`'s `reports()`/`md_section()`/`findings_section()`
and `references/dimensions.md`), and `skills/project-dashboard/SKILL.md` (its flags, output path,
Artifact-publish steps, anchor ids and lang precedence against `dashboard.py`'s `main()`/
`normalise_lang()`, and its "Keelokit credit" section against `copier.yml`'s `credit` question and
the templates that render it). Verified live with real `copier==9.18.2 copy`/`update` runs in
`$SCRATCH/docs-lens/{proj1,proj2,proj3,proj4}` (clone at 19b332e) and a hand-built
`docs/security/<date>/report.md` fixture run through `dashboard.py --json`.

Confirmed **consistent** in this round (no finding): `project-new`'s gate table (`intake → product
→ stack → skeleton → backlog`) matches `doctor.py`'s `GATES["project"]` exactly; `doctor.py` only
ever reads `.keelokit/state.toml`'s `[gates]` table, matching every skill's usage; `pnpm verify
--all` and `pnpm mutation --all` are real, working flag-forwarding invocations of
`scripts/verify.sh`/`scripts/mutation.sh` (confirmed by reading the scripts, not just the docs);
the `apps` `--data` JSON-array shape `project-new` documents matches what `copier.yml`'s
multiselect actually accepts and what `scripts/test-template.sh` itself uses; `check-security`'s
findings-table column order (`id · area · severity · title · status · fix commit · check added`)
matches `dashboard.py`'s `reports()` cell mapping exactly; its cited rule ids (SEC-1..3, SAST-1,
AUTHZ-1, CFG-1, DEP-1) all exist in `rules.toml` (round 2 already confirmed this); `project-dashboard`'s
documented CLI (`--root`, `--lang`, `--out`, `--standalone`, `--json`), default output path
(`.keelokit/out/dashboard.html`, `.gitignore`d on demand) and `--json`'s promised fields all match
`dashboard.py`'s `argparse` setup and `main()`; `normalise_lang()` really does accept `es-AR`/
`Español`/etc. as documented.

## Findings

### DOC-101 · `doctor.py`'s git-hook enforcer accepts a hook that does nothing, so `project-adopt`'s "propose a hook calling guard.py" can't be verified (P1)
- **Persona / context:** Developer with an existing repo running `/keelokit:project-adopt`, sha 19b332e.
- **Steps:**
  1. Read `skills/project-adopt/SKILL.md:110`: "Also propose (don't impose): calling
     `python3 .keelokit/bin/guard.py git-pre-commit` from the repo's pre-commit hook, and a
     `doctor` step in CI."
  2. Read `.keelokit/bin/doctor.py:149-154`, the `git-hook` branch of `enforcer_problem()`:
     ```python
     if kind == "git-hook":
         hooks_dir = git("config", "core.hooksPath").strip() or ".git/hooks"
         for d in (hooks_dir, ".husky"):
             if (ROOT / d / target).exists():
                 return None
         return f"git hook '{target}' is not installed (hooksPath: {hooks_dir}; run pnpm install)"
     ```
     It only checks that a file named `target` (e.g. `pre-commit`) *exists* at the hooks path —
     it never reads the file's contents.
  3. Reproduced in a scratch fixture: created `.git/hooks/pre-commit` containing only `exit 0`
     (never calls `guard.py`, blocks nothing), and a `.keelokit/harness/rules.toml` with one
     `MUST` rule (`TEST-1`) whose only `enforced_by` is `git-hook:pre-commit`. Ran the real
     `doctor.py` copied into the fixture (`$SCRATCH/docs-lens/fixture1`, `python3
     .keelokit/bin/doctor.py`).
- **Expected:** `project-adopt` (and, by the same enforcer, any project's `SEC-1`/`SEC-2`/`QA-4`
  house rules mapped to `git-hook:pre-commit`) should be unenforced — and doctor should say so —
  until the hook actually runs `guard.py`. Source: `skills/project-adopt/SKILL.md:110-113` ("The
  mapped check must enforce the rule **as written**"), `doctor.py`'s own module docstring
  ("each enforcer looks alive … unless an approved exception is active").
- **Observed:** Doctor reports **no error and no warning at all** for `TEST-1`, and prints
  `✔ harness healthy` for the rest of the fixture — the no-op hook is treated as a fully alive
  enforcer of a `MUST` rule.
- **Evidence:**
  ```
  $ python3 .keelokit/bin/doctor.py
  Keelokit doctor
    Gates: intake → product → stack → skeleton → backlog
    Rules: 1 · Context gaps: 0 (0 blocking)
    Invariants: 0 · Critical areas: 0 · Escapes logged: 0
    Backlog: 0/0 done
    ERROR docs/context missing product.md, domain.md, constraints.md, environments.md, gaps.md — run the intake (/keelokit:plan-intake)
  ```
  (the only ERROR is the unrelated missing `docs/context`; `TEST-1` never appears, confirming the
  no-op hook fully satisfies it). `.git/hooks/pre-commit` in the fixture is `#!/bin/sh\nexit 0\n`.
- **Where:** `.keelokit/bin/doctor.py:149-154` (same code in `template/.keelokit/bin/doctor.py`);
  `skills/project-adopt/SKILL.md:110-113`.
- **Root cause (probable):** unlike every other `enforcer_problem()` branch (`ci` checks for real
  steps and no `continue-on-error`; `lint` checks the rule is actually turned on; `test` requires
  an active test citing the rule id; `script`/`file` can require a needle string), the `git-hook`
  branch checks existence only, with no equivalent content check.
- **Class:** consistency
- **Should have been caught by:** the `docs` dimension's own bar ("every command, option and
  file the docs mention exists **and behaves as written**") — nothing tests that a `git-hook`
  enforcer actually enforces anything.
- **Proposed fix:** either (a) have `enforcer_problem()`'s `git-hook` branch also require the
  hook file to reference `guard.py` (mirroring the `claude-hook` and `test` branches' content
  checks), or (b) if that's intentionally left to human review, say so explicitly in
  `project-adopt`'s step 4.1 ("the mapped check must enforce the rule as written") so an adopter
  knows doctor cannot verify a `git-hook` mapping's substance — only its presence.

### DOC-102 · `harness-upgrade`'s ownership summary omits two files `copier.yml` actually protects (P2)
- **Persona / context:** Upgrader from 0.7.1/0.7.0 running `/keelokit:harness-upgrade`, sha 19b332e.
- **Steps:**
  1. Read `skills/harness-upgrade/SKILL.md:13-16`: "The template owns infrastructure (CI,
     lint/format/ts base configs, `scripts/verify.sh`, git hooks, `.keelokit/` **except the
     project's local rules and exceptions**). The product owns its code…" — naming only
     `.keelokit/rules.local.toml` and `.keelokit/exceptions.toml` as the exceptions inside
     `.keelokit/`.
  2. Read `copier.yml`'s `_skip_if_exists` list (product-owned, never re-rendered by `copier
     update`), lines 14-19:
     ```yaml
     - .keelokit/rules.local.toml
     - .keelokit/exceptions.toml
     - .keelokit/critical.toml
     - .keelokit/profile.toml
     ```
- **Expected:** The skill's one-sentence ownership summary for `.keelokit/` should match
  `copier.yml`, the actual source of truth for what `copier update` will or won't rewrite (this
  is exactly the file `check-health`/`project-adopt` point to as canonical, and what INV-003
  governs).
- **Observed:** `.keelokit/critical.toml` (critical areas) and `.keelokit/profile.toml`
  (kind/traits) are also `_skip_if_exists` — product-owned, never rewritten by `copier update` —
  but the skill's summary implies only `rules.local.toml` and `exceptions.toml` are carved out
  and everything else under `.keelokit/` is the template's to manage.
- **Evidence:** `skills/harness-upgrade/SKILL.md:13-16` vs `copier.yml:14-19` (quoted above,
  read directly from the repository at HEAD 19b332e).
- **Where:** `skills/harness-upgrade/SKILL.md:14`.
- **Root cause (probable):** the ownership sentence was written before `profile.toml` (0.7.0)
  and/or `critical.toml` were added to `_skip_if_exists`, and wasn't updated when they were.
- **Class:** consistency
- **Should have been caught by:** the `docs` dimension's bar that "every … file the docs mention
  exists and behaves as written" — here the docs under-mention files that do exist and do behave
  specially.
- **Proposed fix:** update the sentence to "`.keelokit/` except the project's local rules,
  exceptions, critical areas and profile (`rules.local.toml`, `exceptions.toml`,
  `critical.toml`, `profile.toml`)" — or simply say "the files `_skip_if_exists` in `copier.yml`
  lists" so the two never drift again.

### DOC-201 · `project-dashboard`'s "Keelokit credit" instructions describe a setting that copier never writes, silently ignores, and can crash `copier update` on (P1)
- **Persona / context:** Newcomer founder who picked "Off" for credit from the dashboard footer,
  or any project owner following `skills/project-dashboard/SKILL.md`'s "Keelokit credit" section
  to change the level, sha 19b332e. Also blocks the Upgrader journey on the next
  `/keelokit:harness-upgrade`.
- **Steps:**
  1. Read `skills/project-dashboard/SKILL.md`'s "Keelokit credit" section: "Projects are signed
     'Built with Keelokit' by default (`credit` in `.keelokit/answers.yml`: `visible` …; `quiet`
     …; `off`) … To change it: set `credit` in `.keelokit/answers.yml`, then add or remove the
     blocks … Commit `chore: Keelokit credit → <level>`."
  2. Generated a project at HEAD 19b332e in a scratch clone, explicitly passing the level at
     creation time as `project-new`'s own step 4 command shape would (`uvx copier==9.18.2 copy
     --defaults --vcs-ref HEAD --data project_name=Demo2 --data project_slug=demo2 --data
     description=x --data 'apps=["api"]' --data postgis=false --data credit=quiet <clone>
     $SCRATCH/proj2`).
  3. `cat $SCRATCH/proj2/.keelokit/answers.yml` — no `credit:` line at all, and `README.md` shows
     the **visible** badge, not quiet: the `--data credit=quiet` override was silently discarded
     (`copier.yml`'s `credit` question has `when: false`, so copier never asks it, never records
     it, and never honours a passed-in value — only its hardcoded `default: visible` is ever
     used).
  4. Followed the SKILL's own "to change it" instructions literally: `git init`, then by hand
     appended `credit: quiet` to `.keelokit/answers.yml`, committed, and ran `copier update -a
     .keelokit/answers.yml --vcs-ref HEAD --defaults --conflict rej`. Result: `Keeping template
     version …` (succeeds), but `cat .keelokit/answers.yml` afterwards shows the `credit: quiet`
     line **gone again** — `copier update` strips it right back out on every run, since the
     question is still `when: false`.
  5. Repeated step 4 but hand-wrote the third documented level instead: `credit: off` (exactly as
     `copier.yml`'s own choices list spells it: `"Off": "off"`), committed, and ran the same
     `copier update`. This time it did not succeed quietly — it crashed with a raw, unhandled
     Python traceback (captured in full).
- **Expected:** Per the SKILL's own words, `credit` should be a value that lives in
  `.keelokit/answers.yml`, that setting there changes the credit level, and that `copier update`
  — the exact command `harness-upgrade` runs on every future upgrade — keeps working afterwards.
- **Observed:** None of that holds. (a) `credit` is never written to `.keelokit/answers.yml` by
  `copier copy`, with or without `--data credit=…`, because the question is `when: false` in
  `copier.yml` (it is always silently resolved to its hardcoded default, "visible", full stop).
  (b) Hand-adding `credit: quiet` per the SKILL's instructions is silently undone by the very
  next `copier update` (it never reaches the answers file). (c) Hand-adding `credit: off` — one
  of only three levels this same SKILL section documents — is **not** silently ignored: YAML
  parses the bare word `off` as the boolean `False` (the classic YAML 1.1 "off/on/yes/no" trap),
  and copier's own `when: false` default-resolution path then tries to validate `str(False)`
  against `['visible', 'quiet', 'off']` and raises an unhandled `ValueError`, so `copier update`
  dies with a full Python traceback instead of updating the project — reproduced twice
  independently, in a project with `apps=["api"]` and one with `apps=["web"]`, both clean at
  19b332e.
- **Evidence:**
  ```
  $ cat $SCRATCH/proj2/.keelokit/answers.yml       # generated with --data credit=quiet
  ... (no `credit:` key at all) ...
  $ sed -n '1,6p' $SCRATCH/proj2/README.md
  <!-- keelokit:credit -->
  [![Built with Keelokit](docs/assets/built-with-keelokit.svg)](https://keelokit.com/?ref=built-with)
  <!-- /keelokit:credit -->    # visible badge despite --data credit=quiet

  $ echo 'credit: off' >> .keelokit/answers.yml && git commit -am x
  $ uvx copier==9.18.2 update -a .keelokit/answers.yml --vcs-ref HEAD --defaults --conflict rej
  Keeping template version 0.7.1.post2.dev0+19b332e
  Traceback (most recent call last):
    ...
    File ".../copier/_main.py", line 641, in _ask
      if question.get_default() is MISSING:
    File ".../copier/_user_data.py", line 288, in get_default
      result = self.parse_answer(result)
    File ".../copier/_user_data.py", line 532, in _parse_answer
      raise ValueError(f"Invalid choice for '{self.var_name}': {error_detail}")
  ValueError: Invalid choice for 'credit': 'False' is not in ['visible', 'quiet', 'off']
  ```
  Confirmed the crash is specific to the hand-added `credit: off` line, not a pre-existing
  problem: an unmodified `apps=["web"]` project (`$SCRATCH/proj4`) ran the identical
  `copier update` cleanly (`Keeping template version …`, no traceback), and the same project with
  `credit: quiet` hand-added also updated cleanly (silently dropping the key) — only `credit: off`
  crashes, because of the YAML boolean coercion.
- **Where:** `skills/project-dashboard/SKILL.md` ("## Keelokit credit" section); `copier.yml:104`
  (`credit:` question, `when: false`); `.keelokit/answers.yml`'s own header comment ("Written by
  Copier — never edit by hand. `copier update` reads it to upgrade this project" — directly
  contradicted by the SKILL telling the user to hand-edit exactly this file).
- **Root cause (probable):** `credit`'s `when: false` was presumably meant to keep it out of the
  interactive prompt flow (it says "changed later from the dashboard", not "asked at intake"),
  but `when: false` in copier also means the question's answer is never asked *or persisted* on
  copy or update — it always resolves to the literal `default:` — so the whole "set it in
  `.keelokit/answers.yml`" mechanism the dashboard SKILL documents has no path to ever take
  effect. The crash on `off` is a second, independent bug: nothing quotes or validates a
  hand-typed answers.yml value, so YAML's own type coercion (`off` → `False`) reaches copier's
  choice validator unguarded.
- **Class:** consistency
- **Should have been caught by:** the `docs` dimension's bar that every file and behaviour the
  docs describe "exists and behaves as written" — none of the three credit levels can actually be
  set the way the docs describe, and one crashes the exact command `harness-upgrade` depends on.
- **Proposed fix:** either make `credit` a real, persisted answer (drop `when: false`, or add a
  computed/persisted-only question copier supports) so `--data credit=…` and hand-edits actually
  take effect and survive `copier update`; or, if `.keelokit/answers.yml` is never meant to be
  hand-edited (per its own header), stop telling users to edit it and instead have the "change
  it" flow touch only the rendered blocks/meta tags directly, and store the chosen level
  somewhere `copier update` never revisits (e.g. `.keelokit/state.toml`, which the dashboard
  already owns). Either way, quoting/validating a hand-typed value before it reaches copier would
  turn the crash into a clean error.

### DOC-202 · The "quiet" credit level's defining feature (the invisible generator tag) is also present at "visible" — the docs describe it as what tells the two apart (P3)
- **Persona / context:** Newcomer founder reading `skills/project-dashboard/SKILL.md`'s "Keelokit
  credit" section to decide between "Visible" and "Quiet", sha 19b332e.
- **Steps:**
  1. Read the SKILL: "`visible` — the README badge and a line at the foot of the public site;
     `quiet` — the README badge and a `<meta name="generator" content="Keelokit">` in the web and
     site HTML" — read as two different bundles, the meta tag being `quiet`'s extra ingredient
     the visible level doesn't have (visible instead shows the human-visible footer line).
  2. Read the actual templates: `template/apps/web/index.html.jinja:8-9` and
     `template/apps/site/src/pages/index.astro.jinja:19-20` both gate the
     `<meta name="generator" content="Keelokit">` tag on `{% if credit != 'off' %}` — true for
     **both** `visible` and `quiet`, not `quiet` alone.
  3. Confirmed by generating a project with `apps=["web"]` and the (only reachable, see DOC-201)
     default level `visible`: `grep generator $SCRATCH/proj4/apps/web/index.html` →
     `<meta name="generator" content="Keelokit" />` present despite `credit` never being set to
     `quiet`.
- **Expected:** The SKILL's own framing implies the generator meta tag is what "quiet" adds
  instead of the visible badge/footer — i.e. that a "visible" project's web app has no hidden
  generator tag, only the readable badge/footer.
- **Observed:** A "visible" project's web app (and site) carries the exact same invisible
  `<meta name="generator" content="Keelokit">` tag as "quiet", on top of the visible badge and
  footer — the tag is not something that distinguishes the two levels at all, it's present for
  every level except `off`.
- **Evidence:** `template/apps/web/index.html.jinja:6-9`; `template/apps/site/src/pages/index.astro.jinja:18-20`;
  `$SCRATCH/proj4/apps/web/index.html:7` (generated at default/`visible`, `credit` never
  overridden — see DOC-201 for why it can't be).
- **Where:** `skills/project-dashboard/SKILL.md` ("## Keelokit credit" section).
- **Root cause (probable):** the sentence lists each level's *additional, human-visible* signal
  but was written as if it were an exhaustive description of everything rendered for that level,
  omitting that the machine-readable tag is shared by `visible` and `quiet` alike.
- **Class:** consistency
- **Should have been caught by:** the `docs` dimension's line-for-line diff of a doc's promises
  against the template files that actually render them.
- **Proposed fix:** reword to "`visible` — README badge, a line at the foot of the public site,
  and the generator meta tag; `quiet` — the generator meta tag only (no visible badge or
  footer)" or similar — or, if the intent really was for `visible` to have no hidden tag, fix the
  `{% if credit != 'off' %}` guards in the two templates to gate on `credit == 'quiet'` instead.

### DOC-203 · `check-security`'s report format never says the "Scope" section must be a literal `## Scope` heading, unlike its sibling `check-bugbash`'s workflow prompt — the dashboard's sha extraction for security reports has no such guarantee (P3)
- **Persona / context:** Any user running `/keelokit:check-security` and then opening the
  dashboard's Security section, sha 19b332e.
- **Steps:**
  1. Read `skills/check-security/SKILL.md` §5: "Scope (sha, staging URL), what was checked and
     what couldn't be; the findings table …; `## Pending decisions` … ; the data map's changes." —
     `## Pending decisions` is spelled out with literal heading markup; "Scope" is not (no `##`,
     no code formatting indicating a required heading).
  2. Compared with `check-bugbash`'s equivalent report contract: its own `SKILL.md` §5 is just as
     loose ("Scope (sha), lenses run, …"), but `workflows/check-bugbash-flow.js:337` patches this
     for the automated bugbash flow by hardcoding the requirement in the write-up prompt:
     `"## Scope" first, with the sha …` — a safety net `check-security` has no equivalent of,
     since it has no driving workflow script.
  3. Read `skills/project-dashboard/scripts/dashboard.py`'s `reports()` (used identically for
     `docs/security/*/report.md` and `docs/bugbash/*/report.md`): `"sha": … re.search(r"\b[0-9a-f]{7,40}\b",
     md_section(text, "Scope") or text)` — `md_section` only finds a body under a literal
     `^#{1,6}\s+Scope` heading; when absent, sha extraction silently falls back to scanning the
     *entire* report text for the first 7–40 char hex-looking word.
  4. Built a fixture `docs/security/2026-09-20/report.md` following `check-security`'s literal
     prose (a plain paragraph mentioning the sha, no `## Scope` heading) and ran
     `dashboard.py --root <fixture> --json`; extraction happened to pick the right sha here
     because it was the first hex-like token in the file, but nothing in the SKILL or the parser
     guarantees that ordering for every report an agent might write.
- **Expected:** Since `dashboard.py` parses `docs/security` and `docs/bugbash` reports with the
  exact same `md_section(text, "Scope")` call, and `check-security` has no workflow script to
  enforce the heading the way `check-bugbash-flow.js` does, its own `SKILL.md` should be the one
  place spelling out the literal `## Scope` heading requirement — the same way it does spell out
  `` `## Pending decisions` `` a few lines later.
- **Observed:** `check-security/SKILL.md` never uses the string `"## Scope"` or otherwise says the
  scope information must be its own markdown heading; a compliant write-up could put the sha
  anywhere in prose (or under a differently-worded heading such as "Scope and coverage"), which
  `md_section` would not recognise, falling back to an unscoped whole-document hex search that
  can pick up the wrong token (a fix commit, an unrelated hash) on some future report.
- **Evidence:** `skills/check-security/SKILL.md:73` (no heading markup for "Scope") vs.
  `skills/check-security/SKILL.md:75` (`` `## Pending decisions` `` literally backtick-and-hash
  marked); `workflows/check-bugbash-flow.js:337`; `skills/project-dashboard/scripts/dashboard.py`
  `reports()`/`md_section()`; fixture run at
  `$SCRATCH/docs-lens/fixture-sec/docs/security/2026-09-20/report.md`.
- **Where:** `skills/check-security/SKILL.md:73`.
- **Root cause (probable):** the report-format prose for `check-security` was adapted from
  `check-bugbash/SKILL.md`'s equally loose §5 without carrying over the stricter contract that
  `check-bugbash-flow.js` separately enforces only for the bugbash side.
- **Class:** consistency
- **Should have been caught by:** the `docs` dimension's bar that a doc's promises to a
  machine-parsing consumer (the dashboard) match what the parser actually requires.
- **Proposed fix:** add the same explicit `` `## Scope` `` heading instruction (sha, staging URL,
  what was/wasn't checked) to `check-security/SKILL.md` §5, mirroring `` `## Pending decisions` ``
  right below it.

## Not covered

- Did not execute `scripts/test-template.sh` end to end (`--adopt`, `--update-from v0.7.0`,
  `api+web`) to confirm `harness-upgrade`'s and `project-adopt`'s promised commands against a
  real generated project in this pass (round 2's note) — round 3 did run several real
  `copier copy`/`copier update` cycles by hand (see DOC-201/DOC-202) but not the full
  `test-template.sh` matrix.
- Did not run `/keelokit:check-security` or `/keelokit:project-dashboard` end to end against a
  real, hosted, `personal-data` project to see an actual `docs/security/<date>/report.md` in the
  wild (none exists in this repo or its history); DOC-203's fixture is a hand-built stand-in for
  what an agent following the SKILL literally might write, not a captured real report.
- Did not diff `skills/project-dashboard/references/design.md` (visual/CSS design spec) against
  the rendered HTML/CSS in this pass — out of this round's line-by-line focus (the three skill
  bodies named in the brief).
- Did not independently verify every `references/question-bank.md` row against
  `plan-intake/SKILL.md`'s prose beyond `D03`–`D03d` (round 2's note, unchanged).
- Did not check Spanish-language behaviour of `project-new`, `check-security` or
  `project-dashboard` specifically (routing text, terminology) beyond what their bodies state
  inline (`olas de desarrollo`, the dashboard's `lang` handling in DOC-203's neighbourhood) — a
  full Spanish-locale pass of these three skill bodies was not done.

## Round 4

Picked up the two items this lens's brief called out explicitly and that rounds 1–3 had not yet
closed: the known lead (`docs/releasing.md` step 6 vs `.github/workflows/ci.yml`'s "update from"
row) and `guard.py`'s docstring rule list vs `rules.toml`'s `enforced_by`. Also re-walked the
README "Try it" / "Data and network" commands, `template/AGENTS.md.jinja`'s command table against
`template/package.json.jinja` and `template/scripts/verify.sh`/`mutation.sh`, and
`skills/project-dashboard/references/design.md` against the CSS `dashboard.py` actually emits
(colours, fonts, icon) — the one item rounds 1–3 had explicitly left as not covered.

**Known lead already closed, not a live finding:** `docs/releasing.md` step 6's example ("0.7.1
renamed template files, yet ci.yml still says v0.7.0") described a real problem, but it's already
fixed at this sha: `.github/workflows/ci.yml:73` reads `update from v0.7.1` /
`--update-from v0.7.1`, and `tests/test_release.py`'s `test_DOC_2_update_from_row_names_the_last_
release_that_changed_the_template` (its own docstring names this exact history: "after 0.7.1,
which renamed dozens of template files, main kept upgrading from 0.7.0 (DOC-2)") now guards it in
CI and in `scripts/release.sh`. Confirmed the guard is real, not just the row: `git tag --merged
HEAD --list 'v*'` at this sha lists only `v0.7.0`/`v0.7.1`, and `git diff v0.7.1 -- template
copier.yml` is empty on `main`, so the row correctly names the latest tag that changed the
template. No finding.

**Investigated and ruled out — not a bug:** `CHANGELOG.md`'s "## Unreleased" section carries 14
bullets marked "Already in 0.7.1" (e.g. `CHANGELOG.md:25` for LOG-4, `:56` for CPY-1) next to
fixes described as shipping now. Read in isolation this could be misread as "the fix already
shipped in the v0.7.1 tag" — which git history contradicts: `git log --oneline v0.7.0..v0.7.1`
is only 4 commits (the claude.ai-upload path/description fixes CHANGELOG's own `## 0.7.1` section
names), and diffing `git show v0.7.1:template/.keelokit/bin/guard.py` against HEAD confirms the
LOG-4 git-option-grammar rewrite and CPY-1's `pnpm doctor` → `python3 .keelokit/bin/doctor.py`
wording are HEAD-only; v0.7.1's guard/doctor still have the old, buggy text
(`run \`pnpm doctor\`` is still literally present in `git show v0.7.1:template/.keelokit/bin/
doctor.py`). But every instance reads as "the **bug** already existed in 0.7.1" (not "the fix
shipped in 0.7.1"), consistently followed by "`harness-upgrade` brings the new guard/doctor" —
which is the correct, actionable instruction either way, and matches lines like `:122` ("Already
in 0.7.1; affects new projects only") that have no upgrade-instruction at all and only make sense
as "pre-existing in 0.7.1". No finding: the phrasing is terse but internally consistent across all
14 uses, and this round found no place where it actually misleads the Upgrader journey.

**Everything else checked this round matched:** `guard.py`'s docstring "Rules enforced: SEC-1,
SEC-2, QA-2, QA-4, DB-1, AGENT-1, REL-1" is exactly the set of `rules.toml` ids whose
`enforced_by` lists `claude-hook:guard.py` (confirmed by parsing both the docstring and every
`[[rule]] enforced_by` pair in `template/.keelokit/harness/rules.toml`, no rule id on either side
without a match). `dashboard.py`'s docstring flags (`--root`, `--lang`, `--out`, `--standalone`,
`--json`) match its `argparse` calls one for one. `scripts/test-template.sh`'s header (plain,
`--adopt`, `--update-from`) matches its `case` statement. The `docs/design.md#bugs-come-in-classes`
and `template/.keelokit/harness/stack.md` links README/README.es cite both resolve. README's "Try
it" marketplace/install commands (`claude plugin marketplace add leosimini/keelokit`,
`claude plugin install keelokit@keelokit`) match `marketplace.json`'s `name: keelokit` and
`plugin.json`'s `name: keelokit` (so `keelokit@keelokit` is the right `plugin@marketplace` pair).
`template/AGENTS.md.jinja`'s `pnpm e2e:stack` row is gated by the identical Jinja condition
(`'api' in apps and ('web' in apps or 'mobile' in apps)`) as the script it documents in
`template/package.json.jinja`, so it never appears for a project that wouldn't have the script.
`skills/project-dashboard/references/design.md`'s colour tokens (foam `#F6F1E8`, ink `#172126`,
ink-2 `#4A5552`, line `#E3DCCF`, the sea gradient `#1A64B0 → #114D96 → #0B3574 → #07214E →
#040F28`, board `#FBC82A`, foil `#EE7B24`, reef `#8FE0C4`) and its three named fonts (Cormorant
Garamond, Karla, Fragment Mono) all appear verbatim in `dashboard.py`'s emitted CSS
(`:root{...}` block and the Google Fonts `<link>`).

## Not covered (round 4)

- Did not render `skills/project-dashboard/references/design.md`'s layout claims (1160 px wrap,
  330 px sticky side column, collapsible stage cards) against a real rendered dashboard in a
  browser — only diffed the colour/font tokens against the CSS source text.
- Did not re-run `scripts/test-template.sh` end to end this round (rounds 2–3's gap); still
  relying on the harness's own recorded baseline run for `'["api","web"]'` and `--adopt`.
- Did not check whether any of the other 12 "Already in 0.7.1" CHANGELOG bullets (beyond LOG-4
  and CPY-1, spot-checked above) describe a fix that is itself inaccurate about what changed —
  only checked that the "Already in 0.7.1" framing itself is consistent, not each bullet's
  technical claim against the diff.
