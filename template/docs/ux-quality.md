# UX quality: screens, journeys, and the proof

The product ships with design quality that was checked, not hoped for. This page is the standard
behind rules UX-2 to UX-5 (`.keelokit/harness/rules.toml`). Each line is a yes or no a reviewer
can answer by looking at the piece; "mostly" is no.

## 1. Every screen (UX-2)

Before building, write the **person's journey**: what they come to do, where they arrive from, where
they go when they finish, and what happens if something they need is missing. The screen is built
from that, not the other way round. Before it lands, whoever built it looks at it running and goes
through these lists; each point that fails is fixed, or noted in the handoff with its reason.

| # | Criterion | Yes when |
|---|---|---|
| S1 | One purpose | One goal per screen, the main action the most prominent thing on it; on a first use only the essentials, the advanced folded away or kept for editing |
| S2 | Every block earns its place | Each block answers what the person came to do on this screen, or it goes; nothing duplicated on the screen, nothing repeated that is already one tap away |
| S3 | Hierarchy | What to read first, second and last is clear in a second; one primary action per view |
| S4 | Title and instruction | A title says what the screen is, and one line says what to do |
| S5 | System | Only components and tokens from the theme; no raw colour, size or spacing value; air between blocks from the spacing tokens; cards of the same kind identical (height, structure, text) |
| S6 | Text | Plain words for the person's goal, no internal terms; labels say what happens; follows the project's style guide |
| S7 | Nothing unusable | No option that can't be used yet: if it depends on something that doesn't exist, the screen explains and offers to create it, or doesn't show it |
| S8 | Every way out explained | No link or button without saying where it leads |
| S9 | Order follows dependencies | The steps come in the order the person needs them (what one step needs is done before it) |
| S10 | Accessibility | Contrast meets WCAG AA in every theme; touch targets ≥ 44 pt; every control reachable and named for a screen reader and the keyboard; nothing carried by colour alone |
| S11 | Adaptation | Nothing cut at the narrowest configured width or with large type; on large phones the height is used (look at it at about 412 wide and on a tall phone, not only the smallest); right at the widest desktop width; long text and a slow network don't break it |

## 2. Every state and every ending (UX-4)

| # | State | Yes when |
|---|---|---|
| T1 | Empty | Says why it is empty and offers the next step |
| T2 | Loading | Shows progress in the shape of what is coming; no layout jump when it arrives |
| T3 | Error | Appears where the person is looking, says what failed in words, what to do, and offers the way out (retry, back, contact) |
| T4 | Success / ending | Saving or finishing leads to a place that confirms what was done and offers the next step; never back to the same screen without a notice |
| T5 | No dead ends | Every screen has a visible way out; none leaves a person with nothing to press |

## 3. Consistency and coherence (UX-4)

- **System.** The same pattern for the same thing; spacing from the scale, uniform within a screen and across screens.
- **Vocabulary.** One word for one thing on every surface (app, web, email, notices), and the same one in a card and in its detail. A glossary entry in `docs/context/product.md` settles each disputed term.
- **Journeys.** For each journey: where the person comes from and where they go next; going back loses nothing they entered; the same task works the same way on every surface.
- **Real device.** What a web preview can't show (notches and safe areas, keyboard covering a field, native gestures, permissions, OS back) is read in code, listed in the critique, and checked on a device when the story changes it.

## 4. The critique (UX-2)

Every new or changed screen or journey is critiqued **before** the adversarial review and before it
is handed over, from its captures, not its description, and through the lens of its surface (mobile
app or desktop web). The session runs the design skills the environment has (`design:design-critique`,
`design:ux-copy`, `design:accessibility-review`, and `impeccable` for interface polish) or, with none
installed, the `reviewer` takes the criteria above one by one. If the piece's session lacks the skills,
it pushes the captures and asks whoever coordinates for the critique.

Every P1 and P2 finding is fixed. The result is `CRITIQUE.md` in the piece's folder, with four
sections: `Journey` (the person's journey as written before building), `Design critique` (each
criterion S1–S11 and T1–T5 as ok / fixed / open, with the capture it was judged on, what was
flagged, what was fixed, what remains and why), `Consistency and coherence` (system, vocabulary,
journeys) and `Real device` (what was read in code and what still needs a device). Captures from
before the fix go in the piece's `before/` folder, next to the after ones. An open finding is a
decision with a recommendation, never "later" (DEBT-1). The test: would the screen be defended in front
of a product designer? If not, it is not finished.

## 5. The captures (UX-3)

`docs/design/captures/<piece>/<surface>-<width>-<theme>-<state>.png`, for every surface, width and
theme in `.keelokit/ux.toml` (defaults: mobile 360 and 390, desktop 1280 and 1440, light and dark),
each state the piece has (`default`, `empty`, `loading`, `error`, `success`…). A piece is a story or
a screen; name the folder after it. `python3 .keelokit/bin/ux_gate.py` checks the matrix and the
critique's sections; the doctor runs it, so `pnpm verify`, the pre-push hook and CI refuse a branch
that changes interface files (`ui_paths`) without them.

The gate checks that the evidence exists, is committed and is complete for every piece the branch touches; it can't tell that the captures show *this* change, which is the reviewer's check. If no tracked file matches `ui_paths`, the gate says so (set `ui_paths` to your apps' folders).

No evidence is needed when the change cannot be seen: put `ux-gate: n/a — <reason>` on its own line in a
commit message (a refactor with no visual change, a rename). The gate passes and the doctor says so; the
reviewer judges the reason, and a reason that is false is BLOCKING.

## 6. Integration and releases (UX-4, UX-5)

- **Integrating pieces.** Whoever lands pieces (`coordinate`, or a convoy's integrator) rejects an
  interface piece without evidence and reviews the journeys that cross pieces: each one end to end,
  vocabulary and states included.
- **Release walk-through.** Each release candidate on staging is walked from start to finish on every
  surface, per journey and per theme, before the owner is told it is ready. Findings are P0 (the journey
  breaks), P1 (a wrong or misleading result, an inaccessible control), P2 (rough but usable), P3 (polish).
  **P0 and P1 stop production** (REL-1 keeps the decision with the owner).
