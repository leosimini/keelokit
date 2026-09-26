# Question bank (product only)

Ask in the user's language, in your own words. **B** = blocking: unanswered → `Blocking: yes` gap.

## P — Product → product.md

| Id | Question | Accept only if | B |
|---|---|---|---|
| P01 | What problem does it solve, and who has it? Tell me about the last time someone suffered it. | Named user + concrete situation | B |
| P02 | What kinds of users are there, and what does each need to do? | Role + job, per role | B |
| P03 | What do they use today instead, and why isn't it enough? | Named alternative + failure | |
| P04 | How will we know it worked? A number and a date. | Metric + target + date | B |
| P05 | What is explicitly out of the launch? | At least 3 exclusions | B |
| P06 | How does money come in (who pays, how much, when)? | Payer + model, or "not monetised yet" | |
| P07 | Which countries and languages does it launch in? | Countries + languages | |
| P08 | What would make a user abandon the product? | Concrete scenario | |

## D — Domain → domain.md

| Id | Question | Accept only if | B |
|---|---|---|---|
| D01 | Name the 5–15 main things of the business and define each in one sentence. | Entity + definition | B |
| D02 | Which words do you use with a meaning different from the usual one? | Term + meaning | |
| D03 | Which business rule must never break? | Testable invariant | B |
| D04 | Which states does the main entity go through? Which transition is forbidden? | States + forbidden transitions | |
| D05 | Are there critical calculations (prices, fees, quotas)? Exactly how are they computed? | Formula or worked example | |
| D06 | Which events trigger work (a booking, a payment, a date)? | Event + reaction | |
| D07 | Which currencies, units and time zones apply? | Explicit values | |

## C — Constraints → constraints.md

| Id | Question | Accept only if | B |
|---|---|---|---|
| C01 | Which regulations apply (personal data, payments, minors, health, consumer law)? | Named law per country, or "none" confirmed | B |
| C02 | What is the monthly ceiling for infrastructure and services? | Amount + currency | |
| C03 | Are there dates that can't move? Why? | Date + driver | |
| C04 | Which external services must it integrate with (payments, maps, email, login)? | Named service per need | B |
| C05 | Must the data stay in a given country or region? | Region, or "no restriction" | |
| C06 | What must stay manual or go through a person? | Named step | |
| C07 | Store or platform requirements (App Store, Google Play, accessibility)? | Named requirement | |

## E — Environments → environments.md

| Id | Question | Accept only if | B |
|---|---|---|---|
| E01 | Environments: local, staging, production (house default). Any other, or different? | Confirmed list | |
| E02 | Which domains or URLs will it use? | Domain names, or gap | |
| E03 | Which devices and browsers are supported? | Explicit matrix | |
| E04 | Who approves a production deploy? | Named person | |
| E05 | Who owns each account (hosting, app stores, payments, email)? | Owner per account | |

## Adaptive rules

- No mobile app → skip C07 (stores) and the device part of E03.
- No money flows → P06 = "not monetised yet"; skip D05 if nothing is calculated.
- Existing repo → confirm what it shows (stack, entities in the schema, environments in CI)
  instead of asking cold.
- Always ask the blocking questions; everything else can wait as a non-blocking gap.
