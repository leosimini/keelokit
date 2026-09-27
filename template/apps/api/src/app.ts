import type { INestApplication } from '@nestjs/common';
import { NestFactory } from '@nestjs/core';
import helmet from 'helmet';
import { AppModule } from './app.module.js';
import type { Env } from './config/env.schema.js';
import { AppLogger, requestIdMiddleware } from './observability/logger.js';

/** The app exactly as it runs in production; main.ts listens on it, integration tests call it. */
export async function createApp(env: Env): Promise<INestApplication> {
  const app = await NestFactory.create(AppModule, { logger: new AppLogger(env) });
  app.use(requestIdMiddleware);
  app.use(helmet());
  app.enableCors({
    origin: env.CORS_ALLOWED_ORIGINS.split(',')
      .map((origin) => origin.trim())
      .filter(Boolean),
  });
  // SIGTERM (Fly's kill_signal) closes the server and runs onModuleDestroy, so in-flight
  // requests finish and the database pool is released before the process exits.
  app.enableShutdownHooks();
  return app;
}
