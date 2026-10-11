#!/usr/bin/env python3
"""Where the parallel sessions stand, in ten lines. Stdlib only (Python 3.11+).

    python3 .keelokit/bin/status.py [--no-ci]

Worktrees and what they hold, branches with commits not on origin/main ("not finished"), the verify
lock, the CI of main (`ci.py health`, skipped with --no-ci or without network), and the backlog.
The coordinator runs it every round and trusts origin/main, not what a session said (SESS-1).
"""
import sys

if sys.version_info < (3, 11):
    print(f"Keelokit needs Python 3.11+ (found {sys.version.split()[0]}).")
    sys.exit(1)

import os  # noqa: E402
import subprocess  # noqa: E402
from pathlib import Path  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
BIN = ROOT / ".keelokit/bin"


def git(*args: str) -> str:
    res = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    return res.stdout.strip() if res.returncode == 0 else ""


def alive(pid: str) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (ValueError, ProcessLookupError, OSError):
        return False


def main() -> int:
    lines: list[str] = []
    if "--no-ci" not in sys.argv and not os.environ.get("KEELOKIT_STATUS_OFFLINE"):
        subprocess.run(["git", "fetch", "--quiet", "origin", "main"], cwd=ROOT, capture_output=True)
    main_ref = "origin/main" if git("rev-parse", "--verify", "--quiet", "origin/main") else "main"
    lines.append(f"main: {main_ref} @ {git('rev-parse', '--short', main_ref) or '?'}")

    trees = [b.splitlines() for b in git("worktree", "list", "--porcelain").split("\n\n") if b.strip()]
    lines.append(f"worktrees: {len(trees)}")
    unpushed = []
    for t in trees:
        info = dict(l.split(" ", 1) for l in t if " " in l)
        path, branch = info.get("worktree", "?"), info.get("branch", "").removeprefix("refs/heads/")
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=path, capture_output=True, text=True).stdout.strip()
        ahead = git("rev-list", "--count", f"{main_ref}..{branch}") if branch else ""
        if branch and branch != "main" and ahead not in ("", "0"):
            unpushed.append(f"{branch} (+{ahead})")
        if len(lines) < 5 and (dirty or (ahead not in ("", "0") and branch != "main")):
            lines.append(f"  {Path(path).name}: {branch or 'detached'} · {ahead or 0} commit(s) not on main"
                         f"{' · uncommitted changes' if dirty else ''}")
    lines.append("not finished (commits not on main): " + (", ".join(unpushed) if unpushed else "none"))

    lock = Path(git("rev-parse", "--git-common-dir") or ".git")
    lock = (lock if lock.is_absolute() else ROOT / lock) / "keelokit-verify.lock"
    if lock.is_dir():
        pid = (lock / "pid").read_text().strip() if (lock / "pid").exists() else ""
        where = (lock / "where").read_text().strip() if (lock / "where").exists() else "?"
        lines.append(f"verify lock: held by pid {pid or '?'} in {where}" + ("" if alive(pid) else " (stale: its owner is gone)"))
    else:
        lines.append("verify lock: free")

    if "--no-ci" in sys.argv or os.environ.get("KEELOKIT_STATUS_OFFLINE"):
        lines.append("CI of main: not checked")
    else:
        res = subprocess.run([sys.executable, str(BIN / "ci.py"), "health"], cwd=ROOT, capture_output=True, text=True, timeout=90)
        lines.append("CI of main: " + ((res.stdout.strip().splitlines() or [res.stderr.strip() or "unknown"])[0]))

    brief = subprocess.run([sys.executable, str(BIN / "doctor.py"), "--brief"], cwd=ROOT, capture_output=True, text=True)
    lines += [l for l in brief.stdout.strip().splitlines()[:3]]
    print("\n".join(lines[:10]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
