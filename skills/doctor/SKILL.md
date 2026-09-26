---
name: doctor
description: Check and repair the health of a Keelokit project's harness — rules without enforcers, enforcers that point nowhere, expired or incomplete exceptions, gaps in docs/context, malformed stories — and add new rules with their checks. Use when the user says "doctor", "chequeá el harness", "¿está todo en orden?", "salud del proyecto", "agregá una regla", "esto no puede volver a pasar", "registrá una excepción", or when `pnpm doctor` / CI's doctor step fails.
---

# Doctor — a rule without a check is a wish

## Run

```bash
python3 .keelokit/bin/doctor.py
```

## Fix by error type

| Error | Fix |
|---|---|
| MUST rule without an enforcer | Add the test, lint rule, hook or CI job that fails when the rule breaks, then list it in `enforced_by`. If nothing can check it, it is a SHOULD — downgrade it and say so. |
| Enforcer does not exist | Fix the path/name, or create the missing check. Never delete the rule to go green. |
| Enforced only by review | Acceptable for SHOULD; for MUST, find a computational check or tell the user it is weak. |
| Exception incomplete or expired | Ask the user: renew (new date, reason, approver) or remove it and comply. Never renew on your own. |
| docs/context missing / vague / untracked gap | Missing → `/keelokit:intake`. Vague → ask for the number or name. Untracked gap → add its row to `gaps.md`. |
| Story errors | Fix front matter, file name, or unknown `depends_on`; remove any `status` field. |

House rules (`.keelokit/harness/`) are inherited: don't edit them in the project. If one is wrong
for everyone, say so — it gets fixed in the Keelokit template and arrives with `copier update`. If
it is wrong only here, register an exception.

## Adding a rule (after an incident or a repeated mistake)

1. State it: `[MUST|MUST NOT|SHOULD] <actor> <verb> <object> <measurable qualifier>`.
2. Write the enforcer first and show it failing on the bad case, passing on the good one.
3. Add the entry to `.keelokit/rules.local.toml`: `id`, `level`, `rule`, `why` (the incident in one
   line), `enforced_by`, and `when` if it only applies when some path exists.
4. Run the doctor; commit rule and enforcer together.
5. If the lesson applies to every product, tell the user it should move to the house rules in
   Keelokit.

## Registering an exception

Only with the user's explicit approval in chat. Add to `.keelokit/exceptions.toml`: `rule`,
`reason`, `approver` (the user's name), `expires` (a date; `permanent` only if the user says so).
