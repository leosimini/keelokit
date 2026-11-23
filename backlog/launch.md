# Keelokit launch: drafts

Publish order: 1) the blog post (Medium @leosimini or leopoldosimini.com, under your name) →
2) Show HN linking to the post → 3) Reddit the same day → 4) LinkedIn in Spanish.
awesome-claude-code: submit the form from 2026-10-10.

---

## 1. Blog post (EN)

**Title:** My coding agents kept saying "done". So I stopped letting them grade their own work.

In my experience, agents tend to close stories and leave a trail of bugs behind them, bugs they
neither write down nor mention. The code compiles, the summary sounds confident, and three
stories later you find the edge case nobody tried.

The problem isn't that the model is bad at code. It's that the same agent writes the code, writes
the tests, and decides when it's finished. No human team works that way.

So I built Keelokit, a Claude Code plugin around one rule: **the agent that writes the code can't
close the task.**

- **Tests before code, by someone else.** A verifier agent turns the story's acceptance criteria
  into tests before any code exists. The builder writes code until they pass. It didn't write
  them, and it doesn't decide when it's done.
- **A reviewer and a breaker.** One agent reads the diff cold against the story and the house
  rules. Another tries to break it: two clicks in a row, two requests at once, a user from
  another account, the edge of every limit.
- **Every bug leaves a check.** When a bug gets through, the fix isn't enough: it adds the test,
  lint rule or CI step that would have caught its whole class, and logs it. The same kind of bug
  can't come back quietly.
- **Rules backed by checks.** Every house rule points to something that enforces it. A doctor
  script tells you when a rule has lost its check.
- **From idea to app.** An interview, a PRD, a TypeScript monorepo (API, web, mobile) with CI and
  staging, a backlog in waves, and a live dashboard that shows where the project is without
  reading code.

I ran it on itself: a bug bash on Keelokit's own repo found 50 root causes, and each fix came
with a check for its class.

It's free and MIT. Install it in Claude Code:

```
claude plugin marketplace add leosimini/keelokit
claude plugin install keelokit@keelokit
```

Repo: https://github.com/leosimini/keelokit · Site: https://keelokit.com

I'd love to hear where it breaks for you.

— Leopoldo Simini

---

## 2. Show HN

**Title** (≤80 chars):
`Show HN: Keelokit – a Claude Code plugin where no agent grades its own work`

**URL:** the blog post (or https://github.com/leosimini/keelokit)

**First comment (post it yourself right away):**

> Hi HN, I'm Leo. I build apps with Claude Code, and the thing that kept biting me was agents
> saying "done" on code with bugs they never mentioned. Keelokit splits the job: one agent writes
> tests from the acceptance criteria before the code exists, another writes the code, a reviewer
> reads it cold, and a "breaker" tries to break it (double clicks, concurrent requests, other
> users' data). Every bug that escapes adds a check for its class, so it can't come back.
> It also scaffolds a TypeScript monorepo with CI and a live dashboard. MIT, feedback welcome,
> especially on where it's too heavy.

Tip: post on a weekday between 8:00 and 10:00 ET and stay around to answer for the first 2 hours.

---

## 3. Reddit (r/ClaudeCode, flair "Built with Claude"; r/ClaudeAI in the showcase thread)

**Title:** I stopped letting Claude Code grade its own work. Here's the plugin that came out of it.

**Body:**
In my experience, agents close stories and leave a trail of undocumented bugs. Keelokit is the
fix I ended up with: separate agents write the tests first, review the code and try to break it,
and every escaped bug adds a check so its kind can't return. It also goes from idea to a
TypeScript monorepo with CI, with a dashboard for non-coders.

Free, MIT: https://github.com/leosimini/keelokit (install commands in the README).
What would make you trust an agent's "done"?

---

## 4. LinkedIn (ES)

En mi experiencia, los agentes de código tienden a cerrar historias y dejan un tendal de bugs en
el camino, que no documentan ni explicitan.

Por eso armé Keelokit, un plugin para Claude Code con una regla simple: **el mismo agente que
programa no puede cerrar una tarea sin que otro agente la revise.** Otro agente escribe los tests
antes que el código, otro revisa y otro intenta romperlo. Y cada bug que se escapa deja un control
para que ese tipo de error no vuelva.

Va de la idea a una app TypeScript con CI y un tablero para ver el avance sin leer código. Es
gratis y open source: https://keelokit.com

#ClaudeCode #IA #Startups #DesarrolloDeSoftware
