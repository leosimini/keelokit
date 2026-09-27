import 'reflect-metadata';
import type { Express } from 'express';
import { describe, expect, it, vi } from 'vitest';
import { createApp } from '../app.js';
import { loadEnv } from '../config/env.schema.js';
import { authzMatrix } from './authz.matrix.js';

// Only the routes matter here: boot the real app without a database.
vi.mock('../prisma.service.js', () => ({ PrismaService: class {} }));

async function registeredRoutes(): Promise<string[]> {
  const env = { DATABASE_URL: 'postgresql://unused', NODE_ENV: 'test', LOG_LEVEL: 'warn' };
  const app = await createApp(loadEnv(env));
  await app.init();
  // Every route Nest maps lands in Express's router stack (Nest itself inspects it there).
  const express: Express = app.getHttpAdapter().getInstance();
  const { stack } = express.router;
  await app.close();
  return stack.flatMap(({ route }) => {
    if (!route) return []; // middleware
    const methods = new Set(route.stack.map((layer) => layer.method.toUpperCase()));
    return [...methods].map((method) => `${method} ${route.path}`);
  });
}

describe('authorization matrix (AUTHZ-1)', () => {
  it('declares every registered route, and only those', async () => {
    expect(
      (await registeredRoutes()).sort(),
      'keep src/authz/authz.matrix.ts in step with the routes',
    ).toEqual(Object.keys(authzMatrix).sort());
  });
});
