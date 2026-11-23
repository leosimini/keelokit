+++
id = "HARN-004"
epic = "HARN"
title = "Opening a repo doesn't run its own copy of the guard and the doctor unchecked"
wave = 3
depends_on = []
touches = ["hooks/hooks.json", "template/.keelokit/bin/guard.py", ".keelokit/bin/guard.py", "template/.keelokit/bin/doctor.py", ".keelokit/bin/doctor.py", "tests/test_guard.py", "tests/test_doctor.py"]
dimensions = ["security", "dx", "packaging"]
origin = "bugbash:2026-09-27 SEC-3"
+++
## Context
SEC-3: the plugin's hooks run the opened repo's own `.keelokit/bin/guard.py` and `doctor.py` on
every session and tool call, so a hostile repo runs its Python the moment its session starts.
0.8.1 documents it as the trust model (README, "Good to know"). This story removes the need for it.
Two ways, to choose when it's built:
- B: the hooks run the plugin's bundled copy against the project's rules and data (guard and
  doctor take `--root`); an older project then runs a newer script.
- C: the hooks compare the project's copy with the bundled one, run the project's only when they
  match, and otherwise warn and run the bundled copy; noisy on projects not upgraded yet.

Does NOT do: sandbox the project's tests or scripts (running a repo's code is still trusting it).

## User story
As someone who opens other people's repos with Keelokit on, I want the hooks to run code I
installed, so that opening a repo doesn't run code from it.

## Acceptance criteria
```gherkin
Scenario: [S1] A tampered project copy doesn't run
  Given a repo whose .keelokit/bin/guard.py differs from the plugin's
  When a session starts and a tool is called
  Then that file is not executed, and the rules are still enforced

Scenario: [S2] A project on the same version sees no change
  Given a repo whose .keelokit/bin/ matches the plugin's
  Then the guard and the doctor behave as today
```

## Testable units
| Unit | Test type | File |
|---|---|---|
| which copy the hooks run | unit | tests/test_guard.py |
| doctor with --root | unit | tests/test_doctor.py |

## Definition of done
`scripts/verify.sh` green, every scenario covered by a test titled with its id, `Story: HARN-004`
trailer on the completing commit, README's trust note updated.
