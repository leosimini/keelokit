# Keelokit pages — design

Every page Keelokit shows a person (today, the project dashboard) carries the look of
[keelokit.com](https://keelokit.com), so it reads as part of the product. The spec lives in code:
`scripts/dashboard.py` holds the tokens, the CSS and the components below. A new page reuses that
CSS and header, never a hand-written style, and any change to the look is made there and here
together.

## Identity

- **Top bar** on the page ground: the Keelokit icon (`.claude-plugin/icon.svg`, 30 px, radius 8,
  soft blue shadow), the wordmark `Keelokit`, `/`, the product's name; at the right, chips for the
  run mode and the plugin version.
- **Sea band** under it, dark in both themes as on the site: the sea gradient
  (`#1A64B0 → #114D96 → #0B3574 → #07214E → #040F28`) with foam text. It holds the product name,
  the current stage, the next step and the stage stepper.
- **Title**: `Tablero de <product>` / `<product> dashboard`. Artifact icon: `dashboard`.

## Colour

The site's palette, unchanged: foam `#F6F1E8`, ink `#172126`, ink-2 `#4A5552`, line `#E3DCCF`,
sea `#1A64B0 #114D96 #0B3574 #07214E`, abyss `#040F28`, board `#FBC82A`, foil `#EE7B24`,
reef `#8FE0C4`.

| Role | Light | Dark (abyss ground) |
|---|---|---|
| Ground / paper / sunk | foam / `#FFFDF8` / `#EFE8DA` | abyss / `#081834` / `#0C2147` |
| Text / secondary / tertiary | ink / ink-2 / `#747B76` | foam at 100 / 74 / 52 % |
| Accent (links, ready) | sea `#114D96` | `#8FC0F2` |
| Done | `#1C7559` on reef tint | reef |
| Waits for you (review, a MUST) | `#AD540F` on foil tint | `#FFAE6B` |
| In progress | `#7A5C00` on board tint | board |
| Blocked | `#AE3F2D` | `#FF9A8A` |

Board yellow marks what you can act on: the copy button, the command prompt, the stepper dot of
the stage in progress. Status colour appears only in pills and stepper dots.

## Type

- Display: **Cormorant Garamond** 500/600 (italic for the current stage) — the product name,
  stage names, wave and epic names, the next step.
- Text: **Karla** 400–600, 16 px / 1.6. Eyebrows: 12 px, 600, uppercase, letter-spacing .16em.
- Data: **Fragment Mono** — ids (`AUTH-001`, `GAP-003`, `INV-002`), commands, paths, numbers.
- Fallbacks (Georgia, system sans, system mono) keep the page readable offline.

## Layout and behaviour

- 1160 px wrap, 16 px gutter. Main column of stages + a 330 px sticky side column (what waits for
  you, project decisions, glossary); on narrow screens the side column comes first, then stages.
- **Only what matters now is open.** Each stage is a collapsible card whose closed header still
  says enough: number, name, status, a one-line summary (e.g. "5 stories · 3 waves · 3 epics")
  and the approval date. The stage in progress or waiting for review opens by default; so does
  Build once every gate is approved. Inside the backlog, only the wave (or epic) with work left
  opens. Documents and stories stay closed until asked for. Links to a section open it.
- The stepper in the sea band mirrors the stages, like the site's numbered steps.

## Components

| Component | What it says |
|---|---|
| Next step | the one action, and its command in a terminal line with a copy button |
| Stepper | every stage with its status (dot: reef done, foil waiting for you, board in progress, hollow not started) |
| Stage card | what the stage is in plain words, what to check before approving (foil callout, only while waiting), its content and documents |
| Waits for you | approvals, blocking questions, harness errors, undecided run settings |
| Project decisions | project type (greenfield / brownfield), run mode and build mode with a lock (fixed once chosen), the apps, the recorded decisions |
| Backlog | stories by development wave or by epic (segmented control), progress per group |
| Build modes | one at a time vs in parallel, what each costs; the chosen one marked |
| Glossary | the terms of art the page uses |
| Ask Claude | a box every action button fills with its request; Send to Claude (page comment to the watching session) or Copy |
| Action buttons | pill buttons (primary: sea; in the sea band: board) that fill the Ask box, never act on their own |
| Bug bashes | each run: counts, findings with severity and the check added, pending decisions, the stories it created |
| History | stories done, bug bashes and stage approvals, newest first; closed by default |

## Copy

- The user's language (`[dashboard] lang`); code, paths and ids stay as they are.
- Written for a founder who has never run a software project: each term of art is explained in
  plain words where it first appears and in the glossary. Spanish says **olas de desarrollo**.
- A control says what it does ("Copy"); a status says what is true ("Waits for AGENDA-002").
