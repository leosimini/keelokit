// Shared by the arch-specs: every source file under `root` matching `pattern`, without node_modules or build output.
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';

export function walk(root: string, pattern: RegExp, out: string[] = []): string[] {
  for (const name of readdirSync(root)) {
    if (['node_modules', 'dist', 'build', '.expo', 'coverage'].includes(name)) continue;
    const path = join(root, name);
    if (statSync(path).isDirectory()) walk(path, pattern, out);
    else if (pattern.test(path)) out.push(path);
  }
  return out;
}

export function offenders(root: string, files: RegExp, bad: RegExp, allow: Record<string, string>): string[] {
  return walk(root, files)
    .filter((f) => !(f in allow))
    .flatMap((f) =>
      readFileSync(f, 'utf8')
        .split('\n')
        .map((line, i) => ({ f, line, n: i + 1 }))
        .filter(({ line }) => bad.test(line) && !line.includes('arch-allow'))
        .map(({ f, n }) => `${f}:${n}`),
    );
}
