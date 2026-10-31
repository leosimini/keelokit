import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { walk } from './_walk';

// stable-tests 7: a git hook sets GIT_DIR, GIT_INDEX_FILE and friends. A test that runs `git` inherits them
// and can rewrite the real repository (one left `core.bare = true` after every push). Clean the environment.
const ROOT = new URL('../..', import.meta.url).pathname; // adjust
const RUNS_GIT = /(execSync|execFileSync|spawnSync|spawn|exec)\(\s*['"`]git\b|\[\s*['"]git['"]/;
const CLEANS = /GIT_[A-Z_]+|cleanGitEnv|gitEnv\(/;

describe('ARCH tests that run git clean the GIT_* environment', () => {
  it('every spec that runs git also strips GIT_* variables', () => {
    const bad = walk(ROOT, /\.(test|spec)\.[cm]?[jt]sx?$/).filter((f) => {
      const text = readFileSync(f, 'utf8');
      return RUNS_GIT.test(text) && !CLEANS.test(text);
    });
    expect(bad, `these run git without cleaning GIT_*:\n${bad.join('\n')}`).toEqual([]);
  });
});
