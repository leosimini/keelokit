import { existsSync } from 'node:fs';
import { defineConfig } from 'prisma/config';

// Prisma 7 no longer reads .env itself. Real environment variables win over the file.
if (existsSync('.env')) process.loadEnvFile('.env');

export default defineConfig({
  schema: 'prisma/schema.prisma',
  // tsx, not node: the generated client imports its own .ts files by .js names.
  migrations: { seed: 'tsx prisma/seed.ts' },
  // Not env('DATABASE_URL'): that throws when unset, and `prisma generate` runs without a database.
  datasource: { url: process.env.DATABASE_URL },
});
