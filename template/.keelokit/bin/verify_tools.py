#!/usr/bin/env python3
"""Helpers of scripts/verify.sh. Stdlib only (Python 3.11+).

    verify_tools.py plan [--all] [--base REF]   the steps this change calls for, one line
    verify_tools.py table                       stdin "seconds|step" lines → the time per step
    verify_tools.py causes LOG                  known causes of a red found in LOG
    verify_tools.py record FILE RESULT RC HEAD LEVEL STEPS FAILED LOG
                                                append one JSON line of this run to FILE
                                                (the rest comes from VERIFY_* variables, see cmd_record)
    verify_tools.py steps LIST | --list         check step names (comma list) / print every name
    verify_tools.py rerun HISTORY --head SHA --base SHA --scope TEXT --level LEVEL
                                                the steps --rerun-failed runs; empty (and why) when it
                                                can't tell, which means the normal verify
    verify_tools.py shared-seal --head SHA --base SHA --level LEVEL
                                                0: a shared seal covers this commit; 1: refused (why);
                                                3: [verify] shared_seals is not set

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
import os  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402
import tomllib  # noqa: E402
from pathlib import Path  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
STEPS = ["format", "lint", "typecheck", "unit", "integration", "build", "e2e", "e2e-stack", "mutation", "sast", "audit"]
# What --steps accepts: the routing's steps plus the two that run on every change.
NAMES = ["secrets", *STEPS[:3], "doctor", *STEPS[3:], "clock"]  # clock: the date-bomb rerun, only with --all
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


def relative(path: str) -> str:
    try:
        return Path(path).resolve().relative_to(ROOT.resolve()).as_posix() or "."
    except ValueError:
        return path


def cmd_record(args: list[str]) -> int:
    """One JSON line per run. Besides the arguments, from the environment: VERIFY_BASE (the base's sha),
    VERIFY_PLANNED / VERIFY_PASSED / VERIFY_FAILED_STEPS (step names), VERIFY_SCOPE (the --packages /
    --filter selectors, if any), VERIFY_PACKAGES (pnpm's parseable list of the packages in scope),
    VERIFY_STEP_PACKAGES ("step=dir " pairs for steps whose packages aren't the run's), VERIFY_PARTIAL and
    VERIFY_CLEAN (the tree had no uncommitted or untracked changes when the run started)."""
    file, result, rc, head, level, steps, failed, log = (args + [""] * 8)[:8]
    env = os.environ.get
    try:
        text = Path(log).read_text(errors="replace")
    except OSError:
        text = ""
    step_packages: dict[str, list[str]] = {}
    for pair in env("VERIFY_STEP_PACKAGES", "").split():
        name, _, folder = pair.partition("=")
        if folder and folder not in step_packages.setdefault(name, []):
            step_packages[name].append(folder)
    entry = {
        "t": int(time.time()), "head": head, "base": env("VERIFY_BASE", ""), "level": level, "result": result,
        "rc": int(rc or 0), "partial": env("VERIFY_PARTIAL") == "true", "scope": " ".join(env("VERIFY_SCOPE", "").split()),
        "steps": [[n, int(s)] for s, _, n in (l.partition("|") for l in steps.splitlines()) if s.isdigit()],
        "failed": [l for l in failed.splitlines() if l],
        "clean": env("VERIFY_CLEAN") == "true",
        "planned": env("VERIFY_PLANNED", "").split(),
        "passed": [n for n in env("VERIFY_PASSED", "").split() if n not in env("VERIFY_FAILED_STEPS", "").split()],
        "failed_steps": env("VERIFY_FAILED_STEPS", "").split(),
        "packages": sorted({relative(l) for l in env("VERIFY_PACKAGES", "").splitlines() if l.strip()}),
        "step_packages": step_packages,
        "causes": [cid for cid, _ in causes_in(text)] if result != "pass" else [],
    }
    with open(file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    return 0


def cmd_steps(args: list[str]) -> int:
    if args == ["--list"]:
        print(" ".join(NAMES))
        return 0
    asked = [n.strip() for n in (args[0] if args else "").replace(" ", ",").split(",") if n.strip()]
    unknown = [n for n in asked if n not in NAMES]
    if unknown or not asked:
        print(f"--steps: unknown step(s) {', '.join(unknown) or '(none given)'}; the steps are: {', '.join(NAMES)}",
              file=sys.stderr)
        return 2
    print(" ".join(n for n in NAMES if n in asked))
    return 0


def option(args: list[str], name: str, default: str = "") -> str:
    return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else default


def is_ancestor(old: str, new: str) -> bool:
    return subprocess.run(["git", "merge-base", "--is-ancestor", old, new], cwd=ROOT, capture_output=True).returncode == 0


def rerun_steps(history: str, head: str, base: str, scope: str, level: str) -> tuple[list[str], str]:
    """(steps to run, why). No steps means: run the normal verify, for the reason given. The last run of
    this commit or an ancestor decides; only a red one with a clean tree and the same base, scope and level
    can be narrowed to what it didn't pass plus what the files changed since then call for."""
    try:
        lines = Path(history).read_text(encoding="utf-8").splitlines()
    except OSError:
        return [], "no verify history in this clone"
    last = None
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        old = entry.get("head", "") if isinstance(entry, dict) else ""
        if isinstance(old, str) and len(old) == 40 and (old == head or is_ancestor(old, head)):
            last = entry
            break
    if last is None:
        return [], "no earlier verify of this commit or one before it"
    if last.get("result") == "pass":
        return [], f"the last verify of {last['head'][:7]} passed: nothing failed"
    if not all(isinstance(last.get(k), list) for k in ("planned", "passed", "failed_steps")) or not last["planned"]:
        return [], "the last red run recorded no steps (an older verify)"
    if last.get("base") != base:
        return [], "origin/main (or --since) is not where it was for that run"
    if " ".join(scope.split()) != last.get("scope", ""):
        return [], "that run covered other packages (--packages / --filter differ)"
    if last.get("level") != level:
        return [], ("that run was --all: rerun it with --all" if last.get("level") == "all"
                    else "that run was not --all, so its passes don't cover an --all request")
    if last.get("clean") is not True:
        return [], "that run saw uncommitted or untracked changes, so what passed is not this commit's"
    setup = [s for s in last["failed_steps"] if s not in NAMES]
    if setup:
        return [], f"it stopped in a setup step ({', '.join(setup)})"
    passed = set(last["passed"]) - set(last["failed_steps"])
    todo = {s for s in last["planned"] if s in NAMES and s not in passed}
    files = changed_files(last["head"])
    if files is None:
        return [], f"{last['head'][:7]} is not in this clone"
    steps, unknown = plan_for(files, load_routes())
    if "all" in steps:
        return [], (f"{len(unknown)} file(s) changed since then match no route" if unknown
                    else "the files changed since then call for every step")
    todo |= set(steps)
    if not todo:
        return [], "nothing failed or was left unrun"
    return [n for n in NAMES if n in todo], ""


def cmd_rerun(args: list[str]) -> int:
    steps, why = rerun_steps(args[0] if args else "", option(args, "--head"), option(args, "--base"),
                             option(args, "--scope"), option(args, "--level", "changed"))
    if not steps:
        print(f"verify --rerun-failed: can't narrow the run ({why}): running the normal verify.", file=sys.stderr)
    print(" ".join(steps))
    return 0


SHARED = re.compile(r"(?P<remote>[\w.-]+)/(?P<branch>[\w./-]+):(?P<path>[^\s:]*\{head\}[^\s:]*)")


def shared_seal(head: str, base: str, level: str) -> tuple[int, str]:
    """[verify] shared_seals = "<remote>/<branch>:<path with {head}>" in .keelokit/state.toml: a TOML file
    (head, base, exit, level) another machine pushed for this commit. Accepted only when head is this
    commit, base is origin/main now, exit is 0, its level covers the request and the tree is clean.
    Trusting it is trusting whoever can push to that branch."""
    try:
        state = tomllib.loads((ROOT / ".keelokit/state.toml").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 3, ""
    spec = state.get("verify", {}).get("shared_seals") if isinstance(state.get("verify"), dict) else None
    if spec is None:
        return 3, ""
    m = SHARED.fullmatch(spec) if isinstance(spec, str) else None
    if not m or ".." in m["branch"] or m["remote"] not in git_lines("remote"):
        return 1, (f"verify: shared seal not used: [verify] shared_seals must be "
                   f'"<remote>/<branch>:<path with {{head}}>" with a remote of this clone (found {spec!r:.80})')
    ref = f"refs/remotes/{m['remote']}/{m['branch']}"
    where = f"{m['remote']}/{m['branch']}:{m['path'].replace('{head}', head)}"
    no = f"verify: shared seal {where} not used"
    if git_lines("status", "--porcelain"):
        return 1, f"{no}: the working tree has changes"
    fetch = subprocess.run(["git", "fetch", "--quiet", m["remote"], f"+refs/heads/{m['branch']}:{ref}"],
                           cwd=ROOT, capture_output=True, text=True)
    if fetch.returncode:
        return 1, f"{no}: can't fetch {m['remote']}/{m['branch']}"
    shown = subprocess.run(["git", "show", f"{ref}:{m['path'].replace('{head}', head)}"], cwd=ROOT,
                           capture_output=True, text=True)
    if shown.returncode:
        return 1, f"{no}: no seal for this commit there"
    try:
        seal = tomllib.loads(shown.stdout)
    except ValueError:
        return 1, f"{no}: not valid TOML"
    checks = [
        (seal.get("head") == head, "its head is another commit"),
        (bool(base) and seal.get("base") == base, "its base is not origin/main now"),
        (type(seal.get("exit")) is int and seal["exit"] == 0, "its exit is not 0"),
        (seal.get("level") in ("all", "changed") and (seal.get("level") == "all" or level != "all"),
         "its level doesn't cover this request" if seal.get("level") in ("all", "changed") else "its level is not all or changed"),
    ]
    failed = [why for ok, why in checks if not ok]
    if failed:
        return 1, f"{no}: {'; '.join(failed)}"
    return 0, (f"verify: commit {head[:7]} already passed a {seal['level']} verify against {base[:7]} "
               f"(shared seal {where}; it is trusted as far as whoever can push to that branch is); not repeated.")


def cmd_shared_seal(args: list[str]) -> int:
    code, message = shared_seal(option(args, "--head"), option(args, "--base"), option(args, "--level", "changed"))
    if message:
        print(message)
    return code


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
    if a[0] == "steps":
        return cmd_steps(a[1:])
    if a[0] == "rerun":
        return cmd_rerun(a[1:])
    if a[0] == "shared-seal":
        return cmd_shared_seal(a[1:])
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
