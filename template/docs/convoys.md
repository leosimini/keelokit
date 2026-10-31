# Convoys — landing several sessions' work in one voyage

A **convoy** is a wave of stories that sails together: each session finishes its branch (tests by the
verifier, review, captures if it has a screen) and hands it over by name and hash; one **conductor**
merges them into `convoy/<n>`, reads the result, runs one `pnpm verify --all` and pushes once. It is
the policy for a project where every push to `main` costs a CI run (`landing = "convoy"` in
`.keelokit/state.toml` `[run]`); with cheap CI, `landing = "direct"` and each session lands alone.
(JOUNA called them *trenes*.)

| Role | Does | Never |
|---|---|---|
| **Captain** (one, holds the watch) | Decides what enters each convoy and when it sails; resolves product decisions inside what the owner already decided; escalates the owner's (money, prices, fees, production, third-party accounts, legal data); checks in at least every 90 min; hands the watch over when fresh enough | Integrates, pushes to main, or decides what only the owner decides |
| **Conductor** (one per convoy) | Merges the pieces into `convoy/<n>`, reads the seams, runs the cheap checks, then `verify --all` and one push once the captain gives the ok | Pushes to main without the ok |
| **Worker session** | Finishes one piece on its branch and reports its hash | Pushes to main; leaves a branch only in its container (push it to the remote) |

State lives on the branch `coord/board` (a push there never runs the CI or moves main):
`python3 .keelokit/bin/coord.py status`. The watch is taken by the first push that changes `LEASE.json`;
a watch not checked in for 3 hours (`ttl_minutes` in `[coord]`) may be taken by anyone.

```
coord.py claim --id S                 take the watch         coord.py convoy new 6 --conductor S2
coord.py heartbeat --id S             check in               coord.py convoy add 6 QA-1 --branch b --hash h [--ui]
coord.py handoff --id S --note -      pass it on (≤ 40 lines) coord.py convoy piece 6 QA-1 --tests ok --review ok --state lista
coord.py tick --id S                  what a scheduled check runs                coord.py convoy docs 6 ok
coord.py convoy ready 6               the four conditions   coord.py convoy seam 6        files two pieces both change
coord.py convoy ship 6 --hash H       record that it sailed coord.py budget               low / medium / high
```

**A convoy sails when** `convoy ready` passes: every piece is `lista` with tests and review (and captures
if it has a screen); nothing is left out that can still be finished (what stays has a reason: `owner`,
`production-config` or `machine`); the manual and the environments doc are up to date; main is green or
the convoy carries its fix. Between convoys nothing goes to main, except the fix of a red main.

`/keelokit:orquestador` is the skill that plays the captain, with the relief procedure, the scheduled
check that survives the death of any session, and what to do when sessions stop at a usage limit.
