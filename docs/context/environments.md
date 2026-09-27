# Environments

Keelokit isn't hosted. It reaches users through these channels:

| Environment | Purpose | URL | Deployed by | Approver |
|---|---|---|---|---|
| main | Keelokit's own marketplace (`claude plugin marketplace add leosimini/keelokit`) | github.com/leosimini/keelokit | push to main | — |
| release | the Claude plugin directory, which scans and publishes it | claude.ai/directory | `scripts/release.sh` | Leo |
| GitHub Releases | release notes, the tag the skills fetch the template from | github.com/leosimini/keelokit/releases | Release workflow | — |
| keelokit.com | the site (another repo, `leosimini/keelokit.com`, Vercel) | keelokit.com | push to its main | Leo |

## Accounts
| Service | Owner | Used for |
|---|---|---|
| GitHub | Leo | code, CI, releases |
| Claude plugin directory | Leo | publishing |
| Vercel | Leo | keelokit.com |
