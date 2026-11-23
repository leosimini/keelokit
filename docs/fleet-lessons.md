# Lessons from the JOUNA fleet (November 2026) — what Keelokit, Harbor and Swarm take

On the night of 2026-11-22 the JOUNA project ran about 40 sessions on two accounts and three trains
(39, 40, 41). Its coordinator wrote down what it learned, with measured impact, in the Claude doc
*Aprendizajes de coordinación multiagente (JOUNA, noviembre 2026)*. This file maps each lesson to where
it already lives, where it is planned, or the new story that takes it. The ledger epic is in
[ledger.md](ledger.md); this file adds the `FLEET` epic (Keelokit) and Harbor's phase 7
(`docs/lessons-phase7.md` in leosimini/keelokit-harbor).

The main finding of the mapping: **much of what JOUNA learned the hard way is already in Keelokit and
Harbor**, and JOUNA did not get it because it runs its own `verify --piece`, its own trains and a
hand-kept board instead of Keelokit's verify and Harbor's convoys. So part of the value is in JOUNA
adopting what exists; the rest is new work below.

## The mapping

| # | JOUNA's lesson (measured impact) | Already in Keelokit / Harbor | Planned | New |
|---|---|---|---|---|
| 1 | Instability is the biggest cost: memory kills and intermittent tests (~15 h in one night) | Keelokit names a memory kill after the fact (`verify_tools.py` causes `heap`, `killed`); FLAKY-1 (never skip, retry or lengthen); `red-causes.toml`; preflight refuses a busy machine (load, another test run) | — | **FLEET-001** (memory-aware workers, peak memory per step); **FLEET-003** (tests that stay green: harvest `stable-tests.md`, arch-specs and `flaky.sh` from the unmerged branch `claude/orquestador-y-verify`, plus two rules JOUNA found) |
| 2 | Re-verifying a verified piece found nothing (0 of ~30) | Harbor rule 2: a vessel is verified once, its seal is reused, a one-vessel convoy sails on the vessel's seal | — | — |
| 3 | A piece-scoped run of the train's union before `--all` repeats work (~2 h per train) | Harbor rule 1 scopes the convoy verify by its diff and treats `--all` as the exception | — | **HRB-4**: when the scoped plan already covers what `--all` would, the ok goes straight to `all`; never a scoped run and then `--all` |
| 4 | Before a resume, verify only the fix against the last verified head (3.5 h vs 10 min) | Harbor rule 3 with Keelokit's `--rerun-failed`: the fix's files are verified first, then the failed steps; a covering green is sealed as composite | — | — (JOUNA's own `--resume` is what lacks it) |
| 5 | Hand-made design critiques miss findings (3 of 3 missed P1/P2, two about money) | UX-3 gate: `CRITIQUE.md` with four sections, or `ux-gate: n/a` | — | **FLEET-004**: the critique comes from the design skills, and the gate checks it |
| 6 | Every train red was a seam between pieces or the environment (~9 seams, ~12 environment) | Harbor hotspots; `touches` and waves; `stable-tests.md` rule 8 (on the unmerged branch) | Early hotspot warning from `touches` (Harbor, designed) | **HRB-6** (a mechanical seam report at assemble); **FLEET-003** rule 11 (absence assertions live in one registry); FLEET-004 (one navigation component per section, in the UX consistency criteria) |
| 7 | State read by hand misleads (shallow clone, stale board) | — | The whole `LEDGER` epic (LEDGER-001, 002, 003, 010; HRB-1 `Convoy:`) | — |
| 8 | An idle session loses its container and its unpushed work (2 runs lost) | WIP-1 (`wip/` branches); Harbor's handover (only pushed work is handed over); Swarm 26.4 | — | **FLEET-006**: push before any long wait, wait in the background on the verify's state |
| 9 | Money bugs live in failure paths (2 pre-existing refund bugs) | Invariant classes and the breaker (`integrity`); COPY-1 | — | **FLEET-005**: the breaker walks every failure path of a money story; the copy check asks whether a text can make someone move money twice |

Coordination lessons:

| Lesson | Already | New |
|---|---|---|
| Rounds every 25–30 min, scheduled with a self-contained prompt, survived context compaction and a night unattended | Harbor's control round (`control_every_minutes = 90`); `coordinate` every ~15 min | **HRB-8**: default 30 min; the scheduled prompt holds commands (`ledger.py`, `harbor.py log`), not a pasted state |
| An independent check before every push to main (parents, author, commit count, `wip/`, expected diff), 1 min | Harbor `sail`: green seal on the exact head and the harbormaster's ok | **HRB-5**: a mechanical sail preflight |
| Hour cutoffs with a clear rule of what is mandatory | Harbor `convoy defer` (by hand) | **HRB-7**: a cutoff time; optional vessels late at the cutoff are deferred by themselves |
| No direct messages between accounts; a stale board copy made one account think nobody coordinated | Harbor 0.3: `msg send`, the watcher (13 s measured), the dispatcher, fresh reads | — (JOUNA adopting `/harbor:dispatch`) |
| Sessions waited on the wrong log text and went silent (50 min lost with a green verify) | Agent brief: read the result from the exit code and `status.py`, never by searching the log | FLEET-006 removes "a log line" from the brief's list of things to wait on |
| Long verifies always took longer than estimated | `keelokit-verify.history` keeps seconds per step | **FLEET-002**: the verify says how long it will take, as a range |
| Subagents tried `--no-verify` | The guard blocks it, prefixes included | FLEET-006: every delegated prompt says it |
| Archive each session when it delivers | Swarm helpers archive themselves | FLEET-006: the agent brief says it for cloud sessions |
| Short subagents for critiques and audits (3–5 min) | `check-bugbash-flow`, LEDGER-015's review | FLEET-004 uses one when the session lacks the design skills |
| Cherry-pick a piece's own commits into the train, never merge, so no `wip/` commit enters | Keelokit's pre-push refuses a push holding an unproven `wip/` tip | — (Harbor merges vessel branches; `convoy add` refusing a branch with a `wip/` tip is already in Harbor's proposals) |

What stays JOUNA's own (it is not Keelokit's verify): the related-test map computed once and shared by
four integration shards, with an equivalence test; the central list of closed routes as JOUNA writes it;
the two refund fixes.

**GitHub Issues.** JOUNA's document still points to the Issues-based registry of its first proposal. That
was replaced by the ledger, derived from git, with no Issues (see [ledger.md](ledger.md)).

## Order

JOUNA's evidence is that instability costs more than anything else, so stability goes right after the
ledger's phase 0 (both are small), before the ledger's phase 1:

1. LEDGER-001, LEDGER-002 (phase 0: read the history right).
2. FLEET-001, FLEET-003 (memory and tests that stay green).
3. LEDGER phase 1 (003, 004, 015, 005, 006, 007) → Keelokit 0.15.0, with FLEET-001 and 003.
4. FLEET-002, FLEET-004, FLEET-005, then LEDGER phase 2 (008–012), then FLEET-006 (it touches the agent
   brief after LEDGER-007 and 008) → Keelokit 0.16.0.
5. Harbor: HRB-4 and HRB-5 do not need the ledger and start at once, in parallel with Keelokit; HRB-1, 2, 3
   after Keelokit 0.16.0; HRB-6, 7, 8 after. Swarm's SWM-1..3 start at once, in parallel.

The `FLEET` stories carry waves 20 to 25 so no wave shares a file with another story; the order to build
is the list above, not the wave numbers.
