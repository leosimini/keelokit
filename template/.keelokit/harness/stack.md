# House stack

The stack Keelokit generates, and why. It is one person's preference for building products, not a
recommendation for every team. A project that needs something else records the deviation in
`docs/decisions/` and keeps going.

| Layer | Choice | Why |
|---|---|---|
| Monorepo | pnpm workspaces (`apps/*`, `packages/*`) | One install, one lockfile, shared packages without publishing. No Turbo/Nx until build times hurt. |
| Language | TypeScript strict everywhere, Node 22 LTS | Types are the cheapest test an agent can't forget to run. |
| API | NestJS + Prisma + PostgreSQL (PostGIS when geo is needed) | Modules map well to domains; Prisma migrations are plain SQL you can read. |
| Web app / backoffice | Vite + React | A fast SPA on the same API and shared contracts. |
| Mobile | Expo (managed) + React Navigation, EAS builds | One codebase for iOS/Android; the Expo web build doubles as the E2E target. |
| Public sites | Astro | Static landing and docs, same tokens as the apps. |
| Shared code | `packages/shared` (zod contracts, i18n, pure rules), `packages/ui-tokens` | One source for what crosses the wire and for the look. |
| Tests | Vitest (API, web, packages), Jest (mobile), integration on real PostgreSQL, Playwright + axe for journeys (web, and mobile via Expo web) | Each layer tested where it breaks. |
| Local | docker-compose for data services only | Apps run natively; only Postgres lives in Docker. |
| CI | GitHub Actions: secrets → checks → unit/sast → integration/e2e/build → staging deploy | The same gates run locally in `pnpm verify` before every push. |
| Hosting | Fly.io (API + Postgres), any static host for web and sites | Cheap to start, simple to reason about. |
| Observability | Sentry (no-op without a DSN), JSON logs with request id, `/health` | Enough to know what broke and where. |

Versions move fast; the template pins what was tested together, and `copier update` brings the
next tested set.
