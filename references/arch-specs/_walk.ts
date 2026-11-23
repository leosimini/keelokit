// Shared by the arch-specs (references/stable-tests.md): walk the test files of a source tree and
// return each place a rule is broken as "<path from the root>:<line>". Copy it with the spec you use.
// The reference brings Node's types into the package's typecheck (TypeScript 6 adds none by itself).
/// <reference types="node" />
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join, relative, sep } from 'node:path';

/** A file (path from the root, with /) the rule does not apply to, and why. */
export type Allow = Record<string, string>;

const SKIP_DIRS = new Set([
  'node_modules',
  'dist',
  'build',
  '.expo',
  '.astro',
  'coverage',
  '.git',
  'playwright-report',
  'test-results',
  '.stryker-tmp',
]);
const TEST_FILE = /\.(test|spec)\.[cm]?[jt]sx?$/;
const SOURCE = /\.[cm]?[jt]sx?$/;
const TEST_DIR = new Set(['e2e', 'fixtures', '__tests__', 'test', 'tests']);
// The arch-specs hold the patterns they forbid, as fixtures: they never check themselves.
const SELF = /(\.arch\.test\.[cm]?[jt]sx?|(^|\/)_walk\.ts)$/;

/** The project's root: the first folder above `from` with pnpm-workspace.yaml, else with .git. */
export function repoRoot(from: string): string {
  for (const marker of ['pnpm-workspace.yaml', '.git']) {
    for (let dir = from; ; dir = dirname(dir)) {
      if (existsSync(join(dir, marker))) return dir;
      if (dirname(dir) === dir) break;
    }
  }
  throw new Error(`no pnpm-workspace.yaml or .git above ${from}`);
}

/** Test files under `root` (paths from the root, with /): specs, and sources in a test folder. */
export function testFiles(root: string): string[] {
  const out: string[] = [];
  const visit = (dir: string, inTestDir: boolean) => {
    for (const name of readdirSync(dir).sort()) {
      if (SKIP_DIRS.has(name)) continue;
      const path = join(dir, name);
      if (statSync(path).isDirectory()) visit(path, inTestDir || TEST_DIR.has(name));
      else if (TEST_FILE.test(name) || (inTestDir && SOURCE.test(name))) {
        const rel = relative(root, path).split(sep).join('/');
        if (!SELF.test(rel)) out.push(rel);
      }
    }
  };
  visit(root, false);
  return out;
}

type Line = { text: string; n: number };
type FileCheck = (lines: Line[]) => number | undefined;

function lines(root: string, rel: string): Line[] {
  return readFileSync(join(root, rel), 'utf8')
    .split('\n')
    .map((text, i) => ({ text, n: i + 1 }));
}

/** Every line that matches `bad`, unless its file is allowed or the line says `arch-allow`. */
export function offenders(root: string, bad: RegExp, allow: Allow = {}): string[] {
  return testFiles(root)
    .filter((rel) => !(rel in allow))
    .flatMap((rel) =>
      lines(root, rel)
        .filter(({ text }) => bad.test(text) && !text.includes('arch-allow'))
        .map(({ n }) => `${rel}:${n}`),
    );
}

/** One place per file, where `check` (a rule about the whole file) points. */
function fileOffenders(root: string, check: FileCheck, allow: Allow): string[] {
  return testFiles(root)
    .filter((rel) => !(rel in allow))
    .flatMap((rel) => {
      const n = check(lines(root, rel).filter(({ text }) => !text.includes('arch-allow')));
      return n === undefined ? [] : [`${rel}:${n}`];
    });
}

const firstLine = (ls: Line[], re: RegExp) => ls.find(({ text }) => re.test(text))?.n;

// Rule 4: a calendar date of this era written into a test (it becomes a date bomb).
const LITERAL_DATE = /['"`][^'"`\n]*\b20[2-3]\d-[01]\d-[0-3]\d|new Date\(\s*20[2-3]\d\s*,/;
export const literalDates = (root: string, allow: Allow = {}) =>
  offenders(root, LITERAL_DATE, allow);

// Rule 3: a test that sleeps to wait for work.
const SLEEP =
  /new Promise\([^;]*setTimeout|setTimeout\(\s*(resolve|res|r|done)\b|await\s+(sleep|delay|wait)\(\s*\d|\.waitForTimeout\(/;
export const sleepsInSpecs = (root: string, allow: Allow = {}) => offenders(root, SLEEP, allow);

// Rule 10: test data from an unseeded random source.
const RANDOM = /\bMath\.random\(|\brandomUUID\(/;
const FAKER_USE = /\bfaker\.(?!seed\()/;
const FAKER_SEED = /\bfaker\.seed\(/;
export const randomTestData = (root: string, allow: Allow = {}) => [
  ...new Set([
    ...offenders(root, RANDOM, allow),
    ...fileOffenders(
      root,
      (ls) => (ls.some(({ text }) => FAKER_SEED.test(text)) ? undefined : firstLine(ls, FAKER_USE)),
      allow,
    ),
  ]),
];

// Rule 7: a test that runs git with the GIT_* variables a hook set.
const RUNS_GIT =
  /\b(execSync|execFileSync|spawnSync|spawn|execFile|exec)\(\s*['"`]git\b|\[\s*['"`]git['"`]/;
const CLEANS_GIT = /\bGIT_[A-Z_]+|\bcleanGitEnv\b|\bgitEnv\(/;
export const inheritedGitEnv = (root: string, allow: Allow = {}) =>
  fileOffenders(
    root,
    (ls) => (ls.some(({ text }) => CLEANS_GIT.test(text)) ? undefined : firstLine(ls, RUNS_GIT)),
    allow,
  );
