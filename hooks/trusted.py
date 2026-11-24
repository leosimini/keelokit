#!/usr/bin/env python3
"""The plugin's hooks run the guard, the doctor and the ledger through this file, so that opening a repo
runs code a person controls, never the repo's own copy unchecked (HARN-004).

    python3 -I hooks/trusted.py run guard|doctor|ledger [ARGS…]   the hooks (project: $CLAUDE_PROJECT_DIR)
    python3 -I hooks/trusted.py check          one line when the project's own copy is not what runs, else nothing
    python3 -I hooks/trusted.py githooks       turns the repo's .githooks on only when they are safe to (see below)
    python3 -I hooks/trusted.py show [DIR]     how .keelokit/bin and .githooks differ from the plugin's, escaped
    python3 -I hooks/trusted.py trust [DIR]    a person approves them as they are now (asks on the terminal)
    python3 -I hooks/trusted.py untrust [DIR]  withdraws that approval

Which code runs is decided before anything from the project executes, by reading bytes, never by running them.
Every file of .keelokit/bin and .githooks is read once (a snapshot), and everything is decided on, and run from,
those bytes:
1. the project's copy of every script the hook runs (guard.py; ledger.py; doctor.py with the ledger.py and
   ux_gate.py it runs) is byte for byte the plugin's: the plugin's copy runs, with `--root <project>`;
2. else, this machine's trust store holds the snapshot's fingerprint, approved for this project by a person with
   `trust`: the project's copy runs, from the snapshot's bytes;
3. else the plugin's copy runs against the project's data (its rules, rules.local.toml, state, backlog), and
   `check` says so in one line at the session start. The project's file never runs.
Only plain files can be approved: a .keelokit/bin or .githooks holding a directory, a symlink, a special file or a
file over the size limit is something a fingerprint can't pin down (a package that shadows a module, a link whose
target changes), so `trust` refuses it and the plugin's copy runs.
`githooks` sets core.hooksPath to .githooks (where it is unset, as LEDGER-009 did) only when the hooks are the
plugin's own and the .keelokit/bin scripts they run are too, or when a person approved the snapshot; otherwise it
says in one line that the repo's hooks stay off and how to review them. The plugin's ledger and guard, run with
`--root`, also run git with no hooks of the repo's (core.hooksPath=/dev/null), whatever the hooks path says.
The trust store is ~/.config/keelokit/trusted.json of the user running it, found from the password database, not
from $HOME, which a repo's settings could set. `trust` reads its answer from the controlling terminal (/dev/tty)
and asks for the fingerprint's first characters; the guard refuses `trust` and writes to the store to agents. An
agent with a shell of its own, running as the same user, can still write the store: the same limit as the guard's.
Whatever runs gets no PYTHON* variables (and PYTHONDONTWRITEBYTECODE=1: no bytecode the fingerprint never saw) and
no relative PATH entries, so neither a planted module nor a planted `git` in the project is reached; the hooks cd
into the plugin before looking python3 up, for the same reason. Only the Python standard library is imported, and
nothing next to this file (`-I`).
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
import hashlib  # noqa: E402
import json  # noqa: E402
import pwd  # noqa: E402
import shlex  # noqa: E402
import stat  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import types  # noqa: E402
import unicodedata  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

PLUGIN = Path(__file__).resolve().parents[1]
BUNDLED = PLUGIN / "template/.keelokit/bin"
BUNDLED_HOOKS = PLUGIN / "template/.githooks"
BIN = ".keelokit/bin"
HOOKS = ".githooks"
DIRS = (BIN, HOOKS)
# What each hook runs: the entry script first, then the scripts it runs in turn.
RUNS = {"guard": ("guard.py",), "ledger": ("ledger.py",), "doctor": ("doctor.py", "ledger.py", "ux_gate.py")}
HOOKED = ("guard.py", "doctor.py", "ledger.py", "ux_gate.py")
GITHOOKS_RUN = ("guard.py", "ledger.py")  # what the template's .githooks run from .keelokit/bin
MAX_BYTES = 8 << 20  # a script bigger than this is never read whole: it can't be the plugin's
MAX_TOTAL = 32 << 20  # what one snapshot reads at most, so a repo can't make every hook call slow
MAX_ENTRIES = 512
WHY_TRUST = "approving the code Keelokit's hooks run is a person's decision"
TURNED_ON = ("Keelokit: turned the git hooks on (git config core.hooksPath .githooks): the guard and the trailer "
             "check run on every commit here")


def store_path() -> Path:
    return Path(pwd.getpwuid(os.getuid()).pw_dir) / ".config/keelokit/trusted.json"


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


def snapshot(project: Path) -> list[tuple[str, str, str, bytes | None]]:
    """(dir, name, kind, bytes) for each entry of the project's .keelokit/bin and .githooks, sorted, each file read
    once; kind is "file" only for a regular file read whole. The hooked scripts are read first, so the total limit
    never keeps them from being read."""
    out: list[tuple[str, str, str, bytes | None]] = []
    budget = MAX_TOTAL
    for d in DIRS:
        where = project / d
        try:
            names = sorted(os.listdir(where))
        except OSError:
            continue
        if len(names) > MAX_ENTRIES:
            out.append((d, "", f"more than {MAX_ENTRIES} entries", None))
            names = names[:MAX_ENTRIES]
        first = [n for n in names if d == BIN and n in HOOKED]
        rows = {}
        for name in first + [n for n in names if n not in first]:
            p = where / name
            try:
                mode = os.lstat(p).st_mode
            except OSError:
                continue
            if stat.S_ISLNK(mode):
                rows[name] = ("symlink", None)
            elif stat.S_ISDIR(mode):
                rows[name] = ("directory", None)
            elif not stat.S_ISREG(mode):
                rows[name] = ("special file", None)
            elif budget <= 0:
                rows[name] = ("file past the snapshot's limit", None)
            else:
                data = regular_bytes(p)
                if data is None:
                    rows[name] = ("file over the size limit, or unreadable", None)
                else:
                    budget -= len(data)
                    rows[name] = ("file", data)
        out.extend((d, name, *rows[name]) for name in names if name in rows)
    return out


def files_in(snap, d: str = BIN) -> dict[str, bytes]:
    return {name: data for dd, name, kind, data in snap if dd == d and kind == "file" and data is not None}


def names_in(snap, d: str = BIN) -> set[str]:
    return {name for dd, name, _, _ in snap if dd == d}


def fingerprint_of(snap) -> str:
    h = hashlib.sha256(b"keelokit-bin-2\0")
    for d, name, kind, data in snap:
        for part in (d, name, kind):
            h.update(part.encode("utf-8", "surrogateescape") + b"\0")
        h.update(hashlib.sha256(data).digest() if data is not None else b"-")
    return h.hexdigest()


def unapprovable(snap) -> str | None:
    """Why this snapshot cannot be approved, or None: only plain files read whole can be."""
    bad = [f"{d}/{name or '…'} is a {kind}" for d, name, kind, data in snap if kind != "file" or data is None]
    return "; ".join(bad[:5]) or None


def fingerprint(project: Path) -> str:
    return fingerprint_of(snapshot(project))


def read_store() -> dict:
    """The trust store, or {} when it is missing, unreadable, not the user's own or writable by others."""
    p = store_path()
    try:
        fd = os.open(p, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    except OSError:
        return {}
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o022:
            return {}
        data = json.loads(os.read(fd, MAX_BYTES).decode("utf-8"))
    except (OSError, ValueError):
        return {}
    finally:
        os.close(fd)
    return data.get("projects", {}) if isinstance(data, dict) and isinstance(data.get("projects"), dict) else {}


def write_store(projects: dict) -> None:
    p = store_path()
    p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".trusted-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "projects": projects}, f, indent=2, sort_keys=True)
        f.write("\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, p)


def approved_snapshot(project: Path, snap) -> bool:
    if unapprovable(snap):
        return False
    entry = read_store().get(str(project))
    return isinstance(entry, dict) and entry.get("fingerprint") == fingerprint_of(snap)


def approved(project: Path) -> bool:
    return approved_snapshot(project, snapshot(project))


def same_as_plugin(snap, names) -> bool:
    """Every one of `names` that the project's .keelokit/bin has is a plain file, byte for byte the plugin's."""
    files, present = files_in(snap), names_in(snap)
    for name in names:
        if name in present and (name not in files or files[name] != plugin_bytes(BUNDLED / name)):
            return False
    return True


def differing(snap) -> list[str]:
    """The hooked scripts the project has that are not the plugin's, in the order the hooks run them."""
    return [n for n in HOOKED if n in names_in(snap) and not same_as_plugin(snap, (n,))]


def githooks_like_plugin(snap) -> bool:
    """Every entry of .githooks is a plain file, byte for byte one of the plugin's, and the .keelokit/bin scripts they
    run are the plugin's too."""
    hooks, present = files_in(snap, HOOKS), names_in(snap, HOOKS)
    if not present or set(hooks) != present:
        return False
    if any(data != plugin_bytes(BUNDLED_HOOKS / name) for name, data in hooks.items()):
        return False
    return same_as_plugin(snap, GITHOOKS_RUN)


def plugin_version() -> str:
    try:
        return json.loads((PLUGIN / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))["version"]
    except (OSError, ValueError, KeyError, TypeError):
        return "?"


def clean_environment() -> None:
    """No PYTHON* variable reaches what runs or the Python it starts, no bytecode is written (a .pyc next to approved
    code is code the fingerprint never saw), and PATH keeps only absolute entries: a relative one (`.`, an empty
    one) would look commands up in the project, where the scripts run git."""
    for key in [k for k in os.environ if k.startswith("PYTHON")]:
        del os.environ[key]
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    sys.dont_write_bytecode = True
    parts = os.environ.get("PATH", "").split(os.pathsep)
    os.environ["PATH"] = os.pathsep.join(p for p in parts if p and os.path.isabs(p)) or os.defpath


def execute(path: Path, data: bytes, argv: list[str]) -> None:
    """Runs `data` as the script at `path` would run, in this process: the bytes that were checked are the bytes
    that run, so nothing can swap the file between the check and the run."""
    code = compile(data, str(path), "exec", dont_inherit=True)
    module = types.ModuleType("__main__")
    module.__file__ = str(path)
    module.__builtins__ = builtins
    sys.modules["__main__"] = module
    sys.argv = [str(path), *argv]
    exec(code, module.__dict__)


def project_dir(arg: str | None = None) -> Path | None:
    raw = arg if arg is not None else os.environ.get("CLAUDE_PROJECT_DIR", "")
    if not raw:
        return None
    p = Path(raw).resolve()
    return p if p.is_dir() else None


def choose(tool: str, project: Path) -> tuple[Path, bytes, list[str]] | None:
    """(the file to run as, its bytes, the arguments before the hook's own), or None when the project lacks it.
    One snapshot decides, and its bytes are the ones that run."""
    names = RUNS[tool]
    if not os.path.lexists(project / BIN / names[0]):
        return None
    snap = snapshot(project)
    if not same_as_plugin(snap, names) and approved_snapshot(project, snap):
        data = files_in(snap).get(names[0])
        if data is not None:
            return project / BIN / names[0], data, []
    ours = BUNDLED / names[0]
    data = plugin_bytes(ours)
    if data is None:
        raise SystemExit(f"Keelokit: the plugin's {names[0]} is missing ({ours}); reinstall the plugin")
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
    os.chdir(project)
    execute(path, data, [*before, *args])
    return 0


def check(arg: str | None = None) -> int:
    project = project_dir(arg)
    if project is None:
        return 0
    snap = snapshot(project)
    off = differing(snap)
    if not off or approved_snapshot(project, snap):
        return 0
    print(f"Keelokit: this project's {', '.join(off)} in .keelokit/bin differ from the plugin's, so the hooks run "
          f"Keelokit {plugin_version()}'s copy against this project's data and never the project's own. An older "
          f"harness: /keelokit:harness-upgrade. Changes of your own: review and approve them in your terminal with "
          f"python3 -I {shlex.quote(str(Path(__file__).resolve()))} trust {shlex.quote(str(project))}")
    return 0


def git(project: Path, *args: str) -> str | None:
    """stdout of a git call in the project that fires no hook (config and rev-parse), or None when it fails."""
    try:
        out = subprocess.run(["git", "-C", str(project), *args], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout if out.returncode == 0 else None


def githooks(arg: str | None = None) -> int:
    """LEDGER-009.S7, made safe (ESC-271): a clone with .githooks and no hooks path gets core.hooksPath .githooks
    only when its hooks are the plugin's (and so are the scripts they run) or a person approved them."""
    project = project_dir(arg)
    if project is None or os.path.islink(project / HOOKS) or not os.path.isdir(project / HOOKS):
        return 0
    clean_environment()
    top = git(project, "rev-parse", "--show-cdup")
    if top is None or top.strip() or git(project, "config", "--get", "core.hooksPath") is not None:
        return 0
    snap = snapshot(project)
    if githooks_like_plugin(snap) or approved_snapshot(project, snap):
        if git(project, "config", "core.hooksPath", ".githooks") is not None:
            print(TURNED_ON)
        return 0
    me = shlex.quote(str(Path(__file__).resolve()))
    print(f"Keelokit: this repo's .githooks are not the plugin's (or run a .keelokit/bin that isn't), so they stay "
          f"off and git runs none of them. Review them with python3 -I {me} show, then approve them in your terminal "
          f"with `trust`, or turn them on yourself: git config core.hooksPath .githooks")
    return 0


def visible(text: str) -> str:
    """Every character a terminal would not show as itself (controls, bidi overrides, zero-width and odd spaces,
    tabs) written as an escape, so the reviewer sees exactly what they approve."""
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


def report(snap) -> list[str]:
    """What differs between the project's .keelokit/bin and .githooks and the plugin's, every line escaped."""
    out = []
    for d, name, kind, data in snap:
        ours = plugin_bytes((BUNDLED if d == BIN else BUNDLED_HOOKS) / name) if name else None
        if kind == "file" and data is not None and data == ours:
            continue
        head = f"== {d}/{visible(name)} ({visible(kind)})"
        if kind != "file" or data is None:
            out.append(f"{head}: its content is not read")
            continue
        out.append(head + (": not in the plugin" if ours is None else ""))
        for line in difflib.unified_diff(lines_of(ours), lines_of(data), "plugin", "project", lineterm="", n=2):
            out.append(visible(line))
    return out


def show(arg: str | None) -> int:
    project = project_dir(arg) or Path.cwd().resolve()
    snap = snapshot(project)
    lines = report(snap)
    print("\n".join(lines) if lines else f"Keelokit: {project}'s .keelokit/bin and .githooks match the plugin's.")
    why = unapprovable(snap)
    print(f"fingerprint: {fingerprint_of(snap)}  approved: {'yes' if approved_snapshot(project, snap) else 'no'}"
          + (f"  (cannot be approved: {visible(why)})" if why else ""))
    return 0


def ask(prompt: str) -> str | None:
    """A line typed on the controlling terminal, never stdin: None when there is no terminal. Unbuffered bytes on a
    file descriptor: a terminal is not seekable, so a text-mode "r+" file can't be opened on it (ESC-273)."""
    try:
        fd = os.open("/dev/tty", os.O_RDWR | os.O_NOCTTY)
    except OSError:
        return None
    try:
        if not os.isatty(fd):
            return None
        os.write(fd, prompt.encode("utf-8", "replace"))
        line = b""
        while not line.endswith(b"\n") and len(line) < 256:
            chunk = os.read(fd, 1)
            if not chunk:
                break
            line += chunk
        return line.decode("utf-8", "replace").strip()
    except OSError:
        return None
    finally:
        os.close(fd)


def trust(arg: str | None) -> int:
    project = project_dir(arg) or Path.cwd().resolve()
    if not os.path.lexists(project / BIN) and not os.path.lexists(project / HOOKS):
        print(f"Keelokit: {project} has no .keelokit/bin and no .githooks", file=sys.stderr)
        return 2
    snap = snapshot(project)
    if why := unapprovable(snap):
        print(f"Keelokit: this cannot be approved: {visible(why)}. Only plain files can be approved (a directory, a "
              f"link or a special file is something a fingerprint can't pin down); the hooks run the plugin's copy.",
              file=sys.stderr)
        return 2
    lines = report(snap)
    if not lines:
        print(f"Keelokit: {project}'s .keelokit/bin and .githooks match the plugin's; nothing to approve.")
        return 0
    fp = fingerprint_of(snap)
    answer = ask("\n".join(lines) + (f"\n\nThe hooks would run this project's .keelokit/bin and .githooks as shown "
                                     f"above (fingerprint {fp}).\nType its first 8 characters to approve it: "))
    if answer is None:
        print(f"Keelokit: {WHY_TRUST}: run this in your own terminal (it asks there, not on stdin).", file=sys.stderr)
        return 2
    if answer != fp[:8]:
        print("Keelokit: not approved.", file=sys.stderr)
        return 1
    if fingerprint(project) != fp:
        print("Keelokit: .keelokit/bin or .githooks changed while you read them; not approved.", file=sys.stderr)
        return 1
    projects = read_store()
    projects[str(project)] = {"fingerprint": fp, "approved": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    write_store(projects)
    print(f"Keelokit: approved; the hooks run {project}'s own .keelokit/bin until it or .githooks change.")
    return 0


def untrust(arg: str | None) -> int:
    project = project_dir(arg) or Path.cwd().resolve()
    projects = read_store()
    if projects.pop(str(project), None) is not None:
        write_store(projects)
    print(f"Keelokit: the hooks run the plugin's copy for {project} unless its .keelokit/bin matches it.")
    return 0


COMMANDS = {"check": check, "githooks": githooks, "show": show, "trust": trust, "untrust": untrust}


def main(argv: list[str]) -> int:
    cmd, rest = (argv[0], argv[1:]) if argv else ("", [])
    if cmd == "run" and rest:
        return run(rest[0], rest[1:])
    if cmd in COMMANDS and len(rest) <= 1:
        return COMMANDS[cmd](rest[0] if rest else None)
    print(__doc__.split("\n\n")[1], file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
