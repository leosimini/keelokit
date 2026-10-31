#!/usr/bin/env python3
"""What the process cost and where it hurt, from what it already records. Stdlib only.

    report.py [--since 7d|24h|2026-10-01] [--md]

(a) verify runs, reds and their known causes, and the time per step, from the git directory's
keelokit-verify.history; (b) pieces per convoy and how many are ready, from the coord/board branch (when
the repository has one); (c) escapes in docs/escapes.md, by class and how many repeated a class the log
already had; (d) review rounds per story. Tokens per role are NOT here: nothing in the repository records
them, and an estimate written down as a measurement is worse than a blank. The report says so.
"""
import sys

if sys.version_info < (3, 11):
    sys.exit(f"Keelokit needs Python 3.11+ (found {sys.version.split()[0]})")

import json  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def git(*a: str) -> str:
    r = subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def window(spec: str) -> int:
    m = re.fullmatch(r"(\d+)([hd])", spec)
    if m:
        return int(time.time()) - int(m.group(1)) * (3600 if m.group(2) == "h" else 86400)
    try:
        return int(time.mktime(time.strptime(spec, "%Y-%m-%d")))
    except ValueError:
        sys.exit("report: --since is 24h, 7d or a date like 2026-10-01")


def mins(s: float) -> str:
    return f"{int(s) // 60}m{int(s) % 60:02d}s"


def verify_section(since: int) -> list[str]:
    common = Path((ROOT / git("rev-parse", "--git-common-dir").strip()).resolve())
    runs = []
    try:
        for line in (common / "keelokit-verify.history").read_text().splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("t", 0) >= since:
                runs.append(e)
    except OSError:
        pass
    out = ["## Verify", ""]
    if not runs:
        return out + ["No verify runs recorded in this clone for the period (the record lives in the git directory of each clone).", ""]
    red = [r for r in runs if r["result"] != "pass"]
    out.append(f"- {len(runs)} runs ({sum(1 for r in runs if r['level'] == 'all')} full), {len(red)} red.")
    causes: dict[str, int] = {}
    for r in red:
        for c in r.get("causes") or ["unclassified"]:
            causes[c] = causes.get(c, 0) + 1
    if causes:
        out.append("- Reds by cause: " + ", ".join(f"{c} ×{n}" for c, n in sorted(causes.items(), key=lambda kv: -kv[1])) + ".")
    steps: dict[str, list[int]] = {}
    for r in runs:
        for name, secs in r.get("steps", []):
            steps.setdefault(name, []).append(secs)
    if steps:
        out += ["", "| Step | Runs | Average | Longest |", "|---|---:|---:|---:|"]
        for name, v in sorted(steps.items(), key=lambda kv: -sum(kv[1]))[:12]:
            out.append(f"| {name} | {len(v)} | {mins(sum(v) / len(v))} | {mins(max(v))} |")
    failed_steps: dict[str, int] = {}
    for r in red:
        for s in r.get("failed", []):
            failed_steps[s] = failed_steps.get(s, 0) + 1
    if failed_steps:
        out += ["", "Steps that failed under --keep-going: " + ", ".join(f"{s} ×{n}" for s, n in failed_steps.items()) + "."]
    return out + [""]


def convoy_section() -> list[str]:
    out = ["## Convoys", ""]
    subprocess.run(["git", "fetch", "-q", "origin", "coord/board"], cwd=ROOT, capture_output=True)
    raw = git("show", "origin/coord/board:STATE.json")
    if not raw:
        return out + ["No logbook branch (`coord/board`) yet.", ""]
    state = json.loads(raw)
    for n, c in sorted(state.get("convoys", {}).items(), key=lambda kv: int(kv[0])):
        ready = sum(1 for p in c["pieces"].values() if p.get("state") == "lista")
        out.append(f"- Convoy {n}: {c.get('status')}, {ready}/{len(c['pieces'])} pieces ready"
                   + (f", sailed with {c['shipped']}" if c.get("shipped") else "")
                   + (f", {len(c.get('pending', []))} left out" if c.get("pending") else ""))
    out.append(f"- Usage-limit stops recorded: {len(state.get('limit_hits', []))}.")
    return out + [""]


def escapes_section() -> list[str]:
    rows = []
    path = ROOT / "docs/escapes.md"
    for line in path.read_text().splitlines() if path.exists() else []:
        if re.match(r"^\|\s*ESC-\d+", line):
            rows.append([c.strip() for c in line.strip().strip("|").split("|")])
    out = ["## Escapes", ""]
    if not rows:
        return out + ["None logged.", ""]
    classes: dict[str, int] = {}
    for r in rows:
        if len(r) > 4:
            classes[r[4]] = classes.get(r[4], 0) + 1
    repeats = sum(n - 1 for n in classes.values())
    out.append(f"- {len(rows)} logged, {len(classes)} classes; {repeats} repeated a class the log already had (the goal is zero).")
    out.append("- By class: " + ", ".join(f"{c} ×{n}" for c, n in sorted(classes.items(), key=lambda kv: -kv[1])) + ".")
    return out + [""]


def rounds_section() -> list[str]:
    common = Path((ROOT / git("rev-parse", "--git-common-dir").strip()).resolve()) / "keelokit-rounds"
    out = ["## Review rounds", ""]
    items = sorted(common.iterdir()) if common.is_dir() else []
    if not items:
        return out + ["No rounds counted in this clone.", ""]
    return out + [", ".join(f"{p.name}: {p.read_text().strip()}" for p in items) + ".", ""]


def main() -> int:
    a = sys.argv[1:]
    if "-h" in a or "--help" in a:
        print(__doc__)
        return 0
    spec = a[a.index("--since") + 1] if "--since" in a and a.index("--since") + 1 < len(a) else "7d"
    lines = [f"# Process report — since {spec}", ""]
    lines += verify_section(window(spec)) + convoy_section() + escapes_section() + rounds_section()
    lines += ["## Not measured", "", "Tokens per role and per tier: nothing records them here, so there is no number. Count them in the Claude app's usage view if you need them.", ""]
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
