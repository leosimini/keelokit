// Shared by the arch-specs (references/stable-tests.md): walk the test files of a source tree and
// return each place a rule is broken as "<path from the root>:<line>". Copy it with the spec you use.
// The reference brings Node's types into the package's typecheck (TypeScript 6 adds none by itself).
/// <reference types="node" />
import { existsSync, lstatSync, readdirSync, readFileSync } from 'node:fs';
import { dirname, join, relative, sep } from 'node:path';

/** A file (path from the root, with /) the rule does not apply to, and why. */
export type Allow = Record<string, string>;

// Hidden folders (.git, .claude/worktrees, .turbo…) and tmp/ hold other checkouts and scratch work,
// never this project's tests, so they are not walked either.
const SKIP_DIRS = new Set([
  'tmp',
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
const SOURCE = /\.([cm]?[jt]sx?|json)$/;
const TEST_DIR = new Set([
  'e2e',
  'fixtures',
  '__fixtures__',
  '__tests__',
  '__mocks__',
  'mocks',
  'test',
  'tests',
  'testing',
  'test-utils',
]);
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

/** Test files under `root` (paths from the root, with /): specs, and sources and JSON in a test
 * folder. Symbolic links are never followed (a dangling one or a loop is skipped). */
export function testFiles(root: string): string[] {
  const out: string[] = [];
  const visit = (dir: string, inTestDir: boolean) => {
    for (const name of readdirSync(dir).sort()) {
      if (SKIP_DIRS.has(name) || name.startsWith('.')) continue;
      const path = join(dir, name);
      const stat = lstatSync(path);
      if (stat.isSymbolicLink()) continue;
      if (stat.isDirectory()) visit(path, inTestDir || TEST_DIR.has(name));
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

function lineOf(root: string, at: string): string {
  const i = at.lastIndexOf(':');
  return lines(root, at.slice(0, i))[Number(at.slice(i + 1)) - 1]?.text ?? '';
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
const isComment = (text: string) => /^\s*(\/\/|\/?\*)/.test(text);
const code = (ls: Line[]) => ls.filter(({ text }) => !isComment(text));

// Rule 4: a calendar date of this era written into a test (it becomes a date bomb). A line that pins
// the clock (`vi.setSystemTime(…)`, Playwright's `clock.install`) is how rule 4 wants time tested.
const LITERAL_DATE =
  /['"`][^'"`\n]*\b20[2-3]\d-[01]\d-[0-3]\d|new Date\(\s*20[2-3]\d\s*,|Date\.UTC\(\s*20[2-3]\d/;
const PINS_CLOCK = /setSystemTime\(|clock\.(install|setFixedTime|setSystemTime)\(/;
export const literalDates = (root: string, allow: Allow = {}) =>
  offenders(root, LITERAL_DATE, allow).filter((at) => !PINS_CLOCK.test(lineOf(root, at)));

// Rule 3: a test that sleeps to wait for work (a promise that only resolves after a delay). A
// timeout guard that rejects is not a sleep.
const SLEEP = new RegExp(
  [
    String.raw`new Promise\(\s*\(?\s*(resolve|res|r|done)\b[^;]*setTimeout`,
    String.raw`setTimeout\(\s*(resolve|res|r|done)\b`,
    String.raw`setTimeout\(\s*\(\)\s*=>\s*(resolve|res|r|done)\(`,
    String.raw`await\s+(setTimeout|sleep|delay)\(`,
    String.raw`await\s+wait\(\s*\d`,
    String.raw`\.waitForTimeout\(`,
    String.raw`\bcy\.wait\(\s*\d`,
    String.raw`['"\x60]sleep\s+\d`,
  ].join('|'),
);
export const sleepsInSpecs = (root: string, allow: Allow = {}) => offenders(root, SLEEP, allow);

// Rule 10: test data from an unseeded random source. Faker counts as seeded only with a seed given
// in code (`faker.seed(42)`, `fakerDE.seed(n)`), not `faker.seed()`, which picks a random one.
const RANDOM =
  /\bMath\.random\(|\brandomUUID\(|\buuidv4\(|\bnanoid\(|\brandomInt\(|\brandomBytes\(|\bgetRandomValues\(/;
const FAKER_USE = /\b(faker[A-Z_]*)\.(?!seed\()/g;
const fakerUnseeded: FileCheck = (ls) => {
  const lines = code(ls);
  for (const { text, n } of lines) {
    for (const [, name] of text.matchAll(FAKER_USE)) {
      const seeded = new RegExp(String.raw`\b${name}\.seed\(\s*[\w.]`);
      if (!lines.some(({ text: t }) => seeded.test(t))) return n;
    }
  }
  return undefined;
};
export const randomTestData = (root: string, allow: Allow = {}) => [
  ...new Set([...offenders(root, RANDOM, allow), ...fileOffenders(root, fakerUnseeded, allow)]),
];

// Rule 7: a test that runs git with the GIT_* variables a hook set. Naming a GIT_ variable is not
// enough (setting GIT_AUTHOR_NAME on top of process.env keeps GIT_DIR); dropping them is.
const RUNS_GIT = new RegExp(
  [
    String.raw`\b(execSync|execFileSync|spawnSync|spawn|execFile|exec|execa|execaSync)\(\s*['"\x60]git\b`,
    String.raw`\b(execSync|execFileSync|spawnSync|spawn|execFile|exec|execa|execaSync)\(\s*['"\x60][^'"\x60]*(&&|;|\|)\s*git\b`,
    String.raw`\$\x60\s*git\b`,
    String.raw`\[\s*['"\x60]git['"\x60]`,
  ].join('|'),
);
const CLEANS_GIT = new RegExp(
  [
    String.raw`\{[^}]*\bGIT_[A-Z_]+[^}]*\.\.\.\w+\s*\}\s*=\s*process\.env`,
    String.raw`/\^GIT_`,
    String.raw`startsWith\(\s*['"\x60]GIT_`,
    String.raw`\bdelete\s+[\w.]+(\.GIT_|\[\s*['"\x60]?GIT_)`,
    String.raw`\bGIT_[A-Z_]+\s*:\s*undefined`,
    String.raw`\bcleanGitEnv\b`,
    String.raw`\bgitEnv\(`,
  ].join('|'),
);
export const inheritedGitEnv = (root: string, allow: Allow = {}) =>
  fileOffenders(
    root,
    (ls) =>
      code(ls).some(({ text }) => CLEANS_GIT.test(text)) ? undefined : firstLine(ls, RUNS_GIT),
    allow,
  );
