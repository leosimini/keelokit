import { describe, expect, it } from 'vitest';
import { offenders } from './_walk';

// stable-tests 3: never sleep to wait for work. Wait for the event, drain the queue, read once.
// A line that really needs it says why with `// arch-allow: <reason>`; a whole file goes in ALLOW with its reason.
const ROOT = new URL('../..', import.meta.url).pathname; // adjust: the package that holds the tests
const ALLOW: Record<string, string> = {};

describe('ARCH no sleeps in specs', () => {
  it('no spec waits with setTimeout/sleep', () => {
    const bad = offenders(
      ROOT,
      /\.(test|spec)\.[cm]?[jt]sx?$/,
      /new Promise\([^)]*setTimeout|await\s+(sleep|delay|wait)\(\s*\d|setTimeout\(\s*(resolve|r)\b/,
      ALLOW,
    );
    expect(bad, `sleeps found (wait for the event instead):\n${bad.join('\n')}`).toEqual([]);
  });
});
