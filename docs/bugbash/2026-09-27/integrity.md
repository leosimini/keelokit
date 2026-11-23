# integrity

### INT-1 · `checks` job's default `actions/checkout` makes `doctor.py`/`dashboard.py` count a PR's own unmerged `Story:` trailers as done, defeating INV-005 in the run that matters most (P1)
- **Persona / context:** Developer or agent following the "Story and bug bash loop" journey in any generated/adopted project; the `pull_request` trigger of the generated `.github/workflows/ci.yml`'s `checks` job (`python3 .keelokit/bin/doctor.py --ci`), which is the job that is supposed to gate the PR before merge. HEAD 19b332e, also present at v0.7.1 (fca160c) — pre-existing, not introduced by this branch.
- **Steps:**
  1. `main_ref()` (`.keelokit/bin/doctor.py:114-118`, identical in `skills/project-dashboard/scripts/dashboard.py:621-625` and in `template/.keelokit/bin/doctor.py`) tries `origin/main`, then `main`, and **falls back to `HEAD`** if neither ref exists.
  2. `template/.github/workflows/ci.yml.jinja`'s `checks` job (lines 33-39) checks out with a bare `actions/checkout@v4` — no `fetch-depth: 0`, no explicit ref. Contrast with the `secrets` job three lines above it (line 26-28), which does set `fetch-depth: 0`, and with the mutation job at line ~180 which sets it too "to find the critical files a pull request changes" — i.e. the workflow's author already knows some jobs need full history and `origin/main`, but the `checks` job (the one that calls doctor) was missed.
  3. For a `pull_request` event, GitHub's default `actions/checkout@v4` behaviour (shallow, single ref, detached `HEAD`) leaves neither a local `main` branch nor an `origin/main` remote-tracking ref in the workspace — reproduced locally below with a plain `git fetch --depth=1` of just the PR-tip SHA into a fresh repo.
  4. A commit that exists **only on the PR branch** (not yet merged to `main`) and carries a `Story: <ID>` trailer is then treated as "on main" by `done_story_ids()` (`doctor.py:383-386`) / the dashboard's equivalent, because `main_ref()` silently resolved to `HEAD` (the PR's own tip) instead of failing loudly or refusing to guess.
- **Expected:** Per `AGENTS.md`/`docs/context/domain.md`, INV-005 [MUST]: "A story is done if and only if a commit reachable from `main` carries its `Story:` trailer" — class consistency. A commit that is only reachable from the PR's own branch must **not** count, especially not during that very PR's own CI run.
- **Observed:** Reproduced exactly the shallow/detached-HEAD checkout GitHub Actions produces for a PR, then ran the same `main_ref()`/`done_story_ids()` logic against it:
  ```
  $ git init -q --bare remote.git && git clone -q remote.git work1 && cd work1
  $ git commit -qm init && git push -q origin main
  $ git checkout -qb pr-branch
  $ git commit -qam "$(printf 'feat: unmerged story\n\nStory: PR-ONLY-1\n')"
  $ git push -q origin pr-branch   # PR_SHA=859837c
  $ cd .. && mkdir ci_checkout && cd ci_checkout && git init -q
  $ git remote add origin ../remote.git
  $ git fetch -q --depth=1 origin 859837c26d8b5a84152e011d38cabf8465b18437
  $ git checkout -q FETCH_HEAD          # exactly what actions/checkout does for a PR, minus fetch-depth:0
  $ git rev-parse --verify --quiet main;        echo $?   # 1 (doesn't exist)
  $ git rev-parse --verify --quiet origin/main; echo $?   # 1 (doesn't exist)
  $ python3 -c "
  import subprocess
  def git(*a): 
      o = subprocess.run(['git', *a], capture_output=True, text=True); return o.stdout if o.returncode==0 else ''
  def main_ref():
      for ref in ('origin/main','main'):
          if git('rev-parse','--verify','--quiet',ref).strip(): return ref
      return 'HEAD'
  ref = main_ref(); print('main_ref():', ref)
  t = git('log', ref, '--format=%(trailers:key=Story,valueonly,separator=%x2C)')
  print('done_story_ids():', {s.strip() for l in t.splitlines() for s in l.split(',') if s.strip()})
  "
  main_ref(): HEAD
  done_story_ids(): {'PR-ONLY-1'}
  ```
  `PR-ONLY-1` is reported "done" although it lives only on the not-yet-merged branch.
- **Evidence:** Full transcript above (session scratch dir `inv005/shallow_pr/`); `template/.github/workflows/ci.yml.jinja:26-28` (secrets job, sets `fetch-depth: 0`) vs `:33-39` (checks job, doesn't); same file at v0.7.1 tag confirmed identical (`git show v0.7.1:template/.github/workflows/ci.yml.jinja`).
- **Where:** `.keelokit/bin/doctor.py:114-118` and `:383-386`; `skills/project-dashboard/scripts/dashboard.py:621-625`; `template/.github/workflows/ci.yml.jinja:33-39` (all three identical in `template/.keelokit/bin/doctor.py`).
- **Root cause (probable):** `main_ref()`'s silent `return "HEAD"` fallback assumes HEAD is a reasonable stand-in for "main" when neither ref is resolvable; that assumption is false in the one place doctor actually runs unattended in CI on a `pull_request` event, because that job's checkout doesn't fetch `origin/main`.
- **Class:** consistency — INV-005
- **Should have been caught by:** a transition/consistency test per `references/invariants.md`'s INV-005 row, specifically one that runs `doctor.py`/`dashboard.py` against a fixture shaped like a real shallow `pull_request` checkout (no local `main`, no `origin/main`, detached `HEAD` with a trailer of its own) — `tests/test_doctor.py` and `tests/test_dashboard.py` were not checked in depth here but the fixtures this bash built (`main missing`, `origin/main present`, `detached HEAD`) are exactly the invariant's specified attack surface and none of them exercise "neither ref exists, at all."
- **Proposed fix:** either (a) add `fetch-depth: 0` to the `checks` job's checkout (consistent with the `secrets` and mutation jobs, which already need it for the same reason), or (b) make `main_ref()` fail loudly (raise / `errors.append` a real ERROR, don't silently use `HEAD`) when neither `origin/main` nor `main` resolves, since a wrong guess here silences the exact safety checks (`check_backlog`'s "touches critical area … declare integrity" and wave/overlap checks in `doctor.py:454-455`) that gate a critical-area PR before merge. Doing both is safer: the checkout fix removes the everyday trigger, the loud-failure fix stops any future job from repeating the mistake.

### INT-2 · `doctor.py`'s `gate_state()` is the one TOML loader in the file with no `TOMLDecodeError` handling — a malformed `.keelokit/state.toml` crashes every mode, including `--brief` (P2)
- **Persona / context:** Daily agent session journey; SessionStart hook runs `doctor.py --brief`. `.keelokit/state.toml` is hand/agent-edited routinely (`project-adopt`'s SKILL.md: "Record each approval in `.keelokit/state.toml` under `[gates]`"), so a bad edit or an unresolved merge-conflict marker left in it is plausible. HEAD 19b332e, also present at v0.7.1 (`template/.keelokit/bin/doctor.py` identical) — pre-existing.
- **Steps:** Built a fixture by copying this repo's own `.keelokit/` (so `ROOT` resolves inside the fixture, per the run-in-isolation note) and corrupting `.keelokit/state.toml`:
  ```
  [gates
  this is not valid toml
  ```
  then ran `python3 .keelokit/bin/doctor.py --brief` and `python3 .keelokit/bin/doctor.py --ci` from the fixture root.
- **Expected:** Same treatment as every other malformed-TOML case doctor.py already handles cleanly: `load_rules`/`check_exceptions` (rules.local.toml), `load_profile` (profile.toml) and `load_critical` (critical.toml) each wrap their `tomllib.loads` in `try/except tomllib.TOMLDecodeError` and turn it into a normal `errors.append(...)` line. `--brief` in particular is documented (doctor.py's own module docstring: "where am I / what's next (SessionStart hook)") to be the harmless, always-succeeds summary the SessionStart hook calls on every session start.
- **Observed:** Both modes raise an unhandled `tomllib.TOMLDecodeError` and print a full Python traceback instead of any doctor output — no gates line, no context-gap count, no backlog line, no `Harness errors: N` summary. `--brief` exits 1 (not 0), and `--ci` also exits 1, but via a Python traceback rather than through the `errors` list:
  ```
  $ python3 .keelokit/bin/doctor.py --brief
  Traceback (most recent call last):
    File ".../doctor.py", line 604, in <module>
      sys.exit(main())
    File ".../doctor.py", line 565, in main
      gates = gate_state()
    File ".../doctor.py", line 494, in gate_state
      return tomllib.loads(path.read_text()).get("gates", {}) if path.exists() else {}
  tomllib.TOMLDecodeError: Expected ']' at the end of a table declaration (at line 1, column 7)
  exit brief=1
  ```
  (identical traceback and same exit code for `--ci`). Note the `SessionStart` hook's shell wrapper (`hooks/hooks.json`: `python3 "$f" --brief; exit 0`) always exits 0 regardless, so the session itself is not blocked — but the human/agent sees a raw traceback instead of the "gate pending / context gaps / backlog" status the hook exists to show, on every single prompt until the file is fixed.
- **Evidence:** Command + full output above; fixture at session scratch dir `inv006/fixture/`; confirmed identical code at `git show v0.7.1:template/.keelokit/bin/doctor.py` (function body byte-identical).
- **Where:** `.keelokit/bin/doctor.py:492-494` (`gate_state`), identical in `template/.keelokit/bin/doctor.py`. Contrast with `skills/project-dashboard/scripts/dashboard.py:629-632` and `:1913-1916`, which read the very same `.keelokit/state.toml` file **and do** wrap both reads in `try/except tomllib.TOMLDecodeError`.
- **Root cause (probable):** `gate_state()` was written without the same defensive wrapping every sibling loader in the file has; the dashboard script (which reads the identical file) got it right, so this is an omission specific to `doctor.py`, not a harder problem.
- **Class:** consistency — related to INV-006 ("`doctor --ci` exits non-zero whenever it reports an error": here it exits non-zero, but via an unreported crash rather than a clean `ERROR` line, so the letter of INV-006 holds by accident while its spirit — a legible, actionable report — does not).
- **Should have been caught by:** a unit test in `tests/test_doctor.py` feeding a syntactically-invalid `.keelokit/state.toml` to `gate_state()`/`main()`, parallel to whatever coverage exists for the other TOML files (this bash didn't find one for `state.toml` specifically; `find` over `tests/` for `state.toml` fixtures came back empty).
- **Proposed fix:** wrap `gate_state()`'s body the same way `load_profile`/`load_critical` do: `try: ... except tomllib.TOMLDecodeError as e: errors.append(f".keelokit/state.toml: invalid TOML ({e})"); return {}`.

### INT-3 · `guard.py --claude` fails open (non-blocking exit 1, not `--claude`'s documented exit 0/2) on any input shape it doesn't expect (P2)
- **Persona / context:** "An agent inside a Keelokit project trying to get past the guard" persona / adversary for INV-002; also plain robustness of the `PreToolUse` hook wired in `hooks/hooks.json`. HEAD 19b332e, also present at v0.7.1 (`guard.py` is byte-identical between `template/.keelokit/bin/guard.py` and the root copy, confirmed by `diff`).
- **Steps:** Fed `guard.py --claude` every input shape called for by the plan (malformed JSON, missing `tool_input`, unknown tool, empty command, huge stdin, and — going further than the plan — a `tool_input` whose type doesn't match what `edit_payload`/`args.get` expects):
  ```
  echo 'not json at all {{{' | python3 guard.py --claude; echo $?      # exit 1, traceback (json.decoder.JSONDecodeError)
  printf ''                  | python3 guard.py --claude; echo $?      # exit 1, traceback (same)
  echo '{"tool_name":"Bash","tool_input":"oops"}' | python3 guard.py --claude; echo $?   # exit 1, traceback (AttributeError: 'str' object has no attribute 'get')
  echo '{"tool_name":"Bash"}' | python3 guard.py --claude; echo $?                       # exit 0 (fine — missing tool_input defaults to {})
  echo '{"tool_name":"FooBarTool","tool_input":{"command":"rm -rf /"}}' | ... ; echo $?   # exit 0 (fine — unknown tool isn't Bash, not evaluated)
  ```
  A 5 MB single-argument command and a command with 2000 repeated `-c x` flags (to probe the nested-quantifier `GIT_NO_HOOKS` regexes for ReDoS) both returned in well under 1 second — no performance issue found there.
- **Expected:** `docs/releasing.md`'s own directory-scan notes describe the contract in exactly two states: *"The guard only blocks (exit 2) or lets the call through (exit 0); it never approves."* INV-002 [MUST]: "The guard only blocks or lets a call through; it never approves one." Both describe a closed set of two outcomes.
- **Observed:** On malformed JSON, empty stdin, or a `tool_input` of the wrong JSON type, `guard.py --claude` does neither: it crashes with an **unhandled Python exception and exit code 1** — a third, undocumented outcome. Per Claude Code's hook contract, exit code 2 is the only blocking signal; any other non-zero code (including this 1) is a **non-blocking** error — stderr is shown to the person, but the tool call proceeds exactly as if the guard had exited 0. So on these inputs the guard's net effect is indistinguishable from "let the call through," just dressed as a crash instead of a clean allow — the one behaviour the docs say never happens outside the documented exit-0 case, and the one the guard's whole raison d'être (a security speed bump for secrets, `--no-verify`, skipped tests, etc.) depends on not doing silently.
- **Evidence:** Full command+output above (session, no scratch file needed — run directly against the HEAD scratch clone at `inv003`... reran against a fresh clone for cleanliness, same result both times). `tool_input` being a bare string is not far-fetched: it is exactly the shape a buggy/older client or a different hook matcher could send, and the guard has no schema check before touching it.
- **Where:** `.keelokit/bin/guard.py:144-146` (`claude()`, `event = json.load(sys.stdin)` and `args.get(...)` both unguarded), identical in `template/.keelokit/bin/guard.py`.
- **Root cause (probable):** No top-level `try/except` around `claude()`'s body; every other hard case in the file (unknown tool, missing fields) degrades gracefully to "no problem found," but a shape the parser can't even open crashes instead of also degrading — in the wrong direction for a security control (fail-open instead of fail-closed, and undocumented instead of "always 0 or 2").
- **Class:** isolation (fail-open under malformed input) — the invariant this touches is INV-002.
- **Should have been caught by:** the plan's own INV-002 attack list ("malformed JSON, missing tool_input, unknown tool, empty command, huge stdin") — run as written, three of the five shapes trip this; there's no test in `tests/` (per the earlier grep, `tests/test_guard.py`-style coverage exists for rule behaviour but not for parser-level malformed input) exercising `guard.py --claude` with non-JSON or wrong-shaped stdin.
- **Proposed fix:** wrap `claude()`'s body (or just its call site at the bottom) in `try/except Exception`, and on any exception print a clear message to stderr and `return 2` (block) rather than let the interpreter's default traceback path fall through to exit 1 — fail closed, matching "it never approves," and keep the exit code contract exactly `{0, 2}` as documented.

## Covered

- INV-001 (release.sh + release.yml, consistency): ran `scripts/release.sh` in a scratch clone with a local bare `origin` (never the real remote) through every edge case in the plan — Unreleased heading with a `— title`, an empty Unreleased section, an already-existing tag, `release` not an ancestor of `main`, and equal/lower/malformed version strings (`v0.7.4`, no arg, `0.8`). All six were rejected with the expected `fail "..."` message and no partial file writes (`git status`/`plugin.json` unchanged after a rejected run); the two accepted runs (plain Unreleased, and one with a ` — title`) produced headings that replay correctly against `release.yml`'s tag-job grep and its "Upgrading"-title `sed` pipeline, and against the manifests job's `\n## {version} — ` check in `ci.yml`. No INV-001 bug found.
- INV-002 (guard.py, consistency): every shape in the plan tried; three of five crash instead of returning a documented exit code — see INT-3. No ReDoS/perf issue found on huge or crafted-adversarial `GIT_NO_HOOKS` input.
- INV-003 (copier `_skip_if_exists`, isolation): generated at v0.7.0 and separately at v0.7.1, edited every path in the `_skip_if_exists` list (`docs/context/*.md`, `docs/prd.md`, `.keelokit/{rules.local,exceptions,critical,profile}.toml`, `docs/escapes.md`, `CHANGELOG.md`, `backlog/*.md`, `README.md`, `apps/*/src/**` including the negated `i18n.test.ts`, `apps/*/e2e/**`, `apps/*/index.html`, `packages/*/src/**`, `apps/*/prisma/**`, `apps/*/package.json`, `packages/*/package.json`, `apps/*/.env.example`, `apps/api/.env.ci`, `apps/api/fly.*.toml`), then ran `copier update -a .keelokit/answers.yml --vcs-ref <HEAD sha> --defaults --conflict rej`. From v0.7.1 there is no template content diff at all to HEAD (confirmed with `git diff --stat v0.7.1 19b332e -- template/ copier.yml`, empty), so that run was a null test; re-ran from v0.6.0 → HEAD, a span with real content changes to `README.md.jinja`, `CHANGELOG.md` and `profile.toml.jinja` (all three `_skip_if_exists`), and confirmed byte-for-byte that the product's edited versions survived untouched (`grep`/`diff` after update) while the template-owned `.keelokit/bin/doctor.py` and `.keelokit/harness/rules.toml` did update. No `.rej` files, no INV-003 bug found in either span. Did not get to test the `!apps/*/src/i18n/i18n.test.ts` negation's actual overwrite behavior under a real upstream content change to that file specifically (only confirmed the file is present and edited by the product; the negation exists to force I18N-1's generic test to update even though its parent glob is skipped, and no version span tested had a content change to that file to exercise the merge/reject path) — flagging as not fully covered rather than as a finding.
- INV-004 (`project-adopt`/`mode=harness`, isolation): ran `copier copy --data mode=harness` against a richer fixture than `test-template.sh`'s stub — existing `AGENTS.md`, `CLAUDE.md`, `.gitignore`, `docs/context/*.md` with real content, a `pnpm-workspace.yaml`, an existing `CHANGELOG.md`, and a **partial pre-existing `.keelokit/`** (stale `profile.toml`, `rules.local.toml`) simulating an interrupted earlier adopt. Copier correctly reported `conflict`/`skip` for the two pre-existing `.keelokit/*.toml` files and `git status --porcelain --untracked-files=all` showed zero changes outside `.keelokit/` afterwards. No INV-004 bug found. Also read `skills/project-adopt/SKILL.md` end to end: it explicitly proposes (never silently installs) the git pre-commit hook and a CI doctor step, consistent with what was observed.
- INV-005 (`Story:` trailer, consistency): built a fixture repo and tried an unmerged branch's trailer (correctly excluded), a trailer folded into the commit **subject** rather than the footer (correctly not recognized as a trailer at all — git's own trailer parser requires footer position), a **lowercase** `story: ID` trailer (recognized anyway — git's trailer-key matching is case-insensitive; more lenient than the documented `Story:` spelling but not unsafe, not filed as a finding), and a squash merge (trailer correctly carried through and counted once on `main`). The `main` missing / `origin/main` present case correctly falls back to `origin/main`. The detached-HEAD case only failed when **neither** ref exists at all, which is exactly the real, everyday shape of the generated project's own PR-triggered `checks` job — see INT-1, the one real bug this line of attack found.
- INV-006 (doctor `--ci`, consistency): confirmed `--ci` and no-argument mode share the same `return 1 if errors else 0` path (`--ci` isn't a distinct branch in `main()`, so this always held trivially); confirmed `--brief`'s unconditional `return 0` is intentional and documented (module docstring, and `hooks/hooks.json`'s wrapper also forces `exit 0` independent of doctor's own code) rather than an INV-006 violation — a pending-decision note from the plan, resolved as "working as designed." Tried malformed TOML across the `.keelokit/*.toml` family: `rules.local.toml`/`profile.toml`/`critical.toml`/story front matter all degrade to a clean `errors.append` (verified by code reading, not separately re-broken here since `LOG-2` in `docs/bugbash/2026-09-27/logic.md` already exercises `exceptions.toml`'s date field); `state.toml` does not — see INT-2. Did not separately fuzz `--scope <ID>` with a nonexistent id or `--critical --changed` outside a git repo (ran out of time budget); noting as not covered.
- Replayed `release.yml`'s tag-job shell logic (heading grep, title-`sed` extraction) locally against the CHANGELOGs produced by each `release.sh` run above; did not spin up an actual `gh` CLI/stub to exercise the GitHub Release creation step end-to-end.

## Not covered

- The `!apps/*/src/i18n/i18n.test.ts` negation's actual conflict/merge behavior when the *template's own* copy of that file changes content upstream (no version span available in this repo's history had a content diff there to exercise it against a product edit).
- `doctor.py --scope <ID>` and `--critical [--changed]` error paths (bad/unknown scope id, running outside a git repo, a `critical.toml` area glob that matches nothing) — not exercised.
- `gh release create` in `release.yml`'s second step (no `gh` stub was built; only the shell/grep logic feeding it was replayed).
- Concurrency: two `release.sh` runs racing, or two `guard.py --claude` invocations racing on the same repo (INV-002/INV-001 are per-call, but the plan's "N parallel requests" attack class was not run against these single-writer CLI scripts, which have no shared mutable state beyond the working tree itself).
- INV-003/004 against a repo using a different package manager or a non-pnpm workspace layout, and against Windows-style paths.

---

## Round 2 — INV-003/INV-004 on the upgrade path of an ADOPTED (`mode=harness`) project

Round 1's INV-003 coverage note (above) exercised `_skip_if_exists` product files (`README.md`,
`apps/*/src/**`, …) that only exist under `mode=project`, and its INV-004 coverage note exercised
only the initial `copier copy --data mode=harness` (fresh adopt), never a subsequent
`harness-upgrade` on a project that was already adopted. This repo's own `.keelokit/answers.yml`
(`_commit: v0.7.0`, `mode: harness`, `_src_path: gh:leosimini/keelokit`) is exactly that
untested case, so this round ran `skills/harness-upgrade/SKILL.md` for real: once against this
repo's own state (v0.7.0 → HEAD), and repeatedly against a from-scratch `mode=harness` fixture
(an unrelated existing repo with `package.json`/`README.md`/`src/`, adopted at v0.7.0, then given
a local `.keelokit/rules.local.toml` rule (`PAY-1`) and `.keelokit/exceptions.toml` entry
(`UI-1`), matching the format `harness-upgrade`'s own SKILL.md and `project-adopt`'s SKILL.md
show) across several real upstream template changes (a new house rule, a reworded rule, a
renamed file). All of those runs confirmed the happy path holds: `mode: harness` survives every
update, the `{% if mode == 'harness' %}**{% endif %}` / `!.keelokit/**` exclude pair keeps every
change inside `.keelokit/`, `_skip_if_exists` files (`rules.local.toml`, `exceptions.toml`,
`profile.toml`, `critical.toml`) come through byte-identical (`md5sum` before/after) even across
three chained updates, non-`skip_if_exists` harness files (`doctor.py`, `guard.py`,
`harness/rules.toml`) do pick up real upstream changes, file renames/deletions inside `.keelokit/`
are tracked correctly, and a genuine content conflict correctly produces a `.rej` (standard
`git apply --reject` semantics: the conflicting hunk's region ends up as the new template's
content, with the previous state recorded in the `.rej`, exactly what `harness-upgrade`
SKILL.md step 4 tells the user to expect and resolve — not a bug). One real, previously
unreported bug came out of testing the "second upgrade" case round 1 never ran:

### INT-101 · A project's `_commit` can silently become an unresolvable git-describe string, permanently crashing every future `harness-upgrade` (P1)
- **Persona / context:** "User with a fork via `KEELOKIT_TEMPLATE=gh:<you>/keelokit`" and the
  Contributor persona, on the Upgrader journey, for a `mode=harness` (adopted) project — but the
  root cause is in how Copier resolves a local `_src_path`, so it applies identically to
  `mode=project`. HEAD 19b332e. Not introduced by this branch: the mechanism is entirely inside
  the `copier==9.18.2` library and inside `.keelokit/answers.yml`'s format, both unchanged since
  v0.7.0 — reproduces identically against the `v0.7.1` tag (fca160c) and would reproduce against
  any Keelokit release, past or future, that keeps the documented `harness-upgrade` flow.
- **Steps:** `skills/harness-upgrade/SKILL.md:24-26` explicitly anticipates a local `_src_path`
  ("If `_src_path` in that file is a local path, the project can only upgrade from that machine")
  — exactly the situation for a contributor testing their own fork's in-progress template edits
  with `KEELOKIT_TEMPLATE=<local clone>` before pushing, or (as this very bug bash's own
  isolation instructions and round 1's `nfr.md:84` both did) a lens/tester pointing `_src_path`
  at a local clone. Copier's own `--help` text for `update` says: *"If you want to checkout
  always the latest version, use `--vcs-ref=HEAD`"* — nothing in `harness-upgrade`'s SKILL.md
  tells a user not to do exactly that (step 3's command uses a `<tag>` placeholder but never
  says "must be a tag, never `HEAD`").
  1. Adopt a plain existing repo at v0.7.0, `mode=harness` (`uvx copier==9.18.2 copy --vcs-ref
     v0.7.0 --defaults --data mode=harness --data project_name=Acme3 <local-clone> <dir>`).
  2. Make one **uncommitted** edit in the local template clone (`echo x >>
     template/.keelokit/harness/execution-protocol.md`) — an entirely ordinary state for someone
     mid-edit on their fork, not a contrived setup.
  3. Run exactly `harness-upgrade`'s documented command, substituting `HEAD` for `<tag>`:
     `uvx copier==9.18.2 update -a .keelokit/answers.yml --defaults --conflict rej --vcs-ref HEAD`.
     It succeeds, with only a terse `DirtyLocalWarning: Dirty template changes included
     automatically` on stderr (easy to miss; not a Keelokit message and not mentioned anywhere in
     Keelokit's docs). It silently writes `_commit: bugbash-test-3-1-g2ec7e9a` into
     `.keelokit/answers.yml` — a `git describe`-style string (`<ref>-<n>-g<sha>`) whose `<sha>`
     is an **ephemeral commit Copier fabricated on the fly** (`git -c core.fsmonitor=false commit
     -m "Copier automated commit for draft changes"` inside a temp clone, per
     `copier/_vcs.py:399-419` in the installed `copier==9.18.2` package) to package the dirty
     working tree — a commit that is never written to the real repository and disappears with the
     temp clone.
  4. Commit the local template edit for real (so the fork's source tree is now perfectly clean)
     and run `harness-upgrade` again — this time with a proper, real, resolvable tag, exactly as
     SKILL.md step 2 says to ("pick the target tag"): `uvx copier==9.18.2 update -a
     .keelokit/answers.yml --defaults --conflict rej --vcs-ref bugbash-test-4`.
- **Expected:** Per `harness-upgrade`'s own promise ("brings Keelokit's new rules and checks into
  the project, on a branch, and never rewrites their product") and INV-003, every
  `harness-upgrade` invocation should either succeed (possibly with `.rej` files to resolve) or
  fail with a clear, actionable message — never leave the project in a state where **all future**
  upgrades are impossible regardless of what tag is targeted next.
- **Observed:** Step 4's update — run against a perfectly ordinary, clean, real tag — crashes with
  a raw Python traceback instead of updating anything:
  ```
  $ uvx copier==9.18.2 update -a .keelokit/answers.yml --defaults --conflict rej --vcs-ref bugbash-test-4
  ...
    File ".../copier/_vcs.py", line 428, in clone
      git("-c", "core.fsmonitor=false", "checkout", "-f", ref)
  ...
  plumbum.commands.processes.ProcessExecutionError: Unexpected exit code: 1
  Command line: | /usr/bin/git -c core.fsmonitor=false checkout -f bugbash-test-3-1-g2ec7e9a
  Stderr:       | error: pathspec 'bugbash-test-3-1-g2ec7e9a' did not match any file(s) known to git
  ```
  Copier needs the **previously recorded** `_commit` (`bugbash-test-3-1-g2ec7e9a`, written in step
  3) to check out the "before" side of its three-way diff, and that string is not a real,
  resolvable git ref anywhere — not in the fork's repo, not in the ephemeral temp clone from step
  3 (already discarded). The command exits non-zero with `git status --porcelain` on the project
  completely unchanged (no partial write in this run) — so the project is not corrupted further,
  but it is **permanently stuck**: every subsequent `harness-upgrade`, targeting any tag, past or
  future, fails identically, because the failure is in resolving the *old* side of the diff, not
  the new one. `python3 .keelokit/bin/doctor.py` (run against this exact stuck state) reports
  nothing about it at all — 20 ordinary adopt-debt errors, zero mention of `_commit` or the
  harness being unable to update — so the person only discovers the problem the next time they
  try to upgrade, via this traceback, with no Keelokit-authored message anywhere in it. The only
  way out found in this bash was hand-editing `.keelokit/answers.yml`'s `_commit` back to a real
  tag (`v0.7.1`) — the exact action both the file's own header (`# Written by Copier — never edit
  by hand.`) and `harness-upgrade`'s framing of that file as Copier's own bookkeeping tell the
  user never to do; after that hand-edit the same `--vcs-ref bugbash-test-4` update succeeds
  cleanly.
- **Evidence:** Full transcripts above, reproduced twice independently in two separate fixtures
  (`$SCRATCH/integrity2/fixture-adopted` via `--vcs-ref HEAD` on a repeat run, and
  `$SCRATCH/integrity2/fixture-adopted3` via the exact clean-fork-editing sequence above); the
  installed `copier==9.18.2`'s `_vcs.py:399-419` (dirty-commit block, gated on `ref == "HEAD" and
  url_abspath.is_dir()`) and `_template.py:586`/`_vcs.py:428` (the `checkout -f <stored _commit>`
  that fails) confirm the mechanism; `skills/harness-upgrade/SKILL.md:19-26` and
  `.keelokit/answers.yml:1` (and `template/.keelokit/answers.yml.jinja:1`, byte-identical since
  v0.4.0 per `git log --follow`) confirm neither warns about it. `nfr.md`'s existing
  `copier update ... --vcs-ref HEAD` idempotency check (line 84) didn't hit this because its
  source clone happened to be clean both times it ran — this bug only surfaces once, on the
  *next* update after any single dirty-tree `--vcs-ref HEAD` run anywhere in the project's
  history.
- **Where:** `skills/harness-upgrade/SKILL.md:19-26` (no warning against `--vcs-ref HEAD` or a
  dirty local `_src_path`); `.keelokit/answers.yml:1` / `template/.keelokit/answers.yml.jinja:1`
  (the file `_commit` is stored in, and the comment telling users never to touch it — with no
  corresponding validation anywhere that what gets stored there is actually re-resolvable);
  `.keelokit/bin/doctor.py` (no check at all for `_commit`'s shape or resolvability, so the
  broken state is invisible until the next upgrade attempt).
- **Root cause (probable):** Copier's own dirty-local-source convenience feature (auto-commit
  and describe dirty changes when `--vcs-ref HEAD` is used against a local directory) produces a
  version string that is only valid for the single invocation that created it; Keelokit stores
  that string verbatim as the durable, cross-invocation `_commit` bookmark with no check that
  it is a stable, re-resolvable reference, and neither the harness-upgrade skill nor doctor.py
  warns against or detects the mismatch.
- **Class:** consistency — this doesn't cleanly break one of INV-001..006 by name, but it breaks
  the precondition INV-003 depends on (that `harness-upgrade` is a working, repeatable operation);
  it also undermines INV-005/INV-006 indirectly, since a project stuck like this can never pull in
  new/fixed house rules or doctor checks again through the documented path.
- **Should have been caught by:** the Focus brief's own repeat-update scenario ("run `copier
  update` ... on a branch" — implicitly repeatable) and `nfr.md`'s idempotency check, had either
  one included a dirty-source variant; there is no test in `tests/` that exercises two
  chained `copier update` calls against a `mode=harness` fixture with any local `_src_path`
  edits between them.
- **Proposed fix:** the smallest change at the cause: `harness-upgrade`'s SKILL.md step 2/3
  should explicitly say to commit all local template changes before running `update`, and to
  target only a real tag or commit SHA — never `HEAD` — when `_src_path` is a local path (a one-
  line addition next to the existing local-`_src_path` note at lines 24-26). Defense in depth:
  have `doctor.py` flag a non-canonical `_commit` (one that doesn't match `^v?\d+\.\d+\.\d+$`) as
  an ERROR with a clear message and the exact fix (edit `_commit` to the last real tag), so the
  breakage is caught at the next `doctor`/dashboard run instead of silently waiting for the next
  `harness-upgrade` attempt to crash uninformatively.

### Round 2 — Covered

- Real self-adoption state: `copier update -a .keelokit/answers.yml --defaults --conflict rej
  --vcs-ref HEAD` run against this repo's own `.keelokit/answers.yml` (`_commit: v0.7.0`,
  `mode: harness`) in a scratch clone of HEAD 19b332e. Result: only `_commit` changed (bumped to
  a HEAD-describing string); confirmed by diffing `template/.keelokit/**` between `v0.7.0` and
  HEAD (`git diff v0.7.0 HEAD --stat -- template/.keelokit`) that there is in fact no real content
  change in that window beyond a cosmetic template-file rename (`{{_copier_conf.answers_file}}.jinja`
  → `answers.yml.jinja`, commit `81fec18`) — so this specific window is a null test for conflict
  handling, and INT-101 above was found by testing richer, synthetic version spans instead.
- A from-scratch `mode=harness` fixture (existing `package.json`/`README.md`/`src/`, not a
  Keelokit-shaped repo) adopted at v0.7.0, given a local `PAY-1` rule in `rules.local.toml` and a
  `UI-1` exception in `exceptions.toml` (same shapes the repo's own commented templates show),
  then updated across three real synthetic upstream changes (new house rule, reworded rule,
  renamed file) chained in sequence. `mode: harness` held throughout; `_skip_if_exists` files
  came through byte-identical (`md5sum` before/after each hop); no file ever appeared outside
  `.keelokit/`; deletions/renames of non-`skip_if_exists` files inside `.keelokit/harness/`
  tracked correctly; a genuine conflict (a hand-edited `id` field colliding with an upstream wording
  change) produced a `.rej` and left the file matching the new template — standard
  `git apply --reject` behaviour, matching what `harness-upgrade` SKILL.md step 4 tells the user
  to expect, not a bug.
- The repeat-update / "second upgrade" case round 1 didn't run: found INT-101 (above).
- Whether `doctor.py`/dashboard's `behind()` check (comparing `.keelokit/answers.yml`'s `_commit`
  against `.claude-plugin/plugin.json`'s version) reports correctly for this repo's real state:
  it does (`harness=0.7.0 < plugin_version=0.7.1` → "behind", correctly) — no bug there, and
  `doctor.py` was also confirmed to say nothing about a corrupted/unresolvable `_commit`, feeding
  into INT-101's "should have been caught by" / proposed fix.

### Round 2 — Not covered

- A `mode=harness` fixture that pre-dates `.keelokit/profile.toml`/`critical.toml` existing at
  all (a project adopted before v0.4.0-era answers, if any such projects exist) — out of reach
  without an older real project to test against.
- `project-adopt`'s own docs/context write (step 3, "Intake from what exists") relative to
  INV-004's "until the user says yes to a code change" wording — `docs/context/*.md` is written
  outside `.keelokit/` by the `/keelokit:plan-intake` flow that `project-adopt` calls, before the
  separate "adopt" gate's approval; this looked worth a closer read of `plan-intake`'s own
  SKILL.md against INV-004's exact wording, but that skill and its approval-timing were not
  audited in this round — flagging as a possible gap for a future pass rather than a finding here,
  since it wasn't verified with reproduction.
- Testing INV-003/004 with a non-git destination (`harness-upgrade` step 1 requires a git repo;
  did not check what a non-repo destination actually reports).
- Concurrency: two `harness-upgrade` runs (or `project-adopt` + `harness-upgrade`) racing on the
  same working tree — not attempted.

---

## Round 3 — INV-004 against `project-adopt`'s steps 3–5 (docs/context, decisions, diagnosis, backlog), not just the copier step

Rounds 1–2 verified INV-004 only against step 2 (`copier copy --data mode=harness`, which
Copier itself confines to `.keelokit/` via `_exclude`'s `mode == 'harness'` pair — reconfirmed
here, `copier.yml:65-68`). Round 2 flagged, but did not test, the gap this round covers: step 3
(`plan-intake`, writing `docs/context/*.md`) and step 5 (writing `docs/diagnosis.md` then
`plan-backlog`, writing `backlog/`) both run **outside Copier entirely** — they are plain file
writes the skill/agent performs directly, so nothing like `_skip_if_exists` protects them, and
per the gate table (`skills/project-adopt/SKILL.md:12-16`) both run *before* their own gate's
human approval, let alone before the "adopt" gate's exception approvals. Built a fixture
(`$SCRATCH/integrity3/fixture`) simulating exactly the case the brief asks for: a real,
pre-`.keelokit/` repo that already has content at all four paths — `docs/context/product.md`
(a 2-year internal spec, own format), `docs/decisions/0001-choose-framework.md` (a real ADR,
`0001`-numbered per the standard ADR convention), `docs/diagnosis.md` (an unrelated incident
postmortem) and `backlog/stories/GH-042.md` (an imported Jira ticket) — then ran
`copier copy --data mode=harness` (confirmed: only `.keelokit/**` touched,
`git status --porcelain` before/after), then `doctor.py` and `dashboard.py` against the result.

### INT-201 · `project-adopt`'s doc-writing steps (intake, diagnosis, backlog) have no pre-existence check at any of their four output paths — a repo with real content there gets it silently read as Keelokit's own and is one un-gated write away from having it overwritten (P1) — productRule
- **Persona / context:** "Developer or small team with an existing non-Keelokit repo" — the
  brief's own example already lists "an AGENTS.md or CLAUDE.md already present"; a repo that
  also already keeps ADRs under `docs/decisions/`, a `backlog/` folder, or a `docs/diagnosis.md`
  from its own incident process is at least as plausible for a team mature enough to be worth
  adopting Keelokit onto. HEAD 19b332e; the mechanism (no Copier involvement at all for these
  four paths in `mode=harness`) is identical at v0.7.1 (`fca160c`) and has been unchanged since
  `project-adopt`/`plan-intake`/`plan-backlog` were introduced — pre-existing, not from this branch.
- **Steps:**
  1. Built a fixture repo with pre-existing `docs/context/product.md` (own format),
     `docs/decisions/0001-choose-framework.md`, `docs/diagnosis.md` (unrelated postmortem) and
     `backlog/stories/GH-042.md`, committed.
  2. `uvx copier==9.18.2 copy --defaults --vcs-ref HEAD --data mode=harness --data project_name="Acme Billing" --data description="billing app" <clone> .` —
     confirmed via `git status --porcelain --untracked-files=all` that only ten new files under
     `.keelokit/` appeared; none of the four pre-existing files were touched by Copier (expected —
     this is round 1/2's already-verified part).
  3. Read `skills/project-adopt/SKILL.md` step 3 ("## 3. Intake from what exists", line 70:
     `Run /keelokit:plan-intake`) and step 5 ("## 5. Diagnose and seed the backlog", line 115:
     `Write docs/diagnosis.md: ... Then run /keelokit:plan-backlog`) end to end, plus
     `plan-intake`'s and `plan-backlog`'s own SKILL.md and `references/context-format.md`, for
     any instruction to check whether `docs/context/*.md`, `docs/decisions/*.md`,
     `docs/diagnosis.md` or `backlog/` already have unrelated content before writing to them.
     `grep -n -i "already exist|overwrite|merge|preserve|collision|conflict"` across all of
     `skills/project-adopt/SKILL.md`, `skills/plan-intake/SKILL.md`,
     `skills/plan-intake/references/context-format.md` and `skills/plan-backlog/SKILL.md` returns
     nothing relevant: the only "already exists" match is `plan-intake`'s harvest step ("Ask once
     what already exists in writing... briefs, notes, decks, screenshots, a repo, links" —
     `skills/plan-intake/SKILL.md:16`), which treats existing material purely as a *source to
     harvest facts from*, not as content to protect. `plan-intake`'s write step says flatly
     "Write the five files **exactly as** `references/context-format.md` shows"
     (`skills/plan-intake/SKILL.md:44-45`) with no exists-check; `context-format.md` shows the
     five files' target shape with no skip/merge note either. `project-adopt`'s own step 4 hardcodes
     the ADR filename as literally `docs/decisions/0001-existing-stack.md`
     (`skills/project-adopt/SKILL.md:106`), not "the next ADR number" — so on a repo that already
     numbers its ADRs from `0001` (the near-universal convention, and exactly what the fixture
     has), Keelokit's own first decision collides on the sequence number even though the filename
     text differs.
  4. Ran `python3 .keelokit/bin/doctor.py` and
     `python3 <clone>/skills/project-dashboard/scripts/dashboard.py --root . --out dash.html --standalone --lang en`
     against the fixture (pre-intake, pre-backlog — i.e. exactly the state right after step 2,
     before an agent has run steps 3/5 for real) to see how the pre-existing files already read.
- **Expected:** Per the skill's own description ("Bring an existing repository... without
  touching its code" — `skills/project-adopt/SKILL.md:3`) and INV-004 ("`project-adopt` writes
  only inside `.keelokit/` until the user says yes to a code change" — `docs/context/domain.md:15`),
  a repo's own real, pre-existing planning/decision/backlog documents should either be left alone,
  or the skill should explicitly say to merge/rename/ask before writing over them — and the
  dashboard/doctor should not present foreign content as if it were Keelokit's own diagnosis just
  because it happens to sit at a conventional path.
- **Observed:** Two things, together, that add up to a real content-loss and misattribution risk:
  1. **No gate ever fires for these paths.** INV-004's only stated release valve is "until the
     user says yes to a code change" — but `docs/context/*.md`, `docs/decisions/*.md`,
     `docs/diagnosis.md` and `backlog/**` are all doc paths, not "code", and the skill's own
     framing (line 3, line 8: "The code is never modified by this skill without the user's yes")
     deliberately scopes the promise to *code*. So by the skill's own words these four paths are
     *never* covered by any "yes" at all — they are written automatically by steps 3 and 5, and
     the gate table's approvals ("approves the context", "approves each exception", "approves the
     order" — lines 14-16) all happen *after* the write, as a review of what was already produced,
     not as a pre-write confirmation. Whether this makes INV-004 (as literally worded in
     `domain.md:15`, with no docs/code carve-out) technically false for every real `project-adopt`
     run, or whether it's a wording gap where "code" should be read narrowly (matching the SKILL's
     own line 3/8 language) — either way, nothing in the implementation distinguishes "a repo with
     nothing at these four paths yet" from "a repo whose real, valuable content already lives
     there", and the invariant as written gives no test any way to tell the difference either.
  2. **Once something is there, doctor/dashboard already read it as Keelokit's own**, which is
     the concrete mechanism that turns the wording gap into a real hazard the moment an agent
     runs steps 3/5 for real. Against the fixture, *before any intake or backlog step ran*:
     ```
     $ python3 .keelokit/bin/doctor.py
     ...
     ERROR docs/context missing domain.md, constraints.md, environments.md, gaps.md — run the intake (/keelokit:plan-intake)
     ```
     — note it does **not** list `product.md` as missing: the mere existence of the file at that
     path, regardless of its content or format, counts as satisfying it (`doctor.py`'s
     `CONTEXT_FILES` check is existence-only — confirmed by reading the check, no per-file format
     validation exists). The dashboard goes further and actively renders the foreign content as
     first-class Keelokit output:
     ```html
     <!-- Context/"intake" stage: -->
     <span class="sum">1 documents · 0 open questions (0 blocking) · 0 invariants</span>
     ...<span class="path">docs/context/product.md</span>...
     <h3>Our actual product spec (pre-Keelokit)</h3><p>...</p><h4>Roadmap</h4>

     <!-- "Project decisions" panel: -->
     <span class="k">Recorded decisions</span><ul>
       <li><a href="#stage-stack">ADR 0001: Choose Fastify over Express</a> <span class="muted">· Accepted</span></li>
     </ul>
     <p class="muted">These are fixed: Keelokit doesn't ask again or change them on its own.
     To change one, ask for it explicitly in the chat.</p>

     <!-- "Adopt" stage evidence: -->
     <span class="path">docs/diagnosis.md</span>...
     <h3>Postmortem: Payment outage 2024-03-01</h3>
     <p>Root cause: a null pointer in the reconciliation job. Not a Keelokit diagnosis at all — ...</p>
     ```
     The dashboard literally tells the user Keelokit "doesn't ask again or change [this] on its
     own" about an ADR Keelokit has never seen, and shows the team's own incident postmortem
     inside the "adopt" stage's own evidence list, indistinguishable in the UI from a diagnosis
     Keelokit produced. If steps 3/5 then run for real with no exists-check (per the reading
     above), `docs/context/product.md` and `docs/diagnosis.md` are exactly the paths `plan-intake`
     and step 5 write to — so the next thing that happens to this "recorded", "fixed" content is
     very plausibly getting overwritten by Keelokit's own generated version, with no step in
     between that ever asked "yes, replace this?".
- **Evidence:** Full commands and output above; fixture at
  `$SCRATCH/integrity3/fixture` (git history preserved, one commit before the copier run, `git
  status --porcelain` empty for all four foreign paths after it); rendered
  `$SCRATCH/integrity3/dash.html` (grepped snippets above, byte-for-byte from the file);
  `copier.yml:43,65-68` (`_exclude` — confirms these four paths are outside Copier's reach
  entirely in `mode=harness`, so no `_skip_if_exists`-style mechanism can apply to them even in
  principle); `skills/project-adopt/SKILL.md:3,8,12-16,70,106,115`;
  `skills/plan-intake/SKILL.md:16,44-45`; `skills/plan-intake/references/context-format.md`
  (five-file list, no skip/merge note); `docs/context/domain.md:15` (INV-004's exact text).
- **Where:** `skills/project-adopt/SKILL.md` (steps 3, 4's `0001-existing-stack.md`, 5);
  `skills/plan-intake/SKILL.md:16,44-45` and its `references/context-format.md`;
  `skills/plan-backlog/SKILL.md` (no exists-check in its "Consolidate" section either — it merges
  *Keelokit* duplicates, never checks for non-Keelokit files already at `backlog/`);
  `.keelokit/bin/doctor.py` `CONTEXT_FILES`/its existence-only check (`doctor.py:36`, used in
  `main()`'s context-completeness block); `skills/project-dashboard/scripts/dashboard.py:451`
  (`locked_note`), `:654-655` (`decisions` glob — any `docs/decisions/*.md` qualifies, no
  Keelokit-authorship marker exists to distinguish one), `:714` (`docs/diagnosis.md` unconditionally
  listed as "adopt" evidence whenever the file exists, regardless of who wrote it).
- **Root cause (probable):** `project-adopt`/`plan-intake`/`plan-backlog` were designed around the
  assumption that a freshly-adopted repo has nothing yet at `docs/context/`, `docs/decisions/`,
  `docs/diagnosis.md` or `backlog/` — reasonable for a repo with no prior process, but false for
  exactly the more mature "existing repo" teams the adopt journey targets; there is no marker
  (front-matter field, filename convention, or check) anywhere in the format that lets Keelokit's
  own tooling tell "content we wrote" from "content that was already there", so every reader
  (skill instructions, `doctor.py`, `dashboard.py`) treats path-existence as Keelokit-authorship.
- **Class:** isolation — INV-004.
- **Should have been caught by:** an isolation test per `references/invariants.md`'s isolation row
  (a fixture with foreign content already at each of the four output paths, run through the real
  skill flow, asserting the pre-existing bytes survive) — no such fixture exists in `tests/`
  (`tests/` only covers `guard.py`/`doctor.py` unit behaviour on synthetic `.keelokit/` state, not
  a brownfield-content collision at these docs paths); the brief's own round-2 note flagged this
  exact gap as unverified.
- **Proposed fix:** smallest change at the cause: before `plan-intake` writes `docs/context/*.md`,
  before step 5 writes `docs/diagnosis.md`, and before `plan-backlog` writes to `backlog/`, check
  whether the target path already has non-Keelokit content (e.g. lacks the format
  `context-format.md`/`backlog/README.md` define) and if so treat it as a harvested **source**
  (as `plan-intake`'s own step 1 already does for "briefs, notes, decks") requiring the user's
  explicit yes before it's replaced — write the new content to a sibling path (or ask) instead of
  silently overwriting. Separately, make step 4's ADR filename "the next available
  `NNNN-*.md` in `docs/decisions/`" instead of hardcoding `0001-existing-stack.md`. Defense in
  depth: have `doctor.py`/`dashboard.py` distinguish Keelokit-authored docs from foreign ones (a
  marker line, or simply validating `product.md` etc. actually match `context-format.md`'s
  headings before counting them as "done") so a collision is visible in the dashboard instead of
  silently presented as settled, locked Keelokit output.

### INT-202 · `doctor.py` treats any pre-existing `backlog/stories/*.md` file as a broken Keelokit story and raises a hard ERROR on it, while `dashboard.py` silently ignores the identical file — inconsistent, and a false positive against the same "honest doctor" promise INT-201 already dents (P2)
- **Persona / context:** Same fixture and persona as INT-201, isolated down to the one concrete,
  reproducible code-level defect it surfaces: a repo whose own pre-Keelokit backlog already lives
  at `backlog/stories/*.md` (a plausible, even natural folder name for a team's own story/ticket
  tracking — the fixture's `GH-042.md`, an imported Jira ticket, needs nothing more unusual than
  that). HEAD 19b332e; `check_backlog`/`read_story` and `split_story` are byte-identical at v0.7.1
  (`template/.keelokit/bin/doctor.py`, `skills/project-dashboard/scripts/dashboard.py`
  unchanged since) — pre-existing, not from this branch.
- **Steps:** With the fixture from INT-201 (`.keelokit/` installed via `mode=harness`,
  `backlog/stories/GH-042.md` = a plain, non-Keelokit markdown ticket with no `+++` front matter),
  ran both readers of the same file:
  ```
  $ python3 .keelokit/bin/doctor.py
  ...
  ERROR backlog/stories/GH-042.md: missing +++ TOML front matter
  ```
  ```
  $ python3 <clone>/skills/project-dashboard/scripts/dashboard.py --root . --out dash.html --standalone
  $ grep -o "GH-042" dash.html   # no output at all
  ```
- **Expected:** `project-adopt`'s promise is "an honest `pnpm doctor`... every house rule either
  enforced by a real check, or excepted" (`skills/project-adopt/SKILL.md:8-10`) — an ERROR should
  mean a real problem with *Keelokit's own* backlog, not a false positive from a file Keelokit
  has no relationship to yet (this repo hasn't even reached step 5 — `plan-backlog` has never
  run). The two tools reading the identical `backlog/stories/` directory for the identical
  purpose (rendering/validating the backlog) should also treat unrecognised files the same way.
- **Observed:** `check_backlog()` (`.keelokit/bin/doctor.py:420-436`) globs
  `backlog/stories/*.md` unconditionally and calls `read_story()` on every match; `read_story()`
  (`doctor.py:389-401`) requires the `+++...+++ ` TOML front matter and, on any file lacking it,
  appends a hard `errors.append(...)` — there is no "not a Keelokit story, skip it" path at all.
  `dashboard.py`'s equivalent, `split_story()` (`dashboard.py:605-613`), returns `({}, text)` for
  the exact same shape, and its caller (`dashboard.py:668`: `if not meta.get("id"): continue`)
  silently drops it — no error, no mention anywhere in the rendered page. So the identical file,
  read for the identical purpose by two tools in the same repo that are supposed to agree on what
  "the backlog" is, is a hard blocking ERROR in one and invisible in the other; a project relying
  on `doctor --ci`/`--brief` (the SessionStart hook, and CI's `checks` job) sees a spurious error
  for a file that was never meant to be a Keelokit story, has no `[[rule]]`/exception path to
  silence it (it's not a house rule, it's a parse error on an unrelated file), and the only fix is
  to move or rename the team's own pre-existing folder to work around Keelokit's naming
  assumption.
- **Evidence:** Both commands + full output above; `.keelokit/bin/doctor.py:389-401,420-436`
  (`read_story`, `check_backlog`); `skills/project-dashboard/scripts/dashboard.py:605-613,666-676`
  (`split_story`, its caller); confirmed identical logic in `template/.keelokit/bin/doctor.py`.
- **Where:** `.keelokit/bin/doctor.py:389-401` (`read_story`'s unconditional `errors.append` on
  missing front matter, with no way to distinguish "this isn't a story at all" from "this is a
  story with a formatting mistake").
- **Root cause (probable):** `read_story()` was written assuming every `.md` file ever placed
  under `backlog/stories/` is a Keelokit story (true once `plan-backlog` is the only thing that
  ever writes there, false the moment a repo brings its own pre-existing content to that path,
  which `project-adopt`'s brownfield premise makes plausible); `dashboard.py`'s independently
  written, more defensive version happens to fail safe on the same input, showing the stricter
  behaviour in `doctor.py` was a choice, not a shared contract.
- **Class:** consistency (the two readers of the same directory disagree) / isolation
  (INV-004's premise that adopting shouldn't manufacture new failures out of a repo's own
  pre-existing, unrelated files).
- **Should have been caught by:** the same isolation-fixture gap noted in INT-201 — a
  `tests/test_doctor.py` case feeding `check_backlog()` a non-Keelokit `.md` file under
  `backlog/stories/` (none found: `tests/` covers malformed *Keelokit* stories — missing id,
  duplicate id, unknown dimensions — but not "not a story at all").
- **Proposed fix:** in `read_story()`, treat a missing `+++` block as "not a Keelokit story, skip
  it silently" (matching `dashboard.py`'s `split_story` behaviour) rather than a hard error —
  reserve the front-matter error for files that *do* start with `+++` but contain invalid TOML
  inside it, which is the actual formatting-mistake case the check exists for.

### Round 3 — Covered

- INV-004 against `project-adopt` steps 3–5 specifically (not just step 2's `copier copy`):
  read `skills/project-adopt/SKILL.md`, `skills/plan-intake/SKILL.md` (+ its
  `references/context-format.md`) and `skills/plan-backlog/SKILL.md` end to end for any
  pre-existence/merge/overwrite handling at `docs/context/*.md`, `docs/decisions/*.md`,
  `docs/diagnosis.md` and `backlog/**`; found none (INT-201).
- The concrete collision case the brief asks for: built a fixture with real, differently-formatted
  content at all four paths, ran the real `copier copy --data mode=harness` step against it, and
  ran `doctor.py`/`dashboard.py` (both real invocations, not code reading alone) against the
  result to see how the pre-existing files are read today (INT-201's observed section; INT-202 for
  the `backlog/stories/` parsing asymmetry specifically).
- Whether `doctor.py`'s harness layout (`GATES['harness']`, `CONTEXT_FILES` check) or
  `dashboard.py` misreads a foreign `backlog/*.md` being parsed as a story, or a foreign `0001`
  ADR colliding: confirmed both — the backlog case is INT-202; the ADR case is folded into INT-201
  (hardcoded `0001-existing-stack.md` filename, sequence-number collision, and the dashboard's
  "these are fixed" framing of a foreign ADR).

### Round 3 — Not covered

- Did not run `plan-intake`/`plan-backlog` as a live LLM-driven skill session against the fixture
  (only their written instructions, plus the downstream `doctor.py`/`dashboard.py` behaviour on
  hand-built fixture content) — so INT-201's claim about what an agent *would* actually do on
  overwrite is grounded in the absence of any contrary instruction in the skill text, not in a
  live rerun of the skill itself producing the overwrite. Flagging this as the honest limit of
  this round's evidence rather than a separate finding.
- `docs/decisions/` colliding on the exact same filename (not just the same leading number) —
  not attempted; the fixture used a differently-named `0001-choose-framework.md`, which already
  exposes the sequence-number collision without needing an exact filename match.
- Whether `harness-upgrade` (a later, separate flow) has the same or a different exists-check gap
  for these four paths — out of scope for this round, which is scoped to `project-adopt` steps 3–5
  as directed.

---

## Round 4 — INV-003/INV-004 with a rich adopted repo, chained across two real releases, plus the `--data mode=` mistake

This round's brief: take a rich pre-existing repo (its own `AGENTS.md`, `CLAUDE.md`, `.gitignore`,
`docs/context/`, `CHANGELOG.md`, `package.json` — round 2's fixture had only
`package.json`/`README.md`/`src/`, not `AGENTS.md`/`CLAUDE.md`/`docs/context/`), adopt it at
`v0.7.0`, update to `v0.7.1`, hand-edit all four product-owned `.keelokit/*.toml` files and commit,
then update to HEAD (19b332e) — and separately, try a `copier update` that passes
`--data mode=project` by mistake.

Built `$SCRATCH/integrity/richrepo`: a real git repo with `AGENTS.md` ("Always run `npm test`...
Never touch `vendor/`"), `CLAUDE.md` (`@AGENTS.md`), `.gitignore`, `CHANGELOG.md` (`## Unreleased`),
`docs/context/product.md`, `README.md` and `package.json`, committed. Adopted it with
`uvx copier==9.18.2 copy --vcs-ref v0.7.0 --defaults --data mode=harness --data project_name=richrepo
$SCRATCH/integrity/keelokit .` — confirmed only `.keelokit/` was created (`git status --short` →
`?? .keelokit/`), committed, then `copier update -a .keelokit/answers.yml --vcs-ref v0.7.1 --defaults
--conflict rej` (only `.keelokit/answers.yml`'s `_commit` changed), then hand-edited `profile.toml`
(`kind = "api-service"`, real traits), appended a `[[area]]` to `critical.toml`, a `[[exception]]` to
`exceptions.toml` and a `[[rule]]` (`PAY-1`) to `rules.local.toml` (the shapes their own header
comments show), committed, then `copier update -a .keelokit/answers.yml --vcs-ref HEAD --defaults
--conflict rej` (HEAD = 19b332e, this branch). Result: only `.keelokit/answers.yml` changed
(`_commit: v0.7.1` → `v0.7.1-2-g19b332e`), zero `.rej` files, and `git diff --stat v0.7.1 HEAD --
template/ copier.yml` confirms why — `template/` and `copier.yml` are byte-for-byte unchanged
between `v0.7.1` and HEAD on this branch (the branch's "adopted harness and check-bugbash workflow"
additions are all in the plugin root — `skills/check-bugbash/`, `workflows/`,
`tests/test_workflows.py` — none of which ships through Copier, so an adopted project's `update` to
HEAD is a no-op beyond the version bookkeeping; not a bug, just means this round's real signal came
from a synthetic drift test). To get a genuine merge to test, committed a throwaway branch in the
template clone (`bugbash-template-drift`) that edits `template/.keelokit/profile.toml.jinja` (a
`_skip_if_exists` file) and, separately, `template/.keelokit/harness/rules.toml` (not
`_skip_if_exists`) and updated against it: the edit to the protected file never appeared in
`richrepo/.keelokit/profile.toml` (`grep` for the marker: not present — INV-003 holds), while the
edit to the unprotected file propagated cleanly (`grep` for its marker: present) — both correct,
corroborating round 2's INT-101 coverage note with a richer fixture. `mode: harness` and all four
hand-edited `.keelokit/*.toml` files survived every hop unchanged. One genuinely new scenario came
out of the brief's last instruction — try an update with `--data mode=project` by mistake:

### INT-301 · `copier update` accepts an explicit `--data mode=project` on an already-adopted (`mode=harness`) project with no confirmation, no warning and no later detection — silently overwriting the repo's own `AGENTS.md`/`package.json`/`.gitignore` and dumping the full product scaffold into it (P0) — productRule

- **Persona / context:** "Developer or small team with an existing non-Keelokit repo... adopting
  the harness" and the Upgrader journey, for a `mode=harness` project. HEAD 19b332e. The mechanism
  (`copier.yml`'s `mode` question and `_exclude`'s `{% if mode == 'harness' %}` pair) is unchanged
  since `v0.7.0`/`v0.7.1` (`git diff v0.7.0 HEAD -- copier.yml` shows the `mode`/`_exclude` block
  untouched in this window) — reproduces identically at `v0.7.1` (fca160c), not introduced by this
  branch.
- **Steps:** In the `richrepo` fixture above (real `AGENTS.md`, `CLAUDE.md`, `.gitignore`,
  `package.json`, adopted `mode=harness`, `.keelokit/answers.yml` showing `mode: harness`,
  `_commit: v0.7.1-4-gca501b1`, clean working tree, committed), ran the exact family of command
  `skills/harness-upgrade/SKILL.md` step 3 documents, with one flag added — the kind of flag a
  human recalls from `skills/project-adopt/SKILL.md:63`'s own `--data mode=harness` example, or
  that an agent mixes up between the two skills' documented commands:
  ```
  uvx copier==9.18.2 update -a .keelokit/answers.yml --vcs-ref <newer-commit> --defaults \
      --data mode=project --conflict rej
  ```
  No `--pretend`, no interactive prompt (`--defaults` suppresses prompting), no error, no
  confirmation of any kind — the command exits 0 printing only `Updating to template version …`.
- **Expected:** INV-003 ("`harness-upgrade` never rewrites a product-owned file (`_skip_if_exists`
  in `copier.yml`)") and INV-004 ("`project-adopt` writes only inside `.keelokit/` until the user
  says yes to a code change") — both `[MUST]`. `docs/design.md`/`harness-upgrade`'s own SKILL.md
  promise: "brings Keelokit's new rules and checks into the project... and never rewrites their
  product." An adopted project should never be able to silently turn into a from-scratch product
  scaffold through the *update* path; if `mode` can be changed at all post-adoption, it should be
  behind an explicit, named, confirmed operation — not a same-shaped flag on the routine upgrade
  command with zero difference in output or prompting from a normal upgrade.
- **Observed:** `git status --short` after the command above (25 changed/new paths, evidence saved
  at `/tmp/copier_update_head.log` → `/tmp/real_mode_project.log` in this session):
  ```
   M .gitignore
   M .keelokit/answers.yml
   M .keelokit/harness/rules.toml
   M AGENTS.md
   M package.json
  ?? .githooks/  ?? .github/  ?? .gitignore.rej  ?? .nvmrc  ?? .prettierignore  ?? .prettierrc
  ?? AGENTS.md.rej  ?? CLAUDE.md.rej  ?? apps/  ?? backlog/  ?? docker-compose.yml
  ?? docs/assets/  ?? docs/decisions/  ?? docs/escapes.md  ?? eslint.config.mjs
  ?? package.json.rej  ?? packages/  ?? pnpm-workspace.yaml  ?? scripts/  ?? tsconfig.base.json
  ```
  `.keelokit/answers.yml` now reads `mode: project` (silently flipped from `harness`, with new
  `apps:`/`postgis:` keys copier itself must have prompted-and-auto-defaulted for under `--defaults`)
  — nothing in the transcript calls this out as a mode change. `AGENTS.md` (richrepo's own, "Always
  run `npm test`... Never touch `vendor/`") is **replaced in place** by Keelokit's generated
  `AGENTS.md.jinja` content (65 lines of Keelokit house rules, `pnpm verify`/`backlog/`/`apps/`
  references that don't exist in this repo) — `git diff AGENTS.md` shows a full-file replacement,
  and the repo's *original* content is relegated to `AGENTS.md.rej` (a sidecar the user has to know
  to look for and manually reconcile — it is not restored to `AGENTS.md`). `package.json` is merged
  in place with Keelokit's monorepo scripts/devDependencies (`git diff package.json`: `"test": "echo
  no tests yet"` → `pnpm -r --if-present test`, `+18` new `devDependencies`), with the pre-existing
  version verbatim in `package.json.rej`. `.gitignore` is similarly replaced (`node_modules/` →
  `node_modules`, plus 15 new Keelokit-specific ignore lines) with `.gitignore.rej` holding the
  original two lines. `CLAUDE.md` produced a `.rej` too even though its rendered content happened to
  be byte-identical to the existing file (a `.rej` for a no-op change — a smaller, separate oddity).
  Nothing was *deleted* (`git status --short | grep -c '^ D'` → `0`), but the full product monorepo
  scaffold — `apps/`, `packages/`, `backlog/`, `.github/`, `.githooks/`, `docker-compose.yml`,
  `pnpm-workspace.yaml`, `tsconfig.base.json`, `eslint.config.mjs`, `.nvmrc`, `.prettierrc`,
  `docs/decisions/`, `docs/assets/`, `docs/escapes.md` — is dumped into what was, one command
  earlier, a harness-only adoption of an unrelated real product. Checked whether anything downstream
  would catch the mode flip afterward: `.keelokit/bin/doctor.py:567`
  (`layout = "harness" if ... re.search(r"(?m)^mode: harness$", answers.read_text()) else "project"`)
  just reads whatever string is currently in `answers.yml` — it has no memory of what the project
  was adopted as, no diff against git history, and no validation that a `mode` transition is legal;
  it will happily report the new "project" layout as normal on the very next run, so nothing in the
  harness ever flags that this happened.
- **Evidence:** `/tmp/real_mode_project.log` (command + `Updating to template version
  0.7.1.post5.dev0+21793a7`), `$SCRATCH/integrity/richrepo` working tree and `git log`/`git diff`
  output reproduced above (`AGENTS.md`, `package.json`, `.gitignore` diffs; `.keelokit/answers.yml`
  full contents showing `mode: project`); `.keelokit/bin/doctor.py:567` (also identical in
  `template/.keelokit/bin/doctor.py:567`); `copier.yml:70-76` (the `mode` question: `type: str`,
  `default: project`, no `validator:`, no `when:` guarding it from being freely overridden on
  `update`); `copier.yml:12-42` (`_skip_if_exists`: none of `AGENTS.md`, `CLAUDE.md`, `.gitignore`,
  or the root `package.json` are listed — only `apps/*/package.json` and `packages/*/package.json`
  are, so once `mode=project` widens what's in scope, these root files are fully unprotected);
  `skills/harness-upgrade/SKILL.md:19-21` (documents `--data mode=harness` for the *initial* adopt
  in the sibling skill, `project-adopt`, at line 63 — the two skills' example commands differ only
  by this one flag, which is exactly the kind of thing that gets carried over by habit or by an
  agent conflating the two).
- **Where:** `copier.yml:70-76` (`mode` question, no guard); `copier.yml:12-42` (`_skip_if_exists`,
  root-level files absent); `.keelokit/bin/doctor.py:567` and `template/.keelokit/bin/doctor.py:567`
  (no mode-transition or drift check); `skills/harness-upgrade/SKILL.md` (no warning against passing
  `--data mode=...` on update at all).
- **Root cause (probable):** Copier applies any explicit `--data` override unconditionally, with no
  built-in concept of "this answer already has a recorded, different value for this existing
  project, on `update`" — that is a product-level gap for Keelokit to close, not a Copier bug.
  Keelokit built no defense-in-depth against it: `_skip_if_exists` only protects a fixed list of
  paths that happens to assume `mode=project`'s file layout (root-level `AGENTS.md`/`CLAUDE.md`/
  `.gitignore`/`package.json` aren't on it because under normal `mode=harness` operation they're
  never in scope at all, via `_exclude`'s `**` wildcard — nobody had to think about protecting them
  until `mode` itself can change), `doctor.py` never inspects `mode` for a suspicious transition,
  and no skill documents the danger of passing `--data mode=` on an `update`.
- **Class:** isolation — directly breaks INV-003 and INV-004 together, the exact combination this
  round was scoped to test.
- **Should have been caught by:** an isolation/consistency test per `references/invariants.md`'s
  INV-003/INV-004 rows that runs `copier update` against an adopted fixture with a deliberately
  wrong `--data mode=` value and asserts either a refusal or that the product-owned root files are
  unchanged; `tests/` has no such case (confirmed by `grep -rn "mode=project" tests/` finding
  nothing that pairs it with an already-adopted fixture), and `scripts/test-template.sh`'s `--adopt`
  and default (`mode=project`) runs are exercised as two entirely separate invocations, never
  chained on the same directory the way this round chained them.
- **Proposed fix:** smallest change at the cause: add a `validator:` to `copier.yml`'s `mode`
  question that raises when `_copier_conf.operation == "update"` and the new `mode` differs from
  `_copier_answers.mode` (or the equivalent Copier update-context variable) unless the invoking
  command also passes some explicit acknowledgement — Copier's Jinja context exposes the previous
  answers during `update`, so this needs no new mechanism, only a validator expression. Defense in
  depth: extend `_skip_if_exists` to also cover the root-level product-identity files
  (`AGENTS.md`, `CLAUDE.md`, `.gitignore`, root `package.json`) so that even a successful mode
  change doesn't silently clobber them; and have `doctor.py` flag (ERROR) when `.keelokit/`'s harness
  files (`.keelokit/bin/*.py`, `.keelokit/harness/*`) coexist with a full `apps/`/`packages/` tree
  but `answers.yml` still carries no memory of ever having been `mode=harness` — or, more simply,
  have `harness-upgrade`'s SKILL.md explicitly say, next to its existing local-`_src_path` warning:
  "never pass `--data mode=...` when updating an adopted project."

## Round 4 — Covered

- Rich fixture (`AGENTS.md`, `CLAUDE.md`, `.gitignore`, `docs/context/`, `CHANGELOG.md`,
  `package.json`) adopted at `v0.7.0`, updated to `v0.7.1`, hand-edited across all four
  `_skip_if_exists` `.keelokit/*.toml` files, committed, updated to HEAD (19b332e) — clean at every
  hop, `git status`/byte diffs confirm nothing outside `.keelokit/` was written and nothing was
  deleted, no `.rej` files, `mode: harness` and every hand-edit preserved verbatim.
- Confirmed *why* the v0.7.1→HEAD hop was a no-op for an adopted project: `template/` and
  `copier.yml` are byte-identical between `v0.7.1` and HEAD on this branch — the branch's own
  content additions never touch the Copier template.
- A genuine template-content-drift test (not available between real tags in this window): forced a
  synthetic upstream edit to a `_skip_if_exists` file (`profile.toml.jinja`) and to a non-protected
  one (`harness/rules.toml`) and updated against both — the protected edit never landed, the
  unprotected one did, both correct.
- The brief's explicit last instruction — an update that passes `--data mode=project` by mistake —
  run for real (not `--pretend`, which prints only the version line and no file-level detail) and
  found INT-301.

## Round 4 — Not covered

- Whether `/keelokit:harness-upgrade` as an **agent-run skill** (rather than the bare `copier`
  command) would ever actually type `--data mode=project` itself — SKILL.md's documented command
  doesn't include it, so this finding is about the absence of a guard against a human/agent mistake,
  not a claim that the skill's own instructions cause it.
- Whether the analogous mistake in the other direction (`--data mode=harness` on an already
  `mode=project` repo) is equally undefended — not attempted; by `_exclude`'s asymmetric structure
  (`mode=='harness'` excludes everything outside `.keelokit/`, so going *to* harness mode should at
  worst leave existing product files untouched rather than overwrite them) this direction looked
  lower-risk and was deprioritized in favor of fully evidencing the higher-risk direction.
- Concurrency between two chained `copier update` calls, or `project-adopt` racing `harness-upgrade`
  — not attempted (same gap round 2 already flagged as not covered).
- Whether `claude plugin install`'s own `/keelokit:harness-upgrade` invocation surfaces the
  `DirtyLocalWarning`/mode-mismatch output to the user in a way that would let them notice and abort
  before committing — only the bare `copier` CLI's stdout was inspected, not any wrapping the skill
  might do around it.
