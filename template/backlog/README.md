# Backlog

- `epics.md` — epics in priority order, each with its goal and the stories it groups.
- `stories/<ID>-<slug>.md` — one story per file. `pnpm doctor` validates them.

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
+++
```

Then: Context (with a "does NOT do" list), User story, Acceptance criteria (Gherkin, one
`Scenario: [S1] …` per behaviour), Testable units, Definition of done.

`dimensions` says what the story can break; `/keelokit:build` turns each into lines of its
done-contract. Every scenario of a done story must have a test whose title cites
`<ID>.S<n>` — `pnpm doctor` checks it (TRACE-1). Stories in the same wave must not share
`touches`; doctor checks that too.

No status field: a story is done when a commit on `main` carries the trailer
`Story: AUTH-001` (the last line of the commit message). `pnpm doctor --brief` lists what is
ready next.
