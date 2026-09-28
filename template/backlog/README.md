# Backlog

- `epics.md` — epics in priority order, each with its goal and the stories it groups.
- `stories/<ID>-<slug>.md` — one story per file. `pnpm run doctor` validates them.

Story front matter is TOML between `+++` lines:

```
+++
id = "AUTH-001"            # EPIC-NNN, unique, also the file-name prefix
epic = "AUTH"
title = "Sign up with email"
wave = 1                   # stories in the same wave never touch the same files
depends_on = []            # story ids that must be done first
touches = ["apps/api/src/auth/", "apps/mobile/src/screens/SignUp.tsx"]
dimensions = ["api", "contract", "auth", "data", "ux", "ui", "i18n", "a11y", "mobile"]
invariants = []            # INV-nnn from docs/context/domain.md; any → add "integrity"
# origin = "bugbash:2026-10-03 UX-4"   # optional: where the story came from
+++
```

Then: Context (with a "does NOT do" list), User story, Acceptance criteria (Gherkin, one
`Scenario: [S1] …` per behaviour), Testable units, Definition of done.

`dimensions` says what the story can break; `/keelokit:build-story` turns each into lines of its
done-contract. Every scenario of a done story must have a test whose title cites
`<ID>.S<n>` — `pnpm run doctor` checks it (TRACE-1) — and every invariant it keeps must have a test
whose title cites `INV-nnn` (INV-1). Stories in the same wave must not share `touches` or a
critical area (`.keelokit/critical.toml`), and a story that touches a critical area declares
`integrity`; doctor checks all of that too.

No status field: a story is done when a commit on `main` carries the trailer
`Story: AUTH-001` (the last line of the commit message). `pnpm run doctor --brief` lists what is
ready next.
