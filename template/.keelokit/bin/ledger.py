#!/usr/bin/env python3
"""Keelokit ledger. Stdlib only (Python 3.11+ for tomllib).

    python3 .keelokit/bin/ledger.py history            report: is the trunk's history complete?
                                                       (exit 0 complete, 1 incomplete, 2 not a git repo)
    python3 .keelokit/bin/ledger.py history --ensure   complete it (SessionStart hook); always exit 0

Any other command line prints the usage and exits 2.

A shallow clone cuts the trunk's history and the doctor then reads the done state as unknown.
`history --ensure` completes it: `git fetch --filter=blob:none --unshallow origin <trunk>` brings
commits only, so a large repo does not pay for every old file. A server that does not accept the
filter either ignores it (git says "filtering not recognized by server", the result is complete and
the promisor config the filter left is removed again) or rejects it, and then a plain
`git fetch --unshallow origin <trunk>` runs with what remains of the cap.

The trunk is `[ledger] trunk`, else `[harbor] trunk`, else main, from .keelokit/state.toml; the
remote is origin. The whole operation has one budget, `[ledger] history_seconds` (default 20, at
most 20: the hook's timeout is 30 s and the doctor must still run). At the cap the fetch's whole
process group gets SIGTERM (git removes its lock files), then SIGKILL after about 2 s. git never
prompts (GIT_TERMINAL_PROMPT=0, no stdin, its own session) and runs with LC_ALL=C so its messages
can be read.

Every outcome of --ensure is one `Keelokit:` line, and nothing when the history is already
complete. It never blocks a session: whatever goes wrong, one line and exit 0.
"""
import sys

if sys.version_info < (3, 11):
    print(f"Keelokit needs Python 3.11+ (found {sys.version.split()[0]}); the ledger is off.")
    sys.exit(0)

import os  # noqa: E402
import signal  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402
import tomllib  # noqa: E402
from pathlib import Path  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CAP = 20
MAX_CAP = 20
GRACE = 2.0
USAGE = __doc__.split("\n\n")[0]
KEYS = ("remote.origin.promisor", "remote.origin.partialclonefilter", "extensions.partialclone")


def git_env() -> dict:
    return {**os.environ, "LC_ALL": "C", "GIT_TERMINAL_PROMPT": "0"}


def run_git(args: list[str], timeout: float | None = None) -> tuple[int | None, str]:
    """(returncode, stderr). returncode None: cut at `timeout`, the process group is gone."""
    proc = subprocess.Popen(["git", *args], cwd=ROOT, env=git_env(), stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            errors="replace", start_new_session=True)
    try:
        _, err = proc.communicate(timeout=timeout)
        return proc.returncode, err
    except subprocess.TimeoutExpired:
        pass
    for sig, wait in ((signal.SIGTERM, GRACE), (signal.SIGKILL, GRACE)):
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            pass
        try:
            proc.communicate(timeout=wait)
            break
        except subprocess.TimeoutExpired:
            continue
    else:
        proc.kill()
    return None, ""


def git_out(*args: str) -> tuple[int, str]:
    r = subprocess.run(["git", *args], cwd=ROOT, env=git_env(), stdin=subprocess.DEVNULL,
                       capture_output=True, text=True, errors="replace")
    return r.returncode, r.stdout.strip()


def read_state() -> dict:
    try:
        return tomllib.loads((ROOT / ".keelokit/state.toml").read_text(encoding="utf-8"))
    except (OSError, ValueError):  # missing, not UTF-8, invalid TOML: the defaults apply
        return {}


def cap_seconds(state: dict) -> int:
    value = (state.get("ledger") or {}).get("history_seconds") if isinstance(state.get("ledger"), dict) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return DEFAULT_CAP
    return min(int(value), MAX_CAP) or DEFAULT_CAP


def trunk_name(state: dict) -> str:
    for table in ("ledger", "harbor"):
        t = state.get(table)
        if isinstance(t, dict) and isinstance(t.get("trunk"), str) and t["trunk"].strip():
            return t["trunk"].strip()
    return "main"


def last_error(err: str) -> str:
    lines = [line.strip() for line in err.splitlines() if line.strip()]
    pick = next((line for line in reversed(lines) if line.startswith(("fatal:", "error:"))), None)
    return pick or (lines[-1] if lines else "git fetch failed")


def is_shallow() -> bool | None:
    code, out = git_out("rev-parse", "--is-shallow-repository")
    return None if code else out == "true"


def config_set(key: str) -> bool:
    return git_out("config", "--local", "--get", key)[0] == 0


def ensure(trunk: str, cap: int) -> str:
    """Complete the history; the one line to print."""
    fix = f"`git fetch --unshallow origin {trunk}`"
    if git_out("remote", "get-url", "origin")[0]:
        return f"Keelokit: no origin: history incomplete; add a remote, then run {fix}"
    before = {k: config_set(k) for k in KEYS}
    start = time.monotonic()
    deadline = start + cap
    attempts = [["fetch", "--filter=blob:none", "--unshallow", "origin", trunk],
                ["fetch", "--unshallow", "origin", trunk]]
    code, err = None, ""
    for i, args in enumerate(attempts):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            code = None
            break
        code, err = run_git(args, remaining)
        if code is None or code == 0:
            break
        if i == 0 and "filter" not in err.lower():
            break
    # The ignored filter leaves a promisor config behind: a later fetch would warn forever.
    for key in KEYS:
        if not before[key] and config_set(key):
            git_out("config", "--local", "--unset-all", key)
    if code is None:
        return f"Keelokit: cut at {cap}s: history incomplete; run {fix}"
    if code != 0:
        msg = " ".join(last_error(err).split())
        return f"Keelokit: offline: history incomplete ({msg}); the doctor reads unknown until {fix}"
    if is_shallow():
        return f"Keelokit: history still incomplete after the fetch; run {fix}"
    ok, count = git_out("rev-list", "--count", f"refs/remotes/origin/{trunk}")
    if ok:
        count = git_out("rev-list", "--count", "HEAD")[1]
    return f"Keelokit: history completed ({count} commits of {trunk}) in {time.monotonic() - start:.1f}s"


def history(do_ensure: bool) -> int:
    shallow = is_shallow()
    if shallow is None:
        if not do_ensure:
            print("Keelokit: not a git repository.", file=sys.stderr)
        return 0 if do_ensure else 2
    if not shallow:
        return 0
    state = read_state()
    trunk = trunk_name(state)
    if trunk.startswith("-") or git_out("check-ref-format", "--branch", trunk)[0]:
        print(f"Keelokit: trunk {trunk!r} is not a branch name: history incomplete")
        return 0 if do_ensure else 1
    if not do_ensure:
        print("Keelokit: history incomplete (shallow clone); run `python3 .keelokit/bin/ledger.py history --ensure`")
        return 1
    print(ensure(trunk, cap_seconds(state)))
    return 0


def main(argv: list[str]) -> int:
    if argv[:1] != ["history"] or any(a != "--ensure" for a in argv[1:]) or len(argv) > 2:
        print(USAGE, file=sys.stderr)
        return 2
    do_ensure = "--ensure" in argv
    try:
        return history(do_ensure)
    except Exception as e:  # noqa: BLE001 - the hook must never fail a session
        if not do_ensure:
            raise
        print(f"Keelokit: history check failed ({type(e).__name__}: {' '.join(str(e).split())[:120]}); "
              "run `git fetch --unshallow origin main`")
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
