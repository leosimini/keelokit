# Epics

| Epic | Goal | Serves | Outside it |
|---|---|---|---|
| HARN | Keelokit's own harness holds it to the rules it gives projects: every rule checked, the checks themselves tested | product.md — generated projects pass on the first run; escapes fall release over release | New skills or template features |
| LEDGER | Every session, new or not, knows what is being done and what was done, from facts in git and never from a hand-kept state (docs/ledger.md) | product.md — generated projects pass on the first run; the agents that build them don't redo work | GitHub Issues and Projects; Harbor's and Swarm's own changes (their repos) |
| FLEET | What the JOUNA fleet paid for in one night (memory kills, intermittent tests, critiques without the skills, money failure paths, waiting habits) stops costing anyone again (docs/fleet-lessons.md) | product.md — generated projects pass on the first run; parallel sessions don't lose hours | JOUNA's own verify (its shared related map), Harbor's convoy changes (its repo) |

## Wave 1

| Story | Title | Depends on | Touches |
|---|---|---|---|
| HARN-001 | Mutation testing for the guard and the doctor | — | scripts/mutation.sh, .github/workflows/mutation.yml, .keelokit/critical.toml, .keelokit/exceptions.toml |
| HARN-003 | An exception can cover only some paths, and the guard honours it | — | template/.keelokit/bin/guard.py, .keelokit/bin/guard.py, template/.keelokit/bin/doctor.py, .keelokit/bin/doctor.py, tests/test_guard.py, tests/test_doctor.py |

## Wave 2

| Story | Title | Depends on | Touches |
|---|---|---|---|
| HARN-002 | The lint enforcer check reads what a config really enables | — | template/.keelokit/bin/doctor.py, .keelokit/bin/doctor.py, tests/test_doctor.py |

## Wave 3

| Story | Title | Depends on | Touches |
|---|---|---|---|
| HARN-004 | Opening a repo doesn't run its own copy of the guard and the doctor unchecked | — | hooks/hooks.json, template/.keelokit/bin/guard.py, .keelokit/bin/guard.py, template/.keelokit/bin/doctor.py, .keelokit/bin/doctor.py, tests/test_guard.py, tests/test_doctor.py |

## Wave 4

| Story | Title | Depends on | Touches |
|---|---|---|---|
| HARN-020 | The guard reads a variable reference as no secret, and a product can register paths SEC-1 and SEC-2 let through | — | template/.keelokit/bin/guard.py, template/.keelokit/bin/doctor.py, template/.keelokit/guard-allow.toml, copier.yml, tests/ |

Collisions resolved: HARN-002 moved to wave 2 and HARN-004 to wave 3 because they touch the doctor and its tests, as HARN-003 does.

## LEDGER (docs/ledger.md)

One story per wave: almost all of them touch `ledger.py` or the doctor, and this repo builds serially.

| Wave | Story | Title | Depends on |
|---|---|---|---|
| 5 | LEDGER-001 | With an incomplete history, the doctor and the dashboard say unknown | — |
| 6 | LEDGER-002 | The SessionStart hook completes the trunk's history | LEDGER-001 |
| 7 | LEDGER-003 | ledger.py computes every story's state from git | LEDGER-002 |
| 8 | LEDGER-004 | Approved corrections and a backfill for the history that has no trailers | LEDGER-003 |
| 9 | LEDGER-015 | Corrections can be approved by agents, with an adversarial review, when the person delegates it | LEDGER-004 |
| 10 | LEDGER-005 | ledger.py show, next and check, with the why of every story | LEDGER-015 |
| 11 | LEDGER-006 | The doctor, the dashboard and the skills read the ledger | LEDGER-005 |
| 12 | LEDGER-007 | A new session knows where the truth is | LEDGER-006 |
| 13 | LEDGER-008 | ledger.py take and drop: the story a worktree works on, and abandoned attempts | LEDGER-007 |
| 14 | LEDGER-009 | prepare-commit-msg writes Part-of:, commit-msg checks the trailers | LEDGER-008 |
| 15 | LEDGER-010 | Pre-push and CI: nothing unattributed reaches the trunk | LEDGER-009 |
| 16 | LEDGER-011 | The CI snapshot, the time each commit reached the trunk, and the deploy branches | LEDGER-010 |
| 17 | LEDGER-012 | Rule LEDGER-1, and the doctor checks that its enforcers are alive | LEDGER-011 |
| 18 | LEDGER-013 | The ledger reads Harbor's logbook | LEDGER-012 |
| 19 | LEDGER-014 | The ledger sees the swarm's deliveries | LEDGER-013 |

Harbor's HRB-1..3 (`docs/ledger-phase6.md` in keelokit-harbor) and Swarm's SWM-1..3 (`docs/ledger-refs.md` in enjambre) are built in their repos; LEDGER-013 waits for HRB-2 and LEDGER-014 for SWM-2.

## FLEET (docs/fleet-lessons.md)

Build order (not the wave order): FLEET-001 and FLEET-003 right after LEDGER-002; FLEET-002, 004, 005 after the ledger's phase 1; FLEET-006 after LEDGER-008.

| Wave | Story | Title | Depends on |
|---|---|---|---|
| 20 | FLEET-001 | The verify fits its test workers to the memory the machine has, and records what each step used | — |
| 21 | FLEET-002 | The verify says how long it will take, as a range from its own history | FLEET-001 |
| 22 | FLEET-003 | Tests that stay green: stable-tests rules, arch-specs and flaky.sh reach main, with JOUNA's two rules | — |
| 23 | FLEET-004 | The design critique comes from the design skills, and the UX gate checks it | — |
| 24 | FLEET-005 | A money story's breaker walks every failure path, and its copy cannot make anyone move money twice | — |
| 25 | FLEET-006 | The agent brief takes the fleet's lessons: push before waiting, wait on state, ranges, archive, never --no-verify | LEDGER-008, FLEET-002 |
