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
