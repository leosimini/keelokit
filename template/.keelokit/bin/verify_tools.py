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
                                                "steps|inherited|red head|proven packages": what
                                                --rerun-failed runs, the passes it keeps, and from where;
                                                empty steps (and why) when it can't tell = normal verify
    verify_tools.py seal-branch-only REMOTE      (the pre-push hook, its refs on stdin) exit 0 when every
                                                ref pushed to REMOTE is the [verify] shared_seals branch
    verify_tools.py clock-plan --base REF        "<package dir>\t<vitest|jest>\t<test files>" per package, for
                                                the unit tests changed since REF (the zones step)
    verify_tools.py clock-scenarios             "<name>\t<zone>\t<local time>" per scenario of
                                                .keelokit/verify-clock.toml (built-in ones without it)
    verify_tools.py proven REMOTE SHA           exit 0 when SHA passed a clean, full verify here against
                                                REMOTE's main as it is now (the pre-push hook, for a
                                                commit pushed to a branch from another checkout)
    verify_tools.py wip-prefix REMOTE           print [verify] wip_branches (as REMOTE's main sets it), or exit 1
    verify_tools.py wip-record SHA              remember a pushed wip tip in this clone
    verify_tools.py wip-inside REMOTE SHA       exit 0 (and name it) when SHA holds unverified wip work
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
# Steps the routing doesn't decide: they look at every commit (gitleaks scans origin/main..HEAD, the doctor
# reads the whole repo, clock reruns the unit tests), so a pass of theirs never outlives a new file.
UNROUTED = {"secrets", "doctor", "clock"}
# Steps whose result depends on the date, not only on the code: never kept from an earlier run (advisories
# and semgrep's rule packs change, the calendar moves, the doctor's exceptions expire).
TIMED = {"audit", "clock", "doctor", "sast"}
# Steps that look at the whole repo, or at whichever files changed: any change reaches them.
WHOLE_REPO = {"format", "lint", "sast"}
# Steps that run per package: a change inside any package can change what they see (a text an e2e
# asserts, a type a build needs), whatever the routing asks for when that file changes alone.
PER_PACKAGE = {"typecheck", "unit", "integration", "build", "e2e", "e2e-stack", "mutation", "zones"}
NAMES = ["secrets", *STEPS[:3], "doctor", *STEPS[3:], "clock", "zones"]  # clock: the date-bomb rerun, only with --all;
# zones: the changed unit tests at awkward clocks (.keelokit/verify-clock.toml)
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
    ("worker-exit", r"A (jest )?worker process (has failed to exit|was terminated)|signal=SIGTERM",
     "a test worker was stopped (memory, or a handle left open): fewer workers, close what the test opened"),
    ("hook-timeout", r"Hook timed out in \d+ ?ms|Test timed out in \d+ ?ms|Exceeded timeout of \d+ ?ms",
     "a test or hook ran out of time: run that file alone; a busy machine or a slow import in beforeAll, never a longer timeout (FLAKY-1)"),
    ("shared-rows", r"Foreign key constraint (failed|violated)|Unique constraint failed|violates (foreign key|unique) constraint",
     "two tests touched the same rows: each test filters to the rows it created; a global table needs a lock (FLAKY-1)"),
    ("unbuilt-package", r"Cannot find module '@[\w.-]+/[\w.-]+'",
     "a workspace package isn't built (or is stale): build it (pnpm -r build) before the tests that import it"),
    ("unhandled", r"Unhandled (Errors?|Rejection)|window is not defined",
     "every test passed but something threw outside a test: the error above names it (a timer or import that outlived its test)"),
    ("db-exists", r'database "[^"]+" already exists',
     "a throwaway database name was reused: each run (and each call) needs its own name"),
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


API = "apps/api/"  # the template's API, whose integration specs verify.sh runs


def integration_failures(reports: str, red: bool) -> dict:
    """For a red integration step: the spec files that failed (repo-relative), from the Vitest JSON reports
    the step wrote, and whether every report was there to read (`int_complete`). Nothing when it was green."""
    if not red:
        return {}
    failed, complete = set(), bool(reports.split())
    for path in reports.split():
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            results = data["testResults"]
        except (OSError, ValueError, KeyError, TypeError):
            complete = False
            continue
        for t in results if isinstance(results, list) else []:
            if not isinstance(t, dict):
                continue
            bad = t.get("status") == "failed" or any(isinstance(a, dict) and a.get("status") == "failed"
                                                     for a in t.get("assertionResults") or [])
            name = str(t.get("name", "")).replace("\\", "/")
            if bad and API in name:
                failed.add(API + name.rsplit(API, 1)[1])
    return {"failed_specs": sorted(failed), "int_complete": complete and bool(failed)}


def integration_narrowing(last: dict, files: list[str]) -> dict | None:
    """When the last run's integration step went red with every failed spec on record, and the files changed
    since are ones `vitest related` can follow (the API's own sources and specs, docs, other apps), the
    integration step reruns only: the specs that failed, the specs the fix changed, and those related to the
    sources it changed. None (the whole suite) for anything that reaches every spec: the API's config,
    Prisma schema and migrations, its test setup, seeds and fixtures, shared packages, root manifests."""
    if ("integration" not in last.get("failed_steps", []) or last.get("int_complete") is not True
            or not isinstance(last.get("failed_specs"), list) or not last["failed_specs"]):
        return None
    specs, sources = set(last["failed_specs"]), set()
    for f in files:
        if f.startswith(API):
            inner = f[len(API):]
            if not inner.startswith("src/") or re.search(r"(^|/)(test|tests|testing|setup|seeds?|fixtures?)(/|[.-])", inner):
                return None
            (specs if f.endswith(".integration.spec.ts") else sources).add(f)
        elif f.startswith("packages/") or not (f.startswith("apps/") or f.endswith(".md") or f.startswith(("docs/", "backlog/"))):
            return None
    return {"specs": sorted(s[len(API):] for s in specs), "related": sorted(s[len(API):] for s in sources)}


def proven_packages(packages: list[str], kept_from: str) -> list[str] | None:
    """Where every step this run counts as passed holds. A run's own steps hold on its packages; a rerun's
    kept passes hold where the red run proved them: `kept_from` is "" for a run that kept nothing, "?" when
    unknown, else "@" followed by the list (so an empty list is not mistaken for "kept nothing")."""
    if kept_from == "?":
        return None
    if not kept_from.startswith("@"):
        return packages
    return sorted(set(packages) & set(kept_from[1:].split()))


def in_a_package(path: str) -> bool:
    """A file under apps/ or packages/, or whose nearest package.json isn't the root's."""
    if path.startswith(("apps/", "packages/")):
        return True
    folder = (ROOT / path).parent
    while folder != ROOT and ROOT in folder.parents:
        if (folder / "package.json").is_file():
            return True
        folder = folder.parent
    return False


def cmd_record(args: list[str]) -> int:
    """One JSON line per run. Besides the arguments, from the environment: VERIFY_BASE (the base's sha),
    VERIFY_PLANNED / VERIFY_PASSED / VERIFY_FAILED_STEPS (step names), VERIFY_SCOPE (the --packages /
    --filter selectors, if any), VERIFY_PACKAGES (pnpm's parseable list of the packages in scope),
    VERIFY_STEP_PACKAGES ("step=dir " pairs for steps whose packages aren't the run's), VERIFY_PARTIAL and
    VERIFY_CLEAN (the tree had no uncommitted or untracked changes when the run started), VERIFY_SINCE (it
    compared with a ref given by --since, not origin/main), and for a narrowed
    rerun VERIFY_INHERITED (passes kept from the red run), VERIFY_PROVEN_PACKAGES (where those were proven),
    VERIFY_RERUN_OF (the first red run of the chain) and VERIFY_COMPOSITE_OF (the same head, when the runs
    together sealed the commit)."""
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
    packages = sorted({relative(l) for l in env("VERIFY_PACKAGES", "").splitlines() if l.strip()})
    entry = {
        "t": int(time.time()), "head": head, "base": env("VERIFY_BASE", ""), "level": level, "result": result,
        "rc": int(rc or 0), "partial": env("VERIFY_PARTIAL") == "true", "scope": " ".join(env("VERIFY_SCOPE", "").split()),
        "steps": [[n, int(s)] for s, _, n in (l.partition("|") for l in steps.splitlines()) if s.isdigit()],
        "failed": [l for l in failed.splitlines() if l],
        "clean": env("VERIFY_CLEAN") == "true", "since": env("VERIFY_SINCE") == "true",
        "inherited": env("VERIFY_INHERITED", "").split(),
        "composite_of": env("VERIFY_COMPOSITE_OF") or None,
        "rerun_of": env("VERIFY_RERUN_OF") or None,
        "proven_packages": proven_packages(packages, env("VERIFY_PROVEN_PACKAGES", "")),
        "planned": env("VERIFY_PLANNED", "").split(),
        "passed": [n for n in env("VERIFY_PASSED", "").split() if n not in env("VERIFY_FAILED_STEPS", "").split()],
        "failed_steps": env("VERIFY_FAILED_STEPS", "").split(),
        **integration_failures(env("VERIFY_INT_REPORT", ""), "integration" in env("VERIFY_FAILED_STEPS", "").split()),
        "packages": packages,
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


def rerun_steps(history: str, head: str, base: str, scope: str, level: str) -> tuple[list[str], str, dict]:
    """(steps to run, why, what it builds on). No steps means: run the normal verify, for the reason given.
    The last run of this commit or an ancestor decides; only a red one with a clean tree and the same base,
    scope and level can be narrowed to what it didn't pass plus what the files changed since then call for.
    The third value says which passes still hold (`inherited`), whose they are (`head`) and on which
    packages they were proven (`packages`, None when unknown): what a composite seal needs."""
    try:
        lines = Path(history).read_text(encoding="utf-8").splitlines()
    except OSError:
        return [], "no verify history in this clone", {}
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
        return [], "no earlier verify of this commit or one before it", {}
    if last.get("result") == "pass":
        return [], f"the last verify of {last['head'][:7]} passed: nothing failed", {}
    if not all(isinstance(last.get(k), list) for k in ("planned", "passed", "failed_steps")) or not last["planned"]:
        return [], "the last red run recorded no steps (an older verify)", {}
    if last.get("base") != base:
        return [], "origin/main (or --since) is not where it was for that run", {}
    if " ".join(scope.split()) != last.get("scope", ""):
        return [], "that run covered other packages (--packages / --filter differ)", {}
    if last.get("level") != level:
        return [], ("that run was --all: rerun it with --all" if last.get("level") == "all"
                    else "that run was not --all, so its passes don't cover an --all request"), {}
    if last.get("clean") is not True:
        return [], "that run saw uncommitted or untracked changes, so what passed is not this commit's", {}
    setup = [s for s in last["failed_steps"] if s not in NAMES]
    if setup:
        return [], f"it stopped in a setup step ({', '.join(setup)})", {}
    inherited = last.get("inherited") if isinstance(last.get("inherited"), list) else []
    passed = (set(last["passed"]) | set(inherited)) - set(last["failed_steps"])
    todo = {s for s in last["planned"] if s in NAMES and s not in passed}
    files = changed_files(last["head"])
    if files is None:
        return [], f"{last['head'][:7]} is not in this clone", {}
    steps, unknown = plan_for(files, load_routes())
    narrow = integration_narrowing(last, files)
    if "all" in steps:
        if unknown or narrow is None:
            return [], (f"{len(unknown)} file(s) changed since then match no route" if unknown
                        else "the files changed since then call for every step"), {}
        # Code changed: every step runs again, but the red integration step only on what the fix reaches.
        steps = [s for s in last["planned"] if s in NAMES]
    todo |= set(steps)
    if files:  # a new file reaches the steps the routing doesn't decide, and those that read the whole repo
        todo |= {s for s in UNROUTED | WHOLE_REPO if s in last["planned"]}
    if any(in_a_package(f) for f in files):  # and a file inside a package, everything that runs per package
        todo |= {s for s in PER_PACKAGE if s in last["planned"]}
    todo |= {s for s in TIMED if s in last["planned"]}  # advisories and the calendar move on their own
    if not todo:
        return [], "nothing failed or was left unrun", {}
    if "proven_packages" in last:
        proven = last["proven_packages"] if isinstance(last["proven_packages"], list) else None
    else:
        proven = last.get("packages") if isinstance(last.get("packages"), list) else None
    kept = sorted(passed & set(NAMES) - todo)
    root = last.get("rerun_of") if isinstance(last.get("rerun_of"), str) and last.get("rerun_of") else last["head"]
    return [n for n in NAMES if n in todo], "", {"inherited": kept, "head": root, "packages": proven,
                                                  "int": narrow if "integration" in todo else None}


def cmd_rerun(args: list[str]) -> int:
    steps, why, base_on = rerun_steps(args[0] if args else "", option(args, "--head"), option(args, "--base"),
                                      option(args, "--scope"), option(args, "--level", "changed"))
    if not steps:
        print(f"verify --rerun-failed: can't narrow the run ({why}): running the normal verify.", file=sys.stderr)
        print("")
        return 0
    packages = base_on["packages"]
    narrow = base_on.get("int")
    print("|".join([" ".join(steps), " ".join(base_on["inherited"]), base_on["head"],
                    "?" if packages is None else "@" + " ".join(packages),
                    "" if narrow is None else "@" + " ".join(narrow["specs"]),
                    "" if narrow is None else " ".join(narrow["related"])]))
    return 0


def cmd_covers(args: list[str]) -> int:
    """covers PLANNED RAN INHERITED PROVEN PACKAGES: exit 0 when the steps this rerun ran plus the passes it
    inherited are the whole plan, and every package now in scope is one the inherited passes were proven
    on; otherwise print what is missing and exit 1. PROVEN "?" (unknown) never covers."""
    planned, ran, inherited, proven, packages = (args + [""] * 5)[:5]
    missing = sorted(set(planned.split()) - set(ran.split()) - set(inherited.split()))
    if missing:
        print(f"the steps {', '.join(missing)} passed in no run of this diff")
        return 1
    if inherited.split():
        if not proven.startswith("@"):
            print("the red run recorded no packages")
            return 1
        now = {relative(l) for l in packages.splitlines() if l.strip()}
        outside = sorted(now - set(proven[1:].split()))
        if outside:
            print(f"{', '.join(outside)} came into scope after the red run, whose passes didn't cover it")
            return 1
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


# Branches a seal branch can never be: a push to them carries code.
NEVER_SEAL_BRANCHES = {"main", "master", "release"}


def seal_branch_only(remote: str, refs: str) -> bool:
    """True when the push (git's pre-push stdin: "<local ref> <local sha> <remote ref> <remote sha>" per
    line) goes to `remote` and updates nothing but the [verify] shared_seals branch there: Harbor's
    logbook, which holds seals and no code, so there's nothing to verify. Checked, not assumed:
    - the key is read from `<remote>/main`'s .keelokit/state.toml, never from an uncommitted edit;
    - every commit the push brings beyond the remote's tip (git's own remote sha) holds only regular
      files under the seals' folder, merges included;
    - every seal file in those commits that the remote's tip doesn't already hold, byte for byte, names
      a commit with a clean, full, green verify against origin/main in this clone, at the seal's level
      and with the seal's base: the exception carries seals, it can't mint one for a commit that never
      passed here.
    Anything else, an empty push included, is False: the hook runs the verify."""
    # The remote's main as it is now, not a tracking ref a local edit could have moved (verify.sh does the same).
    subprocess.run(["git", "fetch", "--quiet", remote, "main"], cwd=ROOT, capture_output=True)
    shown = subprocess.run(["git", "show", f"refs/remotes/{remote}/main:.keelokit/state.toml"], cwd=ROOT,
                           capture_output=True, text=True)
    try:
        state = tomllib.loads(shown.stdout) if shown.returncode == 0 else {}
    except ValueError:
        return False
    spec = state.get("verify", {}).get("shared_seals") if isinstance(state.get("verify"), dict) else None
    m = SHARED.fullmatch(spec) if isinstance(spec, str) else None
    if not m or m["remote"] != remote or ".." in m["branch"] or m["branch"] in NEVER_SEAL_BRANCHES:
        return False
    folder = m["path"].split("/", 1)[0] + "/" if "/" in m["path"] else None
    lines = [l.split() for l in refs.splitlines() if l.strip()]
    if not folder or not lines or not all(len(l) == 4 and l[2] == f"refs/heads/{m['branch']}" for l in lines):
        return False
    seal_file = re.compile(re.escape(m["path"]).replace(re.escape("{head}"), "([0-9a-f]{40}|[0-9a-f]{64})") + r"\Z")
    main = git_lines("rev-parse", "--verify", "--quiet", f"refs/remotes/{remote}/main")
    green = green_runs()
    for _, sha, _, remote_sha in lines:
        if set(sha) == {"0"}:  # a deletion pushes no commits
            continue
        known = set(remote_sha) != {"0"}
        if known and subprocess.run(["git", "cat-file", "-e", f"{remote_sha}^{{commit}}"], cwd=ROOT).returncode:
            return False  # the remote's tip isn't here: what the push adds can't be told
        new = subprocess.run(["git", "rev-list", sha, *(["--not", remote_sha] if known else [])], cwd=ROOT,
                             capture_output=True, text=True)
        if new.returncode:
            return False
        have = tree(remote_sha) if known else {}
        for commit in new.stdout.split():
            entries = tree(commit)
            if entries is None or have is None:
                return False
            for path, (mode, blob) in entries.items():
                if not path.startswith(folder) or mode not in ("100644", "100755"):
                    return False  # code, a symlink or a submodule: verify
                hit = seal_file.match(path)
                if hit is None or have.get(path) == (mode, blob):
                    continue
                try:
                    seal = tomllib.loads(subprocess.run(["git", "cat-file", "blob", blob], cwd=ROOT,
                                                        capture_output=True, text=True).stdout)
                except ValueError:
                    return False
                level, base = seal.get("level"), seal.get("base")
                if not main or base != main[0] or (hit[1], base, level) not in green:
                    return False
    return True


# Clocks where date code breaks: a day that is already tomorrow in UTC, month and year ends, a leap
# day, the hour that doesn't exist and the one that happens twice. Local times, in each zone.
CLOCKS = [
    ("month-end-late", "America/Los_Angeles", "2027-01-31 23:30:00"),
    ("year-end-late", "America/Los_Angeles", "2027-12-31 23:30:00"),
    ("leap-day-early", "Europe/Berlin", "2028-02-29 00:30:00"),
    ("dst-gap", "America/New_York", "2027-03-14 02:30:00"),
    ("dst-overlap", "Europe/Berlin", "2027-10-31 02:30:00"),
    ("midnight-east", "Australia/Sydney", "2027-07-01 00:30:00"),
]
UNIT_TEST = re.compile(r"\.(test|spec)\.[cm]?[jt]sx?$")


def clock_scenarios() -> list[tuple[str, str, str]]:
    """.keelokit/verify-clock.toml's [[scenario]] (name, zone, at = "YYYY-MM-DD HH:MM:SS" local time), or
    the built-in CLOCKS when the file is missing, unreadable or names none."""
    try:
        data = tomllib.loads((ROOT / ".keelokit/verify-clock.toml").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return CLOCKS
    out = []
    for s in data.get("scenario", []) if isinstance(data.get("scenario"), list) else []:
        if (isinstance(s, dict) and all(isinstance(s.get(k), str) for k in ("name", "zone", "at"))
                and re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d", s["at"]) and re.fullmatch(r"[\w+/-]+", s["zone"])):
            out.append((s["name"], s["zone"], s["at"]))
    return out or CLOCKS


def clock_plan(base: str) -> list[tuple[str, str, list[str]]]:
    """The unit tests changed since `base` (not integration, not e2e), grouped by the package that holds
    them and its runner (its `test` script starts with vitest or jest; any other is left out)."""
    files = changed_files(base) or []
    groups: dict[str, tuple[str, list[str]]] = {}
    for f in files:
        if not UNIT_TEST.search(f) or ".integration." in f or "/e2e/" in f or not (ROOT / f).is_file():
            continue
        folder = (ROOT / f).parent
        while folder != ROOT and not (folder / "package.json").is_file():
            folder = folder.parent
        if folder == ROOT:
            continue
        try:
            script = json.loads((folder / "package.json").read_text(encoding="utf-8")).get("scripts", {}).get("test", "")
        except (OSError, ValueError, AttributeError):
            continue
        runner = next((r for r in ("vitest", "jest") if isinstance(script, str) and script.strip().startswith(r)), None)
        if runner:
            dir_ = folder.relative_to(ROOT).as_posix()
            groups.setdefault(dir_, (runner, []))[1].append((ROOT / f).relative_to(folder).as_posix())
    return [(d, r, sorted(fs)) for d, (r, fs) in sorted(groups.items())]


def proven(remote: str, sha: str) -> bool:
    """`sha` has a clean, full, green verify in this clone's history (green_runs) against `remote`'s main
    as it is after a fetch: the same proof a seal needs, for a commit that isn't checked out."""
    subprocess.run(["git", "fetch", "--quiet", remote, "main"], cwd=ROOT, capture_output=True)
    main = git_lines("rev-parse", "--verify", "--quiet", f"refs/remotes/{remote}/main")
    return bool(main) and any(head == sha and base == main[0] for head, base, _ in green_runs())


WIP_PREFIX = re.compile(r"[a-z0-9][\w.-]*/")


def remote_state(remote: str) -> dict:
    """.keelokit/state.toml as `remote`'s main holds it after a fetch: settings that loosen the push gate
    are read from there, never from an uncommitted or unpushed edit."""
    subprocess.run(["git", "fetch", "--quiet", remote, "main"], cwd=ROOT, capture_output=True)
    shown = subprocess.run(["git", "show", f"refs/remotes/{remote}/main:.keelokit/state.toml"], cwd=ROOT,
                           capture_output=True, text=True)
    try:
        return tomllib.loads(shown.stdout) if shown.returncode == 0 else {}
    except ValueError:
        return {}


def wip_prefix(remote: str) -> str | None:
    """[verify] wip_branches ("wip/"): branches under it carry unfinished work between sessions, run no
    verify and never land. None when the key is absent or not a branch-name prefix ending in "/"."""
    verify = remote_state(remote).get("verify")
    prefix = verify.get("wip_branches") if isinstance(verify, dict) else None
    return prefix if isinstance(prefix, str) and WIP_PREFIX.fullmatch(prefix) else None


def wip_tips_file() -> Path:
    common = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    return ROOT / common / "keelokit-wip-tips"


def wip_inside(remote: str, sha: str) -> str | None:
    """The first wip tip (a <remote>/<prefix>* branch, or a tip this clone pushed and remembers, so
    deleting the branch doesn't hide it) that `sha` holds, `remote`'s main lacks, and no clean, full,
    green verify here proved. None when there's none, or wip branches are off."""
    prefix = wip_prefix(remote)
    if prefix is None:
        return None
    main = git_lines("rev-parse", "--verify", "--quiet", f"refs/remotes/{remote}/main")
    tips = git_lines("for-each-ref", "--format=%(objectname)", f"refs/remotes/{remote}/{prefix}")
    try:
        tips += [l.strip() for l in wip_tips_file().read_text().splitlines() if l.strip()]
    except OSError:
        pass
    proven_here = {head for head, base, _ in green_runs() if main and base == main[0]}
    for tip in dict.fromkeys(tips):
        if tip in proven_here or (main and is_ancestor(tip, main[0])):
            continue
        if is_ancestor(tip, sha):
            return tip
    return None


def tree(commit: str) -> dict[str, tuple[str, str]] | None:
    """path → (mode, blob) of every entry in a commit's tree, or None when git can't read it."""
    out = subprocess.run(["git", "ls-tree", "-r", "--full-tree", commit], cwd=ROOT, capture_output=True, text=True)
    if out.returncode:
        return None
    entries = {}
    for line in out.stdout.splitlines():
        meta, _, path = line.partition("\t")
        mode, _, obj = meta.split(" ", 2)
        entries[path] = (mode, obj)
    return entries


def green_runs() -> set[tuple[str, str, str]]:
    """(commit, base, level) of every clean, full, green verify against origin/main in this clone's
    history: no --steps/--packages/--rerun-failed narrowing (partial), no --since, no uncommitted change.
    An "all" pass covers "changed" too."""
    common = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    try:
        lines = (ROOT / common / "keelokit-verify.history").read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError):
        return set()
    green = set()
    for line in lines:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if (isinstance(e, dict) and e.get("result") == "pass" and e.get("partial") is False and e.get("clean") is True
                and e.get("since") is False and isinstance(e.get("head"), str) and isinstance(e.get("base"), str)):
            for level in ({"all", "changed"} if e.get("level") == "all" else {"changed"}):
                green.add((e["head"], e["base"], level))
    return green


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
    if a[0] == "covers":
        return cmd_covers(a[1:])
    if a[0] == "wip-prefix" and len(a) == 2:
        prefix = wip_prefix(a[1])
        if prefix:
            print(prefix)
        return 0 if prefix else 1
    if a[0] == "wip-record" and len(a) == 2:
        with open(wip_tips_file(), "a", encoding="utf-8") as f:
            f.write(a[1] + "\n")
        return 0
    if a[0] == "wip-inside" and len(a) == 3:
        tip = wip_inside(a[1], a[2])
        if tip:
            print(tip)
        return 0 if tip else 1
    if a[0] == "clock-plan":
        for dir_, runner, files in clock_plan(option(a, "--base", "origin/main")):
            print(f"{dir_}\t{runner}\t{' '.join(files)}")
        return 0
    if a[0] == "clock-scenarios":
        for name, zone, at in clock_scenarios():
            print(f"{name}\t{zone}\t{at}")
        return 0
    if a[0] == "proven" and len(a) == 3:
        return 0 if proven(a[1], a[2]) else 1
    if a[0] == "seal-branch-only" and len(a) == 2:
        return 0 if seal_branch_only(a[1], sys.stdin.read()) else 1
    if a[0] == "shared-seal":
        return cmd_shared_seal(a[1:])
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
