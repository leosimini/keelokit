# Constraints

## Distribution
- [MUST] Pass `claude plugin validate --strict` on every release — consequence: the plugin directory rejects it. (S3)
- [MUST NOT] Collect data or call a Keelokit server; network traffic is only the user's own tools — consequence: the README's "Data and network" promise breaks. (S1)
- [MUST] Every new plugin-directory scan finding gets a real fix or a line in the submission notes — consequence: the release is held. (S3)

## Platforms
- [MUST] Run on macOS and Linux with Node 22, pnpm 10, Python 3.11+, uv, Docker and git — consequence: the documented requirements lie. (S1)

## Budget
- [MUST NOT] Need paid services to use or maintain it. (S1)
