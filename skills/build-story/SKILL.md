---
name: build-story
description: Build one backlog story end to end with independent checks — done-contract, acceptance tests written before any code, implementation, cold review and adversarial attack proportioned to the story's risk (trivial, light or full, chosen by you from its dimensions and touches, never asked of the user), verification in the running app, then merge. Use when the user says "build the next story", "implement AUTH-003", "next", "continue the backlog", "construí la siguiente historia", "implementá AUTH-003", "seguí con el backlog", or picks a ready story from /keelokit. With a count or several ids of one wave, runs those stories in parallel worktrees.
---

# Build — the builder never grades its own work

How work is done and what "done" means is in `.keelokit/harness/execution-protocol.md`; this skill
is the procedure. Roles are separate agents with fresh context:

| Role | Agent | Model |
|---|---|---|
| Orchestrator (you) | this session | Sonnet; Opus while designing something hard to undo in full tier |
| Verifier — writes acceptance and invariant tests, declares done | `agents/verifier.md` | Sonnet; **Opus in full tier** |
| Builder — writes the code | a general agent you spawn | Sonnet |
| Reviewer — reads the diff cold | `agents/reviewer.md` | Sonnet; **Opus in full tier** |
| Breaker — tries to break the branch (full tier only) | `agents/breaker.md` | **Opus** |
| Cold breaker — one per round on a risky story, never reused (step 5b) | `agents/breaker.md`, mode C | **Opus** |

The agent files default to Sonnet; for the full tier pass `model: "opus"` when you delegate to the
verifier, reviewer and breaker. Searches, logs, status and screenshots go to Haiku. The table by
role and tier is in `.keelokit/harness/agent-brief.md` (Models). Which roles run depends on the tier (step 0).

## 0. Choose the tier — you decide, the user is never asked

Read the story's front matter (`dimensions`, `touches`, `invariants`) and the diff you expect,
then pick the lightest tier whose condition holds. Say it in one line: tier and the reason. The
user can force a tier with `--trivial`, `--light` or `--full`; without a flag it is your call.

| Tier | Pick it when ALL hold | What runs |
|---|---|---|
| **trivial** | dimensions ⊆ {`docs`, `copy`, `config`, `dx`, `ui`}; `touches` has no logic (text, docs, styles, config, locale files); no critical area; the text promises nothing (no time, amount, "we'll notify you", "you can undo", "free": COPY-1) | The builder writes the scenario tests the doctor's TRACE-1 asks for, and runs `pnpm verify`. You run `doctor --scope`, read the diff yourself and, for a screen, look at it once. No verifier A, no reviewer, no breaker, no verifier B |
| **light** | at most two dimensions, none of `data`, `auth`, `security`, `contract`, `nfr`, `integrity`; no critical area; no money, quota, permission, notice or data-deletion path | Verifier A writes the tests first; the builder runs them; ONE reviewer; verifier B walks the result. No breaker |
| **full** | anything else | Every step below |

Rules for the choice:
- **When in doubt, go up one tier.** Missing an escape costs more than a reviewer's tokens.
- Always **full**: a risky story — `python3 .keelokit/bin/ledger.py risky <ID>` says whether and why, from
  `.keelokit/risky.toml` (its `risky = true`, a dimension, a touch, or a path the branch changes); it also gets
  the cold breaker rounds of step 5b. Always **full**, too: a money story: the `integrity` dimension, or a story that moves money in a
  project with the `payments` trait (the breaker walks its failure paths); and a critical area,
  money, reservations, quotas, credits, refunds, notices, permissions or an assistant (doctor
  enforces the declaration).
- **Re-evaluate after the builder, escalate only.** If `doctor --scope` fails, or the diff reaches
  `auth`, `data`, a shared contract, a critical area, or a new endpoint or write path the tier
  didn't expect, rerun from the missing steps at the higher tier. Never lower a tier after a
  finding.
- A trivial story whose diff turns out to carry a promise or logic becomes light.

## Spend less, same checks (every tier)

- One agent per role per story. A later round **continues the same agent** (`SendMessage`)
  instead of launching one that rereads everything (the one exception: step 5b's cold breaker, a new one
  per round); the verifier reproduces ALL the round's
  findings in one pass, not one agent per finding.
- Each Agent's description starts `<ID> · <role>` (`AUTH-003 · reviewer`), so a list of agents reads
  by story, and every prompt you delegate says **never `--no-verify`** (subagents tried it; the guard
  blocks it).
- Agents get **paths**, not pasted files: the story, the contract, the base sha. Reports are at
  most 10 lines with `file:line` and commit hashes; the full detail stays in the commit or file.
- Roles read only what the story needs: the `dimensions.md` rows of its declared dimensions, the
  `invariants.md` classes of its invariants. Not the whole catalogue.
- NON-BLOCKING findings are batched into one commit at the end, never a round of their own.
- Push before any wait longer than a few minutes: the story's branch when verified, else `wip/<topic>`
  with the same commits. Then wait on a background run once, on state, never on a log line:
  `status.py` or the verify's exit code, a CI run's state, a remote ref. Don't poll. Say how long as
  the range `status.py` prints, never one figure.

## 1. Pick

`python3 .keelokit/bin/doctor.py --brief` → first ready story, or the ones the user named. For N
stories: only from the same wave (doctor guarantees their `touches` and critical areas don't
overlap). A count N takes the first ready story and the next ready ones of its wave; several ids
(`/keelokit:build-story AUTH-002 AUTH-003`, what the dashboard's "Build wave N" button sends)
take exactly those, and one that isn't ready or is in another wave is left out with the reason
said. One worktree each (`git worktree add ../<repo>-<ID> -b <id-lower>`), steps 2–7 per
story in parallel. Give each worktree its own ports:
`E2E_PORT=41<n>0 E2E_MOBILE_PORT=81<n>0 E2E_API_PORT=31<n>0` (n = 1..N).

For parallel *sessions* (one per story, possibly on several terminals) the shared brief is
`.keelokit/harness/agent-brief.md`; `/keelokit:coordinate` runs the rounds. Stories that add a
migration go one per wave (MIG-1). Names follow the brief: a session you start gets the title
`python3 .keelokit/bin/status.py title <ID>` prints (`<project> · wave <n> · <ID>`), this session
renames itself with its story's title when its tool can, and the branch stays the id in lowercase.
Each prompt adds `Never --no-verify.`; the brief's other habits (push before waiting, wait on state,
ranges) come with it, and a cloud session archives itself once its work is pushed and reported.

How many at once comes from `[run]` in `.keelokit/state.toml`: `build = "serial"` → one;
`build = "parallel"` → up to `parallel` ready stories of the wave. A count the user gives now
wins for this run only. Never ask again when `[run]` is set; if it isn't, ask once, in plain words
— one at a time (slower, follow every step, Claude usage spread out) or N in parallel (faster,
more Claude usage at once, several results to review together; safe because a wave's stories
never touch the same files) — recommend one at a time, and record the answer in `[run]`.

`mode = "auto"` in `[run]`: after a story lands, pick the next ready ones and go on, wave after
wave, until nothing is ready. Stop only for what needs a person: a product rule the story doesn't
define or a new invariant (steps 2), a third failed review round (step 5), and anything the
execution protocol reserves for the human. `mode = "step"`: report after each story (or each
batch) and wait for the user.

Before the contract, ask the ledger about each story you picked: `python3 .keelokit/bin/ledger.py show <ID>`.
Its card has the state, earlier attempts (`Dropped:`) and why they stopped, the bodies of earlier
`Story:`/`Part-of:` commits, escape rows and bug-bash findings that name it, corrections and the branches
of any other session on it. Read what it says before step 2: a finding or an abandoned attempt changes
the contract. A story already `on-trunk` or later is not built again; one `in-progress` on another
branch is someone else's: pick another or say so; `unknown` is never "not started": `ledger.py` says
why (a cut history: `ledger.py history --ensure`).

Then take it: `python3 .keelokit/bin/ledger.py take <ID>` in the story's worktree. It records the story in
that worktree's own config (`keelokit.story`), so its commits are attributed whatever the branch is called
(`claude/<name>`, a Harbor vessel), and pushes nothing. It refuses a story already on the trunk, and warns,
naming the branch, when another origin branch has `Part-of:` commits of it: read that branch before going on.
Giving a story up at any step (a third failed review round, a blocker the story can't get past):
`python3 .keelokit/bin/ledger.py drop <ID> --motivo "<why, and what was tried>"`. It pushes an empty
`Dropped:` commit to `archive/<id>-<YYYYMMDD>` (no verify; on the current branch when archive/ is refused)
and clears the story, so the next session's `ledger.py show <ID>` reads why.

A story that brings something new into the project — its first migration, a new app, a deploy
config, personal data, payments — updates `traits` in `.keelokit/profile.toml` in the same change;
the doctor warns when the code shows a trait the profile lacks.

## 2. Contract

Write the story's done-contract as a checklist and show it in one block, then continue:
- each scenario `<ID>.S<n>`;
- each invariant the story lists (`invariants`), with its class and the test that class calls
  for, from `${CLAUDE_PLUGIN_ROOT}/references/invariants.md`;
- for each declared dimension, its lines from `${CLAUDE_PLUGIN_ROOT}/references/dimensions.md`;
- dimensions the `touches` imply but the story forgot (a screen → `ux`, `ui`, `i18n`, `a11y`; a
  critical area → `integrity`): add them to the story's front matter now;
- every promise the story's text makes to the user (COPY-1), with the behaviour that keeps it;
- for a money story, its failure paths from `${CLAUDE_PLUGIN_ROOT}/references/invariants.md`
  ("the failure paths of a money movement"), each with the test that
  covers it or why it cannot happen, before the verifier writes any test; the breaker walks the
  same list;
- a decision about money that you take inside what the person already decided is recorded as
  reversible (in the addendum) and the person is told; anything new about money waits for the
  person. Moving money and touching payment configuration stay reserved for the human
  (execution protocol, unchanged): this is about how the code handles money, never about
  moving it.
Anything the story leaves undefined that changes behaviour → a gap in `docs/context/gaps.md` and
a question to the user. Don't guess product rules. An invariant the story needs but
`domain.md` doesn't have is a product rule too: propose it to the user, don't write it alone.

## 3. Acceptance tests first — verifier, mode A

Delegate to `verifier` (mode A). Its tests fail for the right reason before any code exists,
cover every scenario and every invariant with the kind of test its class calls for, and are
committed first on the story branch as `test(<ID>): acceptance tests`. Point it, and any other
agent that writes tests, at `${CLAUDE_PLUGIN_ROOT}/references/stable-tests.md`: the eleven rules
that keep a test from failing one run in fifty.

## 4. Implement — builder

Spawn a fresh agent (Sonnet) with the story, the contract, the failing tests and `AGENTS.md`:
make the tests pass without editing them (a wrong test → stop and say why; only the verifier
changes them, in a `test(<ID>): …` commit); fix causes where all callers route through; stay
within `touches`; keep critical rules in pure functions the API wraps in a transaction;
`pnpm verify` green. For an `integrity` story, `pnpm mutation` too: read its survivors and add
the tests that kill them (MUT-1).

### 4b. Design — only when the story changes the interface (profile trait `ui`, UX-2..4)

Read `docs/ux-quality.md` and `.keelokit/ux.toml`. Before the review, the verifier (mode B's
screenshots start here) saves the captures the matrix asks for under
`<evidence_dir>/<ID>/` and a design specialist writes `CRITIQUE.md` there. The critique comes
from the design skills, run from the start on the captures: every skill in `critique_skills`
(`.keelokit/ux.toml`; defaults `design:design-critique`, `design:ux-copy`,
`design:accessibility-review`), and `impeccable` when installed. Following a skill's framework by
hand does not count. Each skill gets a `### <skill id>` subsection under `## Skills` with
`Ran: YYYY-MM-DD` and its findings by priority; every P1 and P2 ends `— fixed in <commit or file>`
or `— decided: <reason>` (`docs/ux-quality.md` §4). A session without the skills pushes the
captures and asks the coordinator, who runs them in a subagent on a `wip/` branch touching only
`CRITIQUE.md`; take that section in and answer each finding. A critique of a screen that already
had one says whether it confirms or contradicts the earlier one. Fix what it finds, recapture,
repeat until nothing is open. A change nobody can see goes with a commit line
`ux-gate: n/a — <reason>` instead. `doctor` (UX-3) fails the branch otherwise.

## 5. Review and attack — before landing

1. `git fetch && git rebase origin/main`, then record the base: `git rev-parse origin/main`.
2. `python3 .keelokit/bin/doctor.py --scope <ID>` must pass: no files outside `touches`, no
   undeclared critical area, no acceptance test edited by the builder. With interface changes,
   `python3 .keelokit/bin/ux_gate.py` passes too (captures and critique, UX-3).
3. In parallel: `reviewer` (always), and `breaker` in mode A (full mode). Each gets the story, the
   contract and the recorded base.
4. Every BLOCKING or BROKEN item: the verifier reproduces it as a failing test first (mode A),
   and adds its row to `docs/escapes.md` with the check that now catches its class (ESC-1).
   Then back to step 4. Two rounds at most; a third means the story itself is wrong: stop and
   tell the user.

### 5b. Cold breaker rounds — every risky story (HARN-021)

The builder's own review, and a breaker that has read the builder's reasoning, miss what a fresh reader finds.
For a story `ledger.py risky <ID>` calls risky, after step 5's round is clean and before step 6:

1. **Head.** Push the branch; `git rev-parse HEAD` is the round's head (the full sha).
2. **A new breaker, cold.** Spawn a NEW `breaker` agent (mode C, `model: "opus"`, description
   `<ID> · cold breaker <n>`), never one from an earlier round or step 5. Its brief holds only: the story file's
   path, the base and the head (`git diff <base>..<head>`), the invariants the story lists (ids, and where they are
   defined), `.keelokit/risky.toml`, and `Never --no-verify.` — never the builder's conclusions, the reviewer's
   report, an earlier round's findings or what you think is fine. Ask for reproduced findings only, each with its
   repro script and the command that runs it.
3. **Reproduced findings only.** Run each repro yourself; one that does not reproduce is not a finding. Each finding
   that does is fixed starting with a test that fails before the fix (the verifier, mode A, or you: commit the test
   first and watch it fail for the finding's reason), then the fix, and its row in `docs/escapes.md` (ESC-1).
4. **Record the round** as the next line under `## Breaker rounds` in the story file, committed with the fixes:
   ```
   ## Breaker rounds
   - Round <n> · head <sha> · clean
   - Round <n> · head <sha> · <k> findings: ESC-312, ESC-313 · fixed in <commits>
   - Decision · <person> · <YYYY-MM-DD> · <what was decided>
   ```
   One top-level line per round; detail goes on indented lines under it. `clean` means nothing reproduced, and it is
   the round's whole result (a round that lists findings is not clean).
5. **Loop** with a new breaker on the new head until a round is clean. The last round decides, whatever its
   number: a clean last round closes the story, past the cap too. The cap (`rounds` in `.keelokit/risky.toml`,
   default 3) is where you stop and ask: at round `rounds` with findings left the story does not close silently.
   Stop (`mode = "auto"` too), tell the person what is left, and record their call as a `Decision` line naming them
   (another round past the cap, or land as it is with the findings in a follow-up story). If they choose another
   round and it is clean, that round decides; no Decision is needed after it. An agent never writes a Decision of
   its own.

`ledger.py check` (the CI) reports a risky story closed with no round (`BREAKER_MISSING`, error) and one whose last
round left findings with no Decision after it (`BREAKER_UNRESOLVED`, warning). A risky change under the trailer of a
story already closed is new work (`RISKY_AFTER_CLOSE`, error): give it an open story, with its own rounds. A round's
head is the head the breaker actually attacked, on the branch that closes the story (full or 7+ hex digits that
resolve here; a head the close does not reach is `BREAKER_BAD_ENTRY` and that round counts as not clean). The last
clean round's head must be at or after the story's last risky change: a risky commit between it and the `Story:`
commit is `BREAKER_STALE` (error). So record each round line after the commits it attacked, and put `Story:` on the
commit that records the last round, after every risky change. A pull
request is judged by the trunk's `risky.toml`, never its own.

## 6. Verify — verifier, mode B

Delegate to `verifier` (mode B). NOT DONE → the same loop as step 5.4: failing test, escape row,
builder.

## 7. Land

1. `git fetch`. If `origin/main` moved past the base recorded in step 5, other work landed in
   between: bring it in, then `breaker` in mode B (old base → new base × this story) and, if it
   touched the same journeys, a verifier mode B re-walk of them. Findings go through the step 5.4
   loop. For a risky story, after the breaker rounds, merge `origin/main` (`git merge --no-ff`),
   never rebase: a rebase rewrites the heads the rounds recorded, and a round counts only when its
   head is a commit the close reaches. If a rebase is truly needed, do it before the rounds start,
   or run a new round after it; never re-record an old round on a new head (that is a round nobody
   ran). A squash or rebase landing rewrites the heads too: on the trunk its rounds read as
   `BREAKER_BAD_ENTRY` and `BREAKER_UNRESOLVED` (warnings). Land a risky story with a merge commit.
2. `pnpm verify --preflight` first if the full run is long, then `pnpm verify` (the pre-push hook
   runs it with the seal, which skips the repeat only for this exact, unchanged commit).
3. Commit with the trailer that closes the story, as the message's last paragraph, and a body: what
   was decided and what was left out (`ledger.py show` gives it to the next session that asks why):
   ```
   feat(auth): sign up with email

   Decided: the confirmation link expires after 24 h (the story left it open; recorded in the
   addendum). Left out: resending the link, which AUTH-007 covers.

   Story: AUTH-003
   ```
4. If the result differs from the story, append `## Addendum — <date>` to the story file.
5. Push and merge per the project's flow; production deploys stay with the human. The story is
   landed only when `python3 .keelokit/bin/ledger.py show <ID>` says `on-trunk` (or later) with its
   commit: report that hash, never "done" alone.
   With `[landing] policy = "convoy"` in `.keelokit/state.toml`, push the branch only, never main:
   the agent brief's convoy landing. Verify the branch with a plain `pnpm verify` (step 2: the scope
   of `--since origin/main`, but sealed, so the branch push doesn't repeat it); report the branch,
   the full hash, the tier (trivial/light/full) and the verify result.
   A test that fails intermittently while you land is a race: reproduce it with
   `.keelokit/bin/flaky.sh` and find the cause (FLAKY-1, stable-tests rule 9), never a longer
   timeout, a retry or a skip.
6. `python3 .keelokit/bin/doctor.py` passes: TRACE-1 now checks this story's scenarios and INV-1
   its invariants.
7. Once `ledger.py show <ID>` says `on-trunk` (convoy: once the branch is delivered),
   `python3 .keelokit/bin/ledger.py take --clear`: the worktree works on no story until the next `take`.

## Report

After each story lands, refresh the dashboard (`/keelokit:project-dashboard`).

Per story: mode (full/light), contract, tests added (ids), invariants proven and how, review and
attack rounds (findings, what reproduced), the breaker rounds of a risky story (head, findings, fixes, or clean), escapes logged with their new checks, mutation score
if `integrity`, verification evidence (screenshot paths for screens), addendum if any, and the
next ready story.
