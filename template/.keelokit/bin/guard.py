#!/usr/bin/env python3
"""One guard for two callers, so humans and agents hit the same wall.

    python3 .keelokit/bin/guard.py --claude          Claude Code PreToolUse hook (JSON on stdin)
    python3 .keelokit/bin/guard.py git-pre-commit    git pre-commit hook

Exit 2 blocks (Claude shows stderr to the agent); exit 1 blocks a git commit. Claude Code lets a
call through on any exit but 2, so for Claude the guard ends in exactly 0 or 2: an unknown mode,
hook input it can't read or a check that fails all block, with the reason on stderr.
Rules enforced: SEC-1, SEC-2, QA-2, QA-4, DB-1, AGENT-1, REL-1 (.keelokit/harness/rules.toml).

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
import tempfile  # noqa: E402
import tomllib  # noqa: E402
from pathlib import Path  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
ENV_OK = {".env.example", ".env.ci"}
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
# The three alternatives of a password's tokens start differently (`${{`, a `$` not followed by `{{`, a
# character that is no `$`), so a failing match can't backtrack through two ways of reading one text.
URL_PASSWORD = r"(?P<pw>(?:\$\{\{[^}\n]*\}\}|\$(?!\{\{)|[^/\s@$])+)"
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
GIT = rf"\bgit(?:\s+(?:(?:-[Cc]|--(?:git-dir|work-tree|namespace|config-env|attr-source))\s+|-){GIT_VALUE})*?\s+"
# The rest of that git command: up to a shell separator, or `--`, after which come paths.
GIT_ARGS = r"(?:(?!\s--(?![^\s;&|]))[^|;&\n])*"
# A short-option bundle ends at the token's end (-nm"msg" is emptied to -nm'').
BUNDLE_END = r"(?![^\s;&|<>()])"
GIT_NO_HOOKS = [
    # git takes any unambiguous prefix of a long option: --no-veri(f) is --no-verify.
    (r"\bgit\b.*\s--no-veri(fy?)?(?![\w-])", "QA-2: never bypass git hooks"),
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
WRITE_CMD = re.compile(r"(>>?|\btee\b|\bcp\b|\bmv\b|\bsed\s+-i|\bperl\s+-[a-z]*i|\btruncate\b|\brm\b|\btouch\b|\bln\b|\bdd\b)")


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
    return subprocess.run(
        ["git", "cat-file", "-e", f"origin/main:{rel.as_posix()}"], cwd=ROOT, capture_output=True
    ).returncode == 0


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
    out = subprocess.run(["git", "show", f"HEAD:{REGISTRY}"], cwd=ROOT, capture_output=True)
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
CHDIR = re.compile(r"(?:^|[;&|(){\n])\s*(?:cd|pushd|popd)\b")
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
        elif c in ";|\n" or cmd.startswith("&&", i):
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


def bash_problem(cmd: str, allow: list[dict] | None = None) -> str | None:
    allow = committed_registry() if allow is None else allow
    bare = unquoted(cmd)
    if CHDIR.search(bare):
        allow = []  # no registered path is let through once the shell may be elsewhere
    for pattern in (rf"(?i){GIT}(?:-c\s+|--config-env[=\s]\s*)['\"]?keelokit\.allowtamper",
                    rf"(?i){GIT}config\b{GIT_ARGS}['\"]?keelokit\.allowtamper"):
        if re.search(pattern, cmd):  # quoted spellings, which `bare` has emptied
            return "QA-4: only a human may allow a skipped test or silenced check"
    for pattern, why in GIT_NO_HOOKS:
        if re.search(pattern, bare):
            return why
    for segment in re.split(r"&&|\|\||;|\|", bare):
        words = segment.split()
        if not words:
            continue
        deploy = re.search(r"\b(fly|flyctl)\s+deploy\b", segment)
        if deploy and not re.search(r"(--config|-c)[=\s]+\S*staging\S*", segment):
            return "AGENT-1/REL-1: only staging deploys (--config …staging…); production goes out from a vX.Y.Z tag through CI, and is the human's call"
        if re.search(r"\b(eas|eas-cli)\s+submit\b", segment):
            return "AGENT-1: store submissions are the human's call — ask in chat"
        # Copying the example to create a local .env is setup, not a secret.
        if re.match(r"\s*cp\s+(-\w+\s+)*\S+\.example\s+\S+\s*$", segment):
            continue
        if WRITE_CMD.search(segment):
            try:
                targets = shlex.split(segment, posix=True)
            except ValueError:
                targets = words
            if any(is_registry(t.lstrip(">")) or Path(t.lstrip(">")).name == Path(REGISTRY).name for t in targets):
                return REGISTRY_WHY
            if any(is_env_file(t.lstrip(">")) and not allowed(allow, "SEC-2", t.lstrip(">")) for t in targets):
                if re.match(r"\s*(rm|touch|ln)\b", segment) and not re.search(r">", segment):  # LOG-3
                    return "SEC-2: .env files are the human's: don't delete, create or link them from the shell; ask in chat"
                return "SEC-2: don't write .env files from the shell; edit .env.example, real values go in the secret store"
            if any(applied_migration(t) for t in targets if "prisma/migrations/" in t):
                return "DB-1: that migration is already on origin/main; create a new one"
    # The same targets, read from the command as typed: a quoted one is a target too.
    for segment in segments(cmd):
        if not WRITE_CMD.search(unquoted(segment)) or re.match(r"\s*cp\s+(-\w+\s+)*\S+\.example\s+\S+\s*$", segment):
            continue
        targets = write_targets(segment)
        if any(is_registry(t) or Path(t).name == Path(REGISTRY).name for t in targets):
            return REGISTRY_WHY
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


def tool_problem(tool: str, args: dict) -> str | None:
    allow = committed_registry()
    if tool == "Bash":
        return bash_problem(args.get("command", ""), allow)
    path, parts = edit_payload(tool, args)
    if is_registry(path):
        return REGISTRY_WHY
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
    if mode == "--claude":
        return claude()
    if mode == "git-pre-commit":
        return git_pre_commit()
    print(f"Keelokit guard: unknown mode {mode or '(none)'} (use --claude or git-pre-commit)", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
