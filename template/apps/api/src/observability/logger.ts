import { AsyncLocalStorage } from 'node:async_hooks';
import { randomUUID } from 'node:crypto';
import { ConsoleLogger, type LogLevel } from '@nestjs/common';
import * as Sentry from '@sentry/node';
import type { NextFunction, Request, Response } from 'express';
import { LOG_LEVELS, type Env } from '../config/env.schema.js';

/** Ties one request's log lines, its Sentry event and its response together. */
export const REQUEST_ID_HEADER = 'X-Request-Id';

const requestContext = new AsyncLocalStorage<{ requestId: string }>();

/** A caller's id is reused only when it looks like one; anything else gets a fresh UUID. */
const SANE_ID = /^[\w.:-]{1,128}$/;

export function requestIdMiddleware(req: Request, res: Response, next: NextFunction): void {
  // Fly's proxy stamps every request with its own id.
  const incoming = req.header(REQUEST_ID_HEADER) ?? req.header('Fly-Request-Id');
  const requestId = incoming && SANE_ID.test(incoming) ? incoming : randomUUID();
  res.setHeader(REQUEST_ID_HEADER, requestId);
  requestContext.run({ requestId }, next);
}

/**
 * Nest's logger: JSON lines when deployed (Fly ships stdout to its log search), coloured text
 * locally. JSON lines written while serving a request carry its id, and every `error` is also
 * reported to Sentry, which covers unhandled exceptions too (Nest logs them through here).
 */
export class AppLogger extends ConsoleLogger {
  constructor(env: Pick<Env, 'NODE_ENV' | 'LOG_LEVEL'>) {
    super({
      json: env.NODE_ENV === 'production' || env.NODE_ENV === 'staging',
      logLevels: LOG_LEVELS.slice(LOG_LEVELS.indexOf(env.LOG_LEVEL as LogLevel)),
    });
  }

  override error(message: unknown, ...optionalParams: unknown[]): void {
    super.error(message, ...optionalParams);
    if (this.isLevelEnabled('error')) {
      const requestId = requestContext.getStore()?.requestId;
      Sentry.captureException(message instanceof Error ? message : new Error(String(message)), {
        tags: requestId ? { request_id: requestId } : undefined,
      });
    }
  }

  protected override getJsonLogObject(
    message: unknown,
    options: Parameters<ConsoleLogger['getJsonLogObject']>[1],
  ) {
    const requestId = requestContext.getStore()?.requestId;
    const line = super.getJsonLogObject(message, options);
    return requestId ? { ...line, requestId } : line;
  }
}
