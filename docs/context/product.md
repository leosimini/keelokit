# Product

## Problem
Coding agents write working code fast, but the rules that matter live only in prompts, unknown
facts get filled with guesses, and the agent that writes the code is the one that says it's done;
the same classes of bug keep reaching users. (S1, S2)

## Users
| User | Needs to | Today they use |
|---|---|---|
| Founder, technical or not, starting a first MVP | Go from an idea to a working, tested product with agents, without a software process of their own | Prompts and chat sessions, no process (S1) |
| Developer or small team with an existing repo | Put rules backed by checks under the agents that work on it, without a rewrite | Ad-hoc CLAUDE.md files and CI they wrote themselves (S1) |
| The maintainer (Leo) | Build Keelokit with Keelokit, release it safely, keep the site in step | This repo's own CI and `scripts/release.sh` (S3) |

## Success metrics
| Metric | Target | By | Source |
|---|---|---|---|
| Generated projects that pass `pnpm verify --all` on the first run | 100% of the CI matrix | every release | S3 |
| Upgrade from the previous release passes without manual fixes | 100% | every release | S3 |
| Bugs found by a bug bash that escaped a story's own tests | counted per release from the bug bash of 2026-09-27 (the baseline, `docs/escapes.md`); a number to beat is set after two releases of data | every release | S2 (decided 2026-09-28) |

## Out of scope for launch
- Stacks other than the house stack for new products; other stacks come in through `project-adopt`. (S1)
- Windows. (S1)
- Hosting: Keelokit has no server and collects nothing. (S1)

## Business model
Not monetised: an open-source (MIT) hobby project. (S1)

## Markets and languages
Anyone using Claude Code; skills understand English and Spanish; the dashboard renders in both. (S1)

## Sources
| Id | Type | What | Date |
|---|---|---|---|
| S1 | document | README.md and README.es.md | 2026-09-27 |
| S2 | document | docs/design.md | 2026-09-27 |
| S3 | document | docs/releasing.md, scripts/release.sh, .github/workflows | 2026-09-27 |
| S4 | code | skills/, agents/, hooks/, template/, tests/ (inferred) | 2026-09-27 |
