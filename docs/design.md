# How Keelokit is built

This describes Keelokit as it is. For how to use it, see the [README](../README.md).

## Three places

| Place | What lives there | How it changes |
|---|---|---|
| **The plugin** (this repo, installed in Claude Code) | skills, agents, workflows, the hooks that call each project's guard | `claude plugin update` |
| **The template** (`copier.yml` + `template/`, same repo, tagged) | the monorepo skeleton and the house harness in `.keelokit/` | a project runs `/keelokit:harness-upgrade` (Copier's 3-way merge) |
| **A project** (generated or adopted) | its code, `docs/context/`, `docs/prd.md`, `backlog/`, `.keelokit/answers.yml`, local rules and exceptions | by the people and agents working on it |

The template owns infrastructure; the product owns its code. `copier.yml` lists which is which
(`_skip_if_exists`), so an upgrade brings new rules and CI without rewriting product files.

## The house harness (`template/.keelokit/`)

- `harness/rules.toml` — every rule with its reason and its enforcers.
- `harness/execution-protocol.md` — how agents work, what "done" means, what waits for the human.
- `harness/stack.md` — the stack and why.
- `bin/doctor.py` — harness health (below).
- `critical.toml` — the project's critical areas and the mutation score they must keep (the
  product owns it; the template ships one example area).
- `bin/ledger.py` — `ledger.py history --ensure` completes the trunk's history: commits only (`--filter=blob:none`),
  a plain `--unshallow` when the server can't filter, capped by `[ledger] history_seconds` (default 20, at most 20
  under the hook's 30 s timeout). The SessionStart hook runs it before `doctor.py --brief`; it never blocks the session.
- `bin/guard.py` — one guard, two callers: Claude Code's PreToolUse hook and git's pre-commit.
  Without python3 every Claude hook turns off and says so, and pre-commit stops the commit
  with the reason (`tests/test_hooks.py` runs each hook without it).
- Which copy the plugin's hooks run (HARN-004): always the plugin's. `hooks/hooks.json` runs `hooks/trusted.py`
  (with `python3 -I`, after a `cd` into the plugin), which runs the plugin's guard, ledger and doctor with
  `--root <project>` against the project's data (rules, `rules.local.toml`, state, backlog); the project's
  `.keelokit/bin` is only read, to say at the session start that it differs. There is no per-project approval: an
  agent with a shell can forge anything a person would do at a terminal (ESC-278). guard, doctor, ledger and
  ux_gate take `--root DIR` first; the doctor runs the ledger and ux_gate next to itself, with the same `--root`;
  the ledger and the guard with `--root` run git with core.hooksPath=/dev/null. The plugin never turns a repo's git
  hooks on (they run `.keelokit/bin` without `-I`, and whatever `.githooks` holds on the branch checked out:
  ESC-277); the session start says when they are off. The guard runs in a child process the hook waits for at most
  45 s, and its patterns run in linear time; it reads its data files without blocking and at most 1 MB and bounds
  its git calls, so it can't outlive the hook's timeout, which Claude Code would read as a pass (ESC-276, ESC-279).
  Every git call the plugin's scripts make with `--root` (and trusted.py's own) runs hardened (ESC-280):
  safe.bareRepository=explicit, protocol.ext.allow=never, core.fsmonitor=false, GIT_NO_LAZY_FETCH=1, no
  GIT_DIR-like variables, and only where the git dir is the project's .git or outside the project. Any failure of
  the guard hook's own path is a block (ESC-281); the guard runs wherever the project has `.keelokit/`, or had it when a hook last looked (a marker in
  `~/.cache/keelokit/projects`; ESC-282, ESC-295); the PreToolUse gate runs no git (ESC-296).
- `bin/run-local.sh` — launches the Expo app and its API on a phone or a simulator (macOS). It
  runs without Claude or the plugin, reads the `[local]` block of `profile.toml` and detects what
  the block leaves out; `/keelokit:run-local` runs it and repairs what fails (RUN-1).
- `bin/ci.py` — the CI from the command line: health of main (a cancelled run is not green), time per
  job against its timeout, which job and step failed, a manual dispatch. The CI's last job runs
  its `summary`. `bin/status.py` — ten lines for whoever coordinates parallel sessions, and `status.py title`, the
  canonical session title (`<project> · wave <n> · <ID>`) that build-story, coordinate and Harbor use.
- `verify-map.toml` — which `pnpm verify` step runs each CI job; the doctor keeps them in step.
  `verify-routing.toml` — which files need which steps; `red-causes.toml` — the project's known causes of a red.
  `bin/verify_tools.py` plans, times and diagnoses; `scripts/verify.sh` keeps the run state, the seal and the history.
  The memory plan (FLEET-001): each step's peak memory goes into the history (`peak_mb`, with its source). The usual
  source is `rss`, the largest resident size of one process of the step, which is one worker's; `cgroup`, the step's
  `memory.peak`, applies only where the own cgroup allows a child with memory accounting (cgroup v2's
  no-internal-processes rule makes that rare), and is divided by the workers the plan passed. Before the first tool
  runs, `verify_tools.py workers` reads the memory available (`MemAvailable`, or the cgroup's `memory.max` minus
  `memory.current` plus its reclaimable `inactive_file` cache, the lower) and plans the worker steps, `unit` and
  `integration` (`integration` only with an API; e2e scripts build in the same command, so their peak is not a
  worker's and nothing is planned or refused for them). The per-worker figure is the largest of the last 10 history
  entries that measured the step, so a small run never erases the real peak; `[verify] memory_per_worker_mb`
  overrides it. Workers are `min(cores, available × 0.8 / peak)`, at least 1, passed through the runner's own flag
  (`--maxWorkers`) only when memory is what limits them; a planned unit step (and the clock rerun) also runs with
  `--workspace-concurrency=1`, so packages go one after another and the workers are the machine's, not each package's.
  The cgroup limits read are cgroup v2 only. A step whose one worker needs more than is available stops
  the run in seconds with exit 3 and no history line, like a busy machine (`VERIFY_FORCE=1` runs it with 1 worker);
  with no measure and no override, or no `/proc` (macOS), nothing changes.
  The estimate (FLEET-002): the history also keeps seconds per step id (`durations`; older lines are read from their
  step titles). After the memory plan, `verify_tools.py estimate` takes the last 20 green, whole runs of the same
  level with the same planned workers for the worker steps in this plan, and prints "about 55–80 min (from 12 runs)":
  the sum of each planned step's median to the sum of its 90th percentile (setup steps `git` and `prisma` included,
  `db` with integration). Fewer than 3 such runs is "no estimate yet", saying how many ran with other workers. The
  state file keeps the figures (`estimate=id:median:p90 ...`, `step_id`, `step_since`), and `status.py` turns them
  into the range left while the run goes. Nothing is estimated for a preflight, or for a machine with no history.
- `harness/agent-brief.md` — the one page every parallel session is told to read.
- `[landing] policy` in `state.toml` — how finished work reaches main. `direct` (the default, and
  what an absent key means): each session rebases, verifies and pushes main itself. `convoy`: each
  session pushes its own branch with a plain `pnpm verify` green (sealed) on that hash and
  stops; Harbor (a companion plugin, `/harbor:*`) merges a batch of delivered branches, from any
  session, account or machine, into `convoy/<n>`, verifies it once and lands it in one push. With
  `convoy` the brief's landing, `coordinate`, `status.py` ("delivered, waiting for a convoy") and
  the doctor (a note when the pre-push hook would also verify each write to Harbor's logbook) follow;
  nothing else changes.
- `ux.toml` + `bin/ux_gate.py` — product quality (UX-2..5, `docs/ux-quality.md`): which paths are interface,
  which surfaces, widths and themes need captures, where they live. The doctor runs the gate against main: an interface
  change without captures and a `CRITIQUE.md` fails, `ux-gate: n/a — <reason>` in a commit passes and is reported.
- `rules.local.toml`, `exceptions.toml` — the project's own rules, and dated deviations.
- `guard-allow.toml` — the few paths the guard lets through: `[[allow]]` entries for SEC-1 (a key in
  the file) or SEC-2 (a `.env` file) with a path or a bounded glob, reason, approver and optional
  expiry. Product-owned like `exceptions.toml`, but not in it: an exception excepts a whole rule from
  the doctor's enforcer check, and an allowed path must not (a registered path is not an exception).
  It is the human's: the Claude hook blocks every write to it (QA-4), a commit that changes it needs
  `keelokit.allowTamper`, the Claude hook reads it as of the last commit and the pre-commit hook as
  staged, so an edit exempts nothing until a human commits it. Globs take only `*` and `?`; the file is
  scanned for secrets like any other. The template's CI gitleaks job is not told about it: a project
  whose CI runs gitleaks needs its own `.gitleaks.toml` allowlist for the files it registers. A secret in a shell command line stays blocked whatever the registry says. The doctor
  validates the bounds and lists every active entry. Separately, the guard reads a variable reference
  (`${VAR}`, `$VAR` in capitals, `${{ secrets.X }}`) where a URL's password goes as no secret; a literal still is.
- `backlog/ledger-corrections.toml` (next to the backlog, but protected like `guard-allow.toml`) — the ledger's
  approved corrections: `[[row]]` story, commit, kind (`backfill`, `late`, `retract`), evidence, approver, date.
  Product-owned (`_skip_if_exists`) and the human's: the Claude hook blocks writing it and running
  `ledger.py backfill --accept`, which also needs a terminal and a confirmation; a commit that changes it needs
  `keelokit.allowTamper` (the template's comments-only file may be added). Append-only (INV-008).

The process rules that came from long parallel use (CI budget, local gate, sessions, migrations,
flaky tests, formatting, debt) are listed with their reason and check in [process-rules.md](process-rules.md).

## The project's profile

`.keelokit/profile.toml` says what the project is: a `kind` and its `traits` (UI, web, mobile, API,
database, hosted, languages, personal data, payments, developer-facing). It is diagnosed — by
`project-new` from the PRD, by `project-adopt` from the code — and kept up by `plan-intake`,
`build-story` and `check-health`, with the doctor warning when the repo shows a trait the profile
lacks. Rules declare the traits they `needs`, so only the ones that fit apply; the bug bash, the
security review, ship-setup, ship-release and the dashboard read it to decide what matters.

## What `doctor` checks — and what it can't

It checks that each MUST rule has an enforcer and that the enforcer looks alive: a test file
that names the rule and has active tests, a lint rule that is on, a CI job with real steps, no
`continue-on-error` and no `if: false` (bare, `${{ false }}` or quoted, at any indent), a git hook that is installed, a config line that is present. It checks
exceptions (complete, not expired), `docs/context` (files present, no vague phrases, every gap
tracked, every invariant with an id and a class), critical areas (their paths exist), the
backlog (well-formed stories, declared dimensions, scenario ids, no two stories of a wave
touching the same paths or the same critical area, a story in a critical area declaring
`integrity` and its invariants, every scenario and invariant of a done story cited by an active
test title) and the escape log (every row names the check it left). A story's state is the
ledger's (`ledger.py --json`, below): done when it is `on-trunk` or later; a story done only by a
correction row is listed apart as reconstructed, and TRACE-1 and INV-1 skip it.

`doctor --scope <ID>` checks one branch before review: files outside `touches`, a critical area
the story didn't declare, and acceptance tests edited outside a `test(<ID>): …` commit.
`doctor --critical [--changed]` lists the critical files that `scripts/mutation.sh` mutates.

It can't tell whether a test really fails when its rule breaks. For critical code, mutation
testing measures exactly that (MUT-1); everywhere else it is the reviewer's and the verifier's
job, and what `/keelokit:check-bugbash` tightens when a bug gets through. The guard is a speed
bump for agents, not a sandbox; the git hooks and CI are the backstop.

## The ledger

`ledger.py` derives every story's state from git and stores nothing written by hand: `defined` (the
file is on the trunk), `ready` (its dependencies are on the trunk), `in-progress` (`Part-of:` commits on
an origin branch not on the trunk), `on-trunk` (a `Story:` commit reachable from the trunk and not
reverted), `in-version` (the first `v*` tag containing it), `in-staging` and `in-production`
(`origin/deploy/*`). `ledger.py` prints a summary of at most ten lines; `ledger.py --json` is the
schema-1 document every other tool reads. With a cut history every state is `unknown` with the reason,
never a lower one, and the git calls are a fixed number however many stories there are. The design,
the contracts and the plan are in [ledger.md](ledger.md); `[ledger]` in `.keelokit/state.toml`
configures it (stories glob, ids from front matter or file names, trunk, `since`). History without trailers
is reconstructed once from `backlog/ledger-corrections.toml`: `ledger.py backfill --propose [--from FILE…]`
writes candidate rows with a confidence and their evidence (commits and merged branches that name the id, train
sheets, a `BOARD.md`, Harbor's imported board) to a git-ignored file, `ledger.py correct` proposes one late
attribution, and a person accepts them with `backfill --accept`; an accepted row makes its story `on-trunk`,
marked reconstructed. `ledger.py check [--ci] [--json]` lists every difference with its level (the corrections'
`CORRECTION_*`, which the doctor reports too; `UNKNOWN_STORY` (every trunk commit, or from `[ledger] since` on
when it is set) and, from `since` on, `UNATTRIBUTED`, `BAD_CATEGORY`, `STORY_NO_BODY`, `SQUASH_LOST_TRAILERS`,
errors under `enforce = "block"`; and the warnings
`STALE_BRANCH`, `DONE_TWICE`, `SNAPSHOT_BEHIND`, `PENDING_REVIEW`) and exits 1 only on an error. `ledger.py show
<ID> [--full]` gathers a story's why where it already lives, in at most 60 lines: its state and date, its commits
with their subjects, bodies and `Claude-Session:`, the story file's *Addendum* headings, the rows of
`docs/escapes.md` and the bug-bash findings that name it or arrive through a `Finding:` trailer, its abandoned
attempts (`Dropped:` commits on any origin branch, also in `--json` as `attempts`) and its corrections. `ledger.py
next` lists the ready stories nobody works on, by wave and id; `ledger.py --release vX.Y.Z` the stories whose
commit is in that tag and not in the previous version tag.

Harbor (LEDGER-013, [ledger.md](ledger.md) "Harbor and Swarm"). The ledger reads Harbor's logbook,
`origin/harbor/log`, with the same hardened git calls as everything else (`ls-tree` and one `cat-file` per kind of
file), as data: an active worker holding a story makes it `in-progress`, a vessel sealed on its exact head in an open
convoy makes it `delivered`, and a sailed convoy (or the `Convoy: <n>` trailer of the merge that brought it) names an
on-trunk story's convoy, with the exact time from `main.toml`'s convoy move. The logbook never adds a difference, so
no content anyone pushes to it changes what `check` says or an exit code; a malformed file is left out, an unreadable
logbook is none. Three contracts are Harbor's to read: `ledger.py attribution <a>..<b> --json` (`convoy add`'s
`NO_STORY`; the same attribution function `check` uses), `ledger.py show <ID> --json` (`STORY_ON_TRUNK`) and
`ledger.py check [--ci] --json` (the harbormaster's round and the ok, HRB-3): `{"schema": 1, "diffs": [{"level":
"error"|"warning", "code", "detail"}]}`, exit 1 iff a diff is an error; keys may be added, none changes meaning
within schema 1. `check --rules-ref <rev>` reads every rule file the ledger takes from the trunk's committed tree
(`[ledger.approval]` in `.keelokit/state.toml`, `.keelokit/critical.toml`, the review files in
`.keelokit/ledger-reviews/`, and `critical.toml` as of a delegated row's arrival) from `<rev>` instead, with the same
parsing and the same hardened git calls; a correction row that arrived in commits `<rev>` does not reach is judged by
`<rev>`'s critical areas. Harbor's ok runs main's ledger in a clone whose trunk is the convoy as landed: without it
the convoy's own tree would hold the rules it is judged by, so a convoy could relax them. A `<rev>` that is no commit
here is exit 2. The data (stories, corrections, commits) is still the trunk's.

harbor.py is code the ledger runs, so only one explicit command runs it: `ledger.py take` (and `take --clear`), when
`git config --local harbor.py` names an absolute path to a `harbor.py` and `harbor.py story take --help` exits 0
(feature detection, never a version string). Never `show`, `check`, `attribution`, the summary, the doctor, or any
hook's path (the session start, the guard, the git hooks), so opening a repo or committing never runs Harbor; a
Harbor that calls the ledger back (its `story take` asks `ledger.py --json` and `show --json`) cannot loop. It runs
with the interpreter running the ledger (`-E -s`), the hardened git environment, `CLAUDE_PROJECT_DIR` set to the
checkout, no stdin, in its own session killed whole at the timeout (`KEELOKIT_HARBOR_SECONDS`, default 180), its
output read from files and at most 64 KiB of it. Only its exit decides: 0 takes, 1 is Harbor's refusal (one line,
nothing set), anything else or no answer is exit 2, nothing set; what it prints is relayed as one terminal-safe line
and never read as a verdict.

The CI keeps two facts git does not (LEDGER-011). The orphan branch `keelokit/ledger` (`[ledger] snapshot`; `""`
turns it off) holds `LEDGER.md` and `ledger.json` of the trunk's latest commit and `moves.toml`, the time the CI saw
each push reach the trunk: the template's `ledger-snapshot` job runs `ledger.py snapshot` on every push to main and
every tag, alone with `contents: write`, one run at a time. It commits with plumbing in a temporary index (no
checkout is touched), starts again from the new tip when its push is rejected (5 tries), never puts an older
trunk's reading over a newer one, and fills in a push whose own run never recorded it, marked not exact. A story
then has `since_exact = true` from `moves.toml`; a shallow session whose history fetch is cut reads the snapshot
(`history = "snapshot:<sha>"`, each record `as_of` that commit) and proves what it can since (a later `Story:` or
revert, a moved deploy branch or a new tag; unknown otherwise); `history --ensure` fetches it in the last quarter of
its cap. The snapshot branch is never read as a branch of the project. The deploy jobs run `ledger.py deploy
<staging|production> <commit>` once a deploy succeeded: `deploy/staging` and `deploy/production` point at what each
environment runs, backwards too on a rollback (the release workflow run again from an older tag).

House rule LEDGER-1 (LEDGER-012) ties these pieces to the doctor: each run checks that `.githooks/` ships
`commit-msg`, `prepare-commit-msg` and `pre-push`, executable and calling their `ledger.py` command, that git runs
them (the same "not installed" check, and the same single line, as every `git-hook:` enforcer), that a workflow for
pushes or pull requests runs `ledger.py check --ci` in a step and a job that can fail it, that `ledger-config` and
`ledger-snapshot` are in that workflow unless `[ledger] snapshot = ""`, and that `[ledger] since` is on the trunk;
the corrections are checked as before. Its `Ledger:` line gives the share of unattributed
commits since `[ledger] since` and, under `enforce = "warn"`, recommends `block` once the last 3 days of the trunk
(ending at its newest commit's arrival: `moves.toml`'s exact time, else the committer date; never the clock) hold at
least 20 commits, all attributed, with no difference `block` would refuse. The doctor never writes `enforce`; a
dated LEDGER-1 exception in `exceptions.toml` turns the enforcer errors into warnings, as for any rule.

One reader: the doctor, the dashboard and `status.py` take story states from `ledger.py --json` and compute
none of their own, so they never disagree (LEDGER-006). The doctor's done count is the ledger's `on-trunk` or
later; the dashboard shows a story's version and work in progress on another machine (`Part-of:` commits on an
origin branch); `status.py` lists the stories in progress on branches not checked out here. When the ledger
can't answer (a cut history, a story it reads as unknown, no `ledger.py`) all three say unknown, never a lower
state. A story file not on the trunk yet (a plan on a branch) has no ledger record: not done, and ready once its
dependencies are. The skills ask the same commands: `build-story` reads `ledger.py show <ID>` before its
contract and writes the why in its `Story:` commit's body, `coordinate` checks a landing with `show`,
`ship-release` lists a version's stories with `--release`.

## Lifecycle

| Stage | Skill | Human decides |
|---|---|---|
| New product | `project-new`: intake → PRD → stack → skeleton → backlog | context, scope, stack deviations, story order |
| Existing repo | `project-adopt`: intake → `.keelokit/` + rule mapping → diagnosis → backlog | each exception |
| Build | `build-story`: contract → verifier's tests → builder → reviewer + breaker → verifier walks the app → rebase, breaker again if main moved → land | product rules the story doesn't define, new invariants |
| Quality | `check-bugbash`: lenses per dimension → validation → root-cause fixes → a new check per escape | pending product decisions |
| Security | `check-security`: data map → privacy law per market → threat model → scans → root-cause fixes → a check per class | privacy choices, legal questions |
| Ship | `ship-setup`: a verified checklist per environment · `ship-release`: notes → tag → production after approval (REL-1) | accounts, money, every production release |
| Keep up | `harness-upgrade`, `check-health` | rule changes, exceptions |

Reserved for the human always: production deploys, money, legal, deleting data.

## Workflows: where the shape of the work is code

A skill says what to do in prose, and the session follows it. Where a skill already runs many
agents on its own for a long stretch, the prose leaves the shape to the model: how many at once,
how many rounds, whether every finding really got an independent check. Those parts are
Claude Code workflows (`workflows/*.js`, run as `/keelokit:<name>`): a script decides who runs, in
what order and with what limits; agents do the work; the conversation gets only the result, and a
run cut short resumes where it stopped.

| Workflow | Started by | Shape |
|---|---|---|
| `check-bugbash-flow` | `check-bugbash` | plan → lenses (≤ N at once) → a skeptic reproduces each finding (two for P0/P1) → completeness critic, more rounds while it finds gaps → merge by root cause → fixes one at a time, each checked by another agent, undone if rejected → report |
| `ledger-review-flow` | `check-health` (the person delegated the approval of ledger corrections in `[ledger.approval]`) | `ledger.py review --filter` (no model) → judge A and judge B per row, independently (≤ N at once; Opus for a critical story in `delegated`) → a skeptic tries to refute each row both approved → the verdicts go to `.keelokit/ledger-reviews/<run>.json`, `ledger.py backfill --accept --delegated <run>` decides and writes the approved rows as `delegated:<run>`, one commit → report with the person's queue and a sample |

The skill stays the way in, and the fallback: it prepares what needs the person (scope, what to
say), starts the workflow when the session can run one, and afterwards asks the pending
decisions. Nothing a person must decide happens inside a workflow — it has no way to ask — so
decisions come back as results. Conversations (intake, PRD, stack, setup, releases) stay skills.
`tests/test_workflows.py` keeps every script loadable: a pure-literal `meta` whose name is the file
name, phases that match, no clock or randomness, a body that parses.

The dashboard (`skills/project-dashboard/`) is how the human follows all of this: a script reads
`.keelokit/state.toml`, `docs/`, `backlog/` and the ledger's story states (`ledger.py --json`) and renders two pages from
the same state. The **dashboard** is short and operational (next step, what waits, waves, health)
and live: its shell — design and code, no project data — is published once as an Artifact with a
database, and every refresh writes one data document (`dash/ops`) from a file with ArtifactData,
so the page's content never passes through the conversation and an open page updates itself.
The shell's id is a hash of its HTML, recorded as `[dashboard] shell`; it's republished only when
that changes (a new design, another language). The **report** (`--report`, `project-report`) is
the complete page — every stage with its documents, findings, history — read-only, to share as
its own Artifact or export as a standalone file. Neither stores anything; both are rebuilt from the
repo. Every Keelokit page shares its look (`skills/project-dashboard/references/design.md`).

## Bugs come in classes

A bug bash that keeps finding bugs means the build loop lets whole kinds of bug through. Each
kind has a mechanism aimed at it. Everything here works for any product: the product says what
is critical (its invariants and areas), and the harness decides how that gets proven.

| Why bugs escaped | Mechanism | Checked by |
|---|---|---|
| The builder read the spec the same way it wrote the code | The verifier writes the acceptance tests from the story before any code; the builder can't edit them (VERIFY-2) | `doctor --scope`: acceptance tests changed only in `test(<ID>): …` commits |
| One review at the end, for everything | A cold reviewer per story (light mode too) and a breaker that runs attacks (full mode), before landing, and again on the combination when main moved (REVIEW-1) | Review: inferential, and doctor says so |
| Money, limits and notices tested with one happy case | Invariants with ids and classes in `domain.md`; each class calls for one kind of test: property, concurrency with `race()` on the real DB, replay, transition table, fixed clock (INV-1) | Doctor: every invariant of a done story cited by an active test; the verifier and reviewer check it's the right kind |
| Hermetic E2E green while the real API disagreed | The critical journeys again in `e2e/stack/`, against the real API and PostgreSQL, in `pnpm verify` and CI (E2E-2) | CI job `e2e-stack`; lint forbids `page.route` there |
| Screens only looked at when the wave ended | The verifier saves screenshots per scenario and state for every story that touches a screen | Review |
| Parallel stories collided in shared code | Critical areas (`critical.toml`): stories touching one go one at a time, in full mode (CRIT-1) | Doctor: area overlap in a wave, `integrity` required |
| A fix repaired one case and the class came back | Every escape gets a failing test first (by the verifier), a fix, and a check for its class, logged in `docs/escapes.md` (ESC-1); bug bashes compare against it | Doctor: every escape row names its check |
| Text promised what the code didn't do | Every promise in copy points to a test of that behaviour (COPY-1) | Review |
| Green tests that couldn't fail | Mutation testing on critical code, with a score that fails CI (MUT-1) | CI job `mutation`; `scripts/test-template.sh` proves a suite that can't fail is rejected |

Mutation testing uses Stryker's command runner (each mutant reruns the package's `test` script).
It is slower than a per-test runner, but it works with Vitest and Jest of any version: Stryker's
Vitest plugin (10.0) runs no tests per mutant under Vitest 5 and reports every mutant as
survived. So critical areas are kept small and their rules pure.

Not done yet, on purpose: native E2E on a device or emulator (Maestro). The mobile journeys run
on Expo web, which covers the app's logic and screens but not native modules, permissions or
the OS lifecycle. A Maestro job needs a native build and an emulator in CI (about 20–40 minutes
per run) and only earns that once a product depends on native behaviour. Until then that part
is the `mobile` lens of the bug bash, on a real device.

## Testing Keelokit itself

- `tests/` — unit tests for the guard, doctor, dashboard and the template's `verify.sh` scope (`python3 -m unittest discover -s tests`; `test_verify.py` needs pnpm, and the dashboard's layout test playwright's Chromium).
- `scripts/test-template.sh` — generates projects (several app combinations, adopt mode, an
  upgrade from the previous tag), runs `pnpm verify --all` on each (integration tests and the
  real-stack E2E included), then `pnpm mutation --all`, and checks that a suite that can't fail
  is rejected. CI runs both.

## Ideas, not promises

Things that might come if they prove useful in real projects: measuring whether agents follow
the skills (evals), deploying web and sites from CI, per-package caching, a Maestro job for
native mobile journeys, and Stryker's per-test runner once it supports Vitest 5.

Designed and planned, first piece built (`ledger.py history`): the ledger, one derived record of what is being done and what was
done, for every session ([ledger.md](ledger.md), epic `LEDGER`). What the JOUNA fleet learned in November 2026, and where it
lands: [fleet-lessons.md](fleet-lessons.md), epic `FLEET`.
