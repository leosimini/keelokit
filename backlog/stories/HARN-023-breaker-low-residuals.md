+++
id = "HARN-023"
epic = "HARN"
title = "HARN-022's low residuals: a Decision after a squash, and str.splitlines on trailers and story bodies"
wave = 27
depends_on = ["HARN-022"]
touches = ["template/.keelokit/bin/ledger.py", ".keelokit/bin/ledger.py", "tests/test_breaker.py", "tests/test_ledger_swarm.py", "tests/test_ledger.py", "docs/ledger.md", "docs/escapes.md", "CHANGELOG.md", "backlog/stories/HARN-023-breaker-low-residuals.md"]
dimensions = ["logic", "dx"]
invariants = []
risky = true
+++
## Context
HARN-022's cold breaker rounds 6 and 7 left LOW findings, which the coordinator asked to keep out of HARN-022 (2026-11-28):

- A person's `Decision` after a squash landing (the remedy `BREAKER_UNRESOLVED` offers) turns the squash's warnings
  into `BREAKER_STALE`: the decided round's head names no commit here, so it reaches nothing. Probe:
  /tmp/breaker7-HARN-022/probe_squash_decision.py (round 7).
- `parse_trailers` splits git's `%(trailers:only,unfold)` with `str.splitlines`, so a trailer value holding U+2028
  forges a second trailer git does not see (a `Swarm-Task`, a `Dropped`, a `Convoy`, a No-story category); show lists
  a forged swarm task. `breaker_record` splits the story body the same way. Probe:
  /tmp/breaker7-HARN-022/probe_trailer_sep.py (round 7).
- `show` prints a story's title without the line screen: a newline in the title forges a line of the card (a fake
  `state:` line). `next` already keeps it on one line. Probe: /tmp/breaker8-HARN-022/probes/p4_title_newline.py
  (round 8).
- The per-path 3-way check of a merge's own risky change (ESC-389) costs a `cat-file`, a `merge-file`, a
  `hash-object` and a temp directory per risky path that differs from both parents, per merge, on every check over the
  whole history: one clean sync merge of 600 risky files edited on both sides took 5.0 s (0.2 s before), 2000 took
  15.5 s. Probe: /tmp/breaker11-HARN-022/probes/p5_perf.py (round 11).
- `raw_pair_states` (like `pair_diffs`) tries every header for each entry, entries times headers, though the headers
  come in input order: 4000 merges take 10.5 s on synthetic output. Probe:
  /tmp/breaker12-HARN-022/probes/p3_pair_parse_cost.py (round 12).
- The risky rule matches paths, not what is on disk: a `No-story` directory symlink `apps/api/migrations ->
  ../../sql` and a later `No-story` write to `sql/0001.sql` change a migration with no RISKY_* (older than HARN-022).
  Probe: /tmp/breaker12-HARN-022/probes/p2_symlink_dir.py (round 12).
- A risky-to-risky rename across a sync merge gives a false `BREAKER_STALE` (main renamed the file the branch
  edited, or the other way round); accepted in HARN-022 as a fail-closed limitation and pinned by
  `test_HARN_022_S1_breaker12_a_sync_merge_across_a_risky_rename_is_stale_accepted_fail_closed`. A fix must not depend
  on rename detection. Probe: /tmp/breaker12-HARN-022/probes/p1_rename_sync_fp.py (round 12).
- `release_only` exempts a `No-story: release` commit whose paths all end in `/package.json`, wherever they sit, so
  `db/migrations/package.json` or `.keelokit/bin/package.json` inside a risky glob lands with no RISKY_NO_STORY
  (older than HARN-022, from HARN-021). Probe: /tmp/breaker13-HARN-022/probes/p3_release_package_json.py (round 13).
- On a case-insensitive filesystem a committed `.GITATTRIBUTES` steers git like `.gitattributes`, but the always-risky
  `**/.gitattributes` pathspec is case-sensitive (round 16, not reproduced on ext4).
- `glob_regex` misreads POSIX classes (`[[:alpha:]]`), which touches may use; story risk by touches only (round 16).

Does NOT do: anything HARN-022's open HIGH and MEDIUM findings need (they are HARN-022's, by the coordinator's call).

## User story
As the person who decides at the cap, I want my Decision to resolve a squash-landed story and no line separator to
forge a trailer, so that the remedy the ledger offers works and what git reads is what the ledger reads.

## Acceptance criteria
```gherkin
Scenario: [S1] A Decision after a squash landing resolves it
  Given a risky story whose rounds were recorded on a branch that was squash-landed
  When a decider's Decision line follows its last round
  Then check reports no BREAKER_STALE for it (the BAD_ENTRY warning stays)

Scenario: [S2] Line separators never forge a trailer
  Given a commit whose trailer value holds U+2028, U+2029 or U+0085
  Then the ledger reads exactly the trailers git reads, and a story body is split at newlines only

Scenario: [S3] A story title never forges a line of the card
  Given a story whose title holds a newline
  Then `show` prints it on one line, as `next` does
```

## Testable units
| Unit | Test type | File |
|---|---|---|
| a Decision after a squash | integration (real git) | tests/test_breaker.py |
| trailers and story bodies split at newlines only | integration (real git) | tests/test_ledger_swarm.py |
| the title on one line | integration (real git) | tests/test_ledger.py |

## Definition of done
`scripts/verify.sh` green, every scenario covered by a test titled with its id, the two ledger.py copies identical,
`Story: HARN-023` on the completing commit, its breaker rounds recorded below.
