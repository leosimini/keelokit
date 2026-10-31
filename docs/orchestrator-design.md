# Orchestrator: design

How a Keelokit project keeps several parallel sessions on course without depending on any one of them
staying alive. Written from a real project that coordinated seven "trains" this way by hand; the
project's own names and rules stay out. Implemented in `template/.keelokit/bin/coord.py`, the
`/keelokit:orquestador` skill and `template/docs/convoys.md`.

## 1. What Claude Code gives us (docs checked 2026-10-31)

| Piece | Can | Cannot | Who triggers | If the session that created it dies | Consumes |
|---|---|---|---|---|---|
| **Skill** | Instructions loaded on demand; may register hooks for the session | Run by itself; keep state | The person or Claude | Nothing to lose: a file | Its description every turn; its body when invoked |
| **Plugin** | Bundle skills, agents, hooks, MCP servers | Load in a cloud session from *local* settings; project-scope settings do | The person installs it | Nothing: it lives in settings | Names and descriptions in every turn |
| **Hook** | Run a command at an event (`SessionStart`, `Stop`, `SubagentStop`, `PreToolUse`…); `PreToolUse` can deny | Fire when no session is running; block `SessionStart` | The lifecycle | Gone with the session (a subagent's, with the subagent) | Local time; command hooks use no model |
| **Subagent** | A role with its own context and tools; resumable by id | Outlive its parent's usefulness; nest forever (about 3 levels) | Claude, the person, `--agent` | Its transcript is kept; a reclaimed cloud session reports it as stopped | Its own requests, against the same limits |
| **Cloud scheduled task (routine)** | Start a **new session** on a schedule, one-time, API call or GitHub event | Run more often than hourly; reuse one session across runs | The schedule, the API token, GitHub | **Not tied to a session**: it belongs to the account and keeps firing | Same usage as an interactive session; hourly caps per account |
| **Session timers (`/loop`, cron in a session)** | Re-prompt the same session | Survive the session ending or the container being recycled | Claude or the person | Stop | The full context on every fire |
| **Cloud session** | Run unattended; keep its conversation after the VM is reclaimed | Keep running shell commands or session timers after a reclaim; keep files outside the repo | The person, a routine, a trigger | Conversation survives; the VM and its running processes do not | Shares the account's limits (5-hour and weekly windows) with every other session |
| **Messages between sessions** | Plain text to another session, arriving as a prompt | Carry files or history; be treated as the person's consent | Claude | Refused if the target is archived | Counts as a typed prompt on the receiver |

Not stated in the docs, so **tested or avoided** here: how long a cloud session may idle; what happens to
in-flight work when a usage limit hits; whether a session started by a routine can itself start or message
other sessions. The design therefore keeps every durable fact in git and treats session-to-session
messages as an accelerator, never as the only channel.

Findings from trying it (section 7): a routine created from a session carries **no repository sources** unless
given, and the session it starts has **none of the session tools** and no clone of a private repository.

## 2. Options

| Option | Idea | Survives the captain dying | Costs | Verdict |
|---|---|---|---|---|
| A. **A long-lived captain session** (what exists) | One session loops with its own timer | No: timers die with it | Its context grows until it degrades | The problem |
| B. **Logbook in git + a routine that revives the role** | State on a branch; an hourly fresh session runs `coord.py tick` and takes the watch if it expired | **Yes** | One tiny session per hour while idle | **Chosen** |
| C. Agent teams (experimental) | Claude's own multi-agent mode | No resume of teammates; experimental | About several times the usage | No |
| D. A server or bot outside Claude Code | A process that polls and starts sessions | Yes | New infrastructure to run and secure | Not for a plugin |

## 3. The design (option B)

- **Roles**: captain (holds the watch, decides, escalates), conductor (integrates one convoy, one verify, one
  push), worker (one piece). The tables are in `template/docs/convoys.md`. The captain never integrates and
  never decides what is the owner's: money, prices, fees, production, third-party accounts, legal data.
- **Durable state**, on the branch `coord/board` (a push there runs no CI and doesn't move main):
  `LEASE.json` (holder, since, heartbeat, expiry, epoch), `STATE.json` (convoys, pieces, sessions, usage-limit
  stops), `HANDOFF.md`, and generated `BOARD.md` and `convoys/<n>.md`. Nobody edits the generated files.
- **Taking the watch without two taking it**: `claim` writes `LEASE.json` and does a plain push. A second
  claimant's push is rejected (the branch moved), it refetches, sees a live holder and stands down.
  Tested with two clones racing at once (`tests/test_coord.py`). No force-push, ever.
- **Check-in and expiry**: the captain runs `heartbeat` at each control (at least every 90 minutes); the watch
  lasts 3 hours (`[coord] ttl_minutes`). An expired watch can be taken by anyone, including the next
  scheduled check.
- **Relief**: at a boundary (a convoy just sailed, about 4 hours of watch, or a control that read a lot), the
  captain writes a handoff of at most 40 lines and releases; the next one reads the handoff and the board and
  nothing else. This is how a captain with a lot of context hands a fresh one the role: **the handoff is the
  context**, so what is not in the board or the handoff is, by design, not needed.
- **Survival**: one hourly routine (fresh session per run, repository attached, push notifications on) runs
  `coord.py tick`. Usually `WATCH-OK`, ends in seconds. If the watch expired and the run has the session tools,
  it claims the watch, reads the handoff and runs a control; if it doesn't (the probe says it may not), it
  records `WATCH-LAPSED` in the logbook and the owner is told. It does not depend on the session that created
  it, nor on any session being alive.
- **Resuming stopped sessions**: the captain's control reads each session (`get_session`, `list_events`) and
  sends "continue where you stopped"; if a branch only lived in a container it asks for a push first.

## 4. Failures it has to survive

| Failure (all happened) | Detection | Response |
|---|---|---|
| Usage limit stops every session at once | Limit text in `list_events`; several `get_session` stopped together | `note-limit`; budget **high**; no new work; resume one at a time when the window resets, the convoy nearest to sailing first |
| A `verify --all` cut for lack of memory, unnoticed for 90 minutes | `keelokit-verify.state`: `running` with a dead pid → `status.py` prints **CUT** | Fewer sessions; `--preflight`; rerun detached with a log; judge by exit code |
| Main moves mid-convoy | The seal's base no longer matches; `git fetch` | Merge main into the convoy, read the seams again, verify again |
| Date bombs and new advisories turn main red | Nightly `clock` (clock a year ahead) and audit; `ci.py health` | First job of the captain: no convoy sails over a red main |
| A branch only in a container | `status.py` lists branches not on main; `ls-remote` lacks it | Push before anything else |
| Decisions that need the owner | A worker's question about money, production, accounts | One line in the board and in the report, with options and a recommendation; the rest keeps moving |

## 5. Budget

No monetary figures. `coord.py budget` returns **low / medium / high** from three signals: active sessions
against the cap (`[run] parallel`), usage-limit stops recorded in the last 3 and 24 hours, and a verify
running. High means start nothing and pause the convoy with the most pieces not ready. The honest limit: a
session cannot read the account's remaining allowance, so the warning comes from signs of trouble, not from
a balance. The person can add a rule of their own (for example, high from 5 hours into the window).

## 6. Stages

1. **Minimum, done in this branch**: the logbook and watch (`coord.py`), the skill, `status.py` and `report.py`,
   convoys with `ready` and `seam`, and the verify changes the orchestrator depends on (run state, seal,
   keep-going, preflight, load refusal, known causes).
2. **Next**: wire the scheduled check for a real project and watch it for a week (the probe below says what a
   routine's session can reach); tune the 3-hour expiry and the 4-hour relief to what that week shows.
3. **Later**: decide with data whether the captain should launch conductors itself; budget rules from the
   project's own limit history (`report.py`).

## 7. Probe

One routine, "Prueba orquestador", was created for a single run and deleted afterwards. Its prompt asked a fresh
session to look for `create_session`, `send_message`, `list_sessions`, `get_session` and `list_events`, to call two of
them, and to `git fetch` the logbook branch. Result, from its transcript:

- It searched for the tools twice and found none (only the unrelated in-session `SendMessage`).
- `/home/user` was not a repository and no `keelokit` folder existed (the routine was created with an empty
  `sources` list); a `git ls-remote` of the private repository returned nothing.

So a revival check cannot assume it can resume sessions, and cannot read the logbook unless the routine is
created with the repository as a source. The design was changed accordingly: `coord.py tick --observe-only`
records that the watch lapsed without taking it, the routine runs with push notifications so the owner hears
about it, and waking stopped sessions stays with a live captain (or a one-time routine fired into the stopped
session, which is what the project had done by hand). **Still to verify by hand,** because this probe could not:
a routine created in the claude.ai routines page *with* the repository attached (does it clone it, and with what
access to push the logbook branch?). Until then the minimum useful setup is: the captain keeps the watch alive,
the check tells the owner when it lapses.
