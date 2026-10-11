#!/usr/bin/env python3
"""CI health for the main branch and the time budget of each job. Stdlib only (Python 3.11+).

    python3 .keelokit/bin/ci.py health [--branch main] [--workflow CI]
        Runs of main since its last green one. A cancelled run is NOT a green one: two or more in a
        row without a green, or a failure / timeout at the head, is an alarm (exit 1).
    python3 .keelokit/bin/ci.py budget [RUN_ID]
        Each job's time against its `timeout-minutes`; warns above 2/3 (exit 0; --strict: exit 1).
    python3 .keelokit/bin/ci.py jobs [RUN_ID]
        Which job and which step failed, cancelled or timed out. Read this before the logs.
    python3 .keelokit/bin/ci.py summary [--tests DIR]
        `budget` plus the 10 slowest tests found in DIR (vitest / Playwright JSON reports), as
        Markdown; written to $GITHUB_STEP_SUMMARY when set. The CI's last job runs it.
    python3 .keelokit/bin/ci.py dispatch [--ref main]
        Starts the CI by hand (workflow_dispatch). docs/ci.md says what to do on a 403.

Runs come from the GitHub API with $GITHUB_TOKEN / $GH_TOKEN (`actions: read`; `dispatch` needs
`actions: write`), or from `gh api` when the token is absent. `--runs-file` / `--jobs-file` read the
same JSON from disk (tests, offline). RUN_ID defaults to $GITHUB_RUN_ID, else the latest run.
"""
import sys

if sys.version_info < (3, 11):
    print(f"Keelokit needs Python 3.11+ (found {sys.version.split()[0]}); ci.py is off.")
    sys.exit(1)

import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402
from datetime import datetime  # noqa: E402
from pathlib import Path  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
RED = {"failure", "timed_out", "startup_failure"}
NOT_GREEN = RED | {"cancelled", "action_required"}
BUDGET_SHARE = 2 / 3
FORBIDDEN = (
    "403 from the GitHub API. The token lacks a permission: reading runs needs `actions: read`, "
    "starting one `actions: write`. The integration's own token often has neither. Options "
    "(docs/ci.md): a fine-grained token with Actions read/write in $GITHUB_TOKEN, the scheduled "
    "trigger already in the workflow, or run `pnpm verify --all` locally, which is the same gate."
)


def repo_slug() -> str | None:
    if slug := os.environ.get("GITHUB_REPOSITORY"):
        return slug
    try:
        url = subprocess.run(["git", "remote", "get-url", "origin"], cwd=ROOT, capture_output=True, text=True).stdout
    except OSError:
        return None
    m = re.search(r"github\.com[:/]+([^/\s]+/[^/\s]+?)(?:\.git)?\s*$", url)
    return m.group(1) if m else None


def api(path: str, method: str = "GET", body: dict | None = None):
    """JSON from the GitHub API, or exit 2 with the reason (a 403 says what to do)."""
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        req = urllib.request.Request(
            f"https://api.github.com{path}", method=method, data=json.dumps(body).encode() if body else None,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                raw = res.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            sys.exit(f"ci.py: {FORBIDDEN}" if e.code == 403 else f"ci.py: GitHub API {e.code} for {path}")
        except OSError as e:
            sys.exit(f"ci.py: cannot reach the GitHub API ({e})")
    cmd = ["gh", "api", "-X", method, path] + (["--input", "-"] if body else [])
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, input=json.dumps(body) if body else None, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        sys.exit("ci.py: no $GITHUB_TOKEN / $GH_TOKEN and no working `gh`; see docs/ci.md")
    if res.returncode:
        sys.exit(f"ci.py: {FORBIDDEN}" if "403" in res.stderr else f"ci.py: gh api failed: {res.stderr.strip()[:200]}")
    return json.loads(res.stdout) if res.stdout.strip() else {}


def load_runs(args: list[str], branch: str) -> list[dict]:
    if f := opt(args, "--runs-file"):
        data = json.loads(Path(f).read_text())
    else:
        slug = repo_slug() or sys.exit("ci.py: cannot tell the repository (set GITHUB_REPOSITORY)")
        data = api(f"/repos/{slug}/actions/runs?branch={branch}&per_page=40")
    runs = data["workflow_runs"] if isinstance(data, dict) else data
    return sorted(runs, key=lambda r: r.get("created_at", ""), reverse=True)


def opt(args: list[str], name: str, default: str | None = None) -> str | None:
    return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else default


def health(args: list[str]) -> int:
    branch, workflow = opt(args, "--branch", "main"), opt(args, "--workflow", "CI")
    runs = [r for r in load_runs(args, branch)
            if r.get("status", "completed") == "completed" and (not workflow or r.get("name") == workflow)]
    if not runs:
        print(f"CI {branch}: no finished runs yet")
        return 0
    streak = []
    for r in runs:
        if r.get("conclusion") == "success":
            break
        if r.get("conclusion") in ("skipped", "neutral"):
            continue
        streak.append(r)
    if not streak:
        print(f"CI {branch}: green (last run #{runs[0].get('run_number', '?')})")
        return 0
    kinds: dict[str, int] = {}
    for r in streak:
        kinds[r["conclusion"]] = kinds.get(r["conclusion"], 0) + 1
    count = ", ".join(f"{n} {k}" for k, n in kinds.items())
    since = "no green run in the last %d" % len(runs) if len(streak) == len(runs) else f"last green before #{streak[-1].get('run_number', '?')}"
    head = streak[0]["conclusion"]
    alarm = head in RED or len(streak) >= 2
    print(f"CI {branch}: {'ALARM' if alarm else 'watch'} — {len(streak)} run(s) without a green ({count}); {since}.")
    print("  A cancelled run is not a green one: it is usually a timeout or a superseded run. "
          "`python3 .keelokit/bin/ci.py jobs` says which job and step.")
    return 1 if alarm else 0


def workflow_budgets() -> dict[str, float]:
    """Job display name (or id) → timeout-minutes, read from .github/workflows (jobs without one are left out)."""
    out: dict[str, float] = {}
    for path in sorted((ROOT / ".github/workflows").glob("*.y*ml")):
        text = path.read_text(errors="replace")
        jobs = re.search(r"(?ms)^jobs:[ \t]*(?:#[^\n]*)?\n(.*?)(?=^[^\s#]|\Z)", text)
        indent = jobs and re.search(r"(?m)^( +)[^\s#]", jobs.group(1))
        if not indent:
            continue
        n = len(indent.group(1))
        for m in re.finditer(rf"(?ms)^ {{{n}}}([\w-]+):[ \t]*(?:#[^\n]*)?\n(.*?)(?=^ {{{n}}}[\w-]+:|\Z)", jobs.group(1)):
            body = m.group(2)
            t = re.search(rf"(?m)^ {{{n + 2}}}timeout-minutes:\s*(\d+)", body)
            name = re.search(rf"(?m)^ {{{n + 2}}}name:\s*['\"]?(.+?)['\"]?\s*$", body)
            if t:
                out[m.group(1)] = out[name.group(1)] = float(t.group(1))
    return out


def seconds(job: dict) -> float | None:
    try:
        a, b = (datetime.fromisoformat(job[k].replace("Z", "+00:00")) for k in ("started_at", "completed_at"))
    except (KeyError, TypeError, AttributeError, ValueError):
        return None
    return max((b - a).total_seconds(), 0)


def load_jobs(args: list[str], positional: str | None) -> list[dict]:
    if f := opt(args, "--jobs-file"):
        data = json.loads(Path(f).read_text())
        return data["jobs"] if isinstance(data, dict) else data
    slug = repo_slug() or sys.exit("ci.py: cannot tell the repository (set GITHUB_REPOSITORY)")
    run_id = positional or os.environ.get("GITHUB_RUN_ID")
    if not run_id:
        runs = load_runs(args, opt(args, "--branch", "main"))
        run_id = str(runs[0]["id"]) if runs else sys.exit("ci.py: no runs found")
    return api(f"/repos/{slug}/actions/runs/{run_id}/jobs?per_page=100")["jobs"]


def positional(args: list[str]) -> str | None:
    values = {"--branch", "--workflow", "--runs-file", "--jobs-file", "--tests", "--ref"}
    for i, a in enumerate(args):
        if not a.startswith("-") and (i == 0 or args[i - 1] not in values):
            return a
    return None


def budget_rows(jobs: list[dict]) -> tuple[list[tuple[str, float | None, float | None, str]], list[str]]:
    budgets = workflow_budgets()
    rows, flagged = [], []
    for j in jobs:
        if j.get("status") not in (None, "completed"):
            continue
        used, limit = seconds(j), budgets.get(j.get("name", ""))
        mark = ""
        if j.get("conclusion") == "cancelled" and used is not None and limit and used >= limit * 60 * 0.95:
            mark = "cancelled AT its timeout"
        elif used is not None and limit and used > limit * 60 * BUDGET_SHARE:
            mark = f"over 2/3 of its {limit:.0f} min"
        if mark:
            flagged.append(f"{j['name']}: {mark}")
        rows.append((j.get("name", "?"), used, limit, mark))
    return rows, flagged


def fmt_min(s: float | None) -> str:
    return "—" if s is None else f"{int(s // 60)}m{int(s % 60):02d}s"


ADVICE = ("Do not raise the timeout: split the job by kind of test or shard it "
          "(docs/ci.md). A job that nears its timeout turns into 'cancelled', not 'failed'.")


def budget(args: list[str]) -> int:
    rows, flagged = budget_rows(load_jobs(args, positional(args)))
    for name, used, limit, mark in rows:
        print(f"  {name:<46} {fmt_min(used):>8} / {limit:.0f} min  {mark}" if limit
              else f"  {name:<46} {fmt_min(used):>8} / no timeout set  {mark}")
    for f in flagged:
        print(f"WARN {f}")
    if flagged:
        print(ADVICE)
    return 1 if flagged and "--strict" in args else 0


def slowest(tests_dir: Path, top: int = 10) -> list[tuple[float, str]]:
    found: list[tuple[float, str]] = []
    for path in sorted(tests_dir.rglob("*.json")) if tests_dir.is_dir() else []:
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        for tr in data.get("testResults", []) if isinstance(data, dict) else []:  # vitest / jest
            for a in tr.get("assertionResults", []):
                found.append((float(a.get("duration") or 0), a.get("fullName") or a.get("title", "?")))

        def walk(suite: dict, trail: str) -> None:  # Playwright
            trail = f"{trail} › {suite['title']}".strip(" ›") if suite.get("title") else trail
            for spec in suite.get("specs", []):
                ms = sum(r.get("duration", 0) for t in spec.get("tests", []) for r in t.get("results", []))
                found.append((float(ms), f"{trail} › {spec.get('title', '?')}".strip(" ›")))
            for s in suite.get("suites", []):
                walk(s, trail)
        for s in data.get("suites", []) if isinstance(data, dict) else []:
            walk(s, "")
    return sorted(found, reverse=True)[:top]


def summary(args: list[str]) -> int:
    rows, flagged = budget_rows(load_jobs(args, positional(args)))
    out = ["## Time per job", "", "| Job | Time | Timeout | Share |", "|---|---:|---:|---:|"]
    for name, used, limit, mark in rows:
        share = f"{used / (limit * 60):.0%}" if used is not None and limit else "—"
        out.append(f"| {name} | {fmt_min(used)} | {f'{limit:.0f} min' if limit else 'none'} | {share}{' ⚠ ' + mark if mark else ''} |")
    if flagged:
        out += ["", f"**Warning:** {len(flagged)} job(s) near their timeout. {ADVICE}"]
    tests = slowest(Path(opt(args, "--tests", "ci-timings") or "ci-timings"))
    out += ["", "## 10 slowest tests", ""]
    out += ([f"{i}. {ms / 1000:.1f}s — {name}" for i, (ms, name) in enumerate(tests, 1)] if tests
            else ["No timing reports were uploaded by the test jobs."])
    text = "\n".join(out) + "\n"
    if path := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(path, "a") as f:
            f.write(text)
    print(text)
    return 0


def jobs_cmd(args: list[str]) -> int:
    jobs = load_jobs(args, positional(args))
    bad = [j for j in jobs if j.get("conclusion") in NOT_GREEN]
    if not bad:
        print("No job failed, was cancelled or timed out.")
        return 0
    for j in bad:
        steps = [s for s in j.get("steps", []) if s.get("conclusion") in NOT_GREEN]
        step = ", ".join(f"step {s.get('number', '?')} “{s['name']}” ({s['conclusion']})" for s in steps) or "no step marked (cancelled before or between steps)"
        print(f"- {j['name']}: {j['conclusion']} — {step}")
    print("Read the failing step's log, not the service containers' (a database logs expected errors "
          "while it starts and while tests probe constraints).")
    return 1


def dispatch(args: list[str]) -> int:
    slug = repo_slug() or sys.exit("ci.py: cannot tell the repository (set GITHUB_REPOSITORY)")
    api(f"/repos/{slug}/actions/workflows/ci.yml/dispatches", "POST", {"ref": opt(args, "--ref", "main")})
    print("CI started (workflow_dispatch). `python3 .keelokit/bin/ci.py health` follows it.")
    return 0


COMMANDS = {"health": health, "budget": budget, "jobs": jobs_cmd, "summary": summary, "dispatch": dispatch}


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help") or args[0] not in COMMANDS:
        print(__doc__)
        return 0 if args[:1] in ([], ["-h"], ["--help"]) else 2
    return COMMANDS[args[0]](args[1:])


if __name__ == "__main__":
    sys.exit(main())
