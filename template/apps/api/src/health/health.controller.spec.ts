import { ServiceUnavailableException } from '@nestjs/common';
import { describe, expect, it, vi } from 'vitest';
import type { PrismaService } from '../prisma.service.js';
import { HealthController } from './health.controller.js';

function controllerWith(queryRaw: () => Promise<unknown>): HealthController {
  return new HealthController({ $queryRaw: vi.fn(queryRaw) } as unknown as PrismaService);
}

describe('HealthController', () => {
  it('answers ok while the database answers', async () => {
    await expect(controllerWith(async () => [{ '?column?': 1 }]).check()).resolves.toEqual({
      status: 'ok',
      db: 'up',
    });
  });

  it('answers 503 degraded when the database query fails', async () => {
    const check = controllerWith(() => Promise.reject(new Error('connection refused'))).check();
    const error = await check.catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ServiceUnavailableException);
    expect((error as ServiceUnavailableException).getResponse()).toEqual({
      status: 'degraded',
      db: 'down',
    });
  });
});
