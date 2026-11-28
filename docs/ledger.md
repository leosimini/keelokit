# The ledger — design and plan (being built)

This is the design of the ledger and the plan to build it. Built so far: completing the trunk's history
(LEDGER-001, LEDGER-002), `ledger.py`'s states from git, its summary and `--json` (LEDGER-003), and the
corrections file with `backfill`, `correct`, a first `check` and the doctor's report of it (LEDGER-004), the
delegated review of corrections (LEDGER-015), and `show`, `next`, `--release` and every code of `check`
(LEDGER-005), and the doctor, the dashboard, `status.py` and the skills reading it (LEDGER-006), and the session start and every agreement pointing to it (LEDGER-007), and the CI snapshot, exact arrival times and the deploy branches (LEDGER-011); the decisions each took are in its story's addendum. The rest does not exist yet: [design.md](design.md)
describes Keelokit as it is. Each story in
`backlog/stories/LEDGER-*.md` cites the section of this file it implements; a story that needs
something this file does not say adds it here first.

The proposal and its premortem, in Spanish, are in the Claude doc *Registro de historias en Keelokit:
propuesta* (two tabs: the proposal, and the implementation plan this file mirrors).

## Why

On 2026-11-22 a coordinator in a project built with agents reported six trains as never shipped; one
had been on `main` since 2026-11-10. The facts were in git; the reading and the hand-kept board failed:

1. **A shallow clone.** Keelokit has the same failure today, silently. On this repo, with `main` at
   `a082db4`, `doctor.py --brief` says *16/20 done* with the full history (229 commits) and *3/20 done*
   on a `--depth 30` clone, with no error or warning. Cloud sessions clone shallow: this repo's clone in
   the session that measured it had 59 of 229 commits.
2. **States written by hand.** A board, `backlog/next.md` ("Where things stand after 0.8.3" while the
   repo is at 0.14.0): someone has to remember.
3. **No state per story outside `main`.** "In progress" is only visible on one machine (`status.py` reads
   worktrees); "delivered" is in Harbor's logbook; "in version 1.4" is rebuilt by hand in `ship-release`;
   "in production since" is nowhere. And only 20 of this repo's 229 commits on `main` carry `Story:`.

## The principle

A story's state is derived from facts, never declared by an agent. Keelokit already does this for one
state (INV-005: done iff a commit reachable from `main` carries `Story: <ID>`). The ledger extends it
to every state, keeps the *why* next to the *what*, and gives every session one command to ask.

`ledger.py` computes; it stores nothing a person or agent writes by hand. Hooks make sure the facts
exist. Harbor and Swarm feed it facts they already own, read-only. No GitHub Issues, Projects or API:
only git and the CI the project already has.

## Contracts

These are fixed before any story is built.

### Files

| File or ref | What it is | Owner |
|---|---|---|
| `.keelokit/bin/ledger.py` | The ledger. Python 3.11+, stdlib only. All hook logic lives here | Template (arrives with `harness-upgrade`) |
| `.githooks/prepare-commit-msg`, `.githooks/commit-msg` | Three-line wrappers that call `ledger.py hook prepare` and `ledger.py hook msg` | Template |
| `backlog/ledger-corrections.toml` | Approved corrections: old history and late attributions | Product (`_skip_if_exists` in `copier.yml`) |
| `.keelokit/ledger-corrections.proposed.toml` | What the backfill proposes, for review | Local, git-ignored |
| branch `keelokit/ledger` | The snapshot: `LEDGER.md`, `ledger.json`, `moves.toml` | The CI only |
| branches `deploy/staging`, `deploy/production` | Point at the commit deployed to each environment | The deploy job only |

### Configuration (`.keelokit/state.toml`; every key has a default)

```toml
[ledger]
stories = "backlog/stories/*.md"   # an adopted repo: e.g. "5-Roadmap/stories/*.md"
id_from = "front-matter"           # or "filename": the EPIC-NNN prefix of the file name
trunk = "main"                     # default: [harbor] trunk when present
since = "<sha>"                    # attribution is required from this commit on (the adoption commit)
enforce = "block"                  # block | warn: commit-msg, pre-push and CI follow it.
                                   # project-new and this repo: block; project-adopt: warn (see below)
no_story = ["harness", "docs", "release", "deps", "ci"]
stale_days = 7
history_seconds = 20               # the SessionStart hook's cap to complete the history
snapshot = "keelokit/ledger"       # "" turns the snapshot off
```

### Trailers

In the last paragraph of the message, as `git interpret-trailers` reads them.

| Trailer | Means | Written by |
|---|---|---|
| `Story: <ID>[, <ID>]` | Closes the story (as today). The commit has a body: what was decided and what was left out | The landing commit, in `build-story` |
| `Part-of: <ID>[, <ID>]` | Work of the story that does not close it | `prepare-commit-msg`, from `git config keelokit.story` |
| `No-story: <category>[ — <reason>]` | Work outside stories; the category is one of `[ledger] no_story` | Whoever commits; `commit-msg` requires one of the three |
| `Finding: <ID>` | Fixes a bug-bash or review finding | Whoever fixes it |
| `Convoy: <n>` | The merge commit of a Harbor convoy | `harbor.py convoy assemble` |
| `Swarm-Task: <id>` | Made by a swarm helper | The helper prompt, or the swarm runner |
| `Dropped: <ID>` | An abandoned attempt; the reason is the body | `ledger.py drop` |

- `<ID>` matches `[A-Z][A-Z0-9]*-[0-9]+` and exists among the configured stories.
- A `Story:` commit has a body: at least one line outside the subject and the trailers.
- A merge commit's trailers cover the commits it brings in: those reachable from its second parent and not
  from its first.
- A merge commit with no trailer of its own (GitHub's "Merge pull request #N from …", a sync of the trunk into a
  branch) is attributed when every non-merge commit it brings in — reachable from its non-first parents and not
  from its first — is attributed. A merge that brings nothing new is attributed. A merge that brings an
  unattributed commit is `UNATTRIBUTED`, and so is that commit.
- Git reads trailers only in the message's last paragraph: a `Story:`/`Part-of:` line in a paragraph of its own
  before `Co-Authored-By:` or `Claude-Session:` is not a trailer (`SQUASH_LOST_TRAILERS`). Put every trailer in
  the same final paragraph, with no blank line between them.
- `Claude-Session:`, which cloud sessions already add, links a commit to the session that made it.

### States

A story has one state: the most advanced one the facts prove. From lowest to highest:

| State | The fact that proves it | Source |
|---|---|---|
| `defined` | The story file is on the trunk | git |
| `ready` | Every `depends_on` is `on-trunk` or later | git |
| `in-progress` | Commits with `Part-of: <ID>` not on the trunk, on any `origin` branch whatever its name; or a Harbor worker holding the story | git, `harbor/log` |
| `delivered` | A Harbor vessel sealed on its exact head, with its convoy and state | `harbor/log` |
| `on-trunk` | A commit with `Story: <ID>` reachable from the trunk, or a correction row (shown as *reconstructed*) | git |
| `in-version` | The first `v*` tag that contains that commit; an `-rc.N` tag is a candidate | git |
| `in-staging`, `in-production` | `origin/deploy/staging` or `origin/deploy/production` contains the commit. A project without environments (library, plugin) stops at `in-version` | git |

- A revert of the `Story:` commit on the trunk (`This reverts commit <sha>.`) turns `on-trunk` back into
  `ready`, marked `reverted`.
- A state that depends on missing history is `unknown`, with the reason; never a lower state.
- `in-progress` with no new commit in `stale_days` carries the signal `stale` (a signal, not a state).
- Displayed in the language of `[dashboard] lang`.

### `ledger.py` commands

| Command | Does |
|---|---|
| `ledger.py` | The summary in at most 10 lines |
| `ledger.py show <ID> [--full\|--json]` | The story's card (`--json`: the record and the why as data, below): state, date (exact or approximate), commits with subject and `Claude-Session:`, version, environments, branches, the file and its *Addendum* headings, and the why: bodies of its `Story:`/`Part-of:` commits, rows of `docs/escapes.md` and findings of `docs/bugbash/` that name it or arrive through `Finding:`, attempts (`Dropped:`), corrections, convoy events. At most 60 lines without `--full`; paths, not long contents |
| `ledger.py next` | `ready` stories not `in-progress`, by wave and id |
| `ledger.py take <ID>` / `take --clear` | Sets or clears `git config --worktree keelokit.story` (see LEDGER-008); with Harbor, `harbor.py story take`/`release` first (LEDGER-013) |
| `ledger.py drop <ID> --motivo "…"` | Records an abandoned attempt (see LEDGER-008) |
| `ledger.py check [--ci] [--json]` | Every difference, with its code |
| `ledger.py --json` | Everything, for the dashboard, the coordinator, Harbor and the CI |
| `ledger.py --release vX.Y.Z` | The stories that entered that version |
| `ledger.py history --ensure` | Completes the trunk's history (SessionStart) |
| `ledger.py backfill --propose [--from FILE…]` / `backfill --accept` | Proposes correction rows / accepts them (a person only) |
| `ledger.py correct <commit> --story <ID> --evidence "…"` | Proposes a late attribution |
| `ledger.py review --filter` / `backfill --accept --delegated <run>` / `review --reject-sample <run>` | The delegated review's mechanical filter / writing its approved rows / sending a run back (a person) |
| `ledger.py attribution <a>..<b> [--json]` | Whether every commit of a range is attributed, as `check` attributes it (Harbor's `convoy add` calls it; contract below) |
| `ledger.py hook prepare\|msg`, `ledger.py prepush` | The git hooks' logic |
| `ledger.py snapshot [--run ID] [--push BEFORE..AFTER]` / `snapshot --branch` | Writes the snapshot branch (the CI only; the time from `KEELOKIT_SNAPSHOT_AT`, the push event's) / prints its name, empty when off (the CI's gate) |
| `ledger.py deploy <staging\|production> <commit>` | Moves `deploy/<env>` to the deployed commit (the deploy jobs only, after a deploy that ran; backwards on a rollback) |

### `--json` (schema 1)

```json
{"schema": 1, "trunk": "main", "trunk_sha": "a082db4…", "history": "complete",
 "stories": [{"id": "UXC-113", "title": "…", "epic": "UXC", "wave": 3, "state": "in-version",
   "since": "2026-11-10T14:02:00Z", "since_exact": true, "commit": "a1b2c3d…", "convoy": 18,
   "version": "v1.15.0", "environments": {"staging": "…", "production": null},
   "reconstructed": false, "reverted": false, "branches": [], "attempts": [], "swarm": [], "signals": []}],
 "unattributed": {"since": "…", "commits": 0, "ratio": 0.0},
 "diffs": [{"level": "error", "code": "UNKNOWN_STORY", "detail": "…"}]}
```

`history` is `complete`, `snapshot:<sha>` or `incomplete`. New keys may be added; existing keys never
change meaning within schema 1.
LEDGER-013 added `harbor` (`logbook`: the logbook commit read or null, `skipped`, `error`) and, on each story,
`delivered` (null or `{convoy, convoy_state, branch, head}`) and `workers` (the active Harbor workers holding it).
LEDGER-014 added `swarm` (`error`) and fills each story's `swarm` list ("What the ledger reads of Swarm").

### Exit codes and difference codes

Exit 0: no difference. 1: differences or a refusal. 2: the environment (no git, no trunk).

| Code | Level | Given by |
|---|---|---|
| `UNKNOWN_STORY`, `UNATTRIBUTED`, `BAD_CATEGORY`, `STORY_NO_BODY`, `SQUASH_LOST_TRAILERS` | error | `hook msg`, `prepush`, `check` |
| `CORRECTION_INVALID`, `CORRECTION_EDITED` | error | `check`, the doctor |
| `CORRECTION_UNCHECKED` (a partial clone lacks earlier versions of the corrections file, so append-only is checked in CI only) | warning | `check`, the doctor |
| `HISTORY_INCOMPLETE` | error in CI, warning in a session | every reader |
| `STALE_BRANCH`, `SNAPSHOT_BEHIND`, `DONE_TWICE`, `PENDING_REVIEW` | warning | `check` |
| `BREAKER_MISSING` (a risky story closed with no breaker round recorded), `BREAKER_CONFIG` (a `.keelokit/risky.toml` it cannot use: every closed story counts as risky) | error | `check` (a pull request too) |
| `RISKY_NO_STORY` (after the breaker rule's start, a commit, or a merge's own resolution, changes a risky path and names no story; a `No-story: release` commit touching only the release files excepted) | error | `check` (a pull request too) |
| `RISKY_AFTER_CLOSE` (after the breaker rule's start, a commit, or a merge's own resolution, changes a risky path under `Story:`/`Part-of:` of stories all closed by a live `Story:` commit of an earlier landing; commits the close reaches, commits the commit recording the resolved story's last round reaches, and reverts excepted) | error | `check` (a pull request too) |
| `BREAKER_STALE` (a risky commit of the story that came before its close — the close reaches it, or it landed earlier — is not reached by the head of its last round, clean or decided by a person) | error | `check` (a pull request too) |
| `BREAKER_UNRESOLVED` (the last round left findings with no person's Decision after it; the last round decides, past the cap too), `BREAKER_BAD_ENTRY` (a line under `## Breaker rounds` that is neither a round nor a Decision) | warning | `check` (a pull request too) |
| `NO_STORY`, `STORY_TAKEN`, `STORY_ON_TRUNK`, `LEDGER_DIFF` | refusal | `harbor.py` (Harbor's plan) |
| `UNATTRIBUTED` | refusal | `swarm.py deliver` (Swarm's plan) |

### Breaker rounds (HARN-021)

A story is **risky** when its front matter says `risky = true`, when one of its `dimensions` is in
`.keelokit/risky.toml`'s `dimensions`, when one of its `touches` meets a glob of its `paths`, or when a trunk commit
of the story (`Story:` or `Part-of:`) changes such a path; `ledger.py risky <ID>` says whether and why. A risky story
closes only with its cold breaker rounds recorded in its file:

```
## Breaker rounds
- Round 1 · head <full sha> · 2 findings: ESC-312, ESC-313 · fixed in a1b2c3d, e4f5a6b
- Round 2 · head <full sha> · clean
- Decision · <person> · <YYYY-MM-DD> · <what was decided>      (only when the last round left findings)
```

The last round decides, whatever its number (HARN-022): a clean last round resolves the story, past the cap too. A
last round with findings is `BREAKER_UNRESOLVED` until a later round is clean or a person's Decision follows it; its
detail says which comes next (below the cap: the next round; at or past it: a person). The cap is where the build
must stop and ask. A touch that names a directory (it ends in `/`, or its last part has no extension: `apps/api`,
`.github`) meets every glob that can match a path beneath it (`**/migrations/**`). A risky change committed under
the trailer of stories already closed by an earlier landing (before the rule, or with their rounds) is
`RISKY_AFTER_CLOSE`: their rounds never saw it and nothing closes them again, so it names an open story, which then
needs its own rounds. One rule, however the branch lands (merge, fast-forward, rebase) and in the pull request alike:
a later commit lands with the close when the commit that recorded the story's last round in its file comes after it
(reaches it), while that round is clean or a person's Decision follows it. So the closing branch's commits before its
round line are judged with the close, and a fix after the round was recorded is reported before it lands. A later
change to a closed story is accepted only when a new round line recorded after it covers it: a reopening with its own
round. A touch naming the repository root (`./`, `/`, `.`) meets every glob; every spelling of one directory is one;
`.` and `..` inside a touch are normalised, and one that leaves the repository names nothing. The commit that recorded
a round is found by the story's id, over every file under the stories' glob, never by its current path: renaming or
copying the file moves nothing.

A round's head (full, or 7 to 63 hex digits that resolve uniquely) must be a commit some live close of the story reaches: the head
the breaker attacked, on the branch that closes it. Any other head is `BREAKER_BAD_ENTRY` and that round counts as not
clean. When the last round is clean, a risky commit of the story that the close reaches and the round's head does not
(it landed after the round, the `Story:` commit itself included, or it landed on the trunk before the close outside
its branch, as a parallel delivery does; a merge counts by its own change: its tree against git's automatic merge of its parents, `git merge-tree`, conflicted paths included; and when either side renamed to or from a risky path, or the merge base is not one commit, every risky path whose content differs from every parent's) is `BREAKER_STALE` (error); a last round
a person decided covers only what its head saw too: run a round on the code that lands. A branch rewritten as it lands (a rebase or a squash)
rewrites the heads away, so its rounds count as not clean on the trunk (warnings): merge `origin/main` after the
rounds and land with a merge commit. After the close, a change is covered only by a new round whose head reaches it,
recorded by a re-close (a later `Story:` commit); a revert counts only as the exact inverse of a commit that exists
here, and a revert of a risky change is itself a risky change: it needs its own round, like any change after the close. A revert of a merge reverts
a commit the merge brought only when it changes back exactly what that commit changed, path by path.

`check` reads the story file and `risky.toml` from the trunk's committed tree (`--rules-ref`'s with that flag), and
for a pull request the base's `risky.toml` and committed `[ledger]` with the pull request's story file. The rule holds
for `Story:` commits that the first commit to bring `risky.toml` to the trunk does not reach (a later add moves
nothing; its `since` key can only move the start later), and after `[ledger] since` when it is set: stories closed
before are exempt by position, never by editing them. No `risky.toml` on the trunk: no rule. A `Decision` counts
when it names one of `risky.toml`'s `deciders`, or, with none listed, a name that is no agent's or model's. A closed
id whose story file is gone, moved or broken is still judged by what its commits change. An unknown key in
`risky.toml` is `BREAKER_CONFIG`. In a pull request, `check --ci` reads the base branch's committed `state.toml` when
it has one, so a pull request cannot move the trunk it is judged on (nor loosen its own `enforce`, which changes
what an existing pull request's attribution check says when it edits state.toml). Risk is the union over every copy
of the story's file, its earlier version (as `risky.toml` found it on the trunk, or as the base has it), and every
trunk or pull-request commit of the story that changes a risky path; the rounds come only from the file as it is.
Rounds numbered other than 1, 2, … count as none, and nothing inside a code fence or an HTML comment is a record.
`risky.toml`, `state.toml` and `backlog/ledger-corrections.toml` are always risky paths; once `risky.toml` was on the
trunk (added by a commit or by a merge's own resolution), its absence fails closed. Risk is sticky across every
committed version of every file under the stories' glob, for the id its own front matter gives (whatever it is
named). Without `deciders`, a Decision name with digits, a non-Latin letter or a known agent, bot or model word is
refused. Only the `since` of `risky.toml` as it first
reached the trunk counts. A round is clean only when its whole result reads `clean`.

Reverts, ledger-wide: a commit reverts X only when its message says so and its change is X's inverted as git records
it (each path's modes and blob ids: no whitespace rule, binary file or `.gitattributes` can fake it); a message-only or partial "revert" is an ordinary commit. With the whole history (the CI's
clone), a "revert" of a sha that is no commit reverts nothing, and a change git cannot read counts no revert on a
message's word (it fails closed, ESC-374); a shallow or partial clone keeps the message's word for its states, and the
CI's full clone decides. The line is a record, as a trailer is: `check` asks that it is there and well
formed, not that the round happened.

### Corrections file

```toml
[[row]]
story = "UXC-113"
commit = "a1b2c3d4e5f6…"   # full sha, reachable from the trunk
kind = "backfill"           # backfill | late | retract (cancels an earlier row: same story and commit)
evidence = "train sheet 18; BOARD.md row T18"
approver = "Leo"
date = "2026-11-25"
```

Append-only: no row already on the trunk may change, move or disappear (`CORRECTION_EDITED`); the versions read
are the first-parent ones and those each parent of a first-parent merge had. A bad edit is undone by putting the
rows back as they were (reverting the edit does it), then cancelling a wrong row with a `retract`. Protected like
`guard-allow.toml`: the Claude hook blocks writing it, a commit that changes it needs
`keelokit.allowTamper`, and `ledger.py backfill --accept` is denied to agents by a PreToolUse hook (as
Harbor denies `convoy approve`), except in a delegated approval (below).

### Approval modes

Who approves correction rows is the person's choice, made once per project (LEDGER-015):

```toml
[ledger.approval]
mode = "mixed"                     # human (default) | delegated | mixed
human_for = ["critical", "disagreement", "low-confidence"]   # mixed only
sample = 0.05                      # share of delegated approvals shown to the person for a spot check
```

| Mode | Who approves | The person's work |
|---|---|---|
| `human` | The person, row by row | Review everything |
| `delegated` | Agents, with an adversarial review | Nothing required; the sample if they want |
| `mixed` | Agents for the clear rows; the person for critical stories, low confidence and disagreements | Only the queue of exceptions |

A delegated review (`workflows/ledger-review-flow.js`): a mechanical filter with no model drops every row
it can prove wrong; two independent judges read the story's criteria, the diff and the evidence; a skeptic
tries to refute a row both approved. A row is approved only when both judges say yes and the skeptic
fails; otherwise it goes to the person (`mixed`) or stays pending (`PENDING_REVIEW`, `delegated`). Stories
in a critical area go to the person in `mixed`. A delegated row has `approver = "delegated:<run id>"` and
its verdicts are committed in `.keelokit/ledger-reviews/<run id>.json`; the ledger shows *reconstructed
(delegated)* or *(person)*. The `[ledger.approval]` table is protected like the corrections file, so no
agent authorizes itself. The proposer never approves its own rows.

### Performance and trust

- A fixed number of git calls, never one per story. Budget: under 2 s on 10 000 commits and 700 stories,
  measured by a test on a synthetic repo (as the doctor's NFR-1).
- As today, the plugin runs the project's `.keelokit/bin/`. Whatever HARN-004 decides applies to
  `ledger.py` too.

## Mechanisms

| Mechanism | When | Guarantees | Story |
|---|---|---|---|
| Fail-closed reading | every read | an incomplete history says `unknown`, never a low number | LEDGER-001 |
| SessionStart hook | each session | completes the trunk's history (commits only, capped), activates the git hooks, prints the summary and where to look; falls back to the snapshot | LEDGER-002, 007, 009, 011 |
| `take` / `drop` | starting / abandoning a story | the story the worktree works on; abandoned attempts stay readable | LEDGER-008 |
| `prepare-commit-msg` | each commit | `Part-of:` from `keelokit.story`, whatever the branch is called | LEDGER-009 |
| `commit-msg` | each commit | the trailer grammar; warns or blocks per `enforce` | LEDGER-009 |
| pre-push and CI | each push to the trunk, each PR | nothing unattributed reaches the trunk; a squash keeps its branch's trailers; a merge attributes what it brings | LEDGER-010 |
| Corrections | once for old history, and when something slipped through | the old history and late attributions, approved by a person or, when the person delegates it, by agents with an adversarial review | LEDGER-004, LEDGER-015 |
| CI snapshot | each push to the trunk and each tag | a cheap read for short sessions; the exact time each commit reached the trunk | LEDGER-011 |
| Deploy branches | each successful deploy | `in-staging`, `in-production` | LEDGER-011 |
| LEDGER-1 | each doctor run | every enforcer above is alive | LEDGER-012 |
| "Where the truth is" | each session reads it | state is asked of `ledger.py`, never of memory or a handoff file | LEDGER-007 |

## Harbor and Swarm

Each keeps its own state; the ledger reads it and never writes it. Both detect `ledger.py` and behave as
today without it.

- **Harbor** (plan: `docs/ledger-phase6.md` in `leosimini/keelokit-harbor`): `Convoy: <n>` on convoy
  merges; `convoy add` refuses an unattributed vessel (`NO_STORY`); `harbor.py story take` is a lock in the
  logbook (`STORY_TAKEN`); the harbormaster's round runs `ledger.py check --json` and the ok refuses a
  convoy with a difference (`LEDGER_DIFF`). Keelokit's side: LEDGER-013, below.
- **Swarm** (plan: `docs/ledger-refs.md` in `leosimini/enjambre`): an opaque `ref` on tasks; the helper
  prompt sets the hooks and the story; the runner writes `Part-of:` and `Swarm-Task:` itself; `deliver`
  refuses an unattributed delivery (`UNATTRIBUTED`); `swarm-ask` asks for `plugin:keelokit`. The ledger
  never reads the swarm repo: it sees deliveries as `swarm/*` branches in the code repo. Keelokit's side:
  LEDGER-014.

### What the ledger reads of Harbor, and the contracts Harbor reads (LEDGER-013)

The logbook (`origin/harbor/log`, as the last fetch left it; the ledger never fetches or writes it) is read with
git, as data, never by running Harbor. It only raises a story that is not on the trunk and dates or names the
convoy of one that is; it adds no difference, so nothing in it changes `check`, the diffs or an exit code. A file
that is not what Harbor writes (not UTF-8 TOML, a wrong type, larger than 1 MiB) is left out and counted in
`--json`'s `harbor.skipped`; a logbook git cannot read is none (`harbor.error`).

| Fact in the logbook | Gives |
|---|---|
| `workers/<account>/<host>/<session>.toml` with `state = "active"` and `story` (HRB-2) | `in-progress` (from `defined` or `ready`); the record's `workers` |
| `convoys/<n>.toml` assembling, waiting, ready or verifying, with a `[[vessels]]` whose `head` has a green run (`runs/<head>.toml` or `seals/<head>.toml`, `exit = 0`) and whose `origin/<branch>`, when it exists, is still that head | `delivered`, `convoy = n`, the record's `delivered` (`convoy`, `convoy_state`, `branch`, `head`); several convoys: the highest number |
| the `Convoy: <n>` trailer of the first-parent merge that brought an on-trunk story's commit (git, no logbook needed); else a sailed convoy whose `[sail]` `main_before..main_after` holds it; else a `main.toml` move with `cause = "convoy <n>"` | the record's `convoy` |
| `main.toml`'s move with `cause = "convoy <n>"` whose `from..to` holds the commit's arrival | `since` from its `seen`, `since_exact = true` (unless the CI's `moves.toml` already gave an exact time); a `loose` move gives none |

`show` adds the delivery, the workers and the convoy's events (the last 8; all with `--full`). The snapshot path
(a cut history) does not read the logbook.

**`ledger.py show <ID> --json`** prints `{"schema": 1, …the story's record as --json gives it, "history": …,
"why": {"addenda", "commits", "corrections", "escapes", "findings", "convoy_events"}}` (`why` is null with a cut
history); each commit is `{sha, date, kind ("Story"|"Part-of"), branches, subject, session, body}`. The id is
matched exactly, else without case. No such story: exit 1 and `{"schema": 1, "id": …, "error": …}`, with no
`state`.

**`ledger.py attribution <a>..<b> [--json] [--rules-ref <rev>]`** (Harbor's `convoy add`): exit 0 when it answered, even with
unattributed commits; 2 for a usage error, a range that is not `<a>..<b>`, or an end that does not resolve to a
commit; 3 when the history is incomplete.

```json
{"schema": 1, "range": "<a>..<b>", "ok": true,
 "commits": [{"sha": "<40 hex>", "subject": "…", "story": ["AUTH-001"], "part_of": [], "no_story": null,
              "merge": false, "attributed": true, "via": "own"}],
 "unattributed": ["<sha>"], "stories": ["AUTH-001"],
 "since": "<sha>|null", "diffs": [{"level": "error", "code": "BAD_CATEGORY", "detail": "…"}]}
```

`commits` are those `<b>` reaches and `<a>` does not, in `git rev-list --reverse` order, attributed exactly as
`check` attributes (the same function): a commit's own `Story:`/`Part-of:`/`No-story:`, an active correction row,
a merge with one that brings it, or, for a merge, everything it brings being attributed (`via`: `own`,
`correction`, `merge`; null when not attributed; a merge with its own trailer is `own`), with the arrivals of
`<b>`'s first-parent chain, as `check --ci` reads a pull request. `ok`: every non-merge commit is attributed.
`[ledger]` (`since`, `no_story`, `stories`) comes from the trunk's committed `state.toml` (origin/<trunk>), never
the checkout's; with `--rules-ref <rev>`, from `<rev>`'s, and the rules and corrections as for `check --rules-ref`.
`stories`: the union of `story` and `part_of`, sorted. As in `check`, commits `[ledger] since` reaches are left out
(`since` names it; null when it names no commit here, and then the whole range counts). `diffs` adds what `check`
says of those commits besides `UNATTRIBUTED` (`BAD_CATEGORY`, `UNKNOWN_STORY`, `STORY_NO_BODY`,
`SQUASH_LOST_TRAILERS`): a `No-story:` with an unknown category is attributed and still an error there. Without
`--json`: a line per unattributed commit, those diffs, and a summary line.

**`ledger.py check [--ci] --json [--rules-ref <rev>]`** (Harbor's harbormaster round and the ok, HRB-3) prints
`{"schema": 1, "diffs": [{"level": "error"|"warning", "code": "<CODE>", "detail": "…"}]}`; keys may be added,
none changes meaning within schema 1; exit 1 iff a diff is an error. `--rules-ref <rev>`: the rules come from
`<rev>`'s committed tree, never the trunk's or the checkout's (the whole `.keelokit/state.toml`, `critical.toml`, the
review files, `critical.toml` at a row's own arrival on `<rev>`'s history, and the story files' touches and
dimensions for the critical flag), and the corrections: a row counts only when `<rev>`'s own corrections file holds
it, identical (a row only the candidate adds attributes nothing and is no error). Harbor passes main's tip when it
judges a convoy as landed. Exit 2 when `<rev>` is
no commit here, or when a rule file it has is not in this clone (a partial clone).

### What the ledger reads of Swarm (LEDGER-014)

The ledger never reads the swarm repo. A swarm helper delivers a branch `swarm/<task>` in the code repo, and its
commits carry `Part-of: <ID>` and `Swarm-Task: <task>` (SWM-2). They add information to a story's record, its `swarm`
list, and nothing else: no difference, no attribution (a `Swarm-Task:` alone attributes nothing; `check`,
`attribution` and `--rules-ref` read only the trailers they always read), no state (an unintegrated delivery is
`in-progress` by its `Part-of:`, as any branch is).

| Fact | Gives, in the story's `swarm` list |
|---|---|
| a non-merge commit off the trunk on `origin/swarm/<task>` with `Part-of: <ID>` and one `Swarm-Task: <task>`, that same task | `{"task", "state": "in-progress", "branch": "swarm/<task>", "head": <the branch's tip>, …}`; `convoy`: the open convoy whose vessel is that branch sealed on that head (as `delivered` reads it), else null |
| a non-merge trunk commit with one `Swarm-Task: <task>`, the story's by its own `Story:`/`Part-of:`, else by the trunk merges that bring it with one | `{"task", "state": "on-trunk", "branch": null, "head": null, …}`, `"state": "reverted"` once a revert on the trunk undid it (as a `Story:` commit's revert is read); `convoy`: the convoy that brought it, read as an on-trunk story's convoy is |

Each entry: `{task, state, branch, head, commits (oldest first), authors (sorted), convoy}`, one per story, task,
state and convoy; `authors` are the commits' author names as recorded (no mailmap),
cut to 200 characters (control characters, tabs and newlines shown as `?`). A task id is `[A-Za-z0-9][A-Za-z0-9._-]{0,127}`; a commit with none, or with two different
ones, is no delivery, nor is one on a branch outside `swarm/<task>`. `--json` adds `swarm: {error}` (null, or why
the lists are empty: whatever goes wrong reading Swarm's trailers is never a crash). `show` lists the deliveries
under *swarm deliveries* (task · state · branch@head · convoy · authors), and each listed commit's task and author
under it; `show --json`'s commits add `author` and `swarm_task`. A snapshot carries the lists; an entry of the wrong
shape (a key missing or extra, a control character, tab or newline in a name) is left out, never the snapshot; a shallow clone
whose snapshot is behind the trunk leaves out the snapshot's trunk deliveries (on-trunk, reverted) when a revert
landed since, or may have (a history it cannot read back, a rewritten trunk): it cannot vouch for them now.

**`ledger.py take <ID>` with Harbor**: when `git config --local harbor.py` names an absolute path to a file called
`harbor.py` (Harbor records it when it adopts a project) and `harbor.py story take --help` exits 0 (asked by
feature, never by version), `take` first runs `harbor.py story take <ID>`: exit 0 is the take (its line is relayed,
then `keelokit.story` is set); exit 1 is Harbor's refusal (`STORY_TAKEN`, `STORY_ON_TRUNK`, …), relayed as one line,
exit 1, nothing set; any other exit, or no answer in `KEELOKIT_HARBOR_SECONDS` (default 180), is exit 2, nothing
set. An unregistered session's take is Harbor's check only (its `worker register --story` is the real take).
`take --clear` runs `harbor.py story release <ID>` of the worktree's story; the worktree is cleared whatever
Harbor says, and a release Harbor did not make is exit 1 (2 without an answer). The session id goes to Harbor as
Harbor reads it (`HARBOR_SESSION`, `CLAUDE_SESSION_ID`), else `CLAUDE_CODE_SESSION_ID` handed over as
`HARBOR_SESSION` (never as an argument). Without Harbor,
or with one without `story take`, `take` is as before.

## Plan

| Phase | Stories | Gate | Release |
|---|---|---|---|
| 0 — read well | LEDGER-001, LEDGER-002 | On a `--depth 30` clone of this repo the doctor says 16/20 after the hook, or that it cannot; never 3/20. The hook's time is measured on a fresh clone of a large project | (with phase 1) |
| 1 — the ledger, read-only | LEDGER-003, 004, 015, 005, 006, 007 | This repo's backfill accepted (by Leo, or in `mixed` mode with Leo's queue), `ledger.py check` with no error, and a fresh session answers "is HARN-020 done, and why did it end up that way?" by citing `ledger.py show` | Keelokit 0.15.0 |
| 2 — the fact always exists | LEDGER-008 to LEDGER-012 | `scripts/test-template.sh` walks a generated project from `take` to `in-production` against a local remote, with nobody writing a state | Keelokit 0.16.0 |
| 3 — Harbor and Swarm | HRB-1..3 (Harbor), SWM-1..3 (Swarm, can run alongside phase 2), LEDGER-013, LEDGER-014 | In a test project with Harbor and a swarm, a convoy carrying a swarm delivery lands and `ledger.py show` says each piece's story, who made it and which convoy sailed it | Keelokit 0.17.0, Harbor 0.6.0 |

Keelokit's stories are built one at a time (`[run] build = "serial"` here, and almost all of them touch
`ledger.py` or the doctor); their waves are 5 to 19 so no two share one (LEDGER-015 is wave 9).

### Versions and compatibility

| Version | Brings | Needs | On upgrade |
|---|---|---|---|
| Keelokit 0.15.0 | LEDGER-001..007, LEDGER-015 | — | `harness-upgrade`; write `[ledger] since`; choose `[ledger.approval] mode`; `ledger.py backfill --propose`, then the review |
| Keelokit 0.16.0 | LEDGER-008..012 | 0.15.0 | `harness-upgrade` brings the hooks, the CI step and job, the deploy jobs; `enforce = "warn"` in an adopted project, `block` in a generated one; CHANGELOG *Upgrading from 0.15.x* |
| Harbor 0.6.0 | HRB-1..3 | Keelokit 0.16.0 for the new parts; with an older one it behaves as 0.5 | `claude plugin update`; the logbook stays `schema = 1` (`story` on workers is an optional key) |
| Swarm: protocol v3, section 27 | SWM-1..3 | — unless SWM-1 finds that an unknown task field breaks older tools: then a new protocol version and `migrate` | update each swarm repo's template |
| Keelokit 0.17.0 | LEDGER-013, 014 | Harbor 0.6.0, Swarm section 27 | `harness-upgrade` |

Releases follow [releasing.md](releasing.md): a CHANGELOG line per story under `## Unreleased`,
`scripts/release.sh X.Y.Z` only when Leo asks, the CI's "update from" row moved to the new tag. A scan
finding from the plugin directory (the new hooks, the `core.hooksPath` change) gets a real fix or a line in
the submission notes.

### Measuring, switching to block, going back

- Measured with `ledger.py check --json`: the share of unattributed commits on the trunk since `since`, the
  error-level differences, and the hook's history time (it prints it).
- A generated project and Keelokit itself start in `block`: almost every commit is made by an agent with
  the hooks on, which write the attribution themselves, so there is nothing to get used to.
- An adopted project starts in `warn` and moves to `block` after 3 days in a row with zero unattributed
  commits and zero error differences, with at least 20 commits in that window. The doctor recommends it;
  the coordinator (or a person) switches it.
- Going back: `enforce = "warn"`; a dated LEDGER-1 exception in `exceptions.toml`; `snapshot = ""`; Harbor
  and Swarm detect the ledger. A wrong correction row is cancelled with a `retract` row.

## Decisions (taken by Leo on 2026-11-22; 6 and 7 by the coordinator on 2026-11-23)

These change existing rules or invariants, so a person decided them (execution protocol: new invariants
and product rules wait for the human). All five were accepted as proposed. INV-007 and INV-008 are in
`docs/context/domain.md`; INV-005's new wording lands with LEDGER-003.

1. **INV-005 changes.** Today: a story is done iff a commit reachable from `main` carries its `Story:`
   trailer. Proposed: *a story is on the trunk iff a commit reachable from the trunk carries its `Story:`
   trailer, or an approved correction names it, and no revert of that commit is on the trunk.*
   (LEDGER-003, LEDGER-004) **Accepted.**
2. **New invariants**, proposed for `docs/context/domain.md`:
   - *INV-007: every commit that reaches the trunk after `[ledger] since` is attributed, by its own
     trailers or by a merge that brings it — class: consistency.* (LEDGER-009, LEDGER-010)
   - *INV-008: no row of `backlog/ledger-corrections.toml` already on the trunk changes or disappears —
     class: consistency.* (LEDGER-004) **Both accepted.**
3. **The SessionStart hook activates `core.hooksPath`.** Today the doctor says "a human runs
   `git config core.hooksPath .githooks`". Every cloud session is a fresh clone, so without this the git
   hooks never run there. Alternative: keep it human and rely on the pre-push and the CI. (LEDGER-009)
   **Accepted: the hook turns them on.**
4. **Corrections are accepted only by a person in their terminal** (like `guard-allow.toml` and Harbor's
   `convoy approve`). (LEDGER-004) **Accepted, then widened the same day:** the person may delegate the
   approval to agents with an adversarial review (`delegated` or `mixed`; LEDGER-015). `mixed` is the
   recommended mode for projects with critical areas.
5. **TRACE-1 and INV-1 skip reconstructed stories**, which predate those rules. (LEDGER-006) **Accepted.**

6. **Block from the start where nothing needs getting used to.** Generated projects and Keelokit start in
   `enforce = "block"`; adopted ones in `warn`, moving to `block` after 3 days with zero unattributed
   commits (at least 20). Replaces the earlier 14-day window, which only delayed the guarantee.
7. **Coordination is delegated.** On 2026-11-23 Leo delegated the coordination, the decisions and the
   merges of this plan to a coordinator session (`[run] mode = "auto"` in `.keelokit/state.toml`). It stops
   only for what a person must do: pressing Publish in the plugin directory, GitHub settings, the one-time
   commit that enables delegated approval of corrections (LEDGER-015, protected on purpose), and access to
   repositories outside the session.

## How to launch

Order: phase 0 → gate → phase 1 → gate → release 0.15.0 → phase 2 → gate → release 0.16.0 → phase 3.
Swarm's SWM-1..3 can start any time; Harbor's HRB-1 waits for Keelokit 0.16.0.

**Keelokit (this repo).** One session per story, in order (the decisions above are taken). The prompt,
and nothing more about process:

```
Read .keelokit/harness/agent-brief.md and docs/ledger.md, then /keelokit:build-story LEDGER-001.
```

Title it with `python3 .keelokit/bin/status.py title LEDGER-001`. `/keelokit` and `doctor.py --brief` say
which story is ready next. `[run] mode = "auto"`: the coordinator merges each story once its CI is green
 and starts the next.

**Harbor.** A session in `leosimini/keelokit-harbor`:

```
Read docs/ledger-phase6.md and docs/design.md, then build HRB-1 (and only HRB-1): tests in tests/test_phase6.py first, then the code, then docs and CHANGELOG. Verify with python3 -m unittest discover -s tests and scripts/test-with-keelokit.sh.
```

**Swarm.** The project's own swarm builds it: in `leosimini/enjambre-dev`, a session publishes SWM-1, then
SWM-2 and SWM-3, with the task texts in `docs/ledger-refs.md` of `leosimini/enjambre` (`swarm-ask`), or one
session builds them in order following that file.

**JOUNA, now and independent of Keelokit.** A session in that repo, in Spanish:

```
Lee el documento «Registro de historias y entregas de JOUNA» y hacé solo su fase 0: un hook de inicio que corra git fetch --unshallow antes de leer cualquier estado; que el tablero marque un tren como zarpado por el commit aplastado con la línea «Tren: N» en su mensaje; y cerrar las filas viejas T18, T23, T24, T26, T28 y T29. Medí además cuánto tarda en un clon nuevo `git fetch --filter=blob:none --unshallow origin main` y `git fetch --unshallow origin main`, y anotá los dos tiempos.
```

## Out of scope, on purpose

- GitHub Issues, Projects and the deployments API: nothing the agents need. A mirror can be added later on
  top of `ledger.py --json` without touching any of this.
- Project-level hooks in `.claude/settings.json` or `.codex/hooks.json`: opening a repo would run its code
  unchecked, against what HARN-004 is after. Accounts that work on a Keelokit project install the plugin;
  Swarm asks for it with `requires`.
- Reading the swarm repo from the ledger.
- Rewriting `main`'s history: what is missing is fixed with new rows, never by editing commits.
- Judging the quality of the why: the hooks make sure the body exists; whether it is useful is the
  reviewer's call in `build-story`.
- A lock without Harbor: without it, `in-progress` is a signal, and two sessions can take the same story
  (`check` shows it).
- The ledger in projects without Keelokit: a fleet that uses only Harbor's session layer has no stories.
- Other CI systems: the template ships GitHub Actions; the job and its permissions for another CI are
  written apart.
