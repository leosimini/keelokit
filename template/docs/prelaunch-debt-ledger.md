# Pre-launch debt ledger

Every finding from a review, bug bash, security pass or user report goes in one row and ends in one
of two states: **fixed** (with the commit) or **decided** (a recommendation and who decides). There
is no third state: "known issue", "later" and "pending" are not decisions. `python3
.keelokit/bin/doctor.py` rejects a row that reads like one, and `doctor --launch` exits 1 until no
row is `open` and nothing waits on the owner (DEBT-1).

Zero debt before a launch does not mean zero ideas: an improvement nobody needs for the launch is
decided as "not now, because …" with the cost of waiting, and the owner can overrule it.

## Findings

Status is `open`, `fixed` or `decided`. A `decided` row's last cell must say what you recommend.

| Id | Found | Finding | Status | Fix (commit) or decision with recommendation |
|---|---|---|---|---|

## Needs the owner

What only the owner can supply: legal and company data, accounts, tokens, store listings,
approvals. One row each, with what is blocked without it. Status is `needed` or `provided`;
a row stays here (as `provided`) after the owner answers.

| Id | What is needed | Why / what it blocks | Status |
|---|---|---|---|
