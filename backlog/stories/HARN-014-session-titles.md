+++
id = "HARN-014"
epic = "HARN"
title = "Every session has a canonical title"
wave = 13
depends_on = ["HARN-013"]
touches = ["template/.keelokit/bin/status.py", "template/.keelokit/harness/agent-brief.md", "skills/build-story/SKILL.md", "skills/coordinate/SKILL.md", "docs/design.md", "tests/test_session_titles.py"]
dimensions = ["dx"]
origin = "harbor:2026-11-02"
+++
## Context
Sessions of one project run on several machines and accounts, and Harbor lists and starts them: each was named by hand, or not at all. One title per story, from the project's own files, lets anyone (and Harbor) tell them apart.

Does NOT do: rename branches (they stay the id in lowercase) or rename sessions by itself (the tools that start them do).

## User story
As whoever runs several sessions of a project, I want each one titled the same way everywhere, so that I can tell at a glance which story and wave it is.

## Acceptance criteria
```gherkin
Scenario: [S1] A story title in English without a dashboard language
  Given a story with a wave and no [dashboard] lang
  When status.py title <ID>
  Then `<project> · wave <n> · <ID>`

Scenario: [S2] A story title in Spanish
  Given [dashboard] lang = es (or es-AR)
  When status.py title <ID>
  Then `<project> · ola <n> · <ID>`

Scenario: [S3] The coordinator title
  Given any project
  When status.py title --role coordinator
  Then `<project> · coordinator` (coordinador in Spanish); another role is exit 2

Scenario: [S4] An unknown id is exit 2 with the reason
  Given no story with that id
  When status.py title <ID>
  Then exit 2, the reason on stderr, nothing on stdout

Scenario: [S5] A story without a wave is exit 2 with the reason
  Given a story whose front matter has no whole-number wave
  When status.py title <ID>
  Then exit 2 naming the story file

Scenario: [S6] The project name as copier writes it
  Given answers.yml with a Unicode, quoted or folded project_name, or none
  When status.py title
  Then the name as typed; none is exit 2
```

## Testable units
| Unit | Test type | File |
|---|---|---|
| status.py title | unit (fixture project) | tests/test_session_titles.py |

## Definition of done
`scripts/verify.sh` green, every scenario covered by a test named `test_HARN_014_S<n>_…`,
`Story:` trailer on the completing commit.
