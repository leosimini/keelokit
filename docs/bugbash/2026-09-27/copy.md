# copy

### CPY-1 · Doctor's fix-it text says "run `pnpm doctor`" / "run pnpm install" in repos that have neither (P2)
- **Persona / context:** Daily agent session in Keelokit's own repo (kind=`plugin`, no root `package.json`) at sha 19b332e — the SessionStart hook runs exactly this command on every session in this repo. The same text ships to any `project-adopt`ed repo that isn't a pnpm/Node project (INV-004 guarantees `project-adopt` never adds a `package.json`, so a Python/Rust/Go/CLI adoption hits this permanently, not just once).
- **Steps:**
  1. `cd /home/user/keelokit && python3 .keelokit/bin/doctor.py --brief`
  2. `python3 .keelokit/bin/doctor.py` (full mode)
  3. Follow the remedy each line prints: `pnpm doctor`, then `pnpm install`.
- **Expected:** The remedy a fix-it message prints should be something the reader can actually run to see/fix the problem — that is the entire point of "a small script (`doctor`) tells you when a rule has lost its check" (README.md "The idea"). Source of the string: `.keelokit/bin/doctor.py:154,582`.
- **Observed:** `doctor --brief` ends with `Harness errors: 16 — run \`pnpm doctor\``, and each of the four "git hook … is not installed" ERRORs says "run pnpm install". This repo has no `package.json` anywhere at its root, so neither command does what it says: `pnpm doctor` silently exits **0 with no output at all** (looks like success, not "command not found"), and `pnpm install` prints an error but *also* exits 0, so a script or an inattentive reader sees no failure either way.
- **Evidence:**
  ```
  $ cd /home/user/keelokit && python3 .keelokit/bin/doctor.py --brief
  Keelokit: gate pending → intake
  Context gaps: 3 (0 blocking) · Backlog: 0/0 done
  Profile: plugin · 6 rules don't apply
  Harness errors: 16 — run `pnpm doctor`

  $ pnpm doctor; echo "EXIT:$?"
  EXIT:0

  $ pnpm install; echo "EXIT:$?"
   ERR_PNPM_NO_PKG_MANIFEST  No package.json found in /home/user/keelokit
  EXIT:0

  $ python3 .keelokit/bin/doctor.py | grep 'run pnpm install'
    ERROR rule SEC-1: git hook 'pre-commit' is not installed (hooksPath: .git/hooks; run pnpm install)
    ERROR rule SEC-2: git hook 'pre-commit' is not installed (hooksPath: .git/hooks; run pnpm install)
    ERROR rule QA-1: git hook 'pre-push' is not installed (hooksPath: .git/hooks; run pnpm install)
    ERROR rule QA-4: git hook 'pre-commit' is not installed (hooksPath: .git/hooks; run pnpm install)
  ```
- **Where:** `.keelokit/bin/doctor.py:154` ("run pnpm install", ×4 in this run), `.keelokit/bin/doctor.py:582` ("run \`pnpm doctor\`" in `--brief`); byte-identical text in `template/.keelokit/bin/doctor.py:154,582`.
- **Root cause (probable):** The hint strings are hardcoded for the generated-project profile, where `template/package.json.jinja` does define a `"doctor"` script and `pnpm install` does set `core.hooksPath`. Nothing branches on whether a root `package.json` (or that script) actually exists before printing the pnpm-specific remedy.
- **Class:** consistency
- **Should have been caught by:** COPY-1 ("every promise … has a test of that behaviour") — `tests/test_doctor.py` apparently never runs doctor against a fixture without a `package.json` and asserts the printed remedy text; the harness's own dogfooding (this repo) is exactly that fixture and still shows the bug.
- **Proposed fix:** Before choosing the hint, check for a root `package.json` (and that it defines the relevant script); when absent, print a command that actually works here, e.g. `python3 .keelokit/bin/doctor.py` and a plain `git config core.hooksPath …` line, instead of `pnpm doctor` / `pnpm install`.

### CPY-2 · `check-bugbash`'s own description undercounts "every dimension" by three (P3)
- **Persona / context:** Any user reading the skill list (e.g. in the Claude plugin picker, or `claude plugin validate` output) for a developer-facing project such as this one (`.keelokit/profile.toml`: `kind = "plugin"`, `traits = ["developer-facing"]`).
- **Steps:** 1. Read `skills/check-bugbash/SKILL.md`'s frontmatter `description`. 2. Compare it against `references/dimensions.md`'s dimension table and the lens-selection rule ("`dx`, `docs`, `packaging` | `developer-facing`"). 3. Compare against `CHANGELOG.md`'s own 0.7.0 entry.
- **Expected:** The description says "Full bug bash … **across every dimension**" and then parenthesizes the list — for a plugin/library/CLI project the list should include the three dimensions the harness itself added for exactly this case. `CHANGELOG.md` under `## 0.7.0` says in its own words: "developer experience, docs and packaging (three new dimensions: `dx`, `docs`, `packaging`) for something developers use".
- **Observed:** The parenthetical list in the skill's user-facing description names only 17 dimensions — `data, API, contracts, logic, integrity, auth, UX, UI, web, mobile, i18n, copy, a11y, security, NFRs, config, ops` — and omits `dx`, `docs` and `packaging` entirely, even though this very repo's profile (`developer-facing`, no `ui`/`api`/`web`) is the case those three dimensions exist for and most of the listed 17 don't even apply to it.
- **Evidence:**
  ```
  $ grep -n '"description"\|^description:' skills/check-bugbash/SKILL.md
  description: Full bug bash of a Keelokit project across every dimension (data, API, contracts,
  logic, integrity, auth, UX, UI, web, mobile, i18n, copy, a11y, security, NFRs, config, ops) — …

  $ grep -n 'dx.*docs.*packaging\|developer-facing' references/dimensions.md
  | `dx` | For people who use it as developers … |
  | `docs` | Every command, option and file the docs mention exists … |
  | `packaging` | Install, upgrade and uninstall work from a clean machine … |
  | `dx`, `docs`, `packaging` | `developer-facing` |
  ```
- **Where:** `skills/check-bugbash/SKILL.md:3`.
- **Root cause (probable):** The description's dimension list was written before `dx`/`docs`/`packaging` existed (0.7.0's CHANGELOG entry adds them) and wasn't updated when the developer-facing lenses were introduced.
- **Class:** consistency
- **Should have been caught by:** COPY-1 — no test diffs the skill description's dimension list against `references/dimensions.md`'s table.
- **Proposed fix:** Append `dx, docs, packaging` to the parenthetical list in the description (or say "and, for a library/CLI/plugin, dx, docs and packaging" the way the body text on line 19 already correctly does).

### CPY-3 · "A run cut short resumes where it stopped" has no code path that captures or replays the `runId` (P2)
- **Persona / context:** Anyone running `/keelokit:check-bugbash` (or `/keelokit:check-security`, same shape) on a long job that gets interrupted — a killed session, a crashed container, a context-window cutoff. This exact bug-bash run is an instance of the promise.
- **Steps:** 1. Read `skills/check-bugbash/SKILL.md`'s "How it runs" section and its literal invocation instructions. 2. Look for where the Workflow tool's returned `runId` is captured or where a later resume passes `resumeFromRunId`. 3. Compare against the Workflow tool's own resume contract (`workflow-authoring` skill: "relaunch with `Workflow({scriptPath, resumeFromRunId})`" — it needs `scriptPath`, not a saved-workflow `name`).
- **Expected:** README.md: "*a run cut short resumes*" (table row for `/keelokit:check-bugbash`); `skills/check-bugbash/SKILL.md:33`: "a run cut short resumes where it stopped"; `CHANGELOG.md` Unreleased repeats it verbatim. This implies re-invoking after a cut-short run picks up cached progress instead of re-running everything.
- **Observed:** Nothing in `SKILL.md`'s instructions tells the invoking agent to note the `runId` the Workflow tool call returns, and the start instructions on line 35-36 say to start it "with the Workflow tool, name `keelokit:check-bugbash-flow` (or `scriptPath` …)" — with no `resumeFromRunId` anywhere. Per the Workflow tool's own resume mechanism, resuming requires passing back that `runId` together with `scriptPath`; a plain re-invocation by `name` (as instructed) starts a fresh run with a fresh `runId`, re-running every `agent()` call — including the expensive Survey/Validate/Fix phases — from scratch. The "Without workflows, follow the steps below in this conversation" fallback path (used whenever the Workflow tool isn't available) has no resume mechanism of any kind, yet the promise on the README's line is not qualified to only the workflow path.
- **Evidence:**
  ```
  $ grep -n "runId\|resume\|scriptPath\|name \`keelokit" skills/check-bugbash/SKILL.md
  35:Start it with the Workflow tool, name `keelokit:check-bugbash-flow` (or `scriptPath`
  36:`${CLAUDE_PLUGIN_ROOT}/workflows/check-bugbash-flow.js`), and `args`: …
  (no other matches — "runId" and "resumeFromRunId" do not appear in the file)

  $ grep -n "resume\|checkpoint\|runId" workflows/check-bugbash-flow.js
  (no matches — the script itself has no resume-related code, which is expected since the
   host's Workflow tool provides resume transparently — but only when the caller re-supplies
   the prior runId, which nothing here does)
  ```
- **Where:** `skills/check-bugbash/SKILL.md:27-36`; `README.md` check-bugbash row; `CHANGELOG.md` Unreleased entry.
- **Root cause (probable):** The resume capability is a real feature of the host Workflow tool, but the skill's own instructions for starting/restarting the flow never plumb the `runId` through, so in practice a cut-short run cannot be resumed by anyone following the documented procedure.
- **Class:** consistency
- **Should have been caught by:** COPY-1 — no test/dry-run exercises "kill the workflow, re-run the skill, verify it resumed instead of restarting".
- **Proposed fix:** Have the skill capture the Workflow tool result's `runId` (e.g. write it to `docs/bugbash/<date>/.run` or print it to the user), and instruct: "cut short → relaunch with `scriptPath` + that `resumeFromRunId`", not a bare `name` restart.

### CPY-4 · The plugin's own description text disagrees with itself between `plugin.json` and `marketplace.json` (P3)
- **Persona / context:** A newcomer or claude.ai user deciding whether to install, comparing what they see in the Claude plugin directory/marketplace listing against what `plugin.json` (and the README) says the same plugin does.
- **Steps:** `grep -rn "harness for" .claude-plugin/*.json README.md`
- **Expected:** A single product should describe itself the same way in the places a user compares before installing (marketplace listing vs. plugin manifest vs. README's own lede).
- **Observed:** Three different lengths of the same sentence exist side by side:
  - `marketplace.json` (top-level, the marketplace's own blurb): *"Keelokit — a Claude Code harness for TypeScript monorepos."* — drops "building apps".
  - `marketplace.json`'s `plugins[0].description` (what the directory shows for the plugin entry itself): *"A harness for building apps in TypeScript monorepos with Claude Code: rules backed by checks."*
  - `plugin.json`: *"A Claude Code harness for building apps in TypeScript monorepos: intake, PRD, a generated skeleton with CI, backlog, independent verification and rules backed by checks."*
  A reader who sees the marketplace's owner-level tagline first ("harness for TypeScript monorepos") and then the plugin's manifest ("harness for **building apps** in TypeScript monorepos: intake, PRD, …") gets two different scopes for the same one-line pitch.
- **Evidence:**
  ```
  $ grep -n "harness for" .claude-plugin/marketplace.json .claude-plugin/plugin.json README.md
  .claude-plugin/marketplace.json:3:  "description": "Keelokit — a Claude Code harness for TypeScript monorepos.",
  .claude-plugin/marketplace.json:12:      "description": "A harness for building apps in TypeScript monorepos with Claude Code: rules backed by checks."
  .claude-plugin/plugin.json:4:  "description": "A Claude Code harness for building apps in TypeScript monorepos: intake, PRD, a generated skeleton with CI, backlog, independent verification and rules backed by checks.",
  README.md:7:**A Claude Code harness for building apps in TypeScript monorepos.**
  ```
- **Where:** `.claude-plugin/marketplace.json:3`.
- **Root cause (probable):** The three descriptions were each edited independently over time (marketplace top-level blurb, marketplace plugin-entry blurb, plugin.json) and never kept as one source of truth.
- **Class:** consistency
- **Should have been caught by:** COPY-1 — no test asserts the marketplace's owner-level description and the plugin's own description agree.
- **Proposed fix:** Make `marketplace.json`'s top-level `description` match `plugins[0].description` (or vice versa) — pick one sentence and use it in both places, or shorten intentionally and note that's a summary.

### CPY-5 · "Every bug that got through adds a check" isn't true of confirmed bugs sized `story` or whose fix is rejected twice (P2)
- **Persona / context:** Anyone reading the check-bugbash promise before running it, then reading its report afterward and expecting every listed bug to have left a check behind.
- **Steps:** 1. Read the promise in README.md and docs/design.md. 2. Trace `workflows/check-bugbash-flow.js`'s Fix phase for what happens to a confirmed bug that is (a) sized `"story"`, or (b) sized `"fix"` but whose independent checker rejects two attempts.
- **Expected:** README.md (check-bugbash row): "*every bug that got through adds a check for its whole class so it doesn't come back*." `docs/design.md:111`: "Every escape gets a failing test first (by the verifier), a fix, and a check for its class". Both are unconditional — "every".
- **Observed:** In the Fix phase, a confirmed root cause only gets a test+fix+check when `g.size === 'fix'` **and** the independent check (`agent(...CHECKED...)`) approves within 2 attempts. Two other paths leave it with **no check at all**:
  - `g.size === 'story'` (or `FIX` off): pushed straight to `results` with `status: 'story'`/`'open'`, `check: ''`, `notes: g.why` — no test, no fix, no check, ever, in this run.
  - A `'fix'`-sized bug whose fix is rejected by the independent checker twice: the code runs `git reset --hard`/`git revert` to undo it and sets `status: 'open'`, `check: ''` — the bug is confirmed and reported, but it does **not** come away with a check for its class, contradicting "every bug … adds a check".
- **Evidence:**
  ```
  $ grep -n "status: g.size === 'story' ? 'story' : 'open'\|status: 'open', commit: '', notes:" workflows/check-bugbash-flow.js
  266:    results.push({ ...g, status: g.size === 'story' ? 'story' : 'open', commit: '', check: '', notes: FIX ? g.why : 'fixes off' })
  ...
  347:      fixed = { ...fixed, status: 'open', commit: '', notes: `${fixed.notes} — rejected and undone: ${problems.join('; ')}` }

  $ grep -n "every bug that got through adds a check\|Every escape gets a failing test" README.md docs/design.md
  README.md:43:… every bug that got through adds a check for its whole class so it doesn't come back. …
  docs/design.md:111:| A fix repaired one case and the class came back | Every escape gets a failing test first …
  ```
- **Where:** `workflows/check-bugbash-flow.js:262-267` (`story`/fixes-off path), `:340-348` (rejected-fix path).
- **Root cause (probable):** The report/JS code correctly models "story" and "rejected fix" as legitimate outcomes (they're surfaced honestly as `open`/`story` in the report), but the marketing-level promise in README/design.md was written for the common case and never qualified for these two outcomes.
- **Class:** consistency
- **Should have been caught by:** COPY-1 — no test checks that the promise's wording matches the code's actual guarantee (it should say "every *fixed* bug" or similar, or the two escape hatches should be called out).
- **Proposed fix:** Soften the promise to match what the code guarantees, e.g. "every bug we fix adds a check for its whole class; ones too big for a same-session fix become a story with the escape still logged" — or, alternatively, make the `story`/rejected-fix paths still add a *skeleton* check (e.g. a `.skip`ped or `xfail` test naming the bug) so the literal promise holds.

### CPY-6 · Dashboard has no plural handling — renders "1 exceptions recorded" / "1 dated exceptions" (and the same for stories, documents, gaps, errors) (P2)
- **Persona / context:** Any user of `/keelokit:project-dashboard` on a project where a count happens to be exactly 1 — e.g. right after registering the first exception, or with exactly one ready story, one open gap, or one harness error.
- **Steps:**
  1. Built a minimal fixture project with `.keelokit/exceptions.toml` holding exactly **one** `[[exception]]`.
  2. `python3 skills/project-dashboard/scripts/dashboard.py --root <fixture> --out fix1-en.html --lang en --standalone`
  3. Read the rendered "Harness" stage text.
- **Expected:** English (and Spanish) copy should read grammatically for `n = 1` — "1 exception recorded", not "1 exceptions recorded" — the same way the finding-format/dimensions docs call out "zero/one/many" as an edge every screen must handle.
- **Observed:** The page literally reads **"1 exceptions recorded"** and, in the same section, **"Of 1 rules: 0 covered by what the repo already had · 1 dated exceptions · the rest, by Keelokit's own checks"**. `dashboard.py`'s translation dict has zero pluralization logic anywhere (`grep` for `plural`/`ngettext`/`== 1` returns nothing), so every `{n}`-templated string is affected at `n = 1`: `wait_errors` ("{n} harness errors to review"), `next_gaps_d` ("{n} open questions block progress."), `next_doctor_d` ("The doctor found {n} errors."), `stories_n` ("{n} stories"), `sum_intake` ("{docs} documents · {gaps} open questions …"), and their Spanish equivalents (`"{n} historias"`, `"{n} errores del harness para revisar"`, etc.) all produce the same "1 X" mis-agreement.
- **Evidence:**
  ```
  $ grep -o "1 exceptions recorded\|[0-9]* dated exceptions" fix1-en.html
  1 exceptions recorded
  1 dated exceptions

  $ grep -n "def plural\|ngettext\|== 1 else\|if n == 1" skills/project-dashboard/scripts/dashboard.py
  (no matches)

  $ grep -n '"sum_adopt":\|"rules_counts":\|"wait_errors":\|"stories_n":' skills/project-dashboard/scripts/dashboard.py
  124:        "wait_errors": "{n} errores del harness para revisar",
  256:        "stories_n": "{n} historias",
  335:        "wait_errors": "{n} harness errors to review",
  378:        "rules_counts": "Of {house} rules: {mapped} covered by what the repo already had · {exc} dated exceptions · the rest, by Keelokit's own checks",
  463:        "sum_adopt": "{exc} exceptions recorded",
  467:        "stories_n": "{n} stories",
  ```
- **Where:** `skills/project-dashboard/scripts/dashboard.py:378` (`rules_counts`), `:463` (`sum_adopt`), and every other `{n}`/`{docs}`/`{exc}`/`{gaps}` templated string in the `T` dict (lines 47-470).
- **Root cause (probable):** All count-driven strings are flat `str.format()` templates; none of the ~10 places that interpolate a count branch on `n == 1`.
- **Class:** consistency
- **Should have been caught by:** COPY-1 — no test renders the dashboard with count = 1 for any of these fields and asserts the singular form.
- **Proposed fix:** Add a small `plural(n, singular, plural)` helper (English and Spanish forms) and route every count-templated string through it; the existing key-parity test (`es`/`en` key sets match, verified in this bash) is a good place to also assert `n=1` renders vs. `n=2`.

---

## Status re-check against the actual current HEAD

The bug-bash brief for this run says HEAD is `19b332e`, 2 commits ahead of `origin/main` (v0.7.1).
That is **not what the working tree holds**: `git rev-parse HEAD` on the real
`/home/user/keelokit` (not a fresh clone) returns `fcbbee799d476a41ed254521037c969f02d44372` on
branch `claude/vigilant-hamilton-u202mw`, **25 commits ahead of `origin/main`** (`git rev-list
--count origin/main..HEAD`), not 2. `git log --oneline` on this branch shows a full prior
bug-bash-and-fix cycle already landed, with commits explicitly citing `CPY-1` and `CPY-6`:

```
$ git rev-parse HEAD && git rev-list --count origin/main..HEAD
fcbbee799d476a41ed254521037c969f02d44372
25

$ git log --oneline | grep -i CPY-
7ed835a fix(dashboard): render every count with its singular (CPY-6)
e391054 fix(doctor): name only commands the repo has in fix-it lines (CPY-1)
```

Re-running this lens's own steps against the real, current HEAD (not the SHA the brief names)
shows two of the six findings above are **already fixed and should not be re-opened**:

- **CPY-1 is fixed.** `python3 .keelokit/bin/doctor.py --brief` in this repo right now prints
  `Harness errors: 16 — run \`python3 .keelokit/bin/doctor.py\`` (not `pnpm doctor`), and
  `.keelokit/bin/doctor.py` names the repo's actual install step per commit `e391054`. Confirmed
  by direct run, not by reading the diff.
- **CPY-6 is fixed.** `skills/project-dashboard/scripts/dashboard.py` now defines `plural(t, key,
  n, **kw)` (docstring: "Every number that sits before a word goes through here") and every
  `{n}`-templated string (`sum_adopt`, `wait_errors`, `stories_n`, `n_rules`, `n_mapped`,
  `n_dated_exc`, …) is a `(one, other)` tuple routed through it, per commit `7ed835a`.

CPY-2 (dimension list omits `dx`/`docs`/`packaging`), CPY-3 (no `runId`/`resumeFromRunId` plumbed
for resume), CPY-4 (three disagreeing plugin/marketplace descriptions) and CPY-5 (the
`story`-sized / twice-rejected fix paths still leave `check: ''`) were all re-verified against
this same live HEAD (`grep` shown below) and are **still open, unchanged**:

```
$ grep -n '^description:' skills/check-bugbash/SKILL.md
description: Full bug bash of a Keelokit project across every dimension (data, API, contracts,
logic, integrity, auth, UX, UI, web, mobile, i18n, copy, a11y, security, NFRs, config, ops) — …
  # dx, docs, packaging still absent

$ grep -n "runId\|resumeFromRunId" workflows/check-bugbash-flow.js skills/check-bugbash/SKILL.md
skills/check-bugbash/SKILL.md:33:conversation, and a run cut short resumes where it stopped.
  # still the only mention; no runId is captured or replayed anywhere

$ grep -n '"description"\|harness for' .claude-plugin/marketplace.json .claude-plugin/plugin.json README.md
.claude-plugin/marketplace.json:3:  "description": "Keelokit — a Claude Code harness for TypeScript monorepos.",
.claude-plugin/marketplace.json:12:      "description": "A harness for building apps in TypeScript monorepos with Claude Code: rules backed by checks."
.claude-plugin/plugin.json:4:  "description": "A Claude Code harness for building apps in TypeScript monorepos: intake, PRD, a generated skeleton with CI, backlog, independent verification and rules backed by checks.",
README.md:7:**A Claude Code harness for building apps in TypeScript monorepos.**

$ grep -n "status: g.size === 'story'\|rejected and undone" workflows/check-bugbash-flow.js
273:    results.push({ ...g, status: g.size === 'story' ? 'story' : 'open', commit: '', check: '', notes: FIX ? g.why : 'fixes off' })
324:      fixed = { ...fixed, status: 'open', commit: '', notes: `${fixed.notes} — rejected and undone: ${problems.join('; ')}` }
```

No new copy-lens findings turned up beyond re-confirming CPY-2 through CPY-5; this pass's only
new information is the fixed/open split above. Flagging it here rather than as a numbered finding
because it is about the bug-bash record's own accuracy (which findings are still live), not a
product-copy defect by itself — but a consolidation step that doesn't re-check against the real
HEAD would waste a fix cycle re-closing CPY-1 and CPY-6.
