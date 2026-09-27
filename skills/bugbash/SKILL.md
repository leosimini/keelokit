---
name: bugbash
description: Full bug bash of a Keelokit project across every dimension (data, API, contracts, logic, integrity, auth, UX, UI, web, mobile, i18n, copy, a11y, security, NFRs, config, ops) — parallel lenses on the running app with seeded personas, adversarial validation of each finding, fixes at the root cause, and, for every class of bug, a new automatic check so it can't come back. Use when the user says "bug bash", "cazá bugs", "revisá todo", "buscá errores", "QA completo", before a release, or after each wave.
---

# Bug bash — find, prove, fix at the root, and never again

Autonomous until the report. The one exception: a fix that would change a **product rule** (what
the product should do, not how) is not decided — it becomes a pending decision with options and
a recommendation, and work continues on everything else.

**Source of truth for "expected":** `docs/context/`, `docs/prd.md`, the stories in `backlog/`,
the project's style guide if any. If the expected behaviour doesn't follow from them, it is a
pending decision, not a bug.

Findings format and severity: `references/finding-format.md`. Lenses: one per row of
`${CLAUDE_PLUGIN_ROOT}/references/dimensions.md` (skip dimensions the project doesn't have). The
`integrity` lens attacks every invariant in `docs/context/domain.md` with its class's attack from
`${CLAUDE_PLUGIN_ROOT}/references/invariants.md`, the way `agents/breaker.md` does for one story.

## 1. Prepare

1. Read product, users, roles, critical journeys per role. List the journeys.
2. Scope — default is **incremental**: the diff since the last bug bash (`docs/bugbash/` has the
   previous reports; none → since the first commit) and only the dimensions its stories declare
   plus `ux`, `i18n`, `a11y` for any touched screen, and `integrity` whenever the diff touches a
   critical area (`.keelokit/critical.toml`) or an invariant's code. `--full` runs every lens on
   `main`. Record the sha and the lenses chosen, and why.
3. Budget: at most 4 lenses in parallel (the rest queue); lens and validator agents run on
   Sonnet. Each lens that runs the app gets its own ports (`E2E_PORT`, `E2E_MOBILE_PORT`, `PORT`)
   and, when it writes data, its own database (`docker run … postgres` on a free port, then
   `prisma:migrate:deploy` and `db:seed`).
4. Run the app with seeded personas (`pnpm --filter ./apps/api db:seed`; add the personas the
   product needs to `apps/api/prisma/seed.ts` if they're missing — one per role and relevant
   state: new, with data, no permission, expired session). All locales.
5. Baseline: `pnpm verify` result, so pre-existing failures aren't blamed on fixes.

## 2. Survey — one agent per lens, in parallel, no fixing yet

Each lens agent gets: its row of `dimensions.md`, the journeys, the personas, the finding format,
and a write-only findings file `docs/bugbash/<date>/<lens>.md`. It tests expected cases **and**
edges: empty, error, huge, zero/one/many, other role, other locale, 320 px, offline, twice in a
row, two at once (N parallel requests on the same resource, two cron instances), and every
promise the screens make (COPY-1). Every finding needs evidence.

## 3. Validate — adversarially

A separate agent tries to refute each finding: reproduce it from the steps on the same sha.
Not reproducible → discarded (listed as such). Merge duplicates by **root cause**, keeping the
highest severity. Re-rate severities with the rubric.

## 4. Fix — by priority, root cause first

For each confirmed finding (P0 → P3, product-rule changes excluded):
1. A test that fails, citing the finding id in its title (and the story scenario id if any).
2. The fix where the cause lives; grep every caller of what you change — siblings of the
   reported path are usually broken too.
3. **Escape analysis**: which check should have caught it (see "Automatic" in `dimensions.md`)
   and why it didn't. Add or tighten the check for the **class**, not the case: a race escaped →
   a `race()` concurrency test for that kind of write, not only for that endpoint; a lying text
   → a test of the promised behaviour and a copy line in the contract. A test, a lint rule, a
   type, a contract, an E2E step, a mutation area (`.keelokit/critical.toml`) or a new invariant
   in `domain.md` (with the user's yes: it is a product rule). If it expresses a rule, register it
   with `/keelokit:doctor` (rule + enforcer). Log the escape in `docs/escapes.md` (ESC-1): found
   by `bugbash`, its class, the check added.
4. One commit per finding: `fix(<area>): … (<finding id>)`; if it completes a story's scenario,
   add the `Story: <ID>` trailer. Re-walk the affected journeys.

`pnpm verify` green after every few fixes and at the end; push per the project's flow.

## 5. Report — `docs/bugbash/<date>/report.md`

- Scope (sha), lenses run, personas, what couldn't be verified and why.
- Table: id · lens · severity · title · status (fixed / pending decision / open) · fix commit ·
  **check added**.
- Pending decisions for the human: options + recommendation each.
- **Escapes by dimension and by class** and the checks added; compare with the previous report
  and with `docs/escapes.md` (what the build loop caught before merge) — the trend should go
  down. A dimension or class escaping two bug bashes in a row → propose a house rule for
  Keelokit. Code that produced a P0 or P1 and isn't in a critical area yet → propose adding it.
- Mutation score of the critical areas (`pnpm mutation --all`) and its survivors.
- Final `pnpm verify` and `doctor` results.
