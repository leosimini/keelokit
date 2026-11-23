---
name: coordinate
description: Run several Keelokit sessions at once and keep them honest — one session per story with the shared agent brief, status in ten lines, follow-up rounds, and verifying landed work by its hash on origin/main. Use when the user says "coordinate", "run these stories in parallel sessions", "status of the sessions", "¿cómo van las sesiones?", "coordiná las sesiones", "estado de las sesiones", or when several sessions or worktrees are running.
---

# Coordinate — origin/main is the only truth

The brief every session follows is `.keelokit/harness/agent-brief.md` (SESS-1). Read it once.

First read `[landing] policy` in `.keelokit/state.toml` (absent = `direct`). With `convoy`, say in
one line that coordination is `/harbor:*`'s, and only run and report `python3 .keelokit/bin/status.py`;
the rest of this skill is for `direct`.

## Start sessions

- One session per story, from the same wave (the doctor guarantees their `touches` don't overlap).
  Stories that add migrations go one at a time (MIG-1).
- The prompt is short: `Read .keelokit/harness/agent-brief.md, then /keelokit:build-story <ID>.` Pass paths, not
  contents; don't repeat the brief's rules.
- Title each session with `python3 .keelokit/bin/status.py title <ID>` (`create_session`'s `title`),
  and rename this one with `title --role coordinator` when the tool can. Exit 2 means the story or
  its wave is missing: fix the backlog, never type a title by hand. Branches stay the id in lowercase.
- Respect the machine: at most two sessions running tests at once (`pnpm verify` takes a per-machine
  lock, so more only wait).

## Every round (about every 15 minutes while sessions run)

1. `python3 .keelokit/bin/status.py`: worktrees, branches with commits not on `origin/main`, the
   verify lock, the CI of main (a cancelled run is not green) and the backlog, in ten lines.
2. For each session that says it finished: `git fetch origin main && python3 .keelokit/bin/ledger.py show <ID>`.
   Landed means the card's state is `on-trunk` or later, with its commit hash; never grep `git log`
   yourself (the ledger reads reverts, corrections and the history's gaps). **A session that ends well
   does not message you; don't wait for a message, check the card.** "Done" without that state is not
   done: send it back to land (rebase, `pnpm verify`, push) or land it yourself. An `unknown` state is
   not "not landed": `ledger.py` says why (a cut history: `ledger.py history --ensure`); fix it and ask again.
3. CI of main red, or two runs in a row without a green: stop starting stories; `python3
   .keelokit/bin/ci.py jobs` says which job and step; fix that first.
4. Wait with one `until` loop on one condition, never with repeated polling.

## Integrating interface work

Before accepting a branch that changes interface files, run `python3 .keelokit/bin/ux_gate.py`:
no captures or critique means back to its session (UX-3). A session without the design skills
asks you for its critique: from its pushed captures, run a short subagent with the skills in
`critique_skills` (`.keelokit/ux.toml`) on a `wip/<ID>-critique` branch cut from the piece's branch,
touching only the piece's `CRITIQUE.md` and writing its `## Skills` section (`docs/ux-quality.md` §4);
send the session the branch and let the piece take the section in and answer every P1 and P2. When several pieces touch one journey,
walk that journey across them once they are all in (`docs/ux-quality.md` §6, UX-4).

## Report to the user

Two lines per session at most: story, hash on main (or "not landed" and why), then what needs the
user. The whole report fits in ten lines.
