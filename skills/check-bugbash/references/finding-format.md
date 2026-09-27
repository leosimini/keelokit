# Finding format and severity

## One finding

```markdown
### <LENS>-<n> · <short title> (P<0-3>)
- **Persona / context:** <role, state, locale, viewport, sha>
- **Steps:** 1. … 2. … 3. …
- **Expected:** <behaviour> — source: <docs/context/… § / PRD § / story ID.Sn / style guide>
- **Observed:** <what happened>
- **Evidence:** <screenshot path | request + response | log lines | test output>
- **Where:** <file:line, if known>
- **Root cause (probable):** <one sentence>
- **Class:** <conservation | once | limit | transition | isolation | time | consistency | other>
- **Should have been caught by:** <check type from dimensions.md> — <why it wasn't>
- **Proposed fix:** <smallest change at the cause>
```

Lens prefixes: `DATA`, `API`, `CTR`, `LOG`, `INT`, `AUTH`, `UX`, `UI`, `WEB`, `MOB`, `I18N`,
`CPY`, `A11Y`, `SEC`, `NFR`, `CFG`, `OPS`. An `INT` finding names the invariant it breaks
(`INV-003`) and its class.

## Severity

| | Meaning | Examples |
|---|---|---|
| **P0** | Data loss or leak, money wrong, security hole, production down, a limit passed or a side effect repeated | Another user's data after logout; support form posts to localhost; two bookings for the last seat; a charge sent twice |
| **P1** | A critical journey is broken or blocked for a role | Session dies every 15 minutes; can't complete a booking |
| **P2** | Degraded, with a workaround; wrong but recoverable | Wrong plural; missing empty state; slow at volume |
| **P3** | Cosmetic or polish | Misalignment; inconsistent capitalisation |

Rate by impact on the user and the business, not by effort to fix. When lenses disagree, the
validator decides with this table and says why.
