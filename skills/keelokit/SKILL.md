---
name: keelokit
description: Entry point of the Keelokit harness. Use when the user says "keelokit", "/keelokit", "dónde estamos", "qué sigue", "what's next", "estado del proyecto", "retomemos", or opens a session in a Keelokit project and asks what to do. Reads the project state and answers where the project is, what comes next and what decision is waiting for the human; routes to kickstart, adopt, intake, backlog, build, doctor or the dashboard.
---

# Keelokit — where are we, what's next

Answer three things, in this order, in at most ten lines:

1. **Where we are** — gate or backlog progress.
2. **What's next** — the one concrete next action.
3. **What waits for the human** — pending approvals or decisions, as a short package
   (options + recommendation).

## Procedure

1. Find the project root: the nearest directory with `.keelokit/` (walk up from the cwd).
   - **None found, empty folder or no code** → offer a new product (`/keelokit:kickstart`).
   - **None found, existing code** → offer to bring it under the harness (`/keelokit:adopt`).
   Do not install or scaffold anything without the user's answer.
2. Run `python3 .keelokit/bin/doctor.py --brief`. If Python is missing, say so and stop.
3. Route:
   | State | Next action |
   |---|---|
   | A gate is pending | Continue `/keelokit:kickstart` (new product) or `/keelokit:adopt` (existing repo) from that gate |
   | Harness errors reported | `/keelokit:doctor` |
   | Blocking context gaps | Ask the gap questions (owner = the user) and update `docs/context/` |
   | Stories ready | Propose `/keelokit:build` on the first ready story (or N of the same wave) |
   | A wave just finished, or a release is near | Propose `/keelokit:bugbash` |
   | Nothing ready, backlog not empty | Show which dependency blocks the next wave |
   | Backlog empty or done | Offer `/keelokit:backlog` for the next slice, or a new feature intake |
4. If the user already said what they want, skip the report and do it.
5. Offer the dashboard (`/keelokit:dashboard`) with the answer, and open it without asking when
   a gate is pending or the user is resuming a half-finished run: it shows the stages, what
   waits for their review and the next step.
