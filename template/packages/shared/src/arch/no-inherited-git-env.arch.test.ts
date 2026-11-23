import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { inheritedGitEnv, repoRoot, type Allow } from './_walk.js';

// stable-tests 7: a git hook sets GIT_DIR, GIT_INDEX_FILE and friends. A test that runs `git` from a
// hook inherits them and can rewrite the real repository (one left `core.bare = true` after every
// push). A test that runs git strips the GIT_* variables from the environment it passes.
// A file that really needs to inherit them goes in ALLOW with its reason; a single line says why
// with `// arch-allow: <reason>`.
const ROOT = repoRoot(fileURLToPath(import.meta.url));
const ALLOW: Allow = {};

describe('ARCH tests that run git clean the GIT_* environment', () => {
  it('every spec that runs git also strips the GIT_* variables', () => {
    const bad = inheritedGitEnv(ROOT, ALLOW);
    expect(bad, `these run git without cleaning GIT_*:\n${bad.join('\n')}`).toEqual([]);
  });
});

describe('no-inherited-git-env on fixtures', () => {
  let dir = '';
  const put = (rel: string, lines: string[]) => {
    mkdirSync(dirname(join(dir, rel)), { recursive: true });
    writeFileSync(join(dir, rel), lines.join('\n') + '\n');
  };
  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), 'arch-git-'));
    writeFileSync(join(dir, 'pnpm-workspace.yaml'), 'packages: []\n');
  });
  afterEach(() => rmSync(dir, { recursive: true, force: true }));

  it('stable-tests 7 a spec that runs git with the inherited environment fails', () => {
    put('scripts/release.test.ts', [
      "import { execSync } from 'node:child_process';",
      "it('tags the release', () => {",
      "  execSync('git init -q', { cwd: repo });",
      '});',
    ]);
    expect(inheritedGitEnv(dir)).toEqual(['scripts/release.test.ts:3']);
  });

  it('stable-tests 7 the same spec with the GIT_* variables stripped passes', () => {
    put('scripts/release.test.ts', [
      "import { execFileSync } from 'node:child_process';",
      'const env = Object.fromEntries(',
      "  Object.entries(process.env).filter(([k]) => !k.startsWith('GIT_')),",
      ');',
      "it('tags the release', () => {",
      "  execFileSync('git', ['init', '-q'], { cwd: repo, env });",
      '});',
    ]);
    expect(inheritedGitEnv(dir)).toEqual([]);
  });

  it('stable-tests 7 setting one GIT_ variable, or naming one in a comment, is not cleaning', () => {
    put('a.test.ts', [
      "execSync('git commit -m x', { env: { ...process.env, GIT_AUTHOR_NAME: 'T' } });",
    ]);
    put('b.test.ts', ['// a hook sets GIT_DIR', "execSync('git init -q');"]);
    put('c.test.ts', ["await execa('git', ['init']);"]);
    put('d.test.ts', ['await $`git init`;']);
    put('e.test.ts', ["execSync('cd repo && git init');"]);
    expect(inheritedGitEnv(dir).sort()).toEqual([
      'a.test.ts:1',
      'b.test.ts:2',
      'c.test.ts:1',
      'd.test.ts:1',
      'e.test.ts:1',
    ]);
  });

  it('stable-tests 7 each way of stripping the GIT_* variables passes', () => {
    const run = "execFileSync('git', ['init'], { env });";
    put('a.test.ts', [
      'const env = Object.fromEntries(Object.entries(process.env).filter(([k]) => !/^GIT_/.test(k)));',
      run,
    ]);
    put('b.test.ts', ['const env = { ...process.env };', 'delete env.GIT_DIR;', run]);
    put('c.test.ts', ['const env = { ...process.env, GIT_DIR: undefined };', run]);
    put('d.test.ts', ['const env = cleanGitEnv();', run]);
    expect(inheritedGitEnv(dir)).toEqual([]);
  });
});
