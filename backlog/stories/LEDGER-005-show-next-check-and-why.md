+++
id = "LEDGER-005"
epic = "LEDGER"
title = "ledger.py show, next and check, with the why of every story"
wave = 10
depends_on = ["LEDGER-015"]
touches = ["template/.keelokit/bin/ledger.py", ".keelokit/bin/ledger.py", "tests/test_ledger.py", "docs/design.md", "docs/ledger.md", "CHANGELOG.md"]
dimensions = ["logic", "dx", "docs"]
invariants = []
origin = "docs/ledger.md — Contracts (commands, difference codes); premortem failure 6"
+++
## Context
The rework that started this epic comes from decisions and failed attempts nobody wrote down: a state
alone does not say why. `show` gathers the why from the places it already lives, so a new session asks
instead of investigating (docs/ledger.md, "`ledger.py` commands").

- `show <ID> [--full]`: state and date (exact or approximate), commits with their subject and
  `Claude-Session:`, version, environments, branches, the story file and its *Addendum* headings, and the
  why: bodies of its `Story:` and `Part-of:` commits, rows of `docs/escapes.md` and findings in
  `docs/bugbash/` that name the id or arrive through a `Finding:` trailer on its commits, attempts
  (`Dropped:` commits on any remote branch), corrections. At most 60 lines; paths, not long contents.
- `next`: `ready` stories that are not `in-progress`, by wave and id.
- `check [--ci] [--json]`: every difference of docs/ledger.md, "Exit codes and difference codes", with its
  level and exit code.
- `--release vX.Y.Z`: the stories that entered that version (the commits between the previous tag and it).

Does NOT do: change any state; read Harbor (LEDGER-013) or swarm branches (LEDGER-014); enforce anything.

## User story
As a session that starts without context, I want one command that tells me a story's state and why it
ended up that way, so that I don't redo work or investigations someone already did.

## Acceptance criteria
```gherkin
Scenario: [S1] show gathers the why
  Given a done story whose Story: commit has a body, whose file has an Addendum, and a row of docs/escapes.md that names it
  When `ledger.py show <ID>` runs
  Then the output has the body, the addendum heading and the escape row, each with its path

Scenario: [S2] show lists an abandoned attempt
  Given a `Dropped: <ID>` commit on an origin branch with its reason
  Then show lists it as an earlier attempt with the reason and the branch

Scenario: [S3] show finds findings through Finding:
  Given a commit of the story with `Finding: LOG-303` and a bug-bash report that has LOG-303
  Then show lists LOG-303 with the report's path

Scenario: [S4] next excludes work in progress
  Given two ready stories, one of them with a Part-of: branch
  Then next lists only the other

Scenario: [S5] check finds an unknown id
  Given a trailer `Story: NOPE-001` on the trunk
  Then check reports UNKNOWN_STORY and exits 1

Scenario: [S6] check warns about a stale branch
  Given an in-progress branch with no commit for more than stale_days
  Then check reports STALE_BRANCH as a warning and exits 0

Scenario: [S7] --release
  Given tags v1.0.0 and v1.1.0 and two Story: commits between them
  Then `--release v1.1.0` lists exactly those two stories

Scenario: [S8] show is bounded
  Given a story with more than 60 lines of material
  Then show prints at most 60 lines and says how to see the rest (--full)
```

## Testable units
| Unit | Test type | File |
|---|---|---|
| show's sources, its bound, next, check's codes and exit, --release | unit, synthetic repos | tests/test_ledger.py |

## Definition of done
`scripts/verify.sh` green, every scenario covered by a test titled with its id, a CHANGELOG line,
`Story: LEDGER-005` trailer, addendum if the result differs.

## Addendum — 2026-11-23

Decided (smallest option consistent with the story and docs/ledger.md; the coordinator's delegation, decision 7):
- `check` alone gives the codes whose "Given by" column names `check` (or the hooks): the attribution codes,
  `STALE_BRANCH`, `DONE_TWICE`, `SNAPSHOT_BEHIND`. `ledger.py` and `--json` keep LEDGER-003/004/015's `diffs`
  (`HISTORY_INCOMPLETE`, `CORRECTION_*`, `PENDING_REVIEW`) and their exit codes: a stale branch does not turn the
  summary's exit into 1. `check` exits 1 on an error-level difference, 0 on warnings only (S6).
- The attribution codes read the trunk commits after `[ledger] since` (not reachable from it): `UNATTRIBUTED` (no
  `Story:`/`Part-of:`/`No-story:` of its own nor on the first-parent commit that brought it, as LEDGER-003's count;
  a merge with none is attributed when every non-merge commit it brings in is, ESC-130..132),
  `SQUASH_LOST_TRAILERS` (such a commit whose message has `Story:`/`Part-of:` lines git does not read as trailers:
  a squash's body, or a line outside the last paragraph; reported instead of `UNATTRIBUTED`; ESC-133), `BAD_CATEGORY` (a `No-story:` whose category, the text
  before the first space, dash of any kind or colon, compared as written, is not in `[ledger] no_story`; an empty
  `No-story:` is only `UNATTRIBUTED`), `STORY_NO_BODY` (a `Story:` commit with no
  line outside its subject paragraph and its trailer paragraph; git's `(cherry picked from commit …)` line counts as a
  trailer). A `Story:` line git did not read as a trailer is `SQUASH_LOST_TRAILERS` even when the commit is
  attributed otherwise (ESC-125). `UNKNOWN_STORY` (a `Story:`/`Part-of:` id with no story file on the trunk, or a
  value that is not an id at all, ESC-123) reads the same range, or every trunk commit when there is no `since`; skipped while a story
  file is unreadable. Errors under `enforce = "block"` (the default), warnings under `"warn"`.
- `DONE_TWICE`: a known story whose live `Story:` commits arrived on the trunk through more than one first-parent
  commit (two commits of one merged branch are one delivery). `STALE_BRANCH`: once per in-progress story with the
  `stale` signal, naming its branches. `SNAPSHOT_BEHIND`: `origin/<[ledger] snapshot>` exists and its `ledger.json`
  is not of the trunk's head (LEDGER-011 writes it; `snapshot = ""` turns it off); one `cat-file`, only when the
  branch exists. Two sessions on one story (two branches) are listed by `show` and the summary, with no code: the
  table has none outside Harbor's `STORY_TAKEN`.
- `--ci` reads as the CI does: `HISTORY_INCOMPLETE` is an error (as with `CI` set).
- `show <ID> [--full]`: header (state in `[dashboard] lang`, date with exact/approximate, reconstructed by whom,
  reverted, stale, the unknown reason), version and candidate, environments, branches, the file and its
  `# … Addendum` headings (path:line, outside code fences), the commits (the trunk's `Story:` and `Part-of:` and
  the origin branches' `Part-of:`; `Story:` first, then newest first) with date, subject, `Claude-Session:` and
  body (6 lines each unless `--full`), attempts, active correction rows, `docs/escapes.md` table rows and
  `docs/bugbash/**/*.md` lines that name the id, and bug-bash headings and escape rows that name a `Finding:` id of
  its commits. Without `--full` lines are cut at 200 characters and the card at 60 lines, the last one saying
  `ledger.py show <ID> --full`. A value with newlines prints as several lines inside the bound (ESC-121) and
  terminal control characters are replaced by `?`, with `--full` too (ESC-127). A candidate is shown only for a
  story with no version yet. Exit 1 for an id that is not a story; with a cut history only the header and the
  file (the facts are unknown). Convoy events wait for LEDGER-013.
- Attempts: `Dropped: <ID>` commits off the trunk on origin branches, and on the trunk (named by the trunk), fill
  the story's `attempts` in `--json` (`commit`, `branches`, `date`, `reason`: the body, else the subject). A
  `Dropped:` commit does not end `in-progress` here: LEDGER-008 (`drop`) owns that.
- `next`: the `ready` stories (in-progress already wins over ready), by wave (none last) then epic and number.
  With a cut history, or any story `unknown` (a partial clone lacking story blobs), it names them with the reason
  and exits 1 (ESC-126).
- `--release vX.Y.Z`: the stories with a commit (`Story:`, reverted later or not (ESC-124), or an active
  correction's) reachable from the tag and not from
  the previous final version tag in version order (rc tags are never the previous one); the first version takes
  everything before it. An unknown or non-version tag exits 1.
- The trunk log carries every trailer (`%(trailers:only,unfold)`) and the branch log the `Dropped:` trailer and the
  body: still one call each, so the S10 budget holds (`show` adds one `cat-file` for the story file, escapes and
  bug-bash files).
- docs/ledger.md joined the touches for its "built so far" line.

Left as they are, after review: `DONE_TWICE` also fires when one branch lands two `Story:` commits by a fast-forward
or rebase (no merge commit to group them: this repo's HARN-009/017/019 follow-up fixes); a `since` that names no
single commit turns the attribution codes off without a difference, as LEDGER-003's count; `check` in a shallow clone
gives `HISTORY_INCOMPLETE` as a warning and exits 0 outside CI (the table's level; `--ci` and the CI make it an
error); `show` does not say that escapes or bug-bash files are absent from a partial clone; a finding only in a
report table (not a heading) is found by `Finding:` only if the row also names the story.

Review and attack: a reviewer and a breaker, one round (ESC-121..127, each reproduced first as a failing test).

On this repo (no `[ledger] since` yet) `check` reports `UNKNOWN_STORY` on the ESC-090 junk commits on main
(`AUTH-001`, `A-001`, `PAY-001`, …) and `DONE_TWICE` for HARN-009, HARN-017 and HARN-019: writing `since` (the
0.15.0 upgrade step) clears the first; the phase-1 gate needs it.
