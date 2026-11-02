+++
id = "HARN-009"
epic = "HARN"
title = "The pre-push hook verifies the commits it pushes, not only HEAD"
wave = 8
depends_on = ["HARN-008"]
touches = ["template/.githooks/pre-push", "template/docs/verify.md", "tests/test_verify_operativo.py", "CHANGELOG.md"]
dimensions = ["security", "dx"]
origin = "review:2026-11-02"
+++
## Context
The template's pre-push hook ran `pnpm verify --use-seal`, which checks the checked-out commit and its
working tree. Git pushes whatever refs it is given, so with a green (or sealed) HEAD,
`git push origin <red sha>:main` or pushing another branch reached the remote without that commit ever
being verified. A cold review of the 0.11.1 fixes found it; it predates them.

Does NOT do: verify a non-HEAD commit in a temporary worktree. A fresh worktree has no
`node_modules`, build outputs, `.env` files or database, so its verify would be an install plus a
full run that goes red for reasons the commit doesn't have, inside a push, for a commit nobody is
looking at. Refusing costs one `git switch`, and the seal still skips a commit that already passed.

## User story
As whoever pushes, I want the pre-push hook to verify every commit it pushes, or refuse it, so that
nothing reaches the remote without a verify of that exact commit.

## Acceptance criteria
```gherkin
Scenario: [S1] A commit other than HEAD is refused
  Given a green, sealed HEAD and a red commit on another branch
  When git push origin <red sha>:main, red:main, red, or HEAD:main together with red
  Then the push is refused before any verify, says "check it out and push from there", and the remote is unchanged

Scenario: [S2] A push of HEAD runs the verify as before
  Given a sealed HEAD
  When git push origin HEAD:main, or a tag on HEAD
  Then pnpm verify --use-seal runs (the seal skips the repeat); a checked-out red commit is stopped by its verify

Scenario: [S3] A deletion pushes nothing to verify
  Given a push that only deletes a remote branch
  When git push origin :branch
  Then no verify runs and the branch is deleted
```

## Testable units
| Unit | Test type | File |
|---|---|---|
| .githooks/pre-push | integration (real pushes to a bare origin, real verify.sh, stub pnpm) | tests/test_verify_operativo.py |

## Definition of done
`scripts/verify.sh` green, every scenario covered by a test named `test_HARN_009_S<n>_…`,
`docs/verify.md` updated, `Story:` trailer on the completing commit.
