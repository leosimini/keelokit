+++
id = "LEDGER-010"
epic = "LEDGER"
title = "Pre-push and CI: nothing unattributed reaches the trunk"
wave = 15
depends_on = ["LEDGER-009"]
touches = ["template/.githooks/pre-push", ".githooks/pre-push", "template/.keelokit/bin/ledger.py", ".keelokit/bin/ledger.py", "template/.github/workflows/ci.yml.jinja", ".github/workflows/ci.yml", "tests/test_ledger.py", "tests/test_verify.py", "tests/test_ci.py", "CHANGELOG.md"]
dimensions = ["logic", "integrity", "ops"]
invariants = ["INV-005", "INV-007"]
origin = "docs/ledger.md — Mechanisms (pre-push and CI); JOUNA's squashed trains"
+++
## Context
A local hook can be skipped (`--no-verify`, a machine without hooks, a swarm helper without the plugin),
so the guarantee lives where work enters the trunk: the pre-push and, behind it, the CI.

`ledger.py prepush` reads git's pre-push lines; for a push to the trunk it runs before the verify (it is
the fast part) and checks the new commits that are not merges:
- each is attributed, or a merge commit of the same push that brings it carries `Story:`, `Part-of:` or
  `No-story:` (a branch from elsewhere without trailers is attributed by the merge that integrates it);
- a commit whose tree equals the tip of an unintegrated origin branch is a squash of it, and must carry
  every `Story:` and `Part-of:` of that branch (`SQUASH_LOST_TRAILERS`). This is the case of JOUNA's
  trains, which entered `main` squashed and lost their stories.

`ledger.py check --ci` does the same in CI: on a pull request over its commits, on a push to the trunk over
the trunk since `[ledger] since`. For each unattributed commit it prints the exact `ledger.py correct`
command. The step goes in the job that already runs the doctor with `fetch-depth: 0`. All three follow
`enforce`: with `warn` they print, with `block` they fail.

**Decided:** INV-007 (docs/ledger.md, "Decisions", 2), already in `docs/context/domain.md`.

Does NOT do: write the snapshot (LEDGER-011); check pushes to branches that are not the trunk.

## User story
As the person responsible for a project, I want nothing unattributed to reach the trunk, whatever machine
or account pushed it, so that the ledger's history is complete.

## Acceptance criteria
```gherkin
Scenario: [S1] An unattributed commit pushed to the trunk
  Then with enforce = "block" the push is refused with UNATTRIBUTED and the commit's hash
  And with enforce = "warn" it goes through and the same text is printed

Scenario: [S2] A merge attributes what it brings
  Given a branch from elsewhere with two commits without trailers
  When it is merged with a merge commit carrying `Part-of: AUTH-005` and pushed
  Then the push goes through

Scenario: [S3] A squash that loses a story
  Given an origin branch with `Part-of: AUTH-006` and `Story: AUTH-007` commits
  And a commit on the trunk with the same tree that carries only `Story: AUTH-007`
  Then SQUASH_LOST_TRAILERS names AUTH-006

Scenario: [S4] A squash that keeps everything
  Given the same squash carrying both trailers
  Then it goes through

Scenario: [S5] CI on the trunk
  Given an unattributed commit on the trunk after `since`
  Then with block the CI step fails and prints the `ledger.py correct` command for that commit

Scenario: [S6] Other branches
  Then a push to a branch that is not the trunk is not checked
```

## Testable units
| Unit | Test type | File |
|---|---|---|
| prepush: attribution, merge coverage, squash detection | unit, local remote | tests/test_ledger.py |
| the pre-push order (attribution before verify) | unit | tests/test_verify.py |
| the CI step exists, with fetch-depth 0 | unit | tests/test_ci.py |

## Definition of done
`scripts/verify.sh` green, every scenario covered by a test titled with its id, INV-005 cited, this repo's
own pre-push and CI get the same step, a CHANGELOG line, `Story: LEDGER-010` trailer, addendum if the
result differs.

## Addendum — 2026-11-24

Where the result goes beyond or differs from the text above:
- **A squash is found two ways.** By tree, as written (the commit's tree is the tip of an unintegrated origin
  branch): an error under block. And, since a train usually lands after the trunk moved, by the patch-id of the
  branch's change since its merge base with the trunk (ESC-200): only a warning with no correction command, since
  the same change made twice (a pin bump on a branch and in a CVE fix) is no proof of a squash (ESC-240); the
  pre-push refuses only on an error. Never from a commit the branch itself reaches, nor from a branch whose
  tip has its base's tree, i.e. one that changes nothing (ESC-199), nor from a branch of fewer than two commits of
  its own: a copy of one commit is a cherry-pick, and the same small change or revert is often made on the trunk
  too (ESC-202, ESC-203). So a one-commit branch squashed on the trunk is not caught. Only branches with a
  `Story:`/`Part-of:` of their own are read, and a patch only for a range commit that changes exactly the branch's
  paths (ESC-204); a branch costs git calls of its own only when its tip's tree, or a range commit's paths within
  the paths it touches, match (ESC-245). Never from a branch under the unverified prefixes (`[verify] wip_branches`, `wip/` when unset,
  and `archive/`), whose work never lands as it is (ESC-241). A tree match does not count when the trunk already
  had that tree since the branch forked: a revert back to it (ESC-207). A branch's `Story:` must stay a `Story:` (a `Part-of:` would take the story off the trunk); its
  `Part-of:` is kept by either. What the squash keeps counts on it and on every trunk commit since the branch
  forked (the fork of its own oldest commits, not its merge base, which a sync merge of main moves: ESC-243,
  ESC-244), in the checked range or not, so the pre-push and `check` agree on the same history: a rebase merge, a
  fix cherry-picked earlier, a branch stacked on one already squashed, a reapplied squash (ESC-238, ESC-239,
  ESC-242). A trunk commit before the fork does not count.
- **Approved correction rows attribute the commit they name**, in `check`, in the summary's unattributed count
  and in the pre-push (ESC-201), which reads them from the trunk the remote or origin already has, never from the
  pushed tip (ESC-205). Without it, the `ledger.py correct` command the CI prints could never turn the
  CI green again. A correction row naming a squash keeps the story it names.
- **A merge attributes what it brings wherever it sits.** A merge with a trailer nested in a branch (brought by
  GitHub's trailerless "Merge pull request") covers the commits it brings, as docs/ledger.md's "Trailers" says;
  before, only the first-parent merge that brought a commit counted.
- **The pull request check.** `check --ci` on a `pull_request` run into the trunk (`GITHUB_EVENT_NAME`,
  `GITHUB_BASE_REF`) also checks the commits the checked-out `refs/pull/N/merge` reaches and the trunk does not;
  GitHub's merge commit stands for the one to come. A pull request into another branch is not checked (S6).
  GitHub's default shallow checkout fails the step (no trunk, a cut history), never passes it.
- **The fix hint.** On the trunk, the exact `ledger.py correct <sha> --story <ID> --evidence "…"`; for a commit
  not on the trunk yet (pre-push, pull request), how to reword it or bring it with an attributed merge.
- **The pre-push** checks the commits the remote it pushes to lacks (its sha and its remote-tracking trunk; not
  origin's when the push goes elsewhere). Without a `since` nothing is checked, as in `check`. A shallow clone
  cut before `since` checks what the remote lacks, and fails when nothing bounds it (ESC-198). When `ledger.py` is
  missing or cannot run (exit 2) the hook says so in one line and goes on to the verify: the CI, which fails
  closed, checks the same. This repo's own `.githooks/pre-push`, which runs `scripts/verify.sh` and has none of the
  template's verify logic, got the same block before its verify.
- **Not caught (no git-side fix):** a squash made on GitHub's server ("Squash and merge") whose head branch is
  deleted before the push-to-main CI checks out (GitHub's "automatically delete head branches"): no origin branch
  is left to compare with, and the pre-push never sees a server-side merge. A project that squashes on GitHub keeps
  the branch until the CI ran, or writes every trailer of the branch in the squash message's last paragraph.
- **Invariants.** INV-007 is enforced where work enters the trunk (pre-push, then CI); INV-005 by refusing a
  squash that drops a `Story:`. Review and attack: reviewer round 1 (non-blocking, fixed), breaker round 1
  (ESC-198..ESC-201) and round 2 (ESC-202..ESC-205), each with its test; the fixture fix ESC-206 came from the
  PR's own CI. The coordinator's review of #30 ran another breaker pass on the squash check and found false
  positives (ESC-207, ESC-238..ESC-242), each with its test; a last breaker pass on the squash check found two
  more after a sync merge and a cost per open branch (ESC-243..ESC-245), each with its test.
