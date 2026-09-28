export const meta = {
  name: 'check-bugbash-flow',
  description: 'Engine of /keelokit:check-bugbash. Lenses picked by the project profile survey the product in parallel, independent skeptics reproduce every finding, duplicates merge by root cause, confirmed bugs are fixed one by one with a failing test and a check for their class, and the report lands in docs/bugbash.',
  whenToUse: 'Started by /keelokit:check-bugbash, which prepares the scope and handles the pending decisions afterwards. Run it directly for a bug bash with the defaults: incremental scope, fixes on.',
  phases: [
    { title: 'Prepare', detail: 'scope, lenses from the profile, journeys, personas, baseline' },
    { title: 'Survey', detail: 'one agent per lens, no fixing' },
    { title: 'Validate', detail: 'independent skeptics reproduce each finding' },
    { title: 'Coverage', detail: 'what no lens looked at yet' },
    { title: 'Consolidate', detail: 'merge by root cause, re-rate, pending decisions' },
    { title: 'Fix', detail: 'failing test, fix at the cause, check for the class, independent check' },
    { title: 'Report', detail: 'report, final verify and doctor' },
  ],
}

// args (all optional): {date, scope: 'incremental' | 'full', lenses: ['dx', ...], fix: true,
//   maxParallel: 4, rounds, pluginRoot, model: 'sonnet', notes}
// Rules of the procedure live in skills/check-bugbash/SKILL.md; this script only fixes its shape:
// who runs, in what order, how many at once, how many rounds, and what each step must return.

const A = args || {}
const WORKER = A.model || 'sonnet'
const FIX = A.fix !== false
const MAX = Number.isFinite(A.maxParallel) && A.maxParallel > 0 ? A.maxParallel : 4
const LENSES = A.lenses == null ? null : [].concat(A.lenses).map(String) // 'logic' or ['logic', 'dx']
const ROUNDS = Number.isFinite(A.rounds) ? Math.max(1, A.rounds) : null
// Resuming a run replays every agent() whose prompt is unchanged, so no prompt may depend on the
// order in which parallel agents happen to finish: what they see of each other is sorted, and a
// survey sees only the findings of earlier rounds. Anything with a side effect (a commit) checks
// for itself whether it already happened, because a call that died never returned.
const SEV = ['P0', 'P1', 'P2', 'P3']

// At most MAX agents that run the product at the same time (ports, databases, cost).
function limiter(n) {
  let active = 0
  const queue = []
  const next = () => {
    if (active >= n || !queue.length) return
    active++
    const { fn, resolve } = queue.shift()
    fn().then(resolve, () => resolve(null)).finally(() => { active--; next() })
  }
  return fn => new Promise(resolve => { queue.push({ fn, resolve }); next() })
}
const slot = limiter(MAX)
const byId = list => list.slice().sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0))

const str = { type: 'string' }
const strs = { type: 'array', items: str }

const PLAN = {
  type: 'object',
  required: ['date', 'sha', 'scope', 'outDir', 'pluginRoot', 'kind', 'lenses', 'skipped', 'journeys', 'personas', 'run', 'verify', 'baseline'],
  properties: {
    date: str, sha: str, scope: { enum: ['incremental', 'full'] }, since: str, outDir: str, pluginRoot: str,
    kind: str, traits: strs,
    lenses: {
      type: 'array',
      items: {
        type: 'object', required: ['id', 'prefix', 'row', 'focus', 'why'],
        properties: { id: str, prefix: str, row: str, focus: str, why: str },
      },
    },
    skipped: { type: 'array', items: { type: 'object', required: ['id', 'why'], properties: { id: str, why: str } } },
    journeys: strs, personas: strs, invariants: strs, critical: strs, sources: strs,
    run: str, verify: str, doctor: str, baseline: str, escapes: str,
  },
}

const FINDING = {
  type: 'object',
  required: ['id', 'title', 'severity', 'steps', 'expected', 'observed', 'evidence', 'rootCause', 'class', 'proposedFix'],
  properties: {
    id: str, title: str, severity: { enum: SEV }, persona: str, steps: str, expected: str, source: str,
    observed: str, evidence: str, where: str, rootCause: str, class: str, shouldHaveCaught: str,
    proposedFix: str, productRule: { type: 'boolean' },
  },
}
const SURVEY = {
  type: 'object', required: ['findings', 'covered', 'notCovered'],
  properties: { findings: { type: 'array', items: FINDING }, covered: strs, notCovered: strs },
}
const VERDICT = {
  type: 'object', required: ['reproduced', 'kind', 'severity', 'evidence', 'why'],
  properties: {
    reproduced: { type: 'boolean' },
    kind: { enum: ['bug', 'decision', 'not-a-bug'] },
    severity: { enum: SEV }, evidence: str, why: str,
  },
}
const GAPS = {
  type: 'object', required: ['tasks'],
  properties: {
    tasks: {
      type: 'array',
      items: { type: 'object', required: ['lens', 'focus', 'why'], properties: { lens: str, focus: str, why: str } },
    },
  },
}
const CONSOLIDATED = {
  type: 'object', required: ['groups', 'decisions'],
  properties: {
    groups: {
      type: 'array',
      items: {
        type: 'object', required: ['id', 'merged', 'severity', 'title', 'area', 'rootCause', 'size', 'why'],
        properties: {
          id: str, merged: strs, severity: { enum: SEV }, title: str, area: str, rootCause: str,
          size: { enum: ['fix', 'story'] }, why: str, plan: str,
        },
      },
    },
    decisions: {
      type: 'array',
      items: {
        type: 'object', required: ['id', 'question', 'options', 'recommendation'],
        properties: { id: str, question: str, options: strs, recommendation: str },
      },
    },
  },
}
const FIXED = {
  type: 'object', required: ['status', 'base', 'commit', 'test', 'check', 'escapeClass', 'notes'],
  properties: {
    status: { enum: ['fixed', 'open'] }, base: str, commit: str, test: str, check: str, escapeClass: str, notes: str,
  },
}
const CHECKED = {
  type: 'object', required: ['ok', 'problems'],
  properties: { ok: { type: 'boolean' }, problems: strs },
}
const REPORT = {
  type: 'object', required: ['report', 'verify', 'doctor', 'summary'],
  properties: { report: str, commit: str, verify: str, doctor: str, summary: str },
}

// ── Prepare ─────────────────────────────────────────────────────────────────────────────────────
phase('Prepare')
const plan = await agent(
  `You prepare a Keelokit bug bash of the repository in the current directory. Read, run, decide; change nothing except creating the output folder.

1. Find the Keelokit plugin root: ${A.pluginRoot ? `"${A.pluginRoot}"` : 'the folder that holds references/dimensions.md and skills/check-bugbash/ — try $CLAUDE_PLUGIN_ROOT, then ~/.claude/plugins (any keelokit folder), then this repository itself'}. Read skills/check-bugbash/SKILL.md, skills/check-bugbash/references/finding-format.md and references/dimensions.md there.
2. Date: ${A.date ? `"${A.date}"` : 'today, from `date +%F`'}. Sha: \`git rev-parse --short HEAD\`. Output folder: reserve it with a plain \`mkdir docs/bugbash/DATE\` (no -p); if that fails because it exists, try DATE-2, DATE-3… until one succeeds, and return the one you created as outDir.
3. Scope: ${A.scope === 'full' ? 'full — every lens the profile calls for, on the whole product' : 'incremental unless there is no previous report — the diff since the sha in the latest docs/bugbash/*/report.md (none → since the first commit); only the lenses that diff can break, plus the ones the SKILL names for touched screens or critical areas'}. ${LENSES ? `The user asked for exactly these lenses: ${LENSES.join(', ')}.` : ''}
4. Lenses: from .keelokit/profile.toml (kind, traits) and "Which lenses a project gets" in dimensions.md. For each lens: its id, a 2–4 letter uppercase finding prefix (the ones finding-format.md lists; DX, DOC and PKG for dx, docs and packaging), its full row of dimensions.md, a concrete focus for THIS repository (which files, commands, journeys and invariants it should attack), and why it runs. Every lens that doesn't run goes in skipped with its reason. If the code shows a trait the profile lacks, say so in why of the affected lens and include that lens.
5. From docs/context (product.md, domain.md, constraints.md), docs/prd.md, backlog/, README: the critical journeys per role (or, for a developer-facing project, per kind of user: newcomer following the README, someone upgrading from the last release, a contributor running the tests), the personas, every invariant (id, text, class), the critical areas from .keelokit/critical.toml, and the files that define "expected".
6. How to run the product for a lens without disturbing the others (own ports, own database, own temp dirs; for a developer-facing project: install or load the package from a clean copy), the command that verifies the repository (pnpm verify, or for a repo without it the tests and checks its AGENTS.md or CI run), the doctor command if .keelokit/bin/doctor.py exists, and where escapes are logged (docs/escapes.md; say "missing" if it isn't there).
7. Baseline: run the verify command now and summarise the result, so pre-existing failures aren't blamed on fixes.

${A.notes ? `Notes from the user: ${A.notes}` : ''}
Return the plan.`,
  { label: 'plan', phase: 'Prepare', schema: PLAN },
)
if (!plan) return { error: 'Prepare failed: no plan' }
log(`Scope ${plan.scope} at ${plan.sha} — lenses: ${plan.lenses.map(l => l.id).join(', ')}; skipped: ${plan.skipped.map(s => s.id).join(', ') || 'none'}`)

const CONTEXT = `Keelokit bug bash of the repository in the current directory, sha ${plan.sha}, scope ${plan.scope}${plan.since ? ` since ${plan.since}` : ''}.
Project kind: ${plan.kind}. Plugin root (procedure and formats): ${plan.pluginRoot}.
Where "expected" comes from: ${(plan.sources || []).join(', ') || 'docs/context, docs/prd.md, backlog, README'}. If the expected behaviour doesn't follow from them it is a pending decision, not a bug.
Journeys:\n- ${plan.journeys.join('\n- ')}
Personas:\n- ${plan.personas.join('\n- ')}
Invariants:\n- ${(plan.invariants || []).join('\n- ') || 'none recorded'}
Critical areas: ${(plan.critical || []).join(', ') || 'none'}
How to run it in isolation: ${plan.run}
Verify: ${plan.verify}. Baseline before any fix: ${plan.baseline}`

// ── Survey and validate, in rounds until coverage runs dry ──────────────────────────────────────
const counters = {}
const confirmed = []
const discarded = []
const decisions = []
const covered = []
const seenTitles = []
let tasks = plan.lenses.map(l => ({ lens: l.id, focus: l.focus, why: l.why }))
const rounds = ROUNDS ?? (plan.scope === 'full' ? 3 : 2)
const byLens = Object.fromEntries(plan.lenses.map(l => [l.id, l]))

async function survey(task, round, known, n) {
  const lens = byLens[task.lens] // tasks only ever name planned lenses
  const start = (counters[lens.prefix] = counters[lens.prefix] || 0) + 1
  counters[lens.prefix] += 100 // room for this agent's findings; ids stay unique across rounds
  return slot(() => agent(
    `${CONTEXT}

You are the ${lens.id} lens${round > 1 ? ` (round ${round}, a gap the first rounds left)` : ''}. Its row of dimensions.md:
${lens.row}
Focus: ${task.focus}

Survey only — do not fix, do not commit, do not edit tracked files. Run the product the way the plan says, as the personas, and test expected cases and edges: empty, error, huge, zero/one/many, other role, other locale, twice in a row, two at once, wrong input on every command, every promise the docs and screens make. Every finding needs evidence you produced yourself (command + output, request + response, file:line).
Already reported in earlier rounds (don't repeat them): ${known.slice(-60).join(' | ') || 'nothing yet'}
Number your findings ${lens.prefix}-${start}, ${lens.prefix}-${start + 1}… Severity by the rubric in finding-format.md. Mark productRule when the fix would change what the product should do rather than how.
Append each finding, in the format of finding-format.md, to ${plan.outDir}/${lens.id}.md (create it with a "# ${lens.id}" title). Return the findings, what you covered and what you couldn't.`,
    { label: `${lens.id}${round > 1 ? ` r${round}.${n}` : ''}`, phase: 'Survey', schema: SURVEY, model: WORKER },
  ))
}

async function validate(f, lensId) {
  const serious = f.severity === 'P0' || f.severity === 'P1'
  const skeptic = (model, n) => slot(() => agent(
    `${CONTEXT}

You are an independent skeptic. Another agent reported this finding; try to refute it. Default to reproduced=false when you can't make it happen yourself on this sha.
${JSON.stringify(f, null, 1)}

1. Reproduce it from its steps, in isolation (own ports and temp dirs), without editing tracked files. Record your own evidence.
2. Decide what it is: "bug" (it happens and contradicts an expected behaviour that follows from the sources), "decision" (it happens but the sources don't say what should happen, or fixing it changes a product rule) or "not-a-bug" (the sources say this is right).
3. Re-rate the severity with the rubric in finding-format.md, saying why.`,
    { label: `check ${f.id}${n ? ` #${n + 1}` : ''}`, phase: 'Validate', schema: VERDICT, model },
  ))
  const votes = (await Promise.all(serious ? [skeptic(WORKER, 0), skeptic(undefined, 1)] : [skeptic(WORKER, 0)])).filter(Boolean)
  const yes = votes.filter(v => v.reproduced)
  const entry = { ...f, lens: lensId, votes }
  if (!votes.length || yes.length * 2 < votes.length) return discarded.push({ ...entry, why: votes.map(v => v.why).join(' / ') || 'no verdict' })
  const kinds = yes.map(v => v.kind)
  const kind = kinds.includes('decision') || f.productRule ? 'decision' : kinds.every(k => k === 'not-a-bug') ? 'not-a-bug' : 'bug'
  if (kind === 'not-a-bug') return discarded.push({ ...entry, why: yes.map(v => v.why).join(' / ') })
  const severity = yes.map(v => v.severity).sort()[0]
  const record = { ...entry, severity, kind, reproducedBy: `${yes.length}/${votes.length}` }
  if (kind === 'decision') decisions.push(record)
  else confirmed.push(record)
}

for (let round = 1; round <= rounds && tasks.length; round++) {
  if (round > 1) log(`Round ${round}: ${tasks.length} gaps — ${tasks.map(t => t.lens).join(', ')}`)
  const known = seenTitles.slice().sort()
  await pipeline(
    tasks,
    (task, _, i) => survey(task, round, known, i + 1),
    (res, task) => {
      if (!res) return null
      covered.push(...res.covered.map(c => `${task.lens}: ${c}`), ...res.notCovered.map(c => `${task.lens} (not covered): ${c}`))
      seenTitles.push(...res.findings.map(f => `${f.id} ${f.title}`))
      return Promise.all(res.findings.map(f => validate(f, task.lens)))
    },
  )
  log(`After round ${round}: ${confirmed.length} bugs, ${decisions.length} decisions, ${discarded.length} discarded`)
  if (round === rounds) break
  const gaps = await agent(
    `${CONTEXT}

You are the completeness critic of this bug bash. Lenses that ran: ${plan.lenses.map(l => `${l.id} (${l.focus})`).join('; ')}.
What they covered and what they said they couldn't:
- ${covered.slice().sort().join('\n- ')}
Findings so far: ${seenTitles.slice().sort().join(' | ') || 'none'}

Read the repository and name what matters and nobody looked at yet: a journey, a command, a file, an invariant, an edge (twice, two at once, upgrade, clean install, wrong input), a promise in the docs. At most ${MAX * 2} tasks, each for one lens id from the list above with a concrete focus. Return no tasks when the rest would only repeat what was done.`,
    { label: `coverage r${round}`, phase: 'Coverage', schema: GAPS },
  )
  const proposed = gaps && gaps.tasks || []
  const unknown = proposed.filter(t => !byLens[t.lens])
  tasks = proposed.filter(t => byLens[t.lens])
  if (unknown.length) log(`Coverage r${round}: dropped ${unknown.length} task(s) for lenses that aren't planned: ${unknown.map(t => t.lens).join(', ')}`)
  if (tasks.length > MAX * 2) log(`Coverage r${round}: kept ${MAX * 2} of ${tasks.length} tasks; dropped: ${tasks.slice(MAX * 2).map(t => `${t.lens} (${t.focus})`).join('; ')}`)
  tasks = tasks.slice(0, MAX * 2)
}

// ── Consolidate ─────────────────────────────────────────────────────────────────────────────────
phase('Consolidate')
let groups = []
let pending = []
if (confirmed.length || decisions.length) {
  const merged = await agent(
    `${CONTEXT}

Consolidate the validated findings of this bug bash. Read the code where needed.
Bugs (reproduced by independent skeptics):
${JSON.stringify(byId(confirmed).map(({ votes, ...f }) => f), null, 1)}
Pending decisions (they happen, but what should happen is a product rule):
${JSON.stringify(byId(decisions).map(({ votes, ...f }) => f), null, 1)}

1. Group the bugs by root cause: one group per cause, keeping the lowest id as the group's id, the highest severity (re-check it with the rubric in finding-format.md), a title, the area (conventional commit scope), the cause in one sentence and the smallest fix plan at the cause (grep every caller: siblings of the reported path are usually broken too).
2. size "fix" when one focused change with its test fixes it; "story" when it needs design, many files, or a migration — say why.
3. For each pending decision: the question in plain words for the product's owner, 2–3 options with their consequences, and a recommendation.`,
    { label: 'merge', phase: 'Consolidate', schema: CONSOLIDATED },
  )
  groups = (merged && merged.groups || []).sort((a, b) => SEV.indexOf(a.severity) - SEV.indexOf(b.severity))
  pending = merged && merged.decisions || []
}
log(`${groups.length} root causes (${groups.filter(g => g.size === 'fix').length} to fix now), ${pending.length} pending decisions`)

// ── Fix, one at a time: every fix commits on the same branch ────────────────────────────────────
phase('Fix')
const results = []
for (const g of groups) {
  if (!FIX || g.size !== 'fix') {
    results.push({ ...g, status: g.size === 'story' ? 'story' : 'open', commit: '', check: '', notes: FIX ? g.why : 'fixes off' })
    continue
  }
  const findings = confirmed.filter(f => f.id === g.id || (g.merged || []).includes(f.id)).map(({ votes, ...f }) => f)
  const brief = `${CONTEXT}

Root cause ${g.id} (${g.severity}, area ${g.area}): ${g.title}
Cause: ${g.rootCause}
Plan: ${g.plan || 'find the smallest change at the cause'}
Findings it explains:
${JSON.stringify(findings, null, 1)}`
  let fixed = null
  let problems = []
  for (let attempt = 1; attempt <= 2; attempt++) {
    fixed = await agent(
      `${brief}
${problems.length ? `\nYour previous attempt was rejected by an independent check:\n- ${problems.join('\n- ')}\nFix what it says, on top of your commit (amend it).` : ''}

Fix it, following section 4 of skills/check-bugbash/SKILL.md in ${plan.pluginRoot}:
${attempt === 1 ? `0. First, \`git log --format='%h %s' --grep='(${g.id})' ${plan.sha}..HEAD\`: a commit there means an earlier, interrupted run already fixed this root cause. Don't fix it again — return status "fixed" with that commit, its parent as base, and the test and check it added.
` : ''}1. Note \`git rev-parse HEAD\` first (return it as base). A test that fails now, with ${g.id} in its title.
2. The fix where the cause lives; grep every caller and fix the siblings too. Don't touch unrelated code.
3. Escape analysis: which check should have caught it and why it didn't. Add or tighten the check for the class, not the case (a test, a lint rule, a type, a contract, a validation step in CI). A new product rule or invariant is not yours to add: write it in notes instead.
4. A row in ${plan.escapes && plan.escapes !== 'missing' ? plan.escapes : 'docs/escapes.md (create it with the columns Id · Date · Found by · What escaped · Class · Check added)'}: found by check-bugbash ${plan.date}.
5. ${plan.verify} — green, except failures the baseline already had.
6. One commit: "fix(${g.area}): <what> (${g.id})". Don't push.
If you can't fix it properly, reset to the sha you noted and return status "open" with why.`,
      { label: `fix ${g.id}${attempt > 1 ? ' again' : ''}`, phase: 'Fix', schema: FIXED },
    )
    if (!fixed || fixed.status !== 'fixed') break
    const check = await agent(
      `${brief}

A fixer says it fixed this in commit ${fixed.commit}: ${fixed.notes}
Test: ${fixed.test}. Check added for the class: ${fixed.check}.

Check it independently; you did not write it and owe it no charity. Don't edit tracked files.
- The test fails without the fix (check out the parent's version of the changed non-test files in a temporary worktree, run the test there) and passes with it.
- Each finding's steps no longer reproduce.
- The fix is at the cause, and the siblings a grep of the callers finds are fixed too.
- The check added would catch another bug of the same class, not only this one.
- The escapes row exists; ${plan.verify} is green except what the baseline already failed.
- The commit touches nothing unrelated.`,
      { label: `check fix ${g.id}`, phase: 'Fix', schema: CHECKED },
    )
    if (check && check.ok) break
    problems = check ? check.problems : ['the independent check did not return']
    if (attempt === 2) {
      await agent(
        `Undo a rejected bug bash fix: if every commit in \`git log ${fixed.base}..HEAD\` is a fix for ${g.id}, run \`git reset --hard ${fixed.base}\`; otherwise revert only the ${g.id} commits with \`git revert --no-edit\`. Leave the working tree clean and report what you did.`,
        { label: `undo ${g.id}`, phase: 'Fix', model: WORKER, effort: 'low' },
      )
      fixed = { ...fixed, status: 'open', commit: '', notes: `${fixed.notes} — rejected and undone: ${problems.join('; ')}` }
    }
  }
  if (!fixed) {
    // A fixer that died may have left edits or even a commit behind; the next root cause starts clean.
    await agent(
      `A bug bash fixer for ${g.id} stopped without reporting. Leave the repository as it was before it: restore every tracked file that isn't committed (\`git checkout -- .\`), delete the untracked files \`git status --porcelain\` lists outside docs/bugbash/, and revert any commit \`git log --format=%h --grep='(${g.id})' ${plan.sha}..HEAD\` shows (\`git revert --no-edit\`). Report what you did.`,
      { label: `clean up ${g.id}`, phase: 'Fix', model: WORKER, effort: 'low' },
    )
  }
  results.push({ ...g, ...(fixed || { status: 'open', commit: '', check: '', notes: 'the fixer stopped without reporting; its changes were undone' }) })
  log(`${g.id}: ${results[results.length - 1].status}`)
}

// ── Report ──────────────────────────────────────────────────────────────────────────────────────
phase('Report')
const report = await agent(
  `${CONTEXT}

Write ${plan.outDir}/report.md, the bug bash report, following section 5 of skills/check-bugbash/SKILL.md in ${plan.pluginRoot}. The dashboard parses it, so keep these exact shapes:
- "## Scope" first, with the sha ${plan.sha}, the scope, lenses run (${plan.lenses.map(l => l.id).join(', ')}), lenses skipped with their reasons (${plan.skipped.map(s => `${s.id}: ${s.why}`).join('; ') || 'none'}), the personas, and what couldn't be verified and why.
- "## Findings": one table, header "| Id | Lens | Severity | Title | Status | Fix commit | Check added |", one row per root cause, status one of fixed / pending decision / open / story; merged ids named in the title.
- "## Pending decisions": each question with its options and the recommendation.
- "## Discarded": findings the skeptics couldn't reproduce or found correct, one line each with why.
- "## Escapes": by dimension and by class, the checks added, and the comparison with the previous report in docs/bugbash/ and with docs/escapes.md.
- The mutation score of the critical areas if the project has them (pnpm mutation --all), and the final verify and doctor results — run them now.

Root causes and what happened to each:
${JSON.stringify(results, null, 1)}
Pending decisions:
${JSON.stringify(pending, null, 1)}
Discarded:
${JSON.stringify(byId(discarded).map(({ votes, ...f }) => ({ id: f.id, lens: f.lens, title: f.title, why: f.why })), null, 1)}
Coverage:
- ${covered.slice().sort().join('\n- ')}

Write it in the language of docs/context (the project's working language). Commit the report folder as "docs: bug bash ${plan.date}". Don't push.`,
  { label: 'report', phase: 'Report', schema: REPORT },
)

return {
  date: plan.date,
  sha: plan.sha,
  report: report ? report.report : `${plan.outDir}/report.md (not written)`,
  lenses: plan.lenses.map(l => l.id),
  skipped: plan.skipped,
  fixed: results.filter(r => r.status === 'fixed').map(r => ({ id: r.id, severity: r.severity, title: r.title, commit: r.commit, check: r.check })),
  open: results.filter(r => r.status === 'open').map(r => ({ id: r.id, severity: r.severity, title: r.title, notes: r.notes })),
  stories: results.filter(r => r.status === 'story').map(r => ({ id: r.id, severity: r.severity, title: r.title, why: r.why })),
  decisions: pending,
  discarded: discarded.length,
  verify: report ? report.verify : '',
  doctor: report ? report.doctor : '',
  summary: report ? report.summary : '',
}
