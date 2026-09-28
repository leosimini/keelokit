# logic

### LOG-1 · TAMPER patterns (skipped tests, eslint-disable, ts-ignore) are never checked for Bash-written files (P2)
- **Persona / context:** An agent inside a Keelokit project trying to get past the guard (the INV-002/QA-4 adversary), HEAD 19b332e, scratch clone.
- **Steps:**
  1. `python3 .keelokit/bin/guard.py --claude` with a PreToolUse `Edit` event whose `new_string` is `it.skip("x", () => {})` on `a.test.ts` → blocked (exit 2), as expected.
  2. Same payload delivered instead as a `Bash` PreToolUse event: `{"tool_name":"Bash","tool_input":{"command":"echo 'it.skip(x)' >> src/foo.test.ts"}}` → exit 0 (passes).
  3. Same again via a heredoc: `cat >> src/foo.test.ts <<'EOF'\nit.skip("x", () => {})\nEOF` → exit 0 (passes).
  4. Same for an `eslint-disable` comment added with `sed -i "1i // eslint-disable" src/foo.ts` → exit 0 (passes).
- **Expected:** AGENTS.md / the daily-agent journey: "PreToolUse guard blocks secrets, skipped/focused tests, eslint-disable, --no-verify, hooksPath overrides and force-push" — no qualification that this only holds for Edit/Write tool calls. `bash_problem()` already re-implements the SECRETS and GIT_NO_HOOKS checks for Bash commands, so the same treatment is expected for TAMPER (QA-4).
- **Observed:** `bash_problem()` (guard.py:105-133) never calls `tamper_in()` — it only checks `GIT_NO_HOOKS`, `secret_in()`, and the env-file/migration `WRITE_CMD` logic. `tamper_in()` is only invoked from `claude()` for the non-Bash branch (edit_payload of Edit/Write/MultiEdit/NotebookEdit). Any of `it.skip`, `xit(`, `eslint-disable`, `@ts-ignore`/`@ts-nocheck`, `continue-on-error: true` written via `Bash` (echo, heredoc, `sed -i`, `tee`, etc.) sails through the PreToolUse hook untouched.
- **Evidence:**
  ```
  $ echo '{"tool_name":"Edit","tool_input":{"file_path":"a.test.ts","new_string":"it.skip(\"x\", () => {})"}}' | python3 .keelokit/bin/guard.py --claude
  Blocked by Keelokit — QA-4: a skipped or focused test needs the human's yes — ask in chat, don't silence the check
  exit=2

  $ echo '{"tool_name":"Bash","tool_input":{"command":"echo '"'"'it.skip(x)'"'"' >> src/foo.test.ts"}}' | python3 .keelokit/bin/guard.py --claude
  exit=0

  $ echo '{"tool_name":"Bash","tool_input":{"command":"sed -i \"1i // eslint-disable\" src/foo.ts"}}' | python3 .keelokit/bin/guard.py --claude
  exit=0
  ```
  I confirmed the git-pre-commit hook *does* still catch the same content once staged (backstop works): in a scratch repo, `cat >> a.test.ts <<'EOF'\nit.skip("bad", () => {})\nEOF && git add a.test.ts && python3 .keelokit/bin/guard.py git-pre-commit` → `✖ QA-4: a.test.ts adds a skipped or focused test.` exit 1. So the gap is specifically at write-time, in the PreToolUse hook.
- **Where:** `.keelokit/bin/guard.py:105-133` (`bash_problem`), and identically `template/.keelokit/bin/guard.py:105-133`.
- **Root cause (probable):** `bash_problem()` was written to catch secrets and git-hook bypasses in Bash commands but the TAMPER list was wired only into the Edit/Write branch of `claude()`, not into `bash_problem()`.
- **Class:** consistency
- **Should have been caught by:** a unit test in `tests/test_guard.py` asserting the guard blocks a `Bash` command that writes `it.skip(`/`eslint-disable`/`@ts-ignore` to a tracked file — `tests/test_guard.py` currently only exercises `tamper_in` through Edit/Write-shaped events (grep shows no Bash+TAMPER case).
- **Proposed fix:** in `bash_problem()`, after extracting the write targets for `WRITE_CMD` segments, also scan the segment's literal text (or, better, run `tamper_in()` against `unquoted(cmd)`) and return the same QA-4 message when a TAMPER pattern is present outside `.keelokit/`/`*.md`, mirroring how `secret_in(cmd)` is already checked unconditionally at the end of `bash_problem()`.

### LOG-2 · A malformed exception `expires` date crashes doctor.py entirely, in every mode including `--brief` (P2)
- **Persona / context:** Any Keelokit project with `.keelokit/exceptions.toml`; specifically the "daily agent session" journey where `doctor.py --brief` runs from the SessionStart hook. HEAD 19b332e, scratch fixture.
- **Steps:**
  1. Build a minimal harness fixture with one MUST rule and no enforcer, plus `.keelokit/exceptions.toml`:
     ```
     [[exception]]
     rule = "R-1"
     reason = "testing bad date"
     approver = "Leo"
     expires = "not-a-date"
     ```
  2. Run `python3 .keelokit/bin/doctor.py`, `--ci`, and `--brief` from that fixture's root.
- **Expected:** Per the docstring, "exceptions are complete and not expired" is a check that should surface as a normal `errors.append(...)` line like the existing "missing rule/reason/approver/expires" check three lines above it (`check_exceptions`, doctor.py:216-219) — a bad date is exactly as much a malformed exception as a missing field. The SessionStart-hook path (`--brief`) in particular must never show a raw traceback to the human/agent; `--brief` is documented as the "where am I / what's next" summary.
- **Observed:** All three modes raise an unhandled `ValueError: Invalid isoformat string: 'not-a-date'` from `dt.date.fromisoformat(expires)` and dump a Python traceback to stderr; nothing about rules, backlog, or context is ever reported because the crash happens before any of that runs. This is strictly worse than the "16 ERRORs" baseline state — instead of a report, the operator gets a traceback.
- **Evidence:**
  ```
  $ python3 .keelokit/bin/doctor.py --brief
  Traceback (most recent call last):
    ...
    File ".../doctor.py", line 559, in main
      check_rules(rules, check_exceptions(set(rules)), profile)
                         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    File ".../doctor.py", line 225, in check_exceptions
      expires = dt.date.fromisoformat(expires)
                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  ValueError: Invalid isoformat string: 'not-a-date'
  ```
  Same traceback, same line, for plain `doctor.py` and `doctor.py --ci`. For comparison, a value that is TOML's native unquoted date type (`expires = 2026-01-01`), `"permanent"`, a past date ("2020-01-01", correctly reported as `expired on 2020-01-01`), and a date equal to today (correctly kept active as a warning) all work without crashing — only a syntactically-invalid *string* crashes.
- **Where:** `.keelokit/bin/doctor.py:222-227` (`check_exceptions`), identical in `template/.keelokit/bin/doctor.py`.
- **Root cause (probable):** `dt.date.fromisoformat(expires)` is called unguarded; every other malformed-input case in this function (missing keys, unknown rule id) is handled with an `errors.append(...)` + `continue`, but an unparseable date string is not.
- **Class:** consistency
- **Should have been caught by:** a unit test in `tests/test_doctor.py` for `check_exceptions` with a bad `expires` string (the existing tests only cover missing fields and a far-future date — `tests/test_doctor.py:121` — never a malformed one, per the earlier grep for `fromisoformat`/`expire`).
- **Proposed fix:** wrap the parse in try/except and append `f"exception for {rid}: 'expires' is not a valid date or 'permanent' ({expires!r})"` then `continue`, the same way the missing-field branch does two lines above.

### LOG-3 · `rm`/`touch` of an `.env` file is blocked with a "don't write" message that doesn't fit the action (P3)
- **Persona / context:** Daily agent session doing routine cleanup (e.g. removing a stray generated `.env` before a fresh `pnpm install`). HEAD 19b332e.
- **Steps:**
  1. `echo '{"tool_name":"Bash","tool_input":{"command":"rm apps/api/.env"}}' | python3 .keelokit/bin/guard.py --claude`
  2. `echo '{"tool_name":"Bash","tool_input":{"command":"touch apps/api/.env"}}' | python3 .keelokit/bin/guard.py --claude`
- **Expected:** SEC-2 is about not leaking secrets into `.env`/committing them (`enforced_by` and the rule text in `rules.toml` talk about writing real values from the shell); deleting or touching (0 bytes, no content) a `.env` file writes no secret and shouldn't trigger a "don't write .env files … real values go in the secret store" message, which is actively misleading for a deletion.
- **Observed:** Both commands are blocked (exit 2) with `SEC-2: don't write .env files from the shell; edit .env.example, real values go in the secret store`. The message talks about writing/editing, but the action was a deletion or a no-content touch.
- **Evidence:**
  ```
  $ echo '{"tool_name":"Bash","tool_input":{"command":"rm apps/api/.env"}}' | python3 .keelokit/bin/guard.py --claude
  Blocked by Keelokit — SEC-2: don't write .env files from the shell; edit .env.example, real values go in the secret store
  exit=2
  ```
- **Where:** `.keelokit/bin/guard.py:59` (`WRITE_CMD` includes `\brm\b`/`\btouch\b`) and `:122-128` (`bash_problem`, the `is_env_file(t)` check applies uniformly to every `WRITE_CMD` match without distinguishing delete/touch from actual content-writing commands like `>`, `tee`, `cp`, `sed -i`).
- **Root cause (probable):** `WRITE_CMD` bundles content-writing commands together with `rm`/`touch`/`ln` (which don't write file *content*) and applies the same "don't write .env files" message to all of them.
- **Class:** consistency
- **Should have been caught by:** a guard test distinguishing "blocks writing secrets into .env" from "blocks deleting .env" — `tests/test_guard.py` doesn't currently separate these two behaviors or check the message text for `rm`.
- **Proposed fix:** either keep blocking `rm`/`touch` of `.env` (arguably a legitimate belt-and-suspenders policy) but give it its own message ("don't delete/touch `.env` from the shell either — ask a human"), or drop `rm`/`touch`/`ln` from the set of commands that trigger the env-file check, keeping it only for content-writing commands (`>`, `>>`, `tee`, `cp`, `sed -i`, `perl -i`).

### LOG-4 · Guard's `commit -n` detector is a substring match on the letter "n", blocking legitimate flags like `-uno` (P2)
- **Persona / context:** Daily agent session running an ordinary `git commit` with a common short flag. HEAD 19b332e.
- **Steps:**
  1. `echo '{"tool_name":"Bash","tool_input":{"command":"git commit -uno -m \"quick commit\""}}' | python3 .keelokit/bin/guard.py --claude`
  2. Compare with the long-form equivalent: `git commit --untracked-files=no -m "quick commit"` (passes, exit 0).
- **Expected:** `-uno` is documented git shorthand for `--untracked-files=no` and has nothing to do with skipping hooks; only `-n`/`--no-verify` (and `-n` combined with other single-letter flags, e.g. `-na`) should trip QA-2's "commit -n skips the git hooks" rule.
- **Observed:** `git commit -uno -m "quick commit"` is blocked with `QA-2: \`commit -n\` skips the git hooks` (exit 2), purely because the flag token contains the letter "n" somewhere. The long-form spelling of the exact same operation is allowed through.
- **Evidence:**
  ```
  $ echo '{"tool_name":"Bash","tool_input":{"command":"git commit -uno -m \"quick commit\""}}' | python3 .keelokit/bin/guard.py --claude
  Blocked by Keelokit — QA-2: `commit -n` skips the git hooks
  exit=2

  $ echo '{"tool_name":"Bash","tool_input":{"command":"git commit --untracked-files=no -m \"quick commit\""}}' | python3 .keelokit/bin/guard.py --claude
  exit=0
  ```
- **Where:** `.keelokit/bin/guard.py:52`, the pattern `r"\bgit\b(\s+-[^c]\S*)*\s+commit\b[^|;&]*\s-[a-zA-Z]*n[a-zA-Z]*\b"`. The `[a-zA-Z]*n[a-zA-Z]*` class matches any single-dash flag that merely contains an "n" anywhere (`-uno`, `-unormal`, and similarly any other short flag combo spelling out a word with an "n" in it), not specifically `-n`.
- **Root cause (probable):** The regex was meant to catch bundled short flags like `-na`/`-an` (where one of the letters is literally `n`, i.e. `--no-verify`'s `-n`), but `[a-zA-Z]*n[a-zA-Z]*` is a substring match rather than "one of the flag's letters, each independently a known short option, is exactly n".
- **Class:** consistency
- **Should have been caught by:** `tests/test_guard.py`'s false-positive cases for GIT_NO_HOOKS — the suite already has near-miss cases (per the lens brief) but not one for a real git short flag that happens to contain "n" (`-uno` is a real, git-documented value).
- **Proposed fix:** stop matching "any single-dash token containing the letter n" and instead only flag a token that is `-n` on its own, or `-n` bundled purely with other known no-argument short options for `git commit` (e.g. `a`, `e`, `q`, `s`, `v`), such as `-na`/`-an`. A flag carrying letters that only make sense as part of a word (`u`, `o`, `l`, …, as in `-uno`/`-unormal`) should not match. Concretely, reject the flag unless every character after the leading `-` is drawn from a small allow-list of single-letter options that includes `n`, rather than the current `[a-zA-Z]*n[a-zA-Z]*` substring match.

### LOG-101 · A fixer that "doesn't return" skips its independent check and undo path entirely, so a partially-edited working tree is never reverted (P1)
- **Persona / context:** Maintainer running `/keelokit:check-bugbash` with fixes on (`fix: true`), where the Fix phase's `agent()` fixer call for a root cause dies on a terminal API error or is skipped mid-run — the Workflow-authoring contract says `agent()` then resolves to `null`. HEAD 19b332e, `workflows/check-bugbash-flow.js`.
- **Steps:**
  1. Drove the workflow body directly under Node with a stubbed `agent`/`phase`/`pipeline`/`args` API (per the Workflow-authoring script contract), reproducing the real hooks' signatures.
  2. Ran one full Prepare→Survey→Validate→Consolidate→Fix→Report pass with 2 lenses, `fix: true`, `rounds: 1`, and 3 confirmed findings grouped into 3 root causes: one whose fixer's independent check is rejected twice (LOG-1-style), one whose fixer `agent()` call for `fix SEC-1` resolves to `null` (SEC-1-style), and one sized `story` (LOG-2-style).
  3. Captured every `agent()` call's label/phase/order.
- **Expected:** Per the code's own model (lines 271-329), a fixer that fails should either succeed a re-check, or be actively reverted: "if every commit in `git log fixed.base..HEAD` is a fix for `g.id`, run `git reset --hard fixed.base`; otherwise revert only the `g.id` commits" (the undo agent's own instructions, line ~321). That safety net is what makes it safe to run several fixes back-to-back on the same branch with `fix: true`.
- **Observed:** When the fixer call for `SEC-1` resolved to `null`, the loop hit `if (!fixed || fixed.status !== 'fixed') break` on attempt 1 and exited immediately — **no `check fix SEC-1` call, and no `undo SEC-1` call, ever fired.** The group was simply recorded as `{status:'open', notes:'the fixer did not return'}` and the Fix loop moved on to the next group. Unlike the "rejected twice" path (which explicitly resets/reverts via `git log fixed.base..HEAD`), there is no code path at all that inspects or cleans the working tree when the fixer itself never returned. If that fixer had already made file edits or an uncommitted/uncomitted-but-staged change before dying (a live possibility — "dies on a terminal API error after retries" says nothing about how far into its own steps it got), those changes are left in the tree with nothing that ever runs `git status`/`git reset` against them, and the very next group's fixer (`fix LOG-1`) then runs "Note `git rev-parse HEAD` first (return it as base)" against that same, potentially dirty, working tree.
- **Evidence:**
  ```
  $ node scenario-a.mjs        # harness: workflows/check-bugbash-flow.js body run verbatim under Node
  ...
  9 fix SEC-1 | Fix | model= null | resultKind= null      # fixer resolves to null
                                                            # <- no "check fix SEC-1" call follows
                                                            # <- no "undo SEC-1" call follows
  10 fix LOG-1 | Fix | model= null | resultKind= object    # next group's fixer starts immediately
  ...
  RESULT.open = [
    { "id": "SEC-1", "severity": "P0", "title": "fixer never returns", "notes": "the fixer did not return" },
    { "id": "LOG-1", "severity": "P1", "title": "fixer rejected twice",
      "notes": "attempt 2 — rejected and undone: rejected attempt 2: test still fails with the fix" }
  ]
  ```
  Harness: `harness.mjs` loads `workflows/check-bugbash-flow.js`'s body verbatim (same meta-stripping regex as `tests/test_workflows.py`) into an `AsyncFunction(agent, parallel, pipeline, phase, log, args, budget, workflow, BODY)` and runs it with a stubbed `agent()`; scenario in `scenario-a.mjs` (both under the session scratchpad, `wf-logic/`). LOG-1's own path in the same run *does* show the designed safety net firing (`check fix LOG-1` called twice, then `undo LOG-1`), confirming the asymmetry is specific to the "fixer never returns" branch, not a harness artifact.
- **Where:** `workflows/check-bugbash-flow.js:286-301` (the `for (attempt...)` loop: `fixed = await agent(...)`; `if (!fixed || fixed.status !== 'fixed') break`) and `:327` (`results.push({ ...g, ...(fixed || {status:'open', ...}) })`) — no `git`/undo instruction is ever issued on this branch, in contrast to `:319-325`.
- **Root cause (probable):** The undo/revert safety net was written only for the "fixer returned but was rejected by the independent check" case (which has a `fixed.base` and a `fixed.commit` to reason about); the `!fixed` case (fixer died or was skipped) was treated as equivalent to "no-op", but a dead fixer can still have mutated the working tree before dying, and nothing resets it.
- **Class:** isolation
- **Should have been caught by:** a workflow-level test that stubs a fixer `agent()` call resolving to `null` and asserts the working tree/branch is left exactly as it was (or is verified clean) before the loop proceeds to the next group — no such test exists for `check-bugbash-flow.js` (`tests/test_workflows.py` only checks the script's static shape, not its runtime branching).
- **Proposed fix:** when `fixed` is falsy, still note `git rev-parse HEAD` *before* the fix attempt (not just inside the fixer's own prompt) so the harness itself can run a defensive `git reset --hard <pre-attempt HEAD>` (or at minimum `git status --porcelain` and abort loudly) before moving to the next group, instead of trusting a fixer that never got the chance to report its own base.

### LOG-102 · `rounds: 0` in `args` is indistinguishable from "not set" — a caller cannot ask for zero extra survey rounds (P2)
- **Persona / context:** `/keelokit:check-bugbash` invoked (or scripted) with `args: {rounds: 0}` — e.g. a maintainer wanting exactly one survey pass with no coverage-gap rounds. HEAD 19b332e.
- **Steps:** Ran the workflow body with `args = {scope: 'incremental', rounds: 0}` and a coverage critic stubbed to always return one more task (so the loop would keep going if it weren't dry), counting how many Survey-phase rounds actually ran.
- **Expected:** `rounds` is documented in the file's own header comment (`// args (all optional): {..., rounds, ...}`) as a plain optional numeric override; `0` is a valid integer and the natural way to ask for "just the first pass, no gap-filling".
- **Observed:** `const rounds = A.rounds || (plan.scope === 'full' ? 3 : 2)` (line 168) uses `||`, so `A.rounds = 0` is falsy and silently replaced by the scope default. With `rounds: 0` requested, the run still executed **2 full rounds** (round 1 survey, then a "Round 2: 1 gaps — logic" survey), identical to what happens when `rounds` is omitted entirely.
- **Evidence:**
  ```
  $ node scenario-e-rounds0.mjs
  rounds arg passed: 0
  survey calls (should be 0 if rounds:0 were honored): 2 [ 'logic', 'logic r2' ]
  coverage calls: 1
  logs:
    Scope incremental at deadbee — lenses: logic; skipped: none
    After round 1: 0 bugs, 0 decisions, 0 discarded
    Round 2: 1 gaps — logic
    After round 2: 0 bugs, 0 decisions, 0 discarded
  ```
- **Where:** `workflows/check-bugbash-flow.js:168` — `const rounds = A.rounds || (plan.scope === 'full' ? 3 : 2)`.
- **Root cause (probable):** `||` treats the falsy-but-valid value `0` the same as "unset"; the same class of bug that `MAX = A.maxParallel || 4` (line 24) would have for `maxParallel: 0`, and `FIX = A.fix !== false` on line 23 was already written correctly to *avoid* (using `!== false` specifically so that `fix: false` isn't swallowed).
- **Class:** consistency
- **Should have been caught by:** a workflow-runtime test asserting `rounds: 0` produces exactly the Prepare/Survey/Consolidate/Fix/Report calls of a single pass with no Coverage-phase agent call at all — none exists.
- **Proposed fix:** `const rounds = A.rounds ?? (plan.scope === 'full' ? 3 : 2)` (nullish coalescing, mirroring the `A.fix !== false` treatment already used for the other boolean/numeric flag on the line above it).

### LOG-103 · Coverage-gap tasks dropped by the unknown-lens filter or the `MAX*2` cap are never logged, unlike every other skip point in the same script (P3)
- **Persona / context:** Any bug bash with `rounds > 1` where the completeness critic (Coverage phase) names a lens id that isn't in `plan.lenses`, or returns more tasks than `MAX*2`. HEAD 19b332e.
- **Steps:** Ran the workflow with `maxParallel: 2` (so `MAX*2 = 4`) and rounds `3`, with the Coverage-phase critic (after round 1) returning 6 tasks: 5 for valid lenses (`logic`/`security`) interleaved with one for lens id `bogus-lens`, ordered so that filtering removes `bogus-lens` and the cap then removes one more valid task.
- **Expected:** The script is otherwise careful to surface every other place work is dropped — lenses that don't run at all are collected into `plan.skipped` and printed in the very first `log()` line ("skipped: ..."); the `budget`/"no silent caps" convention in this codebase's own authoring rules says any bounded coverage should log what was dropped.
- **Observed:** `tasks = (gaps && gaps.tasks || []).filter(t => byLens[t.lens]).slice(0, MAX * 2)` (line 241) silently drops both the invalid-lens task and the over-cap task with no corresponding `log()` call anywhere in the surrounding code — the only round-2 log line is `Round 2: 4 gaps — logic, security, logic, security`, which reports the 4 *survivors* and gives no indication that a `bogus-lens` task and a 6th "logic C" task ever existed or were discarded.
- **Evidence:**
  ```
  $ node scenario-d.mjs
  ...
  --- LOGS ---
  Scope full at deadbee — lenses: logic, security; skipped: none
  After round 1: 0 bugs, 0 decisions, 0 discarded
  Round 2: 4 gaps — logic, security, logic, security
  After round 2: 0 bugs, 0 decisions, 0 discarded
  ...
  ```
  (Coverage critic's stubbed return had 6 tasks, including `{lens:'bogus-lens', focus:'gap bogus', ...}` and a 6th `logic` task; neither appears anywhere in the logs.)
- **Where:** `workflows/check-bugbash-flow.js:241`.
- **Root cause (probable):** The filter+cap was written as a plain one-line guard with no accompanying `log()`, unlike the `plan.skipped` lenses which are explicitly surfaced.
- **Class:** other
- **Should have been caught by:** a workflow-runtime test feeding the Coverage stage a task list that mixes a valid and an invalid lens id and asserting a log line names the drop — none exists.
- **Proposed fix:** `log()` the dropped tasks by reason, e.g. `if (invalid.length) log(\`Coverage: dropping unknown lens id(s) ${invalid.map(t=>t.lens).join(', ')}\`)` and, when the cap actually truncates, `log(\`Coverage: capping ${gaps.tasks.length} gap tasks to ${MAX*2}\`)`.

### LOG-104 · Two coverage-gap tasks for the same lens in the same round get the identical `agent()` label, making them indistinguishable in the run's own telemetry (P3)
- **Persona / context:** A bug bash round where the completeness critic assigns more than one gap task to the same lens (a legitimate case — the critic's own instructions only cap total tasks at `MAX*2`, not per-lens). HEAD 19b332e.
- **Steps:** Same run as LOG-103: the round-1 Coverage critic returned two separate tasks for lens `logic` (different `focus` text each), both of which survived the filter/cap into round 2's `tasks` array.
- **Expected:** Each `agent()` call in this workflow is otherwise given a distinguishing `label` for progress/telemetry purposes (survey calls append `' r' + round`; skeptics append `' #2'`; fix retries append `' again'`), so that a person or a log watching the run can tell two concurrent calls apart.
- **Observed:** `survey()`'s label is computed purely as `` `${lens.id}${round > 1 ? ' r' + round : ''}` `` (line ~172-186), with no per-task disambiguator. Both round-2 gap tasks for `logic` produced two separate, concurrently-running `agent()` calls both labeled `"logic r2"` — confirmed identical in the captured call list even though they carried different `focus` text and (correctly) got non-colliding finding-id ranges (`101` and `201`).
- **Evidence:**
  ```
  $ node scenario-d.mjs
  --- SURVEY CALLS (label, start-number-in-prompt) ---
  { seq: 1, label: 'logic', start: 1 }
  { seq: 2, label: 'security', start: 1 }
  { seq: 4, label: 'logic r2', start: 101 }
  { seq: 5, label: 'security r2', start: 101 }
  { seq: 6, label: 'logic r2', start: 201 }   # <- identical label to seq 4, different task
  { seq: 7, label: 'security r2', start: 201 }
  ```
- **Where:** `workflows/check-bugbash-flow.js:173-186` (`survey()`'s `label: \`${lens.id}${round > 1 ? \` r${round}\` : ''}\``).
- **Root cause (probable):** The label was designed for "one task per lens per round" (true for round 1, where `tasks = plan.lenses.map(...)` is 1:1); it wasn't updated for the Coverage phase's tasks, which can legitimately put more than one task on the same lens in the same round.
- **Class:** other
- **Should have been caught by:** a workflow-runtime test with a Coverage critic returning two tasks for the same lens id, asserting the resulting `agent()` calls have distinct labels — none exists.
- **Proposed fix:** include the task index (or a hash of `task.focus`) in the label when more than one task targets the same lens in a round, e.g. `` `${lens.id}${round > 1 ? ` r${round}` : ''}${dup ? ` #${dupIndex+1}` : ''}` ``.

### LOG-105 · `args.lenses` as a bare string (instead of an array) crashes the whole workflow before a single agent runs (P2)
- **Persona / context:** `/keelokit:check-bugbash` (or any other caller of this workflow) invoked with `args: {lenses: 'logic'}` — a single lens id passed as a plain string rather than `['logic']`. This is exactly the JSON-array-vs-string footgun the workflow-authoring reference itself calls out generically for `args` ("pass arrays/objects as actual JSON values... not as a JSON-encoded string"), but nothing in this script guards against it for this specific field. HEAD 19b332e.
- **Steps:** Ran the workflow body with `args = {scope: 'incremental', lenses: 'logic'}` and an `agent()` stub that would fail the test if any agent call were ever reached.
- **Expected:** A malformed-but-plausible `args` value should either be tolerated (treated as `['logic']`) or fail with a clear, workflow-level message — not a raw JS internal error before the Prepare phase's own `agent()` call is even made.
- **Observed:** The very first template-string evaluation for the Prepare prompt — `` `The user asked for exactly these lenses: ${A.lenses.join(', ')}.` `` (line 137) — throws `TypeError: A.lenses.join is not a function` synchronously, before `agent()` is called at all. The whole workflow throws instead of returning any `{error: ...}` shape (contrast with line 147's `if (!plan) return {error: 'Prepare failed: no plan'}`, which *is* a handled, reported failure).
- **Evidence:**
  ```
  $ node scenario-e-lenses-string.mjs
  CRASHED: TypeError - A.lenses.join is not a function
  ```
  (Confirmed the crash happens strictly before any `agent()` call — the stub's `agentImpl` would itself throw a different, distinguishing error if reached, and it never was.)
- **Where:** `workflows/check-bugbash-flow.js:137`.
- **Root cause (probable):** `A.lenses.join(', ')` assumes `args.lenses` is always an array with no runtime check, unlike `A.fix`/`A.maxParallel`/`A.rounds`, which all tolerate any input type via `||`/`!==` coercion.
- **Class:** other
- **Should have been caught by:** a workflow-runtime test passing a non-array `lenses` value and asserting the workflow returns a handled `{error: ...}` rather than throwing — none exists.
- **Proposed fix:** normalize once near the top of the script, e.g. `const requestedLenses = A.lenses ? [].concat(A.lenses) : null`, and use `requestedLenses` in the prompt.

### LOG-106 · `survey()`'s fallback for an "unknown lens id" is dead code — every real caller already filters it out first (P3)
- **Persona / context:** Code-reading + confirmed by driving the workflow: the defensive branch is never exercised by either round-1 or Coverage-phase task construction. HEAD 19b332e.
- **Steps:** Traced every place `survey(task, round)` is called (`workflows/check-bugbash-flow.js:220`, the only call site) back to where `task` objects are constructed: round 1's `tasks = plan.lenses.map(l => ({lens: l.id, ...}))` (line 167, always a known lens by construction) and every later round's `tasks = (gaps && gaps.tasks || []).filter(t => byLens[t.lens]).slice(...)` (line 241, already filtered to known lenses before assignment). Confirmed empirically in scenario-a and scenario-d runs (12+ survey calls total across both) that `byLens[task.lens]` was truthy on every single call — the fallback path was never taken.
- **Expected:** Either the fallback is reachable and meaningfully tested (an "unknown lens" survey with `row: ''` and a 4-letter guessed prefix should behave sensibly), or it shouldn't exist, since dead defensive code silently misrepresents what inputs the function can actually receive.
- **Observed:** `const lens = byLens[task.lens] || { id: task.lens, prefix: task.lens.slice(0, 4).toUpperCase(), row: '' }` (line 172) can never take its right-hand branch given the two current call sites, both of which already guarantee `byLens[task.lens]` is defined.
- **Evidence:** Static trace above, cross-checked against the full `calls` list captured in scenario-a.mjs and scenario-d.mjs (12 survey/coverage-derived calls in total, all resolving through `byLens[...]` truthy) — no `agent()` call was ever built from the fallback object (which would be visible as a prompt with an empty "row of dimensions.md:" line).
- **Where:** `workflows/check-bugbash-flow.js:172`.
- **Root cause (probable):** The fallback was presumably written for perceived robustness against a lens-id typo, but the `.filter(t => byLens[t.lens])` on the only other call site (added for the `MAX*2` cap logic) already makes it unreachable.
- **Class:** other
- **Should have been caught by:** nothing catches dead code by construction; a coverage tool over the workflow's runtime branches would flag the `||` fallback as never taken across the test suite.
- **Proposed fix:** either delete the fallback (let a truly unknown lens id throw loudly, matching how `A.lenses.join` already fails hard elsewhere) or, if defensive handling is wanted, move the filtering out so the fallback path becomes reachable and testable — as written, it's misleading dead code.

## Round 2 — `enforcer_problem()` / `ci_job()` (doctor.py:121-185)

Every fixture below was run by importing `.keelokit/bin/doctor.py` as a module with `ROOT` monkeypatched
to a throwaway fixture directory (no full harness/context setup needed — `enforcer_problem(rid, ref)` and
`ci_job(job)` are pure functions of `ROOT`'s filesystem/git state) and calling them directly, under
`$SCRATCH/logic/fixtures/*` (scratch clone of HEAD 19b332e). Diffed byte-for-byte identical against
`git show v0.7.1:template/.keelokit/bin/doctor.py` (the only copy that existed at that tag — the plugin
repo's own root-level `.keelokit/bin/doctor.py` is new on this branch, from the self-adoption commit) —
**every finding below also affects v0.7.1**, and every generated/adopted project made from it, since
they all carry this file unchanged.

### LOG-201 · `ci_job()` matches any top-level 2-space YAML key in the whole file, not just keys under `jobs:` — a job name that collides with an unrelated section binds to the wrong block (P2)
- **Persona / context:** Maintainer/contributor whose `rules.toml` names a CI enforcer whose job id happens to equal a key already used elsewhere at the top level of the same workflow file (`on:`, `env:`, `permissions:`, …). HEAD 19b332e, scratch fixture.
- **Steps:**
  1. Build `.github/workflows/ci.yml`:
     ```yaml
     name: CI
     on:
       push:
         branches: [main]
       pull_request:
     jobs:
       push:
         runs-on: ubuntu-latest
         steps:
           - uses: actions/checkout@v4
           - run: npm run build-push
     ```
  2. Call `ci_job("push")` and `enforcer_problem("R-1", "ci:push")` with `ROOT` set to this fixture.
- **Expected:** `ci_job("push")` returns the real `jobs.push` block (checkout + a real `run:` step), so `enforcer_problem` should return `None` (alive) — the job genuinely exists and does real work.
- **Observed:** `ci_job("push")` returns `'    branches: [main]\n'` — the body of `on.push`, not `jobs.push` — because the regex `^  {job}:\s*\n(.*?)(?=^  \S|\Z)` matches the *first* `^  push:` line anywhere in the file, and `on:\n  push:\n    branches: [main]` comes before `jobs:\n  push:` in the text. `enforcer_problem` then reports `"CI job 'push' has no real step"` for a job that in fact has two real steps.
- **Evidence:**
  ```
  $ python3 run_ci_cases.py   # (imports doctor.py with ROOT patched to fixtures/ci2)
  ci_job() matched block: '    branches: [main]\n'
  enforcer_problem() -> "CI job 'push' has no real step"
  ```
- **Where:** `.keelokit/bin/doctor.py:124` (`ci_job`'s regex `^  {job}:\s*\n(.*?)(?=^  \S|\Z)`, searched against the whole file with no anchor to a `jobs:` block), identical in `template/.keelokit/bin/doctor.py:124`.
- **Root cause (probable):** The regex isn't scoped to the text after the top-level `jobs:` key — it treats every `^  <name>:` line in the file (under `on:`, `env:`, `permissions:`, `jobs:`, …) as a candidate job.
- **Class:** consistency
- **Should have been caught by:** a unit test in `tests/test_doctor.py` for `ci_job`/`enforcer_problem` with a job name that also appears as a 2-space key under `on:` — the existing tests (per the earlier grep for `ci_job`) only exercise a single, unambiguous job name per fixture workflow.
- **Proposed fix:** first isolate the text under the workflow's own top-level `jobs:` key (e.g. `^jobs:\s*\n(.*?)(?=^\S|\Z)`), then run the per-job regex only within that slice.

### LOG-202 · `ci_job()`'s job-line regex is hardcoded to exactly 2-space indentation — a job block indented differently is reported as "does not exist" (P2)
- **Persona / context:** Any workflow file that indents `jobs:` children by 4 spaces (or another consistent amount) instead of 2 — valid YAML, and not unheard of from some codegen tools or hand-edited files. HEAD 19b332e.
- **Steps:**
  1. Build a workflow whose `jobs:` block uses 4-space indentation throughout:
     ```yaml
     name: CI
     on: [push]
     jobs:
         build:
             runs-on: ubuntu-latest
             steps:
                 - uses: actions/checkout@v4
                 - run: npm test
     ```
  2. Call `ci_job("build")` / `enforcer_problem("R-1", "ci:build")`.
- **Expected:** The job exists, has a real step, and no `continue-on-error` — `enforcer_problem` should return `None`.
- **Observed:** `ci_job("build")` returns `None` and `enforcer_problem` returns `"CI job 'build' does not exist"` — a live, working CI job is reported as missing outright, purely because of its indentation width.
- **Evidence:**
  ```
  $ python3 run_ci_cases.py
  ci_job() matched block: None
  enforcer_problem() -> "CI job 'build' does not exist"
  ```
- **Where:** `.keelokit/bin/doctor.py:124` — the pattern literally spells `^  {job}:` (exactly two spaces), never accounting for a different (but valid) indent width.
- **Root cause (probable):** The regex assumes GitHub Actions' most common style (`actions/checkout`-generated 2-space) is universal, rather than deriving the indent from the file's own `jobs:` line.
- **Class:** consistency
- **Should have been caught by:** a `tests/test_doctor.py` fixture using a non-2-space-indented workflow — none exists; all current fixtures presumably mirror this repo's own `.github/workflows/*.yml` styling.
- **Proposed fix:** capture the indent actually used right after `jobs:\n` (e.g. `^jobs:\n(?P<indent> +)`) and build the per-job regex with that captured width instead of a literal two spaces.

### LOG-203 · A job with `if: false` (never runs) is reported as a live enforcer (P1)
- **Persona / context:** A CI job that has been temporarily (or permanently, by accident) disabled with a top-level `if: false` while its steps are left in place "for later." HEAD 19b332e.
- **Steps:**
  1. Build:
     ```yaml
     jobs:
       build:
         if: false
         runs-on: ubuntu-latest
         steps:
           - uses: actions/checkout@v4
           - run: npm test
     ```
  2. Call `enforcer_problem("R-1", "ci:build")`.
- **Expected:** Per the docstring's promise ("doctor tells you when a rule has lost its check"), a job that structurally never executes is exactly a rule that has lost its check — same effect as `continue-on-error: true`, which the function *does* check for.
- **Observed:** `enforcer_problem` returns `None` (alive) — GitHub Actions will never run this job on any trigger, yet doctor reports the enforcer as healthy.
- **Evidence:**
  ```
  $ python3 run_ci_cases.py
  ci_job() matched block: '    if: false\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n      - run: npm test\n'
  enforcer_problem() -> None
  ```
- **Where:** `.keelokit/bin/doctor.py:140-148` (`kind == "ci"` branch) — checks `continue-on-error` and "has a real step," never a job-level `if:`.
- **Root cause (probable):** The function's threat model for "job looks alive but isn't really enforcing" only covered `continue-on-error`; a job-level `if:` that's statically falsy (or an always-false expression) is an equally direct way to neuter a job and wasn't considered.
- **Class:** consistency
- **Should have been caught by:** a `tests/test_doctor.py` case for a job carrying `if: false` — none exists (the existing `continue-on-error` test, per the docstring's own description, isn't paired with an `if:` test).
- **Proposed fix:** in the `ci` branch, also flag `re.search(r"(?m)^\s*if:\s*false\b", block)` (and, defensively, the common `if: ${{ false }}` form) as `f"CI job '{target}' has if: false"`.

### LOG-204 · `continue-on-error: ${{ true }}` (expression form) is invisible to the literal-`true` regex (P1)
- **Persona / context:** A CI job using the GitHub Actions expression syntax for `continue-on-error` (e.g. driven by a repository variable or just written as `${{ true }}` instead of the bare `true`). HEAD 19b332e.
- **Steps:**
  1. Build:
     ```yaml
     jobs:
       build:
         runs-on: ubuntu-latest
         continue-on-error: ${{ true }}
         steps:
           - uses: actions/checkout@v4
           - run: npm test
     ```
  2. Call `enforcer_problem("R-1", "ci:build")`.
- **Expected:** This job's failures are swallowed exactly as much as a literal `continue-on-error: true` — doctor should flag it the same way.
- **Observed:** `enforcer_problem` returns `None` (alive) — the existing check (`^\s*continue-on-error:\s*true`) requires the literal token `true` immediately after the colon and doesn't match `${{ true }}`.
- **Evidence:**
  ```
  $ python3 run_ci_cases.py
  ci_job() matched block: '    runs-on: ubuntu-latest\n    continue-on-error: ${{ true }}\n    steps:\n      - uses: actions/checkout@v4\n      - run: npm test\n'
  enforcer_problem() -> None
  ```
- **Where:** `.keelokit/bin/doctor.py:144` — `re.search(r"(?m)^\s*continue-on-error:\s*true", block)`.
- **Root cause (probable):** The regex only anticipates the bare YAML boolean spelling, not GitHub Actions' `${{ <expr> }}` wrapping, which is valid and common wherever a value might come from a variable.
- **Class:** consistency
- **Should have been caught by:** a `tests/test_doctor.py` case using the `${{ true }}` spelling for `continue-on-error` — the existing test (implied by the docstring) presumably only uses the literal form.
- **Proposed fix:** broaden the regex to `r"(?m)^\s*continue-on-error:\s*(\${{\s*true\s*}}|true)\b"`, and note in a comment that this is necessarily best-effort against arbitrary expressions (e.g. a variable that evaluates to true can't be resolved statically).

### LOG-205 · A job whose only step is `run: echo ok` counts as a "real step" — a no-op stub passes as a live enforcer (P2, productRule)
- **Persona / context:** A CI job created as a placeholder (or left over after its real check was gutted) that never actually does anything but succeed. HEAD 19b332e.
- **Steps:**
  1. Build:
     ```yaml
     jobs:
       build:
         runs-on: ubuntu-latest
         steps:
           - run: echo ok
     ```
  2. Call `enforcer_problem("R-1", "ci:build")`.
- **Expected:** Unclear from the docs whether this should be caught — this is the pending-decision case, flagged as `productRule`. Arguably a job that runs no test/lint/build command specific to the rule shouldn't count as "real" any more than the `SETUP_STEPS` actions already excluded.
- **Observed:** `enforcer_problem` returns `None` (alive): `real = ["echo ok"]` is non-empty because `"echo ok"` isn't in the small excluded-literal set (`"true"`, `"exit 0"`, `":"`, `""`) and doesn't match `SETUP_STEPS`.
- **Evidence:**
  ```
  $ python3 run_ci_cases.py
  ci_job() matched block: '    runs-on: ubuntu-latest\n    steps:\n      - run: echo ok\n'
  enforcer_problem() -> None
  ```
- **Where:** `.keelokit/bin/doctor.py:147` — `real = [s for s in steps if not SETUP_STEPS.search(s) and s.strip().strip("'\"") not in ("true", "exit 0", ":", "")]`.
- **Root cause (probable):** The exclusion list only rules out a handful of literal always-succeed spellings; any other content-free command (`echo ok`, `echo done`, `exit 0` spelled differently, `sleep 1`) still counts as "real."
- **Class:** consistency
- **Should have been caught by:** a `tests/test_doctor.py` case for an `echo`-only job — likely absent, and deciding the right boundary (which is itself the `productRule` question here) would need to be settled first.
- **Proposed fix (if the product decides this should be caught):** widen the exclusion heuristic (e.g. reject single-word `echo ...`/`sleep ...`/pure-literal commands with no `&&`/pipe/script invocation), or — more robustly, mirroring how the `test:` enforcer already requires the rule id to be cited — require the CI job's steps to reference something specific to the rule (script name, package script, or the rule id in a `# ` comment) rather than merely "any non-setup command."

### LOG-206 · A workflow that only triggers on `workflow_dispatch` (never runs automatically) is reported as a live enforcer (P2, productRule)
- **Persona / context:** A CI job that exists and has real steps, but the workflow's only trigger is `workflow_dispatch` — so it never runs on an ordinary push or PR unless someone remembers to click "Run workflow." HEAD 19b332e.
- **Steps:**
  1. Build:
     ```yaml
     name: CI
     on:
       workflow_dispatch:
     jobs:
       build:
         runs-on: ubuntu-latest
         steps:
           - uses: actions/checkout@v4
           - run: npm test
     ```
  2. Call `enforcer_problem("R-1", "ci:build")`.
- **Expected:** Unclear from docs whether doctor should check triggers at all (flagged `productRule` — some rules might legitimately be enforced only via a manual/scheduled job, e.g. an expensive scan). If the intent is "runs on every relevant push/PR," this should be flagged; if manual-only enforcement is an accepted pattern, it shouldn't.
- **Observed:** `enforcer_problem` returns `None` (alive) — `ci_job`/`enforcer_problem` never inspect the workflow's top-level `on:` block at all, so a job that can only ever be triggered by a human clicking a button is indistinguishable from one that runs on every push.
- **Evidence:**
  ```
  $ python3 run_ci_cases.py
  ci_job() matched block: '    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n      - run: npm test\n'
  enforcer_problem() -> None
  ```
- **Where:** `.keelokit/bin/doctor.py:140-148` — no reference anywhere in the `ci` branch to the workflow's `on:` triggers.
- **Root cause (probable):** The function was designed to validate a job's own body (steps, continue-on-error), not the workflow-level conditions under which that body would ever run.
- **Class:** consistency
- **Should have been caught by:** a `tests/test_doctor.py` case for a `workflow_dispatch`-only workflow — none exists; this is also the kind of case a spec decision (`docs/context/constraints.md` or `rules.toml`'s own docs) would need to settle first.
- **Proposed fix (if the product decides automatic triggers are required):** also require the containing workflow's `on:` to include at least one of `push`/`pull_request`/`schedule`, and report e.g. `f"CI job '{target}' only runs on workflow_dispatch"` otherwise.

### LOG-207 · A git hook is judged "installed" by existence alone — an empty, non-executable file that never calls guard.py is reported as a live enforcer (P1)
- **Persona / context:** A repo where a `pre-commit` hook file was created (e.g. by a half-finished setup, or `touch`ed as a placeholder) but is empty, not executable, and doesn't invoke `guard.py`. HEAD 19b332e, scratch git repo.
- **Steps:**
  1. `git init` a fixture, `: > .git/hooks/pre-commit` (0 bytes, mode `-rw-r--r--`, no `core.hooksPath` set).
  2. Call `enforcer_problem("INV-002", "git-hook:pre-commit")` with `ROOT` at the fixture.
- **Expected:** Git will never execute this file (not executable) and even if it were executable it does nothing (empty) — the enforcer should report a problem, matching the docstring's "a git hook that is installed" (which, given INV-002/QA-4's whole purpose, must mean "installed and actually running the guard," not merely present on disk).
- **Observed:** `enforcer_problem` returns `None` (alive).
- **Evidence:**
  ```
  $ ls -la .git/hooks/pre-commit
  -rw-r--r-- 1 root root 0 Sep 28 01:35 .git/hooks/pre-commit
  $ python3 run_hook_cases.py
  core.hooksPath = ''
  enforcer_problem('git-hook:pre-commit') -> None
  ```
- **Where:** `.keelokit/bin/doctor.py:149-154` (`kind == "git-hook"`) — `if (ROOT / d / target).exists(): return None`; no check of executability or content.
- **Root cause (probable):** The check was written to detect "was a hook ever installed here" (file present) rather than "will git actually execute something that calls guard.py here."
- **Class:** consistency
- **Should have been caught by:** a `tests/test_doctor.py` case with an empty/non-executable/unrelated-content hook file — none exists (existing tests, per the earlier grep, presumably only cover "file present" vs. "file absent").
- **Proposed fix:** also require `target` file to be executable (`os.access(path, os.X_OK)`) and to contain a reference to `guard.py` (mirroring the `file:`/`script:` enforcer's own `#needle` support), returning a specific message (e.g. `"git hook '{target}' exists but is empty/not executable"` or `"...doesn't call guard.py"`) when either check fails.

### LOG-208 · The git-hook check's hardcoded `.husky` fallback ignores the actually-configured `core.hooksPath` — a stray file, or husky v9's own layout, is reported "installed" when git will never find it (P1)
- **Persona / context:** (a) A husky v9 project where `core.hooksPath` is set to `.husky/_` and the real hook script lives only at the top-level `.husky/pre-commit` (the wrapper husky itself would generate at `.husky/_/pre-commit` hasn't been generated yet, e.g. before the first `npm install`/`prepare` run); (b) any repo where `core.hooksPath` points at a broken/missing/absolute directory while an unrelated leftover file happens to sit at `.husky/<hookname>` (e.g. from a previous hook manager). HEAD 19b332e, scratch git repos.
- **Steps (husky v9 layout):**
  1. `git init`; `git config core.hooksPath .husky/_`; create `.husky/pre-commit` (executable, calls `guard.py git-pre-commit`); leave `.husky/_/` empty (no generated wrapper yet).
  2. Call `enforcer_problem("INV-002", "git-hook:pre-commit")`.
- **Steps (broken hooksPath + stray file):**
  1. `git init`; `git config core.hooksPath /nonexistent/hooks/dir` (git will look there and find nothing, ever); create an executable but unrelated `.husky/pre-commit` (`echo "stray unrelated hook, not used by git anymore"`) left over from a previous setup.
  2. Call `enforcer_problem("INV-002", "git-hook:pre-commit")`.
- **Expected:** In both cases git itself will never execute a `pre-commit` hook (nothing named `pre-commit` exists inside the *configured* `hooksPath`, `.husky/_`, in case (a); the configured `hooksPath` doesn't exist at all in case (b)) — the enforcer should report a problem.
- **Observed:** Both return `None` (alive), because the loop `for d in (hooks_dir, ".husky"): if (ROOT / d / target).exists(): return None` always additionally checks the *literal, hardcoded* path `.husky/<target>` regardless of what `core.hooksPath` is actually set to, and finds a same-named file there in both fixtures.
- **Evidence:**
  ```
  $ python3 run_hook_cases.py
  === hookB: husky v9: hooksPath=.husky/_, hook lives at top-level .husky/pre-commit only
      core.hooksPath = '.husky/_'
      enforcer_problem('git-hook:pre-commit') -> None

  === hookC: hooksPath=/nonexistent/hooks/dir (git can never find a hook there); stray .husky/pre-commit left over
      core.hooksPath = '/nonexistent/hooks/dir'
      enforcer_problem('git-hook:pre-commit') -> None
  ```
- **Where:** `.keelokit/bin/doctor.py:150-154`:
  ```python
  hooks_dir = git("config", "core.hooksPath").strip() or ".git/hooks"
  for d in (hooks_dir, ".husky"):
      if (ROOT / d / target).exists():
          return None
  ```
- **Root cause (probable):** `.husky` was added as a fallback for the common "husky installed, `core.hooksPath` not set yet" case, but it's checked unconditionally — even when `core.hooksPath` *is* set (to `.husky/_`, to an absolute path, to anything) — so it can mask a genuinely broken or reconfigured hooksPath whenever a same-named file happens to still sit in `.husky/`.
- **Class:** consistency
- **Should have been caught by:** a `tests/test_doctor.py` case with `core.hooksPath` set to something other than `.husky`/`.git/hooks` and a stray `.husky/<hook>` file present — none exists.
- **Proposed fix:** only fall back to `.husky` when `core.hooksPath` is unset (i.e. the fallback tuple should be `(hooks_dir,)` when hooksPath is configured, and `(".git/hooks", ".husky")` only when it isn't); for the husky-v9-not-yet-installed case specifically, treat `hooksPath == ".husky/_"` as also acceptable when the *top-level* `.husky/{target}` exists, but only when hooksPath is exactly that expected husky value, not any arbitrary configured path.

### LOG-209 · A lint rule enabled only through a spread preset (e.g. `...tseslint.configs.recommended`) is reported as "not enabled" (P2)
- **Persona / context:** A TypeScript project whose flat ESLint config enables most of its rules via a shared preset spread into the config array, rather than spelling out each rule literally — the standard `typescript-eslint` / `eslint-plugin-*` recommended-config pattern. HEAD 19b332e.
- **Steps:**
  1. Build `eslint.config.js`:
     ```js
     import tseslint from 'typescript-eslint';
     export default [
       ...tseslint.configs.recommendedTypeChecked, // enables @typescript-eslint/no-floating-promises
       { rules: { "no-console": "warn" } },
     ];
     ```
  2. Call `enforcer_problem("R-1", "lint:@typescript-eslint/no-floating-promises")`.
- **Expected:** The rule is genuinely on (via the preset) — the enforcer should return `None`.
- **Observed:** `enforcer_problem` returns `"lint rule '@typescript-eslint/no-floating-promises' is not enabled"` — a false error for a correctly-configured project.
- **Evidence:**
  ```
  $ python3 run_lint_cases.py
  ref='lint:@typescript-eslint/no-floating-promises'
  enforcer_problem() -> "lint rule '@typescript-eslint/no-floating-promises' is not enabled"
  ```
- **Where:** `.keelokit/bin/doctor.py:169-175` (`kind == "lint"`) — only greps the repo's own `eslint.config.*`/`.eslintrc*` text for the rule name followed by `error`/`warn`/`2`/`1`; a rule enabled inside a spread preset (defined in the preset package, not textually present in the repo's config file) never matches.
- **Root cause (probable):** The check is a pure text grep over the config file(s) actually in the repo, with no awareness of (and no way to evaluate) rules that presets contribute.
- **Class:** consistency
- **Should have been caught by:** a `tests/test_doctor.py` case using a preset-spread config for a known TypeScript rule — none exists; every existing fixture presumably spells rules out literally.
- **Proposed fix:** when a rule can't be found spelled out, either (a) also check the `enforced_by` target for an explicit `known-preset` annotation the rule author can supply as an escape hatch (similar to how `rules.local.toml` lets an adopted repo remap enforcers to what it already has), or (b) narrow the promise in the docstring/README to "a lint rule that is spelled out (not preset-only) is on," so this is an accepted, documented limitation rather than a silent false error.

### LOG-210 · The lint "off somewhere" check ignores text order and file-glob scoping — it can report a rule as off even when the last (winning) config block turns it back on repo-wide (P2)
- **Persona / context:** A flat-config ESLint setup where an old/superseded block sets a rule `off` and a later block (which actually wins, per ESLint flat-config's own "last matching config wins" semantics) sets it back to `error` for all files. HEAD 19b332e.
- **Steps:**
  1. Build `eslint.config.js`:
     ```js
     export default [
       { rules: { "no-eval": "off" } },                              // legacy, superseded below
       { files: ["**/*.{ts,tsx}"], rules: { "no-eval": "error" } },  // the actual, currently-effective setting
     ];
     ```
  2. Call `enforcer_problem("R-1", "lint:no-eval")`.
- **Expected:** The rule is effectively `error` for every matching file (flat config: later entries win over earlier ones for overlapping files) — `enforcer_problem` should return `None`.
- **Observed:** `enforcer_problem` returns `"lint rule 'no-eval' is turned off somewhere"` — the "off" branch is checked first and unconditionally (`any(... 'off' ...)` over the whole file text, with no notion of which occurrence is later or more specific), so the fact that a *later, winning* block re-enables it is never considered. (A related but distinct variant: a rule `error` everywhere, with a narrow `**/*.test.ts`-only override to `off` for test files, is also reported "turned off somewhere" — collapsing a deliberate, narrowly-scoped carve-out into a blanket "rule is compromised" verdict, even though production code is fully covered.)
- **Evidence:**
  ```
  $ python3 run_lint_cases.py   # (lintC fixture — off first, on wins by position/order)
  === lintC
      enforcer_problem() -> "lint rule 'no-eval' is turned off somewhere"

  # separately, lintB fixture — 'error' base + narrow **/*.test.ts override to 'off':
  === lintB: rule 'error' in base block, 'off' only in a narrow **/*.test.ts override
      enforcer_problem() -> "lint rule 'no-eval' is turned off somewhere"
  ```
- **Where:** `.keelokit/bin/doctor.py:169-175`:
  ```python
  if any(re.search(rf"['\"]{rule}['\"]\s*:\s*\[?\s*['\"]?(off|0)\b", t) for t in texts):
      return f"lint rule '{target}' is turned off somewhere"
  on = any(re.search(rf"['\"]{rule}['\"]\s*:\s*\[?\s*['\"]?(error|warn|2|1)\b", t) for t in texts)
  return None if on else f"lint rule '{target}' is not enabled"
  ```
- **Root cause (probable):** `any()` over the whole config text has no concept of ESLint flat config's "later block wins for matching files" precedence, or of `files:` scoping — it's a pure "does the string 'off' appear anywhere near this rule name" check.
- **Class:** consistency
- **Should have been caught by:** a `tests/test_doctor.py` case with an `off` block followed by a later `error` block for the same rule (order matters) — none exists.
- **Proposed fix:** at minimum, take the *last* matching occurrence in file order as authoritative (mirroring real flat-config semantics) instead of "any off anywhere wins"; more completely, this would need real config-array evaluation (order + `files:` glob matching) rather than a flat grep, which is a larger design change worth flagging even if not fixed immediately.

### LOG-211 · The `test:` enforcer checks "rule id appears somewhere in the file" and "the file has some active test" independently — a skipped test citing the rule is masked by any unrelated active test in the same file (P1)
- **Persona / context:** The exact scenario the docstring says this check exists to catch: "a test that cites the rule and has active cases" going stale — here, the one test that actually exercises the rule gets skipped (e.g. during a refactor, `it.skip`'d "temporarily"), but the same test file also has an unrelated active test. HEAD 19b332e.
- **Steps:**
  1. Build `apps/api/src/rule.test.ts`:
     ```ts
     import { describe, it } from "vitest";
     describe("amount validation", () => {
       it.skip("LOG-201: rejects a negative amount", () => {
         // the only test that actually exercises the rule is skipped
       });
       it("some unrelated active test", () => {
         // does not mention LOG-201 at all
       });
     });
     ```
  2. Call `enforcer_problem("LOG-201", "test:apps/api/src/rule.test.ts")`.
  3. Sanity check: with the unrelated active test removed (file has *only* the skipped, rule-citing test), the same call correctly reports the enforcer as dead.
- **Expected:** Per the docstring, an enforcer looks alive when there is "a test that cites the rule *and* has active cases" — i.e. the citing test itself must be active. The rule's own actual test being skipped should be reported as a lost check, regardless of what else happens to be active in the same file.
- **Observed:** `enforcer_problem` returns `None` (alive) once the unrelated active test is added — `re.search(rid, text)` matches because "LOG-201" appears anywhere in the raw file (inside the skipped test's title string), and `test_titles(f)` is non-empty because of the *unrelated* active test; the two conditions are ANDed at the file level, not tied to the same test.
- **Evidence:**
  ```
  $ python3 run_test_case.py
  enforcer_problem() -> None
  test_titles() -> ['amount validation', 'some unrelated active test']

  # Sanity check — same rid, but the file's ONLY test is the skipped one (no unrelated active test):
  $ python3 -c "... rule2.test.ts with only 'it.skip(\"LOG-999: only test, and it is skipped\", ...)' ..."
  apps/api/src/rule2.test.ts: no active test that names LOG-999 (add a comment or title citing it)
  ```
  (Confirms the bug is specifically the presence of *any other* active test/describe title in the same file, not a general failure to detect skips — see LOG-999 control case, correctly reported dead.)
- **Where:** `.keelokit/bin/doctor.py:164`:
  ```python
  live = [f for f in files if re.search(rf"\b{re.escape(rid)}\b", f.read_text(errors="ignore")) and test_titles(f)]
  ```
- **Root cause (probable):** The rule-id search runs over the whole file's raw text (which includes skipped tests' title strings, since `it.skip(...)`'s string argument is still just text) while `test_titles()` — which does correctly exclude skipped titles — is checked only for "is the list non-empty," not "does one of these active titles (or a comment adjacent to one) contain rid."
- **Class:** consistency
- **Should have been caught by:** a `tests/test_doctor.py` case with a skipped rule-citing test plus a separate unrelated active test in the same file — none exists (existing tests, per the earlier grep, presumably use single-test fixture files, which is exactly why the LOG-999 control case above still passes).
- **Proposed fix:** require the rid match and an active title to co-occur near each other — simplest: search for `rid` only within a window around each active test's own match (e.g. the `describe`/`it` call whose title or immediately preceding comment contains rid), or, cheaper, split the file's skipped-vs-active regions and only run the `rid` search over the *active* region (built by removing every `it.skip(...)`/`it.todo(...)`/`xit(...)` call's text before searching).

### LOG-301 · `doctor.py`'s `main_ref()` silently falls back to `HEAD` when no `origin/main` or local `main` exists, so `pnpm mutation` and `doctor --scope` report a clean diff of nothing-against-itself instead of erroring (P1)
- **Persona / context:** Developer with an existing repo, or an agent working in a fresh worktree/branch before origin is configured — any git state with no `origin/main` and no local branch literally named `main` (e.g. working entirely offline on a feature branch cut before `git remote add origin` ever ran, or a shallow/worktree checkout that never fetched `main`). HEAD 19b332e, generated project `api+web`, scratch dir (isolated clone, no `/home/user/keelokit` touched).
- **Steps (mutation path):**
  1. Generate a project at HEAD (`api`,`web`), `git init -q -b other-branch` (never `main`), add a bare `origin` whose only branch is `other-branch` (so `origin/main` does not exist either).
  2. Edit the critical file the template ships by default (`.keelokit/critical.toml`'s `allocation` area → `packages/shared/src/allocate.ts`), commit it.
  3. Run `python3 .keelokit/bin/doctor.py --critical --changed` and `bash scripts/mutation.sh`.
- **Steps (`--scope` path, same fixture):**
  4. Add `backlog/stories/STORY-001-probe.md` with `touches = ["packages/shared/src/i18n.ts"]` only, commit.
  5. Add an *undeclared* edit to the critical file `packages/shared/src/allocate.ts` (outside `touches`, and a critical area not declared as `integrity`), commit.
  6. Run `python3 .keelokit/bin/doctor.py --scope STORY-001`.
- **Expected:** Per the script's own docstrings, `pnpm mutation` mutates "critical files changed since origin/main" (MUT-1) and should fail loudly or run against the actually-changed critical file; `doctor --scope` reports "files this branch changed outside the story's touches" and flags an undeclared critical-area touch (CRIT-1). Neither promise says "silently see zero files when there is no `main` anywhere" — verify.sh's own analogous case (no origin / origin with no main) explicitly falls back to the *safe* direction (`all=true`, run everything); doctor.py's diff-based checks should fail safe the same way, or at least error, not silently report "nothing changed."
- **Observed:**
  ```
  $ python3 .keelokit/bin/doctor.py --critical --changed
  (empty output)
  $ bash scripts/mutation.sh
  No critical code changed since origin/main to mutate (.keelokit/critical.toml).
  ```
  — printed even though `packages/shared/src/allocate.ts` (the one declared critical area) was just edited and committed on this branch, and even though the message names `origin/main`, which does not exist in this repo at all.
  ```
  $ python3 .keelokit/bin/doctor.py --scope STORY-001
  STORY-001: all 0 changed files are within its touches
  ```
  — printed (exit 0) even though the branch's last commit edited `packages/shared/src/allocate.ts`, which is (a) outside the story's declared `touches` (`packages/shared/src/i18n.ts` only) and (b) a declared critical area the story does not declare `integrity` for. Both the scope-creep check and the CRIT-1 undeclared-critical-area check are bypassed.
- **Where:** `.keelokit/bin/doctor.py:114-118`:
  ```python
  def main_ref() -> str:
      for ref in ("origin/main", "main"):
          if git("rev-parse", "--verify", "--quiet", ref).strip():
              return ref
      return "HEAD"
  ```
  consumed at `doctor.py:551` (`base = git("merge-base", main_ref(), "HEAD").strip() or "HEAD"`, used by `--critical --changed`) and `doctor.py:505` (`git("diff", "--name-only", f"{main_ref()}...HEAD")`, used by `--scope`) and `doctor.py:521` (backlog wave-clash acceptance-test range).
- **Root cause (probable):** When neither `origin/main` nor a local `main` branch exists, `main_ref()` returns the string `"HEAD"` as a stand-in ref. Every caller then diffs or computes a merge-base of `HEAD` against `HEAD` itself, which is by definition empty (`merge-base(HEAD,HEAD) == HEAD`, and `git diff HEAD...HEAD` / `git diff --name-only HEAD` show nothing once the change is committed). The fallback silently converts "I don't know what to compare against" into "nothing has changed," instead of erroring or defaulting to "everything is in scope" the way `scripts/verify.sh` deliberately does for the same missing-origin/missing-main condition (`git rev-parse --verify --quiet origin/main` failing there triggers `all=true`, the safe direction).
- **Class:** consistency
- **Should have been caught by:** a `tests/test_doctor.py` case for `--critical --changed` and one for `--scope` in a repo with no `origin` remote and no branch named `main` — none exists; the existing tests for both flags appear to always fix up a `main` ref first.
- **Proposed fix:** make `main_ref()` return `None` (or raise) when neither ref exists, and have each caller fail safe in the direction that matches its purpose: `--critical --changed` should behave like `--critical` (treat *all* critical files as "changed," matching `verify.sh`'s own `all=true` fallback) rather than printing a misleading "since origin/main" message that names a ref that doesn't exist; `--scope` should print an explicit "no `main` ref to compare against — scope check skipped" (and a non-zero/likely-error exit) rather than a clean "0 changed files" pass that reads as a real pass.

### LOG-302 · `scripts/verify.sh`'s full-verify trigger (`git diff --quiet origin/main -- package.json pnpm-lock.yaml …`) is blind to a manifest file that is present but untracked — the affected-only gate silently stays on even though the lockfile has diverged from `origin/main` (P1)
- **Persona / context:** Any of: a newcomer following `/keelokit:project-new`'s documented order (`git init -b main`, `pnpm install`, **then** `pnpm verify`, first commit only after — SKILL.md step 3-4, `skills/project-new/SKILL.md:135-138`), or a developer/agent who runs `pnpm install` to add a dependency and stages files individually rather than `git add -A`. HEAD 19b332e, generated project `api+web`, scratch dir with a local bare `origin`.
- **Steps:**
  1. Generate a project, `git init -b main`, `pnpm install` (creates `pnpm-lock.yaml` on disk), commit **before** `git add`ing the lockfile (mirroring `scripts/test-template.sh`'s own generation order — `commit_all generated` runs before `pnpm install` — and also reachable via the ordering above if the first commit's `git add` misses the freshly-written lockfile), push `main` to a bare `origin`.
  2. On `main`, with `pnpm-lock.yaml` present on disk (222 KB, real content) but `git status` showing it as `??` (untracked) and never present in `origin/main` at all:
     ```
     $ git diff --quiet origin/main -- pnpm-lock.yaml; echo exit=$?
     exit=0
     $ git diff origin/main -- pnpm-lock.yaml | head
     (no output)
     ```
  3. Run `pnpm verify` (the pre-push hook's exact command) on a branch whose only change is to `docs/context/product.md` (a root file outside the manifest list and outside any package).
- **Expected:** `scripts/verify.sh`'s own comment: "Root manifests and the base tsconfig reach every package: a change there means everything" — the check exists specifically so that a lockfile/manifest change forces `all=true` full verification instead of the affected-only fast path, because a dependency-graph change isn't attributable to any single workspace package the way `pnpm --filter '...[origin/main]'` detects. That safety net should trigger whenever `pnpm-lock.yaml`'s content differs from what's on `origin/main` — which is unambiguously true here (it doesn't exist on `origin/main` at all).
- **Observed:** The `git diff --quiet origin/main -- package.json pnpm-lock.yaml pnpm-workspace.yaml tsconfig.base.json` check in `scripts/verify.sh` returns "no difference" (exit 0) for `pnpm-lock.yaml` even though the file exists only in the working tree and not in `origin/main`, because `git diff <ref> -- <path>` only ever compares paths that are in git's index; an untracked file is invisible to it regardless of content. `pnpm verify` therefore takes the affected-only branch (`Affected packages only (since origin/main); …`) and, for the docs-only branch in the same run, ends up running typecheck/test/build/e2e against **zero** packages (`No projects matched the filters`) — the full suite is skipped with no warning that the lockfile itself is out of sync with `origin/main`. Separately, because the file is untracked, `git push` never sends it to `origin` at all, so the same blind spot means the updated lockfile can silently never reach CI either.
- **Where:** `template/scripts/verify.sh:35-42`:
  ```bash
  scope=(-r)
  if ! $all && git rev-parse --verify --quiet origin/main >/dev/null &&
    git diff --quiet origin/main -- package.json pnpm-lock.yaml pnpm-workspace.yaml tsconfig.base.json; then
    scope=(--filter '...[origin/main]' --filter '!{.}')
    echo 'Affected packages only (since origin/main); `pnpm verify --all` runs everything.'
  else
    all=true
  fi
  ```
- **Root cause (probable):** `git diff <ref> -- <path>` is defined over tracked paths (the index); it silently treats an untracked file at that path as if it doesn't exist, rather than as "added" or "changed." The escalation check assumes `pnpm-lock.yaml` (and the other three manifest files) are always tracked, but nothing in the template, `.gitignore`, or `doctor.py` asserts that — and the template's own `scripts/test-template.sh` generates projects in an order (commit, then `pnpm install`) that leaves the freshly created lockfile untracked at the point the very first `pnpm verify --all` runs, so this exact state is one step in workflow ordering away in the documented `/keelokit:project-new` flow too (step 3's `pnpm install` runs before step 4's first commit, and nothing enumerates which files that commit must include).
- **Class:** consistency
- **Should have been caught by:** an integration test in `tests/` or a `scripts/test-template.sh` scenario that runs plain `pnpm verify` (not `--all`) after leaving `pnpm-lock.yaml` untracked — none exists; every template run in this repo's CI and `scripts/test-template.sh` calls `pnpm verify --all`, so the affected-only branch of `verify.sh` (and this blind spot) has no automated coverage at all.
- **Proposed fix:** don't rely solely on `git diff --quiet <ref> -- <path>` for files that must always be tracked; first assert trackedness (`git ls-files --error-unmatch pnpm-lock.yaml` or check `git status --porcelain -- pnpm-lock.yaml` for a leading `??`) and force `all=true` (with a clear message naming the untracked file) whenever a watched manifest path is untracked, in addition to the existing tracked-diff check.

### LOG-303 · `next_step()` lets any pending stage pre-empt doctor errors, blocking gaps and a stale harness — reproduced live on this repo's own dashboard (P1)
- **Persona / context:** Every journey that reads the dashboard's "next step" (the founder, the developer adopting, the daily agent session) whenever a stage is mid-flow at the same time something else needs attention — reproduced both on synthetic fixtures and directly on this repo, HEAD fcbbee7 (self-adopted, `layout: harness`, `dashboard.lang = es`).
- **Steps:**
  1. `python3 skills/project-dashboard/scripts/dashboard.py --json` in `/home/user/keelokit` itself (real state: intake stage awaiting approval, 16 harness errors from `doctor.py`, harness `v0.7.0` behind plugin `v0.7.1`).
  2. Synthetic fixture (`build_fx.py` in the lens's scratch dir, reusing `tests/test_dashboard.py`'s own `STORY`/`context` helpers): a project with all four `docs/context/*.md` files present, one gap marked `Blocking: yes`, and intake's stage output complete so `stages[0]["status"] == "review"`.
  3. Read `view["next"]` and `view["waiting"]` from both.
- **Expected:** `skills/project-dashboard/references/design.md` describes "Next step" as **"the one action"** — the single most important thing to do next — with "Waits for you" (approvals, blocking questions, *harness errors*, undecided run settings) as its supporting list carrying the same class of urgency. `t["next_doctor"]`/`next_doctor_d"` and `t["next_gaps"]`/`"next_gaps_d"` exist precisely to surface harness errors and blocking questions as *the* next step when they apply — INV-006 treats a doctor error as something `--ci` must fail on, and `SKILL.md` for `project-new` says a blocking gap "can stay open only if the user explicitly accepts them," i.e. approving over one is a distinct, deliberate action, not the default "review and approve."
- **Observed:** On this repo, `next` is `{"title": "Revisá la etapa «Contexto» y aprobala", "command": None, "anchor": "stage-intake"}` — "Review the Context stage and approve it" — with no mention of the 16 harness errors or the harness being a version behind, even though `waiting` (the secondary list) does list both (`"16 errores del harness para revisar"`, `"Actualizar el harness: v0.7.0 → v0.7.1"`). On the synthetic fixture, `next` is `{"title": 'Review the "Context" stage and approve it', ...}` while the blocking gap (`GAP-001`, `blocking: yes`) is silently omitted from the one recommended action, appearing only in `waiting`. In both cases the single, most-prominent piece of guidance the dashboard gives ("the one action") tells the reader to simply approve, hiding that there is more urgent or qualifying information available one line below it in the same JSON/page.
- **Evidence:**
  ```
  $ cd /home/user/keelokit && python3 skills/project-dashboard/scripts/dashboard.py --json | python3 -c "
  import json,sys; d=json.load(sys.stdin)
  print('next=', d['next']); print('waiting=', d['waiting']); print('errors=', d['errors'])"
  next= {'title': 'Revisá la etapa «Contexto» y aprobala', 'detail': 'Todo lo que hay que mirar está en su sección de este tablero.', 'command': None, 'anchor': 'stage-intake'}
  waiting= [{'text': 'Aprobar «Contexto»', ...}, {'text': '16 errores del harness para revisar', 'anchor': 'health'}, {'text': 'Actualizar el harness: v0.7.0 → v0.7.1', 'anchor': 'decisions', ...}]
  errors= 16
  ```
  Synthetic (context files complete, one `Blocking: yes` gap, intake status "review"):
  ```
  next= {'title': 'Review the "Context" stage and approve it', 'detail': 'Everything to look at is in its section of this dashboard.', 'command': None, 'anchor': 'stage-intake'}
  waiting= [{'text': 'Approve "Context"', ...}, {'text': 'GAP-001: What is X?', 'anchor': 'stage-intake', 'ask': 'Answer to GAP-001: ', 'act': 'Answer'}]
  ```
- **Where:** `skills/project-dashboard/scripts/dashboard.py:989-1005` (`next_step`): the `if s["pending"]:` branch (`:993`) returns at `:996-997` (review) or `:998-999` (current) unconditionally, before `if s["errors"]:` (`:1000`) or `if blocking:` (`:1003`) are ever reached — both of those branches, and the `behind(s)` check used lower in `waiting_on_user`, are dead code for the "next" recommendation whenever any stage is not yet fully approved, which is true for nearly every project that hasn't finished its backlog stage.
- **Root cause (probable):** `next_step()`'s branches are ordered by stage progression (pending → errors → blocking gaps → build) rather than by urgency; "a stage is waiting for review or in progress" was written as the first, unconditional check instead of being merged with (or placed after) the errors/blocking-gap checks it can otherwise never reach.
- **Class:** consistency
- **Should have been caught by:** a `tests/test_dashboard.py` case asserting `next_step()`'s title/command when `s["errors"] > 0` (or `blocking`) is combined with a stage in "review"/"current" status — the existing tests exercise `s["errors"]` and blocking gaps against an *otherwise-idle* project (no stage mid-flow), and exercise "review" status against a project with no doctor errors, but never the two together, which is precisely this repo's own everyday state.
- **Proposed fix:** move the `s["errors"]` (and, for intake specifically, the `blocking` gaps) check ahead of the `s["pending"]` branch in `next_step()` — or fold them into it, e.g. surface `next_doctor`/`next_gaps` first and only fall through to "review/continue this stage" once there are no outstanding errors or blocking gaps, matching how `waiting_on_user()` already ranks them.

### LOG-304 · A story that touches a critical area without declaring `integrity` stops being flagged forever the moment it merges (P1)
- **Persona / context:** Any project with `.keelokit/critical.toml` areas (the invariant this repo itself documents: "a story that touches an area declares the `integrity` dimension… doctor.py and `doctor --scope` check it"); a developer or agent that merges a critical-path story without running `--scope` first (or whose CI `checks` job — one of the ERRORs this very repo's doctor already reports as missing — never ran `--scope` at all). HEAD fcbbee7, scratch fixture built from a copy of `.keelokit/bin/doctor.py`.
- **Steps:**
  1. Fixture repo with `.keelokit/critical.toml` declaring area `billing` at `apps/api/src/billing/`, and story `PAY-001` (no `integrity` dimension, no `invariants`) whose `touches` is `apps/api/src/billing/charge.ts`.
  2. `python3 .keelokit/bin/doctor.py --ci` → exit 1, `ERROR story PAY-001: touches critical area billing — declare 'integrity' and the invariants it must keep` (correct, matches critical.toml's own documented contract).
  3. Create `apps/api/src/billing/charge.ts`, commit it with trailer `Story: PAY-001` on `main` (simulating the merge that makes the story "done").
  4. Re-run `python3 .keelokit/bin/doctor.py --ci`.
- **Expected:** Per `.keelokit/critical.toml`'s own header comment, this check exists so that code moving money (or otherwise critical) always carries the `integrity` dimension and its invariants — a guarantee that should hold for code that has actually shipped even more than for code still in the backlog; nothing in `rules.toml`/`critical.toml`/`AGENTS.md` suggests the guarantee lapses once a story merges.
- **Observed:** After the commit, the exact same error disappears from every mode (`doctor.py`, `--ci`, `--brief`) and never reappears — `doctor --ci` now exits 1 only for the unrelated "acceptance criteria need scenario ids" error on the first run and drops to exit 0/clean on subsequent runs once that's fixed too. The merged `PAY-001` story, whose code lives permanently in `apps/api/src/billing/`, is never flagged again for lacking `integrity`/invariants — the backlog-wide scan (the one `--brief`'s SessionStart hook and a `checks` CI job would run) has no memory that this gap exists once the story is "done." Only the pre-merge, per-branch `check_scope()` (`--scope <ID>`) still catches it, and only if it is actually invoked before the merge.
- **Evidence:**
  ```
  $ python3 .keelokit/bin/doctor.py --ci   # PAY-001 still pending
    ERROR story PAY-001: touches critical area billing — declare 'integrity' and the invariants it must keep
  exit=1

  $ git commit -qm "feat: charge

  Story: PAY-001"
  $ python3 .keelokit/bin/doctor.py --ci   # PAY-001 now "done" via the Story: trailer on main
    ERROR story PAY-001: acceptance criteria need scenario ids, e.g. 'Scenario: [S1] …'
  # the critical-area ERROR line is gone; the story's lack of `integrity`/invariants is no longer reported at all
  ```
- **Where:** `.keelokit/bin/doctor.py:745-746` (`check_backlog`): `if sid not in done and (hit := areas_hit(...)) and "integrity" not in (dims or []):` — the `sid not in done` guard silently drops the check for any story once it has a `Story:` trailer reachable from `main`. The parallel invariant checks at `:766-775` (`TRACE-1`/`INV-1`) only re-check invariants the story *already declared*, so a story with zero declared invariants (this case) has nothing left checking it post-merge.
- **Root cause (probable):** The `sid not in done` guard was written to stop nagging about *pending* stories once they ship (reasonable for the wave-clash check, which is genuinely moot after merge), but it was applied uniformly to the critical-area/integrity check too, which is a property of the *shipped code*, not of the story's pending status — it should hold for as long as the code exists in a critical path, done or not.
- **Class:** isolation (a critical area's isolation guarantee — that it always carries its invariants and `integrity` — must hold after merge, not just before)
- **Should have been caught by:** a `tests/test_doctor.py` case for `check_backlog` that marks a critical-area story "done" (a commit with its `Story:` trailer) and re-asserts the integrity error is still present — the existing tests for this check (per the earlier grep for `areas_hit`/`critical`) only exercise the pending-story path.
- **Proposed fix:** drop the `sid not in done` condition from the critical-area/integrity check specifically (keep it for the wave-clash check, where it's correct), so `check_backlog` keeps flagging any story — done or pending — whose `touches` overlap a critical area without declaring `integrity` and its invariants, for as long as the story file and its `touches` exist in the backlog.
