#!/usr/bin/env python3
"""The plugin's hooks run the guard, the doctor and the ledger through this file, so that opening a repo
runs code a person controls, never the repo's own copy unchecked (HARN-004).

    python3 -I hooks/trusted.py run guard|doctor|ledger [ARGS…]   the hooks (project: $CLAUDE_PROJECT_DIR)
    python3 -I hooks/trusted.py check          one line when the project's own copy is not what runs, else nothing
    python3 -I hooks/trusted.py show [DIR]     how the project's .keelokit/bin differs from the plugin's, escaped
    python3 -I hooks/trusted.py trust [DIR]    a person approves the project's copy as it is now (asks on a terminal)
    python3 -I hooks/trusted.py untrust [DIR]  withdraws that approval

Which code runs is decided before anything from the project executes, by reading bytes, never by running them:
1. the project's copy of every script the hook runs (guard.py; ledger.py; doctor.py with the ledger.py and
   ux_gate.py it runs) is byte for byte the plugin's: the plugin's copy runs, with `--root <project>`;
2. else, this machine's trust store holds the fingerprint of the project's .keelokit/bin as it is now, approved
   for this project by a person with `trust`: the project's copy runs, from the very bytes that were checked;
3. else the plugin's copy runs against the project's data (its rules, rules.local.toml, state, backlog), and
   `check` says so in one line at the session start. The project's file never runs.
The trust store is ~/.config/keelokit/trusted.json of the user running it, found from the password database, not
from $HOME, which a repo's settings could set. `trust` reads its answer from the terminal (/dev/tty) and asks for
the fingerprint's first characters, so neither a pipe nor an agent's shell approves anything by accident; the
guard also refuses it to agents.
Whatever runs gets no PYTHON* variables and no relative PATH entries, so neither a planted module nor a planted
`git` in the project is reached; the hooks cd into the plugin before looking python3 up, for the same reason.
Only the Python standard library, and nothing it imports is looked up next to this file (`-I`).
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
import tempfile  # noqa: E402
import types  # noqa: E402
import unicodedata  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

PLUGIN = Path(__file__).resolve().parents[1]
BUNDLED = PLUGIN / "template/.keelokit/bin"
BIN = ".keelokit/bin"
# What each hook runs: the entry script first, then the scripts it runs in turn.
RUNS = {"guard": ("guard.py",), "ledger": ("ledger.py",), "doctor": ("doctor.py", "ledger.py", "ux_gate.py")}
HOOKED = ("guard.py", "doctor.py", "ledger.py", "ux_gate.py")
MAX_BYTES = 8 << 20  # a script bigger than this is never read whole: it can't be the plugin's
MAX_ENTRIES = 512
WHY_TRUST = "approving the code Keelokit's hooks run is a person's decision"


def store_path() -> Path:
    return Path(pwd.getpwuid(os.getuid()).pw_dir) / ".config/keelokit/trusted.json"


def regular_bytes(path: Path) -> bytes | None:
    """The bytes of a regular file (a symlink is followed), or None: missing, a FIFO, a device, a directory, too big.
    Opened without blocking, so a FIFO planted where a script should be can't hang the hook."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0))
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


def present(path: Path) -> bool:
    return os.path.lexists(path)


def same_as_plugin(project: Path, names) -> bool:
    """Every one of `names` that the project has is byte for byte the plugin's."""
    for name in names:
        mine = project / BIN / name
        if not present(mine):
            continue
        ours = regular_bytes(BUNDLED / name)
        if ours is None or regular_bytes(mine) != ours:
            return False
    return True


def entries(project: Path) -> list[tuple[str, str, bytes | None]]:
    """(name, kind, bytes) for each entry of the project's .keelokit/bin, sorted: what a fingerprint covers."""
    d = project / BIN
    try:
        names = sorted(os.listdir(d))[:MAX_ENTRIES + 1]
    except OSError:
        return []
    out = []
    for name in names:
        p = d / name
        try:
            mode = os.lstat(p).st_mode
        except OSError:
            continue
        if stat.S_ISLNK(mode):
            kind = "symlink → " + os.readlink(p)
            data = regular_bytes(p)
        elif stat.S_ISREG(mode):
            kind, data = "file", regular_bytes(p)
            kind = kind if data is not None else "file too big to read"
        else:
            kind, data = ("directory" if stat.S_ISDIR(mode) else "special file"), None
        out.append((name, kind, data))
    return out


def fingerprint(project: Path) -> str:
    h = hashlib.sha256(b"keelokit-bin-1\0")
    found = entries(project)
    if len(found) > MAX_ENTRIES:
        return "too-many-entries"
    for name, kind, data in found:
        h.update(name.encode("utf-8", "surrogateescape") + b"\0" + kind.encode("utf-8", "surrogateescape") + b"\0")
        h.update(hashlib.sha256(data).digest() if data is not None else b"-")
    return h.hexdigest()


def read_store() -> dict:
    """The trust store, or {} when it is missing, unreadable, not the user's own or writable by others."""
    p = store_path()
    try:
        fd = os.open(p, os.O_RDONLY | os.O_NONBLOCK)
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


def approved(project: Path) -> bool:
    entry = read_store().get(str(project))
    return isinstance(entry, dict) and entry.get("fingerprint") == fingerprint(project)


def differing(project: Path) -> list[str]:
    """The hooked scripts the project has that are not the plugin's, in the order the hooks run them."""
    return [n for n in HOOKED if present(project / BIN / n) and not same_as_plugin(project, (n,))]


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
    """(the file to run as, its bytes, the arguments before the hook's own), or None when the project lacks it."""
    names = RUNS[tool]
    if not present(project / BIN / names[0]):
        return None
    if not same_as_plugin(project, names) and approved(project):
        mine = project / BIN / names[0]
        data = regular_bytes(mine)
        if data is not None:
            return mine, data, []
    ours = BUNDLED / names[0]
    data = regular_bytes(ours)
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
    off = differing(project)
    if not off or approved(project):
        return 0
    print(f"Keelokit: this project's {', '.join(off)} in .keelokit/bin differ from the plugin's, so the hooks run "
          f"Keelokit {plugin_version()}'s copy against this project's data and never the project's own. An older "
          f"harness: /keelokit:harness-upgrade. Changes of your own: review and approve them in your terminal with "
          f"python3 -I {shlex.quote(str(Path(__file__).resolve()))} trust {shlex.quote(str(project))}")
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


def report(project: Path) -> list[str]:
    """What differs between the project's .keelokit/bin and the plugin's, every line escaped."""
    out = []
    for name, kind, data in entries(project):
        ours = regular_bytes(BUNDLED / name)
        if kind == "file" and data is not None and data == ours:
            continue
        head = f"== .keelokit/bin/{visible(name)} ({visible(kind)})"
        if data is None:
            out.append(f"{head}: its content is not read")
            continue
        out.append(head + (": not in the plugin" if ours is None else ""))
        for line in difflib.unified_diff(lines_of(ours), lines_of(data), "plugin", "project", lineterm="", n=2):
            out.append(visible(line))
    return out


def show(arg: str | None) -> int:
    project = project_dir(arg) or Path.cwd().resolve()
    lines = report(project)
    print("\n".join(lines) if lines else f"Keelokit: {project}'s .keelokit/bin matches the plugin's.")
    print(f"fingerprint: {fingerprint(project)}  approved: {'yes' if approved(project) else 'no'}")
    return 0


def ask(prompt: str) -> str | None:
    """A line typed on the controlling terminal, never stdin: None when there is no terminal."""
    try:
        with open("/dev/tty", "r+", encoding="utf-8", errors="replace") as tty:
            if not tty.isatty():
                return None
            tty.write(prompt)
            tty.flush()
            return tty.readline().strip()
    except OSError:
        return None


def trust(arg: str | None) -> int:
    project = project_dir(arg) or Path.cwd().resolve()
    if not present(project / BIN):
        print(f"Keelokit: {project} has no .keelokit/bin", file=sys.stderr)
        return 2
    lines = report(project)
    if not lines:
        print(f"Keelokit: {project}'s .keelokit/bin matches the plugin's; the hooks run the plugin's copy already.")
        return 0
    fp = fingerprint(project)
    tty_text = "\n".join(lines) + (f"\n\nThe hooks would run this project's .keelokit/bin as shown above "
                                   f"(fingerprint {fp}).\nType its first 8 characters to approve it: ")
    answer = ask(tty_text)
    if answer is None:
        print(f"Keelokit: {WHY_TRUST}: run this in your own terminal (it asks there, not on stdin).", file=sys.stderr)
        return 2
    if answer != fp[:8]:
        print("Keelokit: not approved.", file=sys.stderr)
        return 1
    if fingerprint(project) != fp:
        print("Keelokit: .keelokit/bin changed while you read it; not approved.", file=sys.stderr)
        return 1
    projects = read_store()
    projects[str(project)] = {"fingerprint": fp, "approved": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    write_store(projects)
    print(f"Keelokit: approved; the hooks run {project}'s own .keelokit/bin until it changes.")
    return 0


def untrust(arg: str | None) -> int:
    project = project_dir(arg) or Path.cwd().resolve()
    projects = read_store()
    if projects.pop(str(project), None) is not None:
        write_store(projects)
    print(f"Keelokit: the hooks run the plugin's copy for {project} unless its .keelokit/bin matches it.")
    return 0


def main(argv: list[str]) -> int:
    cmd, rest = (argv[0], argv[1:]) if argv else ("", [])
    if cmd == "run" and rest:
        return run(rest[0], rest[1:])
    if cmd in ("check", "show", "trust", "untrust") and len(rest) <= 1:
        return {"check": check, "show": show, "trust": trust, "untrust": untrust}[cmd](rest[0] if rest else None)
    print(__doc__.split("\n\n")[1], file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
