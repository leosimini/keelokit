+++
id = "FLEET-005"
epic = "FLEET"
title = "A money story's breaker walks every failure path, and its copy cannot make anyone move money twice"
wave = 24
depends_on = []
touches = ["agents/breaker.md", "agents/reviewer.md", "references/invariants.md", "references/dimensions.md", "skills/build-story/SKILL.md", "tests/test_process.py", "CHANGELOG.md"]
dimensions = ["logic", "copy", "docs"]
invariants = []
origin = "docs/fleet-lessons.md — lesson 9; JOUNA: two refund bugs already on main, past tests and reviews"
+++
## Context
JOUNA's two money bugs of the night were already on `main`, had passed tests and reviews, and showed up
only when someone asked what happens when something fails:
- the app told the organizer to "refund by hand" while the job was still retrying the refund (risk:
  refunding twice);
- closing an organization deleted its Mercado Pago connection with refunds still in flight (a refund that
  never goes out, and nobody sees it).

Keelokit's breaker attacks a story in full mode and the invariant classes call for replay and concurrency
tests, but nothing makes the breaker walk failure paths one by one, and COPY-1 asks whether a promise has a
test, not whether a text can make someone act twice.

- `agents/breaker.md`: for a story with `integrity` or the `payments` trait, the attack report has one line
  per failure path, each with the test or the reason it cannot happen: automatic retry still running; a
  response lost after the money moved; the connection or credential removed mid-flight; a double submit;
  a close, cancel or delete with operations pending; a manual instruction shown while an automatic one is
  still running.
- `agents/reviewer.md` and COPY-1's review: every text near money answers "can this text lead someone to
  move money twice, or not at all?"
- `references/invariants.md`: the failure-path list under the replay and one-time-effect classes, with
  JOUNA's two bugs as examples (no project data, only the shape).
- `build-story`: a money story's contract lists its failure paths before any code.
- Decisions about money that the agents take inside what the person already decided are recorded as
  reversible and the person is told; anything new about money waits for the person (execution protocol,
  unchanged).

Does NOT do: add a mechanical check (a breaker report is a review); change who decides about money.

## User story
As the person responsible for a product that moves money, I want every money story attacked on its
failure paths and every text near money read for double action, so that the bugs that cost real money are
found before they ship.

## Acceptance criteria
```gherkin
Scenario: [S1] The breaker's checklist
  Then agents/breaker.md lists the six failure paths and requires one line per path, with a test or a reason, for integrity and payments stories

Scenario: [S2] The copy question
  Then agents/reviewer.md asks of every text near money whether it can lead someone to move money twice or not at all

Scenario: [S3] The contract lists the paths
  Then build-story's contract step lists a money story's failure paths before the verifier writes tests

Scenario: [S4] The reference
  Then references/invariants.md has the failure-path list under replay and one-time effects, with two anonymized examples
```

## Testable units
| Unit | Test type | File |
|---|---|---|
| the agents' and skill's text carries the checklist and the question | unit | tests/test_process.py |

## Definition of done
`scripts/verify.sh` green, every scenario covered by a test titled with its id, a CHANGELOG line,
`Story: FLEET-005` trailer, addendum if the result differs.

## Addendum — 2026-11-23

- **What makes a money story** was left open: `integrity` alone, or anything in a project with
  `payments`. Settled as one definition, worded the same in the breaker, `build-story` and
  `invariants.md`: the `integrity` dimension, or a story that moves money in a project with the
  `payments` trait. Such a story is always **full** in `build-story`'s step 0, so the breaker
  always runs on it (ESC-101).
- **The breaker's report limit** (10 lines beyond the BROKEN items) left no room for six path lines;
  the six FAILURE PATHS lines are now outside the limit too (ESC-100).
- **Reversible money decisions vs the execution protocol**: the protocol reserves "anything that
  moves money or touches payment configuration" for the human, with no exception. The contract
  item says so explicitly: it covers how the code handles money inside what the person decided,
  never moving money or changing payment configuration; the protocol itself is unchanged (ESC-102).
- The failure-path list in `invariants.md` is a subsection of the `once` tests
  ("once: the failure paths of a money movement"), right after the replay test; the `integrity` row
  of `dimensions.md` and its `copy` row carry the paths and the money question.
- The six paths are pinned by key phrases ("retry still running", "response lost", "credential
  removed", "double submit", "operations pending", "manual instruction"); like any text check, the
  tests can't tell that a sentence makes the line optional. That stays with the review.
