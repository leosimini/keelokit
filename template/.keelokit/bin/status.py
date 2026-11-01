#!/usr/bin/env python3
"""Where the parallel sessions stand, in ten lines. Stdlib only (Python 3.11+).

    python3 .keelokit/bin/status.py [--no-ci]

Worktrees and what they hold, branches with commits not on origin/main ("not finished"), the verify
lock, the CI of main (`ci.py health`, skipped with --no-ci or without network), and the backlog.
The coordinator runs it every round and trusts origin/main, not what a session said (SESS-1).
With `[landing] policy = "convoy"` in .keelokit/state.toml, a branch whose head is already on origin
is "delivered, waiting for a convoy": Harbor, not the session, takes it to main.
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


def landing_policy() -> str:
    """"convoy" or "direct"; absent, unreadable or anything else is direct."""
    try:
        import tomllib
        landing = tomllib.loads((ROOT / ".keelokit/state.toml").read_text()).get("landing", {})
        return "convoy" if isinstance(landing, dict) and landing.get("policy") == "convoy" else "direct"
    except (OSError, ValueError):
        return "direct"


def delivered(branch: str) -> bool:
    """The branch's head is on origin (its remote branch contains it): pushed, nothing left local."""
    return bool(git("rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}")) and subprocess.run(
        ["git", "merge-base", "--is-ancestor", f"refs/heads/{branch}", f"refs/remotes/origin/{branch}"],
        cwd=ROOT, capture_output=True).returncode == 0


def alive(pid: str) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (ValueError, ProcessLookupError, OSError):
        return False


def verify_line(common: Path) -> str:
    """The last verify in this clone: running, passed, failed, or CUT (its process is gone and it never finished)."""
    try:
        st = dict(l.split("=", 1) for l in (common / "keelokit-verify.state").read_text().splitlines() if "=" in l)
    except OSError:
        return "verify: no run recorded in this clone"
    age = int((__import__("time").time() - int(st.get("since", "0"))) // 60)
    head = st.get("head", "?")[:7]
    if st.get("state") == "running":
        if alive(st.get("pid", "")):
            return f"verify: running '{st.get('step')}' for {age} min ({st.get('level')}, {head})"
        return f"verify: CUT — it stopped at '{st.get('step')}' after {age} min and nobody finished it ({head}); see {st.get('log')}"
    return f"verify: last {st.get('state')} (exit {st.get('rc')}) on {head}, {st.get('level')}"


def main() -> int:
    lines: list[str] = []
    if "--no-ci" not in sys.argv and not os.environ.get("KEELOKIT_STATUS_OFFLINE"):
        subprocess.run(["git", "fetch", "--quiet", "origin", "main"], cwd=ROOT, capture_output=True)
    main_ref = "origin/main" if git("rev-parse", "--verify", "--quiet", "origin/main") else "main"
    lines.append(f"main: {main_ref} @ {git('rev-parse', '--short', main_ref) or '?'}")

    trees = [b.splitlines() for b in git("worktree", "list", "--porcelain").split("\n\n") if b.strip()]
    lines.append(f"worktrees: {len(trees)}")
    convoy = landing_policy() == "convoy"
    unpushed, waiting = [], []
    for t in trees:
        info = dict(l.split(" ", 1) for l in t if " " in l)
        path, branch = info.get("worktree", "?"), info.get("branch", "").removeprefix("refs/heads/")
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=path, capture_output=True, text=True).stdout.strip()
        ahead = git("rev-list", "--count", f"{main_ref}..{branch}") if branch else ""
        if branch and branch != "main" and ahead not in ("", "0"):
            (waiting if convoy and delivered(branch) else unpushed).append(f"{branch} (+{ahead})")
        if len(lines) < 5 and (dirty or (ahead not in ("", "0") and branch != "main")):
            lines.append(f"  {Path(path).name}: {branch or 'detached'} · {ahead or 0} commit(s) not on main"
                         f"{' · uncommitted changes' if dirty else ''}")
    if waiting:
        lines.append("delivered, waiting for a convoy: " + ", ".join(waiting))
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

    lines.append(verify_line(lock.parent))

    brief = subprocess.run([sys.executable, str(BIN / "doctor.py"), "--brief"], cwd=ROOT, capture_output=True, text=True)
    lines += [l for l in brief.stdout.strip().splitlines()[:3]]
    print("\n".join(lines[:10]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
