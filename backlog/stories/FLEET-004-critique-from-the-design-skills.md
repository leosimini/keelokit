+++
id = "FLEET-004"
epic = "FLEET"
title = "The design critique comes from the design skills, and the UX gate checks it"
wave = 23
depends_on = []
touches = ["template/.keelokit/bin/ux_gate.py", "template/.keelokit/ux.toml", "template/docs/ux-quality.md", "skills/build-story/SKILL.md", "skills/coordinate/SKILL.md", "agents/reviewer.md", "tests/test_ux_gate.py", "CHANGELOG.md"]
dimensions = ["logic", "ux", "copy", "a11y", "dx"]
invariants = []
origin = "docs/fleet-lessons.md — lessons 5 and 6; JOUNA: 3 of 3 hand-made critiques missed P1/P2 findings, two about money"
+++
## Context
JOUNA ran the design skills over three critiques written "by hand, following their frameworks": all three
had missed findings (1 P1 + 5 P2; 7 P2 in a page promising "appears on Google"; 2 P1 + 8 P2 in closing an
organization, which did not say how much is refunded). The skills run took ~3 minutes as a subagent.

Keelokit's UX-3 gate requires `CRITIQUE.md` with four sections (`Journey`, `Design critique`, `Consistency
and coherence`, `Real device`). This story adds where the critique comes from:

- `ux.toml` gains `critique_skills = ["design:design-critique", "design:ux-copy",
  "design:accessibility-review"]` (product-owned; a project can change the list) and the gate requires a
  section `## Skills` in `CRITIQUE.md` with one subsection per skill, each with the date it ran, its
  findings with their priority, and what the piece did about each P1 and P2 (fixed, or decided with a
  reason). "Followed its framework by hand" does not count.
- `build-story` runs the skills from the start. A session without them asks the coordinator, who runs a
  subagent on a `wip/` branch that touches only `CRITIQUE.md`; the piece takes the section in.
- A later critique says whether it confirms or contradicts the earlier one (JOUNA: two design reviews
  solved the same gap two ways; the latest wins and the record says so).
- `ux-quality.md`'s consistency criteria gain: one navigation component per section of the app (JOUNA: two
  tab bars in Settings from two pieces).
- The reviewer checks that every P1 and P2 of the `## Skills` section is fixed or decided.

Like the rest of the gate, this checks that the section exists and is shaped right, not that a skill truly
ran; the reviewer is the backstop.

Does NOT do: run the skills in CI; judge the design itself.

## User story
As the person responsible for a product built by agents, I want every critique to come from the design
skills and every serious finding to be fixed or decided before the piece lands, so that a missed P1 does
not reach users.

## Acceptance criteria
```gherkin
Scenario: [S1] No Skills section fails
  Given an interface change with a CRITIQUE.md that has the four sections and no "## Skills"
  Then the UX gate fails and names the missing skills

Scenario: [S2] A skill missing fails
  Given a Skills section without design:ux-copy
  Then the gate fails naming it

Scenario: [S3] An open P1 fails
  Given a Skills section with a P1 neither fixed nor decided
  Then the gate fails naming the finding

Scenario: [S4] A complete section passes
  Given the three subsections, each dated, every P1 and P2 fixed or decided
  Then the gate passes

Scenario: [S5] The project's list rules
  Given critique_skills = ["design:design-critique"] in ux.toml
  Then only that subsection is required

Scenario: [S6] n/a still works
  Given a commit line `ux-gate: n/a — <reason>`
  Then the gate passes and the doctor reports it, as today
```

## Testable units
| Unit | Test type | File |
|---|---|---|
| the Skills section, the list, open findings, n/a | unit | tests/test_ux_gate.py |

## Definition of done
`scripts/verify.sh` green, every scenario covered by a test titled with its id, a CHANGELOG line with how
an adopted project updates `ux.toml`, `Story: FLEET-004` trailer, addendum if the result differs.

## Addendum — 2026-11-23
- **Shape decided by the coordinator:** `### <skill id>` per skill under `## Skills`, a `Ran: YYYY-MM-DD`
  line (a real date), findings as list items starting with their priority, every P1 and P2 ending
  `— fixed in <commit or file>` or `— decided: <reason>`. The parse is documented in `docs/ux-quality.md` §4.
- **P0 counts too.** The gate asks a fix or decision for P0 as well as P1 and P2 (a P0 is worse than a P1);
  the skills' own scale is mapped in the doc (Critical → P1, P0 when the journey breaks; Moderate/Major → P2;
  Minor → P3), and an item or table row graded only by a severity label is refused until it has a priority.
- **Every run is read.** Review and breaker found the first draft read only the first `Skills` section and
  the first subsection of a skill, so a later critique (which this story asks for) carried an open P1 past
  the gate (ESC-070), and that findings written as task boxes, `[P2]`, tables or wrapped lines escaped or
  were wrongly refused (ESC-071). The gate now reads every Skills section and subsection, skips fenced code,
  accepts a table row (fix in its last cell) and a wrapped item or a sub-bullet holding the fix.
- **`critique_skills` is checked:** anything but a list of skill ids is an error naming the key. Without the
  key (an adopted project) the three defaults apply; `[]` drops the section.
- Doc-only parts as written: the coordinator's subagent on a `wip/` branch (coordinate, build-story), a later
  critique confirms or contradicts the earlier one, one navigation component per section of the app, and
  the reviewer's check of every P1 and P2.
