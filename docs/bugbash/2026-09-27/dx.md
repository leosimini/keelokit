# dx

### DX-1 · doctor.py's own SessionStart message tells a Keelokit contributor to run a command that doesn't exist here (P2)
- **Persona / context:** Contributor / maintainer working in the Keelokit repo itself (this repo is self-adopted, `.keelokit/bin/doctor.py` exists at HEAD), any daily session. HEAD 19b332e, scratch clone.
- **Steps:**
  1. `git clone /home/user/keelokit <clone>` and confirm there is no `package.json` anywhere at the repo root: `ls package.json` → "No such file or directory".
  2. Run the exact SessionStart hook command from `hooks/hooks.json` against the clone: `python3 <clone>/.keelokit/bin/doctor.py --brief`.
  3. Read the last line of output.
- **Expected:** dimensions.md's dx row: "errors say what went wrong and how to fix it". The message printed is an actionable next step, so it should be a command that actually works in this repo (e.g. `python3 .keelokit/bin/doctor.py`, which is what AGENTS.md's own command table and this repo's Verify step use).
- **Observed:** `doctor.py --brief` prints `Harness errors: 16 — run `pnpm doctor`` — every single time a Claude Code session starts in this very repository (SessionStart hook), because `hooks/hooks.json` runs `doctor.py --brief` unconditionally whenever `.keelokit/bin/doctor.py` exists, which it does here (self-adoption commit `0e21e44`). Typing `pnpm doctor` in this repo fails immediately (`pnpm: command not found` in a repo with no `package.json`), because Keelokit itself is a plugin/template repo, not a generated pnpm project.
- **Evidence:**
  ```
  $ ls package.json
  ls: cannot access 'package.json': No such file or directory

  $ python3 .keelokit/bin/doctor.py --brief
  Keelokit: gate pending → intake
  Context gaps: 3 (0 blocking) · Backlog: 0/0 done
  Profile: plugin · 6 rules don't apply
  Harness errors: 16 — run `pnpm doctor`
  ```
  `diff .keelokit/bin/doctor.py template/.keelokit/bin/doctor.py` → identical: the same `"Harness errors: {n} — run \`pnpm doctor\`"` string (doctor.py:582) is baked into the project template's copy and blindly copied into this repo's own self-adoption, with nothing that adapts the hint to a repo whose own AGENTS.md commands table says `python3 -m unittest discover -s tests` / `python3 .keelokit/bin/doctor.py` and never mentions pnpm.
- **Where:** `.keelokit/bin/doctor.py:582` (and the identical `template/.keelokit/bin/doctor.py:582`); wired in by `hooks/hooks.json`'s `SessionStart` hook.
- **Root cause (probable):** the `--brief` hint is a template-wide constant written for generated/adopted *product* projects (which always have pnpm scripts), and self-adoption copies that file byte-for-byte into Keelokit's own repo without any per-project override — so the harness's own dogfooding session gets product-shaped advice.
- **Class:** consistency
- **Should have been caught by:** a doctor test or a bugbash pass run inside this repo's own checkout (not only inside fixtures) that checks `--brief`'s output for the actual repo it runs in; nothing currently exercises doctor.py's own hint text against a non-pnpm profile such as `plugin`.
- **Proposed fix:** key the hint off `profile.kind` (already loaded a few lines above as `profile`), e.g. `python3 .keelokit/bin/doctor.py` for `kind == "plugin"`/no `package.json`, `pnpm doctor` otherwise; or read the actual `doctor` script command from `package.json`'s `scripts.doctor` when present and fall back to the raw python invocation.

### DX-2 · dashboard.py silently renders a full, misleading dashboard for a `--root` that doesn't exist (P2)
- **Persona / context:** Anyone running the dashboard by hand with a typo'd or stale `--root` (the "Dashboard" journey; also how this bash's own isolation instructions run it: `dashboard.py --root <fixture>`). HEAD 19b332e, scratch clone.
- **Steps:**
  1. `python3 <clone>/skills/project-dashboard/scripts/dashboard.py --root /nonexistent/path/xyz --out dash1.html` → exit 0, no error on stdout/stderr.
  2. `python3 <clone>/skills/project-dashboard/scripts/dashboard.py --root <a plain empty dir, no .keelokit> --out dash2.html` → exit 0, no error either.
  3. Diff the two outputs and inspect `dash1.html`.
- **Expected:** dimensions.md's dx row: "wrong input on every command... defaults are safe". A `--root` that does not exist on disk is a plainly wrong input distinct from "a fresh/greenfield project" — the tool should say so (or at minimum warn), not fabricate a project page for a place that was never there.
- **Observed:** Both calls exit 0 and produce a byte-for-byte-structurally-identical 344-line HTML dashboard titled "xyz dashboard" / "plaindir dashboard" (the basename of whatever path was given), showing stage "01 Context" as "In progress" with "0 documents · 0 open questions" — i.e. a normal "brand-new greenfield product" dashboard, with nothing anywhere on the page indicating the directory doesn't exist at all.
- **Evidence:**
  ```
  $ python3 skills/project-dashboard/scripts/dashboard.py --root /nonexistent/path/xyz --out /tmp/dash1.html; echo $?
  /tmp/dash1.html
  0
  $ grep -io 'error\|missing\|not found' /tmp/dash1.html
  (no matches other than the unrelated word "error" inside an inline SVG id)
  $ grep -o '<title>[^<]*' /tmp/dash1.html
  <title>xyz dashboard
  ```
  `read()` at `skills/project-dashboard/scripts/dashboard.py:548-552` catches `OSError` (which includes a missing directory) and returns `""` for every file read, and `find_root`/`collect()` never call `root.is_dir()` or similar before proceeding — a nonexistent root is treated exactly like an existing-but-empty one.
- **Where:** `skills/project-dashboard/scripts/dashboard.py:548-552` (`read`), `:1913` (`root = (args.root or find_root(Path.cwd())).resolve()` — no existence check before use).
- **Root cause (probable):** every file access in `collect()` goes through `read()`/`.exists()` checks that were written to tolerate a fresh project with no files yet, so they can't distinguish "this file doesn't exist in a real project" from "this whole directory doesn't exist".
- **Class:** consistency
- **Should have been caught by:** a CLI-level input check (`argparse` `type=` or an explicit `if not root.is_dir(): sys.exit(...)`) with a test asserting non-zero exit and a clear stderr message for a missing `--root`; no such test exists in the repo.
- **Proposed fix:** right after resolving `root`, check `root.is_dir()` (and ideally that either `.git` or `.keelokit` or `docs/` exists) and exit non-zero with a clear message ("`--root <path>` does not exist") instead of proceeding into `collect()`.

### DX-3 · test-template.sh's `--update-from` swallows the next flag as the tag, surfacing a three-layer-deep Python traceback instead of a script error (P2)
- **Persona / context:** Contributor exercising `scripts/test-template.sh` per AGENTS.md's command table, flags given in an unexpected order (e.g. `--update-from --postgis` instead of `--postgis --update-from v0.7.0`). HEAD 19b332e, scratch clone, no push/tag/version changes.
- **Steps:**
  1. `scripts/test-template.sh '["api"]' --update-from --postgis` (real exit code captured via a redirected log file, not a pipe, to avoid losing it to `tail`).
  2. Read the tail of the output and the real exit code.
- **Expected:** the script's own pattern for the *missing*-argument case is a clear, one-line, script-level message: `scripts/test-template.sh: line 17: 2: --update-from needs a tag` (verified separately, works well). The same care should apply when the value taken is itself clearly a flag.
- **Observed:** `from=${2:?--update-from needs a tag}; shift` only checks that *some* value exists, not that it looks like a tag rather than another flag. `--postgis` is silently consumed as the git ref/tag for `--update-from`, `postgis` itself stays `false`, and the script goes on to run `copier copy --vcs-ref --postgis ...`, which fails four calls deep with a raw `plumbum`/`copier` Python traceback ending in `error: unknown option \`postgis'` and a full `git checkout` usage dump, rather than anything naming `test-template.sh` or `--update-from`.
- **Evidence:**
  ```
  $ scripts/test-template.sh '["api"]' --update-from --postgis < /dev/null > /tmp/out1.log 2>&1
  $ echo $?
  1
  $ tail -12 /tmp/out1.log
    File ".../copier/_main.py", line 1780, in run_copy
      worker.run_copy()
    ...
  plumbum.commands.processes.ProcessExecutionError: Unexpected exit code: 129
  Command line: | /usr/bin/git -c core.fsmonitor=false checkout -f --postgis
  Stderr:       | error: unknown option `postgis'
  usage: git checkout [<options>] <branch>
    ...
  ```
- **Where:** `scripts/test-template.sh:17` (`--update-from) from=${2:?--update-from needs a tag}; shift ;;`).
- **Root cause (probable):** the `${2:?...}` guard only checks for a present argument, not that it doesn't itself start with `-`; combined with `-*) echo "unknown option: $1" >&2; exit 2 ;;` never getting a chance to see `--postgis` because it was already consumed as `$2` of the previous case.
- **Class:** consistency
- **Should have been caught by:** the same category of test that already exercises the "no tag given" case, extended to "the next token looks like a flag" (`case ${2:-} in -*|"") fail ... ;; esac`), with a unit/CI check on the script's own argument parsing (currently there is none — only generated-project behavior is tested).
- **Proposed fix:** validate the token consumed by `--update-from` doesn't start with `-` (e.g. `case ${2:-} in ''|-*) fail "--update-from needs a tag" ;; esac`) and fail with the same one-line style as the missing-argument case.

### DX-4 · A project name that starts with a digit (e.g. "3D Store") crashes `/keelokit:project-new`'s copier step with a raw traceback (P1)
- **Persona / context:** Newcomer founder following the README/`project-new` "Try it" flow with a plausible product name; also directly matches the focus item "the `project_slug` validator (a name with accents, starting with a digit)". HEAD 19b332e, scratch clone.
- **Steps:**
  1. `copier.yml`'s `project_slug` default derives from `project_name` via `regex_replace('[^a-z0-9]+', '-')`, which does **not** strip a leading digit, while its own `validator` requires `^[a-z][a-z0-9-]*$` (must start with a letter).
  2. Reproduce exactly the invocation `skills/project-new/SKILL.md:130` documents (explicit `--data project_slug=...` alongside `--data project_name=...`), with a name/slug a real newcomer could give: `uvx copier==9.18.2 copy --vcs-ref HEAD --defaults --data 'project_name=3D Store' --data 'project_slug=3d-store' --data description=x --data 'apps=[api]' --data postgis=false <clone> <dir>`.
  3. Also reproduce via the *default*-derivation path alone (no explicit `project_slug`): `--data 'project_name=3D Store'` with `--defaults`.
- **Expected:** README's "Try it" / `project-new`'s documented flow promises "copier copy ... → `pnpm install` → `pnpm verify --all` green" — i.e. a working skeleton for any product name a founder types in the intake conversation. At minimum, a validation failure on a very ordinary business name should surface a clear, actionable Keelokit-level message ("the slug can't start with a digit — try `store-3d`"), not a raw internal stack trace.
- **Observed:** both invocations crash with an **uncaught Python traceback** from `copier`'s own internals (`ValueError: Validation error for question 'project_slug': lowercase letters, digits and dashes`), non-zero exit, no Keelokit-specific message anywhere, and nothing in `copier.yml` or `skills/project-new/SKILL.md` warns that the slug (whether auto-derived or explicitly chosen by the agent during intake) must not start with a digit.
- **Evidence:**
  ```
  $ uvx copier==9.18.2 copy --vcs-ref HEAD --defaults --data 'project_name=3D Store' \
      --data 'project_slug=3d-store' --data description=x --data 'apps=[api]' --data postgis=false <clone> <dir>
  ...
    File ".../copier/_user_data.py", line 465, in validate_answer
      raise ValueError(
  ValueError: Validation error for question 'project_slug': lowercase letters, digits and dashes
  $ echo $?
  1
  ```
  Same crash (via `get_default()` instead of `validate_answer()`) when only `project_name=3D Store` is given and `project_slug` is left to its computed default.
- **Where:** `copier.yml:83-87` (`project_slug`'s `default:` regex and `validator:`); consumed as documented by `skills/project-new/SKILL.md:126-131`.
- **Root cause (probable):** the default-slug regex only strips characters outside `[a-z0-9]`, so a name that is digit-first (very common for products — "3D Store", "24/7 Clinic", "7 Waves Surf") yields a digit-first slug that the very same file's validator then rejects; there is no re-prompt path in the non-interactive `--defaults`/`--data` mode Keelokit always uses, so the failure is fatal rather than recoverable.
- **Class:** consistency
- **Should have been caught by:** a copier-level test (or the existing `scripts/test-template.sh`, which always passes a safe hard-coded `project_name=Demo`) covering a digit-led product name; none of the template tests vary `project_name`.
- **Proposed fix:** either prefix a fallback letter when the stripped name starts with a digit (e.g. `'p-' ~ ... if slug starts with digit`) in the default-derivation Jinja, or have `SKILL.md` instruct the agent to validate/normalise the slug itself (strip/prefix leading digits) before calling copier, and note the constraint explicitly next to the `--data project_slug=` line.

### DX-5 · Accented project names produce a mangled slug instead of a transliterated one (P3)
- **Persona / context:** Spanish-speaking founder naming a product with an accented word (e.g. "Peña S.A."). HEAD 19b332e, scratch clone.
- **Steps:** `uvx copier==9.18.2 copy --vcs-ref HEAD --defaults --data 'project_name=Peña S.A.' --data description=x --data 'apps=[api]' --data postgis=false <clone> <dir>`.
- **Expected:** a readable, recognisable slug derived from the name (e.g. `pena-s-a`), matching the "defaults are safe" / usable-by-default bar for a product whose whole point is Spanish-language support (this repo's own `.keelokit/state.toml` sets `lang=es`).
- **Observed:** the generated `.keelokit/answers.yml` records `project_slug: pe-a-s-a` — the `ñ` is dropped outright rather than folded to `n`, producing a slug that reads as "pe-a" rather than anything resembling "Peña". The command does succeed (exit 0), so this is a quality/consistency issue, not a crash.
- **Evidence:**
  ```
  $ cat <dir>/.keelokit/answers.yml | grep slug
  project_slug: pe-a-s-a
  ```
- **Where:** `copier.yml:86` (`default: "{{ project_name | lower | regex_replace('[^a-z0-9]+', '-') | regex_replace('^-+|-+$', '') }}"` — no accent-folding step before stripping non-ASCII characters).
- **Root cause (probable):** the regex strips any character outside `[a-z0-9]` including accented letters, instead of first normalising them to their base Latin letter (`ñ`→`n`, `í`→`i`, etc.).
- **Class:** consistency
- **Should have been caught by:** a template test with an accented `project_name`; none exists.
- **Proposed fix:** add a Unicode-normalisation step (NFKD + strip combining marks) before the existing regex in the `project_slug` default, so `ñ`→`n`, `í`→`i`, etc., survive into the slug.

### DX-6 · guard.py silently does nothing — exit 0, zero output — for any invocation that isn't exactly `--claude` or `git-pre-commit` (P2)
- **Persona / context:** Anyone wiring or debugging the guard by hand — a contributor testing it, or a maintainer adapting `hooks/hooks.json`/the git hook scripts with a typo. HEAD 19b332e, scratch clone.
- **Steps:** run `python3 .keelokit/bin/guard.py` with, respectively: no arguments; `--help`; `claude` (missing the leading `--`); `--Claude` (wrong case); `--bogus-mode`.
- **Expected:** dimensions.md's dx row: "commands ... do what their names say ... errors say what went wrong". A speed-bump security tool that receives an argument it doesn't recognise should say so (even a one-line "unknown mode, use --claude or git-pre-commit"), especially since its own docstring documents exactly two modes and nothing else.
- **Observed:** every one of the five invocations above exits **0** with **no output whatsoever** — identical to a fully successful, permissive run. `main()`'s dispatch (`sys.exit(claude() if mode == "--claude" else git_pre_commit() if mode == "git-pre-commit" else 0)`) has no `else` branch that reports anything; any other string for `mode` (including empty, a typo, or wrong case) falls straight through to `0`.
- **Evidence:**
  ```
  $ python3 .keelokit/bin/guard.py; echo $?
  0
  $ python3 .keelokit/bin/guard.py --help; echo $?
  0
  $ python3 .keelokit/bin/guard.py claude < /dev/null; echo $?
  0
  $ echo '{}' | python3 .keelokit/bin/guard.py --Claude; echo $?
  0
  $ python3 .keelokit/bin/guard.py --bogus-mode; echo $?
  0
  ```
- **Where:** `.keelokit/bin/guard.py:206` (`sys.exit(claude() if mode == "--claude" else git_pre_commit() if mode == "git-pre-commit" else 0)`), identically in `template/.keelokit/bin/guard.py:206`.
- **Root cause (probable):** manual `sys.argv[1]` dispatch with no `else`/unknown-mode branch, mirroring the same pattern in `doctor.py`'s `main()` (see `doctor.py --help`/`--unknown-flag`, which instead runs the *full* check rather than nothing — the two scripts fail differently on the same class of input).
- **Class:** consistency
- **Should have been caught by:** a unit test asserting a non-zero exit and a message for an unrecognised `sys.argv[1]`; `tests/test_guard.py` only exercises the two documented modes.
- **Proposed fix:** add an explicit branch for any `mode` other than the two known ones that prints `Keelokit guard: unknown mode '<mode>' (use --claude or git-pre-commit)` to stderr and exits non-zero, so a misconfigured or mistyped hook is loud instead of silently permissive.

### DX-7 · Missing python3 degrades gracefully only in the SessionStart hook — the PreToolUse guard and the git hooks fail with a raw shell error instead (P2)
- **Persona / context:** Any machine/container that has Claude Code but not Python 3.11+ installed yet (a plausible early state before `README`'s prerequisite step completes) — the same documented scenario the focus item asks to try. HEAD 19b332e, scratch clone.
- **Steps:**
  1. Build a `PATH` with no `python3` on it (only `bash`, `git`, etc.).
  2. Run the exact `SessionStart` command from `hooks/hooks.json`: `command -v python3 >/dev/null || { echo 'Keelokit: python3 not found...'; exit 0; }; python3 "$f" --brief; exit 0` → clean, friendly message, exit 0.
  3. Run the exact `PreToolUse` command from the same file: `f="$CLAUDE_PROJECT_DIR/.keelokit/bin/guard.py"; [ -f "$f" ] && exec python3 "$f" --claude; exit 0`.
  4. Run the git pre-commit hook shipped in the template: `exec python3 .keelokit/bin/guard.py git-pre-commit`.
- **Expected:** the same documented degradation as the SessionStart hook ("tells the user python3 is missing", per this bash's own focus item) applied consistently to every entry point that shells out to `python3`, since all three exist to protect the same journey.
- **Observed:** the `PreToolUse` command has no `command -v python3` guard before its `exec`, so with no `python3` on `PATH` it fails with `bash: line 1: exec: python3: not found`, exit code **127** — the guard produces zero Keelokit-branded message; per Claude Code's PreToolUse hook contract a non-{0,2} exit is a non-blocking error shown to the user, so the person sees a bare, confusing shell error instead of "install Python 3.11+". The git pre-commit hook (`template/.githooks/pre-commit`) has the identical gap: `exec python3 .keelokit/bin/guard.py git-pre-commit` with no `python3` on `PATH` also fails with the same raw `exec: python3: not found`, and (unlike PreToolUse) this one actually **blocks the commit**, with no explanation of why.
- **Evidence:**
  ```
  $ PATH=<dir with no python3> bash -c 'f=".../guard.py"; [ -f "$f" ] && exec python3 "$f" --claude; exit 0' <<<'{"tool_name":"Bash","tool_input":{"command":"ls"}}'
  bash: line 1: exec: python3: not found
  $ echo $?
  127
  ```
  Compare with the SessionStart command run under the identical `PATH`, which prints `Keelokit: python3 not found, so the guard and doctor are off. Install Python 3.11+.` and exits 0.
- **Where:** `hooks/hooks.json` (`PreToolUse` command, no `command -v python3` guard, unlike its own `SessionStart` entry two blocks below it); `template/.githooks/pre-commit` and `template/.githooks/pre-push` (same pattern, no guard).
- **Root cause (probable):** the `command -v python3 || …` guard was added only to the `SessionStart` hook command, and never carried over to the `PreToolUse` hook or to the `.githooks/*` scripts that invoke `python3` the same way.
- **Class:** consistency
- **Should have been caught by:** a test running the literal `PreToolUse`/git-hook command strings from `hooks/hooks.json` and `template/.githooks/*` (not just calling `guard.py` directly) under a `PATH` without `python3`; no such test exists — `tests/` only imports/calls `guard.py` in-process.
- **Proposed fix:** add the same `command -v python3 >/dev/null || { echo '...'; exit 0; }` (or `exit 1` for the git hooks, since blocking is appropriate there but the message shouldn't be blank) guard to the `PreToolUse` command and to `template/.githooks/pre-commit`/`pre-push` before their `exec python3 ...`.

### DX-8 · `doctor.py --scope` with no ID produces a malformed, double-spaced message instead of naming the missing argument (P3)
- **Persona / context:** Developer running `/keelokit:check-health`'s `--scope <ID>` mode and forgetting the ID. HEAD 19b332e, scratch clone.
- **Steps:** `python3 .keelokit/bin/doctor.py --scope` (no further argument).
- **Expected:** per the script's own usage docstring ("`--scope ID` files changed on this branch..."), a missing ID should be called out by name, e.g. "usage: doctor.py --scope ID".
- **Observed:** prints `No story  in backlog/stories` (note the double space where the ID would be) and exits 1 — technically correct (nothing matches an empty ID) but reads as a rendering bug rather than a "you forgot the ID" message.
- **Evidence:**
  ```
  $ python3 .keelokit/bin/doctor.py --scope; echo $?
  No story  in backlog/stories
  1
  ```
- **Where:** `.keelokit/bin/doctor.py:541-543` (`if mode == "--scope": return check_scope(sys.argv[2] if len(sys.argv) > 2 else "")`) and `:500-502` inside `check_scope` (`if sid not in stories: print(f"No story {sid} in backlog/stories")`).
- **Root cause (probable):** `main()` passes `""` for a missing `--scope` argument straight into `check_scope`, which has no special case for an empty `sid` and just interpolates it into its generic "no such story" message.
- **Class:** consistency
- **Should have been caught by:** a unit test calling `check_scope("")` or running `doctor.py --scope` with no ID; `tests/` currently only exercises `--scope` with a real or a garbage-but-nonempty ID.
- **Proposed fix:** in `main()`, when `--scope` has no following argument, print a one-line usage message ("usage: doctor.py --scope ID") and return 2, instead of calling `check_scope("")`.
