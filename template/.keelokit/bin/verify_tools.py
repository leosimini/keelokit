#!/usr/bin/env python3
"""Helpers of scripts/verify.sh. Stdlib only (Python 3.11+).

    verify_tools.py plan [--all] [--base REF]   the steps this change calls for, one line
    verify_tools.py table                       stdin "seconds|step" lines → the time per step
    verify_tools.py causes LOG                  known causes of a red found in LOG
    verify_tools.py record FILE RESULT RC HEAD LEVEL STEPS FAILED LOG
                                                append one JSON line of this run to FILE

`plan` reads .keelokit/verify-routing.toml: [[route]] paths (globs, `**` crosses folders) → steps.
Each file takes the FIRST route that matches (specific routes go first); a change runs the union of
its files' steps plus `always`. A file no route knows runs EVERYTHING
(unknown goes up, never down), and `--all` is every step: any plan is a subset of it. Without the
file, or when anything fails, the plan is `all` (the behaviour before routing existed).
`causes` reads .keelokit/red-causes.toml: [[cause]] pattern (regex), look (what to check first).
"""
import sys

if sys.version_info < (3, 11):
    sys.exit(f"Keelokit needs Python 3.11+ (found {sys.version.split()[0]})")

import json  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402
import tomllib  # noqa: E402
from pathlib import Path  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
STEPS = ["format", "lint", "typecheck", "unit", "integration", "build", "e2e", "e2e-stack", "mutation", "sast", "audit"]
# Causes every TypeScript project meets; the project's own go in .keelokit/red-causes.toml.
BUILTIN_CAUSES = [
    ("heap", r"JavaScript heap out of memory|heap limit|FATAL ERROR: .*Allocation failed",
     "a test worker ran out of memory: fewer workers, or NODE_OPTIONS=--max-old-space-size=4096; the suite often passes alone"),
    ("disk", r"ENOSPC|no space left on device", "the disk is full: clear build output and caches, then rerun"),
    ("db-start", r"ECONNREFUSED.*5432|database system is starting up|the database system is not yet accepting",
     "the throwaway database was not ready or Docker is down: docker info, then rerun"),
    ("format", r"Code style issues found|\[warn\] .*\.(ts|tsx|md|json)\b", "formatting: pnpm format, commit, rerun"),
    ("secrets", r"leaks found|Finding:.*\n.*Secret", "gitleaks found a secret-looking string: remove it, or fix the false positive's allowlist"),
    ("lockfile", r"ERR_PNPM_OUTDATED_LOCKFILE|lockfile.*not up to date", "pnpm install, commit the lockfile"),
    ("migration", r"migration.*(already|out of order)|P3\d{3}", "migrations: a new one must sort after main's last; never edit an applied one"),
    ("timezone", r"timezone|tzdata|Intl\.DateTimeFormat.*RangeError", "a date/timezone dependency: compare this machine's tzdata with CI's"),
    ("killed", r"\bKilled\b|exit code 137|SIGKILL", "the process was killed, usually by memory: free the machine, fewer workers"),
]


def glob_re(pattern: str) -> re.Pattern:
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif pattern.startswith("**", i):
            out += ".*"
            i += 2
        elif pattern[i] == "*":
            out += "[^/]*"
            i += 1
        elif pattern[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(pattern[i])
            i += 1
    return re.compile(out + r"\Z")


def load_routes() -> tuple[list[str], list[tuple[list[re.Pattern], list[str]]]] | None:
    path = ROOT / ".keelokit/verify-routing.toml"
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    always = [s for s in data.get("always", []) if isinstance(s, str)]
    routes = []
    for r in data.get("route", []) if isinstance(data.get("route"), list) else []:
        if isinstance(r, dict) and isinstance(r.get("paths"), list) and isinstance(r.get("steps"), list):
            routes.append(([glob_re(p) for p in r["paths"] if isinstance(p, str)], [s for s in r["steps"] if isinstance(s, str)]))
    return always, routes


def plan_for(files: list[str], routes_data, everything: bool = False) -> tuple[list[str], list[str]]:
    """(steps, files no route knows). `all` in the steps means every step."""
    if everything or routes_data is None:
        return ["all"], []
    always, routes = routes_data
    steps, unknown = set(always), []
    for f in files:
        hit = next((st for pats, st in routes if any(p.match(f) for p in pats)), None)  # the first route that matches
        if hit is None:
            unknown.append(f)
        else:
            steps.update(hit)
    if unknown or "all" in steps:
        return ["all"], unknown
    return sorted(steps), []


def git_lines(*args: str) -> list[str]:
    res = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    return [l for l in res.stdout.split("\n") if l] if res.returncode == 0 else []


def changed_files(base: str) -> list[str] | None:
    if subprocess.run(["git", "rev-parse", "--verify", "--quiet", base], cwd=ROOT, capture_output=True).returncode:
        return None
    return sorted(set(git_lines("diff", "--name-only", base)) | set(git_lines("ls-files", "--others", "--exclude-standard")))


def cmd_plan(args: list[str]) -> int:
    everything = "--all" in args
    base = args[args.index("--base") + 1] if "--base" in args and args.index("--base") + 1 < len(args) else "origin/main"
    files = None if everything else changed_files(base)
    if files is None:
        print("all")
        return 0
    steps, unknown = plan_for(files, load_routes(), everything)
    if unknown and steps == ["all"]:
        kinds = sorted({Path(f).suffix or Path(f).name for f in unknown})
        print(f"verify: {len(unknown)} changed file(s) match no route in .keelokit/verify-routing.toml "
              f"({', '.join(kinds[:6])}): running everything. Add a route to make this faster.", file=sys.stderr)
    print(" ".join(steps) or "none")
    return 0


def cmd_table() -> int:
    rows = []
    for line in sys.stdin.read().splitlines():
        secs, _, name = line.partition("|")
        if secs.isdigit() and name:
            rows.append((int(secs), name))
    if rows:
        total = sum(s for s, _ in rows)
        print("\nTime per step:")
        for secs, name in rows:
            print(f"  {secs // 60:>3}m{secs % 60:02d}s  {name}")
        print(f"  {total // 60:>3}m{total % 60:02d}s  total")
    return 0


def causes_in(log_text: str) -> list[tuple[str, str]]:
    found = []
    table = list(BUILTIN_CAUSES)
    try:
        data = tomllib.loads((ROOT / ".keelokit/red-causes.toml").read_text(encoding="utf-8"))
        for c in data.get("cause", []) if isinstance(data.get("cause"), list) else []:
            if isinstance(c, dict) and isinstance(c.get("pattern"), str) and isinstance(c.get("look"), str):
                table.insert(0, (str(c.get("id", c["pattern"][:20])), c["pattern"], c["look"]))
    except (OSError, ValueError):
        pass
    for cid, pattern, look in table:
        try:
            if re.search(pattern, log_text):
                found.append((cid, look))
        except re.error:
            continue
    return found


def cmd_causes(path: str) -> int:
    try:
        text = Path(path).read_text(errors="replace")
    except OSError:
        return 0
    found = causes_in(text)
    if found:
        print("\nKnown causes seen in this log (look here first):")
        for cid, look in found:
            print(f"  [{cid}] {look}")
    return 0


def cmd_record(args: list[str]) -> int:
    file, result, rc, head, level, steps, failed, log = (args + [""] * 8)[:8]
    try:
        text = Path(log).read_text(errors="replace")
    except OSError:
        text = ""
    entry = {
        "t": int(time.time()), "head": head[:12], "level": level, "result": result, "rc": int(rc or 0),
        "steps": [[n, int(s)] for s, _, n in (l.partition("|") for l in steps.splitlines()) if s.isdigit()],
        "failed": [l for l in failed.splitlines() if l],
        "causes": [cid for cid, _ in causes_in(text)] if result != "pass" else [],
    }
    with open(file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    return 0


def main() -> int:
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if a[0] == "plan":
        return cmd_plan(a[1:])
    if a[0] == "table":
        return cmd_table()
    if a[0] == "causes" and len(a) == 2:
        return cmd_causes(a[1])
    if a[0] == "record":
        return cmd_record(a[1:])
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
