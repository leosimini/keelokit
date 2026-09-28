# Epics

| Epic | Goal | Serves | Outside it |
|---|---|---|---|
| HARN | Keelokit's own harness holds it to the rules it gives projects: every rule checked, the checks themselves tested | product.md — generated projects pass on the first run; escapes fall release over release | New skills or template features |

## Wave 1

| Story | Title | Depends on | Touches |
|---|---|---|---|
| HARN-001 | Mutation testing for the guard and the doctor | — | scripts/mutation.sh, .github/workflows/mutation.yml, .keelokit/critical.toml, .keelokit/exceptions.toml |
| HARN-003 | An exception can cover only some paths, and the guard honours it | — | template/.keelokit/bin/guard.py, .keelokit/bin/guard.py, template/.keelokit/bin/doctor.py, .keelokit/bin/doctor.py, tests/test_guard.py, tests/test_doctor.py |

## Wave 2

| Story | Title | Depends on | Touches |
|---|---|---|---|
| HARN-002 | The lint enforcer check reads what a config really enables | — | template/.keelokit/bin/doctor.py, .keelokit/bin/doctor.py, tests/test_doctor.py |

Collisions resolved: HARN-002 moved to wave 2 because it touches the doctor and its tests, as HARN-003 does.
