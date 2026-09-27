// The one list of environment keys this API reads. `loadEnv()` runs before Nest boots, so a
// missing key stops the process at startup with every offender named, not at the first request
// that needs it. `env.schema.spec.ts` keeps .env.example, .env.ci, the README block and the code
// in step with these lists.

/** Absent means the API cannot work. */
export const REQUIRED_ENV_KEYS = ['DATABASE_URL', 'NODE_ENV'] as const;

/** Read with a default; the default is the value used when the key is unset. */
export const OPTIONAL_ENV_KEYS = {
  PORT: '3000',
  /** Comma-separated browser origins allowed to call the API. Empty allows none. */
  CORS_ALLOWED_ORIGINS: '',
  /** Empty disables error reporting, which is a valid local setup. */
  SENTRY_DSN: '',
  /** Lowest level written: verbose, debug, log, warn, error or fatal. */
  LOG_LEVEL: 'log',
} as const;

export const LOG_LEVELS = ['verbose', 'debug', 'log', 'warn', 'error', 'fatal'] as const;

export type Env = Record<
  (typeof REQUIRED_ENV_KEYS)[number] | keyof typeof OPTIONAL_ENV_KEYS,
  string
>;

export function loadEnv(source: NodeJS.ProcessEnv = process.env): Env {
  const missing = REQUIRED_ENV_KEYS.filter((key) => !source[key]?.trim());
  if (missing.length > 0) {
    throw new Error(
      `Missing required environment variable(s): ${missing.join(', ')}. ` +
        'See apps/api/.env.example for every key the API reads.',
    );
  }
  const env = { ...OPTIONAL_ENV_KEYS } as Env;
  for (const key of [...REQUIRED_ENV_KEYS, ...Object.keys(OPTIONAL_ENV_KEYS)] as (keyof Env)[]) {
    const value = source[key]?.trim();
    if (value) env[key] = value;
  }
  if (!(LOG_LEVELS as readonly string[]).includes(env.LOG_LEVEL)) {
    throw new Error(`LOG_LEVEL must be one of ${LOG_LEVELS.join(', ')}; got "${env.LOG_LEVEL}".`);
  }
  return env;
}
