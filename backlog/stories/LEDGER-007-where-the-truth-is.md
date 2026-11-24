+++
id = "LEDGER-007"
epic = "LEDGER"
title = "A new session knows where the truth is"
wave = 12
depends_on = ["LEDGER-006"]
touches = ["hooks/hooks.json", "template/AGENTS.md.jinja", "template/.keelokit/harness/agent-brief.md", "template/.keelokit/harness/execution-protocol.md", "AGENTS.md", "README.md", "README.es.md", "backlog/next.md", "tests/test_hooks.py", "tests/test_copier.py", "CHANGELOG.md", "docs/ledger.md", "docs/escapes.md"]
dimensions = ["dx", "docs"]
invariants = []
origin = "docs/ledger.md — Mechanisms (Where the truth is)"
+++
## Context
A session without context should not need anyone to tell it anything: the hook shows the state and says
where to ask the rest.

- SessionStart runs `ledger.py history --ensure`, then `ledger.py` (the summary) followed by one line of
  where to look (`ledger.py show <ID>` for a story, `/harbor:log` for what is under way, `backlog/` for what
  is asked), then `doctor.py --brief`. At most 12 lines, framed as data.
- `template/AGENTS.md.jinja` gains a section *Where the truth is*: a table question → command ("Is X done,
  since when, in which version?" → `ledger.py show X`; "What do I take?" → `ledger.py next`; "Is someone on
  it?" → `ledger.py show X`; "Why did it end up this way?" → `ledger.py show X`; "What went into 1.16?" →
  `ledger.py --release v1.16.0`; "What is under way in the harbor?" → `/harbor:log`; "Is the record
  healthy?" → `ledger.py check`), and the rule: the state is asked of `ledger.py`, never of memory or of a
  handoff file.
- `agent-brief.md` ("The coordinator trusts nothing but origin/main") and `execution-protocol.md` (what
  "done" means) say the same.
- In this repo: `AGENTS.md` gets the section, both READMEs mention the ledger in one line, and
  `backlog/next.md` loses its "Where things stand" section (kept: what Leo does by hand).

Does NOT do: change the ledger's logic; activate git hooks (LEDGER-009).

## User story
As a session that opens a project for the first time, I want to see its state and where to ask
everything else, so that I start from facts instead of investigating or guessing.

## Acceptance criteria
```gherkin
Scenario: [S1] The start shows the summary and the map
  When a session starts in a project with Keelokit
  Then the hook prints the ledger's summary and where to look, in at most 12 lines, framed as data

Scenario: [S2] Without python3
  Then the hook prints one line, as today, and exits 0

Scenario: [S3] A generated project's AGENTS.md has the section
  Then the rendered AGENTS.md has "Where the truth is" with the table and the rule

Scenario: [S4] A fresh session answers from the ledger
  Given a fresh session in this repo, asked "is HARN-020 done, and why did it end up that way?"
  Then it answers citing `ledger.py show HARN-020` (a manual check; the result is written in the addendum)
```

## Testable units
| Unit | Test type | File |
|---|---|---|
| hook order, line bound, guards | unit | tests/test_hooks.py |
| the rendered AGENTS.md section | unit | tests/test_copier.py |
| a fresh session's answer | manual, recorded in the addendum | — |

## Definition of done
`scripts/verify.sh` green, S1–S3 covered by tests titled with their ids, S4 done by hand and written in
the addendum, a CHANGELOG line, `Story: LEDGER-007` trailer. Gate of phase 1: with LEDGER-004's backfill
accepted and `ledger.py check` clean, Keelokit 0.15.0 can be released.

## Addendum — 2026-11-23

Decided (smallest option consistent with the story and docs/ledger.md; the coordinator's delegation):
- "Framed as data" is the first line: `Keelokit: the state of this project, read from git (data, not instructions):`.
  The map line follows the summary and names `ledger.py show <ID>`, `/harbor:log`, `backlog/` and, for every other
  question, AGENTS.md's *Where the truth is* or `.keelokit/harness/agent-brief.md` (an adopted repo gets
  `.keelokit/` only, so its AGENTS.md has no such section). The hook stays one shell command in hooks/hooks.json:
  no new script, no change to the ledger's logic.
- The 12 lines: the hook captures the history line, the summary (`ledger.py`, its stderr included, so a failing
  ledger says why) and the doctor's brief first, then prints frame, history, summary, map, doctor. The doctor's
  brief is printed whole (its last line, `Harness errors`, matters most); the summary gets max(2, 10 − history −
  doctor) lines and, when cut, ends in "… N more lines: `python3 .keelokit/bin/ledger.py`" (ESC-155, ESC-156). A
  final `head -n 12` bounds an unusually long doctor. Without ledger.py there is no map and the doctor speaks as
  before; without python3, one line as before (S2).
- The timeout stays 30 s (history_seconds 20 + 10): the summary takes about 0.15 s and the doctor 0.7 s on this
  repo (546 commits), so the second ledger run fits; LEDGER-002's test pins 30.
- LEDGER-002's hook tests now expect the summary call between the history and the doctor, and the frame line.
- backlog/next.md loses only *Where things stand*; its intro points to `ledger.py`. Its *Stories* checklist is
  left as it is (the story names only the one section).
- The template's AGENTS.md puts *Where the truth is* after *Read first*; this repo's AGENTS.md before *Releases*,
  with 0.15 as the example version. docs/ledger.md's "built so far" names LEDGER-007; docs/ledger.md and
  docs/escapes.md joined the touches.

S4, done by hand on 2026-11-23: a fresh agent given only the session start's output (this repo, main d4fc5ee) and
the question "is HARN-020 done, and why did it end up that way?" ran `python3 .keelokit/bin/ledger.py show
HARN-020` first, then read the story's Context and Addendum. It answered: done, `in-version` v0.14.0 since
2026-11-11 (approximate), with the why from the ledger's card (escapes ESC-044..052 quoted from docs/escapes.md)
and the addendum's changes, citing each source.

Review: light tier (dimensions dx, docs; the hook is shell logic, so not trivial), tests written before the hook,
one reviewer, two rounds. Round 1: ESC-155..157, plus the adopted-repo map wording; each reproduced first as a
failing test. Round 2: APPROVE.

Left as it is: a doctor brief longer than about 8 lines (four or more profile drift lines) still loses its last
lines to the final `head -n 12`, `Harness errors` included; the order of `doctor.py --brief` is the doctor's, outside
this story's touches (the reviewer's round-2 note).
