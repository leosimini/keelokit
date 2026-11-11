+++
id = "HARN-020"
epic = "HARN"
title = "The guard reads a variable reference as no secret, and a product can register paths SEC-1 and SEC-2 let through"
wave = 4
depends_on = []
touches = ["template/.keelokit/bin/guard.py", ".keelokit/bin/guard.py", "template/.keelokit/bin/doctor.py", ".keelokit/bin/doctor.py", "template/.keelokit/guard-allow.toml", ".keelokit/guard-allow.toml", "copier.yml", "tests/test_guard.py", "tests/test_doctor.py", "tests/test_copier.py", "docs/design.md", "skills/check-health/SKILL.md", "skills/project-adopt/SKILL.md", "skills/harness-upgrade/SKILL.md", "CHANGELOG.md"]
dimensions = ["logic", "security", "dx", "integrity"]
invariants = ["INV-002"]
+++
## Context
An adopted project (Gastos Compartidos) can't hook the guard to its people's commits: the guard reads
`postgresql://user:${DB_PASSWORD}@host/db` (GitHub Actions workflow, `compose.*.yml`) as a password,
and rejects files the repo legitimately has — `apps/mobile/google-services.json` (a Firebase key,
public by design) and `.env` templates with placeholders that deploy guides name — with nowhere to say so.

Decided with the project's coordinator on 2026-11-11:
- A variable reference where a URL's password goes (`${VAR}`, `${{ secrets.X }}`, `$VAR`) is not a
  secret; a literal there, alone or mixed with a reference, still is.
- The product registers paths in `.keelokit/guard-allow.toml` (product-owned, in `_skip_if_exists`
  like `exceptions.toml`): `[[allow]]` with `rule` (SEC-1 or SEC-2), `path` (exact) or `glob`, `reason`,
  `approver`, optional `expires`. Not in `exceptions.toml`: an exception there excepts the *whole* rule
  from the doctor's enforcer check; an allowed path must not.

Does NOT do: exempt anything from QA-4, DB-1 or any other rule; exempt a path in the shell command
check for SEC-1 (a secret in a command line stays blocked); change gitleaks or the template's CI job.

## User story
As a product that adopted Keelokit, I want the guard to tell a variable from a password and to let me
register the few files that are public or placeholders, so that I can hook it to my people's commits.

## Acceptance criteria
```gherkin
Scenario: [S1] A variable reference in a URL's password is not a secret
  Given a database or git URL whose password is `${DB_PASSWORD}`, `${{ secrets.DB_PASSWORD }}` or `$DB_PASSWORD`
  Then the Claude hook and the pre-commit hook let it through

Scenario: [S2] A literal in that place is still a secret
  Given the same URLs with a literal password, or a literal mixed with a reference (`pa${X}ss`, `${X}:real`)
  Then both hooks still block it

Scenario: [S3] A registered path is let through for its rule only
  Given an active entry for SEC-1 (or SEC-2) with a path or a bounded glob
  When a file there holds a key (or is a .env file)
  Then both hooks let it through; the same content at any other path, and the other rule at that path, stay blocked

Scenario: [S4] The registry is narrow
  Given an entry for another rule, with no reason or approver, expired, with two of path/glob, with a path that
  is absolute, has `..`, or a glob with `**`, a wildcard in a directory, no literal directory or no literal in the file name
  Then the guard ignores it and the doctor reports an error

Scenario: [S5] The doctor validates and shows it
  Given the registry
  Then the doctor errors on a path or glob that matches no file, and lists every active entry with its rule, path, reason and approver

Scenario: [S6] A change to the registry needs the human
  When an agent edits or writes the registry with a tool or the shell
  Then the Claude hook blocks it; and a commit that changes it is refused unless `keelokit.allowTamper` is set
  And the pre-commit hook reads the registry as staged, so an unstaged edit exempts nothing

Scenario: [S7] The normal case is as before
  Given an empty or missing registry
  Then a real `.env`, a literal token and a password URL are blocked exactly as before

Scenario: [S8] A project receives the file
  Then copier.yml lists the registry under `_skip_if_exists`, the template ships it commented, and the doctor passes on it
```
The guard still only blocks or lets a call through (INV-002).

## Testable units
| Unit | Test type | File |
|---|---|---|
| password reference vs literal, allow lookup, registry protection | unit | tests/test_guard.py |
| registry validation and listing | unit | tests/test_doctor.py |
| ownership in copier.yml | unit | tests/test_copier.py |

## Definition of done
`scripts/verify.sh` green, every scenario covered by a test titled with its id, `Story: HARN-020`
trailer on the completing commit, addendum if the result differs.
