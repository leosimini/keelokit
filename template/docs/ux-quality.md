# UX quality: screens, journeys, and the proof

The product ships with design quality that was checked, not hoped for. This page is the standard
behind rules UX-1 to UX-4 (`.keelokit/harness/rules.toml`). Each line is a yes or no a reviewer
can answer by looking at the piece; "mostly" is no.

## 1. Every screen (UX-1)

| # | Criterion | Yes when |
|---|---|---|
| S1 | One purpose | The screen's one job fits in a sentence, and the main action is the most prominent thing on it |
| S2 | Hierarchy | What to read first, second and last is clear in a second; one primary action per view |
| S3 | System | Only components and tokens from the theme; no raw colour, size or spacing value in a screen |
| S4 | Text | Plain words for the person's goal, no internal terms; labels say what happens; errors say what went wrong and what to do |
| S5 | Accessibility | Contrast meets WCAG AA in every theme; touch targets ≥ 44 pt; every control reachable and named for a screen reader and the keyboard; nothing carried by colour alone |
| S6 | Adaptation | Right at the narrowest and widest configured width; long text, large type and a slow network don't break it |

## 2. Every state (UX-3)

| # | State | Yes when |
|---|---|---|
| T1 | Empty | Says why it is empty and offers the next step |
| T2 | Loading | Shows progress in the shape of what is coming; no layout jump when it arrives |
| T3 | Error | Says what failed in words, what to do, and offers the way out (retry, back, contact) |
| T4 | Success | Confirms what happened and offers the next step |
| T5 | No dead ends | Every screen has a visible way out; none leaves a person with nothing to press |

## 3. Consistency and coherence (UX-3)

- **System.** The same pattern for the same thing; spacing from the scale, uniform within a screen and across screens.
- **Vocabulary.** One word for one thing on every surface (app, web, email, notices). A glossary entry in `docs/context/product.md` settles each disputed term.
- **Journeys.** For each journey: where the person comes from and where they go next; going back loses nothing they entered; the same task works the same way on every surface.
- **Real device.** What a web preview can't show (notches and safe areas, keyboard covering a field, native gestures, permissions, OS back) is read in code, listed in the critique, and checked on a device when the story changes it.

## 4. The critique (UX-1)

Before a piece lands, a design specialist critiques it from its captures, not its description: the
session runs the design skills the environment has (`design:design-critique`, `design:ux-copy`,
`design:accessibility-review`, and `impeccable` for interface polish) or, with none installed, the
`reviewer` takes the criteria above one by one. The result is `CRITIQUE.md` in the piece's folder
with three sections, `Design critique` (each criterion S1–S6 and T1–T5: ok / fixed / open, with
the capture it was judged on), `Consistency and coherence` (system, vocabulary, journeys) and
`Real device` (what was read in code and what still needs a device). Findings are fixed before the
piece lands; an open one is a decision with a recommendation, never "later" (DEBT-1).

## 5. The captures (UX-2)

`docs/design/captures/<piece>/<surface>-<width>-<theme>-<state>.png`, for every surface, width and
theme in `.keelokit/ux.toml` (defaults: mobile 360 and 390, desktop 1280 and 1440, light and dark),
each state the piece has (`default`, `empty`, `loading`, `error`, `success`…). A piece is a story or
a screen; name the folder after it. `python3 .keelokit/bin/ux_gate.py` checks the matrix and the
critique's sections; the doctor runs it, so `pnpm verify`, the pre-push hook and CI refuse a branch
that changes interface files (`ui_paths`) without them.

No evidence is needed when the change cannot be seen: put `ux-gate: n/a — <reason>` on its own line in a
commit message (a refactor with no visual change, a rename). The gate passes and the doctor says so; the
reviewer judges the reason, and a reason that is false is BLOCKING.

## 6. Integration and releases (UX-3, UX-4)

- **Integrating pieces.** Whoever lands pieces (`coordinate`, or a convoy's integrator) rejects an
  interface piece without evidence and reviews the journeys that cross pieces: each one end to end,
  vocabulary and states included.
- **Release walk-through.** Each release candidate on staging is walked from start to finish on every
  surface, per journey and per theme, before the owner is told it is ready. Findings are P0 (the journey
  breaks), P1 (a wrong or misleading result, an inaccessible control), P2 (rough but usable), P3 (polish).
  **P0 and P1 stop production** (REL-1 keeps the decision with the owner).
