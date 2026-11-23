import { z } from 'zod';

// Every API response has a schema here. The API's contract tests parse real responses with it,
// and clients parse what they receive with it — a drifted field fails loudly on both sides
// (house rule CONTRACT-1).

export const healthResponseSchema = z.object({
  status: z.enum(['ok', 'degraded']),
  db: z.enum(['up', 'down']),
});
export type HealthResponse = z.infer<typeof healthResponseSchema>;
