import type { Role } from '../src/authz/authz.matrix.js';
import { PrismaService } from '../src/prisma.service.js';

/**
 * Who the verifier and bug-bash agents act as: one persona per role and per state worth testing
 * (a brand-new account, one with an overdue payment…). Add a persona with the model it needs;
 * `db:seed` creates it and prints this list so an agent knows whom to log in as.
 */
export const personas: { name: string; role: Role; state: string }[] = [];

if (import.meta.main) {
  const prisma = new PrismaService();
  try {
    // $connect() is lazy with a driver adapter; a real query fails here when the database is absent.
    await prisma.$queryRaw`SELECT 1`;
    // Upsert each persona on a natural key (email, slug), never create: seeding twice must leave
    // the database as seeding once did.
  } finally {
    await prisma.$disconnect();
  }
  console.log(`Seeded ${personas.length} persona(s).`);
  console.table(personas);
}
