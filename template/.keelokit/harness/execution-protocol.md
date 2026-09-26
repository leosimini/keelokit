# Agent execution protocol

How any agent (Claude or another tool) works in a Keelokit project. House-level: every project
inherits it; change it in the Keelokit template, not here.

## Before starting

1. Read `AGENTS.md`, then only the context the task needs: `docs/context/*` for product and
   domain, `docs/prd.md` for scope, the story file for the task.
2. Run `pnpm doctor --brief` to see where the project stands.
3. Work on one story (or one explicit request) at a time, in its own branch or worktree.

## While working

- Stay inside the files the story names in `touches`; touching anything else is a scope change —
  say so before doing it.
- Stories go through `/keelokit:build`: the verifier writes the acceptance tests first, the
  builder makes them pass without editing them, the reviewer reads the diff cold, and only the
  verifier declares done — after walking every scenario in the running app.
- Any other behaviour change: failing test first; the smallest change that makes it pass, at the
  root cause (grep every caller of what you change).
- Unknown fact → never guess. Record a gap in `docs/context/gaps.md` (id, owner, exact question,
  blocking yes/no) and continue with what doesn't depend on it, or stop and ask.
- A command fails twice for the same reason → stop, report what you tried, ask.

## Done means

- `pnpm verify` passed on the final commit (it runs before every push anyway).
- For a story: the verifier's DONE verdict, with evidence per scenario; every scenario has a test
  citing `<ID>.S<n>` (doctor checks it).
- The commit that completes a story carries the trailer `Story: AUTH-003` (last line of the
  message). That trailer, reachable from `main`, is what makes the story done — mentioning the id
  anywhere else doesn't count.
- If what was built differs from the story, append `## Addendum — <date>` to the story saying how.
- Report: what changed, how it was verified, what is left, and anything the human must decide.

## Reserved for the human

Ask in chat and wait for a clear yes before:

- approving the PRD/scope, a spec, or a deviation from the house stack;
- deploying to production or submitting to an app store;
- anything that moves money, touches payment configuration, or has legal effect;
- deleting data or dropping tables;
- adding a paid service or a dependency with a non-OSI license.

Everything else proceeds without asking. When a decision is needed, bring it as a package:
the options, a recommendation, and what each option costs.

## Never

- Bypass a gate (`--no-verify`, force-push, disabling a test to go green).
- Commit secrets or `.env` files.
- Edit a migration that already exists on `origin/main`.
- Mark something done that `pnpm verify` has not passed.
