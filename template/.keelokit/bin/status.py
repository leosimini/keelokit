#!/usr/bin/env python3
"""Where the parallel sessions stand, in ten lines. Stdlib only (Python 3.11+).

    python3 .keelokit/bin/status.py [--no-ci]
    python3 .keelokit/bin/status.py title <ID>                 the title of the session that builds story <ID>
    python3 .keelokit/bin/status.py title --role coordinator   the title of the session that coordinates

Worktrees and what they hold, branches with commits not on origin/main ("not finished"), the verify
lock, the CI of main (`ci.py health`, skipped with --no-ci or without network), and the backlog.
The coordinator runs it every round and trusts origin/main, not what a session said (SESS-1).
With `[landing] policy = "convoy"` in .keelokit/state.toml, a branch whose head is already on origin
is "delivered, waiting for a convoy": Harbor, not the session, takes it to main.

`title` prints a session's canonical title, the one every tool that starts or lists sessions uses
(Harbor included): `<project> · <wave|ola> <n> · <ID>` for a story, `<project> · <coordinator|
coordinador>` for the coordinator. The project is `project_name` in .keelokit/answers.yml, the wave
the story's front matter, the words follow `[dashboard] lang` in .keelokit/state.toml (es → Spanish,
anything else or nothing → English). A story or a name it can't find is exit 2 with the reason, never
a made-up title.
"""
import sys

if sys.version_info < (3, 11):
    print(f"Keelokit needs Python 3.11+ (found {sys.version.split()[0]}).")
    sys.exit(1)

import os  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
from pathlib import Path  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
BIN = ROOT / ".keelokit/bin"


def git(*args: str) -> str:
    res = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    return res.stdout.strip() if res.returncode == 0 else ""


SEP = " · "
WORDS = {"en": {"wave": "wave", "coordinator": "coordinator"}, "es": {"wave": "ola", "coordinator": "coordinador"}}


def yaml_scalar(text: str, key: str) -> str | None:
    """A top-level scalar of a flat YAML file as Copier writes it (to_nice_yaml): plain, 'single-quoted'
    ('' is a quote) or "double-quoted" (backslash escapes), and folded over indented lines when long
    (each line break is a space). None when the key isn't there."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not line.startswith(f"{key}:"):
            continue
        parts = [line[len(key) + 1:].strip()]
        for more in lines[i + 1:]:
            if not more.startswith((" ", "\t")):
                break
            parts.append(more.strip())
        raw = " ".join(p for p in parts if p)
        if raw.startswith("'") and raw.endswith("'") and len(raw) > 1:
            return raw[1:-1].replace("''", "'")
        if raw.startswith('"') and raw.endswith('"') and len(raw) > 1:
            simple = {"n": "\n", "t": "\t", '"': '"', "\\": "\\", "/": "/", "0": "\0", " ": " "}
            return re.sub(r'\\(x[0-9A-Fa-f]{2}|u[0-9A-Fa-f]{4}|U[0-9A-Fa-f]{8}|.)',
                           lambda m: chr(int(m[1][1:], 16)) if len(m[1]) > 1 else simple.get(m[1], m[1]), raw[1:-1])
        return raw.split(" #", 1)[0].strip()
    return None


def title(args: list[str]) -> int:
    """`status.py title <ID> [--role coordinator]`: see the module's docstring."""
    import tomllib
    role = "story"
    if "--role" in args:
        i = args.index("--role")
        role = args[i + 1] if i + 1 < len(args) else ""
        args = args[:i] + args[i + 2:]
    if role not in ("story", "coordinator"):
        print(f"status.py title: unknown role {role!r} (story, coordinator)", file=sys.stderr)
        return 2
    try:
        name = yaml_scalar((ROOT / ".keelokit/answers.yml").read_text(encoding="utf-8"), "project_name")
    except (OSError, ValueError):
        name = None
    if not name or not name.strip():
        print("status.py title: no project_name in .keelokit/answers.yml", file=sys.stderr)
        return 2
    try:
        dash = tomllib.loads((ROOT / ".keelokit/state.toml").read_text(encoding="utf-8")).get("dashboard", {})
    except (OSError, ValueError):
        dash = {}
    lang = dash.get("lang") if isinstance(dash, dict) else None
    words = WORDS["es" if isinstance(lang, str) and lang.lower().split("-")[0] == "es" else "en"]
    if role == "coordinator":
        print(SEP.join([name.strip(), words["coordinator"]]))
        return 0
    if len(args) != 1 or not args[0] or args[0].startswith("-"):
        print("usage: status.py title <ID> [--role coordinator]", file=sys.stderr)
        return 2
    sid = args[0]
    found = None
    for path in sorted((ROOT / "backlog/stories").glob("*.md")) if (ROOT / "backlog/stories").is_dir() else []:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, ValueError):
            continue
        if not text.startswith("+++\n") or "\n+++" not in text[4:]:
            continue
        try:
            meta = tomllib.loads(text[4:text.index("\n+++", 4)])
        except ValueError:
            continue
        if meta.get("id") == sid:
            found = (path, meta)
            break
    if found is None:
        print(f"status.py title: no story {sid} in backlog/stories", file=sys.stderr)
        return 2
    wave = found[1].get("wave")
    if not isinstance(wave, int) or isinstance(wave, bool):
        print(f"status.py title: story {sid} ({found[0].name}) has no wave (a whole number in its front matter)",
              file=sys.stderr)
        return 2
    print(SEP.join([name.strip(), f"{words['wave']} {wave}", sid]))
    return 0


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
    if sys.argv[1:2] == ["title"]:
        return title(sys.argv[2:])
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
