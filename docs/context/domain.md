# Domain

## Glossary
| Term | Meaning here | Don't confuse with |
|---|---|---|
| Harness | The rules, checks, guard and doctor a project runs under (`.keelokit/`) | The plugin (skills and agents) |
| Template | `template/` + `copier.yml`: what `project-new` generates and `harness-upgrade` merges | The plugin's own code |
| Gate | A human approval recorded in `.keelokit/state.toml` | A CI check |
| Profile | `.keelokit/profile.toml`: what a project is and which rules apply to it | The house stack |

## Invariants
- [INV-001] [MUST] A release tag `vX.Y.Z` points at a commit of `main` whose `plugin.json` says `X.Y.Z` and whose CHANGELOG has its entry — class: consistency (S3)
- [INV-002] [MUST] The guard only blocks or lets a call through; it never approves one — class: consistency (S3)
- [INV-003] [MUST] `harness-upgrade` never rewrites a product-owned file (`_skip_if_exists` in copier.yml) — class: isolation (S2)
- [INV-004] [MUST] `project-adopt` writes only inside `.keelokit/` until the user says yes to a code change — class: isolation (S2)
- [INV-005] [MUST] A story is done if and only if a commit reachable from `main` carries its `Story:` trailer — class: consistency (S2)
- [INV-006] [MUST] `doctor --ci` exits non-zero whenever it reports an error — class: consistency (S4)

## Events
| Event | Triggers |
|---|---|
| Push to `main` | CI: unit tests, manifests, template generation and upgrade |
| Push to `release` | Release workflow: tag and GitHub Release; the plugin directory scans it |
