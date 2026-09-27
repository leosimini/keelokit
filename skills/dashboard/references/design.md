# Keelokit pages — design

Every page Keelokit shows a person (today, the project dashboard) looks the same, so people know at
a glance that it comes from the plugin. The spec lives in code: `scripts/dashboard.py` holds the
tokens, the CSS and the components below. A new page reuses that CSS and header, never a
hand-written style, and any change to the look is made there and here together.

## Identity

- **Header bar** on every page: the Keelokit icon (`.claude-plugin/icon.svg`, 28 px, radius 7),
  the wordmark `Keelokit`, a `/`, the product's name, and the plugin version at the right. It is
  sticky (`top: env(safe-area-inset-top, 0px)`).
- **Title** (`<title>`): `Tablero de <product>` / `<product> dashboard`. Artifact icon: `dashboard`.
- The brand colours come from the icon: keel blue (sky), navy (sea), foil orange. Board yellow
  stays in the icon only.

## Tokens

| Token | Light | Dark | Use |
|---|---|---|---|
| `--bg` | `#F3F6FB` | `#061127` | page ground (blue-biased, never pure grey) |
| `--surface` | `#FFFFFF` | `#0C1D3D` | panels, stages, header |
| `--sunk` | `#E9EFF8` | `#0A1833` | code, progress track, neutral chips |
| `--ink` | `#0B1B3A` | `#E4ECF9` | text |
| `--muted` | `#4F5F7C` | `#9DB0CD` | secondary text, labels |
| `--line` | `#D5DFEC` | `#1C3260` | borders, table rules |
| `--accent` | `#0B4CC4` | `#63C0FB` | links, buttons, "in progress", "ready" |
| `--foil` | `#C85A12` | `#F7963A` | **waiting on the human**: a stage to review, a MUST |
| `--good` | `#1D7F52` | `#52C992` | approved, done |
| `--bad` | `#B3322A` | `#F2786D` | blocked |

Each colour has a `-soft` fill for pills and callouts. Dark values apply under
`prefers-color-scheme: dark` (unless `data-theme="light"`) and under `data-theme="dark"`.

## Type

- Display: **Bricolage Grotesque** 600/700 — the product name, stage titles, big panel lines.
- Body: **Manrope** 400–700, 15 px / 1.55.
- Data: **JetBrains Mono** 500/600 — ids (`AUTH-001`, `GAP-003`, `INV-002`), commands, paths,
  stage numbers.
- Fallbacks are declared for all three; the page must read well offline with system fonts.

## Components

| Component | What it says | Rule |
|---|---|---|
| **Now** panels | where we are · next step · waiting on you | always first; the next step carries a copyable command when one exists |
| **Stage rail** | every stage, in order, with its status | numbered because the order is the process |
| **Stage section** | name, status pill, approval date, what the stage is in plain words, its outputs | one per gate, anchored `#stage-<gate>` |
| **Review callout** (foil) | what to check before approving, and how to approve | only on the stage waiting for approval |
| **Status pill** | Approved · Ready for review · In progress · Not started; Done · Ready to build · Waits for X | the only place status colour appears |
| **Document** | a repo file rendered inline, collapsed, with "Open on GitHub" when the repo has a GitHub remote | the page never depends on links working |
| **Backlog** | stories by development wave or by epic, with progress per group | toggle remembered per viewer (browser storage) |
| **Build modes** | one at a time vs in parallel, what each costs the user, a command for each | shown once stories exist |
| **Glossary** | the terms of art the page uses | every page that uses one |

## Copy

- The user's language (`[dashboard] lang` in `.keelokit/state.toml`); code, paths and ids stay
  as they are.
- Written for a founder who has never run a software project: every term of art (PRD, stack,
  epic, story, development wave, worktree, invariant, gap) is explained in plain words where it
  first appears and in the glossary.
- Spanish says **olas de desarrollo**, never "waves".
- A control says what it does ("Copy"); status says what is true ("Waits for AGENDA-002").

## Layout

One column up to 1080 px, 16 px side gutter, grids that wrap to one column at phone width.
Tables and code scroll inside their own box; the page never scrolls sideways.
