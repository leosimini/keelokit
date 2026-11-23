+++
id = "LEDGER-007"
epic = "LEDGER"
title = "A new session knows where the truth is"
wave = 12
depends_on = ["LEDGER-006"]
touches = ["hooks/hooks.json", "template/AGENTS.md.jinja", "template/.keelokit/harness/agent-brief.md", "template/.keelokit/harness/execution-protocol.md", "AGENTS.md", "README.md", "README.es.md", "backlog/next.md", "tests/test_hooks.py", "tests/test_copier.py", "CHANGELOG.md"]
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
