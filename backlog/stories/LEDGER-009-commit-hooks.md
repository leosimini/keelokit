+++
id = "LEDGER-009"
epic = "LEDGER"
title = "prepare-commit-msg writes Part-of:, commit-msg checks the trailers"
wave = 14
depends_on = ["LEDGER-008"]
touches = ["template/.githooks/prepare-commit-msg", "template/.githooks/commit-msg", ".githooks/prepare-commit-msg", ".githooks/commit-msg", "template/.keelokit/bin/ledger.py", ".keelokit/bin/ledger.py", "hooks/hooks.json", "template/.keelokit/bin/doctor.py", ".keelokit/bin/doctor.py", "skills/project-new/SKILL.md", "skills/project-adopt/SKILL.md", "skills/harness-upgrade/SKILL.md", "skills/ship-release/SKILL.md", "skills/check-bugbash/SKILL.md", "tests/test_hooks.py", "tests/test_first_commit.py", "tests/test_copier.py", "CHANGELOG.md", "tests/test_doctor.py", "scripts/test-template.sh", "docs/escapes.md", "backlog/stories/LEDGER-009-commit-hooks.md"]
dimensions = ["logic", "integrity", "dx"]
invariants = ["INV-005", "INV-007"]
origin = "docs/ledger.md — Contracts (Trailers); premortem failures 5 and 10"
+++
## Context
The ledger is only as good as the trailers. These two git hooks make attribution cost nothing and catch
it when it is missing. Both are three-line shell wrappers; the logic is `ledger.py hook prepare` and
`ledger.py hook msg`.

- `prepare-commit-msg`: when the worktree has `keelokit.story` and the message has none of `Story:`,
  `Part-of:`, `No-story:`, it appends `Part-of: <ID>` with `git interpret-trailers --if-missing add`.
- `commit-msg`: checks the grammar of docs/ledger.md, "Trailers": one of the three is present; every id
  exists among the configured stories (`UNKNOWN_STORY`); `No-story:` uses a category of `[ledger] no_story`
  (`BAD_CATEGORY`); a `Story:` commit has a body (`STORY_NO_BODY`). Merge commits need no attribution (a
  merge's trailers, when present, are checked); `fixup!` and `squash!` commits are exempt. With
  `enforce = "warn"` it prints what is wrong and what to add, and lets the commit through; with `block` it
  refuses.
- The plugin's SessionStart sets `core.hooksPath = .githooks` when the repo has `.githooks/` and the key is
  unset, and says so in one line (decision 3 in docs/ledger.md, accepted: every cloud session is a fresh
  clone, so without it the git hooks never run there). The doctor's message for a hook that is not
  installed stops saying "a human runs `git config core.hooksPath`" and says the SessionStart hook turns
  them on (or gives the command, for a clone used without the plugin).
- The commits Keelokit's own skills make carry a trailer: `project-new`, `project-adopt` and
  `harness-upgrade` → `No-story: harness`; `ship-release` → `No-story: release`; `check-bugbash` fixes →
  `Finding: <ID>` (plus `Story:` when they close one).

**Decided:** INV-007 (docs/ledger.md, "Decisions", 2), already in `docs/context/domain.md`.

Does NOT do: check pushes (LEDGER-010); change what counts as done.

## User story
As anyone who commits in a Keelokit project, I want my commit attributed without thinking about it and
told plainly when it is not, so that the ledger never loses a piece of work.

## Acceptance criteria
```gherkin
Scenario: [S1] Part-of: is added from the worktree's story
  Given keelokit.story = AUTH-001 in this worktree
  When a commit is made without trailers
  Then its message ends with `Part-of: AUTH-001`

Scenario: [S2] No attribution
  Given no keelokit.story and no trailer
  Then with enforce = "block" the commit is refused with UNATTRIBUTED and the exact lines to add
  And with enforce = "warn" it is made and the same text is printed

Scenario: [S3] A category outside the list
  Given `No-story: misc`
  Then BAD_CATEGORY, listing the allowed categories

Scenario: [S4] A Story: commit without a body
  Then STORY_NO_BODY

Scenario: [S5] An unknown id
  Given `Part-of: NOPE-9`
  Then UNKNOWN_STORY

Scenario: [S6] Merges and fixups
  Then a merge commit without trailers passes, and so does a `fixup!` commit

Scenario: [S7] The hooks are turned on at the start
  Given a fresh clone with .githooks/ and no core.hooksPath
  When a session starts
  Then core.hooksPath is .githooks and one line says so

Scenario: [S8] The first commit of a generated project
  Then the first commit project-new makes passes the guard and both hooks
```

## Testable units
| Unit | Test type | File |
|---|---|---|
| hook prepare and hook msg, warn and block, merges, fixups | unit, temporary repos with the hooks installed | tests/test_hooks.py |
| the first commit | unit | tests/test_first_commit.py |
| the template ships both hooks, executable | unit | tests/test_copier.py |

## Definition of done
`scripts/verify.sh` green, every scenario covered by a test titled with its id, INV-005 cited, this repo's
own `.githooks/` gets both hooks, a CHANGELOG line, `Story: LEDGER-009` trailer, addendum if the result
differs.

## Addendum — 2026-11-24

Where the result goes beyond or differs from the text above:
- **`commit-msg` also adds `Part-of:`.** `prepare-commit-msg` leaves a message with no content alone (the editor is
  about to open, and a trailer there would turn an aborted commit into a commit called `Part-of: …`), so
  `hook msg` first does what `hook prepare` does. The editor flow gets the trailer once a subject is written.
- **`SQUASH_LOST_TRAILERS` at commit time.** A `Story:`/`Part-of:` line in a paragraph of its own before
  `Co-Authored-By:` is reported as that (with the line to move), not as `UNATTRIBUTED`.
- **The hook reads trailers as `git log` does** (`--no-divider`: a `---` line hides nothing, ESC-189) and keeps
  `#` lines unless git will drop them (`commit.cleanup`; unset: a `-m` message keeps them, the editor's comments
  go: `prepare-commit-msg` records git's source for `commit-msg`, `-e` with `-m` read as the editor flow; ESC-190,
  ESC-191, ESC-192). `Dropped:` alone does not attribute (as in `check`): `drop`'s fallback
  commit gets `Part-of:` from the story still taken. A `fixup!` commit passes the hook but `check` has no such
  exemption: it is meant to be squashed before it lands.
- An aborted editor commit (only comments) gets no Keelokit text: git's own "empty commit message" says it.
- **The story is read only in the worktree that took it (ESC-188).** `git worktree add` copies `config.worktree`,
  so a worktree added after `take` inherited `keelokit.story`. `take` now also records `keelokit.storyGitDir` and
  the hooks ignore a story another git dir took.
- **The hooks fail open** when they cannot run (an exception, an unreadable file): one `Keelokit:` line and the
  commit goes through; the pre-push and the CI (LEDGER-010) check again, and agents may not use `--no-verify`.
- **`check-bugbash` fixes carry `Part-of: <ID>`** next to `Finding: <ID>`: `Finding:` alone is not one of the
  three attributing trailers, so `commit-msg` would refuse it.
- **Adopted projects:** `project-adopt` writes `enforce = "warn"` with `since`, and `harness-upgrade` writes it for
  an adopted project that has no `enforce` (absent means `block`). An adopted repo gets no `.githooks/` from the
  template (harness mode installs `.keelokit/` only), so there the hooks arrive only if the repo wires them.
- `scripts/test-template.sh`'s two commits made with the hooks on carry `No-story: harness`.
- The hook messages are in English whatever `[dashboard] lang` says.
