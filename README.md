<p align="center"><img src="docs/assets/keelokit-icon.svg" width="120" alt="Keelokit icon: a hydrofoil board flying over the water"></p>

# Keelokit

**My personal Claude Code harness for building apps in TypeScript monorepos.**

*[Leer en español](README.es.md)*

I'm [Leopoldo Simini](https://leopoldosimini.com). I've been writing software for many years
and starting things for most of my life. Coding agents changed how I build: ideas that used to
wait for a team or a free month now get a real first version. Keelokit is the harness I use for
that — my stack, my rules, the way I like to work — and I maintain it as a hobby, on weekends
and late nights with music on, learning as I go.

I'm sharing it in case it helps someone taking their first steps with agents, or founders and
teams — technical or not — laying the foundation of a first MVP. It is opinionated and built
around my preferences, so it won't fit every project or every team. Take what's useful.

## The idea

When I build with agents, the rules that matter shouldn't live only in a prompt. So in Keelokit each
rule points to something that checks it — a test, a lint rule, a git hook, a CI job — and a
small script (`doctor`) tells you when a rule has lost its check. Unknown facts become written
gaps instead of guesses, and the agent that writes the code isn't the one that says it's done.

## What it does

| Command | What happens |
|---|---|
| `/keelokit:kickstart` | From an idea to a working skeleton: an interview that writes the product context, a short PRD, the stack, a generated monorepo with CI, and a first backlog |
| `/keelokit:adopt` | For an existing repo: adds only the harness (`.keelokit/`), maps its rules to the checks the repo already has, and lists the rest as dated exceptions |
| `/keelokit:intake` | Reads what you already have, then asks only what's missing; what nobody knows yet is written down as an open question |
| `/keelokit:backlog` | Epics and stories with acceptance scenarios, grouped so parallel work doesn't touch the same files |
| `/keelokit:build` | One story: a verifier writes the acceptance tests first, a builder makes them pass, a reviewer reads the diff, the verifier walks it in the running app |
| `/keelokit:bugbash` | A bug hunt across data, API, UX, i18n, accessibility, security and more; every bug that got through adds a check so it doesn't come back |
| `/keelokit:doctor` | Is every rule still checked? Add a rule, register an exception |
| `/keelokit:upgrade` | Bring a project to a newer template without touching its product code |
| `/keelokit` | Where the project is, what's next, what's waiting for you |

## The stack it generates

pnpm workspaces · TypeScript strict · NestJS + Prisma + PostgreSQL · Vite + React · Expo ·
Astro · zod contracts and i18n in a shared package · design tokens in another · Vitest, Jest,
Playwright with axe · GitHub Actions · Fly.io. You pick which apps a product needs. The reasons
are in [`template/.keelokit/harness/stack.md`](template/.keelokit/harness/stack.md).

## Try it

You need Node 22 with pnpm 10, Python 3.11+, [uv](https://docs.astral.sh/uv/) (it runs
[Copier](https://copier.readthedocs.io/)), Docker, and git. macOS or Linux.

```bash
claude plugin marketplace add leosimini/keelokit
claude plugin install keelokit@keelokit
```

Then, in an empty folder, open Claude Code and run `/keelokit:kickstart`. In a repo you already
have, run `/keelokit:adopt`. To generate from your own fork, set `KEELOKIT_TEMPLATE=gh:<you>/keelokit`.

## Good to know

- It's opinionated on purpose. If your stack is different, `adopt` still gives you the rules,
  the guard and the checks, but not the skeleton.
- `build` and `bugbash` run several agents per story; they use more tokens than a single chat.
  `build --light` exists for small changes.
- The guard that stops agents from bypassing hooks or writing secrets is a speed bump, not a
  sandbox. The git hooks and CI are the real backstop.
- `doctor` can tell a check is present and switched on, not that it's a good check. Reviews and
  bug hunts cover that.
- Skills understand requests in English and Spanish.

## How it's built

[`docs/design.md`](docs/design.md) explains the pieces: the plugin, the template, the house rules,
and what `doctor` can and can't see. Keelokit tests itself: `python3 -m unittest discover -s tests`
for the guard and doctor, and `scripts/test-template.sh` to generate projects and run their full
checks.

## Ideas I learned from

Spec-driven development ([OpenSpec](https://github.com/Fission-AI/OpenSpec),
[Spec Kit](https://github.com/github/spec-kit)), [Superpowers](https://github.com/obra/superpowers)
for separating who builds from who reviews, [Copier](https://copier.readthedocs.io/) for templates
that can be upgraded, and a lot of trial and error on my own projects.

## License

MIT — see [LICENSE](LICENSE). Made by [Leopoldo Simini](https://leopoldosimini.com).
