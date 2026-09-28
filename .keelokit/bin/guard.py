#!/usr/bin/env python3
"""One guard for two callers, so humans and agents hit the same wall.

    python3 .keelokit/bin/guard.py --claude          Claude Code PreToolUse hook (JSON on stdin)
    python3 .keelokit/bin/guard.py git-pre-commit    git pre-commit hook

Exit 2 blocks (Claude shows stderr to the agent); exit 1 blocks a git commit.
Rules enforced: SEC-1, SEC-2, QA-2, QA-4, DB-1, AGENT-1 (.keelokit/harness/rules.toml).

It is a speed bump for agents, not a sandbox: a determined shell (variables, eval, scripts)
can get around pattern checks. CI and the git hooks are the backstop.
"""
import sys

if sys.version_info < (3, 11):
    print(f"Keelokit guard needs Python 3.11+ (found {sys.version.split()[0]}); it is off.", file=sys.stderr)
    sys.exit(1)  # non-blocking: Claude shows the message, the tool call proceeds

import json  # noqa: E402
import re  # noqa: E402
import shlex  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
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
    (r"https?://[^/\s:@]+:[^/\s@]+@github\.com", "credentials in a git URL"),
    # A DB URL with a password, unless it points at this machine (local/dev/CI values).
    (r"\b(postgres(ql)?|mysql|mongodb(\+srv)?|redis)://[^/\s:@]+:[^/\s@]+@(?!(localhost|127\.0\.0\.1|postgres|db)[:/])",
     "database URL with a password"),
]
TAMPER = [
    (r"\b(it|test|describe)\.(skip|only|todo)\s*\(", "a skipped or focused test"),
    (r"(?<![\w.])x(it|test|describe)\s*\(", "a disabled test"),
    (r"eslint-disable", "an eslint-disable comment"),
    (r"@ts-(ignore|nocheck)", "a @ts-ignore / @ts-nocheck"),
    (r"continue-on-error:\s*true", "continue-on-error in CI"),
]
GIT_NO_HOOKS = [
    (r"\bgit\b.*\s--no-verify\b", "QA-2: never bypass git hooks"),
    (r"\bgit\b(\s+-[^c]\S*)*\s+commit\b[^|;&]*\s-[a-zA-Z]*n[a-zA-Z]*\b", "QA-2: `commit -n` skips the git hooks"),
    (r"keelokit\.allowTamper", "QA-4: only a human may allow a skipped test or silenced check"),
    (r"\bgit\s+(-c\s+\S+\s+)*-c\s+core\.hooksPath", "QA-2: don't override the hooks path"),
    (r"\bgit\s+config\b.*\bcore\.hooksPath\b", "QA-2: the hooks path is set by `pnpm install`"),
    (r"\bgit\s+push\b.*\s(-f\b|--force\b(?!-with-lease)|--force-if-includes\b)", "QA-2: no force-push (use --force-with-lease on your own branch)"),
    (r"\bgit\s+push\b.*\s\+[\w./:-]+", "QA-2: `+ref` is a force-push"),
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
    return next((label for pattern, label in SECRETS if re.search(pattern, text)), None)


def tamper_in(text: str, path: str = "") -> str | None:
    # The harness itself and prose name these patterns; only code and CI config are checked.
    if path.startswith(".keelokit/") or "/.keelokit/" in path or path.endswith(".md"):
        return None
    return next((label for pattern, label in TAMPER if re.search(pattern, text)), None)


def bash_problem(cmd: str) -> str | None:
    bare = unquoted(cmd)
    for pattern, why in GIT_NO_HOOKS:
        if re.search(pattern, bare):
            return why
    for segment in re.split(r"&&|\|\||;|\|", bare):
        words = segment.split()
        if not words:
            continue
        deploy = re.search(r"\b(fly|flyctl)\s+deploy\b", segment)
        if deploy and not re.search(r"(--config|-c)[=\s]+\S*staging\S*", segment):
            return "AGENT-1: only staging deploys (--config …staging…); production is the human's call"
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
            if any(is_env_file(t.lstrip(">")) for t in targets):
                return "SEC-2: don't write .env files from the shell; edit .env.example, real values go in the secret store"
            if any(applied_migration(t) for t in targets if "prisma/migrations/" in t):
                return "DB-1: that migration is already on origin/main; create a new one"
    if secret_in(cmd):
        return f"SEC-1: the command contains a {secret_in(cmd)}"
    return None


def edit_payload(tool: str, args: dict) -> tuple[str, str]:
    """(path, new text) for every file-editing tool."""
    path = args.get("file_path") or args.get("notebook_path") or ""
    parts = [args.get("content"), args.get("new_string"), args.get("new_source")]
    parts += [e.get("new_string") for e in args.get("edits", []) if isinstance(e, dict)]
    return path, "\n".join(p for p in parts if p)


def claude() -> int:
    event = json.load(sys.stdin)
    tool, args = event.get("tool_name", ""), event.get("tool_input", {}) or {}
    if tool == "Bash":
        why = bash_problem(args.get("command", ""))
    else:
        path, text = edit_payload(tool, args)
        why = None
        if path and is_env_file(path):
            why = "SEC-2: real values go in the secret store; edit .env.example instead"
        elif path and applied_migration(path):
            why = "DB-1: this migration is already on origin/main; create a new one"
        elif secret_in(text):
            why = f"SEC-1: looks like a {secret_in(text)}; reference it from the secret store"
        elif label := tamper_in(text, path):
            why = f"QA-4: {label} needs the human's yes — ask in chat, don't silence the check"
    if why:
        print(f"Blocked by Keelokit — {why}", file=sys.stderr)
        return 2
    return 0


def git_pre_commit() -> int:
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-status", "--no-renames"], cwd=ROOT, capture_output=True, text=True
    ).stdout.splitlines()
    problems = []
    for line in staged:
        status, _, path = line.partition("\t")
        if is_env_file(path) and status != "D":
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
    all_added = "\n".join(l for lines in added.values() for l in lines)
    if label := secret_in(all_added):
        problems.append(f"SEC-1: staged change contains a {label}")
    tampered = [(f, lbl) for f, lines in added.items() if (lbl := tamper_in("\n".join(lines), f))]
    if tampered and not subprocess.run(
        ["git", "config", "--bool", "keelokit.allowTamper"], cwd=ROOT, capture_output=True, text=True
    ).stdout.strip() == "true":
        problems.append(
            f"QA-4: {tampered[0][0]} adds {tampered[0][1]}. If a human decided this, commit with "
            "`git -c keelokit.allowTamper=true commit …` and say why in the message."
        )
    if shutil.which("gitleaks"):
        if subprocess.run(["gitleaks", "git", "--pre-commit", "--staged", "--redact", "--no-banner"], cwd=ROOT).returncode:
            problems.append("SEC-1: gitleaks found a secret in the staged changes")
    for p in problems:
        print(f"✖ {p}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    sys.exit(claude() if mode == "--claude" else git_pre_commit() if mode == "git-pre-commit" else 0)
