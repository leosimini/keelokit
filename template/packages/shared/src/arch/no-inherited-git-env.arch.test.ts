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
      'const { GIT_DIR, GIT_INDEX_FILE, GIT_WORK_TREE, ...env } = process.env;',
      "it('tags the release', () => {",
      "  execFileSync('git', ['init', '-q'], { cwd: repo, env });",
      '});',
    ]);
    expect(inheritedGitEnv(dir)).toEqual([]);
  });
});
