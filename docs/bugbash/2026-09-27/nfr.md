# nfr

Round 2 note: the round-2 nfr lens's first attempt did not run the bash (it answered only an
unrelated shell-recovery check). This is the actual round-2 pass: NFR-1..3 from the round-1 pass
below are re-verified fresh at 19b332e (all three still hold, refiled as NFR-101..103), and the
round-1 pass's one "not covered" item — exercising `workflows/check-bugbash-flow.js` at runtime —
is closed (NFR-104), including the maxParallel check.

### NFR-101 · `doctor.py`'s wave-clash check is O(n²) over pending stories, multi-second SessionStart stalls at a few thousand backlog items (P2)
- **Persona / context:** Any agent session in a generated/adopted project; `doctor.py --brief` runs on every SessionStart. Sha 19b332e, re-verified in a fresh scratch clone (round 2).
- **Steps:**
  1. Cloned `/home/user/keelokit` to a scratch dir, checked out `19b332e`.
  2. Built minimal fixture repos (`.keelokit/bin` + `docs/context` copied verbatim, `.keelokit/critical.toml` with just `mutation_break = 70`, and N generated `backlog/stories/NFR-XXXX-story.md` files with valid `+++ ... +++` TOML front matter — `id`, `wave`, `dimensions = ["logic"]`, `touches`, one `Scenario:` line each) at N = 500, 1000, 2000, all in `wave = 0`.
  3. `time python3 .keelokit/bin/doctor.py --brief` in each fixture.
  4. For contrast, the same 500 stories spread across 50 waves (10/wave).
- **Expected:** `--brief` is the SessionStart hook's fast path ("where am I / what's next"); its runtime should stay near-constant (or at worst linear) in backlog size, since it only prints four summary lines.
- **Observed:** 500 stories, 1 wave: 0.282s. 1000: 0.841s. 2000: 3.083s — roughly a 4× story-count increase (500→2000) costing an ~11× time increase, i.e. quadratic, not linear. The same 500 stories spread over 50 waves: 0.128s — no blow-up, confirming the cost is concentrated in same-wave pairs, not backlog size per se.
- **Evidence:**
  ```
  # 500 stories, wave 0
  real 0m0.282s
  # 1000 stories, wave 0
  real 0m0.841s
  # 2000 stories, wave 0
  real 0m3.083s
  # 500 stories, 50 waves (10/wave)
  real 0m0.128s
  $ tail -3 /tmp/out_2000.txt (2000-story, 1-wave fixture)
  Keelokit: gate pending → intake
  Context gaps: 3 (0 blocking) · Backlog: 0/2000 done
  Next ready stories: NFR-0000, NFR-0001, NFR-0002
  Harness errors: 2000 — run `pnpm doctor`
  ```
  (fixture generator and raw fixtures: scratchpad `nfr2/gen_fixture.sh`, `nfr2/fixtures/w1_{500,1000,2000}`, `nfr2/fixtures/w50_500`)
- **Where:** `.keelokit/bin/doctor.py:462-472` (`check_backlog`): `pending = [s for s in stories if s not in done]` then `for i, a in enumerate(pending): for b in pending[i+1:]:`, computing `overlaps()`/`areas_hit()` for every pair of pending stories sharing a wave. `main()` calls `check_backlog()` unconditionally at `doctor.py:564`, before the `if mode == "--brief":` branch at `:571`, so `--brief` pays the full cost of a check whose output it never prints.
- **Root cause (probable):** The wave/critical-area clash check is a naive all-pairs comparison instead of bucketing by `wave` first, and `--brief` shares the same `main()` prelude as the full report instead of a genuinely lightweight path.
- **Class:** limit
- **Should have been caught by:** A perf/volume test for `doctor.py --brief` on a seeded large backlog — dimensions.md's own `nfr` row calls for "perf budget on seeded volume"; none exists in `tests/`.
- **Proposed fix:** Bucket `pending` by `wave` (`dict[wave, list]`) before the nested comparison so the O(n²) cost is paid only within a wave; skip `check_backlog`'s clash detection in `--brief` mode since its result isn't used there.

### NFR-102 · check-bugbash's per-date output folder ("-2, -3…") is a check-then-create race with no lock — two concurrent runs on the same day can silently drop one run's whole report (P2)
- **Persona / context:** Two bug-bash runs (or a Prepare phase overlapping in time with another one) started on the same date, same repo. Re-read at 19b332e (round 2) — unchanged from round 1.
- **Steps:**
  1. Re-read `workflows/check-bugbash-flow.js:136`: the Prepare-phase agent is still instructed only in plain language to pick "Output folder: docs/bugbash/DATE (create it; if it already exists add -2, -3…)" — no code-level lock; `plan.outDir` from the agent's free-text decision is used verbatim later (`:185`, `:295`, `:336`, `:353`), with no re-check immediately before the first write.
  2. Reproduced the underlying mechanism standalone (no `Workflow` tool available to run two real Prepare phases): two processes each check whether `docs/bugbash/DATE` exists, decide their folder (bumping to `-2`, `-3`… if not), do simulated "thinking" work (`sleep 0.3`, standing in for the several reads a real Prepare agent does between deciding the name and its first write), then `mkdir -p` and write their own `report.md`.
  3. Ran both concurrently.
- **Expected:** Each concurrent invocation on the same date gets its own `docs/bugbash/DATE[-N]` folder, per the documented `-2, -3…` rule, so no run's findings are lost.
- **Observed:** Both processes independently picked the same folder `docs/bugbash/2026-09-27` (neither had created it yet at check time); the second to finish overwrote the first's `report.md` — the first run's report is gone, unrecoverable.
- **Evidence:** `runA` and `runB` both print `picked docs/bugbash/2026-09-27`; final `report.md` contains only `runB`'s content. Code citation above confirms the mechanism is unchanged at 19b332e.
- **Where:** `workflows/check-bugbash-flow.js:136` (the folder-naming instruction to the Prepare agent; no `outDir` collision check anywhere else in the script).
- **Root cause (probable):** Uniqueness of `docs/bugbash/DATE[-N]` is delegated entirely to one subagent's free-text judgement with no atomic reservation (e.g. `mkdir` failing with `EEXIST` as the real arbiter) and no re-check right before the first write.
- **Class:** once
- **Should have been caught by:** dimensions.md's `nfr` row ("multiple instances (crons, locks)") — no test or check for this collision path.
- **Proposed fix:** Have the Prepare step actually attempt to create the directory (`mkdir` without `-p`, or an `O_EXCL` sentinel) and retry with the next suffix on failure, instead of a `test -d`-style check made stale by everything the agent does in between.

### NFR-103 · dashboard.py crashes with a raw Python traceback instead of a clean error when its output path isn't writable (P2)
- **Persona / context:** Anyone running `python3 skills/project-dashboard/scripts/dashboard.py` against a read-only checkout (mounted/reviewed copy, CI artifact, read-only volume). Re-verified at 19b332e (round 2) with a fresh real read-only bind mount (this sandbox runs as root, so `chmod` alone does not reproduce the failure).
- **Steps:**
  1. Built a minimal fixture repo (`.keelokit/bin` + `docs/context` copied from the clone, empty `backlog/stories`), committed it.
  2. `mount --bind <fixture> <target> && mount -o remount,ro,bind <target>`; confirmed with `touch <target>/x` → `Read-only file system`.
  3. `cd <target> && python3 .keelokit/bin/doctor.py [--brief]` and `python3 <clone>/skills/project-dashboard/scripts/dashboard.py --root <target>` (no `--out`, so it defaults inside the read-only tree).
- **Expected:** Reading a repo to produce a report shouldn't require write access to it; at minimum a clean message pointing at `--out`, matching `doctor.py`'s behaviour on the same read-only tree (verified again: `--brief` exits 0, full report exits 1, both cleanly, neither attempts a write).
- **Observed:** `dashboard.py` dies with an unhandled `OSError` traceback and exit code 1:
  ```
  Traceback (most recent call last):
    File ".../skills/project-dashboard/scripts/dashboard.py", line 1946, in <module>
      sys.exit(main())
    File ".../skills/project-dashboard/scripts/dashboard.py", line 1933, in main
      out.parent.mkdir(parents=True, exist_ok=True)
    File "/usr/lib/python3.11/pathlib.py", line 1116, in mkdir
      os.mkdir(self, mode)
  OSError: [Errno 30] Read-only file system: '.../.keelokit/out'
  ```
  (this run's fixture had no pre-existing `.keelokit/out`, so it dies one line earlier, at the `mkdir`, than round 1's fixture which had the directory already and died at `write_text`; both call sites are equally unguarded — see Where.)
- **Evidence:** command + full traceback above, `doctor.py --brief`/full both exit cleanly (0/1) on the same mount.
- **Where:** `skills/project-dashboard/scripts/dashboard.py:1933` (`out.parent.mkdir(...)`, unguarded) and `:1940` (`out.write_text(...)`, unguarded) — whichever is reached first fails the same way.
- **Root cause (probable):** No try/except around the final directory-create/write; the script assumes the repo it reads from is also writable.
- **Class:** other (robustness/error-handling)
- **Should have been caught by:** A test that runs `dashboard.py` against a non-writable target and asserts a clean, actionable exit — none exists.
- **Proposed fix:** Wrap the `mkdir` and `write_text` calls in a try/except that reports the path and suggests `--out <writable path>` or `--json`, exiting non-zero without a stack trace.

### NFR-104 · check-bugbash-flow.js's Fix phase is not resume-safe: an agent interrupted right after its `git commit` but before its structured result returns re-runs live on resume and commits the same fix a second time, with the report accounting for only one of the two commits (P0)
- **Persona / context:** Anyone resuming a `/keelokit:check-bugbash` run that was interrupted mid-Fix-phase (the documented "a run cut short resumes" promise), which is precisely when it matters most: Fix is the phase that leaves real, unreviewed commits on the working branch. This is the item round 1 explicitly listed as "not covered" (no `Workflow` tool in that session); closed this round with a real dynamic run.
- **Steps:**
  1. No `Workflow` tool is available in this session either (confirmed again via `ToolSearch`), so I built a faithful standalone harness (`nfr2/wf_test/runsim.mjs`) that loads the actual `workflows/check-bugbash-flow.js` from the 19b332e clone as an `AsyncFunction` body (only the leading `export` is stripped; the script's own code runs unmodified) and supplies `agent`/`log`/`phase`/`pipeline`/`parallel`/`budget`/`workflow` exactly as the workflow-authoring reference describes them, with `agent()` doing real work for each labelled call (matching the script's own `PLAN`/`SURVEY`/`VERDICT`/`CONSOLIDATED`/`FIXED`/`CHECKED`/`REPORT` shapes it destructures) against a real scratch git repo.
  2. Modelled the documented resume contract literally: a JSON journal records `{label, result}` for every `agent()` call that actually *returns*; on resume, `agent()` returns the journalled result for as long as the call sequence matches (the "longest unchanged prefix" semantics from the workflow-authoring skill), then falls through to live execution for the first uncached call onward.
  3. Ran the script once (`rounds: 1`, one lens `nfr`, one finding `NFR-101`, one Consolidate group sized `fix`). At the `fix NFR-101` agent call (the fixer), the stub does exactly what a real fixer does per the script's own instructions (`workflows/check-bugbash-flow.js:287-300`): writes the fix, `git add -A && git commit -m "fix(nfr): stub fix (NFR-101)"` — then, simulating an interruption *after* the commit lands but *before* `agent()` resolves, wrote the journal (which by construction does not include this still-pending call) and `process.exit(42)`.
  4. Re-ran the script ("resume") pointing at the same journal, no interruption this time.
- **Expected:** Per the plan's own "Story and bug bash loop" journey ("a run cut short resumes"), resuming should pick up exactly where it left off — one fix, one commit per confirmed root cause, matching the report's own accounting.
- **Observed:** Run 1: `plan` → `nfr` (survey) → `check NFR-101` (skeptic) → `merge` (consolidate) all ran live and were journalled; `fix NFR-101` ran live, really committed (`ab5da7b`), then the process exited before that call returned — so it is *not* in the journal. Resume: the four prior calls hit the cache (`[CACHE HIT]`) and returned instantly; `fix NFR-101` was not in the cache (correctly, by the documented model, since it never returned) so it ran live *again* — wrote `fix.txt` a second time and made a second, identical commit (`087bbfe`). `git log` on the scratch repo after resume:
  ```
  087bbfe fix(nfr): stub fix (NFR-101)
  ab5da7b fix(nfr): stub fix (NFR-101)
  5058626 init
  ```
  Both commits carry the exact same message and the same file diff (`fix.txt` gained two identical lines, one per attempt). The resumed run's final structured result (and hence what `Report` would write) lists exactly **one** `fixed` entry for `NFR-101`, with `commit: 087bbfe...` — the first commit `ab5da7b` is not mentioned anywhere in the workflow's own output, orphaned but permanently in the branch's history.
- **Evidence:**
  ```
  === RUN 1 (interrupted at fix NFR-101, right after `git commit`) ===
  == phase: Fix
    [LIVE] #5 label="fix NFR-101" phase=Fix
    [INTERRUPT] committed ab5da7b, now killing before agent() resolves
  exit=42
  $ git -C repo log --oneline
  ab5da7b fix(nfr): stub fix (NFR-101)
  5058626 init
  $ journal after run1 → ['plan', 'nfr', 'check NFR-101', 'merge']   # fix NFR-101 absent — never returned

  === RUN 2 (resume, same journal, no interruption) ===
  == phase: Fix
    [CACHE HIT] #0 plan · [CACHE HIT] #1 nfr · [CACHE HIT] #2 check NFR-101 · [CACHE HIT] #3 merge
    [LIVE] #5 label="fix NFR-101" phase=Fix        # re-ran from scratch, live
    [LIVE] #6 label="check fix NFR-101" phase=Fix
  [log] NFR-101: fixed
  $ git -C repo log --oneline
  087bbfe fix(nfr): stub fix (NFR-101)
  ab5da7b fix(nfr): stub fix (NFR-101)
  5058626 init
  $ cat repo/fix.txt
  fix attempt at fix NFR-101 (callIndex 5)
  fix attempt at fix NFR-101 (callIndex 5)
  --- final result ---
  "fixed": [ { "id": "NFR-101", ..., "commit": "087bbfe07647a8f918cd13d70d787a039dcfefae" } ]   # ab5da7b unmentioned
  ```
  Full harness, journals and both scratch repos: scratchpad `nfr2/wf_test/` (`runsim.mjs`, `journal.json`, `repo/`).
- **Where:** `workflows/check-bugbash-flow.js:287-300` (`fixed = await agent(...)`, the fix call whose prompt tells the fixer to make one real commit — `:296` "One commit: ... Don't push.") together with `:315-317` (the independent check that follows, which only inspects the *new* commit and has no way to know an earlier, uncached attempt already committed the same change) and `:270-330` (the `for (const g of groups)` Fix loop itself, which has no guard checking whether this root cause's fix already landed before invoking the fixer again).
- **Root cause (probable):** The workflow's resume model (cache by call position, "an `agent()` call that performs a real `git commit` but is interrupted before returning its structured result would not be cached and would re-run live from scratch on resume, with the working tree already carrying that commit" — exactly as the workflow-authoring reference itself warns) is sound for read-only or idempotent agent calls, but the Fix phase's fixer call is neither: it has an unconditional, non-idempotent side effect (a `git commit`) with no way for the re-run to detect "a commit for this root cause already exists" before making another one.
- **Class:** once (an automated side effect meant to happen once per root cause happens twice with no detection)
- **Should have been caught by:** dimensions.md's own `nfr` row ("idempotency… multiple instances") and the workflow-authoring skill's own documented resume caveat. `tests/test_workflows.py` does exist and does cover `check-bugbash-flow.js`, but only at the shape level: `test_meta` (phase/meta literal consistency), `test_body_is_replayable` (bans `Date.now`/`Math.random`/`new Date`/dynamic `import`/`require`), and `test_body_parses` (constructs the exact same `new AsyncFunction('agent','parallel','pipeline','phase','log','args','budget','workflow', body)` this finding's harness uses — but only to check it *compiles*, never calling it with a real `agent()`). Nothing executes the Fix loop's logic, let alone resume across an `agent()` call with a real side effect.
- **Proposed fix:** Before invoking the fixer for a group, check whether `git log` already has a commit whose trailer/message names this root cause's id since the branch point (or write a small sentinel — e.g. append the id to a `.keelokit/bugbash-fixed` file — inside the same commit) and skip straight to the independent check if one is found; more generally, treat any workflow step with a real side effect (commit, push, external write) as needing its own idempotency guard, since the cache-by-return-value model cannot protect a call that never returned.
- **Note:** distinct from CPY-1..5's already-reported `CPY-3` ("'A run cut short resumes' has no code path that captures or replays the workflow's runId") — that finding is about the *script* having no runId plumbing of its own; this finding is about what happens even when the surrounding *runtime's* documented, correct resume model (longest-cached-prefix) is used exactly as designed. The bug survives having a working resume mechanism.

## Checked, no finding (round 2)

- **`maxParallel` honoured in the Survey phase's `slot(limiter(MAX))` wrapping**: ran the real `check-bugbash-flow.js` (same harness as NFR-104) with 6 lens tasks and `args.maxParallel = 2` — instrumented concurrency counter around every `phase: 'Survey'` agent call peaked at exactly 2, never 3+, confirming `pipeline(tasks, task => survey(task, round), ...)` respects the shared `limiter(MAX)` (`workflows/check-bugbash-flow.js:28-39`, `:175`). Repeated with `maxParallel` unset (6 lenses, default `MAX = A.maxParallel || 4`, `:21`): peak concurrency was exactly 4. Matches the code by inspection and now by an actual concurrent run — no bug.
- **Fix-phase resume for calls that did complete** (`plan`, the lens survey, the skeptic check, the consolidate merge): all four hit the cache correctly on resume and returned instantly with no re-execution or side effects — resume itself is not broken in general, only the specific interrupted-mid-side-effect case (NFR-104).

## Not covered → closed this round

Round 1 listed as not covered: "Could not exercise `workflows/check-bugbash-flow.js` at runtime at all… maxParallel honouring… Resume-after-interruption for the Fix phase's retry loop… whether the re-run fixer notices and avoids double-fixing is unverified (could not execute)." All of this is now covered above (NFR-104, and the maxParallel checked-no-finding note) via a harness that runs the actual script under `node` with a stubbed but faithful `agent()`/`pipeline()`/cache implementation, since no `Workflow` tool is available in this session.

## Still not covered

- A live run through the real `Workflow` tool (still unavailable in this session) — the harness above is a faithful re-implementation of its documented `agent()`/`pipeline()`/resume contract read from the workflow-authoring skill, not the tool itself; if the real tool's cache keying, `limiter` interaction, or interrupt handling differs from what that skill documents, NFR-104 and the maxParallel check would need re-running against it.
- The Fix phase's *second-attempt* retry path (`workflows/check-bugbash-flow.js:271-329`, the `for (let attempt = 1; attempt <= 2; attempt++)` loop and its `undo ${g.id}` cleanup) under an interruption between attempt 1's rejection and attempt 2 — only the simpler single-attempt path was exercised.
- Two real concurrent `/keelokit:check-bugbash` invocations (as opposed to the standalone reproduction in NFR-102) — still blocked on the same missing `Workflow` tool.
