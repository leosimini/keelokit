+++
id = "HARN-004"
epic = "HARN"
title = "Opening a repo doesn't run its own copy of the guard and the doctor unchecked"
wave = 3
depends_on = []
touches = ["hooks/hooks.json", "hooks/trusted.py", "template/.keelokit/bin/ledger.py", ".keelokit/bin/ledger.py", "template/.keelokit/bin/ux_gate.py", "template/.keelokit/bin/guard.py", ".keelokit/bin/guard.py", "template/.keelokit/bin/doctor.py", ".keelokit/bin/doctor.py", "tests/test_guard.py", "tests/test_doctor.py", "tests/test_hooks.py", "README.md", "CHANGELOG.md", "docs/design.md", "docs/escapes.md", "scripts/unit_shard.py"]
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

## Addendum — 2026-11-24
Chosen: a hybrid of B and C, with C's "run the project's copy" earned by a person's approval rather than by an
equal hash alone. `hooks/hooks.json` runs `hooks/trusted.py` (`python3 -I`, after a `cd` into the plugin), which
decides from bytes, before anything of the project runs:
1. the project's copy of what the hook runs (guard.py; ledger.py; doctor.py with the ledger.py and ux_gate.py it
   runs) is the plugin's byte for byte → the plugin's copy runs with `--root <project>` (S2: the same code, so the
   same answers; tests compare the hook's output with the project's own copy run by hand);
2. else, the project's whole `.keelokit/bin` as it is now (a fingerprint of every entry) was approved for this
   project on this machine with `trusted.py trust` → the project's copy runs, from the bytes that were checked;
3. else → the plugin's copy runs against the project's data, and the session start says so in one line (S1).
Why not B alone: an older harness or a project that changed its doctor in code would silently get another doctor;
here it is told, once, and chooses (upgrade, or approve its copy). Why not C alone: an equal hash proves nothing a
person decided, and on a mismatch C still needs B to keep the rules enforced. The Swarm's trusted tool code
(enjambre protocol §28) is the model for the store, `-I` and the escaped diff; it was not read, its summary was.

How the cases in the brief come out:
- **Older harness.** The plugin's newer doctor may report checks the older harness lacks (this repo itself: its
  own doctor is older than the template's), and the newer guard enforces at least what the older one did. The
  session-start line names the files and both ways out. It is said at the session start only, never per tool
  call, which answers C's noise.
- **`rules.local.toml` and the rest of the data** are read from `--root`, so customised rules work unchanged
  (test: the doctor with `--root` and the project's own doctor give the same report on a project with a local
  rule). A doctor customised in code is case 2.
- **Offline.** The check reads local files only; nothing new touches the network (`ledger.py history --ensure`
  fetches as before and says so when it can't).
- **Codex and other agents.** The plugin ships Claude Code hooks only; there is no Codex manifest. The git hooks
  (`.githooks`) still run the project's own copies, as its tests do: that is the project's code run by its own
  git, which the story's "Does NOT" leaves alone.
- **SessionStart budget.** One more short Python start (`check`) and its line counts in the 12-line budget;
  measured on a fresh project: 0.66–0.77 s before, 0.71–0.78 s after; PreToolUse 59–78 ms before, 65–70 ms after.

Beyond the spec: guard.py, ledger.py and ux_gate.py also take `--root` (the doctor runs them, and the hooks run
the ledger); the doctor runs the scripts next to itself (ESC-268); the guard refuses `trusted.py trust/untrust`
to agents (AGENT-1), and `trust` reads its answer from /dev/tty and asks for the fingerprint's first 8
characters. The breaker round's findings are ESC-268..270 (the doctor's children, relative PATH entries, a FIFO).
The launcher's tests are in tests/test_guard.py (`HooksRunTrustedCode`), the doctor's in tests/test_doctor.py.

Known limits, not fixed here: a repo that arrives with its own `.git/config` (an archive, not a clone) can still
make git run commands (core.fsmonitor, a remote's uploadpack) when the plugin's scripts run git: that is git's
trust model. Environment a repo's `.claude/settings.json` sets is behind Claude Code's own workspace-trust prompt;
trusted.py ignores PYTHON* variables, relative PATH entries and $HOME for the store, but an absolute PATH entry set
there is believed. The session start's "Where to look" line still tells the agent to run
`python3 .keelokit/bin/ledger.py show <ID>`, which an agent runs through its own Bash tool, under its permissions.
`trust` is a speed bump for an agent that fakes a terminal; such an agent already runs code.
