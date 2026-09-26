# Dimensions — what can break, what catches it

One catalogue for three uses: a story lists the dimensions it touches (`dimensions` in its
front matter), `/keelokit:build` turns each into lines of the story's done-contract, and
`/keelokit:bugbash` runs one lens per dimension. When a bug escapes, the fix adds a check to the
"Automatic" column of its dimension.

| Dimension | The story's contract must include | Automatic (every commit / CI) | Bug-bash lens |
|---|---|---|---|
| `data` | Invariants from `domain.md` as DB constraints or tests; migration; seed personas updated | Migration ↔ schema diff clean; integration tests on real Postgres | Volume seed; `EXPLAIN` hot queries; integrity after failures |
| `api` | Every endpoint × role (incl. a stranger); validation and error bodies | Integration tests; AUTHZ-1 matrix test | curl as owner / member / stranger / anonymous |
| `contract` | Response schema in `packages/shared`; clients parse it | CONTRACT-1 contract tests; typecheck across packages | Old client vs new API; missing/extra fields |
| `logic` | Invariants, state transitions (allowed and forbidden), calculations with rounding, dates and time zones | Unit tests named after the invariant/scenario | Walk each rule in `domain.md` against the running app |
| `auth` | Session lifecycle: login, refresh, expiry, logout clears ALL user state (cache, tokens, push), account switch | Tests for logout/switch; AUTHZ-1 | Shared device: log out A, log in B — does B see anything of A? |
| `ux` | Every screen touched: loading, empty, error, success, no-permission, offline; navigation back/forward; form validation | Component tests per state; E2E-1 journeys | Each persona walks the critical journeys |
| `ui` | Tokens only; 320 / 768 / 1280 widths; light/dark | UI-1 lint; A11Y-1 contrast | Screenshots per viewport × theme |
| `web` | Journeys in Playwright; prod build config | E2E-1 web journeys; build | Crawl, broken links, SEO basics |
| `mobile` | Journeys; offline and resume; permissions prompts | Jest; E2E-1 mobile journeys; `expo export` | Small/large devices; background → foreground |
| `i18n` | Every new string in every locale; plurals; dates/currency via Intl | I18N-1 lint (no JSX literals) + locale parity test | Switch locales; mixed-language screens; `1 items` |
| `copy` | Text follows the project's style guide | Banned-words grep if the project has one | Read every screen and email as the user |
| `a11y` | Labels, roles, focus order, contrast | axe in E2E; contrast test | Screen reader pass on critical journeys |
| `security` | Input validation, authz, secrets, PII in logs | SEC-1..3, SAST-1, AUTHZ-1 | Attacker with a valid account of another tenant |
| `nfr` | Timeouts, rate limits, idempotency, multiple instances (crons, locks), performance budget | Tests for locks/idempotency; perf budget on seeded volume | Load and volume; two instances at once |
| `config` | Every new key in schema, `.env.example`, `.env.ci`, README; prod build fails without required public config | CFG-1 drift test | Build/deploy with a key missing |
| `ops` | Logs with request id, errors to Sentry, health, migration on deploy, rollback | Health tests; deploy job | Deploy dry-run; kill the DB mid-request |
