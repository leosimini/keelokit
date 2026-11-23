+++
id = "LEDGER-002"
epic = "LEDGER"
title = "The SessionStart hook completes the trunk's history"
wave = 6
depends_on = ["LEDGER-001"]
touches = ["template/.keelokit/bin/ledger.py", ".keelokit/bin/ledger.py", "hooks/hooks.json", "tests/test_ledger.py", "tests/test_hooks.py", "docs/design.md", "CHANGELOG.md"]
dimensions = ["logic", "dx", "nfr"]
invariants = []
origin = "docs/ledger.md — Mechanisms (SessionStart)"
+++
## Context
After LEDGER-001 a shallow clone reads as unknown. This story makes it rare: the plugin's SessionStart
hook completes the trunk's history before the doctor runs. It creates `ledger.py` with a single
subcommand, `history`; LEDGER-003 adds the rest.

The fetch brings commits only (`--filter=blob:none`), so a large repo does not pay for every old file.
GitHub accepts the filter; a server that does not (a local `file://` remote) gets a plain `--unshallow`.
The hook never blocks a session: a cut or offline fetch is one line and exit 0.

Does NOT do: read the CI snapshot (LEDGER-011); activate git hooks (LEDGER-009); print the ledger's
summary (LEDGER-007).

## User story
As a session that starts in a fresh, shallow clone, I want the trunk's history completed before I read
any state, so that the doctor and the dashboard can count.

## Acceptance criteria
```gherkin
Scenario: [S1] A shallow clone with network is completed
  Given a shallow clone and a reachable origin
  When `ledger.py history --ensure` runs
  Then the clone is no longer shallow and the doctor counts the done stories correctly

Scenario: [S2] Offline is one line and the session goes on
  Given a shallow clone and no network
  Then it prints one line ("offline: history incomplete") and exits 0
  And the doctor says unknown

Scenario: [S3] A server without filter support falls back
  Given a remote that does not accept --filter
  Then it runs `git fetch --unshallow origin <trunk>` with the same cap

Scenario: [S4] The cap cuts it
  Given a fetch that would take longer than `[ledger] history_seconds` (default 20)
  Then it stops at the cap, prints one line, exits 0, and the doctor says unknown

Scenario: [S5] A complete history fetches nothing extra
  Given a clone that is not shallow
  Then no unshallow fetch runs

Scenario: [S6] The hook runs it before the doctor
  Then hooks/hooks.json's SessionStart runs `ledger.py history --ensure` and then `doctor.py --brief`,
    with a timeout of history_seconds + 10, guarded like today when python3 or the file is missing
```

## Testable units
| Unit | Test type | File |
|---|---|---|
| shallow detection, filtered and plain unshallow, cap, offline | unit, with a local bare remote (file:// covers S3) and a simulated timeout | tests/test_ledger.py |
| the hook order and its guards | unit | tests/test_hooks.py |

## Definition of done
`scripts/verify.sh` green, every scenario covered by a test titled with its id, `docs/design.md`
mentions `ledger.py history`, a CHANGELOG line, `Story: LEDGER-002` trailer, addendum if the result
differs. Gate of phase 0 (docs/ledger.md, "Plan"): a person measures the hook on a fresh clone of a
large project and writes the time in the addendum.

## Addendum — 2026-11-23

Decided:
- `ledger.py history` reports only (exit 0 complete, 1 incomplete, 2 no git); `history --ensure` completes and
  always exits 0, with one `Keelokit:` line per outcome (completed with its time, `offline:` for a network error,
  `fetch failed:` with git's reason for anything else, `cut at <cap>s:`), and nothing when already complete.
- The fetch is `git fetch --filter=blob:none --unshallow origin <trunk> +refs/heads/<trunk>:refs/remotes/origin/<trunk>`:
  the explicit refspec gives a single-branch clone of another branch its `origin/<trunk>` (breaker, round 1).
  git ≥2.2x against a server without filter support warns and fetches unfiltered, which is the plain unshallow; a
  filter refused with an error gets a plain `git fetch --unshallow origin <trunk>` within the same budget.
- The filter config (`remote.origin.promisor`, `partialclonefilter`, `extensions.partialclone`) is restored to what it
  was before the run unless a filtered fetch the server honoured completed: a failed, cut or unfiltered fetch never
  turns the clone partial, and an honoured one keeps its promisor (removing it corrupted the clone: review, round 1).
- The cap is one budget for the whole operation, enforced on git's process group (SIGTERM, 2 s grace, SIGKILL), so no
  lock or helper outlives it. `history_seconds` (default 20; non-numbers, inf and nan fall back to it) is capped at
  20, because the hook's timeout is fixed at 30 s in hooks/hooks.json and the doctor runs after it.
- git never prompts: GIT_TERMINAL_PROMPT=0, askpass routes neutralised, `credential.interactive=never`,
  GCM_INTERACTIVE=never, stdin closed, its own session.
- Trunk: `[ledger] trunk`, else `[harbor] trunk`, else `main`; a name git would read as an option or not a branch
  name gives one line and no fetch.

Measured (phase-0 gate, by verifier B in a cloud session through the proxy, not yet by a person): a `--depth 30`
clone of this repo goes from "Backlog: unknown" to "17/41 done" (the full clone's count) in 1.1 s;
psf/requests `--depth 1`: 6 496 commits in 1.3 s; git/git `--depth 1`: cut at 20 s, and the same fetch by hand
finished in 14 s afterwards, so very large repos sit near the cap.
Phase-0 gate, decided by the coordinator (2026-11-23): the hook's 20 s cap and the doctor's unknown fallback are the
guarantee (git/git `--depth 1` hit the cap and the session stayed unblocked); a timing on a large repo is recorded
here when one is measured.

Escape rows ESC-055..059 are in docs/escapes.md; to commit them, ESC-052's and ESC-045's example URLs were reworded
without a literal password (the guard's SEC-1 rightly flagged them; coordinator's decision). Left out: a SIGKILL of ledger.py itself between a filtered pack and the shallow update is not covered.
