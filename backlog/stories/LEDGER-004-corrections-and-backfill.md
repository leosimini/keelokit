+++
id = "LEDGER-004"
epic = "LEDGER"
title = "Approved corrections and a backfill for the history that has no trailers"
wave = 8
depends_on = ["LEDGER-003"]
touches = ["template/.keelokit/bin/ledger.py", ".keelokit/bin/ledger.py", "template/backlog/ledger-corrections.toml", "copier.yml", "template/.gitignore", "template/.keelokit/bin/guard.py", ".keelokit/bin/guard.py", "template/.keelokit/bin/doctor.py", ".keelokit/bin/doctor.py", "hooks/hooks.json", "tests/test_ledger.py", "tests/test_guard.py", "tests/test_guard_corrections.py", "tests/test_doctor.py", "tests/test_copier.py", "docs/design.md", "CHANGELOG.md", ".gitignore"]
dimensions = ["logic", "integrity", "security", "data", "dx"]
invariants = ["INV-002", "INV-003", "INV-005", "INV-008"]
origin = "docs/ledger.md — Contracts (Corrections file); premortem failures 1 and 2"
+++
## Context
On day one most history has no trailers: 20 of this repo's 229 commits on `main` carry `Story:`, and an
adopted project may have none. A ledger that starts by saying almost nothing is done loses everyone's
trust. And a commit that slipped through without a trailer cannot be fixed by rewriting `main`.

Both are fixed by `backlog/ledger-corrections.toml` (format and rules in docs/ledger.md, "Corrections
file"): rows of story, commit, kind (`backfill`, `late`, `retract`), evidence, approver, date. The ledger
treats an active row as the fact that the story is `on-trunk`, shown as *reconstructed*.

- `ledger.py backfill --propose [--from FILE…]` writes candidate rows, each with a confidence and its
  evidence, to `.keelokit/ledger-corrections.proposed.toml` (git-ignored): commits that name the id in
  their subject or body; merges of branches with the id in their name; evidence files (`--from`): train
  sheets, a `BOARD.md`, Harbor's `harbor/imported/board.toml`, as lines of id → commit or train.
- `ledger.py correct <commit> --story <ID> --evidence "…"` proposes one late row.
- `ledger.py backfill --accept` moves the rows a person kept into the file, with `approver` from
  `git config user.name` and today's date. This is the `human` approval mode, the default; LEDGER-015
  adds `delegated` and `mixed`, where agents with an adversarial review may approve when the person
  enables it in `[ledger.approval]`.

The file is the human's, like `guard-allow.toml` (QA-4): the Claude hook blocks writes to it, a commit
that changes it needs `keelokit.allowTamper`, and a PreToolUse hook of the plugin denies `backfill
--accept` to agents (as Harbor denies `convoy approve`). The guard still only blocks or lets a call
through (INV-002). `copier.yml` lists the file under `_skip_if_exists` (INV-003).

**Decided (docs/ledger.md, "Decisions", 1, 2 and 4):** an approved correction counts for INV-005; the file
is append-only (INV-008, already in `docs/context/domain.md`); a person accepts, or agents with an
adversarial review when the person delegates it (LEDGER-015).

Does NOT do: rewrite history; accept rows by itself; read Harbor's logbook beyond the imported board file.

## User story
As the person responsible for a project that adopts the ledger, I want the history without trailers
reconstructed once with evidence I approve, and a way to attribute a commit that slipped through, so that
the ledger is right from day one and stays right without rewriting main.

## Acceptance criteria
```gherkin
Scenario: [S1] Candidates from commits that name the id
  Given commits whose subject or body mention UXC-113 and no Story: trailer for it
  When `ledger.py backfill --propose` runs
  Then the proposed file holds a row for UXC-113 with the commit, a confidence and the evidence

Scenario: [S2] Candidates from an evidence file
  Given a train sheet that maps train 18 to UXC-110 and UXC-111, and train 18's squash commit
  When it runs with `--from` that sheet
  Then both stories get a proposed row pointing at that commit

Scenario: [S3] Agents cannot write or accept
  When an agent writes the corrections file with a tool or the shell, or runs `backfill --accept`
  Then the Claude hook blocks it
  And a commit that changes the file is refused unless keelokit.allowTamper is set

Scenario: [S4] An accepted row reconstructs the story
  Given an accepted backfill row for UXC-113
  Then UXC-113 is on-trunk, marked reconstructed, with the row's evidence

Scenario: [S5] Append-only
  Given a row that is on the trunk
  When a later commit edits or removes it
  Then `ledger.py check` and the doctor report CORRECTION_EDITED

Scenario: [S6] Invalid rows
  Given a row whose commit is not reachable from the trunk, whose story does not exist, or with no approver
  Then CORRECTION_INVALID

Scenario: [S7] A retract cancels a row
  Given a backfill row and a later retract row for the same story and commit
  Then the story is no longer reconstructed from it

Scenario: [S8] A project receives the file
  Then the template ships an empty file with a header, copier.yml lists it under _skip_if_exists, and the
    proposed file is git-ignored
```

## Testable units
| Unit | Test type | File |
|---|---|---|
| propose (commits, merges, --from), correct, accept, retract, the ledger reading rows | unit, synthetic repos | tests/test_ledger.py |
| write protection and the accept denial | unit | tests/test_guard.py |
| CORRECTION_INVALID, CORRECTION_EDITED in the doctor | unit | tests/test_doctor.py |
| ownership in copier.yml | unit | tests/test_copier.py |

## Definition of done
`scripts/verify.sh` green, every scenario covered by a test titled with its id, invariants cited by
tests, `docs/design.md` mentions the file next to `guard-allow.toml`, a CHANGELOG line, `Story:
LEDGER-004` trailer, addendum if the result differs. Then (gate of phase 1) Leo runs the backfill on
this repo.

## Addendum — 2026-11-23

Decided (smallest option consistent with docs/ledger.md; the coordinator's delegation, decision 7):
- The corrections file is read from the trunk's tree, like the stories: a row counts once it is committed to the
  trunk. A row is invalid (`CORRECTION_INVALID`, ignored) when a field is missing or not text, the kind is not
  `backfill`/`late`/`retract`, the commit is not a full sha reachable from the trunk, the story does not exist, the
  approver is empty or `delegated:…` (only LEDGER-015's modes allow that), the date is not YYYY-MM-DD, or a retract
  has no earlier active row of the same story and commit. An unquoted TOML date is read as its text. Invalid TOML is
  one diff and no row counts.
- An active row whose commit is not reverted makes a story with no live `Story:` commit `on-trunk` (or higher, from
  that commit's tags and deploys), `reconstructed: true`, with the new per-story key `correction` (kind, commit,
  evidence, approver, date). A live `Story:` commit wins over rows. Several active rows: the oldest by arrival.
- Append-only (INV-008) compares every version of the file on the trunk's first-parent chain with the tip: a row of
  an earlier version (as a whole table) missing from the tip is `CORRECTION_EDITED`, named where it first was;
  removing the file counts. Two git calls whatever the number of versions. Reading never fetches: in a partial clone
  (what `history --ensure` leaves) earlier versions are often absent, so the check says `CORRECTION_UNCHECKED`
  (warning, new code added to docs/ledger.md) and the CI's full clone checks it.
- `ledger.py check [--json]` exists in a first form: the diffs, exit 1 on an error-level one, 0 on warnings only.
  LEDGER-005 adds `--ci` and its other codes. The doctor runs it and reports the `CORRECTION_*` diffs (errors stay
  errors); a ledger that cannot answer is a doctor warning.
- `backfill --propose` writes one row per story not yet on the trunk, the best candidate (confidence, then the newest
  arrival), its evidence naming up to three others. Confidence: a sha in an evidence file `high`; the subject naming
  the id, a merge of a branch named with it, or a train with exactly one commit `medium`; the body only, or a train
  with several commits `low`. Left out: commits with `No-story:`, reverted commits, the commit's own `Story:` ids
  and the commit that added the story's file. Trains are found by a `Convoy: N` trailer, `train|tren|convoy N` in
  the subject, or a merge of `convoy/N`, `train/N`, `train-N`; in an evidence file by those words, `T<N>`, or a
  Markdown table row whose first cell is the number (BOARD.md, and the rows Harbor keeps in its imported board).
- `backfill --accept` needs a terminal on stdin and stdout and a `y` to the question, so an agent's shell cannot run
  it even past the guard; it refuses everything when one proposed row is invalid, skips a row already active, ignores
  any approver or date in the proposed file (the approver is `git config user.name`, the date today), appends
  without rewriting a byte, and removes the proposed file. `correct` appends a `late` row to the proposed file.
- The plugin's PreToolUse hook that denies `backfill --accept` is the guard (`hooks/hooks.json` already sends every
  Bash call to it), so `hooks/hooks.json` is unchanged. The pre-commit hook lets the template's comments-only file be
  added without `keelokit.allowTamper`, as it does for `guard-allow.toml`.
- `.gitignore` (this repo's) joined the touches: Leo runs the backfill here, and the proposed file must stay out.

Measured on this repo (480 commits, 41 stories): `backfill --propose` proposes 8 rows, all `low` (bodies of docs
commits that mention stories not built yet: for the person to delete), none from the junk commits of ESC-090.
