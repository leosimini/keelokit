import 'reflect-metadata';
import { existsSync } from 'node:fs';
import * as Sentry from '@sentry/node';
import { createApp } from './app.js';
import { loadEnv } from './config/env.schema.js';

// Local runs read apps/api/.env; real environment variables (Fly secrets, CI) win over it.
const envFile = new URL('../.env', import.meta.url);
if (existsSync(envFile)) process.loadEnvFile(envFile);

const env = loadEnv();
// Without a DSN nothing is initialised and every Sentry call is a no-op (local runs, tests).
if (env.SENTRY_DSN) Sentry.init({ dsn: env.SENTRY_DSN, environment: env.NODE_ENV });

const app = await createApp(env);
await app.listen(Number(env.PORT));
