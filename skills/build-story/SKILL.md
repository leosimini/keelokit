---
name: build-story
description: Build one backlog story end to end with independent checks — done-contract, acceptance tests written before any code, implementation, cold review and adversarial attack proportioned to the story's risk (trivial, light or full, chosen by you from its dimensions and touches, never asked of the user), verification in the running app, then merge. Use when the user says "build the next story", "implement AUTH-003", "next", "continue the backlog", "construí la siguiente historia", "implementá AUTH-003", "seguí con el backlog", or picks a ready story from /keelokit. With a count or several ids of one wave, runs those stories in parallel worktrees.
---

# Build — the builder never grades its own work

How work is done and what "done" means is in `.keelokit/harness/execution-protocol.md`; this skill
is the procedure. Roles are separate agents with fresh context:

| Role | Agent | Model |
|---|---|---|
| Orchestrator (you) | this session | the session's model |
| Verifier — writes acceptance and invariant tests, declares done | `agents/verifier.md` | Sonnet |
| Builder — writes the code | a general agent you spawn | Sonnet |
| Reviewer — reads the diff cold | `agents/reviewer.md` | Sonnet; the session's model for `integrity` stories |
| Breaker — tries to break the branch | `agents/breaker.md` | Sonnet; the session's model for `integrity` stories |

Change the models in the agent files if your budget or the story's risk asks for it. Which of these roles run depends on the tier (step 0).

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
- `integrity`, a critical area, money, reservations, quotas, credits, refunds, notices,
  permissions or an assistant are always **full** (doctor enforces the declaration).
- **Re-evaluate after the builder, escalate only.** If `doctor --scope` fails, or the diff reaches
  `auth`, `data`, a shared contract, a critical area, or a new endpoint or write path the tier
  didn't expect, rerun from the missing steps at the higher tier. Never lower a tier after a
  finding.
- A trivial story whose diff turns out to carry a promise or logic becomes light.

## Spend less, same checks (every tier)

- One agent per role per story. A later round **continues the same agent** (`SendMessage`)
  instead of launching one that rereads everything; the verifier reproduces ALL the round's
  findings in one pass, not one agent per finding.
- Agents get **paths**, not pasted files: the story, the contract, the base sha. Reports are at
  most 10 lines with `file:line` and commit hashes; the full detail stays in the commit or file.
- Roles read only what the story needs: the `dimensions.md` rows of its declared dimensions, the
  `invariants.md` classes of its invariants. Not the whole catalogue.
- NON-BLOCKING findings are batched into one commit at the end, never a round of their own.
- Wait on a background run once (`until` on its log or exit status); don't poll.

## 1. Pick

`python3 .keelokit/bin/doctor.py --brief` → first ready story, or the ones the user named. For N
stories: only from the same wave (doctor guarantees their `touches` and critical areas don't
overlap). A count N takes the first ready story and the next ready ones of its wave; several ids
(`/keelokit:build-story AUTH-002 AUTH-003`, what the dashboard's "Build wave N" button sends)
take exactly those, and one that isn't ready or is in another wave is left out with the reason
said. One worktree each (`git worktree add ../<repo>-<ID> -b <id-lower>`), steps 2–7 per
story in parallel. Give each worktree its own ports:
`E2E_PORT=41<n>0 E2E_MOBILE_PORT=81<n>0 E2E_API_PORT=31<n>0` (n = 1..N).

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
- every promise the story's text makes to the user (COPY-1), with the behaviour that keeps it.
Anything the story leaves undefined that changes behaviour → a gap in `docs/context/gaps.md` and
a question to the user. Don't guess product rules. An invariant the story needs but
`domain.md` doesn't have is a product rule too: propose it to the user, don't write it alone.

## 3. Acceptance tests first — verifier, mode A

Delegate to `verifier` (mode A). Its tests fail for the right reason before any code exists,
cover every scenario and every invariant with the kind of test its class calls for, and are
committed first on the story branch as `test(<ID>): acceptance tests`.

## 4. Implement — builder

Spawn a fresh agent (Sonnet) with the story, the contract, the failing tests and `AGENTS.md`:
make the tests pass without editing them (a wrong test → stop and say why; only the verifier
changes them, in a `test(<ID>): …` commit); fix causes where all callers route through; stay
within `touches`; keep critical rules in pure functions the API wraps in a transaction;
`pnpm verify` green. For an `integrity` story, `pnpm mutation` too: read its survivors and add
the tests that kill them (MUT-1).

## 5. Review and attack — before landing

1. `git fetch && git rebase origin/main`, then record the base: `git rev-parse origin/main`.
2. `python3 .keelokit/bin/doctor.py --scope <ID>` must pass: no files outside `touches`, no
   undeclared critical area, no acceptance test edited by the builder.
3. In parallel: `reviewer` (always), and `breaker` in mode A (full mode). Each gets the story, the
   contract and the recorded base.
4. Every BLOCKING or BROKEN item: the verifier reproduces it as a failing test first (mode A),
   and adds its row to `docs/escapes.md` with the check that now catches its class (ESC-1).
   Then back to step 4. Two rounds at most; a third means the story itself is wrong: stop and
   tell the user.

## 6. Verify — verifier, mode B

Delegate to `verifier` (mode B). NOT DONE → the same loop as step 5.4: failing test, escape row,
builder.

## 7. Land

1. `git fetch`. If `origin/main` moved past the base recorded in step 5, other work landed in
   between: `git rebase origin/main`, then `breaker` in mode B (old base → new base × this
   story) and, if it touched the same journeys, a verifier mode B re-walk of them. Findings go
   through the step 5.4 loop.
2. `pnpm verify` (the pre-push hook runs it again).
3. Commit with the trailer that closes the story, as the message's last line:
   ```
   feat(auth): sign up with email

   Story: AUTH-003
   ```
4. If the result differs from the story, append `## Addendum — <date>` to the story file.
5. Push and merge per the project's flow; production deploys stay with the human.
6. `python3 .keelokit/bin/doctor.py` passes: TRACE-1 now checks this story's scenarios and INV-1
   its invariants.

## Report

After each story lands, refresh the dashboard (`/keelokit:project-dashboard`).

Per story: mode (full/light), contract, tests added (ids), invariants proven and how, review and
attack rounds (findings, what reproduced), escapes logged with their new checks, mutation score
if `integrity`, verification evidence (screenshot paths for screens), addendum if any, and the
next ready story.
