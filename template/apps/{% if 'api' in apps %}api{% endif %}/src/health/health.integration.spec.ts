import 'reflect-metadata';
import type { INestApplication } from '@nestjs/common';
import request from 'supertest';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { createApp } from '../app.js';
import { loadEnv } from '../config/env.schema.js';

describe('GET /health against the real database', () => {
  let app: INestApplication;

  beforeAll(async () => {
    app = await createApp(loadEnv());
    await app.init();
  });

  afterAll(async () => {
    await app.close();
  });

  it('answers 200 ok with a request id', async () => {
    const res = await request(app.getHttpServer()).get('/health').set('X-Request-Id', 'probe-1');
    expect(res.status).toBe(200);
    expect(res.body).toEqual({ status: 'ok', db: 'up' });
    expect(res.headers['x-request-id']).toBe('probe-1');
  });
});
