---
name: build
description: Build one backlog story end to end with independent checks — done-contract from its dimensions, acceptance tests written by the verifier before any code, implementation, independent review, verification in the running app, then merge. Use when the user says "build the next story", "implement AUTH-003", "next", "continue the backlog", "construí la siguiente historia", "implementá AUTH-003", "seguí con el backlog", or picks a ready story from /keelokit. With a count ("build 3"), runs that many ready stories of the same wave in parallel worktrees. "--light" for small, low-risk stories.
---

# Build — the builder never grades its own work

How work is done and what "done" means is in `.keelokit/harness/execution-protocol.md`; this skill
is the procedure. Roles are separate agents with fresh context:

| Role | Agent | Model |
|---|---|---|
| Orchestrator (you) | this session | the session's model |
| Verifier — writes acceptance tests, declares done | `agents/verifier.md` | Sonnet |
| Builder — writes the code | a general agent you spawn | Sonnet |
| Reviewer — reads the diff cold | `agents/reviewer.md` | Sonnet |

Change the models in the agent files if your budget or the story's risk asks for it.

## 0. Full or light

**Light** (`--light`, or propose it) when the story declares at most two dimensions and none of
`data`, `auth`, `security`, `contract`, `nfr`: skip step 5 (review) and let the builder run
step 3's tests itself; the verifier still writes the tests first and walks the result (steps 3
and 6). Everything else runs **full**. Say which mode and why in one line.

## 1. Pick

`python3 .keelokit/bin/doctor.py --brief` → first ready story, or the one the user named. For N
stories: only from the same wave (doctor guarantees their `touches` don't overlap), one worktree
each (`git worktree add ../<repo>-<ID> -b <id-lower>`), steps 2–7 per story in parallel. Give
each worktree its own E2E ports: `E2E_PORT=41<n>0 E2E_MOBILE_PORT=81<n>0` (n = 1..N).

## 2. Contract

Write the story's done-contract as a checklist and show it in one block, then continue:
- each scenario `<ID>.S<n>`;
- for each declared dimension, its lines from `${CLAUDE_PLUGIN_ROOT}/references/dimensions.md`;
- dimensions the `touches` imply but the story forgot (a screen → `ux`, `ui`, `i18n`, `a11y`):
  add them to the story's front matter now.
Anything the story leaves undefined that changes behaviour → a gap in `docs/context/gaps.md` and
a question to the user. Don't guess product rules.

## 3. Acceptance tests first — verifier, mode A

Delegate to `verifier` (mode A). Its tests fail for the right reason before any code exists, and
are committed first on the story branch.

## 4. Implement — builder

Spawn a fresh agent (Sonnet) with the story, the contract, the failing tests and `AGENTS.md`:
make the tests pass without editing them (a wrong test → stop and say why); fix causes where all
callers route through; stay within `touches` (`python3 .keelokit/bin/doctor.py --scope <ID>` lists
files outside them); `pnpm verify` green.

## 5. Review — full mode only

Delegate to `reviewer`. CHANGES REQUESTED → back to step 4 with the findings. Two rounds at most;
a third means the story itself is wrong — stop and tell the user.

## 6. Verify — verifier, mode B

Delegate to `verifier` (mode B). NOT DONE → back to step 4 with its evidence.

## 7. Land

1. `git fetch && git rebase origin/main`; `pnpm verify` (the pre-push hook runs it again).
2. Commit with the trailer that closes the story, as the message's last line:
   ```
   feat(auth): sign up with email

   Story: AUTH-003
   ```
3. If the result differs from the story, append `## Addendum — <date>` to the story file.
4. Push and merge per the project's flow; production deploys stay with the human.
5. `python3 .keelokit/bin/doctor.py` passes — TRACE-1 now checks this story's scenarios.

## Report

Per story: mode (full/light), contract, tests added (ids), review rounds, verification
evidence, addendum if any, and the next ready story.
