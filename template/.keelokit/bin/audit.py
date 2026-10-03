#!/usr/bin/env python3
"""Dependency audit (SEC-3): `pnpm audit`, failing only on what can be fixed.

    python3 .keelokit/bin/audit.py

A high or critical advisory with a fixed version fails (exit 1): upgrade, or override the
transitive version in package.json's pnpm.overrides. One with no fixed version yet is listed as a
warning on every run and doesn't fail: nothing can be upgraded, and every project would stay red
until upstream ships a fix. When it does, the advisory gets a fixed version and starts failing.
An audit that can't run (no network, no lockfile) fails."""
import json
import subprocess
import sys

BLOCKING = {"high", "critical"}
NO_FIX = "<0.0.0"


def main() -> int:
    run = subprocess.run(["pnpm", "audit", "--json"], capture_output=True, text=True)
    try:
        report = json.loads(run.stdout)
    except json.JSONDecodeError:
        print(f"✖ pnpm audit didn't run: {(run.stderr or run.stdout).strip()[:500]}", file=sys.stderr)
        return 1
    if "error" in report or "advisories" not in report:
        print(f"✖ pnpm audit didn't run: {json.dumps(report.get('error', report))[:500]}", file=sys.stderr)
        return 1
    fix, wait = [], []
    for a in report["advisories"].values():
        if a.get("severity") not in BLOCKING:
            continue
        paths = sorted({p for f in a.get("findings", []) for p in f.get("paths", [])})
        line = (f"{a['severity']} {a['module_name']} {a.get('vulnerable_versions', '')}: {a.get('title', '')}"
                f" ({a.get('github_advisory_id') or a.get('url', '')}) via {', '.join(paths[:3]) or '?'}")
        (wait if a.get("patched_versions", "").strip() == NO_FIX else fix).append(f"{line}; fixed in {a.get('patched_versions')}")
    for line in sorted(wait):
        print(f"  warn  no fix yet, not blocking: {line.split('; fixed in')[0]}")
    for line in sorted(fix):
        print(f"✖ {line}", file=sys.stderr)
    if fix:
        print(f"✖ {len(fix)} high or critical advisories have a fix: upgrade, or pin it in pnpm.overrides (SEC-3)",
              file=sys.stderr)
        return 1
    print(f"✔ no fixable high or critical advisory{f' ({len(wait)} waiting for a fix upstream)' if wait else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
