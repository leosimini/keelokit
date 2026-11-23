import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { loadEnv, OPTIONAL_ENV_KEYS, REQUIRED_ENV_KEYS } from './env.schema.js';

// Drift guard (rule CFG-1). A key that lives in the code but not in .env.example, .env.ci or the
// README block gives a new developer, or CI, an API that won't start; a key listed there that
// nothing reads sends them chasing a setting that does nothing. Every list must match the schema.

const apiDir = fileURLToPath(new URL('../../', import.meta.url));
const declared = [...REQUIRED_ENV_KEYS, ...Object.keys(OPTIONAL_ENV_KEYS)].sort();

function keysIn(text: string): string[] {
  return [...text.matchAll(/^\s*([A-Z][A-Z0-9_]*)=/gm)].map((m) => m[1]).sort();
}

describe('env.schema: every place that lists API config keys agrees', () => {
  it.each(['.env.example', '.env.ci'])('apps/api/%s lists exactly the declared keys', (file) => {
    expect(keysIn(readFileSync(join(apiDir, file), 'utf8'))).toEqual(declared);
  });

  it("the README's `# apps/api/.env` block lists exactly the declared keys", () => {
    const readme = readFileSync(join(apiDir, '../../README.md'), 'utf8');
    const block = /```bash\n# apps\/api\/\.env\n([\s\S]*?)```/.exec(readme);
    expect(block, 'README.md has no ```bash block starting with `# apps/api/.env`').not.toBeNull();
    expect(keysIn(block![1])).toEqual(declared);
  });

  it('every process.env / config.get key read in src is declared', () => {
    const patterns = [
      /process\.env\.([A-Z][A-Z0-9_]*)/g,
      /process\.env\[\s*'([A-Z][A-Z0-9_]*)'\s*\]/g,
      /config(?:Service)?\.(?:get|getOrThrow)(?:<[^>]*>)?\(\s*'([A-Z][A-Z0-9_]*)'/g,
    ];
    const read = new Set<string>();
    for (const file of sourceFiles(join(apiDir, 'src'))) {
      const code = readFileSync(file, 'utf8');
      for (const pattern of patterns) for (const m of code.matchAll(pattern)) read.add(m[1]);
    }
    expect([...read].filter((key) => !declared.includes(key))).toEqual([]);
  });
});

/** Every non-test .ts file under `dir`, skipping generated code. */
function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) return entry.name === 'generated' ? [] : sourceFiles(full);
    return entry.name.endsWith('.ts') && !entry.name.endsWith('.spec.ts') ? [full] : [];
  });
}

describe('loadEnv', () => {
  const complete = { DATABASE_URL: 'postgresql://x', NODE_ENV: 'test' };

  it('fills optional keys with their defaults', () => {
    expect(loadEnv(complete)).toEqual({ ...OPTIONAL_ENV_KEYS, ...complete });
  });

  it('names every missing required key at once, treating blank as missing', () => {
    expect(() => loadEnv({ NODE_ENV: '  ' })).toThrow(/DATABASE_URL, NODE_ENV/);
  });

  it('rejects an unknown LOG_LEVEL', () => {
    expect(() => loadEnv({ ...complete, LOG_LEVEL: 'loud' })).toThrow(/LOG_LEVEL/);
  });
});
