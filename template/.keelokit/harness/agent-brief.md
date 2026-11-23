# Agent brief — how a session works when several run at once

One page, shared. A prompt for a session says **"read `.keelokit/harness/agent-brief.md`, then do
<story or job>"** and nothing more about process: repeating these rules in prompts makes them drift
apart. The rules of the project (`AGENTS.md`, `rules.toml`) still apply; this is about running in
parallel. (SESS-1)

## One session, one finished job

- A session takes **one** job — normally one story (`/keelokit:build-story <ID>`) — and ends it
  **landed** as `[landing] policy` in `.keelokit/state.toml` says (absent = `direct`). `direct`:
  merged on `origin/main`, `pnpm verify` green, pushed; a branch with commits that are not on
  `origin/main` is **not finished**, whatever the report says. `convoy`: delivered (below).
- It works in its own worktree (`git worktree add ../<repo>-<id> -b <id>`), with its own ports
  (`E2E_PORT`, `E2E_MOBILE_PORT`, `E2E_API_PORT`).
- **Names.** A session that starts another titles it with `python3 .keelokit/bin/status.py title
  <ID>` (`create_session`'s `title`; `--role coordinator` for the coordinator), renames itself with
  its own title on starting when its tool can, and starts each Agent's description `<ID> · <role>`.
- Cut off mid-work? Push it to `wip/<topic>` (when `[verify] wip_branches` is set): unverified, never
  lands; whoever takes it over verifies it before it goes anywhere else (WIP-1).
- Stories that add a **migration** run one at a time (MIG-1): the second waits for the first to
  land, rebases, and takes a timestamp after it; one that sorts before main's last fails the doctor.

## Landing — `direct` (the default)

1. `git fetch origin main && git rebase origin/main`. A conflict only in formatting: keep **your**
   content and run `pnpm format` (FMT-1). A real conflict: stop and say which files.
2. `pnpm verify` — never `--no-verify`. It takes the machine's verify lock, so two sessions on one
   laptop wait for each other instead of starving each other into fake timeouts.
3. `git push origin HEAD:main` (or the repo's way). If main moved, go back to 1.
4. `git log origin/main --oneline -1` shows your commit. That hash is the report.

## Landing — `convoy`

Harbor (`/harbor:*`) merges delivered branches into `convoy/<n>`, verifies them once and pushes
main. The session **never pushes to main**:

1. Rebase on `origin/main` as in step 1 above.
2. `pnpm verify` green on the final commit: the same scope as `--since origin/main`, but it seals,
   so the push in step 3 doesn't run it again. A commit after it means verify again.
3. `git push origin HEAD:<branch>`; `git ls-remote origin <branch>` shows the verified hash.
4. The report is branch + full hash + tier + verify result. Not pushed, or green on another hash:
   not delivered.

## Models

By role and tier, whatever the landing policy. The conductor of a session runs on Sonnet, except
for full design (Opus).

| Work | light | full |
|---|---|---|
| Searches, logs, status, screenshots | Haiku | Haiku |
| Implement, integrate, resolve conflicts, docs | Sonnet | Sonnet |
| Tests (verifier, breaker) and review | Sonnet | Opus |
| Design that is hard to undo (schema, public contract, data model) | Opus | Opus |

## Machine limits

Respect the machine: at most **2** sessions running tests at once on a laptop (one verify at a
time is enforced), no more than the `parallel` count in `.keelokit/state.toml`. Never kill a
process or container you did not start.

## Waiting

One `until` loop on one condition (a log line, an exit status, `gh`/`ci.py` state), with a sleep
inside. Never poll with repeated short calls, never `sleep` alone.

A run that lasts more than a few minutes (`pnpm verify --all`) goes in the background with a log,
because a command a tool keeps in the foreground is killed at about 30 minutes and the run is lost:
`nohup pnpm verify --all > run.log 2>&1 &`, then wait with one `until`. Read its result from the
exit code and from `status.py` (`verify: last pass`, or `CUT` when it died), never by searching
the log for a phrase. Run `pnpm verify --preflight` first: a red there costs minutes, not an hour.
`--keep-going` lists every red of a run at once.

## The report: 8 lines at most

The story id, the commit hash on `origin/main` (convoy: branch and hash), tier, what `verify` ran,
anything the person must decide. **Paths, not contents:** point at the file or commit; never paste
a diff or a log.

## The coordinator trusts nothing but origin/main

- A session that ends well **does not message its parent**; the coordinator does not wait for
  messages. Every follow-up round (about every 15 minutes while sessions run) it runs
  `python3 .keelokit/bin/status.py` and checks the hashes on `origin/main`.
- "Done" without a pushed commit on main is **not done**: the coordinator sends the session back
  to land it, or lands it itself.
- With `convoy`, Harbor coordinates (`/harbor:*`); `status.py` lists the delivered branches.
- A session that failed or got stuck reports it (what it tried, the log path) and stops; it does
  not retry the same thing a third time (execution protocol).
