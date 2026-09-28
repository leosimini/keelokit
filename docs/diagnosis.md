# Diagnosis — 2026-09-28

What Keelokit's code verifiably does today, the debt behind its one exception, and the risks the
first bug bash (2026-09-27, `docs/bugbash/2026-09-27/`) left for decision.

## What it is
A Claude Code plugin — 14 skills (`skills/`), 4 agents (`agents/`), one workflow (`workflows/`),
two hooks (`hooks/hooks.json`) — and the Copier template it generates projects from (`template/`,
`copier.yml`). Its own code is Python 3.11 stdlib: the guard and the doctor
(`template/.keelokit/bin/`, copied into this repo's `.keelokit/bin/`) and the dashboard
(`skills/project-dashboard/scripts/dashboard.py`). CI runs the unit tests, the manifests, the
template end to end for five app mixes and an upgrade from the last release, the secret scan,
Semgrep and the doctor (`.github/workflows/ci.yml`).

## The exception
- **MUT-1** until 2027-01-31: no mutation testing of Keelokit's own Python. Story HARN-001.

## What the bug bash left
- 42 root causes confirmed; the ones fixed each have a test and a check for their class
  (`docs/escapes.md`). What wasn't fixed is in the bug bash's report with its status.
- One story-sized finding became HARN-002 (LOG-209).
- 17 decisions wait for Leo. The ones that weigh most:
  - **SEC-3** — the plugin's hooks run the opened repository's own `.keelokit/bin/guard.py` and
    `doctor.py` on every session and tool call, so opening an untrusted repo runs its code.
  - **SEC-1 / SEC-2** — how far the guard's secret and `.env` checks should go; the README
    already calls it a speed bump, not a sandbox.
  - **SEC-6** — the dashboard's private Artifact URL is in `.keelokit/state.toml`, public in this
    repo's history.

## Risks
- The guard and the doctor are the code agents obey; until HARN-001 there's no measure of how
  well their tests catch a broken condition.
- GAP-001 (the guard vs this repo's own test fixtures) is decided and is HARN-003.
