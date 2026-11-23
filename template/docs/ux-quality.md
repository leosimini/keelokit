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
- **Navigation.** One navigation component per section of the app: a section never shows two tab bars, two side menus or a tab bar inside a tab bar, even when two pieces each added one.
- **Vocabulary.** One word for one thing on every surface (app, web, email, notices), and the same one in a card and in its detail. A glossary entry in `docs/context/product.md` settles each disputed term.
- **Journeys.** For each journey: where the person comes from and where they go next; going back loses nothing they entered; the same task works the same way on every surface.
- **Real device.** What a web preview can't show (notches and safe areas, keyboard covering a field, native gestures, permissions, OS back) is read in code, listed in the critique, and checked on a device when the story changes it.

## 4. The critique (UX-2)

Every new or changed screen or journey is critiqued **before** the adversarial review and before it
is handed over, from its captures, not its description, and through the lens of its surface (mobile
app or desktop web). The critique comes from the **design skills**, run from the start: the ones in
`critique_skills` in `.keelokit/ux.toml` (defaults `design:design-critique`, `design:ux-copy`,
`design:accessibility-review`), plus `impeccable` for interface polish when installed. A critique
written "by hand, following the skill's framework" does not count: hand-made critiques have missed P1
and P2 findings every time they were compared with a skills run, about money among them.

If the piece's session lacks the skills, it pushes the captures and asks whoever coordinates. The
coordinator runs a subagent with the skills on a `wip/` branch from the piece's branch that touches only
the piece's `CRITIQUE.md`; the piece takes that section in (cherry-pick or merge) and answers its
findings. With no design skills anywhere, set `critique_skills = []` in `ux.toml` with the reason in a
comment, and the `reviewer` takes the criteria above one by one.

Every P0, P1 and P2 finding is fixed, or decided with a reason. The result is `CRITIQUE.md` in the piece's
folder, with five sections: `Journey` (the person's journey as written before building), `Design
critique` (each criterion S1–S11 and T1–T5 as ok / fixed / open, with the capture it was judged on, what
was flagged, what was fixed, what remains and why), `Consistency and coherence` (system, navigation,
vocabulary, journeys), `Real device` (what was read in code and what still needs a device) and `Skills`
(below). Captures from before the fix go in the piece's `before/` folder, next to the after ones. An open
finding is a decision with a recommendation, never "later" (DEBT-1). The test: would the screen be
defended in front of a product designer? If not, it is not finished.

### The `Skills` section

One subsection per skill in `critique_skills`, titled with the skill's id; in it a line with the date the
skill ran, then its findings as list items, each starting with its priority (`P0` the journey breaks, `P1`
a wrong or misleading result or an inaccessible control, `P2` rough but usable, `P3` polish). Every P0, P1
and P2 item ends with what the piece did about it: `— fixed in <commit or file>` or `— decided: <reason>`.
A P3 needs neither. A skill that found nothing has its date and no items. The skills grade by their own
scale; give each finding its priority: Critical is P1 (P0 when the journey breaks), Moderate or Major is P2,
Minor is P3. One item per finding, on one line or wrapped with the next lines indented under it; a table
with a priority column works too. A skill run again on the same piece gets another `### <skill id>`
subsection with its own date, read like the first.

```markdown
## Skills

### design:design-critique
Ran: 2026-11-23
- P1 Closing the organization doesn't say how much is refunded — fixed in a1b2c3d
- P2 Settings shows two tab bars — decided: one bar; supersedes the critique of SETTINGS-002
- P3 The title could be shorter

### design:ux-copy
Ran: 2026-11-23
- P2 "Submit" says nothing about what happens — fixed in apps/web/src/close/CloseDialog.tsx

### design:accessibility-review
Ran: 2026-11-23
```

A later critique of the same screen or journey says whether it **confirms or contradicts** the earlier
one, naming it: two reviews that solve the same gap two ways leave the latest as the decision, and the
record says so.

What the gate reads (`.keelokit/bin/ux_gate.py`), and nothing more (fenced code blocks are skipped):

- every heading `Skills`, at any level; under each, every deeper heading whose text is the skill id (any
  case, backticks or bold allowed), for each skill in `critique_skills`; a heading's body runs to the next
  heading of its level or higher;
- in each of those subsections, a line `Ran: YYYY-MM-DD` with a real date (a leading `- ` or bold is fine);
- each list item (`-`, `*`, `+`, `1.` or `1)`, with its indented continuation lines) whose first word is a
  priority (`P1`, `**P1**`, `[P1]`, `- [ ] P1`…), and each table row with a cell that is only a priority:
  when it is `P0`, `P1` or `P2`, it ends with a dash (`—`, `–` or `-`) and `fixed in <something>` or
  `decided: <reason>`; nothing but the reason may follow (in a table, the cells after the priority hold it);
- an item or a cell that starts with a severity (Critical, Major, Moderate, Serious, Blocker, 🔴🟠🟡) and
  has no priority is refused: give it one.

The gate's message names the missing skill or quotes the open finding. Like the rest of the gate it checks
the shape, not that a skill truly ran or that a fix is real: the reviewer checks that (`agents/reviewer.md`).

## 5. The captures (UX-3)

`docs/design/captures/<piece>/<surface>-<width>-<theme>-<state>.png`, for every surface, width and
theme in `.keelokit/ux.toml` (defaults: mobile 360 and 390, desktop 1280 and 1440, light and dark),
each state the piece has (`default`, `empty`, `loading`, `error`, `success`…). A piece is a story or
a screen; name the folder after it. `python3 .keelokit/bin/ux_gate.py` checks the matrix and the
critique's sections, `Skills` included; the doctor runs it, so `pnpm verify`, the pre-push hook and CI refuse a branch
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
