+++
id = "LEDGER-013"
epic = "LEDGER"
title = "The ledger reads Harbor's logbook"
wave = 18
depends_on = ["LEDGER-012"]
touches = ["template/.keelokit/bin/ledger.py", ".keelokit/bin/ledger.py", "tests/test_ledger_harbor.py", "tests/test_ledger.py", "scripts/unit_shard.py", "docs/design.md", "docs/ledger.md", "CHANGELOG.md", "backlog/stories/LEDGER-013-ledger-reads-harbor.md"]
dimensions = ["logic", "integrity", "dx"]
invariants = ["INV-005"]
origin = "docs/ledger.md — Harbor and Swarm; Harbor's plan docs/ledger-phase6.md (HRB-2)"
+++
## Context
Harbor keeps what is under way in its logbook, the orphan branch `harbor/log` (TOML with a fixed schema,
written only by `harbor.py`). The ledger reads it, never writes it:

- a vessel sealed on its exact head in an open convoy (`harbor/convoys/<n>.toml`, `[[vessels]]`) →
  `delivered`, with its convoy and the convoy's state;
- an active worker with a `story` (`harbor/workers/…`, the key HRB-2 adds) → `in-progress`;
- a sailed convoy → the convoy of an `on-trunk` story (also from the `Convoy:` trailer HRB-1 adds), and
  `harbor/main.toml`'s moves give the exact arrival time;
- `show` adds the convoy's events.

`take`, when the project adopted Harbor (`git config harbor.py` set) and `harbor.py story take` exists,
calls it, so taking a story is a real lock (`STORY_TAKEN` reaches the session). Without Harbor, or with a
Harbor older than 0.6.0, nothing changes.

Blocked by HRB-2 (Harbor 0.6.0).

Does NOT do: write the logbook; fetch it (Harbor's hooks already do).

## User story
As a session in a project with Harbor, I want the ledger to include what Harbor knows, so that one command
tells me whether a story is delivered, in which convoy, and exactly when it reached the trunk.

## Acceptance criteria
```gherkin
Scenario: [S1] A sealed vessel in an open convoy
  Given a logbook with convoy 8 assembling and a vessel for AUTH-001 sealed on its head
  Then AUTH-001 is delivered, convoy 8

Scenario: [S2] A sailed convoy
  Given convoy 8 sailed and its merge commit carries `Convoy: 8`
  Then AUTH-001 is on-trunk with convoy 8 and the exact time from harbor/main.toml

Scenario: [S3] take with Harbor
  Given another active worker holds AUTH-002 in the logbook
  Then `ledger.py take AUTH-002` exits 1 with STORY_TAKEN naming that worker

Scenario: [S4] Without a logbook
  Given no harbor/log
  Then every state is as before LEDGER-013

Scenario: [S5] attribution of a range (Harbor's convoy add, HRB-1)
  Given a vessel branch with an own trailer, a commit without one, a No-story:, a clean merge, a merge bringing
    an unattributed commit and a merge with its own trailer
  Then `ledger.py attribution <a>..<b> --json` exits 0 with schema 1, the commits in `git rev-list --reverse`
    order, each attributed exactly as `check` attributes it (via own, merge, correction or null), `unattributed`,
    `ok` and the sorted `stories`; a usage error or an end that does not resolve exits 2, a cut history 3

Scenario: [S6] show --json (Harbor's STORY_ON_TRUNK, HRB-2)
  Given AUTH-001 on the trunk through convoy 8
  Then `ledger.py show AUTH-001 --json` is schema 1 with the record (id, state, version, convoy, delivered) and
    the why as data; an id that is no story exits 1 with `error` and no state

Scenario: [S7] take and take --clear with Harbor
  Given `git config harbor.py` names a harbor.py that has `story take`
  Then `take` runs `harbor.py story take <ID>` and sets the story only when it exits 0; STORY_ON_TRUNK is one
    line and exit 1; an environment failure or no answer is exit 2 with nothing set; an unregistered session
    takes; `take --clear` runs `story release`; a harbor.py without `story take`, or none, changes nothing

Scenario: [S8] Hostile logbook content and harbor.py output
  Given malformed, oversized, mistyped or unreadable logbook files, and a harbor.py that prints a take and exits 1
  Then the ledger never crashes, no logbook content changes a difference or raises a story it should not, a
    refusal is never a take, and no hook's path (summary, --json, history, check, show, attribution, the git
    hooks, the plugin's --root run) runs harbor.py

Scenario: [S9] check --json keeps its schema (Harbor's HRB-3)
  Then `ledger.py check --json` is {"schema": 1, "diffs": [{level, code, detail}]}, exit 1 iff an error

Scenario: [S10] check --rules-ref (Harbor's ok judges a convoy as landed)
  Given main's tip M marks apps/api/pay critical and a convoy commit relaxes critical.toml and adds a delegated
    correction row for a story under it
  Then `ledger.py check --json --rules-ref M` judges that row by M's rules (CORRECTION_INVALID, exit 1), while the
    convoy's own rules would pass it; the same rules give the same verdict; a rev that is no commit is exit 2
```

## Testable units
| Unit | Test type | File |
|---|---|---|
| reading convoys, vessels, workers and moves from a test logbook; take delegating to a stub harbor.py; attribution; show --json; hostile input | unit | tests/test_ledger_harbor.py |

## Definition of done
`scripts/verify.sh` green, every scenario covered by a test titled with its id, INV-005 cited, a CHANGELOG
line, `Story: LEDGER-013` trailer, addendum if the result differs.

## Cold breaker
Each round is a fresh subagent given only the repo, the PR diff and the invariants (attribution equals `check`'s,
hostile logbook or harbor.py output can't crash, run code from a hook's path or change a verdict, take never claims
success when Harbor refused, and from round 1's second half `--rules-ref`); findings are reproduced, each fixed with
a failing test first.

- **Round 1** (9c678ae, then c478797 for `--rules-ref`). Invariants 1–5: none reproduced (90 random DAGs compared
  `attribution` with `check --ci` on a pull request and `check` on the trunk; hostile logbook and harbor.py output).
  Two findings on `--rules-ref`, both fixed with tests named `..._breaker1_...`: (1) a convoy could narrow its story
  file's `touches`/`dimensions` and so un-critical its own delegated correction row, since the story was read from
  the convoy's tree; now the stories that decide the critical flag are `<rev>`'s. (2) `[ledger]` (`enforce`,
  `since`, `no_story`, `stories`) came from the checked-out `state.toml`, so a convoy setting `enforce = "warn"`
  passed; now the whole committed `state.toml` is `<rev>`'s.

