# docs/context format

Five files. Short sentences, facts with sources, gaps inline as `[GAP-nnn]`.
`pnpm doctor` checks: all five exist, no vague phrases, every inline gap is in `gaps.md`, every
invariant has an `INV-nnn` id and a known class.

## product.md

```markdown
# Product

## Problem
<Who, which problem, how often, what it costs today.> (S1)

## Users
| User | Needs to | Today they use |
|---|---|---|

## Success metrics
| Metric | Target | By | Source |
|---|---|---|---|

## Out of scope for launch
- <exclusion> (S2)

## Business model
<Who pays, how much, when — or "not monetised yet".>

## Markets and languages
<Countries, languages.>

## Sources
| Id | Type | What | Date |
|---|---|---|---|
| S1 | interview | Interview with <owner> | YYYY-MM-DD |
```

## domain.md

```markdown
# Domain

## Glossary
| Term | Meaning here | Don't confuse with |
|---|---|---|

## Entities
### <Entity>
<One-sentence definition.>

## Invariants
Rules that must hold in every case, for every user, even with two requests at once. One line
each: an id that never changes, the rule, its class and its source. The class decides the test
(`references/invariants.md` in the Keelokit plugin): conservation · once · limit · transition ·
isolation · time · consistency.

- [INV-001] [MUST] Charged = refunded + held + fee, for every payment — class: conservation (S1)
- [INV-002] [MUST] A reminder goes out at most once per booking — class: once (S1)
- [INV-003] [MUST] A slot never holds more bookings than its capacity — class: limit (S2)

## States
<Entity>: draft → published → closed. Forbidden: closed → published. (S1)

## Calculations
<Formula or worked example, with rounding and currency.>

## Events
| Event | Triggers |
|---|---|

## Units
Currency: <…> · Time zone: <…> · Units: <…>
```

## constraints.md

```markdown
# Constraints

Each one is binding and has a named consequence if broken.

## Regulatory
- [MUST] <measurable rule> — consequence: <fine / store rejection / contract> (S1)

## Budget
- [MUST NOT] exceed <amount/month> in infrastructure and services. (S1)

## Dates
## Integrations
| Need | Service | Account owner |
|---|---|---|

## Data residency
## Must stay manual
## Platform requirements
```

## environments.md

```markdown
# Environments

| Environment | Purpose | URL | Deployed by | Approver |
|---|---|---|---|---|
| local | development | localhost | developer | — |
| staging | every green main | <url or [GAP-nnn]> | CI | — |
| production | users | <url or [GAP-nnn]> | human, from CI | <name> |

## Supported clients
<Devices, OS versions, browsers.>

## Accounts
| Service | Owner | Used for |
|---|---|---|
<Never credentials — only who owns the account.>
```

## gaps.md

```markdown
# Open gaps

| Id | File | Missing | Owner | Question | Blocking |
|---|---|---|---|---|---|
| GAP-001 | constraints.md | Data protection law for Spain | Product owner | Does the MVP launch in Spain? | yes |
```

Close a gap by writing the answer where the `[GAP-nnn]` marker was and deleting its row.
