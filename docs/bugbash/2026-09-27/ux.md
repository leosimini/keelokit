# ux

### UX-1 · A "waiting on you" harness-errors item links to `#stage-build`, a section the page never renders until a backlog exists (P1)
- **Persona / context:** Developer with an adopted-but-not-yet-approved harness (exactly this repo's own current state: `mode=harness`, `.keelokit/state.toml` has `[gates]` empty, no `backlog/` yet, doctor reports 16 ERRORs). Sha 19b332e.
- **Steps:**
  1. `git clone /home/user/keelokit $SCRATCH/keelokit` (sha 19b332e, the repo's own real state — self-adoption "awaiting approval", no backlog).
  2. `cd $SCRATCH/keelokit && python3 skills/project-dashboard/scripts/dashboard.py --root . --json`
  3. Inspect `waiting` and cross-check against the rendered page: `python3 skills/project-dashboard/scripts/dashboard.py --root . --standalone --out $SCRATCH/dash.html && grep -c 'id="stage-build"' $SCRATCH/dash.html`
- **Expected:** Every item under "Waiting on you" (`waiting_on_user()`) is something the user can actually go look at on the same dashboard — the sidebar promises "look here", so the anchor it links to must exist on the page (this is the one screen Keelokit renders; every stated next step must be actionable per the ux lens' own brief).
- **Observed:** The JSON's `waiting` array contains `{"text": "16 errores del harness para revisar", "anchor": "stage-build"}` (no `ask`/`act`, i.e. link-only, no button fallback either) — but `grep -c 'id="stage-build"' dash.html` returns `0`. The "Build" `<details id="stage-build">` section is only appended by `render()` when `s["stories"]` is non-empty (`skills/project-dashboard/scripts/dashboard.py:1800: if s["stories"]:`), and this repo has zero backlog stories yet (`backlog` gate is still pending). Clicking (or middle-clicking) "16 errores del harness para revisar" in the sidebar therefore does nothing useful: the page's own click handler only calls `preventDefault()`/`reveal()` when `document.getElementById(id)` exists (`skills/project-dashboard/scripts/dashboard.py:1348-1349`); when it doesn't, the browser falls through to its default same-page `#stage-build` navigation, which is a no-op fragment (nothing scrolls, nothing opens) — so the doctor's 16 errors, which this dashboard is supposed to make actionable, are simply unreachable from the dashboard in exactly the state the baseline run describes. There is no other control on the page that shows the doctor output before a backlog exists (the "Harness health" `<pre>` block lives inside the same gated `stage-build` section).
- **Evidence:**
  ```
  $ python3 skills/project-dashboard/scripts/dashboard.py --root . --json | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['waiting'])"
  [{'text': 'Aprobar «Contexto»', 'anchor': 'stage-intake', ...},
   {'text': '16 errores del harness para revisar', 'anchor': 'stage-build'},
   {'text': 'Actualizar el harness: v0.7.0 → v0.7.1', 'anchor': 'decisions', ...}]

  $ grep -c 'id="stage-build"' dash-thisrepo-es.html
  0
  $ grep -o 'href="#stage-build"' dash-thisrepo-es.html
  href="#stage-build"
  ```
  (Full waitlist HTML, one dead link among three:)
  ```html
  <ul class="waitlist"><li><div class="wi"><a href="#stage-intake">Aprobar «Contexto»</a>...</div></li>
  <li><div class="wi"><a href="#stage-build">16 errores del harness para revisar</a></div></li>
  <li><div class="wi"><a href="#decisions">Actualizar el harness: v0.7.0 → v0.7.1</a>...</div></li></ul>
  ```
- **Where:** `skills/project-dashboard/scripts/dashboard.py:910-911` (`waiting_on_user`, appends the `stage-build` anchor unconditionally whenever `s["errors"]`) vs. `:1800` (`render`, only emits `id="stage-build"` `if s["stories"]:`).
- **Root cause (probable):** `waiting_on_user()` assumes the "Build" section always exists once there are doctor errors, but `render()` gates that section's existence on having at least one backlog story — the two functions disagree on when `#stage-build` is a valid anchor, and nothing keeps them in sync.
- **Class:** consistency
- **Should have been caught by:** A component/state test for the dashboard's "gate pending + doctor errors + no backlog yet" state (dimensions.md's `ux` row calls for "component tests per state") — none exists; `tests/` has no coverage of `dashboard.py`'s HTML output at all, only of `guard.py`/`doctor.py`.
- **Proposed fix:** Either always render a (possibly collapsed) `id="stage-build"` health section whenever `s["doctor"]` is non-empty, regardless of `s["stories"]`, or point this waiting item at a section that already always exists (e.g. give it an `ask` of `/keelokit:check-health` like the harness-upgrade item has, instead of a bare anchor link, so it's actionable even without a `#stage-build` to jump to).

### UX-2 · "Build wave N in parallel" sends a bare count with no wave reference — ambiguous or wrong once more than one wave has ready work at once (P2)
- **Persona / context:** Any persona mid-backlog, once a later wave's stories happen to be ready before an earlier wave finishes (waves group stories that "don't touch the same files," per `docs/context/domain.md` / the glossary — nothing about wave order requires wave 1 to finish before wave 2's stories can be independently ready). Sha 19b332e.
- **Steps:**
  1. Built a fixture backlog with `W1A` (wave 1, no deps, ready) and `W2A`, `W2B` (wave 2, no deps, both ready) — i.e. two waves ready at once, a state the backlog model explicitly allows.
  2. `python3 skills/project-dashboard/scripts/dashboard.py --root . --standalone --out dash-wave.html`
  3. `grep -o 'data-ask="[^"]*build-story[^"]*"[^>]*>[^<]*' dash-wave.html`
- **Expected:** The button labelled "Build wave 2 in parallel" (`t["act_build_wave"]`) sends Claude a prompt that builds wave 2's ready stories, since that's what the button says it does.
- **Observed:** The button's `data-ask` is `/keelokit:build-story 2` — a bare count, with no mention of wave 2, W2A or W2B anywhere in the string. Per `build-story`'s own documented picking rule (`skills/build-story/SKILL.md`, step 1 "Pick": "first ready story, or the one the user named. For N stories: only from the same wave [as that first pick]"), a plain "build-story 2" tells the agent to take the *first* ready story it finds (which in this fixture is `W1A`, wave 1) and then look for a second ready story in *that same wave* — but wave 1 has only one ready story, so the count the button sends doesn't even describe a coherent instruction for wave 2's own two stories. The per-story "Build this story" buttons do it right (`data-ask="/keelokit:build-story W2A"`), so the wave-level button is the only one that loses the wave-targeting information. (The hero "Next step" card has a related, milder version of the same gap: `next_build_d`'s "One at a time, or in parallel with…" phrasing is shown even when only one story is ready in the wave — e.g. observed text "1 stories are ready in wave 1. One at a time, or in parallel with "/keelokit:build-story 1"." — offering "parallel" as a real alternative when there is nothing to parallelize.)
- **Evidence:**
  ```
  $ python3 -c "..." # stories: W1A wave1 ready, W2A wave2 ready, W2B wave2 ready
  $ grep -o 'data-ask="[^"]*build-story[^"]*"[^>]*>[^<]*' dash-wave.html
  data-ask="/keelokit:build-story W1A">Ask Claude
  data-ask="/keelokit:build-story W1A">Build this story
  data-ask="/keelokit:build-story 2">Build wave 2 in parallel
  data-ask="/keelokit:build-story W2A">Build this story
  data-ask="/keelokit:build-story W2B">Build this story
  ```
- **Where:** `skills/project-dashboard/scripts/dashboard.py:1537-1540` (`wave_action`, builds the prompt as `f"/keelokit:build-story {len(ready)}"`, dropping `w` entirely) and `:114/326` (`next_build_d` template, no `n > 1` guard before offering the parallel phrasing).
- **Root cause (probable):** `wave_action()`'s prompt was written assuming build-story's count always resolves to "the ready stories of whichever wave is currently the front of the queue," which is true only when exactly one wave has ready work — a case the backlog model doesn't guarantee.
- **Class:** consistency
- **Should have been caught by:** Component tests per state for the backlog view with two waves simultaneously ready (dimensions.md's `ux` row: "component tests per state") — none exist for `dashboard.py`.
- **Proposed fix:** Have `wave_action()` send the actual story IDs (`f"/keelokit:build-story {' '.join(x['id'] for x in ready)}"` or equivalent, if `build-story` accepts explicit IDs) instead of a bare count, or at minimum name the wave in the prompt text (e.g. "build the N ready stories of wave {w}") so the instruction is unambiguous regardless of what else is ready elsewhere.

### UX-3 · An environment's pending-steps list silently truncates to 4, with no count of what's hidden and no link to the full checklist doc (P3)
- **Persona / context:** Founder/dev at the "Set up the environments" stage with a real deploy checklist (`docs/deploy.md`) longer than 4 remaining steps. Sha 19b332e.
- **Steps:**
  1. Built a fixture with `docs/deploy.md`'s `## staging` section holding 8 checklist items, 1 done, 7 pending.
  2. `python3 skills/project-dashboard/scripts/dashboard.py --root . --standalone --out dash-env.html`
  3. Inspected the `.env .todo` list for the staging card.
- **Expected:** The environments card either shows every pending step or tells the user there's more (and gives them a way to see the rest), since "next step, actionable" is the dashboard's whole purpose.
- **Observed:** The pill correctly says "1 of 8 steps ready", but the `<ul class="todo">` under it lists only the first 4 pending steps ("Add Fly.io app", "Configure secrets", "Point DNS", "Set up TLS") and silently drops the other 3 ("Configure CDN", "Wire monitoring", "Load test") — no "+3 more", no ellipsis, and the environments section has no link back to `docs/deploy.md` anywhere (unlike every other section, which wraps its source doc in an openable `<details class="doc">`). A user working only from the dashboard has no way to discover, let alone start, the last three steps.
- **Evidence:**
  ```
  $ grep -o '<ul class="todo">.*</ul>' dash-env.html | head -1
  <ul class="todo"><li>Add Fly.io app</li><li>Configure secrets</li><li>Point DNS</li><li>Set up TLS</li></ul>
  ```
  (staging has 8 steps total per the fixture's `docs/deploy.md`; only 4 appear anywhere in the rendered page — `grep -c` for the omitted step texts against `dash-env.html` returns 0.)
- **Where:** `skills/project-dashboard/scripts/dashboard.py:1685` (`environments_section`: `pending = [x for x in e["steps"] if not x["done"]][:4]`), and the section overall has no `doc_block()` call for `docs/deploy.md`.
- **Root cause (probable):** The `[:4]` slice was presumably meant to keep the card short for a nearly-finished environment, but nothing tells the reader the list was cut, and there's no fallback link to the full document for a long one.
- **Class:** other
- **Should have been caught by:** Component test for the "environments" card with a long checklist (dimensions.md's `ux` row: "component tests per state") — none exists.
- **Proposed fix:** Append a "+{n} more" line (linking to the opened `docs/deploy.md`, added as a `doc_block()` like every other section) when `len(pending) > 4`, or simply raise the cap / show a "see all" toggle.

### UX-4 · House-rule IDs and bug-bash finding IDs share the same `<PREFIX>-<n>` namespace and identical on-page styling, so the two are indistinguishable where the dashboard shows both (P3)
- **Persona / context:** Any persona reading the dashboard's harness/adopt section next to its bug-bash section (both visible on the one screen Keelokit renders), or reading `doctor.py`'s plain-text output next to a bug-bash report. Sha 19b332e.
- **Steps:**
  1. `grep -oP '(?<=^id = ")[A-Z]+-\d+' template/.keelokit/harness/rules.toml | sort -u` → house rule IDs include `SEC-1`, `SEC-2`, `SEC-3`, `UX-1`, `UI-1`, `CFG-1`, among others.
  2. `grep -n "Lens prefixes" -A3 skills/check-bugbash/references/finding-format.md` → the bug-bash lens prefixes are `DATA, API, CTR, LOG, INT, AUTH, UX, UI, WEB, MOB, I18N, CPY, A11Y, SEC, NFR, CFG, OPS, DX, DOC, PKG` — i.e. every one of `SEC`, `UX`, `UI`, `CFG` is simultaneously a house-rule prefix and a lens prefix, so `SEC-1`/`UX-1`/`UI-1`/`CFG-1` each name two unrelated things (this very bug bash's own first `ux` finding is `UX-1`, colliding by construction with the house rule `UX-1` in `rules.toml`; the sibling `sec` lens's findings for this same run are `SEC-1`..`SEC-6`, colliding with the house rules `SEC-1`/`SEC-2`/`SEC-3`).
  3. Confirmed both render with the exact same markup on the dashboard: the rules-exceptions table cell is `<span class="tag">{rule id}</span>` (`skills/project-dashboard/scripts/dashboard.py:1721`) and the bug-bash findings table cell is `<span class="tag">{finding id}</span>` (`:1643`) — same CSS class, same font, same pill shape, on the same page.
  4. `cat .keelokit/exceptions.toml` in this repo — its own commented-out example exception literally uses `rule = "UI-1"`, confirming the collision is not a contrived corner case but the format this repo ships as its own documentation example.
- **Expected:** Reading "SEC-1" or "UX-1" anywhere on the dashboard (or in `doctor.py`'s output, which the dashboard also embeds verbatim in the "Harness health" block) should tell the reader one thing.
- **Observed:** `doctor.py`'s own output for this repo already prints `ERROR rule SEC-1: ...` lines and `not applicable: SEC-3, ..., UX-1, ...` in the same run whose bug bash produces findings named `SEC-1`..`SEC-6` and `UX-1`..`UX-4`. A reader skimming an exceptions table row "SEC-1 · approved by Leo · expires 2026-12-31" next to a bug-bash findings table row "SEC-1 · fixed · commit abc123" (both real, both plausible on one page once this bash's own findings are filed) has no way to tell, from the ID alone, whether the two rows describe the same thing — they don't.
- **Evidence:**
  ```
  $ grep -oP '(?<=^id = ")[A-Z]+-\d+' template/.keelokit/harness/rules.toml | sort -u
  AGENT-1 AGENT-2 ARCH-1 AUTHZ-1 CFG-1 CONTRACT-1 COPY-1 CRIT-1 CTX-1 DB-1 DEP-1 ESC-1 GIT-1 GIT-2
  INV-1 MUT-1 QA-1 QA-2 QA-3 QA-4 REL-1 REVIEW-1 SAST-1 SEC-1 SEC-2 SEC-3 TRACE-1 UI-1 UX-1 VERIFY-1 VERIFY-2

  $ grep -n "Lens prefixes" -A3 skills/check-bugbash/references/finding-format.md
  Lens prefixes: `DATA`, `API`, `CTR`, `LOG`, `INT`, `AUTH`, `UX`, `UI`, `WEB`, `MOB`, `I18N`,
  `CPY`, `A11Y`, `SEC`, `NFR`, `CFG`, `OPS`, and for a developer-facing project `DX`, `DOC`, `PKG`.

  $ cat .keelokit/exceptions.toml
  # [[exception]]
  # rule = "UI-1"
  # reason = "Third-party map SDK needs a literal colour for its marker."
  ```
- **Where:** `template/.keelokit/harness/rules.toml` (rule IDs) vs. `skills/check-bugbash/references/finding-format.md:19-21` (lens prefixes); both surfaced identically in `skills/project-dashboard/scripts/dashboard.py:1643` and `:1721`.
- **Root cause (probable):** The two ID schemes (house rules, bug-bash lenses) were designed independently, each picking short mnemonic prefixes from the same small pool of two/three-letter domain words (security, UX, UI, config), with nothing reserving the namespace for one or the other.
- **Class:** consistency
- **Should have been caught by:** A cross-reference check in `doctor.py` or a packaging/docs check (dimensions.md's `dx`/`docs` rows) diffing `rules.toml` IDs against `finding-format.md`'s lens-prefix list — none exists.
- **Proposed fix:** Prefix one of the two namespaces distinctly (e.g. house rules keep bare `SEC-1`, bug-bash findings become `bb:SEC-1` or use a disjoint prefix set), or at minimum render them with visually distinct styling on the dashboard (e.g. a different tag colour/icon) so a shared ID string can't be misread as the same object.

### UX-5 · The dashboard shows nothing about a bug bash — not even "none yet" — for the whole run, including after real fixes from it have already landed in git history (P2)
- **Persona / context:** Any persona checking the dashboard during or right after a bug bash, in a pre-backlog project (this repo's own real, current state: `docs/bugbash/2026-09-27/` already holds 12 lens findings files — `a11y.md, copy.md, docs.md, dx.md, i18n.md, integrity.md, logic.md, nfr.md, packaging.md, security.md, ui.md, ux.md` — and `git log` on the live repo already shows 23 `fix(...)` commits citing findings from these exact files, e.g. `fcbbee7 fix(dashboard): send a wave's stories by id from its build button (UX-2)`, `47ccd43 fix(guard): check what shell commands write... (LOG-1)`). Sha 19b332e (clone), live repo now several commits ahead on the same branch mid-bug-bash.
- **Steps:**
  1. `git clone /home/user/keelokit $SCRATCH/keelokit` (sha 19b332e) and copy the live repo's real, untracked `docs/bugbash/2026-09-27/` (12 lens `.md` files, no `report.md` yet — the fix phase is demonstrably already underway per the commits above) into the clone at the same path.
  2. `cd $SCRATCH/keelokit && python3 skills/project-dashboard/scripts/dashboard.py --root . --json | python3 -c "import json,sys;print(json.load(sys.stdin)['bugbashes'])"`
  3. `python3 skills/project-dashboard/scripts/dashboard.py --root . --lang en --standalone --out $SCRATCH/dash.html && grep -c 'id="bugbash"' $SCRATCH/dash.html`
- **Expected:** Per `references/design.md`'s own component table ("Bug bashes | each run: counts, findings with severity and the check added, pending decisions, the stories it created") and `T["bb_none"]`/`T["bb_none"]` ("None yet. One after each wave is a good habit."), the dashboard should either show the bug bash's findings or, failing that, at least the "none yet" placeholder — the one screen Keelokit renders is supposed to say "where we are," and "we already ran a bug bash and are partway through fixing it" is not the same state as "we've never run one."
- **Observed:** `collect()`'s `reports("docs/bugbash", "bugbash")` (`skills/project-dashboard/scripts/dashboard.py:859`) globs only `docs/bugbash/*/report.md` — the single, final, consolidated file that `skills/check-bugbash/SKILL.md:99` says is written in section 5, *after* duplicates merge and fixes are applied. The per-lens files it globs over are explicitly `skills/check-bugbash/SKILL.md:69`'s "write-only findings file `docs/bugbash/<date>/<lens>.md`" — not the report. Until that last file is written, `s["bugbashes"]` is `[]` (confirmed: `[]`), and because `s["stories"]` is also empty in this pre-backlog state, `render()`'s guard `if s["stories"] or s["bugbashes"]:` (`:1985`) is false, so `bugbash_section()` never runs at all — not the populated table, not the `bb_none` placeholder, nothing (`grep -c 'id="bugbash"'` → `0`; the string "Bug bash" appears exactly once on the whole page, in the unrelated "Run a bug bash" action button). A user opening the dashboard right now, mid-run, sees a page that looks exactly like a project that has never had a bug bash, even though 12 findings files and 23 real fix commits already exist for this one. If the run is "cut short" (a state the journey doc explicitly names as normal — "a run cut short resumes"), this isn't a brief flash between steps: it can persist indefinitely, since nothing but the very last workflow step produces `report.md`, and a crash, timeout or a person closing the loop before that step leaves the dashboard permanently blind to a substantial amount of real, already-applied work.
- **Evidence:**
  ```
  $ ls docs/bugbash/2026-09-27/
  a11y.md copy.md docs.md dx.md i18n.md integrity.md logic.md nfr.md packaging.md security.md ui.md ux.md
  $ ls docs/bugbash/2026-09-27/report.md
  ls: cannot access 'docs/bugbash/2026-09-27/report.md': No such file or directory

  $ python3 skills/project-dashboard/scripts/dashboard.py --root . --json | python3 -c "import json,sys; print(json.load(sys.stdin)['bugbashes'])"
  []

  $ python3 skills/project-dashboard/scripts/dashboard.py --root . --lang en --standalone --out dash.html
  $ grep -c 'id="bugbash"' dash.html
  0
  $ grep -c 'Bug bash' dash.html
  1

  # meanwhile, on the live repo (same bug bash, same date folder):
  $ git log --oneline 19b332e..HEAD | grep -c '^[0-9a-f]* fix('
  23
  $ git log --oneline 19b332e..HEAD | grep 'UX-'
  fcbbee7 fix(dashboard): send a wave's stories by id from its build button (UX-2)
  afac4ba fix(dashboard): link harness errors to a health section that exists before a backlog (UX-1)
  ```
- **Where:** `skills/project-dashboard/scripts/dashboard.py:857-877` (`reports()` globs only `*/report.md`) and `:1985` (`render()`'s `if s["stories"] or s["bugbashes"]:` guard, which hides even the empty-state placeholder when both are empty).
- **Root cause (probable):** The dashboard was built to read the bug bash's single final artifact (`report.md`), on the implicit assumption that nothing worth showing exists before that file lands — but the workflow's own lens phase and fix phase (both real, both potentially long-running or interruptible) now produce durable, inspectable state — findings files and fix commits — well before that assumption holds.
- **Class:** transition
- **Should have been caught by:** A component test for the dashboard's "bug bash lens files present, report.md not yet written" state (dimensions.md's `ux` row: "component tests per state") — none exists; the only fixture the existing dashboard tests build already has a finished `report.md`.
- **Proposed fix:** Either have the workflow write (or update) a minimal `report.md` as soon as the lens phase finishes, before skeptics/fixes run, and update it again if the run is cut short, or have `reports()`/`render()` fall back to a lighter in-progress summary (e.g. "N lenses reported, fixes in progress") built from the per-lens files when no `report.md` exists yet, instead of silently rendering as if no bug bash had ever run.
