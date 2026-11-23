import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { randomTestData, repoRoot, type Allow } from './_walk.js';

// stable-tests 10: test data is deterministic. A random name once in a while contains a word the code
// reacts to ("fee") and the test goes red for no bug. Use fixed fixtures or a seeded generator
// (`faker.seed(42)`, a seeded PRNG); never Math.random, unseeded faker or randomUUID in a test.
// A file that really needs one goes in ALLOW with its reason; a single line says why with
// `// arch-allow: <reason>`.
const ROOT = repoRoot(fileURLToPath(import.meta.url));
const ALLOW: Allow = {
  // 'apps/api/src/testing/ids.ts': 'unique ids for rows; never shown, never matched against words',
};

describe('ARCH no random test data', () => {
  it('no spec builds data from Math.random, unseeded faker or randomUUID', () => {
    const bad = randomTestData(ROOT, ALLOW);
    expect(bad, `random test data found (seed it or fix it):\n${bad.join('\n')}`).toEqual([]);
  });
});

describe('no-random-test-data on fixtures', () => {
  let dir = '';
  const put = (rel: string, lines: string[]) => {
    mkdirSync(dirname(join(dir, rel)), { recursive: true });
    writeFileSync(join(dir, rel), lines.join('\n') + '\n');
  };
  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), 'arch-random-'));
    writeFileSync(join(dir, 'pnpm-workspace.yaml'), 'packages: []\n');
  });
  afterEach(() => rmSync(dir, { recursive: true, force: true }));

  it('FLEET-003.S3 a spec using Math.random to build a name fails', () => {
    put('src/invoice.test.ts', [
      "it('bills the customer', () => {",
      "  const name = 'customer-' + Math.random().toString(36).slice(2);",
      '  expect(bill(name).lines).toHaveLength(1);',
      '});',
    ]);
    put('src/ids.test.ts', ['const id = crypto.randomUUID();']);
    expect(randomTestData(dir).sort()).toEqual(['src/ids.test.ts:1', 'src/invoice.test.ts:2']);
  });

  it('FLEET-003.S3 the same spec with a seeded generator passes', () => {
    put('src/invoice.test.ts', [
      "it('bills the customer', () => {",
      '  const rand = mulberry32(42);',
      "  const name = 'customer-' + Math.floor(rand() * 1e6);",
      '  expect(bill(name).lines).toHaveLength(1);',
      '});',
    ]);
    expect(randomTestData(dir)).toEqual([]);
  });

  it('FLEET-003.S3 faker without a seed fails; with faker.seed it passes', () => {
    put('e2e/fixtures/people.ts', [
      "import { faker } from '@faker-js/faker';",
      'export const person = () => ({ name: faker.person.fullName() });',
    ]);
    expect(randomTestData(dir)).toEqual(['e2e/fixtures/people.ts:2']);
    put('e2e/fixtures/people.ts', [
      "import { faker } from '@faker-js/faker';",
      'faker.seed(42);',
      'export const person = () => ({ name: faker.person.fullName() });',
    ]);
    expect(randomTestData(dir)).toEqual([]);
  });
});
