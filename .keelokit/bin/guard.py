#!/usr/bin/env python3
"""One guard for two callers, so humans and agents hit the same wall.

    python3 .keelokit/bin/guard.py --claude          Claude Code PreToolUse hook (JSON on stdin)
    python3 .keelokit/bin/guard.py git-pre-commit    git pre-commit hook

Exit 2 blocks (Claude shows stderr to the agent); exit 1 blocks a git commit. Claude Code lets a
call through on any exit but 2, so for Claude the guard ends in exactly 0 or 2: an unknown mode,
hook input it can't read or a check that fails all block, with the reason on stderr.
Rules enforced: SEC-1, SEC-2, QA-2, QA-4, DB-1, AGENT-1, REL-1 (.keelokit/harness/rules.toml).
The ledger's corrections (backlog/ledger-corrections.toml) are the human's like guard-allow.toml: agents
may not write the file nor run `ledger.py backfill --accept` (docs/ledger.md, "Corrections file"). Who approves
them is the `[ledger.approval]` table of .keelokit/state.toml, the person's too: agents may not change it, and
only when the trunk's committed table delegates the approval may an agent run `backfill --accept --delegated
<run>` (with the run's verdicts in .keelokit/ledger-reviews/<run>.json) and commit the rows it wrote.

It is a speed bump for agents, not a sandbox: a determined shell (variables, eval, scripts)
can get around pattern checks. CI and the git hooks are the backstop.
"""
import sys

if sys.version_info < (3, 11):
    print(f"Keelokit guard needs Python 3.11+ (found {sys.version.split()[0]}); it is off.", file=sys.stderr)
    sys.exit(1)  # non-blocking: Claude shows the message, the tool call proceeds

import datetime as dt  # noqa: E402
import fnmatch  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import posixpath  # noqa: E402
import re  # noqa: E402
import shlex  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import stat  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
import tomllib  # noqa: E402
from pathlib import Path  # noqa: E402


def root_of(argv: list[str]) -> Path:
    """The project this runs on: `--root DIR`, first on the command line, or the one this file sits in. The plugin's
    hooks run their own copy with `--root <project>` (hooks/trusted.py, HARN-004)."""
    if argv[1:2] == ["--root"] and len(argv) > 2:
        root = Path(argv[2]).resolve()
        del argv[1:3]
        return root
    return Path(__file__).resolve().parents[2]


ROOT = root_of(sys.argv)

PLUGIN_MODE = ROOT != Path(__file__).resolve().parents[2]  # run with --root: by the plugin's hooks (HARN-004)
# Variables that point git at another repository, or at programs to run: none comes from the session's environment.
GIT_SCRUB = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
             "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE", "GIT_EXEC_PATH", "GIT_CONFIG", "GIT_SSH",
             "GIT_SSH_COMMAND", "GIT_ASKPASS", "GIT_EXTERNAL_DIFF", "GIT_PAGER", "GIT_EDITOR")


def harden_git(hooks_off: bool) -> None:
    """HARN-004 (ESC-271, ESC-280): run by the plugin's hooks, every git call of this copy reads no repository the
    project ships (a directory with HEAD, config, objects/ and refs/ is not a bare repository to it), runs no
    transport helper (ext::), no lazy fetch, no fsmonitor, prompts for nothing, and fires no git hook. git
    reads GIT_CONFIG_* as `-c`, above every config file."""
    for key in GIT_SCRUB:
        os.environ.pop(key, None)
    config = {"safe.bareRepository": "explicit", "protocol.ext.allow": "never", "protocol.file.allow": "always",
              "core.fsmonitor": "false"}
    if hooks_off:
        config["core.hooksPath"] = os.devnull
    try:
        n = max(int(os.environ.get("GIT_CONFIG_COUNT") or 0), 0)
    except ValueError:
        n = 0
    for key, value in config.items():
        os.environ[f"GIT_CONFIG_KEY_{n}"] = key
        os.environ[f"GIT_CONFIG_VALUE_{n}"] = value
        n += 1
    os.environ["GIT_CONFIG_COUNT"] = str(n)
    os.environ.update(GIT_NO_LAZY_FETCH="1", GIT_TERMINAL_PROMPT="0", GIT_PROTOCOL_FROM_USER="0")


def git_dir_problem() -> str | None:
    """Why git must not run for ROOT, or None: the repository git finds has its git dir inside ROOT but is not
    ROOT/.git (a directory the repo ships, read as a repository by a git too old for safe.bareRepository)."""
    try:
        out = subprocess.run(["git", "rev-parse", "--absolute-git-dir"], cwd=ROOT, capture_output=True, text=True,
                             timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    found, root = Path(out.stdout.strip()).resolve(), ROOT.resolve()
    if found == root / ".git" or root not in (found, *found.parents):
        return None
    return (f"git reads {found} as this project's repository, a directory inside it that is not its .git, so "
            f"Keelokit runs no git here")


if PLUGIN_MODE:
    harden_git(True)
ENV_OK = {".env.example", ".env.ci"}
# ESC-276: Claude Code lets a call through when the hook outlives its timeout, so the guard bounds what it reads and
# how long its git calls take, and blocks when a bound is hit (hooks/hooks.json gives the hook more than GIT_SECONDS).
MAX_DATA = 1 << 20
GIT_SECONDS = 30
_GIT_DEADLINE = time.monotonic() + GIT_SECONDS


class GuardLimit(Exception):
    """A bound the guard keeps was hit: the call is blocked."""


def read_data(path: Path) -> bytes:
    """A data file's bytes, read without blocking and at most MAX_DATA of them. OSError as reading would raise it (a
    missing file); GuardLimit for a FIFO, a device or a file over the bound."""
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise GuardLimit(f"{rel_shown(path)} is not a regular file")
        data = os.read(fd, MAX_DATA + 1)
        if len(data) > MAX_DATA or st.st_size > MAX_DATA:
            raise GuardLimit(f"{rel_shown(path)} is over {MAX_DATA >> 20} MB")
        while chunk := os.read(fd, MAX_DATA):  # a short read: the rest, still within the bound
            data += chunk
            if len(data) > MAX_DATA:
                raise GuardLimit(f"{rel_shown(path)} is over {MAX_DATA >> 20} MB")
        return data
    finally:
        os.close(fd)


def rel_shown(path: Path) -> str:
    try:
        return Path(path).relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def git_run(*args: str) -> subprocess.CompletedProcess:
    """A git call of the Claude hook: within what is left of GIT_SECONDS, and its output within MAX_DATA."""
    left = _GIT_DEADLINE - time.monotonic()
    if left <= 0:
        raise GuardLimit(f"its git calls took more than {GIT_SECONDS}s")
    try:
        out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, timeout=left)
    except subprocess.TimeoutExpired:
        raise GuardLimit(f"its git calls took more than {GIT_SECONDS}s") from None
    if len(out.stdout) > MAX_DATA:
        raise GuardLimit(f"`git {' '.join(args)}` gave more than {MAX_DATA >> 20} MB")
    return out


SECRETS = [
    (r"AKIA[0-9A-Z]{16}", "AWS access key"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "private key"),
    (r"\bgh[pousr]_[A-Za-z0-9]{30,}", "GitHub token"),
    (r"\bgithub_pat_[A-Za-z0-9_]{40,}", "GitHub token"),
    (r"\bxox[baprs]-[A-Za-z0-9-]{10,}", "Slack token"),
    (r"\b[sr]k_live_[A-Za-z0-9]{16,}", "Stripe live key"),
    (r"\bsk-ant-[A-Za-z0-9_-]{20,}", "Anthropic API key"),
    (r"\bsk-(proj-)?[A-Za-z0-9_-]{32,}", "OpenAI-style API key"),
    (r"\bAIza[0-9A-Za-z_-]{35}", "Google API key"),
    (r"\bnpm_[A-Za-z0-9]{36}\b", "package registry token"),
    (r"\bglpat-[A-Za-z0-9_-]{20,}", "GitLab token"),
    (r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{16,}", "JWT"),
    (r"\bAccountKey=[A-Za-z0-9+/]{40,}={0,2}", "Azure storage key"),
]
# A password in a URL is a secret unless, as a whole, it is a reference to a variable (HARN-020):
# `${NAME}`, `$NAME` or `${{ ctx.name }}`. A literal, alone or mixed with a reference, still is.
# The alternatives of a password's tokens are disjoint (a closed `${{ … }}`, an unclosed `${{` taken as text,
# a `$` not followed by `{{`, a character that is no `$`), so a failing match can't backtrack through two ways of reading one text.
# ESC-279: an expression is at most EXPR characters, the same bound in the token and in the look-ahead that tells a
# closed one from an unclosed one, so each `${{` costs a bounded look and a password is read in linear time (an
# unbounded look-ahead made every `${{` scan to the end of the line: quadratic, minutes on 100 KB).
EXPR = 200
URL_PASSWORD = (rf"(?P<pw>(?:\$\{{\{{[^}}\n]{{0,{EXPR}}}\}}\}}|\$\{{\{{(?![^}}\n]{{0,{EXPR}}}\}}\}})|\$(?!\{{\{{)"
                rf"|[^/\s@$])+)")
URL_SECRETS = [
    (rf"https?://[^/\s:@]+:{URL_PASSWORD}@github\.com", "credentials in a git URL"),
    # A DB URL with a password, unless it points at this machine (local/dev/CI values).
    (rf"\b(postgres(ql)?|mysql|mongodb(\+srv)?|redis)://[^/\s:@]+:{URL_PASSWORD}@(?!(localhost|127\.0\.0\.1|postgres|db)[:/])",
     "database URL with a password"),
]
# A bare `$NAME` counts only in capitals (`$uperSecret1` is a password); in braces any identifier does.
REFERENCE = re.compile(r"\$\{[A-Za-z_]\w*\}|\$[A-Z_][A-Z0-9_]*"
                       r"|\$\{\{\s*(?:secrets|env|vars|inputs|github|matrix|needs|steps|job|runner)\.[\w.-]+\s*\}\}")
TAMPER = [
    (r"\b(it|test|describe)\.(skip|only|todo)\s*\(", "a skipped or focused test"),
    (r"(?<![\w.])x(it|test|describe)\s*\(", "a disabled test"),
    (r"eslint-disable", "an eslint-disable comment"),
    (r"@ts-(ignore|nocheck)", "a @ts-ignore / @ts-nocheck"),
    # Every spelling of an always-true value (LOG-202): true, True, ${{ true }}, each bare or quoted.
    (r"continue-on-error:\s*(?i:['\"]?(?:true\b|\$\{\{\s*true\s*\}\}))", "continue-on-error in CI"),
]
# git's own options come before the subcommand, and -C, -c and these long ones take the next word
# as their value (`git -C dir commit -n`). A value may be quoted ('' by now) or hold `\ `.
GIT_VALUE = r"(?:\\.|[^\s\\])+"
# ESC-279: an option that takes the next word is never also read as a bare `-word` (the look-ahead), so each option
# has one reading and a command that doesn't match fails in linear time (`git -C -C -C …` took minutes).
GIT_TAKES = r"(?:[Cc]|-(?:git-dir|work-tree|namespace|config-env|attr-source))"  # after the option's first dash
GIT = rf"\bgit(?:\s+(?:-{GIT_TAKES}\s+|-(?!{GIT_TAKES}(?:\s|$))){GIT_VALUE})*?\s+"
# The rest of that git command: up to a shell separator, or `--`, after which come paths.
GIT_ARGS = r"(?:(?!\s--(?![^\s;&|]))[^|;&\n])*"
# A short-option bundle ends at the token's end (-nm"msg" is emptied to -nm'').
BUNDLE_END = r"(?![^\s;&|<>()])"
GIT_NO_HOOKS = [
    # git takes any unambiguous prefix of a long option: --no-veri(f) is --no-verify.
    # The first `git` of a line is enough (what follows a later one follows it too): atomic, so a line with many
    # `git`s and no flag fails in linear time (ESC-279).
    (r"(?m)^(?>.*?\bgit\b).*\s--no-veri(fy?)?(?![\w-])", "QA-2: never bypass git hooks"),
    # A short-option bundle skips hooks when -n is one of its letters: flags that take no value
    # (as in `git commit -h`), then n, then maybe one option whose value is the rest (-nm"msg").
    # In -uno or -mn the n is a value, not -n.
    (rf"{GIT}commit\b{GIT_ARGS}\s-[aeiopqsvz]*n[aeinopqsvz]*([FmcCtSuU]\S*)?{BUNDLE_END}",
     "QA-2: `commit -n` skips the git hooks"),
    (r"(?i)keelokit\.allowtamper", "QA-4: only a human may allow a skipped test or silenced check"),
    # Config names are case-insensitive: core.hookspath is core.hooksPath.
    (rf"(?i){GIT}(?:-c\s+|--config-env[=\s]\s*)core\.hookspath\b", "QA-2: don't override the hooks path"),
    (rf"(?i){GIT}config\b{GIT_ARGS}\bcore\.hookspath\b", "QA-2: the hooks path is set by the project's install step; ask a human to change it"),
    # -f bundled with push's no-value flags (-uf, -vf; -o takes the rest as its value), --force and
    # every --force-… but -with-lease, and --mirror, which force-updates, in any prefix git accepts.
    (rf"{GIT}push\b{GIT_ARGS}\s(-[46dnquv]*f[46dfnquv]*(o\S*)?{BUNDLE_END}|--force(?!-w)(-[\w-]*)?(?![\w-])"
     r"|--m(i(r(r(or?)?)?)?)?(?![\w-]))", "QA-2: no force-push (use --force-with-lease on your own branch)"),
    (rf"{GIT}push\b{GIT_ARGS}\s\+[\w./:-]+", "QA-2: `+ref` is a force-push"),
]
WRITE_CMD = re.compile(r"(>>?|\btee\b|\bcp\b|\binstall\b|\bmv\b|\bsed\s+-i|\bperl\s+-[a-z]*i|\btruncate\b|\brm\b|\btouch\b|\bln\b|\bdd\b)")


def unquoted(cmd: str) -> str:
    """The command with quoted strings emptied, so a commit message or a grep pattern that
    merely mentions `--no-verify` or `fly deploy` doesn't trip the guard."""
    return re.sub(r"'[^']*'|\"(?:\\.|[^\"\\])*\"", "''", cmd)


def is_env_file(path: str) -> bool:
    name = Path(path).name
    if name in ENV_OK or name.endswith(".example"):
        return False
    return name.startswith(".env") or name.endswith(".env") or name == ".envrc"


def repo_rel(path: str) -> Path | None:
    p = Path(path)
    if not p.is_absolute():
        return p
    try:
        return p.resolve().relative_to(ROOT)
    except ValueError:
        return None


def applied_migration(path: str) -> bool:
    rel = repo_rel(path)
    if rel is None or "prisma/migrations/" not in rel.as_posix() or rel.name == "migration_lock.toml":
        return False
    return git_run("cat-file", "-e", f"origin/main:{rel.as_posix()}").returncode == 0


def secret_in(text: str) -> str | None:
    if label := next((label for pattern, label in SECRETS if re.search(pattern, text)), None):
        return label
    for pattern, label in URL_SECRETS:
        for m in re.finditer(pattern, text):  # every URL: a reference one doesn't vouch for the next
            if not REFERENCE.fullmatch(m["pw"]):
                return label
    return None


# --- The registry of paths SEC-1 and SEC-2 let through (HARN-020) --------------------------------
# .keelokit/guard-allow.toml: [[allow]] entries with rule, path or glob, reason, approver, expires.
# BOUNDS: the doctor (bin/doctor.py, check_guard_allow) keeps its own copy of everything between
# here and "end of the bounds"; change both together (a test compares them).
REGISTRY = ".keelokit/guard-allow.toml"
ALLOW_RULES = ("SEC-1", "SEC-2")
WILDCARDS = "*?["  # a path has none of these; a glob has `*` and `?` only (no `[` or `]`)


def _plain(value: object) -> bool:
    """A non-empty text without control characters (NUL included)."""
    return isinstance(value, str) and bool(value.strip()) and not any(ord(c) < 32 or ord(c) == 127 for c in value)


def _components(value: str) -> list[str] | None:
    """The parts of a repo-relative POSIX path, or None: absolute, `./`, `..`, `//`, trailing `/`, `\\`."""
    parts = value.split("/")
    if "\\" in value or any(p in ("", ".", "..") for p in parts):
        return None
    return parts


def allow_problem(entry: object, today: dt.date | None = None) -> str | None:
    """Why an [[allow]] entry is not active (invalid, unbounded or expired), or None when it is."""
    if not isinstance(entry, dict):
        return "is not a table"
    if entry.get("rule") not in ALLOW_RULES:
        return "rule is SEC-1 or SEC-2"
    if not _plain(entry.get("reason")) or not _plain(entry.get("approver")):
        return "needs a reason and an approver"
    path, glob = entry.get("path"), entry.get("glob")
    if (path is None) == (glob is None):
        return "needs exactly one of path or glob"
    if path is not None:
        parts = _components(path) if _plain(path) else None
        if parts is None or any(c in path for c in WILDCARDS):
            return "path is a file relative to the repo root: no leading / or ./, no .., no wildcards, no trailing /"
    else:
        parts = _components(glob) if _plain(glob) else None
        if parts is None or len(parts) < 2 or "**" in glob or any(c in "[]" for c in glob) \
                or any(c in WILDCARDS for d in parts[:-1] for c in d):
            return "glob is directory/pattern: a literal directory, only * and ? in the file name, no **, no .., no [ or ]"
        if len(re.sub(r"[*?]", "", parts[-1])) < 2:
            return "glob's file name needs at least two literal characters"
    expires = entry.get("expires")
    if expires is not None and expires != "permanent":
        if isinstance(expires, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", expires):
            try:
                expires = dt.date.fromisoformat(expires)
            except ValueError:
                return "expires is a date (YYYY-MM-DD) or permanent"
        if not isinstance(expires, dt.date) or isinstance(expires, dt.datetime):
            return "expires is a date (YYYY-MM-DD) or permanent"
        if expires < (today or dt.date.today()):
            return f"expired on {expires}"
    return None


def allow_matches(entry: dict, rel: str) -> bool:
    """Whether a repo-relative POSIX path is the entry's path, or a file directly in its glob's directory."""
    if "path" in entry:
        return rel == entry["path"]
    directory, _, name = entry["glob"].rpartition("/")
    return posixpath.dirname(rel) == directory and fnmatch.fnmatchcase(posixpath.basename(rel), name)
# --- end of the bounds -----------------------------------------------------------------------------


def active_allowed(text: str | bytes | None) -> list[dict]:
    """The active entries of a registry's text; any parse or type error means no entries."""
    try:
        if text is None:
            return []
        data = tomllib.loads(text.decode("utf-8") if isinstance(text, bytes) else text)
        entries = data.get("allow")
        return [e for e in entries if allow_problem(e) is None] if isinstance(entries, list) else []
    except Exception:  # bad TOML or bytes, a directory, anything: nothing is allowed
        return []


def committed_registry() -> list[dict]:
    """The registry as of the last commit: what the Claude hook honours, so a write an agent slips past
    the shell check exempts nothing until a human commits it. No registry there means no entries."""
    out = git_run("show", f"HEAD:{REGISTRY}")
    return active_allowed(out.stdout) if out.returncode == 0 else []


def staged_registry() -> list[dict]:
    """The registry as staged, so an unstaged edit exempts nothing."""
    out = subprocess.run(["git", "show", f":{REGISTRY}"], cwd=ROOT, capture_output=True)
    return active_allowed(out.stdout) if out.returncode == 0 else []


def rel_posix(path: str) -> str | None:
    """The repo-relative POSIX spelling of a path (absolute ones inside the repo count), or None."""
    rel = repo_rel(path)
    if rel is None:
        return None
    norm = posixpath.normpath(rel.as_posix())
    return None if norm == ".." or norm.startswith("../") else norm


def allowed(entries: list[dict], rule: str, path: str) -> bool:
    rel = rel_posix(path) if path else None
    return rel is not None and any(e["rule"] == rule and allow_matches(e, rel) for e in entries)


def is_registry(path: str) -> bool:
    return bool(path) and rel_posix(path) == REGISTRY


CORRECTIONS = "backlog/ledger-corrections.toml"
SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
CORRECTIONS_WHY = (f"QA-4: {CORRECTIONS} holds the ledger's approved corrections and is the human's: propose rows "
                   "with `ledger.py backfill --propose` or `ledger.py correct`; a person accepts them in their terminal")
ACCEPT_WHY = ("QA-4: `ledger.py backfill --accept` approves ledger corrections and is a person's, in their own "
              "terminal: propose the rows and ask in chat")


def protected_why(target: str) -> str | None:
    """Why a write to this path (or to a file of that name, once the shell may be elsewhere) is the human's: the
    registry, git's own config and hooks, the plugin's code. The corrections file has its own, narrower reading of a
    command (corrections_write)."""
    if target and (is_registry(target) or Path(target).name == Path(REGISTRY).name):
        return REGISTRY_WHY
    if target and git_internal(target):
        return GIT_INTERNALS_WHY
    if target and in_plugin(target.lstrip(">")):
        return PLUGIN_WHY
    if target and claude_settings(target):
        return SETTINGS_WHY
    if target and hooked(target):
        return HOOKS_ON_WHY
    return None


CORRECTIONS_NAME = Path(CORRECTIONS).name
# Command words that write every file they name, or only their last argument (the destination).
WRITE_ALL = {"tee", "mv", "rm", "truncate", "touch", "shred", "unlink", "patch"}
WRITE_LAST = {"cp", "install", "ln", "rsync", "scp"}
GIT_WRITES = {"checkout", "restore", "mv", "rm", "apply", "reset", "stash"}
INTERPRETERS = re.compile(r"(?:python[0-9.]*|perl|ruby|node|php|deno)")
REDIRECT = re.compile(r"(?<![<>])(?:[0-9]|&)?>{1,2}\|?\s*['\"]?([^\s;&|<>()'\"]+)")
PREFIXES = {"sudo", "env", "nohup", "command", "nice", "time"}


def is_corrections(word: str) -> bool:
    """The word names the corrections file, in any case (a case-insensitive disk writes the same file); an option's
    value counts (`--output=<file>`, `of=<file>`)."""
    value = word.split("=", 1)[-1] if "=" in word else word
    return bool(value) and Path(value).name.lower() == CORRECTIONS_NAME


def corrections_write(cmd: str) -> bool:
    """True when a segment writes the corrections file: a redirect to it, a command that writes the files it names
    (tee, mv, rm, …) or its destination (cp, install, …), `sed -i`/`perl -i` on it, git commands that write the
    work tree (`checkout … -- <file>`, `restore`, `rm`, `--output=<file>`), or inline code (`python3 -c`) that names
    it. A read (`cat <file> 2>/dev/null`, `sed -n`, `find -name`), `git add` or a message that names it passes.
    A command that writes it without naming it (`git checkout feat -- .`, `git apply`) is past this speed bump:
    the pre-commit hook still refuses the commit."""
    return named_write(cmd, CORRECTIONS_NAME)


def named_write(cmd: str, name: str) -> bool:
    """True when a segment writes a file of this name (lowercase), read as corrections_write reads a command."""
    def names_it(word: str) -> bool:
        value = word.split("=", 1)[-1] if "=" in word else word
        return bool(value) and Path(value).name.lower() == name

    for segment in segments(cmd):
        if name not in segment.lower():
            continue
        if any(names_it(t) for t in REDIRECT.findall(segment)):
            return True
        try:
            words = shlex.split(segment, posix=True)
        except ValueError:
            words = segment.split()
        while words and (words[0] in PREFIXES or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", words[0])):
            words = words[1:]
        if not words:
            continue
        head, args = Path(words[0]).name, words[1:]
        plain = [a for a in args if not a.startswith("-")]
        if head in WRITE_ALL and any(names_it(a) for a in args):
            return True
        if head in WRITE_LAST and plain and names_it(plain[-1]):
            return True
        aliasing = head in ("ln", "link") or (head == "cp" and any(
            a in ("--link", "--symbolic-link") or re.fullmatch(r"-[a-zA-Z]*[ls][a-zA-Z]*", a) for a in args))
        if aliasing and any(names_it(a) for a in args):  # an alias (link, cp -l/-s) of the file is a way to write it
            return True
        if head == "dd" and any(a.startswith("of=") and names_it(a) for a in args):
            return True
        if head in ("sed", "perl") and any(re.fullmatch(r"-[a-zA-Z]*i\S*", a) for a in args) \
                and any(names_it(a) for a in args):
            return True
        if head == "git":
            rest = list(args)
            while rest and rest[0].startswith("-"):
                rest = rest[2:] if rest[0] in ("-C", "-c") else rest[1:]
            sub = rest[0] if rest else ""
            if sub in GIT_WRITES and any(names_it(a) for a in rest[1:]):
                return True
            outputs = [a for a in rest if a.startswith("--output=")] + \
                [rest[i + 1] for i in range(len(rest) - 1) if rest[i] in ("--output", "-o")]
            if any(names_it(o) for o in outputs):
                return True
        if INTERPRETERS.fullmatch(head) and any(a in ("-c", "-e", "-E", "-r") for a in args):
            return True
    return False


# A text command may name the accept command (a message, a PR body) unless its output goes to something that runs it.
TEXT_CMDS = {"git", "gh", "echo", "printf"}
# A path before the command never crosses another `|`, so each `|` is read up to the next one (`\S*` read every `|`
# after each one: quadratic, ESC-279).
RUNS_INPUT = re.compile(r"\|\s*(?:sudo\s+)?(?:[^\s|]*/)?(?:sh|bash|zsh|dash|ksh|script|xargs|tmux|unbuffer|eval|source)\b")


def runs_accept(cmd: str, depth: int = 0) -> bool:
    """True when a segment of the command runs a person's ledger command (accept_problem)."""
    return accept_problem(cmd, depth) is not None


def accept_problem(cmd: str, depth: int = 0) -> str | None:
    """Why the command may not run, when a segment runs `ledger.py backfill --accept` or `ledger.py review
    --reject-sample`: its words as the shell splits them (quotes removed), and the script a shell runs
    (`bash -c "…"`, `eval "…"`). A quoted commit message is an argument, not a script, so naming the command there
    is no run. The one exception: `python3 <path>/ledger.py backfill --accept --delegated <run>`, word for word,
    when the trunk's committed [ledger.approval] delegates and the run's review file holds the verdicts."""
    runs_input = RUNS_INPUT.search(cmd)  # once: per segment, it read the whole command again (ESC-279)
    for segment in segments(cmd):
        try:
            words = shlex.split(segment, posix=True)
        except ValueError:
            words = segment.split()
        delegated = False
        for i, w in enumerate(words):
            if Path(w).name != "ledger.py":
                continue
            rest = words[i + 1:]
            if "review" in rest and any(x.startswith("--reject-sample") for x in rest):
                return REJECT_WHY
            if "backfill" in rest and any(x.startswith("--accept") for x in rest):
                exact = rest[:3] == ["backfill", "--accept", "--delegated"] and len(rest) == 4 and \
                    all(re.fullmatch(r"(?:\S*/)?python[0-9.]*", x) for x in words[:i]) and len(words[:i]) <= 1 \
                    and rel_posix(w) == ".keelokit/bin/ledger.py" and not CHDIR.search(unquoted(cmd))
                if not exact:
                    return ACCEPT_WHY
                if why := delegated_gate(rest[3]):
                    return why
                delegated = True
        if delegated:
            continue
        # A wrapper that runs it from a string (script -c, tmux, xargs, `| sh`): the words as one text, unless the
        # segment only prints text (a commit message, a PR body, an echo) that nothing runs.
        text = words and Path(words[0]).name in TEXT_CMDS and not runs_input
        joined = " ".join(words)
        if words and not text and re.search(r"ledger\.py\b.*\breview\b.*--reject-sample", joined, re.S):
            return REJECT_WHY
        if words and not text and re.search(r"ledger\.py\b.*\bbackfill\b.*--accept", joined, re.S):
            return ACCEPT_WHY
        shell = next((i for i, w in enumerate(words) if Path(w).name in SHELLS), None)
        scripts = [words[i + 1] for i in range(len(words) - 1)
                   if shell is not None and i > shell and re.fullmatch(r"-[a-z]*c[a-z]*", words[i])]
        scripts += words[1:] if words[:1] == ["eval"] else []
        if depth < 3:
            for script in scripts:
                if why := accept_problem(script, depth + 1):
                    return ACCEPT_WHY if why != REJECT_WHY else why
    return None


# ── approval modes (docs/ledger.md, "Approval modes"): the [ledger.approval] table is the person's ──
STATE = ".keelokit/state.toml"
REVIEWS = ".keelokit/ledger-reviews"
RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
APPROVAL_WHY = ("QA-4: the [ledger.approval] table of .keelokit/state.toml says who approves the ledger's corrections "
                "and is the person's: ask in chat; they change it and commit with "
                "`git -c keelokit.allowTamper=true commit`")
STATE_SHELL_WHY = ("QA-4: don't write .keelokit/state.toml from the shell: edit it with the Edit tool (its "
                   "[ledger.approval] table is the person's)")
REJECT_WHY = ("QA-4: `ledger.py review --reject-sample` sends a delegated run back and is a person's, in their own "
              "terminal: tell them which sample row is wrong")
DELEGATED_OFF_WHY = ("QA-4: `ledger.py backfill --accept --delegated` needs the trunk's .keelokit/state.toml to "
                     "delegate approval ([ledger.approval] mode = \"delegated\" or \"mixed\", a person's commit); "
                     "otherwise a person accepts the rows in their terminal")


def approval_of(text: str | bytes | None):
    """The `ledger.approval` value of a state.toml text; None when absent or the text is not TOML."""
    try:
        if text is None:
            return None
        data = tomllib.loads(text.decode("utf-8") if isinstance(text, bytes) else text)
    except Exception:  # bad TOML or bytes: no table counts, as ledger.py reads it
        return None
    ledger = data.get("ledger")
    return ledger.get("approval") if isinstance(ledger, dict) else None


def delegates(table) -> bool:
    return isinstance(table, dict) and table.get("mode") in ("delegated", "mixed")


def git_bytes(*args: str) -> bytes | None:
    """stdout of a git call, or None when it fails."""
    out = git_run(*args)
    return out.stdout if out.returncode == 0 else None


def trunk_approval(trunk: str | None = None):
    """The [ledger.approval] table of the trunk's committed state.toml (origin/<trunk>, else the local branch), the
    one ledger.py honours; the trunk is [ledger] trunk, else [harbor] trunk, else main (or the one given)."""
    if trunk is None:
        try:
            trunk = trunk_of(read_data(ROOT / STATE))
        except OSError:
            trunk = "main"
    if trunk.startswith("-") or git_bytes("check-ref-format", f"refs/heads/{trunk}") is None:
        return None
    for ref in (f"refs/remotes/origin/{trunk}", f"refs/heads/{trunk}"):
        sha = git_bytes("rev-parse", "--verify", "-q", f"{ref}^{{commit}}")
        if sha:
            return approval_of(git_bytes("show", f"{sha.decode().strip()}:{STATE}"))
    return None


def review_data(text: str | bytes | None, run: str) -> dict | None:
    """A review file for this run (an object with run and a list of rows), or None when it is not one."""
    try:
        data = json.loads(text.decode("utf-8") if isinstance(text, bytes) else text) if text is not None else None
    except Exception:
        return None
    ok = isinstance(data, dict) and data.get("run") == run and isinstance(data.get("rows"), list)
    return data if ok else None


def review_rows(text: str | bytes | None, run: str) -> list | None:
    """The rows of a review file for this run, or None when it is not one."""
    data = review_data(text, run)
    return data["rows"] if data else None


def verdicts_missing(row) -> bool:
    """True when a review row lacks judge A's or judge B's verdict, or the skeptic's after two yeses."""
    if not isinstance(row, dict):
        return True
    a, b = (row.get(k).get("verdict") if isinstance(row.get(k), dict) else None for k in ("judge_a", "judge_b"))
    if a not in ("yes", "no") or b not in ("yes", "no"):
        return True
    skeptic = row.get("skeptic")
    return a == b == "yes" and not (isinstance(skeptic, dict) and isinstance(skeptic.get("refuted"), bool))


def approved_in(row: dict, rows: list) -> bool:
    """The review rows hold this corrections row (story, commit, kind) approved: decision approved, both judges yes
    and the skeptic's refutation failed."""
    for r in rows:
        if not isinstance(r, dict) or (r.get("story"), r.get("commit"), r.get("kind")) != \
                (row.get("story"), row.get("commit"), row.get("kind")):
            continue
        a, b, s = (r.get(k) if isinstance(r.get(k), dict) else {} for k in ("judge_a", "judge_b", "skeptic"))
        if r.get("decision") == "approved" and a.get("verdict") == b.get("verdict") == "yes" and s.get("refuted") is False:
            return True
    return False


def delegated_gate(run: str) -> str | None:
    """Why an agent may not run `backfill --accept --delegated <run>`, or None: the trunk's committed table
    delegates, and the run's review file in the work tree has every row's verdicts."""
    if not RUN_ID.fullmatch(run):
        return ACCEPT_WHY
    if not delegates(trunk_approval()):
        return DELEGATED_OFF_WHY
    try:
        rows = review_rows(read_data(ROOT / REVIEWS / f"{run}.json"), run)
    except OSError:
        rows = None
    if not rows or any(verdicts_missing(r) for r in rows):
        return (f"QA-4: `backfill --accept --delegated {run}` needs {REVIEWS}/{run}.json with judge A's and judge "
                "B's verdicts for every row, and the skeptic's where both said yes")
    return None


def state_after(tool: str, args: dict, rel: str) -> str | None:
    """The text state.toml would have after this tool call (None: the call cannot be read, so it counts as a
    change)."""
    try:
        current = read_data(ROOT / rel).decode("utf-8")
    except OSError:
        current = ""
    if tool == "Write":
        return args.get("content") if isinstance(args.get("content"), str) else None
    edits = [args] if tool == "Edit" else args.get("edits") if tool == "MultiEdit" else None
    if not isinstance(edits, list):
        return None
    text = current
    for e in edits:
        old, new = (e.get("old_string"), e.get("new_string")) if isinstance(e, dict) else (None, None)
        if not isinstance(old, str) or not isinstance(new, str):
            return None
        if old and old in text:
            text = text.replace(old, new) if e.get("replace_all") else text.replace(old, new, 1)
        elif not old:
            text = new + text
        else:  # the tool may match it another way (quotes normalised): the result is unknown
            return None
    return text


def trunk_of(text: str | bytes | None) -> str:
    """The trunk a state.toml text names ([ledger] trunk, else [harbor] trunk, else main), as ledger.py reads it."""
    try:
        data = tomllib.loads(text.decode("utf-8") if isinstance(text, bytes) else text) if text is not None else {}
    except Exception:
        data = {}
    for table in ("ledger", "harbor"):
        t = data.get(table)
        if isinstance(t, dict) and isinstance(t.get("trunk"), str) and t["trunk"].strip():
            return t["trunk"].strip()
    return "main"


TRUNK_WHY = ("QA-4: that edit of .keelokit/state.toml moves the trunk from {old} to {new}, whose committed "
             "[ledger.approval] differs, and who approves the ledger's corrections is the person's call: ask in chat")


def state_problem(tool: str, args: dict, rel: str) -> str | None:
    """Why this edit of state.toml is the person's: it changes [ledger.approval], or moves the trunk to a branch whose
    committed table differs (the approval is read from the trunk's committed file); None for any other edit."""
    try:
        current = read_data(ROOT / rel).decode("utf-8")
    except OSError:
        current = None
    after = state_after(tool, args, rel)
    if after is None or approval_of(after) != approval_of(current):
        return APPROVAL_WHY
    old, new = trunk_of(current), trunk_of(after)
    if old != new and trunk_approval(old) != trunk_approval(new):
        return TRUNK_WHY.format(old=old, new=new)
    return None


def toml_str(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def gitleaks_path_regex(entry: dict) -> str:
    """An anchored regex for the entry's path, or its glob (`*` and `?` stay inside one component)."""
    if "path" in entry:
        return "^" + re.escape(entry["path"]) + "$"
    directory, _, name = entry["glob"].rpartition("/")
    out, i = "", 0
    while i < len(name):
        c = name[i]
        i += 1
        if c == "*":
            out += "[^/]*"
        elif c == "?":
            out += "[^/]"
        else:
            out += re.escape(c)
    return "^" + re.escape(directory) + "/" + out + "$"


def tamper_in(text: str, path: str = "") -> str | None:
    # The harness itself and prose name these patterns; only code and CI config are checked.
    if path.startswith(".keelokit/") or "/.keelokit/" in path or path.endswith(".md"):
        return None
    return next((label for pattern, label in TAMPER if re.search(pattern, text)), None)


REGISTRY_WHY = (f"QA-4: {REGISTRY} lists what SEC-1 and SEC-2 let through and is the human's: ask in chat; "
                "they edit it and commit with `git -c keelokit.allowTamper=true commit`")


# A command word that moves the shell: after it a relative path is not relative to the repo root.
# The blanks after a separator are never newlines, which are separators themselves: `\s*` read every run of newlines
# from each one, quadratic on a long command (ESC-279).
CHDIR = re.compile(r"(?:^|[;&|(){\n])[^\S\n]*(?:cd|pushd|popd)\b")
ENV_WHY = "SEC-2: don't write .env files from the shell; edit .env.example, real values go in the secret store"
ENV_OWN_WHY = "SEC-2: .env files are the human's: don't delete, create or link them from the shell; ask in chat"


def segments(cmd: str) -> list[str]:
    """The command split at `&&`, `||`, `;`, `|` and newlines that are outside quotes."""
    out, cur, quote, i = [], "", "", 0
    while i < len(cmd):
        c = cmd[i]
        if c == "\\" and quote != "'" and i + 1 < len(cmd):
            cur += cmd[i:i + 2]
            i += 2
            continue
        if quote:
            quote = "" if c == quote else quote
        elif c in "'\"":
            quote = c
        elif (c in ";|\n" and not (c == "|" and cur.endswith(">"))) or cmd.startswith("&&", i):  # `>|` (ESC-293)
            out.append(cur)
            cur = ""
            i += 2 if cmd.startswith(("&&", "||"), i) else 1
            continue
        cur += c
        i += 1
    return [*out, cur]


def write_targets(segment: str) -> list[str]:
    """The words of a write command that can name a file, quoted ones included."""
    try:
        words = shlex.split(segment, posix=True)
    except ValueError:
        words = segment.split()
    return [t for w in words if not any(c.isspace() for c in w) for x in w.split(">") if (t := x.strip("(){}"))]


SHELL_TOOLS = ("Bash", "Monitor", "PowerShell")
HARNESS_DIRS = {".keelokit", ".keelokit/bin"}
HARNESS_WHY = ("QA-2: removing or moving .keelokit/ (or its bin/) as a whole turns the guard and the harness off "
               "for this project; that is the person's call")


PWD_FORMS = re.compile(r"^(?:\$PWD|\$\{PWD\}|\$\(pwd\)|`pwd`)(?=/|$)")
HOME_FORMS = re.compile(r"^(?:~|\$HOME|\$\{HOME\})(?=/|$)")


def expand_word(word: str) -> str:
    """The few spellings of a path the guard can expand itself (ESC-286): $PWD, ${PWD}, $(pwd) and `pwd` as the root
    (the hook's shell starts there), ~, $HOME and ${HOME} as the home."""
    word = PWD_FORMS.sub(lambda m: str(ROOT), word)
    return HOME_FORMS.sub(lambda m: os.path.expanduser("~"), word)


def plugin_trees() -> list[str]:
    """Where the plugin's own code lives (ESC-289): the root its hooks run from, and Claude Code's plugin directory."""
    trees = [os.path.join(os.path.expanduser("~"), ".claude", "plugins")]
    if os.environ.get("KEELOKIT_PLUGIN_ROOT"):
        trees.append(os.environ["KEELOKIT_PLUGIN_ROOT"])
    root = os.path.realpath(ROOT)
    # A plugin run from the project itself (`claude --plugin-dir .`, Keelokit's own repo) is the project: its files
    # are the work, not the installed plugin.
    return [tr for tr in map(os.path.realpath, trees)
            if not (root == tr or root.startswith(tr.rstrip("/") + "/") or tr.startswith(root.rstrip("/") + "/"))]


def in_plugin(word: str) -> bool:
    p = expand_word(word)
    if not posixpath.isabs(p):
        p = str(ROOT / p)
    for candidate in {os.path.realpath(p), posixpath.normpath(p)}:
        if any(candidate == tree or candidate.startswith(tree.rstrip("/") + "/") for tree in plugin_trees()):
            return True
    return False


def holds_plugin(word: str) -> bool:
    """The path holds the plugin's code (`rm -rf ~/.claude`): removing or moving it removes the plugin (ESC-294)."""
    p = expand_word(word)
    p = os.path.realpath(p if posixpath.isabs(p) else str(ROOT / p))
    return any(tree.startswith(p.rstrip("/") + "/") for tree in plugin_trees())


PLUGIN_WHY = "QA-2: that is Keelokit's own code (the plugin), which runs the guard: removing or changing it is the person's call"


def harness_rel(word: str) -> str:
    p = posixpath.normpath(expand_word(word))
    if posixpath.isabs(p):
        try:
            return Path(p).resolve().relative_to(ROOT.resolve()).as_posix()
        except (ValueError, OSError):
            return p
    return p


def harness_hit(word: str) -> bool:
    """The word names .keelokit/ or .keelokit/bin/, as itself or as a glob the shell expands to it (ESC-284; a glob
    whose first part starts with a dot, the only kind that matches a dot directory)."""
    rel = harness_rel(word)
    if rel in HARNESS_DIRS or rel.endswith(("/.keelokit", "/.keelokit/bin")):  # any project's, once the shell moved
        return True
    return any(c in word for c in "*?[") and rel.split("/")[0][:1] in (".", "[") and \
        any(fnmatch.fnmatchcase(d, rel) for d in HARNESS_DIRS)


def mv_sources(args: list[str]) -> list[str]:
    """The words mv moves: all but the last, or all of them with -t/--target-directory (ESC-284)."""
    plain, target, i = [], False, 0
    while i < len(args):
        w = args[i]
        if w in ("-t", "--target-directory") or (re.fullmatch(r"-[a-zA-Z]*t", w) is not None):
            target, i = True, i + 2
            continue
        if w.startswith("--target-directory="):
            target = True
        elif not w.startswith("-"):
            plain.append(w)
        i += 1
    return plain if target else plain[:-1]


def chmod_hooked(cmd: str) -> bool:
    """`chmod -x .githooks/pre-commit` while the hooks are on (ESC-291): a hook git can't execute is one it skips."""
    for segment in segments(cmd):
        try:
            words = shlex.split(segment, posix=True)
        except ValueError:
            words = segment.split()
        if words and Path(words[0]).name in ("chmod", "chown", "chgrp", "chattr") and \
                any(hooked(w) for w in words[1:] if not w.startswith("-")):
            return True
    return False


def harness_removal(cmd: str) -> bool:
    """ESC-282, best effort like every shell rule: a command that deletes or moves .keelokit/ or .keelokit/bin/ whole
    (rm, rmdir, git rm, mv as a source, find … -delete/-exec)."""
    for segment in segments(cmd):
        try:
            words = shlex.split(segment, posix=True)
        except ValueError:
            words = segment.split()
        while words and (words[0] in PREFIXES or ("=" in words[0] and not words[0].startswith("-"))):
            words = words[1:]
        if not words:
            continue
        name = Path(words[0]).name
        if name == "git" and any(w in ("switch", "checkout") for w in words) and \
                any(w == "--orphan" or w.startswith("--orphan=") for w in words):
            return True  # an orphan branch empties the tree and HEAD of .keelokit at once (ESC-290)
        if name == "git" and "mv" in words:
            args = mv_sources(words[words.index("mv") + 1:])
        elif name == "git" and "rm" in words:
            args = words[words.index("rm") + 1:]
        elif name in ("rm", "rmdir", "unlink", "shred", "trash"):
            args = words[1:]
        elif name == "mv":
            args = mv_sources(words[1:])
        elif name == "find" and any(w in ("-delete", "-exec", "-execdir", "-ok") for w in words):
            args = words[1:]
        else:
            continue
        if any(harness_hit(w) or in_plugin(w) or holds_plugin(w) for w in args if not w.startswith("-")):
            return True
    return False


def dequoted(cmd: str) -> str:
    """The command as the shell reads its words: quotes joined and backslashes removed, so `'--no-verify'` and
    `--no-ver""ify` read as the flag they are (ESC-283); a word that holds a blank (a message, a script) is kept only as
    '', so a quoted message that mentions a flag is still not one."""
    out = []
    for segment in segments(cmd):
        try:
            words = shlex.split(segment, posix=True)
        except ValueError:
            words = segment.split()
        out.append(" ".join("''" if not w or any(c.isspace() for c in w) else w for w in words))
    return " ; ".join(out)


ALIAS_BYPASS = re.compile(r"(?:^|\s)(?:--no-veri(?:fy?)?|-[a-zA-Z]*n[a-zA-Z]*)(?=\s|$)|hookspath", re.I)


def alias_bypass(cmd: str) -> bool:
    """`git -c alias.c='commit --no-verify' c`: an alias defined on the command line whose value skips the hooks."""
    for segment in segments(cmd):
        try:
            words = shlex.split(segment, posix=True)
        except ValueError:
            continue
        for w in words:
            if w.lower().startswith("alias.") and "=" in w and ALIAS_BYPASS.search(w.split("=", 1)[1]):
                return True
    return False


def shell_scripts(words: list[str]) -> list[str]:
    """The scripts a command line hands to a shell (`bash -c "…"`, `script -c "…"`) or to eval."""
    shell = next((i for i, w in enumerate(words) if Path(w).name in SHELLS | {"script", "su"}), None)
    scripts = [words[i + 1] for i in range(len(words) - 1)
               if shell is not None and i > shell and re.fullmatch(r"-[a-z]*c[a-z]*", words[i])]
    if words[:1] == ["eval"]:
        scripts.append(" ".join(words[1:]))
    return scripts


CONFIG_ENV = re.compile(r"(?i)^GIT_CONFIG_(?:KEY_\d+|PARAMETERS)=.*(?:core\.hookspath|include\.|includeif\.)")


def config_problem(cmd: str) -> str | None:
    """ESC-287: what a git config change says, wherever it is made (`-c k=v`, `git config k v`, GIT_CONFIG_* in the
    environment): the hooks path, an include (a file that can set it), an alias that skips the hooks, a `+` push
    refspec (a force-push)."""
    for segment in segments(cmd):
        try:
            words = shlex.split(segment, posix=True)
        except ValueError:
            words = segment.split()
        pairs = []
        for i, w in enumerate(words):
            if CONFIG_ENV.match(w) or (w.lower().startswith("git_config_") and "hookspath" in w.lower()):
                return "QA-2: don't override the hooks path (through git's config environment either)"
            if w == "-c" and i + 1 < len(words):
                pairs.append(words[i + 1].partition("=")[::2])
        if "config" in words and any(Path(w).name == "git" for w in words[:words.index("config")]):
            rest = [w for w in words[words.index("config") + 1:] if not w.startswith("-")]
            if rest:
                pairs.append((rest[0], rest[1] if len(rest) > 1 else ""))
        if "config" in words and any(w in ("--remove-section", "--rename-section") for w in words):
            section = next((w for w in words[words.index("config") + 1:] if not w.startswith("-")), "")
            if section.lower() == "core":
                return "QA-2: the hooks path is the person's to set (removing [core] removes it)"
        for key, value in pairs:
            k = key.lower()
            if k == "core.hookspath":
                return "QA-2: the hooks path is the person's to set"
            if k.startswith(("include.", "includeif.")):
                return "QA-2: a config include can change the hooks path; ask the person"
            if k.startswith("alias.") and ALIAS_BYPASS.search(value):
                return "QA-2: never bypass git hooks (an alias that skips them is the same bypass)"
            if re.fullmatch(r"remote\..+\.push", k) and value.strip().startswith("+"):
                return "QA-2: no force-push (a `+` refspec is one)"
    return None


HOOKED_FILES = {".keelokit/bin/guard.py", ".keelokit/bin/ledger.py"}  # what the template's .githooks run
HOOKS_ON_WHY = ("QA-2: the person turned the git hooks on (core.hooksPath .githooks): changing or removing the hooks, "
                "or the guard and ledger they run, is theirs to do")
_hooks_on: list[bool] = []


def hooks_on() -> bool:
    """The person set core.hooksPath to the project's .githooks (read once per call)."""
    if not _hooks_on:  # the person's files, not the /dev/null this copy runs git with (harden_git)
        out = git_bytes("config", "--local", "--get", "core.hooksPath") or \
            git_bytes("config", "--global", "--get", "core.hooksPath") or b""
        value = out.decode("utf-8", "replace").strip()
        _hooks_on.append(bool(value) and harness_rel(value if posixpath.isabs(value) else value) in (".githooks",))
    return _hooks_on[0]


def hooked(target: str) -> bool:
    """ESC-291: a hook in .githooks, or a script the hooks run, while the person has the hooks on."""
    rel = harness_rel(target.lstrip(">"))
    return (rel == ".githooks" or rel.startswith(".githooks/") or rel in HOOKED_FILES) and hooks_on()


SETTINGS_FILE = re.compile(r"(?:^|/)\.claude/settings(?:\.local)?\.json$")
SETTINGS_WHY = ("QA-2: Claude Code's settings decide whether Keelokit's hooks and plugin run; turning them off is the "
                "person's call")


def claude_settings(target: str) -> bool:
    return bool(SETTINGS_FILE.search(posixpath.normpath(expand_word(target.lstrip(">")))))


def turns_hooks_off(text: str) -> bool:
    return "disableAllHooks" in text or ("enabledPlugins" in text and "keelokit" in text.lower())


def plugin_command(cmd: str) -> bool:
    """`claude plugin disable|uninstall|remove keelokit` (ESC-294)."""
    for segment in segments(cmd):
        words = segment.split()
        if Path(words[0]).name == "claude" if words else False:
            if any(w in ("plugin", "plugins") for w in words) and \
                    any(w in ("disable", "uninstall", "remove", "rm") for w in words) and \
                    any("keelokit" in w.lower() for w in words):
                return True
    return False


GIT_INTERNALS_WHY = "QA-2: .git/config and .git/hooks decide which git hooks run; changing them is the person's call"


def git_internal(target: str) -> bool:
    rel = harness_rel(target.lstrip(">"))
    return rel in (".git/config", ".git/config.worktree", ".git/hooks") or rel.startswith(".git/hooks/") or \
        re.fullmatch(r"\.git/worktrees/[^/]+/config(?:\.worktree)?", rel) is not None


def seeds_env(segment: str) -> bool:
    """`cp <repo>/.env….example <dest>`: setting up a local .env from the repo's own example (ESC-288: only a
    repo-relative `.env*.example`, never an example from elsewhere)."""
    m = re.match(r"\s*cp\s+(?:-\w+\s+)*(\S+\.example)\s+\S+\s*$", segment)
    if not m:
        return False
    src = m.group(1)
    name = posixpath.basename(src)
    return not posixpath.isabs(src) and ".." not in src.split("/") and name.startswith(".env") and \
        not src.startswith(("~", "$"))


def bash_problem(cmd: str, allow: list[dict] | None = None, depth: int = 0) -> str | None:
    cmd = re.sub(r"\\\r?\n", " ", cmd)  # a line continuation is a blank to the shell (ESC-293)
    allow = committed_registry() if allow is None else allow
    bare = unquoted(cmd)
    if CHDIR.search(bare):
        allow = []  # no registered path is let through once the shell may be elsewhere
    for pattern in (rf"(?i){GIT}(?:-c\s+|--config-env[=\s]\s*)['\"]?keelokit\.allowtamper",
                    rf"(?i){GIT}config\b{GIT_ARGS}['\"]?keelokit\.allowtamper"):
        if re.search(pattern, cmd):  # quoted spellings, which `bare` has emptied
            return "QA-4: only a human may allow a skipped test or silenced check"
    words_read = dequoted(cmd)
    for pattern, why in GIT_NO_HOOKS:
        if re.search(pattern, bare) or re.search(pattern, words_read):
            return why
    if alias_bypass(cmd):
        return "QA-2: never bypass git hooks (an alias that skips them is the same bypass)"
    if why := config_problem(cmd):
        return why
    if depth < 3:  # ESC-287: the script a shell or eval runs is checked as a command of its own
        for segment in segments(cmd):
            try:
                inner = shell_scripts(shlex.split(segment, posix=True))
            except ValueError:
                inner = []
            for script in inner:
                if why := bash_problem(script, allow, depth + 1):
                    return why
    if harness_removal(cmd):
        return HARNESS_WHY
    if plugin_command(cmd):
        return PLUGIN_WHY
    if chmod_hooked(cmd):
        return HOOKS_ON_WHY
    if why := accept_problem(cmd):
        return why
    if corrections_write(cmd):
        return CORRECTIONS_WHY
    if named_write(cmd, Path(STATE).name):
        return STATE_SHELL_WHY
    for segment in re.split(r"&&|\|\||;|(?<!>)\|", bare):
        words = segment.split()
        if not words:
            continue
        deploy = re.search(r"\b(fly|flyctl)\s+deploy\b", segment)
        if deploy and not re.search(r"(--config|-c)[=\s]+\S*staging\S*", segment):
            return "AGENT-1/REL-1: only staging deploys (--config …staging…); production goes out from a vX.Y.Z tag through CI, and is the human's call"
        if re.search(r"\b(eas|eas-cli)\s+submit\b", segment):
            return "AGENT-1: store submissions are the human's call — ask in chat"
        # Copying the repo's own example to create a local .env is setup, not a secret.
        if seeds_env(segment):
            continue
        if WRITE_CMD.search(segment):
            try:
                targets = shlex.split(segment, posix=True)
            except ValueError:
                targets = words
            if why := next((w for t in targets if (w := protected_why(t.lstrip(">")))), None):
                return why
            if any(is_env_file(t.lstrip(">")) and not allowed(allow, "SEC-2", t.lstrip(">")) for t in targets):
                if re.match(r"\s*(rm|touch|ln)\b", segment) and not re.search(r">", segment):  # LOG-3
                    return "SEC-2: .env files are the human's: don't delete, create or link them from the shell; ask in chat"
                return "SEC-2: don't write .env files from the shell; edit .env.example, real values go in the secret store"
            if any(applied_migration(t) for t in targets if "prisma/migrations/" in t):
                return "DB-1: that migration is already on origin/main; create a new one"
    # The same targets, read from the command as typed: a quoted one is a target too.
    for segment in segments(cmd):
        if not WRITE_CMD.search(unquoted(segment)) or seeds_env(segment):
            continue
        targets = write_targets(segment)
        if why := next((w for t in targets if (w := protected_why(t))), None):
            return why
        if any(is_env_file(t) and not allowed(allow, "SEC-2", t) for t in targets):
            return ENV_OWN_WHY if re.match(r"\s*(rm|touch|ln)\b", segment) and ">" not in segment else ENV_WHY
    if secret_in(cmd):
        return f"SEC-1: the command contains a {secret_in(cmd)}"
    return None


def edit_payload(tool: str, args: dict) -> tuple[str, list[str]]:
    """(path, each piece of new text) for every file-editing tool; a MultiEdit's edits one by one."""
    path = args.get("file_path") or args.get("notebook_path") or ""
    parts = [args.get("content"), args.get("new_string"), args.get("new_source")]
    parts += [e.get("new_string") for e in args.get("edits", []) if isinstance(e, dict)]
    return path, [p for p in parts if isinstance(p, str) and p]


def real_rel(path: str) -> str | None:
    """The repo-relative POSIX path a tool really writes: symlinks resolved, a relative path taken from the root,
    and a hard link to a protected file read as that file (the same inode)."""
    try:
        real = ((ROOT / path) if not Path(path).is_absolute() else Path(path)).resolve()
        if real.is_file():
            for protected in (STATE, CORRECTIONS, REGISTRY):
                target = ROOT / protected
                if target.is_file() and os.path.samefile(real, target):
                    return protected
        norm = real.relative_to(ROOT.resolve()).as_posix()
    except (OSError, ValueError, RuntimeError):
        return None
    return norm


def tool_problem(tool: str, args: dict) -> str | None:
    allow = committed_registry()
    if tool in SHELL_TOOLS:  # ESC-285: every tool that runs a shell command, not only Bash
        return bash_problem(args.get("command", ""), allow)
    path, parts = edit_payload(tool, args)
    if path and (git_internal(path) or (real_rel(path) or "").startswith((".git/hooks/",)) or real_rel(path) == ".git/config"):
        return GIT_INTERNALS_WHY
    if path and in_plugin(path):
        return PLUGIN_WHY
    if path and claude_settings(path) and any(turns_hooks_off(x) for x in parts):
        return SETTINGS_WHY
    if path and hooked(path):
        return HOOKS_ON_WHY
    names = {n for n in (rel_posix(path), real_rel(path)) if n} if path else set()
    if REGISTRY in names:
        return REGISTRY_WHY
    if CORRECTIONS in {n.lower() for n in names}:
        return CORRECTIONS_WHY
    if STATE in {n.lower() for n in names} and (why := state_problem(tool, args, STATE)):
        return why
    if path and is_env_file(path) and not allowed(allow, "SEC-2", path):
        return "SEC-2: real values go in the secret store; edit .env.example instead"
    if path and applied_migration(path):
        return "DB-1: this migration is already on origin/main; create a new one"
    # Each piece on its own, and the pieces run together: a key split over two edits is whole in the file.
    for text in [] if allowed(allow, "SEC-1", path) else [*parts, "".join(parts)]:
        if label := secret_in(text):
            return f"SEC-1: looks like a {label}; reference it from the secret store"
    for text in parts:
        if label := tamper_in(text, path):
            return f"QA-4: {label} needs the human's yes — ask in chat, don't silence the check"
    return None


def claude() -> int:
    # A crash would exit 1, which Claude Code doesn't block on: every failure blocks instead.
    try:
        event = json.load(sys.stdin)
        if not isinstance(event, dict):
            raise ValueError(f"expected a JSON object, got {type(event).__name__}")
        args = event.get("tool_input") or {}
        if not isinstance(args, dict):
            raise ValueError(f"tool_input is a {type(args).__name__}, not an object")
    except Exception as e:  # bad JSON or bytes, nesting past the recursion limit, no stdin at all
        print(f"Keelokit guard: couldn't read the hook input ({type(e).__name__}: {e}), so the call is blocked",
              file=sys.stderr)
        return 2
    try:
        why = tool_problem(event.get("tool_name", ""), args)
    except Exception as e:
        print(f"Keelokit guard: couldn't check this call ({type(e).__name__}: {e}), so it is blocked", file=sys.stderr)
        return 2
    if why:
        print(f"Blocked by Keelokit — {why}", file=sys.stderr)
        return 2
    return 0


def gitleaks(allow: list[dict]) -> int:
    """gitleaks on the staged changes; with active SEC-1 entries, with a config that extends the project's
    own (or the defaults) and allows those paths."""
    cmd = ["gitleaks", "git", "--pre-commit", "--staged", "--redact", "--no-banner"]
    entries = [e for e in allow if e["rule"] == "SEC-1"]
    if not entries:
        return subprocess.run(cmd, cwd=ROOT).returncode
    own = ROOT / ".gitleaks.toml"
    extend = f"path = {toml_str(str(own))}" if own.is_file() else "useDefault = true"
    paths = [gitleaks_path_regex(e) for e in entries]
    config = f"[extend]\n{extend}\n\n[allowlist]\npaths = [{', '.join(toml_str(p) for p in paths)}]\n"
    fd, name = tempfile.mkstemp(suffix=".toml")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(config)
        return subprocess.run([*cmd, "--config", name], cwd=ROOT).returncode
    finally:
        os.unlink(name)


def staged_rows(path: str) -> bool:
    """True unless the staged file is TOML with no [[row]] (an unreadable one counts as having rows)."""
    blob = subprocess.run(["git", "show", f":{path}"], cwd=ROOT, capture_output=True).stdout
    try:
        return bool(tomllib.loads(blob.decode("utf-8")).get("row"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError):
        return True


def delegated_append() -> bool:
    """True when the staged corrections file is a delegated review's append: HEAD's state.toml delegates (and the
    staged table is the same), the staged file is HEAD's plus rows, and every new row has approver
    `delegated:<run>` with the staged review file of that run showing it approved."""
    head_table = approval_of(git_bytes("show", f"HEAD:{STATE}"))
    if not delegates(head_table) or approval_of(git_bytes("show", f":{STATE}")) != head_table:
        return False
    head, staged = git_bytes("show", f"HEAD:{CORRECTIONS}") or b"", git_bytes("show", f":{CORRECTIONS}")
    if staged is None or not staged.startswith(head):
        return False
    try:
        old = tomllib.loads(head.decode("utf-8")).get("row", []) if head else []
        rows = tomllib.loads(staged.decode("utf-8")).get("row", [])
    except Exception:
        return False
    if not isinstance(old, list) or not isinstance(rows, list) or rows[:len(old)] != old or len(rows) <= len(old):
        return False
    for row in rows[len(old):]:
        approver = row.get("approver") if isinstance(row, dict) else None
        if not isinstance(approver, str) or not approver.strip().lower().startswith("delegated:"):
            return False
        run = approver.strip()[len("delegated:"):].strip()
        if not RUN_ID.fullmatch(run) or row.get("kind") not in ("backfill", "late"):
            return False
        review = review_data(git_bytes("show", f":{REVIEWS}/{run}.json"), run)
        if not review or review.get("mode") != head_table.get("mode") or not approved_in(row, review["rows"]) \
                or not any(redecided(r, review) for r in review["rows"] if isinstance(r, dict) and
                           (r.get("story"), r.get("commit"), r.get("kind")) ==
                           (row.get("story"), row.get("commit"), row.get("kind"))):
            return False
    return True


def redecided(r: dict, review: dict) -> bool:
    """The recorded facts of a review row (critical, confidence, the verdict models) and the recorded mode and
    human_for still give `approved`, as ledger.py decides."""
    reasons = review.get("human_for")
    reasons = [h for h in ("critical", "disagreement", "low-confidence") if h in reasons] \
        if isinstance(reasons, list) else ["critical", "disagreement", "low-confidence"]
    if review.get("mode") == "mixed" and ((r.get("critical") is not False and "critical" in reasons)
                                         or (r.get("confidence") == "low" and "low-confidence" in reasons)):
        return False
    if review.get("mode") == "delegated" and r.get("critical") is not False and not all(
            isinstance(r.get(k), dict) and "opus" in str(r[k].get("model", "")).lower()
            for k in ("judge_a", "judge_b", "skeptic")):
        return False
    return review.get("mode") in ("delegated", "mixed")


def git_pre_commit() -> int:
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-status", "--no-renames"], cwd=ROOT, capture_output=True, text=True
    ).stdout.splitlines()
    problems = []
    allow = staged_registry()
    allow_tamper = subprocess.run(
        ["git", "config", "--bool", "keelokit.allowTamper"], cwd=ROOT, capture_output=True, text=True
    ).stdout.strip() == "true"
    for line in staged:
        status, _, path = line.partition("\t")
        # A first commit adding the registry with no active entry (the template's, comments only) lets nothing through.
        if path == REGISTRY and not allow_tamper and not (status == "A" and not allow):
            problems.append(f"QA-4: {path} is changed. If a human decided this, commit with "
                            "`git -c keelokit.allowTamper=true commit …` and say why in the message.")
        # The template's corrections file (comments only, no [[row]]) may be added; any other change is the human's.
        if path == CORRECTIONS and not allow_tamper and not (status == "A" and not staged_rows(path)) \
                and not delegated_append():
            problems.append(f"QA-4: {path} (the ledger's approved corrections) is changed. If a person accepted "
                            "these rows, they commit with `git -c keelokit.allowTamper=true commit …`.")
        if path == STATE and not allow_tamper and \
                approval_of(None if status == "D" else git_bytes("show", f":{STATE}")) != \
                approval_of(git_bytes("show", f"HEAD:{STATE}")):
            problems.append(f"QA-4: the [ledger.approval] table of {STATE} is changed: who approves the ledger's "
                            "corrections is the person's call. If they decided it, they commit with "
                            "`git -c keelokit.allowTamper=true commit …`.")
        if is_env_file(path) and status != "D" and not allowed(allow, "SEC-2", path):
            problems.append(f"SEC-2: {path} must not be committed")
        if status in ("M", "D") and applied_migration(path):
            problems.append(f"DB-1: {path} is already on origin/main; add a new migration instead")
    diff = subprocess.run(["git", "diff", "--cached", "-U0"], cwd=ROOT, capture_output=True, text=True).stdout
    added: dict[str, list[str]] = {}
    current = ""
    for line in diff.splitlines():
        if line.startswith("+++ "):
            current = line[6:] if line.startswith("+++ b/") else ""
        elif line.startswith("+"):
            added.setdefault(current, []).append(line[1:])
    # Secrets: the whole staged file, not only its added lines, so one split over two edits or two
    # commits is still whole here.
    for line in staged:
        status, _, path = line.partition("\t")
        if status == "D" or allowed(allow, "SEC-1", path):
            continue
        blob = subprocess.run(["git", "show", f":{path}"], cwd=ROOT, capture_output=True).stdout
        if label := secret_in(blob.decode("utf-8", "replace")):
            problems.append(f"SEC-1: {path} contains a {label}")
    tampered = [(f, lbl) for f, lines in added.items() if (lbl := tamper_in("\n".join(lines), f))]
    if tampered and not allow_tamper:
        problems.append(
            f"QA-4: {tampered[0][0]} adds {tampered[0][1]}. If a human decided this, commit with "
            "`git -c keelokit.allowTamper=true commit …` and say why in the message."
        )
    if shutil.which("gitleaks"):
        if gitleaks(allow):
            problems.append("SEC-1: gitleaks found a secret in the staged changes")
    for p in problems:
        print(f"✖ {p}", file=sys.stderr)
    return 1 if problems else 0


def main(argv: list[str]) -> int:
    mode = argv[0] if argv else ""
    if mode == "--claude" and PLUGIN_MODE and (why := git_dir_problem()):  # ESC-280
        print(f"Keelokit guard: {why}; the call is blocked", file=sys.stderr)
        return 2
    if mode == "--claude":
        return claude()
    if mode == "git-pre-commit":
        return git_pre_commit()
    print(f"Keelokit guard: unknown mode {mode or '(none)'} (use --claude or git-pre-commit)", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
