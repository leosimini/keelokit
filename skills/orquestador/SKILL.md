---
name: orquestador
description: Be the captain of a Keelokit project's parallel sessions, and hand the role over before the context goes stale or when the session dies. Keeps a logbook on the coord/board branch, convoys (waves that land with one verify and one push), a watch that expires, and a scheduled check that revives the role. Use when the user says "orquestador", "capitán", "coordiná los trenes", "convoy", "tomá la guardia", "relevo", "run the release train", "take over coordination", or when a scheduled check says TAKE-ROLE.
---

# Orquestador — the captain, the watch and the relief

Several sessions build in parallel. The captain keeps the plan, so that **no session is the only one
who knows it**: everything the next captain needs is in the logbook (`coord/board`) and a handoff of
at most 40 lines. Read `.keelokit/harness/agent-brief.md` and `docs/convoys.md` once. This skill is the
procedure; `python3 .keelokit/bin/coord.py` is the tool (it never forces a push, never touches main).

## Roles

| Role | Does | Never |
|---|---|---|
| **Captain** | Holds the watch; decides what enters each convoy and when it sails; gives the ok; resolves product decisions inside what the owner already decided; asks the owner the rest; watches the budget; hands over | Writes product code, integrates a convoy, pushes to main, decides what is the owner's |
| **Conductor** (one per convoy; a session the captain names) | Merges the pieces into `convoy/<n>`, `coord.py convoy seam`, cheap checks, `pnpm verify --all` with the ok, ONE push, then `coord.py convoy ship` | Pushes without the ok; leaves a piece out without a reason |
| **Worker** | One piece, on its own branch: tests by the verifier, review, captures; reports a hash (`review.py lint-report`) | Pushes to main; keeps work only in its container: the branch is pushed to the remote |

**What is the owner's** (ask, wait for a clear yes): money, prices, fees, production deploys and
data deletion, third-party accounts and their keys, legal data. Everything else the captain decides
and notes in the logbook. If the project has more owner-only items, they are in `docs/context/constraints.md`.

## Taking the watch (any session, any time)

```bash
python3 .keelokit/bin/coord.py tick --id <your session id>
```
- `WATCH-OK …` (exit 0): someone is on watch and checked in recently. **Do nothing**; end.
- `TAKE-ROLE` (exit 10): you hold the watch now (epoch N). The output has the previous captain's
  handoff and the board. Do the **first control** below.
- Exit 1: someone took it first. Go back to your own work.

The owner can name a captain at any time by opening a session with: "read `.claude/…`/this skill,
take the watch". What the owner says outranks the board.

## A control (first one on taking the role, then at least every 90 min; the watch lasts 3 h)

1. `python3 .keelokit/bin/status.py`: worktrees, branches not on main, the verify (`running`, `last pass`, `CUT`), CI of main, the board.
2. `python3 .keelokit/bin/coord.py heartbeat --id <you>` — **first**, so the watch doesn't lapse during the control.
3. Sessions: for each session in the board, `get_session` (status, `status_bucket`) and, when it looks stuck, `list_events` with `kinds=["assistant","result"]`.
   - **Stopped by a usage limit** (the events say so): `coord.py note-limit`, then go to *Budget*.
   - **Idle with a finished job**: do not wait for its message. Check its hash on its branch or on `origin/main`; "done" without a pushed commit is not done: `send_message` asking it to push.
   - **Idle in the middle** (the container was recycled; the conversation survives, running commands don't): `send_message` "continue where you stopped: `git status`, rerun what was cut" — and verify that its branch exists on the remote; if it only lived in the container, ask it to push it first.
   - **Archived / unreachable**: start a replacement from the board's note and the branch, `create_session`, and `coord.py session add`.
4. Convoys: `coord.py convoy ready N` for the open ones. When it passes, give the conductor the ok (`send_message`); when it lists what is missing, send each session what it owes.
5. Red main or two cancelled runs: `ci.py health`, `ci.py jobs`. Fix before starting more (a convoy that rebases onto a moving main and fails again costs a full run).
6. A verify that says `CUT`: find why (`log` path in `status.py`): out of memory → fewer sessions at once (*Budget*); then rerun with `nohup`.
7. Write what changed: `coord.py convoy …` / `session …`. The board is generated; never edit it by hand.
8. Anything for the owner: one line in the report with options and your recommendation.

## When main moves in the middle of a convoy

Someone else landed (the owner's docs, a fix, another convoy). The conductor merges `origin/main` into
`convoy/<n>`, **reads the seams again**, and runs `verify` again before pushing: a green verify on the old
base proves nothing about the new one. The seal does this by itself (the base is part of it). A rebase that
conflicts only on formatting keeps your content and runs `pnpm format`.

## Failures the plan has to survive

| What happens | How you notice | What the captain does |
|---|---|---|
| Usage limit stops every session at once | `list_events` shows the limit message; `get_session` of several at once | `note-limit`; stop starting work; when the window resets, resume the paused sessions one at a time, the convoy closest to sailing first |
| A verify cut (out of memory, killed) | `status.py`: `verify: CUT`; the state file says which step | Fewer parallel sessions; `pnpm verify --preflight`, then `nohup pnpm verify --all`; read its exit code, not a phrase in the log |
| Main moved | `status.py`, `git fetch` | See above |
| Date bomb or a new advisory turns main red with no code change | `ci.py health`; the nightly `clock` and `audit` runs | Fix before any convoy; a red main is the first job |
| A branch lives only in a container | `status.py` lists branches not on main; `git ls-remote` doesn't show it | Ask the owner session to push it (`git push origin <branch>`); never leave the only copy in a container |
| The captain dies or its context goes stale | No check-in for 3 h (`coord.py status` says EXPIRED) | The scheduled check below takes the watch; the handoff or the board is enough |
| A decision only the owner can make | A worker asks about money, prices, production, accounts | A line in the board's questions and one in your report; do not decide, do not stall the rest |

## Budget

`python3 .keelokit/bin/coord.py budget` says **low**, **medium** or **high** and what to do:
- **low**: room for more sessions, up to the cap (`[run] parallel` in `.keelokit/state.toml`).
- **medium**: start sessions one at a time, only if a convoy needs them.
- **high** (a usage limit stopped sessions in the last 3 hours, or more sessions than the cap are active): start nothing; pause the biggest open convoy (most pieces not ready) by telling its sessions to finish what they hold and stop; resume when it drops.
No amounts: the app doesn't expose a remaining balance to a session, so this is a proxy from what the board and the events show. Say "high" before the limit, not after.

## Relief — when the captain hands over

Rotate **at a boundary**, not in the middle: right after a convoy sails (`convoy ship`), or when you notice you
are losing the thread, or after about 4 hours of watch or a long control that read a lot. A fresh captain
beats a clever stale one.

1. Finish the control; leave convoys in a state the next one can read (`convoy` rows up to date).
2. Write the handoff (≤ 40 lines): decisions in force and who made them; what you are waiting for and from whom; open questions for the owner; sessions that need attention and why; the next three actions. Nothing the board already says.
3. `python3 .keelokit/bin/coord.py handoff --id <you> --note -` (stdin).
4. Start the next captain: `create_session` with the prompt "Read `.keelokit/harness/agent-brief.md` and the skill `/keelokit:orquestador`, then run `coord.py tick --id <your id>` and take the role"; or let the scheduled check do it within the hour.
5. Tell the sessions on the board who captains now only if the person asks; they read the board.

## Staying alive: the scheduled check

One recurring routine per project, hourly (the minimum), that starts a **fresh** session each time. It runs
`coord.py tick`: usually `WATCH-OK` and ends in seconds; when the watch expired it becomes the captain.
Create it once, after the first claim, with the **repository attached as a source** (without it the check has no
clone and cannot read the logbook), `create_new_session_on_fire = true`, `cron_expression = "0 * * * *"` and push
notifications on, so a lapsed watch reaches the owner's phone:

> Read `.keelokit/harness/agent-brief.md` and the skill `/keelokit:orquestador`. Run `python3 .keelokit/bin/coord.py tick --id <your session id> --observe-only` if you cannot start or message other sessions (no `create_session` / `send_message` tools), otherwise `… tick --id <your session id>`. If it prints WATCH-OK, stop and say nothing. If it prints TAKE-ROLE, you are the captain: do a control and continue the plan in the handoff. If it prints WATCH-LAPSED, say in one line that nobody is captain and a captain session is needed.

**What the probe found (2026-10-31):** a session started by a routine created through the remote-sessions tool, with
no sources, had **no** `create_session` / `send_message` / `list_sessions` tools, **no clone** of the repository
and no access to a private remote. So the revival check can guarantee only this: it reads the logbook (if given
the repository), and either takes the role (when it does have the session tools) or **records that the watch
lapsed and tells the owner** (`--observe-only`). It does not hold the watch when it cannot do the job: a
captain that can't reach sessions would block one that can for the next three hours. Waking a stopped worker
session is the live captain's job (`send_message`), or a one-time routine that fires *into* that session
(`create_trigger` with `persistent_session_id`), which is how a project did it by hand before.

Facts from the Claude Code docs (checked 2026-10-31): a scheduled routine belongs to the account, not to the
session that created it, so it outlives every session; every run is a new session; the minimum interval is one
hour; runs count against the same usage as interactive sessions (the check is cheap on `WATCH-OK`); a cloud
session whose container was recycled keeps its conversation but loses running commands and its own timers
(don't rely on `/loop` or session timers for survival).

## Report to the owner

Two lines per session at most: its story, its hash on main or "not landed" and why; then the convoys
(`ready N`), the budget level, and what needs the owner, with a recommendation. Ten lines in all.
