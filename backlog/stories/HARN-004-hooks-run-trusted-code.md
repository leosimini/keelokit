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
Chosen, in the end: B. The Claude hooks always run the plugin's own copy of the guard, the ledger and the doctor,
with `--root <project>`, against the project's data. `hooks/hooks.json` runs `hooks/trusted.py` (`python3 -I`,
after a `cd` into the plugin); nothing of the project's executes, its `.keelokit/bin` is only read to say at the
session start, in one line, that it differs (S1). A project on the plugin's version gets the same code and so the
same answers (S2; the tests compare the hook's output with the project's own copy run by hand).

How it got there. The first build was a hybrid of B and C: the project's copy ran when a person had approved it
with `trusted.py trust` (a per-machine store, a fingerprint, a terminal prompt), modelled on the Swarm's trusted
tool code. Three breaker rounds (ESC-268..279) showed the approval had too many edges: an agent with a shell, as
the same user, can always fake "a person at a terminal" (a pty it types into, a store it writes), and an approved
doctor still read its children from disk after the check. So the coordinator settled on B and dropped the approval
whole (ESC-278): nothing left to forge or race. Customised scripts still run when a person runs them, or from the
project's git hooks once the person turns them on; only the Claude hooks ignore them.

How the cases in the brief come out:
- **Older harness.** The plugin's newer doctor may report checks the older harness lacks (this repo's own doctor is
  older than the template's), and the newer guard enforces at least what the older one did. The session-start line
  names the files and points at `/keelokit:harness-upgrade`; it is said once per session, never per tool call.
- **`rules.local.toml` and the rest of the data** are read from `--root`, so customised rules work unchanged (a test
  compares the doctor with `--root` and the project's own doctor on a project with a local rule). A doctor
  customised in code is not run by the Claude hooks; the person runs it.
- **Offline.** Nothing new touches the network (`ledger.py history --ensure` fetches as before and says so when it
  can't).
- **Codex and other agents.** The plugin ships Claude Code hooks only; there is no Codex manifest.
- **SessionStart budget.** One more short Python start (`check`) and its line counts in the 12-line budget; measured
  on a fresh project: 0.66–0.77 s before, 0.71–0.78 s after; PreToolUse 59–78 ms before, 65–70 ms after (the
  guard's child process adds a fork).

Beyond the spec, from the breaker rounds:
- **Git hooks** (ESC-271, ESC-277). LEDGER-009.S7 turned `.githooks` on at the session start. That ran repo code:
  hooks of any content, then even the plugin's own hooks (they run `.keelokit/bin` without `-I`, where any module
  shadows the standard library), and a branch's own hooks after a switch. The plugin now never sets
  core.hooksPath; the session start says the hooks are off and how the person turns them on. The plugin's ledger and
  guard with `--root` run git with core.hooksPath=/dev/null, so our own fetches fire no repo hook even when the
  person turned them on. The doctor reads the hooks path to report it, and runs no git command that fires a hook.
- **The doctor's children** run from next to the doctor, with the same `--root` (ESC-268).
- **What runs** gets no PYTHON* variables and no relative PATH entries (ESC-269); files are read without blocking,
  so a FIFO can't hang a hook (ESC-270).
- **No fail-open by timeout** (ESC-276, ESC-279). Claude Code lets a call through when its PreToolUse hook outlives
  the timeout. The guard reads its data files without blocking and at most 1 MB, bounds its git calls (30 s, 1 MB of
  output), and its patterns are linear (a bounded look-ahead, disjoint options, an atomic group); and the hook runs
  the guard in a child process it waits for at most 45 s, then kills it and blocks. The hook states 60 s.
- **The plugin's own git** (ESC-280). A directory the repo ships can look like a bare repository to git, whose
  config then names a remote that runs a command (`ext::`) or a promisor remote fetched lazily. Every git call of
  the plugin's scripts with `--root`, and of trusted.py, runs with safe.bareRepository=explicit,
  protocol.ext.allow=never, core.fsmonitor=false, GIT_NO_LAZY_FETCH=1, GIT_TERMINAL_PROMPT=0,
  GIT_PROTOCOL_FROM_USER=0 and no GIT_DIR-like variables from the session (protocol.file.allow=always: local
  remotes, the tests' too, run nothing of the repo's); and only where the git dir is the project's .git or outside
  the project, else the guard blocks and the ledger and doctor say so and run no git. The doctor keeps the
  person's hooks path, which it reports.
- **Fail closed** (ESC-281). Any failure of the guard hook's own path (a failed fork, an exception, a guard that
  crashed, exited 1 or was killed) is exit 2 with one line.
- **The gate runs no git** (ESC-295, ESC-296). The guard runs where the tree has `.keelokit/`, or where a hook has
  seen it before: a marker in `~/.cache/keelokit/projects/<sha256 of the real path>` (the password database's
  home). A checkout, reset or branch rename can't switch it off, and with no git in the gate nothing can hang it
  before the watchdog. A same-user agent with arbitrary shell can still remove both: the accepted limit.
- **Where the guard runs** (ESC-282). In any project with `.keelokit/`, not only where `.keelokit/bin/guard.py`
  exists, which it never runs; the guard refuses commands that delete or move `.keelokit/` or its `bin/` whole.
  Removing `.keelokit/` makes it not a Keelokit project: the person's decision.
- **The guard's rules, read as the shell reads them** (ESC-283..294, three cold-breaker rounds). Quoted flags, a
  script given to `sh -c` or `eval`, every git config change (`-c`, `git config`, GIT_CONFIG_* in the environment,
  includes, aliases, `+` push refspecs), writes to .git/config and .git/hooks, and removing the harness (globs,
  `mv -t`, `$PWD`, an orphan branch: the hook also looks at origin/HEAD) or the plugin's own files. It is still a
  speed bump for an agent with a shell, as the guard's own docstring says: a variable or a script file gets past
  any lexical rule; CI and the person's review are the backstop. Also covered: `git mv` of the harness, `--orphan`,
  hooks the person turned on (and the guard.py and ledger.py they run), `--remove-section core`, the worktree config,
  `>|`, line continuations, Claude Code settings that disable hooks or the plugin. Known residue, left as it was:
  tool-driven writes (`vercel env pull .env.local`); false positives on `echo .env >> .gitignore`, `git rm --cached
  .env`, `.env.sample`-style names and `--force-if-includes` (LOG-4 blocks it on purpose).
  After the final cold breaker (ESC-297..300) also left: a project directory moved by other means than the guard
  sees (the hook then finds no project), `echo --no-verify | xargs git commit`, git's own cherry-pick of a stash
  commit (no pre-commit), `git config --get core.hooksPath` blocked (LOG-4's rule), a heredoc message that names the
  flag, and a guard that takes the full 45 s on a 20 000-option command before it blocks.
- guard, ledger and ux_gate take `--root` too, not only the doctor. The tests are in tests/test_guard.py
  (`HooksRunTrustedCode`, `HooksRunTrustedCodeRound2`), tests/test_doctor.py (`DoctorRootTest`) and
  tests/test_hooks.py.

Known limits, not fixed here: a repo that arrives with its own `.git/config` (an archive, not a clone) can still
make git run commands (core.fsmonitor, a remote's uploadpack) when the plugin's scripts run git: that is git's
trust model. Environment a repo's `.claude/settings.json` sets is behind Claude Code's own workspace-trust prompt;
trusted.py ignores PYTHON* variables and relative PATH entries, but an absolute PATH entry set there is believed.
The session start's "Where to look" line still tells the agent to run `python3 .keelokit/bin/ledger.py show <ID>`,
which an agent runs through its own Bash tool, under its permissions. Pushing runs the template's pre-push, i.e.
the project's verify, once the person has turned the hooks on: running its tests, which this story leaves alone.
