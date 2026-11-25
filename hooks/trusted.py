#!/usr/bin/env python3
"""The plugin's hooks run the guard, the doctor and the ledger through this file, so that opening a repo
never runs the repo's own code (HARN-004).

    python3 -I hooks/trusted.py run guard|doctor|ledger [ARGS…]   the hooks (project: $CLAUDE_PROJECT_DIR)
    python3 -I hooks/trusted.py check          one line when the project's scripts differ from the plugin's
    python3 -I hooks/trusted.py githooks       one line when the repo has .githooks that are off
    python3 -I hooks/trusted.py show [DIR]     how .keelokit/bin and .githooks differ from the plugin's, escaped

The Claude hooks always run the plugin's own copy, with `--root <project>`, against the project's data (its rules,
rules.local.toml, state, backlog). Nothing of the project's executes: its .keelokit/bin is only read, by `check`
and `show`, to say whether it differs. A project that customised its scripts still runs them when a person runs
them, or turns on the project's git hooks; only the Claude hooks ignore them. There is no per-project approval:
an agent with a shell, running as the same user, could forge any "a person approved this" (ESC-278).
The plugin never turns a repo's git hooks on: they run the repo's own code (.keelokit/bin without -I, whatever
.githooks holds on whichever branch is checked out), so that is the person's call (ESC-277). The plugin's ledger
and guard, run with `--root`, run git with no hooks of the repo's (core.hooksPath=/dev/null) even when the person
turned them on.
The guard runs in a child process, and the hook waits for it at most GUARD_SECONDS: past that the child is killed
and the call is blocked, because Claude Code lets a call through when a hook outlives its timeout (ESC-279).
Whatever runs gets no PYTHON* variables and no relative PATH entries, so neither a planted module nor a planted
`git` in the project is reached; the hooks cd into the plugin before looking python3 up, for the same reason.
Only the Python standard library is imported, and nothing next to this file (`-I`).
"""
import os
import sys

if __name__ == "__main__" and not sys.flags.isolated:  # before any import: a module planted next to this file, PYTHONPATH, never looked at
    os.execv(sys.executable, [sys.executable, "-I", os.path.realpath(__file__), *sys.argv[1:]])
if sys.version_info < (3, 11):
    print(f"Keelokit needs Python 3.11+ (found {sys.version.split()[0]}); the guard and doctor are off.", file=sys.stderr)
    sys.exit(0)

import builtins  # noqa: E402
import difflib  # noqa: E402
import json  # noqa: E402
import shlex  # noqa: E402
import signal  # noqa: E402
import stat  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402
import traceback  # noqa: E402
import types  # noqa: E402
import unicodedata  # noqa: E402
from pathlib import Path  # noqa: E402

PLUGIN = Path(__file__).resolve().parents[1]
BUNDLED = PLUGIN / "template/.keelokit/bin"
BUNDLED_HOOKS = PLUGIN / "template/.githooks"
BIN = ".keelokit/bin"
HOOKS = ".githooks"
RUNS = {"guard": "guard.py", "ledger": "ledger.py", "doctor": "doctor.py"}
HOOKED = ("guard.py", "doctor.py", "ledger.py", "ux_gate.py")  # what the hooks would run, the doctor's children too
MAX_BYTES = 8 << 20  # a script bigger than this is never read whole: it can't be the plugin's
MAX_ENTRIES = 512
GUARD_SECONDS = 45.0  # under the PreToolUse hook's 60 s timeout


def regular_bytes(path: Path) -> bytes | None:
    """The bytes of a regular file, or None: missing, a symlink (never followed), a FIFO, a device, a directory, too
    big. Opened without blocking, so a FIFO planted where a script should be can't hang the hook."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0))
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_BYTES:
            return None
        chunks, size = [], 0
        while chunk := os.read(fd, 1 << 16):
            size += len(chunk)
            if size > MAX_BYTES:
                return None
            chunks.append(chunk)
        return b"".join(chunks)
    except OSError:
        return None
    finally:
        os.close(fd)


def plugin_bytes(path: Path) -> bytes | None:
    """A file of the plugin itself (trusted; an install may link it)."""
    try:
        return path.read_bytes()
    except OSError:
        return None


def differing(project: Path) -> list[str]:
    """The hooked scripts the project has that are not byte for byte the plugin's, in the order the hooks run them."""
    return [n for n in HOOKED if os.path.lexists(project / BIN / n)
            and regular_bytes(project / BIN / n) != plugin_bytes(BUNDLED / n)]


def plugin_version() -> str:
    try:
        return json.loads((PLUGIN / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))["version"]
    except (OSError, ValueError, KeyError, TypeError):
        return "?"


def clean_environment() -> None:
    """No PYTHON* variable reaches what runs or the Python it starts, and PATH keeps only absolute entries: a
    relative one (`.`, an empty one) would look commands up in the project, where the scripts run git."""
    for key in [k for k in os.environ if k.startswith("PYTHON")]:
        del os.environ[key]
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    sys.dont_write_bytecode = True
    parts = os.environ.get("PATH", "").split(os.pathsep)
    os.environ["PATH"] = os.pathsep.join(p for p in parts if p and os.path.isabs(p)) or os.defpath


def execute(path: Path, data: bytes, argv: list[str]) -> None:
    """Runs `data` as the script at `path` would run, in this process."""
    code = compile(data, str(path), "exec", dont_inherit=True)
    module = types.ModuleType("__main__")
    module.__file__ = str(path)
    module.__builtins__ = builtins
    sys.modules["__main__"] = module
    sys.argv = [str(path), *argv]
    exec(code, module.__dict__)


def guard_seconds() -> float:
    """GUARD_SECONDS, or less where KEELOKIT_GUARD_SECONDS says so (tests); never more."""
    try:
        wanted = float(os.environ.get("KEELOKIT_GUARD_SECONDS", GUARD_SECONDS))
    except ValueError:
        wanted = GUARD_SECONDS
    return min(max(wanted, 0.1), GUARD_SECONDS) if wanted == wanted else GUARD_SECONDS


def exit_code(e: SystemExit) -> int:
    if e.code is None:
        return 0
    if isinstance(e.code, int):
        return e.code
    print(e.code, file=sys.stderr)
    return 1


def watched(path: Path, data: bytes, argv: list[str]) -> int:
    """Runs the script in a child process (its own process group) and waits for it at most guard_seconds(); then
    kills the group and blocks (exit 2). CPython's re can't be interrupted mid-match, so only a process boundary
    bounds the guard's own CPU."""
    budget = guard_seconds()
    sys.stdout.flush()
    sys.stderr.flush()
    pid = os.fork()
    if pid == 0:  # the child: the guard
        code = 1
        try:
            os.setpgid(0, 0)
            execute(path, data, argv)
            code = 0
        except SystemExit as e:
            code = exit_code(e)
        except BaseException:
            traceback.print_exc()
            code = 1
        finally:
            try:
                sys.stdout.flush()
                sys.stderr.flush()
            finally:
                os._exit(code)
    try:
        os.setpgid(pid, pid)
    except OSError:
        pass  # the child set it first, or has already ended
    deadline = time.monotonic() + budget
    pause = 0.001
    while True:
        done, status = os.waitpid(pid, os.WNOHANG)
        if done:
            code = os.waitstatus_to_exitcode(status)
            if code < 0:
                print(f"Keelokit guard: the guard was stopped by signal {-code}, so the call is blocked",
                      file=sys.stderr)
                return 2
            return code
        if time.monotonic() >= deadline:
            for kill in (lambda: os.killpg(pid, signal.SIGKILL), lambda: os.kill(pid, signal.SIGKILL)):
                try:
                    kill()
                    break
                except OSError:
                    continue
            os.waitpid(pid, 0)
            print(f"Keelokit guard: the guard did not answer in {budget:g} s, so the call is blocked", file=sys.stderr)
            return 2
        time.sleep(pause)
        pause = min(pause * 2, 0.05)


def project_dir(arg: str | None = None) -> Path | None:
    raw = arg if arg is not None else os.environ.get("CLAUDE_PROJECT_DIR", "")
    if not raw:
        return None
    p = Path(raw).resolve()
    return p if p.is_dir() else None


def keelokit_project(project: Path, tool: str) -> bool:
    """The guard runs wherever the project has .keelokit/ (ESC-282: deleting guard.py, which it never runs, must not
    turn it off; removing .keelokit/ as a whole is the person's call); the ledger and the doctor where the project
    has theirs, as the session start always did."""
    if tool == "guard":  # ESC-284, ESC-286: a harness committed here or on the trunk the clone came from still counts
        return os.path.isdir(project / ".keelokit") or any(
            git(project, "cat-file", "-e", f"{ref}:.keelokit") is not None for ref in ("HEAD", "origin/HEAD"))
    return os.path.lexists(project / BIN / RUNS[tool])


def choose(tool: str, project: Path) -> tuple[Path, bytes, list[str]] | None:
    """(the plugin's script, its bytes, `--root <project>`), or None when this hook has nothing to do in the
    project. The project's own copy is never read for running."""
    if not keelokit_project(project, tool):
        return None
    ours = BUNDLED / RUNS[tool]
    data = plugin_bytes(ours)
    if data is None:
        raise SystemExit(f"Keelokit: the plugin's {RUNS[tool]} is missing ({ours}); reinstall the plugin")
    return ours, data, ["--root", str(project)]


def run(tool: str, args: list[str]) -> int:
    project = project_dir()
    if project is None or tool not in RUNS:
        return 0
    chosen = choose(tool, project)
    if chosen is None:
        return 0
    path, data, before = chosen
    clean_environment()
    os.environ["KEELOKIT_PLUGIN_ROOT"] = str(PLUGIN)  # the guard keeps agents off the plugin's own code (ESC-289)
    os.chdir(project)
    if tool == "guard":
        return watched(path, data, [*before, *args])
    execute(path, data, [*before, *args])
    return 0


def check(arg: str | None = None) -> int:
    project = project_dir(arg)
    if project is None:
        return 0
    off = differing(project)
    if off:
        print(f"Keelokit: this project's {', '.join(off)} in .keelokit/bin differ from the plugin's, so the Claude "
              f"hooks run Keelokit {plugin_version()}'s copy against this project's data, never the project's own. "
              f"An older harness: /keelokit:harness-upgrade. Scripts you customised still run when you run them "
              f"yourself, or from the project's git hooks once you turn them on.")
    return 0


GIT_SCRUB = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
             "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE", "GIT_EXEC_PATH", "GIT_CONFIG", "GIT_SSH",
             "GIT_SSH_COMMAND", "GIT_ASKPASS", "GIT_EXTERNAL_DIFF", "GIT_PAGER", "GIT_EDITOR")
# Without core.hooksPath: this file only reads (rev-parse, config --get), and reads the hooks path the person set.
GIT_CONFIG = {"safe.bareRepository": "explicit", "protocol.ext.allow": "never", "protocol.file.allow": "always",
              "core.fsmonitor": "false"}


def git_env() -> dict:
    """The environment of this file's own git calls: the scripts' hardened one (ESC-280; see harden_git in them)."""
    env = {k: v for k, v in os.environ.items() if k not in GIT_SCRUB}
    try:
        n = max(int(env.get("GIT_CONFIG_COUNT") or 0), 0)
    except ValueError:
        n = 0
    for key, value in GIT_CONFIG.items():
        env[f"GIT_CONFIG_KEY_{n}"], env[f"GIT_CONFIG_VALUE_{n}"] = key, value
        n += 1
    env.update(GIT_CONFIG_COUNT=str(n), GIT_NO_LAZY_FETCH="1", GIT_TERMINAL_PROMPT="0", GIT_PROTOCOL_FROM_USER="0")
    return env


def git(project: Path, *args: str) -> str | None:
    """stdout of a read-only git call in the project (rev-parse, config --get), or None when it fails."""
    try:
        out = subprocess.run(["git", "-C", str(project), *args], capture_output=True, text=True, timeout=10,
                             env=git_env())
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout if out.returncode == 0 else None


def githooks(arg: str | None = None) -> int:
    """LEDGER-009.S7, superseded (ESC-277): a clone with .githooks and no hooks path is told its hooks are off; the
    plugin never sets core.hooksPath."""
    project = project_dir(arg)
    if project is None or not os.path.isdir(project / HOOKS):
        return 0
    clean_environment()
    top = git(project, "rev-parse", "--show-cdup")
    gitdir = git(project, "rev-parse", "--absolute-git-dir")
    if top is None or top.strip() or gitdir is None or Path(gitdir.strip()).resolve() != project / ".git" and \
            project in Path(gitdir.strip()).resolve().parents:
        return 0
    if git(project, "config", "--get", "core.hooksPath") is not None:
        return 0
    print("Keelokit: this repo's git hooks are off, and Keelokit never turns them on: they run the repo's own code. "
          "Review .githooks (and the .keelokit/bin scripts they run), then turn them on yourself: "
          "git config core.hooksPath .githooks")
    return 0


def visible(text: str) -> str:
    """Every character a terminal would not show as itself (controls, bidi overrides, zero-width and odd spaces,
    tabs) written as an escape, so the reader sees exactly what is there."""
    out = []
    for ch in text:
        if ch == " " or (unicodedata.category(ch)[0] not in "CZ" and ch != "\\"):
            out.append(ch)
        elif ch == "\\":
            out.append("\\\\")
        else:
            out.append(f"\\x{ord(ch):02x}" if ord(ch) < 0x100 else f"\\u{ord(ch):04x}" if ord(ch) < 0x10000
                       else f"\\U{ord(ch):08x}")
    return "".join(out)


def lines_of(data: bytes | None) -> list[str]:
    return [] if data is None else data.decode("utf-8", "backslashreplace").split("\n")


def report(project: Path) -> list[str]:
    """What differs between the project's .keelokit/bin and .githooks and the plugin's, every line escaped."""
    out = []
    for d, ours_dir in ((BIN, BUNDLED), (HOOKS, BUNDLED_HOOKS)):
        try:
            names = sorted(os.listdir(project / d))[:MAX_ENTRIES]
        except OSError:
            continue
        for name in names:
            p = project / d / name
            try:
                mode = os.lstat(p).st_mode
            except OSError:
                continue
            data = regular_bytes(p) if stat.S_ISREG(mode) else None
            ours = plugin_bytes(ours_dir / name)
            if data is not None and data == ours:
                continue
            head = f"== {d}/{visible(name)}"
            if data is None:
                out.append(f"{head}: not a plain file, or too big; not read")
                continue
            out.append(head + (": not in the plugin" if ours is None else ""))
            for line in difflib.unified_diff(lines_of(ours), lines_of(data), "plugin", "project", lineterm="", n=2):
                out.append(visible(line))
    return out


def show(arg: str | None) -> int:
    project = project_dir(arg) or Path.cwd().resolve()
    lines = report(project)
    print("\n".join(lines) if lines else f"Keelokit: {project}'s .keelokit/bin and .githooks match the plugin's.")
    return 0


COMMANDS = {"check": check, "githooks": githooks, "show": show}


def guard_hook(args: list[str]) -> int:
    """`run guard`: Claude Code blocks a call only on exit 2, so every other outcome of this path (an exception before
    or around the fork, a failed fork, a guard that crashed, exited 1 or was killed) is a block, said in one line
    (ESC-281)."""
    try:
        code = run("guard", args)
    except BaseException as e:  # noqa: BLE001 - KeyboardInterrupt and SystemExit included: all fail closed
        if isinstance(e, SystemExit) and e.code in (0, None):
            return 0
        print(f"Keelokit guard: the hook failed ({type(e).__name__}: {' '.join(str(e).split())[:120]}), "
              f"so the call is blocked", file=sys.stderr)
        return 2
    if code not in (0, 2):
        print(f"Keelokit guard: the guard ended with exit {code}, so the call is blocked", file=sys.stderr)
        return 2
    return code


def main(argv: list[str]) -> int:
    cmd, rest = (argv[0], argv[1:]) if argv else ("", [])
    if cmd == "run" and rest[:1] == ["guard"]:
        return guard_hook(rest[1:])
    if cmd == "run" and rest:
        return run(rest[0], rest[1:])
    if cmd in COMMANDS and len(rest) <= 1:
        return COMMANDS[cmd](rest[0] if rest else None)
    print(__doc__.split("\n\n")[1], file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
