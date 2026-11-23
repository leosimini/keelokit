import * as Sentry from '@sentry/node';
import type { NextFunction, Request, Response } from 'express';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AppLogger, REQUEST_ID_HEADER, requestIdMiddleware } from './logger.js';

vi.mock('@sentry/node', () => ({ captureException: vi.fn() }));

function serve(incomingId: string | undefined, handler: () => void): Response {
  const req = { header: (name: string) => (name === REQUEST_ID_HEADER ? incomingId : undefined) };
  const res = { setHeader: vi.fn() };
  requestIdMiddleware(
    req as unknown as Request,
    res as unknown as Response,
    handler as NextFunction,
  );
  return res as unknown as Response;
}

describe('AppLogger', () => {
  afterEach(() => vi.restoreAllMocks());

  it('writes JSON lines carrying the id of the request being served', () => {
    const write = vi.spyOn(process.stdout, 'write').mockReturnValue(true);
    const logger = new AppLogger({ NODE_ENV: 'production', LOG_LEVEL: 'log' });

    serve('req-123', () => logger.log('hello', 'Ctx'));

    const line = JSON.parse(String(write.mock.calls.at(-1)![0]));
    expect(line).toMatchObject({ message: 'hello', context: 'Ctx', requestId: 'req-123' });
  });

  it('reports errors to Sentry, tagged with the request id', () => {
    vi.spyOn(process.stderr, 'write').mockReturnValue(true);
    const boom = new Error('boom');

    serve('req-9', () => new AppLogger({ NODE_ENV: 'production', LOG_LEVEL: 'log' }).error(boom));

    expect(Sentry.captureException).toHaveBeenCalledWith(boom, {
      tags: { request_id: 'req-9' },
    });
  });

  it('drops levels below LOG_LEVEL', () => {
    const write = vi.spyOn(process.stdout, 'write').mockReturnValue(true);
    new AppLogger({ NODE_ENV: 'production', LOG_LEVEL: 'warn' }).log('quiet');
    expect(write).not.toHaveBeenCalled();
  });
});

describe('requestIdMiddleware', () => {
  it("reuses a sane caller's id and echoes it", () => {
    expect(serve('abc-1', () => undefined).setHeader).toHaveBeenCalledWith(
      REQUEST_ID_HEADER,
      'abc-1',
    );
  });

  it('replaces a missing or odd id with a UUID', () => {
    for (const incoming of [undefined, 'no spaces or <tags>']) {
      const res = serve(incoming, () => undefined);
      expect(vi.mocked(res.setHeader).mock.calls[0][1]).toMatch(/^[0-9a-f-]{36}$/);
    }
  });
});
