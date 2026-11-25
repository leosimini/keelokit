#!/usr/bin/env python3
"""Keelokit ledger. Stdlib only (Python 3.11+ for tomllib).

    python3 .keelokit/bin/ledger.py                    summary of every story's state, at most 10 lines
    python3 .keelokit/bin/ledger.py --json             the same facts, schema 1 (docs/ledger.md)
                                                       (exit 0 no difference, 1 differences, 2 no git or no trunk)
    python3 .keelokit/bin/ledger.py history            report: is the trunk's history complete?
                                                       (exit 0 complete, 1 incomplete, 2 not a git repo)
    python3 .keelokit/bin/ledger.py history --ensure   complete it (SessionStart hook); always exit 0
    python3 .keelokit/bin/ledger.py show <ID> [--full] a story's card: its state and the why (at most 60 lines)
    python3 .keelokit/bin/ledger.py show <ID> --json   the same record and why, schema 1 (exit 1 no such story)
    python3 .keelokit/bin/ledger.py next               the ready stories nobody works on, by wave and id
    python3 .keelokit/bin/ledger.py --release vX.Y.Z   the stories that entered that version
    python3 .keelokit/bin/ledger.py risky <ID>         is the story risky (.keelokit/risky.toml), why, and the
                                                       breaker round cap (HARN-021); exit 0, 2 no such story
    python3 .keelokit/bin/ledger.py take <ID>          this worktree works on <ID> (git config --worktree
                                                       keelokit.story); exit 1 if it is no story or on the trunk
                                                       with Harbor: harbor.py story take <ID> first (a refusal
                                                       is one line and exit 1, nothing is set)
    python3 .keelokit/bin/ledger.py take --clear       this worktree works on no story (with Harbor: story release)
    python3 .keelokit/bin/ledger.py drop <ID> --motivo "..."
                                                       record an abandoned attempt: an empty commit with
                                                       `Dropped: <ID>`, pushed to archive/<id>-<YYYYMMDD>
    python3 .keelokit/bin/ledger.py hook prepare <file> [<source> [<sha>]]
                                                       prepare-commit-msg: Part-of: <keelokit.story>; exit 0
    python3 .keelokit/bin/ledger.py hook msg <file>    commit-msg: the trailer grammar (docs/ledger.md,
                                                       "Trailers"); exit 1 refuses under enforce = "block"
    python3 .keelokit/bin/ledger.py prepush <remote> [<url>]
                                                       pre-push: git's lines on stdin; a push to the trunk
                                                       must be attributed; exit 1 refuses under enforce = "block"
    python3 .keelokit/bin/ledger.py snapshot [--run ID] [--push BEFORE..AFTER]
                                                       the CI only: write the snapshot branch ([ledger] snapshot,
                                                       keelokit/ledger) with the push's arrival time; --branch
                                                       prints that branch, empty when the snapshot is off
    python3 .keelokit/bin/ledger.py deploy <staging|production> <commit>
                                                       a deploy job, once its deploy succeeded: deploy/<env> points
                                                       at that commit (backwards too, for a rollback)
    python3 .keelokit/bin/ledger.py check [--ci] [--json] [--rules-ref REV]
                                                       every difference (exit 1 on an error-level one); --ci
                                                       in a pull request into the trunk checks its commits too;
                                                       --rules-ref: the committed rule files from REV
    python3 .keelokit/bin/ledger.py attribution <a>..<b> [--json] [--rules-ref REV]
                                                       is every commit of the range attributed, as `check` says
                                                       (exit 0 answered, 2 usage or unresolved, 3 history cut)
    python3 .keelokit/bin/ledger.py backfill --propose [--from FILE ...]
                                                       candidate correction rows, for review, written to
                                                       .keelokit/ledger-corrections.proposed.toml
    python3 .keelokit/bin/ledger.py correct <commit> --story <ID> --evidence "..."
                                                       propose one late attribution (the same file)
    python3 .keelokit/bin/ledger.py backfill --accept  a person, in their terminal: move the proposed rows
                                                       into backlog/ledger-corrections.toml
    python3 .keelokit/bin/ledger.py review --filter    the delegated review's mechanical filter (JSON)
    python3 .keelokit/bin/ledger.py backfill --accept --delegated <run>
                                                       write the rows a delegated review approved
    python3 .keelokit/bin/ledger.py review --reject-sample <run>
                                                       a person, in their terminal: send a run back to review

Any other command line prints the usage and exits 2.

The states are derived from git alone, never declared (docs/ledger.md, "States"): defined, ready,
in-progress, on-trunk, in-version, in-staging, in-production, or unknown. Stories are read from the
trunk's tree (`[ledger] stories`, `id_from`), the trunk is origin/<trunk> else the local branch (never
HEAD). A fixed number of git calls whatever the number of stories, commits or tags: the parent graph
comes from one `rev-list --parents` and arrivals, tags and deploys are walked in Python. Fail closed:
a cut history makes every state unknown with the reason, and a failing git call exits 2 (no partial
answer).

Harbor (LEDGER-013, docs/ledger.md "Harbor and Swarm"): the logbook, origin/harbor/log, is read with git as data,
never written: an active worker holding a story makes it in-progress, a vessel sealed on its exact head in an open
convoy makes it delivered, and a sailed convoy names the convoy of an on-trunk story and its exact time. It never
adds a difference. Only `take` runs Harbor's harbor.py (`git config harbor.py`), never a hook's path.

Swarm (LEDGER-014, docs/ledger.md "Harbor and Swarm"): the ledger never reads the swarm repo. A helper's delivery is
an origin branch `swarm/<task>` whose commits carry `Part-of: <ID>` and `Swarm-Task: <task>`; once on the trunk, a
commit with `Swarm-Task:` is its story's (by its own Story:/Part-of:, else the merges that attribute it). Each
story's `swarm` list says the task, the branch and head, the commits and their authors, and the Harbor convoy that
carries or sailed it. Like the logbook it adds information only: no difference, no attribution, no state.

Corrections (docs/ledger.md, "Corrections file"): `backlog/ledger-corrections.toml`, read from the trunk's
tree, holds approved rows (story, commit, kind, evidence, approver, date). An active row makes its story
`on-trunk`, marked reconstructed; a `retract` row cancels the earlier rows of the same story and commit. An
invalid row is ignored and reported (CORRECTION_INVALID); a row that was on the trunk's first-parent chain
and is no longer in the file is CORRECTION_EDITED (append-only, INV-008). The file is the person's: only
`backfill --accept`, which needs a terminal and asks, writes it, and the guard keeps agents off both.

Approval modes (docs/ledger.md, "Approval modes"): `[ledger.approval]` in the trunk's committed
.keelokit/state.toml (never the work tree's) may delegate the approval to agents (`delegated` or `mixed`; absent
or unreadable: `human`). A delegated review judges each row twice and tries to refute it; `backfill --accept
--delegated <run>` decides from those verdicts (ledger.py decides, the review file only holds them), writes the
approved rows with approver `delegated:<run>`, and keeps the verdicts in .keelokit/ledger-reviews/<run>.json. A
delegated row counts only while that file, on the trunk, shows it approved.

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

import hashlib  # noqa: E402
import json  # noqa: E402
import random  # noqa: E402
import tempfile  # noqa: E402
import math  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import signal  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402
import tomllib  # noqa: E402
import unicodedata  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
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
DEFAULT_CAP = 20
MAX_CAP = 20
GRACE = 2.0
USAGE = __doc__.split("\n\n")[0]
KEYS = ("remote.origin.promisor", "remote.origin.partialclonefilter", "extensions.partialclone")
NOPROMPT = ["-c", "core.askPass=true", "-c", "credential.interactive=never"]
NETWORK = ("could not resolve host", "connection refused", "connection timed out", "timed out",
           "network is unreachable", "no route to host", "failed to connect", "could not connect",
           "temporary failure in name resolution", "connection reset")


def git_env() -> dict:
    return {**os.environ, "LC_ALL": "C", "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "true",
            "SSH_ASKPASS": "true", "SSH_ASKPASS_REQUIRE": "never", "GCM_INTERACTIVE": "never"}


def run_git(args: list[str], timeout: float | None = None, env: dict | None = None) -> tuple[int | None, str]:
    """(returncode, stderr). returncode None: cut at `timeout`, the process group is gone. `env`: extra variables."""
    proc = subprocess.Popen(["git", *NOPROMPT, *args], cwd=ROOT, env={**git_env(), **(env or {})}, stdin=subprocess.DEVNULL,
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
        proc.wait()
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


def cap_seconds(state: dict) -> float:
    value = (state.get("ledger") or {}).get("history_seconds") if isinstance(state.get("ledger"), dict) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        return DEFAULT_CAP
    return min(value, MAX_CAP)


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


def config_get(key: str) -> str | None:
    code, out = git_out("config", "--local", "--get", key)
    return out if code == 0 else None


def restore_config(snapshot: dict[str, str | None]) -> None:
    """Put the filter config back exactly as it was: unset what was unset, set what was set."""
    for key, value in snapshot.items():
        if config_get(key) == value:
            continue
        if value is None:
            git_out("config", "--local", "--unset-all", key)
        else:
            git_out("config", "--local", key, value)


def ensure(trunk: str, cap: float, snapshot_branch: str = "") -> str:
    """Complete the history; the one line to print. With a snapshot branch, the last quarter of the cap (at most 3 s)
    is kept for fetching it when the history stays incomplete (LEDGER-011), so the ledger can read it instead."""
    fix = f"`git fetch --unshallow origin {trunk}`"
    if git_out("remote", "get-url", "origin")[0]:
        return f"Keelokit: no origin: history incomplete; add a remote, then run {fix}"
    snapshot = {k: config_get(k) for k in KEYS}
    honoured = False
    start = time.monotonic()
    reserve = min(3.0, cap / 4) if snapshot_branch else 0.0
    try:
        line, honoured = fetch_history(trunk, cap - reserve, fix, shown=cap)
        if snapshot_branch and not line.startswith("Keelokit: history completed"):
            line += read_snapshot_line(trunk, snapshot_branch, cap - (time.monotonic() - start))
        elif line.startswith("Keelokit: history completed"):
            ensure_deploy_branches(cap - (time.monotonic() - start))
        return line
    finally:
        # git writes the promisor config before it contacts the server: whatever does not end as a
        # complete fetch whose filter the server honoured (failed, cut, ignored, plain fallback)
        # leaves the config as it was, so a later fetch neither warns forever nor comes back partial.
        if not honoured:
            restore_config(snapshot)


def ensure_deploy_branches(remaining: float) -> None:
    """A clone whose fetch leaves deploy/* out (`git clone --depth`, `--single-branch`) never sees where staging and
    production are, so its stories read in-version (ESC-249): add deploy/* to origin's fetch and fetch it, pruned. A
    clone that fetches every branch already has them."""
    code, out = git_out("config", "--get-all", "remote.origin.fetch")
    sources = {line.lstrip("+").split(":", 1)[0] for line in out.splitlines()} if code == 0 else set()
    if remaining <= 0.2 or "refs/heads/*" in sources or git_out("remote", "get-url", "origin")[0]:
        return
    spec = "+refs/heads/deploy/*:refs/remotes/origin/deploy/*"
    if "refs/heads/deploy/*" not in sources:
        git_out("config", "--add", "remote.origin.fetch", spec)
    run_git(["fetch", "-q", "--prune", "--no-tags", "origin", spec], remaining)


def read_snapshot_line(trunk: str, name: str, remaining: float) -> str:
    """What `history --ensure` adds to its line when it fetched origin/<name> in the time left: which trunk commit the
    ledger now reads from; nothing when it could not."""
    if remaining <= 0.2 or name.startswith("-") or git_out("check-ref-format", f"refs/heads/{name}")[0] \
            or not snapshot_usable(name, trunk):
        return ""
    start = time.monotonic()
    code, _ = run_git(["fetch", "-q", "--no-tags", "origin", f"+refs/heads/{name}:refs/remotes/origin/{name}"], remaining)
    if code != 0:
        return ""
    ensure_deploy_branches(remaining - (time.monotonic() - start))  # where each environment is now (ESC-215)
    try:
        snap = parse_snapshot(git_read(["show", f"refs/remotes/origin/{name}:ledger.json"]))
    except LedgerError:
        snap = None
    # ESC-256: named only when the reader will take it
    return f"; the ledger reads the CI's snapshot of {trunk}@{snap['trunk_sha'][:7]} ({name})" if snap else ""


def fetch_history(trunk: str, cap: float, fix: str, shown: float | None = None) -> tuple[str, bool]:
    """(the one line, whether a complete fetch's filter was honoured). `shown`: the cap the line names."""
    start = time.monotonic()
    deadline = start + cap
    spec = f"+refs/heads/{trunk}:refs/remotes/origin/{trunk}"  # also fills origin/<trunk> in a single-branch clone
    attempts = [["fetch", "--filter=blob:none", "--unshallow", "origin", trunk, spec],
                ["fetch", "--unshallow", "origin", trunk, spec]]
    code, err = None, ""
    plain = False
    for i, args in enumerate(attempts):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            code = None
            break
        plain = i == 1
        code, err = run_git(args, remaining)
        if code is None or code == 0:
            break
        if i == 0 and "filter" not in err.lower():
            break
    if code is None:
        return f"Keelokit: cut at {shown or cap:g}s: history incomplete; run {fix}", False
    if code != 0:
        msg = " ".join(last_error(err).split())
        kind = "offline" if any(n in err.lower() for n in NETWORK) else "fetch failed"
        return f"Keelokit: {kind}: history incomplete ({msg}); the doctor reads unknown until {fix}", False
    if is_shallow():
        return f"Keelokit: history still incomplete after the fetch; run {fix}", False
    count = git_out("rev-list", "--count", f"refs/remotes/origin/{trunk}")[1]
    line = f"Keelokit: history completed ({count} commits of {trunk}) in {time.monotonic() - start:.1f}s"
    return line, not plain and "filtering not recognized by server" not in err


def history(do_ensure: bool, state: dict, trunk: str) -> int:
    shallow = is_shallow()
    if shallow is None:
        if not do_ensure:
            print("Keelokit: not a git repository.", file=sys.stderr)
        return 0 if do_ensure else 2
    if not shallow:
        if do_ensure:
            ensure_deploy_branches(cap_seconds(state))
        return 0
    if trunk.startswith("-") or git_out("check-ref-format", "--branch", trunk)[0]:
        print(f"Keelokit: trunk {trunk!r} is not a branch name: history incomplete")
        return 0 if do_ensure else 1
    if not do_ensure:
        print("Keelokit: history incomplete (shallow clone); run `python3 .keelokit/bin/ledger.py history --ensure`")
        return 1
    print(ensure(trunk, cap_seconds(state), read_config(state)["snapshot"]))
    return 0


# ───────────────────────── states of every story (LEDGER-003) ─────────────────────────

STATES = ("defined", "ready", "in-progress", "delivered", "on-trunk", "in-version", "in-staging", "in-production")
ENVIRONMENTS = ("staging", "production")
READ_CONFIG = ["-c", "log.showSignature=false", "-c", "i18n.logOutputEncoding=UTF-8"]
STORY_ID = re.compile(r"[A-Z][A-Z0-9]*-[0-9]+")
VERSION_TAG = re.compile(r"v([0-9]+(?:\.[0-9]+)*)(?:-rc\.([0-9]+))?")
REVERTS = re.compile(r"^This reverts commit ([0-9a-f]{40}|[0-9a-f]{64})(?=[.,]|$)", re.M)
FRONT_MATTER = re.compile(r"\+\+\+\n(.*?)\n\+\+\+(?:\n|$)", re.S)
HEX_SHA = re.compile(r"[0-9a-fA-F]{7,64}")
DEFAULT_STORIES = "backlog/stories/*.md"
DEFAULT_STALE_DAYS = 7
DEFAULT_NO_STORY = ("harness", "docs", "release", "deps", "ci")
DEFAULT_SNAPSHOT = "keelokit/ledger"
SHOW_LINES = 60
SHOW_WIDTH = 200
ESCAPES = "docs/escapes.md"
BUGBASH = "docs/bugbash/"
ADDENDUM_HEADING = re.compile(r"#{1,6}\s+Addendum\b")
SQUASHED_TRAILER = re.compile(r"(?m)^[ \t*-]*((?i:story|part-of)):[ \t]*([A-Z][A-Z0-9]*-[0-9]+)")
TRAILER_LINE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*:|\(cherry picked from commit ")
class Screen:
    """What may not reach a terminal or a snapshot as it is: control characters (Cc, C0 and C1), format characters (Cf:
    bidi overrides and isolates such as U+202E and U+2066..2069, zero-width characters, the BOM) and the line and
    paragraph separators (Zl, Zp: U+2028, U+2029), by Unicode category, whatever this Python's Unicode version
    (HARN-022). `keep`: characters let through (the tab and the newline, which the callers turn into what they mean).
    `.search` and `.sub` read as a regex's."""

    CATEGORIES = ("Cc", "Cf", "Zl", "Zp")

    def __init__(self, keep: str = ""):
        self.keep = keep
        self.ascii = re.compile("[%s]" % "".join(re.escape(chr(c)) for c in [*range(0x20), 0x7f] if chr(c) not in keep))

    def bad(self, ch: str) -> bool:
        return ch not in self.keep and unicodedata.category(ch) in self.CATEGORIES

    def search(self, text: str) -> str | None:
        """The first such character (truthy), else None."""
        if text.isascii():
            m = self.ascii.search(text)
            return m.group(0) if m else None
        return next((ch for ch in text if self.bad(ch)), None)

    def sub(self, repl: str, text: str) -> str:
        if text.isascii():
            return self.ascii.sub(repl, text)
        return "".join(repl if self.bad(ch) else ch for ch in text)


CONTROL = Screen(keep="\t\n")
FIX = "run `python3 .keelokit/bin/ledger.py history --ensure`"
CORRECTIONS = "backlog/ledger-corrections.toml"
PROPOSED = ".keelokit/ledger-corrections.proposed.toml"
KINDS = ("backfill", "late", "retract")
REVIEWS = ".keelokit/ledger-reviews"
STATE_FILE = ".keelokit/state.toml"
CRITICAL_FILE = ".keelokit/critical.toml"
RISKY_FILE = ".keelokit/risky.toml"  # HARN-021: what makes a story risky, and its breaker round cap
DEFAULT_ROUNDS = 3
MAX_ROUNDS = 20
# The files that decide what is judged are always risky, whatever risky.toml says (ESC-331): a change to them belongs
# to a story, which then needs its rounds.
ALWAYS_RISKY = (RISKY_FILE, STATE_FILE, CORRECTIONS)
# What a `No-story: release` commit may change and still not be RISKY_NO_STORY (scripts/release.sh, ship-release).
RELEASE_FILES = ("CHANGELOG.md", ".claude-plugin/plugin.json", "package.json")
RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
MODES = ("human", "delegated", "mixed")
HUMAN_FOR = ("critical", "disagreement", "low-confidence")
DEFAULT_SAMPLE = 0.05
DELEGATED = "delegated:"
CONFIDENCE = {"high": 3, "medium": 2, "low": 1}
FULL_SHA = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
ID_TOKEN = re.compile(r"(?<![A-Za-z0-9])[A-Z][A-Z0-9]*-[0-9]+(?![0-9])")
BRANCH_ID = re.compile(r"(?<![A-Za-z0-9])[A-Za-z][A-Za-z0-9]*-[0-9]+(?![0-9])")
MERGE_BRANCH = re.compile(r"^Merge (?:pull request #[0-9]+ from [^/\s]+/(\S+)|(?:remote-tracking )?branch '([^']+)')")
TRAIN_WORD = re.compile(r"(?i)\b(?:train|tren|convoy)\s*#?\s*([0-9]+)\b")
TRAIN_T = re.compile(r"\bT([0-9]+)\b")
TRAIN_CELL = re.compile(r"(?i)\W*(?:T|train\s*|tren\s*|convoy\s*)?#?([0-9]+)\W*")
TRAIN_BRANCH = re.compile(r"(?i)^(?:origin/)?(?:convoy|train)[/-]([0-9]+)$")
CONVOY_TRAILER = re.compile(r"(?m)^Convoy:\s*#?([0-9]+)\s*$")
HEX_WORD = re.compile(r"(?<![0-9A-Za-z])[0-9a-f]{7,64}(?![0-9A-Za-z])")
CORRECTIONS_HEADER = """\
# Approved corrections to the ledger (docs/ledger.md, "Corrections file"): the history that has no trailers,
# and commits that slipped through without one. An active row makes its story on-trunk, shown as
# reconstructed. Rows are added by `python3 .keelokit/bin/ledger.py backfill --accept`, run by a person in
# their terminal after reviewing what `backfill --propose` or `correct` put in
# .keelokit/ledger-corrections.proposed.toml (git-ignored).
#
# Each row is a [[row]] table:
#   story     the story id, e.g. "UXC-113"
#   commit    the full sha of a commit reachable from the trunk
#   kind      "backfill" (old history), "late" (a commit that slipped through) or "retract" (cancels an
#             earlier row of the same story and commit)
#   evidence  where the attribution comes from
#   approver  who approved it
#   date      "YYYY-MM-DD"
#
# Append-only: no row already on the trunk may change or disappear (INV-008); cancel a wrong row with a
# retract row. A change here needs a human: the guard blocks agents from writing this file, and a commit
# that changes it needs `git -c keelokit.allowTamper=true commit`, saying why in the message.
"""
STATE_NAMES = {
    "en": {s: s for s in (*STATES, "unknown")},
    "es": {"defined": "definida", "ready": "lista", "in-progress": "en curso", "delivered": "entregada",
           "on-trunk": "en trunk",
           "in-version": "en versión", "in-staging": "en staging", "in-production": "en producción",
           "unknown": "desconocida"},
}
LABELS = {
    "en": {"complete": "history complete", "cut": "history INCOMPLETE: every state is unknown",
           "stories": "stories", "progress": "in progress", "delivered": "delivered", "ready": "ready",
           "reverted": "reverted",
           "unknown": "unknown", "stale": "stale", "more": "more", "none": "no stories found",
           "unattributed": "unattributed commits since", "reconstructed": "reconstructed",
           "by_person": "reconstructed (person)", "by_delegated": "reconstructed (delegated)",
           "snapshot": "history incomplete: states read from the CI's snapshot of {sha}"},
    "es": {"complete": "historia completa", "cut": "historia INCOMPLETA: todos los estados son desconocidos",
           "stories": "historias", "progress": "en curso", "delivered": "entregadas", "ready": "listas",
           "reverted": "revertidas",
           "unknown": "desconocidas", "stale": "estancada", "more": "más", "none": "no hay historias",
           "unattributed": "commits sin atribuir desde", "reconstructed": "reconstruidas",
           "by_person": "reconstruidas (persona)", "by_delegated": "reconstruidas (delegada)",
           "snapshot": "historia incompleta: estados leídos de la instantánea del CI de {sha}"},
}


class LedgerError(Exception):
    """A fact could not be read: the run ends with exit 2 and this reason, never a partial answer."""


def git_read(args: list[str], data: bytes | None = None, ok: tuple = (0,), env: dict | None = None) -> bytes:
    """stdout of one git call (LC_ALL=C, no prompts); LedgerError when it cannot run or exits outside `ok`. `env`:
    extra variables (the snapshot's temporary index and identity)."""
    kwargs = {"input": data} if data is not None else {"stdin": subprocess.DEVNULL}
    try:
        r = subprocess.run(["git", *NOPROMPT, *READ_CONFIG, *args], cwd=ROOT,
                           env={**git_env(), "GIT_NO_LAZY_FETCH": "1", **(env or {})},  # reading never fetches
                           capture_output=True, **kwargs)
    except OSError as e:
        raise LedgerError(f"cannot run git ({e})") from e
    if r.returncode not in ok:
        raise LedgerError(f"git {args[0]} failed: {last_error(r.stderr.decode(errors='replace'))}")
    return r.stdout


def setting(state: dict, key: str, kind: type, default):
    """`[ledger] <key>` when it has the right type (bool never counts as a number), else the default."""
    table = state.get("ledger")
    value = table.get(key) if isinstance(table, dict) else None
    if kind is float:
        ok = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0
    else:
        ok = isinstance(value, kind) and (kind is not str or value.strip())
    return value if ok else default


def read_config(state: dict) -> dict:
    """The `[ledger]` keys this reader uses, each with its default; `since` only if it looks like a sha."""
    id_from = setting(state, "id_from", str, "front-matter")
    since = setting(state, "since", str, "").strip()
    lang = state.get("dashboard", {}).get("lang") if isinstance(state.get("dashboard"), dict) else None
    no_story = state.get("ledger", {}).get("no_story") if isinstance(state.get("ledger"), dict) else None
    snapshot = state.get("ledger", {}).get("snapshot") if isinstance(state.get("ledger"), dict) else None
    return {"stories": setting(state, "stories", str, DEFAULT_STORIES).strip(),
            "no_story": text_list(no_story) if isinstance(no_story, list) else list(DEFAULT_NO_STORY),
            "enforce": "warn" if setting(state, "enforce", str, "block").strip() == "warn" else "block",
            "snapshot": snapshot.strip() if isinstance(snapshot, str) else DEFAULT_SNAPSHOT,
            "id_from": id_from if id_from in ("front-matter", "filename") else "front-matter",
            "stale_days": setting(state, "stale_days", float, DEFAULT_STALE_DAYS),
            "since": since if HEX_SHA.fullmatch(since) else None,
            "lang": "es" if lang == "es" else "en"}


def glob_regex(pattern: str) -> re.Pattern:
    """`*` and `?` stay inside one directory, `**` crosses them; anything else is literal."""
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        else:
            c = pattern[i]
            out.append("[^/]*" if c == "*" else "[^/]" if c == "?" else re.escape(c))
            i += 1
    return re.compile("".join(out))


def iso(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── reading the facts: a fixed number of git calls ──

def read_refs(trunk: str, snapshot: str = "") -> dict[str, str]:
    """Commit of each ref that matters: v* tags (fully peeled), every origin branch, the local trunk. The snapshot
    branch (LEDGER-011) is no branch of the project: origin/<snapshot> (and the default name's) is left out, and the
    configured one's commit is under the key "snapshot", which no `refs/` filter matches."""
    patterns = ["refs/tags/v*", "refs/remotes/origin/", f"refs/heads/{trunk}"]
    fmt = "%(refname)%09%(objectname)%09%(objecttype)%09%(*objectname)%09%(*objecttype)"
    refs, nested = {}, []
    for line in git_read(["for-each-ref", f"--format={fmt}", *patterns]).decode(errors="replace").splitlines():
        name, sha, kind, peeled, peeled_kind = line.split("\t")
        if kind == "tag" and peeled_kind == "tag":
            nested.append(name)
        elif kind == "tag":
            sha, kind = peeled, peeled_kind
        if kind == "commit":
            refs[name] = sha
    if nested:
        refs.update(peel_nested(nested))
    snapshot = snapshot if snapshot_usable(snapshot, trunk) else ""
    for name in hidden_snapshots(snapshot):
        if not snapshot_usable(name, trunk):
            continue
        head = refs.pop(f"refs/remotes/origin/{name}", None)
        if head and name == snapshot:
            refs["snapshot"] = head
    return refs


def snapshot_usable(name: str, trunk: str) -> bool:
    """A snapshot name that is not the trunk nor a deploy branch, nor a prefix or child of either's name (ESC-217,
    ESC-255): those are the project's own."""
    return (bool(name) and name not in (trunk, "HEAD", "deploy") and not name.startswith(("deploy/", f"{trunk}/"))
            and not trunk.startswith(f"{name}/"))


def hidden_snapshots(snapshot: str) -> list[str]:
    """The origin branches that hold a snapshot, never read as the project's: the configured one and the default."""
    return sorted({snapshot, DEFAULT_SNAPSHOT} - {""})


def peel_nested(names: list[str]) -> dict[str, str]:
    """name -> commit for tags of tags, one `cat-file --batch-check` of `<ref>^{}` lines; others are dropped."""
    out = git_read(["cat-file", "--batch-check"], "".join(f"{n}^{{}}\n" for n in names).encode())
    lines = out.decode(errors="replace").splitlines()
    if len(lines) != len(names):
        raise LedgerError("git cat-file gave an unexpected answer")
    return {n: line.split()[0] for n, line in zip(names, lines) if line.split()[1:2] == ["commit"]}


def check_trunk(trunk: str) -> None:
    """LedgerError unless the trunk is a branch name git accepts (and cannot read as an option)."""
    try:
        if trunk.startswith("-"):
            raise LedgerError("starts with a dash")
        git_read(["check-ref-format", f"refs/heads/{trunk}"])
    except LedgerError as e:
        raise LedgerError(f"the trunk {trunk!r} is not a branch name") from e


def resolve_trunk(trunk: str, refs: dict[str, str]) -> str:
    """The trunk's commit: origin/<trunk> if it resolves, else the local branch; never HEAD."""
    for name in (f"refs/remotes/origin/{trunk}", f"refs/heads/{trunk}"):
        if name in refs:
            return refs[name]
    raise LedgerError(f"the trunk {trunk!r} does not resolve (no refs/remotes/origin/{trunk}, "
                      f"no refs/heads/{trunk})")


def read_graph(tips: list[str]) -> dict[str, tuple[str, ...]]:
    """sha -> parents of everything the tips reach, from one `rev-list --parents`."""
    out = git_read(["rev-list", "--parents", "--stdin"], "".join(f"{t}\n" for t in tips).encode())
    graph = {}
    for line in out.decode().splitlines():
        sha, *parents = line.split()
        graph[sha] = tuple(parents)
    return graph


def cut_reason(graph: dict, shallow: bool) -> str | None:
    """Why the history is incomplete, or None: a shallow clone whose refs reach a commit of the shallow
    file with a parent the graph lacks (as the doctor's cut_commits; %P hides it, so raw objects)."""
    if not shallow:
        return None
    reach = sorted(shallow_marks() & set(graph))
    if reach and git_cut(reach, graph):
        return f"the clone is shallow and cut the history ({len(graph)} commits reachable); {FIX}"
    return None


def shallow_marks() -> set[str]:
    """The commits of the shallow file: where a shallow clone's history stops (their parents are not here)."""
    path = Path(git_read(["rev-parse", "--git-path", "shallow"]).decode().strip() or "shallow")
    try:
        return set((path if path.is_absolute() else ROOT / path).read_text().split())
    except OSError as e:  # shallow, yet its file cannot be read: no answer from a possibly cut history
        raise LedgerError(f"the shallow file cannot be read ({e.strerror or e})") from e


def git_cut(shas: list[str], graph: dict) -> bool:
    """True when one of these commits has a parent outside the graph, or cannot be read (fails closed)."""
    out = git_read(["cat-file", "--batch"], "".join(f"{s}\n" for s in shas).encode())
    pos = 0
    while pos < len(out):
        end = out.find(b"\n", pos)
        head = out[pos:end].split() if end >= 0 else []
        if len(head) < 3 or head[1] != b"commit":
            return True
        size = int(head[2])
        headers = out[end + 1:end + 1 + size].split(b"\n\n", 1)[0].split(b"\n")
        if any(h.startswith(b"parent ") and h[7:].decode() not in graph for h in headers):
            return True
        pos = end + 1 + size + 1
    return False


def missing_objects(trunk_sha: str) -> set[str]:
    """Objects of the trunk's tree this clone does not have (a partial or damaged one): one tree walk that
    prints `?<sha>` for each, where `cat-file` would try to fetch it from the promisor remote."""
    out = git_read(["rev-list", "--objects", "--missing=print", "--no-object-names", f"{trunk_sha}^{{tree}}"])
    return {line[1:] for line in out.decode(errors="replace").splitlines() if line.startswith("?")}


def is_partial_clone() -> bool:
    """True when the repository has a promisor remote (a `--filter` clone): only there can an object be absent
    by design. One `git config` call; exit 1 means no such key."""
    out = git_read(["config", "--get-regexp", r"^(extensions\.partialclone|remote\..*\.promisor)$"], ok=(0, 1))
    return bool(out.strip())


def read_blobs(shas: list[str], trunk_sha: str) -> dict[str, bytes | None]:
    """Contents of blobs by sha in one `cat-file --batch`; None for one the clone lacks. In a partial clone
    the absent ones are found first (a tree walk) so `cat-file` never tries to fetch them."""
    unique = sorted(set(shas))
    if not unique:
        return {}
    absent = missing_objects(trunk_sha) & set(unique) if is_partial_clone() else set()
    return {**dict.fromkeys(absent), **cat_blobs([sha for sha in unique if sha not in absent])}


def front_matter(text: str) -> tuple[dict | None, str]:
    """(the `+++` TOML block of a story file, the text after it); (None, text) without a valid one."""
    text = text.replace("\r\n", "\n")
    m = FRONT_MATTER.match(text)
    if not m:
        return None, text
    try:
        return tomllib.loads(m.group(1)), text[m.end():]
    except ValueError:
        return None, text


def first_heading(text: str) -> str | None:
    """The first Markdown `# ` heading outside code fences."""
    fenced = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
        elif not fenced and line.startswith("# ") and line[2:].strip():
            return line[2:].strip()
    return None


def build_story(path: str, content: bytes | None, id_from: str) -> dict | None:
    """One story record from its file, or None when it is not a story. `unreadable` when the blob is missing."""
    base = path.rsplit("/", 1)[-1]
    if content is None:  # the id can only come from the name
        m = STORY_ID.match(base)
        if not m:
            raise LedgerError(f"the story file {path} cannot be read and its name has no EPIC-NNN id")
        sid = m.group(0)
        return {"id": sid, "title": sid, "epic": sid.split("-")[0], "wave": None, "depends_on": [], "path": path,
                "unreadable": True, "touches": [], "dimensions": [], "risky": False, "breaker": None}
    meta, body = front_matter(content.decode("utf-8", errors="replace"))
    if id_from == "filename":
        m = STORY_ID.match(base)
        if not m:
            return None
        sid, title = m.group(0), first_heading(body) or m.group(0)
    else:
        if meta is None or not isinstance(meta.get("id"), str) or not STORY_ID.fullmatch(meta["id"]):
            return None
        sid = meta["id"]
        title = meta["title"] if isinstance(meta.get("title"), str) and meta["title"] else sid
    meta = meta or {}
    wave, deps = meta.get("wave"), meta.get("depends_on")
    epic = meta.get("epic") if id_from == "front-matter" else None
    return {"id": sid, "title": title, "epic": epic if isinstance(epic, str) and epic else sid.split("-")[0],
            "wave": wave if isinstance(wave, int) and not isinstance(wave, bool) else None,
            "depends_on": [d for d in deps if isinstance(d, str)] if isinstance(deps, list) else [],
            "path": path, "unreadable": False, "touches": text_list(meta.get("touches")),
            "dimensions": text_list(meta.get("dimensions")), "risky": meta.get("risky") is True,
            "risk_dims": [d.lower() for d in text_list(meta["dimensions"] if isinstance(meta.get("dimensions"), list)
                                                       else [meta.get("dimensions")])],
            "breaker": breaker_record(body)}


def text_list(value) -> list[str]:
    """The non-empty strings of a TOML list (anything else: none)."""
    return [v.strip() for v in value if isinstance(v, str) and v.strip()] if isinstance(value, list) else []


def read_tree(trunk_sha: str) -> list[tuple[str, str]]:
    """(path, blob) of every regular file of the trunk's tree (no symlinks), from one `ls-tree`."""
    files = []
    for rec in git_read(["ls-tree", "-r", "-z", "--full-tree", trunk_sha]).decode(errors="replace").split("\0"):
        meta, _, path = rec.partition("\t")
        fields = meta.split()
        if len(fields) == 3 and fields[0] != "120000" and fields[1] == "blob":
            files.append((path, fields[2]))
    return files


def read_trunk_files(trunk_sha: str, tree: list[tuple[str, str]], strict: bool = False) -> dict:
    """What the approval modes read from the trunk's tree, in one `cat-file`: state.toml, critical.toml and the
    review files ({run: bytes}). A file the clone lacks reads as absent; `strict` (the rules of `check --rules-ref`):
    LedgerError instead, since a rule read as absent is a looser rule (no critical area, the default enforce)."""
    wanted = {path: sha for path, sha in tree if path in (STATE_FILE, CRITICAL_FILE, CORRECTIONS, RISKY_FILE)
              or (path.startswith(REVIEWS + "/") and path.endswith(".json")
                  and RUN_ID.fullmatch(path[len(REVIEWS) + 1:-5]) and "/" not in path[len(REVIEWS) + 1:])}
    blobs = read_blobs(list(wanted.values()), trunk_sha)
    content = {path: blobs.get(sha) for path, sha in wanted.items()}
    lacking = sorted(path for path, data in content.items() if data is None)
    if strict and lacking:
        raise LedgerError(f"the rules at {short(trunk_sha)} are not in this clone ({', '.join(lacking[:3])}"
                          f"{', …' if len(lacking) > 3 else ''}: a partial clone); fetch them, or use a full clone")
    reviews = {path[len(REVIEWS) + 1:-5]: data for path, data in content.items()
               if path.startswith(REVIEWS + "/") and data is not None}
    risky = risky_config(content.get(RISKY_FILE), True) if RISKY_FILE in wanted else None
    if risky is None and git_read(["ls-tree", "-z", trunk_sha, "--", RISKY_FILE]).strip(b"\0"):
        # A risky.toml that is no regular file (a symlink, a submodule) is no file the ledger reads: it fails closed
        # (BREAKER_CONFIG, every closed story risky), never as absent (ESC-315).
        risky = {**risky_config(None, True), "problem": f"{RISKY_FILE} is not a regular file"}
    return {"state": content.get(STATE_FILE), "critical": content.get(CRITICAL_FILE), "reviews": reviews,
            "corrections": content.get(CORRECTIONS), "risky": risky}


def read_stories(trunk_sha: str, cfg: dict, tree: list[tuple[str, str]] | None = None) -> tuple[list[dict], list[str]]:
    """(the stories of the trunk's tree, the paths of the story files that could not be read): `ls-tree` and
    one `cat-file --batch`. A duplicate id keeps the first path, but a readable file beats an unreadable one."""
    pattern = glob_regex(cfg["stories"])
    found = sorted((path, sha) for path, sha in (read_tree(trunk_sha) if tree is None else tree)
                   if pattern.fullmatch(path))
    blobs = read_blobs([sha for _, sha in found], trunk_sha)
    stories, unreadable = {}, []
    for path, sha in found:
        story = build_story(path, blobs[sha], cfg["id_from"])
        unreadable += [path] if blobs[sha] is None else []
        old = stories.get(story["id"]) if story else None
        if story and (old is None or old["unreadable"] and not story["unreadable"]):
            if old is not None:
                story["copies"] = [old, *old.get("copies", [])]
                old.pop("copies", None)
            stories[story["id"]] = story
        elif story and not story["unreadable"]:  # another file with the same id: the breaker reads every copy (ESC-324)
            old.setdefault("copies", []).append(story)
    return sorted(stories.values(), key=lambda s: s["id"]), unreadable


def read_log(args: list[str]) -> list[list[str]]:
    """Records of a NUL-separated log: 8 fields (the 7th every trailer, the last the raw body), so no message can
    break the parsing."""
    fmt = ("%H%x00%P%x00%ct%x00%(trailers:key=Story,valueonly,separator=%x2C,unfold)%x00"
           "%(trailers:key=Part-of,valueonly,separator=%x2C,unfold)%x00"
           "%(trailers:key=No-story,valueonly,separator=%x2C,unfold)%x00%(trailers:only,unfold)%x00%B")
    parts = git_read(["log", "-z", f"--format={fmt}", *args]).decode(errors="replace").split("\0")
    if parts and parts[-1] == "":
        parts.pop()
    if len(parts) % 8:
        raise LedgerError("git log gave an unexpected answer")
    return [parts[i:i + 8] for i in range(0, len(parts), 8)]


def story_ids(field: str) -> list[str]:
    return [i for i in (p.strip() for p in field.split(",")) if STORY_ID.fullmatch(i)]


def read_trunk_log(trunk_sha: str, more: tuple = ()) -> list[dict]:
    """Every trunk commit, children before parents: sha, parents, ct, trailers, the commits it reverts. `more`:
    extra rev-list arguments (`--not <sha>...` for a range). A commit reverts X only when its message says so AND its
    change is X's inverted (real_reverts, ESC-335)."""
    log = read_log_records(trunk_sha, more)
    pairs = {(c["sha"], x) for c in log for x in c["reverts"]}
    real = real_reverts(pairs)
    for c in log:
        # What the message claims stays readable: a "revert" commit is still no evidence of the story (ESC-093).
        c["reverts_said"] = c["reverts"]
        c["reverts"] = [x for x in c["reverts"] if (c["sha"], x) in real]
    return log


REVERT_CACHE: dict[frozenset, set] = {}


def change_ids(shas: list[str], reverse: bool) -> dict[str, str]:
    """commit -> a hash of its change as git records it: each path with its old and new mode and blob id (a merge:
    against its first parent); `reverse`: of the change inverted. One `git log --raw`, so neither a binary file nor
    a `.gitattributes` the change under judgment brings (`* -diff`) can make two changes look alike (ESC-338,
    ESC-342, ESC-343). A commit with no change has none."""
    out = git_read(["-c", "core.quotePath=false", "log", "--no-walk=unsorted", "--stdin", "--raw", "--no-abbrev",
                    "--no-renames", "--diff-merges=first-parent", "--format=%x00%H"],
                   "".join(f"{x}\n" for x in shas).encode()).decode(errors="replace")
    ids = {}
    for chunk in out.split("\0")[1:]:
        head, _, rest = chunk.partition("\n")
        rows = []
        for line in rest.splitlines():
            meta, tab, path = line.partition("\t")
            fields = meta.lstrip(":").split()
            if line.startswith(":") and tab and len(fields) >= 4:
                old, new = (fields[0], fields[2]), (fields[1], fields[3])
                rows.append((path, *(new + old if reverse else old + new)))
        if rows:
            ids[head.strip()] = hashlib.sha256(repr(sorted(rows)).encode()).hexdigest()
    return ids


def real_reverts(pairs: set[tuple[str, str]]) -> set[tuple[str, str]]:
    """The (reverter, target) pairs whose reverter's change is the target's inverted: a message-only "revert", or a
    partial one, reverts nothing (ESC-335). A clone that cannot read the changes (a partial clone without the blobs,
    a target past a cut) keeps the messages' word: the CI's full clone decides."""
    if not pairs:
        return set()
    key = frozenset(pairs)
    if key not in REVERT_CACHE:
        try:
            forward = change_ids(sorted({x for _, x in pairs}), False)
            back = change_ids(sorted({r for r, _ in pairs}), True)
            REVERT_CACHE[key] = {(r, x) for r, x in pairs if forward.get(x) and forward.get(x) == back.get(r)}
        except LedgerError:
            REVERT_CACHE[key] = set(pairs)
    return REVERT_CACHE[key]


def read_log_records(trunk_sha: str, more: tuple = ()) -> list[dict]:
    """read_trunk_log's records, the reverts as the messages name them."""
    return [{"sha": sha, "parents": parents.split(), "ct": int(ct), "story": story_ids(story),
             "part_of": story_ids(part), "attributed": bool(story.strip() or part.strip() or nostory.strip()),
             "no_story": bool(nostory.strip()), "reverts": REVERTS.findall(body), "message": body,
             "trailers": parse_trailers(trailers)}
            for sha, parents, ct, story, part, nostory, trailers, body in read_log(["--topo-order", trunk_sha, *more])]


def parse_trailers(text: str) -> list[tuple[str, str]]:
    """(key, value) of each line of `%(trailers:only,unfold)`."""
    pairs = []
    for line in text.splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip():
            pairs.append((key.strip(), value.strip()))
    return pairs


def trailer_values(trailers: list[tuple[str, str]], key: str) -> list[str]:
    """The values of one trailer key (git matches keys in any case)."""
    return [v for k, v in trailers if k.lower() == key.lower()]


def trailer_ids(trailers: list[tuple[str, str]], key: str) -> list[str]:
    return [i for v in trailer_values(trailers, key) for i in story_ids(v)]


def split_message(message: str, trailers: list) -> tuple[str, list[str]]:
    """(subject, body lines): the body is what is outside the subject line and the trailer paragraph (the last
    one, when git read trailers from it); its lines that are not trailers count as body."""
    paragraphs = [p for p in re.split(r"\n[ \t]*\n", message.replace("\r\n", "\n").strip("\n")) if p.strip()]
    if not paragraphs:
        return "", []
    subject = " ".join(line.strip() for line in paragraphs[0].split("\n") if line.strip())
    body: list[str] = []
    rest = paragraphs[1:]
    last = rest.pop().split("\n") if trailers and rest else []
    for p in rest:
        body += ["", *p.split("\n")] if body else p.split("\n")
    body += [line for line in last if line.strip() and not TRAILER_LINE.match(line) and not line[:1].isspace()]
    while body and not body[0].strip():
        body.pop(0)
    return subject, [line.rstrip() for line in body]


def read_branches(trunk_sha: str, refs: dict, graph: dict, on_trunk: set, snapshot: str = "") -> dict[str, dict]:
    """story id -> {branches, newest, commits, dropped}: every origin branch whose commits off the trunk include a
    Part-of commit of the story, and those commits and the story's `Dropped:` commits there (for `show`). One log
    finds them; each branch tip gets a bit, and the bits flow from the tips to their parents in one pass over the
    off-trunk commits (children before parents)."""
    fmt = ("%H%x00%ct%x00%(trailers:key=Part-of,valueonly,separator=%x2C,unfold)%x00"
           "%(trailers:key=Dropped,valueonly,separator=%x2C,unfold)%x00%(trailers:only,unfold)%x00%B")
    hide = [f"--exclude=origin/{name}" for name in hidden_snapshots(snapshot) if f"refs/remotes/origin/{name}" not in refs]
    out = git_read(["log", "-z", f"--format={fmt}", *hide, "--remotes=origin", "--not", trunk_sha]).decode(errors="replace")
    parts = out.split("\0")
    if parts and parts[-1] == "":
        parts.pop()
    if len(parts) % 6:
        raise LedgerError("git log gave an unexpected answer")
    marked = {sha: (story_ids(part), story_ids(dropped), int(ct), parse_trailers(trailers), body)
              for sha, ct, part, dropped, trailers, body in (parts[i:i + 6] for i in range(0, len(parts), 6))
              if story_ids(part) or story_ids(dropped)}
    if not marked:
        return {}
    names = [n for n in sorted(refs) if n.startswith("refs/remotes/origin/") and n != "refs/remotes/origin/HEAD"]
    masks = flow_masks(graph, on_trunk, [(1 << i, refs[n]) for i, n in enumerate(names)])
    result: dict[str, dict] = {}
    for sha, (part, dropped, ct, trailers, body) in marked.items():
        if not masks.get(sha):
            continue
        commit = {"sha": sha, "ct": ct, "trailers": trailers, "message": body, "mask": masks[sha], "names": names}
        for sid in part:
            entry = result.setdefault(sid, {"mask": 0, "newest": 0, "commits": [], "dropped": []})
            entry["mask"] |= masks[sha]
            entry["newest"] = max(entry["newest"], ct)
            entry["commits"].append(commit)
        for sid in dropped:
            result.setdefault(sid, {"mask": 0, "newest": 0, "commits": [], "dropped": []})["dropped"].append(commit)
    return {sid: {"branches": {names[i].removeprefix("refs/remotes/origin/") for i in set_bits(e["mask"])},
                  "newest": e["newest"], "commits": e["commits"], "dropped": e["dropped"]}
            for sid, e in result.items()}


def held_by(commit: dict) -> list[str]:
    """The origin branches that hold an off-trunk commit of read_branches (named only when asked: a commit can be
    on thousands of branches)."""
    return sorted(commit["names"][i].removeprefix("refs/remotes/origin/") for i in set_bits(commit["mask"]))


def flow_masks(graph: dict, on_trunk: set, tips: list[tuple[int, str]]) -> dict[str, int]:
    """commit -> OR of the bits of the tips that reach it, for the commits off the trunk: one pass, children
    before parents (a commit waits until all its children have passed their bits down)."""
    masks: dict[str, int] = {}
    for bit, tip in tips:
        if tip not in on_trunk:
            masks[tip] = masks.get(tip, 0) | bit
    waiting: dict[str, int] = {}
    stack, seen = list(masks), set(masks)
    while stack:  # the off-trunk commits and, for each, how many children it has among them
        for parent in graph.get(stack.pop(), ()):
            if parent not in on_trunk:
                waiting[parent] = waiting.get(parent, 0) + 1
                if parent not in seen:
                    seen.add(parent)
                    stack.append(parent)
    ready = [c for c in masks if c not in waiting]
    while ready:
        sha = ready.pop()
        for parent in graph.get(sha, ()):
            if parent in on_trunk:
                continue
            masks[parent] = masks.get(parent, 0) | masks[sha]
            waiting[parent] -= 1
            if not waiting[parent]:
                ready.append(parent)
    return masks


def set_bits(mask: int) -> list[int]:
    """Indexes of the bits set in `mask`."""
    bits = []
    while mask:
        low = mask & -mask
        bits.append(low.bit_length() - 1)
        mask ^= low
    return bits


# ── the parent graph, in O(commits) ──

def first_reach(graph: dict, tips: list[str]) -> dict[str, int]:
    """commit -> index of the first tip (in the given order) that reaches it; each commit is visited once."""
    first: dict[str, int] = {}
    for i, tip in enumerate(tips):
        stack = [tip]
        while stack:
            sha = stack.pop()
            if sha not in first:
                first[sha] = i
                stack.extend(graph.get(sha, ()))
    return first


def first_parent_chain(graph: dict, tip: str) -> list[str]:
    """The trunk's first-parent commits, newest first."""
    chain = []
    while tip in graph and tip not in chain[-1:]:
        chain.append(tip)
        tip = graph[tip][0] if graph[tip] else ""
    return chain


def version_key(tag: str) -> tuple | None:
    """Sort key of a `v<N>(.<N>)*` or `-rc.<N>` tag (the rc sorts before its final), None for any other tag."""
    m = VERSION_TAG.fullmatch(tag)
    if not m:
        return None
    parts = [int(p) for p in m.group(1).split(".")]
    while parts and parts[-1] == 0:
        parts.pop()
    return (tuple(parts), 0, int(m.group(2))) if m.group(2) else (tuple(parts), 1, 0)


def version_tags(refs: dict[str, str]) -> list[tuple[tuple, str, str]]:
    """(key, name, commit) of the `v*` tags that are versions or release candidates, in version order."""
    tags = [(version_key(name[10:]), name[10:], sha) for name, sha in refs.items() if name.startswith("refs/tags/")]
    return sorted(t for t in tags if t[0])


def tag_containment(graph: dict, refs: dict[str, str]) -> tuple[dict, dict]:
    """(commit -> first final tag, commit -> first rc tag) in version order."""
    tags = version_tags(refs)
    result = []
    for final in (True, False):
        chosen = [(name, sha) for key, name, sha in tags if (key[1] == 1) == final]
        reach = first_reach(graph, [sha for _, sha in chosen])
        result.append({c: chosen[i][0] for c, i in reach.items()})
    return result[0], result[1]


def arrivals(graph: dict, trunk_sha: str) -> tuple[dict, dict]:
    """(commit -> the first-parent trunk commit that brought it, first-parent commit -> its position, oldest 0)."""
    oldest_first = list(reversed(first_parent_chain(graph, trunk_sha)))
    arrival = {c: oldest_first[i] for c, i in first_reach(graph, oldest_first).items()}
    return arrival, {c: i for i, c in enumerate(oldest_first)}


# ── the states ──

def brought_by(graph: dict, merge: str) -> list[str]:
    """What reverting `merge` reverts: the commits reachable from it and not from its first parent (just the
    commit itself when it is not a merge)."""
    parents = graph.get(merge, ())
    if len(parents) < 2:
        return [merge]
    held = set(first_reach(graph, [parents[0]]))
    stack, found = [merge], set()
    while stack:
        sha = stack.pop()
        if sha not in held and sha not in found:
            found.add(sha)
            stack.extend(graph.get(sha, ()))
    return sorted(found)


def revert_status(log: list[dict], graph: dict) -> dict[str, bool]:
    """sha -> reverted. A revert on the trunk counts unless it is itself reverted (children come first).
    Reverting a merge reverts what the merge brought, wherever the merge sits."""
    reverters: dict[str, list[str]] = {}
    for c in log:
        for target in c["reverts"]:
            for sha in brought_by(graph, target):
                reverters.setdefault(sha, []).append(c["sha"])
    status: dict[str, bool] = {}
    for c in log:
        status[c["sha"]] = any(not status.get(r, False) for r in reverters.get(c["sha"], ()))
    return status


def story_commits(log: list[dict], reverted: dict, arrival: dict, order: dict) -> tuple[dict, set]:
    """({id: its oldest Story: commit not reverted}, {ids whose Story: commits are all reverted})."""
    live: dict[str, tuple] = {}
    seen: set[str] = set()
    for c in log:
        for sid in c["story"]:
            seen.add(sid)
            if not reverted[c["sha"]]:
                key = (order[arrival[c["sha"]]], c["ct"], c["sha"])
                if sid not in live or key < live[sid]:
                    live[sid] = key
    return {sid: key[2] for sid, key in live.items()}, seen - set(live)


def new_story(story: dict) -> dict:
    """The JSON record of a story before its state is known."""
    return {"id": story["id"], "title": story["title"], "epic": story["epic"], "wave": story["wave"],
            "state": "defined", "since": None, "since_exact": False, "commit": None, "convoy": None,
            "version": None, "candidate": None, "environments": dict.fromkeys(ENVIRONMENTS),
            "reconstructed": False, "reconstructed_by": None, "correction": None, "reverted": False, "branches": [], "attempts": [],
            "swarm": [], "signals": [], "reason": None, "path": story["path"], "arrival": None, "as_of": None,
            "delivered": None, "workers": []}


def mark_unknown(records: list[dict], reason: str) -> None:
    for r in records:
        r["state"], r["reason"] = "unknown", reason


def on_trunk_facts(rec: dict, sha: str, arrival: dict, ct: dict, tags: tuple, deploys: dict) -> None:
    """Fill what a Story: commit on the trunk gives: its approximate date, the first final tag, the deploys."""
    rec.update(commit=sha, arrival=arrival[sha], since=iso(ct[arrival[sha]]), since_exact=False, version=tags[0].get(sha),
               candidate=tags[1].get(sha), state="on-trunk")
    for env, (head, reach) in deploys.items():
        if sha in reach:
            rec["environments"][env] = head
    if rec["environments"]["production"]:
        rec["state"] = "in-production"
    elif rec["environments"]["staging"]:
        rec["state"] = "in-staging"
    elif rec["version"]:
        rec["state"] = "in-version"


def settle_dependencies(stories: list[dict], records: dict, unreadable: list[str]) -> None:
    """Unreadable stories are unknown, and so is whatever depends on them, through any chain and in any id
    order (a walk from them over the dependents). While a story file is unreadable, a dependency id with no
    record may be the one it carries: unknown, not unmet. Every other story without a Story: commit is
    ready when each dependency has one, else defined."""
    dependents: dict[str, list[str]] = {}
    for story in stories:
        for d in story["depends_on"]:
            dependents.setdefault(d, []).append(story["id"])
    queue = []
    for story in stories:
        if story.get("unreadable"):
            mark_unknown([records[story["id"]]], f"the story file {story['path']} cannot be read from the trunk's tree")
            queue.append(story["id"])
    files = ", ".join(unreadable)
    for story in stories:
        rec = records[story["id"]]
        if unreadable and rec["state"] != "unknown" and not rec["commit"] \
                and any(d not in records for d in story["depends_on"]):
            mark_unknown([rec], f"a dependency has no readable story and may be in an unreadable file ({files})")
            queue.append(story["id"])
    while queue:
        sid = queue.pop()
        for dep in dependents.get(sid, ()):
            rec = records[dep]
            if rec["state"] != "unknown" and not rec["commit"]:
                mark_unknown([rec], f"it depends on {sid}, which is unknown")
                queue.append(dep)
    for story in stories:
        rec = records[story["id"]]
        if rec["state"] != "unknown" and not rec["commit"]:
            ready = all(d in records and records[d]["commit"] for d in story["depends_on"])
            rec["state"] = "ready" if ready else "defined"


def deploy_heads(graph: dict, refs: dict) -> dict:
    """environment -> (deploy head or None, the commits it contains)."""
    heads = {env: refs.get(f"refs/remotes/origin/deploy/{env}") for env in ENVIRONMENTS}
    return {env: (head, set(first_reach(graph, [head])) if head else set()) for env, head in heads.items()}


def compute_states(stories: list[dict], unreadable: list[str], log: list[dict], graph: dict, refs: dict,
                   arrivals_: tuple, branches: dict, stale_days: float, now: float,
                   corrections: dict | None = None, trunk: str = "") -> list[dict]:
    """The record of every story, from the facts. `corrections`: the active rows and the reverted map
    (corrections_facts); a story with no live Story: commit is reconstructed from its oldest active row whose
    commit is not reverted (INV-005)."""
    arrival, order = arrivals_
    ct = {c["sha"]: c["ct"] for c in log}
    tags, deploys = tag_containment(graph, refs), deploy_heads(graph, refs)
    reverted = revert_status(log, graph)
    commits, all_reverted = story_commits(log, reverted, arrival, order)
    corrections = corrections or {"active": [], "unreadable": None}
    rows: dict[str, list[dict]] = {}
    for row in corrections["active"]:
        rows.setdefault(row["story"], []).append(row)
    records = {s["id"]: new_story(s) for s in stories}
    trunk_dropped: dict[str, list[dict]] = {}  # built once: a scan of the log per story grows as stories x commits
    for c in log:
        for sid in set(trailer_ids(c["trailers"], "Dropped")):
            trunk_dropped.setdefault(sid, []).append(c)
    for sid, rec in records.items():
        rec["reverted"] = sid in all_reverted
        if sid in commits:
            on_trunk_facts(rec, commits[sid], arrival, ct, tags, deploys)
        elif sid in rows:
            live = [r for r in rows[sid] if not reverted.get(r["commit"], False)]
            if live:
                row = min(live, key=lambda r: (order[arrival[r["commit"]]], ct[r["commit"]], r["commit"]))
                on_trunk_facts(rec, row["commit"], arrival, ct, tags, deploys)
                rec["reconstructed"], rec["reverted"] = True, False
                rec["correction"] = {k: row[k] for k in ("kind", "commit", "evidence", "approver", "date")}
                rec["reconstructed_by"] = "delegated" if is_delegated(row["approver"]) else "person"
            else:
                rec["reverted"] = True
        rec["branches"] = sorted(branches[sid]["branches"]) if sid in branches else []
        rec["attempts"] = attempts_of(sid, branches.get(sid), trunk_dropped, trunk)
    if corrections["unreadable"]:
        for rec in records.values():
            if not rec["commit"]:
                mark_unknown([rec], corrections["unreadable"])
    settle_dependencies(stories, records, unreadable)
    for sid, rec in records.items():
        if branches.get(sid, {}).get("branches") and rec["state"] in ("defined", "ready"):
            rec["state"] = "in-progress"
            if now - branches[sid]["newest"] > stale_days * 86400:
                rec["signals"] = ["stale"]
    return list(records.values())


def attempts_of(sid: str, entry: dict | None, trunk_dropped: dict, trunk: str) -> list[dict]:
    """The story's abandoned attempts: `Dropped: <ID>` commits on any origin branch (the trunk too), oldest first,
    with the branches that hold them and the reason (the commit's body, else its subject)."""
    found = [(c, held_by(c)) for c in (entry or {}).get("dropped", [])]
    found += [(c, [trunk]) for c in trunk_dropped.get(sid, ())]
    attempts = []
    for c, held in sorted(found, key=lambda x: (x[0]["ct"], x[0]["sha"])):
        subject, body = split_message(c["message"], c["trailers"])
        attempts.append({"commit": c["sha"], "branches": list(held), "date": iso(c["ct"]),
                         "reason": "\n".join(body).strip() or subject})
    return attempts


def unattributed(cfg: dict, log: list[dict], graph: dict, arrival_of: dict, corrected: set = frozenset()) -> dict:
    """Trunk commits after `since` with no Story:/Part-of:/No-story:, nor a merge that brought them with one, nor
    an active correction row naming them."""
    since = cfg["since"]
    base = {"since": since, "commits": 0, "ratio": 0.0}
    if since is None:
        return base
    matches = [s for s in graph if s.startswith(since.lower())]
    if len(matches) != 1:
        return base
    held = set(first_reach(graph, [matches[0]]))
    in_range = [c for c in log if c["sha"] not in held]
    covered = attributed_in_range(log, in_range, graph, arrival_of, held, corrected)
    loose = sum(1 for c in in_range if c["sha"] not in covered)
    return {**base, "commits": loose, "ratio": loose / len(in_range) if in_range else 0.0}


def reach_until(graph: dict, tips, stop: set) -> set:
    """The commits reachable from `tips` that are not in `stop` (the walk does not cross them)."""
    stack, found = list(tips), set()
    while stack:
        sha = stack.pop()
        if sha not in stop and sha not in found:
            found.add(sha)
            stack.extend(graph.get(sha, ()))
    return found


def attributed_in_range(log: list[dict], in_range: list[dict], graph: dict, arrival_of: dict, held: set,
                        corrected: set = frozenset()) -> set:
    """The commits of `in_range` that are attributed (docs/ledger.md, "Trailers"): by their own Story:/Part-of:/
    No-story: (or an active correction row naming them, `corrected`), by a merge with one that brings them (the
    first-parent merge that brought them, or a merge nested in a branch: reachable from its other parents, not
    from its first), or, for a merge with none, by every non-merge commit it brings in (commits before `since`
    left out) being attributed so; a merge that brings nothing new is attributed."""
    own = {c["sha"] for c in in_range if c["attributed"] or c["sha"] in corrected}
    base = {c["sha"] for c in in_range if c["sha"] in own or arrival_of.get(c["sha"]) in own}
    for c in in_range:
        if c["sha"] in own and len(c["parents"]) > 1 and arrival_of.get(c["sha"]) != c["sha"]:
            mainline = reach_until(graph, c["parents"][:1], held)
            base |= reach_until(graph, c["parents"][1:], held | mainline)
    covered = set(base)
    for c in in_range:
        if c["sha"] in base or len(c["parents"]) < 2:
            continue
        mainline = reach_until(graph, c["parents"][:1], held)
        brought = reach_until(graph, c["parents"][1:], held | mainline)
        if all(sha in base for sha in brought if len(graph.get(sha, ())) < 2):
            covered.add(c["sha"])
    return covered


def ledger_facts(state: dict) -> dict:
    """Everything `--json` prints (schema 1): reads git, raises LedgerError when a fact cannot be read."""
    return read_all(state)["facts"]


def read_all(state: dict, rules_sha: str | None = None, show: str | None = None) -> dict:
    """The facts and what they were computed from (for the commands that propose or accept corrections):
    facts, and with a complete history also stories, log, graph, placed (arrivals), corrections, records."""
    cfg = read_config(state)
    trunk = trunk_name(state)
    shallow = git_read(["rev-parse", "--is-shallow-repository"]).decode().strip() == "true"
    check_trunk(trunk)
    refs = read_refs(trunk, cfg["snapshot"])
    trunk_sha = resolve_trunk(trunk, refs)
    tree = read_tree(trunk_sha)
    stories, unreadable = read_stories(trunk_sha, cfg, tree)
    # The rules the committed tree holds ([ledger.approval], critical.toml, the review files): the trunk's, or with
    # `check --rules-ref` (LEDGER-013) another commit's, so a tree under judgment never relaxes its own rules.
    extra = read_trunk_files(rules_sha, read_tree(rules_sha), True) if rules_sha else read_trunk_files(trunk_sha, tree)
    reviews = {run: parse_review(data, run) for run, data in extra["reviews"].items()}
    tags = [sha for _, _, sha in version_tags(refs)]
    remotes = [sha for name, sha in refs.items() if name.startswith("refs/remotes/origin/")]
    graph = read_graph(sorted({trunk_sha, *tags, *remotes}))
    reason = cut_reason(graph, shallow)
    facts = {"schema": 1, "trunk": trunk, "trunk_sha": trunk_sha, "history": "incomplete" if reason else "complete",
             "stories": [], "unattributed": {"since": cfg["since"], "commits": 0, "ratio": 0.0}, "diffs": [],
             "harbor": {"logbook": None, "skipped": 0, "error": None}, "swarm": {"error": None}}
    if reason:
        level = "error" if os.environ.get("CI", "").lower() not in ("", "0", "false") else "warning"
        view = snapshot_view(cfg, trunk, trunk_sha, refs, graph, stories, tree)
        if view is not None:  # LEDGER-011: the CI's snapshot answers, as of its trunk commit, and says so
            facts.update(history=f"snapshot:{view['sha']}", stories=view["stories"])
            facts["diffs"].append({"level": level, "code": "HISTORY_INCOMPLETE",
                                   "detail": f"{reason}; read from the snapshot of {short(view['sha'])} ({cfg['snapshot']})"})
            facts["diffs"] += view["diffs"]
            return {"facts": facts, "reason": reason, "snapshot": view}
        facts["stories"] = [new_story(s) for s in stories]
        mark_unknown(facts["stories"], reason)
        facts["diffs"].append({"level": level, "code": "HISTORY_INCOMPLETE", "detail": reason})
        return {"facts": facts, "reason": reason}
    log = read_trunk_log(trunk_sha)
    placed = arrivals(graph, trunk_sha)
    # A story's touches and dimensions decide its critical flag: with --rules-ref, as <rev> has them (a story <rev>
    # lacks has no record there, so it counts as critical).
    judged = read_stories(rules_sha, cfg)[0] if rules_sha else stories
    delegation = {"reviews": reviews, "stories": {s["id"]: s for s in judged if not s.get("unreadable")},
                  "areas": critical_areas(extra["critical"]), "approval": approval_config(extra["state"]),
                  "rules_reach": set(read_graph([rules_sha])) if rules_sha else None, "rules_sha": rules_sha}
    corrections = corrections_facts(trunk_sha, {s["id"] for s in stories if not s.get("unreadable")} if not unreadable
                                    else None, set(placed[0]), graph, delegation)
    if rules_sha:  # corrections are rules too: a row counts only when <rev>'s own file holds it, identical
        corrections = {**corrections, "active": held_rows(corrections["active"], extra["corrections"])}
    branches = read_branches(trunk_sha, refs, graph, set(placed[0]), cfg["snapshot"])
    facts["stories"] = compute_states(stories, unreadable, log, graph, refs, placed, branches,
                                      cfg["stale_days"], time.time(), corrections, trunk)
    apply_moves(facts["stories"], snapshot_moves(refs), graph)
    book = read_logbook(refs)
    apply_logbook({r["id"]: r for r in facts["stories"]}, book, refs, log, placed)
    facts["harbor"] = {"logbook": book["head"], "skipped": book["skipped"], "error": book["error"]}
    # `show <ID>` asks for the authors of the story's commits in the same git call as the swarm's (HARN-022): a
    # superset of what why_of lists (every id equal to it but for case, as story_named reads it).
    asked = set()
    if show is not None:
        same = lambda ids: any(i.casefold() == show.casefold() for i in ids)  # noqa: E731
        asked = {c["sha"] for c in log if same(c["story"] + c["part_of"])}
        asked |= {c["sha"] for sid, entry in branches.items() if same([sid]) for c in entry["commits"]}
    authors: dict = {}
    facts["swarm"] = {"error": apply_swarm({r["id"]: r for r in facts["stories"]}, branches, log, graph, placed,
                                           refs, book, asked, authors)}
    facts["unattributed"] = unattributed(cfg, log, graph, placed[0], corrected(corrections))
    facts["diffs"] += corrections["diffs"]
    records = {r["id"]: r for r in facts["stories"]}
    facts["diffs"] += pending_reviews(reviews, records)
    return {"facts": facts, "reason": None, "cfg": cfg, "trunk_sha": trunk_sha, "tip": trunk_sha, "trunk": trunk,
            "unverified": unverified_prefixes(state), "stories": stories, "log": log,
            "graph": graph, "placed": placed, "branches": branches, "tree": tree, "refs": refs, "unreadable": unreadable, "corrections": corrections, "records": records, "reviews": reviews,
            "approval": approval_config(extra["state"]), "areas": delegation["areas"], "delegation": delegation,
            "harbor": book, "risky": extra["risky"], "authors": authors}


# ── Harbor's logbook (LEDGER-013) ──
# Harbor keeps what is under way in the orphan branch harbor/log, written only by harbor.py (its docs/design.md has the
# schemas). The ledger reads it as data, with git, never by running Harbor, and never writes it. What it says only
# raises a story that is not on the trunk (in-progress, delivered) and names the convoy, and the exact time, of one
# that is; it never adds a difference, so no logbook content changes what `check` or the exit codes say. A file that
# is not what Harbor writes is left out (`harbor.skipped`); a logbook git cannot read is none (`harbor.error`).

LOGBOOK = "refs/remotes/origin/harbor/log"
LOGBOOK_FILE_BYTES = 1 << 20   # a larger file is no logbook file Harbor writes: left out, never read whole
LOGBOOK_FILES = 20000          # at most this many files of each kind are read
LOGBOOK_BYTES = 32 << 20       # and at most this many bytes of them in all: the session start reads the logbook
OPEN_CONVOY = ("assembling", "waiting", "ready", "verifying")
CONVOY_STATES = (*OPEN_CONVOY, "sailed", "aborted")
CONVOY_PATH = re.compile(r"harbor/convoys/([1-9][0-9]{0,8})\.toml")
WORKER_PATH = re.compile(r"harbor/workers/[^/]+/[^/]+/[^/]+\.toml")
RUN_PATH = re.compile(r"harbor/(?:runs|seals)/([0-9a-f]{40}|[0-9a-f]{64})\.toml")
MAIN_PATH = "harbor/main.toml"
CONVOY_CAUSE = re.compile(r"convoy ([1-9][0-9]{0,8})")
CONVOY_VALUE = re.compile(r"#?([1-9][0-9]{0,8})")
LOGBOOK_TEXT = 300             # longest text kept from a logbook value (an event's detail, a branch)


def is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def logbook_text(value, limit: int = LOGBOOK_TEXT) -> str | None:
    """A logbook string, cut to `limit` characters; None for anything else."""
    return value[:limit] if isinstance(value, str) else None


def logbook_toml(content: bytes) -> dict | None:
    """A logbook file's table; None when it is not UTF-8 TOML (whatever is wrong with it: never a crash)."""
    try:
        data = tomllib.loads(content.decode("utf-8"))
    except Exception:  # noqa: BLE001 - not UTF-8, not TOML, nested too deep: not a file Harbor wrote
        return None
    return data if isinstance(data, dict) else None


def parse_convoy(number: int, data: dict) -> dict | None:
    """harbor/convoys/<n>.toml: its number (the file's), state, vessels (branch, full head, story), sail and events."""
    if "number" in data and not (is_int(data["number"]) and data["number"] == number):
        return None
    if data.get("state") not in CONVOY_STATES:
        return None
    vessels = []
    for v in data.get("vessels") if isinstance(data.get("vessels"), list) else []:
        if isinstance(v, dict) and isinstance(v.get("branch"), str) and isinstance(v.get("head"), str) \
                and FULL_SHA.fullmatch(v["head"]):
            vessels.append({"branch": v["branch"], "head": v["head"], "story": logbook_text(v.get("story")) or ""})
    sail = data.get("sail") if isinstance(data.get("sail"), dict) else {}
    ends = {k: sail.get(k) for k in ("main_before", "main_after")}
    sail = ends if all(isinstance(x, str) and FULL_SHA.fullmatch(x) for x in ends.values()) else None
    events = []
    for e in data.get("events") if isinstance(data.get("events"), list) else []:
        if isinstance(e, dict):
            events.append({k: logbook_text(e.get(k)) or "" for k in ("at", "by", "what", "detail")})
    return {"number": number, "state": data["state"], "vessels": vessels[:LOGBOOK_FILES], "sail": sail,
            "events": events[-LOGBOOK_FILES:]}


def parse_worker(data: dict) -> dict | None:
    """harbor/workers/<account>/<host>/<session>.toml: id, state and the story it took (HRB-2, optional)."""
    wid, state = logbook_text(data.get("id")), data.get("state")
    if not wid or not isinstance(state, str):
        return None
    return {"id": wid, "state": state, "story": logbook_text(data.get("story")) or ""}


def parse_moves_of_main(data: dict) -> list[dict]:
    """harbor/main.toml's moves of the trunk: from, to (full shas), seen (ISO 8601, UTC) and cause."""
    moves = []
    for m in data.get("moves") if isinstance(data.get("moves"), list) else []:
        if isinstance(m, dict) and all(isinstance(m.get(k), str) and FULL_SHA.fullmatch(m[k]) for k in ("from", "to")) \
                and isinstance(m.get("seen"), str) and ISO_TIME.fullmatch(m["seen"]) and isinstance(m.get("cause"), str):
            moves.append({"from": m["from"], "to": m["to"], "seen": m["seen"], "cause": m["cause"]})
    return moves[-LOGBOOK_FILES:]


def logbook_entries(head: str) -> dict[str, tuple[str, int]]:
    """path -> (blob, size) of every file of the logbook's tree under harbor/ (one `ls-tree`)."""
    out = git_read(["ls-tree", "-r", "-l", "-z", head, "--", "harbor/"])
    entries = {}
    for entry in out.decode("utf-8", errors="replace").split("\0"):
        meta, tab, path = entry.partition("\t")
        fields = meta.split()
        if tab and len(fields) == 4 and fields[1] == "blob" and fields[3].isdigit():
            entries[path] = (fields[2], int(fields[3]))
    return entries


def read_logbook_files(entries: dict, paths: list[str]) -> tuple[dict[str, bytes], int]:
    """Contents of these logbook files (one `cat-file`), and how many were left out: larger than LOGBOOK_FILE_BYTES,
    past LOGBOOK_FILES or LOGBOOK_BYTES, or not in this clone (a partial clone that never fetched them)."""
    chosen, total = [], 0
    for p in paths:
        size = entries[p][1]
        if size <= LOGBOOK_FILE_BYTES and total + size <= LOGBOOK_BYTES and len(chosen) < LOGBOOK_FILES:
            chosen.append(p)
            total += size
    blobs = cat_blobs([entries[p][0] for p in chosen])
    files = {p: blobs[entries[p][0]] for p in chosen if blobs.get(entries[p][0]) is not None}
    return files, len(paths) - len(files)


def read_logbook(refs: dict) -> dict:
    """What the ledger reads of origin/harbor/log: convoys by number, workers, the trunk's moves, and the runs (seals)
    of the vessels' heads. Never raises: an unreadable logbook is an empty one with `error`."""
    book = {"head": refs.get(LOGBOOK), "convoys": {}, "workers": [], "moves": [], "runs": {}, "skipped": 0,
            "error": None}
    if not book["head"]:
        return book
    try:
        entries = logbook_entries(book["head"])
        first = sorted(p for p in entries if p == MAIN_PATH or CONVOY_PATH.fullmatch(p) or WORKER_PATH.fullmatch(p))
        files, skipped = read_logbook_files(entries, first)
        convoys, workers, moves = {}, [], []
        for path, content in files.items():
            data = logbook_toml(content)
            m = CONVOY_PATH.fullmatch(path)
            parsed = None if data is None else parse_convoy(int(m.group(1)), data) if m \
                else parse_worker(data) if WORKER_PATH.fullmatch(path) else data
            if parsed is None:
                skipped += 1
            elif m:
                convoys[parsed["number"]] = parsed
            elif path == MAIN_PATH:
                moves = parse_moves_of_main(parsed)
            else:
                workers.append(parsed)
        heads = {v["head"] for c in convoys.values() if c["state"] in OPEN_CONVOY for v in c["vessels"]}
        runs_paths = sorted(p for p in entries if (r := RUN_PATH.fullmatch(p)) and r.group(1) in heads)
        run_files, run_skipped = read_logbook_files(entries, runs_paths)
        runs: dict[str, dict] = {}
        for path in sorted(run_files):  # runs/ before seals/: Harbor reads runs/ first (run_of)
            sha = RUN_PATH.fullmatch(path).group(1)
            data = logbook_toml(run_files[path])
            if data is None or not is_int(data.get("exit")) or data.get("head", sha) != sha:
                run_skipped += 1
            elif sha not in runs:
                runs[sha] = {"exit": data["exit"]}
        book.update(convoys=convoys, workers=sorted(workers, key=lambda w: w["id"]), moves=moves, runs=runs,
                    skipped=skipped + run_skipped)
    except Exception as e:  # noqa: BLE001 - the logbook is data anyone who can push writes: never a crash, never a verdict
        book.update(convoys={}, workers=[], moves=[], runs={}, error=" ".join(str(e).split())[:200] or type(e).__name__)
    return book


def harbor_ids(value: str, ids: dict[str, str]) -> list[str]:
    """The trunk's story ids a logbook `story` names ("A, B"; Harbor compares ids without case)."""
    return sorted({ids[p.strip().casefold()] for p in value.split(",") if p.strip().casefold() in ids})


def convoy_of_merge(c: dict | None) -> int | None:
    """The convoy a first-parent merge of the trunk carries: its `Convoy: <n>` trailer (one number), else a merge of
    convoy/<n>."""
    if not c or len(c["parents"]) < 2:
        return None
    numbers = {int(m.group(1)) for v in trailer_values(c["trailers"], "Convoy") if (m := CONVOY_VALUE.fullmatch(v.strip()))}
    if len(numbers) == 1:
        return numbers.pop()
    branch = merged_branch(c["message"].split("\n", 1)[0])
    m = TRAIN_BRANCH.match(branch) if branch and not numbers else None
    n = CONVOY_VALUE.fullmatch(m.group(1)) if m and branch.lower().startswith(("convoy", "origin/convoy")) else None
    return int(n.group(1)) if n else None


def apply_logbook(records: dict[str, dict], book: dict, refs: dict, log: list[dict], placed: tuple) -> None:
    """What the logbook adds to the records (docs/ledger.md, "States"): an active worker holding a story makes it
    in-progress (from defined or ready); a vessel sealed on its exact head (a green run of that head, and its origin
    branch, when there is one, still at it) in an open convoy makes it delivered with that convoy (the highest
    number when several); an on-trunk story's convoy is the `Convoy: <n>` of the merge that brought it, else the
    sailed convoy or the convoy's move of the trunk that holds its arrival, whose `seen` is then its exact time.
    INV-005: the logbook never puts a story on the trunk nor takes one off it, and never touches an unknown one."""
    ids = {sid.casefold(): sid for sid in records}
    for w in book["workers"]:
        if w["state"] == "active":
            for sid in harbor_ids(w["story"], ids):
                records[sid]["workers"].append(w["id"])
    for rec in records.values():
        rec["workers"] = sorted(set(rec["workers"]))
        if rec["workers"] and rec["state"] in ("defined", "ready"):
            rec["state"] = "in-progress"
    for n in sorted(book["convoys"]):
        c = book["convoys"][n]
        if c["state"] not in OPEN_CONVOY:
            continue
        for v in c["vessels"]:
            tip = refs.get(f"refs/remotes/origin/{v['branch']}")
            run = book["runs"].get(v["head"])
            if run is None or run["exit"] != 0 or (tip is not None and tip != v["head"]):
                continue
            for sid in harbor_ids(v["story"], ids):
                rec = records[sid]
                if rec["state"] in ("defined", "ready", "in-progress", "delivered"):
                    rec.update(state="delivered", convoy=n, delivered={"convoy": n, "convoy_state": c["state"],
                                                                       "branch": v["branch"], "head": v["head"]})
    places = convoy_places(book, log, placed)
    position = places["position"]
    for rec in records.values():
        at = position.get(rec.get("arrival") or "")
        if not rec["commit"] or rec["state"] == "unknown" or at is None:
            continue
        move = convoy_move(places, at)
        if rec["convoy"] is None:
            rec["convoy"] = convoy_sailed(places, rec["arrival"])
        if move is not None and not rec["since_exact"]:
            rec["since"], rec["since_exact"] = move[0]["seen"], True


def convoy_places(book: dict, log: list[dict], placed: tuple) -> dict:
    """What says which convoy brought a trunk commit: the trunk's first-parent positions, the merges by sha, the
    sailed convoys whose `[sail]` range the trunk holds, and main.toml's convoy moves it holds."""
    position = placed[1]
    sails = [(n, c["sail"]) for n, c in sorted(book["convoys"].items()) if c["state"] == "sailed" and c["sail"]
             and c["sail"]["main_before"] in position and c["sail"]["main_after"] in position]
    moves = [(m, int(k.group(1))) for m in book["moves"] if (k := CONVOY_CAUSE.fullmatch(m["cause"]))
             and m["from"] in position and m["to"] in position]
    return {"position": position, "by_sha": {c["sha"]: c for c in log}, "sails": sails, "moves": moves}


def convoy_move(places: dict, at: int) -> tuple | None:
    """The first convoy move of main.toml whose from..to holds the first-parent position `at`: (move, number)."""
    position = places["position"]
    return next(((m, n) for m, n in places["moves"] if position[m["from"]] < at <= position[m["to"]]), None)


def convoy_sailed(places: dict, arrival: str) -> int | None:
    """The convoy that brought the trunk commit whose first-parent arrival is `arrival`: the `Convoy: <n>` of that
    merge, else the sailed convoy whose range holds it, else the convoy move that holds it."""
    position = places["position"]
    at = position.get(arrival)
    if at is None:
        return None
    move = convoy_move(places, at)
    return convoy_of_merge(places["by_sha"].get(arrival)) \
        or next((n for n, s in places["sails"] if position[s["main_before"]] < at <= position[s["main_after"]]), None) \
        or (move[1] if move else None)


# ── Swarm's deliveries (LEDGER-014) ──
# The ledger never reads the swarm repo (another repo, other credentials, network in every hook). A swarm helper
# delivers a branch swarm/<task> in this repo, and its commits carry `Part-of: <ID>` and `Swarm-Task: <task>` (the
# helper's prompt or the swarm runner writes them, SWM-2). What they say is data anyone who can push writes: it adds
# information to a story's record (its `swarm` list) and never a difference, an attribution or a state. A story with a
# delivery not yet integrated is in-progress by its Part-of:, as on any branch (LEDGER-003), not because of Swarm.

SWARM_BRANCH = "refs/remotes/origin/swarm/"
SWARM_TASK = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")   # a task id that is one: no slash, no control character
SWARM_AUTHOR = 200             # longest author name kept
SWARM_MERGES = 2000            # at most this many attributing merges are walked to find a delivery's story
SWARM_STATES = ("in-progress", "on-trunk", "reverted")
SWARM_UNSAFE = Screen()   # in a name: control and format characters, tab and newline too (ESC-348, HARN-022)
SWARM_KEYS = {"task", "state", "branch", "head", "commits", "authors", "convoy"}


def swarm_task(trailers: list[tuple[str, str]]) -> str | None:
    """The task a commit's `Swarm-Task:` names: exactly one distinct value, a task id; else none."""
    values = {v.strip() for v in trailer_values(trailers, "Swarm-Task")}
    task = values.pop() if len(values) == 1 else None
    return task if task and SWARM_TASK.fullmatch(task) else None


def authors_of(shas: list[str], anchor: str) -> dict[str, str]:
    """commit -> its author's name as recorded (no mailmap: a .mailmap is a file the branch under judgment writes),
    control characters shown as ?, cut to SWARM_AUTHOR. Always one `git log` (with no commit, of `anchor` alone), so
    the number of git calls does not depend on the data."""
    wanted = set(shas)
    out = git_read(["log", "--no-walk=unsorted", "--stdin", "-z", "--no-mailmap", "--format=%H%x00%an"],
                   "".join(f"{sha}\n" for sha in (shas or [anchor])).encode()).decode("utf-8", errors="replace")
    parts = out.split("\0")
    names = {}
    for sha, name in zip(parts[0::2], parts[1::2]):
        sha = sha.strip()
        if sha in wanted:
            names[sha] = SWARM_UNSAFE.sub("?", name)[:SWARM_AUTHOR]
    return names


def placed_anchor(placed: tuple) -> str:
    """A trunk commit (the oldest of its first-parent chain), for authors_of's one call when there is nothing to ask."""
    return next(iter(placed[1]))


def attributing_merges(graph: dict, log: list[dict], arrival_of: dict, wanted: list[str]) -> dict[str, set[str]]:
    """commit -> the story ids of the trunk merges that bring it (their trailers cover it: docs/ledger.md, "Trailers").
    Only the commits of its own arrival can bring a commit, so everything stays inside one arrival's group; at most
    SWARM_MERGES merges are asked. One pass per group (HARN-022): each commit of the group gets the set of wanted
    commits it reaches (a bit mask, parents before children), and a merge brings what its other parents reach and its
    first parent does not, so the cost is the group's size, never merges × group."""
    by_sha = {c["sha"]: c for c in log}
    groups: dict[str, set[str]] = {}
    for sha in wanted:
        groups.setdefault(arrival_of[sha], set())
    for sha, a in arrival_of.items():
        if a in groups:
            groups[a].add(sha)
    found: dict[str, set[str]] = {}
    budget = SWARM_MERGES
    for a, group in sorted(groups.items()):
        merges = sorted(m for m in group if len(graph.get(m, ())) > 1 and m in by_sha
                        and (by_sha[m]["story"] or by_sha[m]["part_of"]))
        if not merges:
            continue
        want = sorted({sha for sha in wanted if arrival_of[sha] == a})
        bit = {sha: 1 << i for i, sha in enumerate(want)}
        parents_of = {x: [p for p in graph.get(x, ()) if p in group] for x in group}
        reach: dict[str, int] = {}
        for x in group_order(parents_of):
            mask = bit.get(x, 0)
            for p in parents_of[x]:
                mask |= reach[p]
            reach[x] = mask
        for m in merges:
            if budget <= 0:
                return found
            budget -= 1
            parents = graph[m]
            mainline = reach.get(parents[0], 0) if parents[0] in group else 0
            other = 0
            for p in parents[1:]:
                if p in group:
                    other |= reach[p]
            brought = other & ~mainline
            ids = by_sha[m]["story"] + by_sha[m]["part_of"]
            for i in set_bits(brought):
                found.setdefault(want[i], set()).update(ids)
    return found


def group_order(parents_of: dict[str, list[str]]) -> list[str]:
    """The commits of a group (commit -> its parents inside the group), each after its parents; each visited once."""
    done: set[str] = set()
    out: list[str] = []
    for root in parents_of:
        if root in done:
            continue
        stack = [(root, False)]
        while stack:
            x, finished = stack.pop()
            if finished:
                out.append(x)
                continue
            if x in done:
                continue
            done.add(x)
            stack.append((x, True))
            stack.extend((p, False) for p in parents_of[x] if p not in done)
    return out


def apply_swarm(records: dict[str, dict], branches: dict, log: list[dict], graph: dict, placed: tuple, refs: dict,
                book: dict, asked: set = frozenset(), known: dict | None = None) -> str | None:
    """Fill each story's `swarm` list (docs/ledger.md, "Harbor and Swarm"): a delivery not yet integrated is an origin
    branch swarm/<task> holding commits off the trunk with `Part-of: <ID>` and `Swarm-Task: <task>` (that task, the
    branch's), with its head, and the open convoy whose vessel is that branch sealed on that head; an integrated one is
    the trunk's commits with `Swarm-Task:` that are the story's (their own Story:/Part-of:, else the merges that
    attribute them), by the convoy that brought them (`reverted` once a revert on the trunk undid them). Merges are no
    deliveries. Never raises: whatever is wrong, the lists stay empty and the answer is the error."""
    try:
        for rec in records.values():
            rec["swarm"] = []
        entries: dict[tuple, dict] = {}

        def add(sid: str, task: str, state: str, convoy, branch, head, commit: dict) -> None:
            e = entries.setdefault((sid, task, state, -1 if convoy is None else convoy), {
                "task": task, "state": state, "branch": branch, "head": head, "commits": {}, "convoy": convoy})
            e["commits"][commit["sha"]] = commit["ct"]

        names = {}
        for entry in branches.values():
            for c in entry["commits"]:
                names = names or {n: i for i, n in enumerate(c["names"])}
                break
        open_heads: dict[tuple[str, str], int] = {}
        for n in sorted(book["convoys"]):
            c = book["convoys"][n]
            if c["state"] in OPEN_CONVOY:
                for v in c["vessels"]:
                    run = book["runs"].get(v["head"])
                    if run is not None and run["exit"] == 0:
                        open_heads[(v["branch"], v["head"])] = n
        for sid, entry in sorted(branches.items()):
            if sid not in records:
                continue
            for c in entry["commits"]:
                task = swarm_task(c["trailers"])
                ref = f"{SWARM_BRANCH}{task}"
                if task is None or ref not in names or not c["mask"] >> names[ref] & 1 or len(graph.get(c["sha"], ())) > 1:
                    continue
                branch, head = f"swarm/{task}", refs[ref]
                add(sid, task, "in-progress", open_heads.get((branch, head)), branch, head, c)
        arrival_of = placed[0]
        places = convoy_places(book, log, placed)
        reverted = revert_status(log, graph)
        pieces = [(c, task) for c in log if len(c["parents"]) < 2 and (task := swarm_task(c["trailers"]))]
        via = attributing_merges(graph, log, arrival_of, [c["sha"] for c, _ in pieces
                                                           if not (c["story"] or c["part_of"])])
        for c, task in pieces:
            ids = set(c["story"]) | set(c["part_of"]) or via.get(c["sha"], set())
            for sid in sorted(ids):
                if sid in records:
                    add(sid, task, "reverted" if reverted.get(c["sha"]) else "on-trunk",
                        convoy_sailed(places, arrival_of[c["sha"]]), None, None, c)
        wanted = {sha for e in entries.values() for sha in e["commits"]} | set(asked)
        authors = authors_of(sorted(wanted), placed_anchor(placed))
        if known is not None:  # what `show` reuses: the commits asked and their authors (`asked` and `names`)
            known.update(asked=wanted, names=authors)
        for (sid, *_), e in sorted(entries.items(), key=lambda x: (x[0][0], x[0][1], SWARM_STATES.index(x[0][2]), x[0][3])):
            shas = sorted(e["commits"], key=lambda sha: (e["commits"][sha], sha))
            records[sid]["swarm"].append({**e, "commits": shas,
                                          "authors": sorted({authors[sha] for sha in shas if sha in authors})})
        return None
    except Exception as e:  # noqa: BLE001 - Swarm's trailers are data anyone who can push writes: never a crash
        for rec in records.values():
            rec["swarm"] = []
        return " ".join(str(e).split())[:200] or type(e).__name__


# ── corrections (docs/ledger.md, "Corrections file") ──

def held_rows(active: list[dict], content: bytes | None) -> list[dict]:
    """The active rows that the corrections file `content` (<rev>'s, for `--rules-ref`) holds with the same story,
    commit, kind, evidence, approver and date. A row only the candidate has attributes nothing (and is no error); a
    row <rev> has that the candidate retracted or changed stays out, as without --rules-ref (CORRECTION_EDITED)."""
    rows, why = parse_rows(content) if content is not None else ([], None)
    fields = ("story", "commit", "kind", "evidence", "approver", "date")
    held = {tuple(plain_value(r.get(k)) for k in fields) for r in rows or [] if isinstance(r, dict) and not why}
    return [r for r in active if tuple(r[k] for k in fields) in held]


def toml_str(value: str) -> str:
    """A TOML basic string: JSON's escapes are TOML's, but DEL must be escaped too."""
    return json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007f")


def parse_rows(content: bytes) -> tuple[list | None, str | None]:
    """([[row]] tables of a corrections file, None) or (None, why it cannot be read)."""
    try:
        data = tomllib.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        return None, f"not valid TOML ({' '.join(str(e).split())[:120]})"
    rows = data.get("row", [])
    if not isinstance(rows, list):
        return None, "`row` must be [[row]] tables"
    return rows, None


def plain_value(value):
    """A row's value as text when TOML gave a date (a person may write date = 2026-11-25 unquoted)."""
    return value.isoformat() if hasattr(value, "isoformat") and not isinstance(value, str) else value


def row_key(row) -> str:
    """A row compared as a whole table (INV-008)."""
    if not isinstance(row, dict):
        return json.dumps(row, default=str)
    return json.dumps({k: plain_value(v) for k, v in row.items()}, sort_keys=True, default=str)


def valid_date(text: str) -> bool:
    try:
        datetime.strptime(text, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def row_problem(row, story_ids: set | None, reachable: set, reviews: dict | None = None) -> str | None:
    """Why a row cannot count, or None. `story_ids` None: some story file is unreadable, so any id may exist.
    `reviews`: the delegation context (with_touched): the review files ({run: parsed or None}), the stories, the
    critical areas and the paths each delegated row's commit touches, which back the rows a review approved."""
    if not isinstance(row, dict):
        return "not a table"
    values = {k: plain_value(row.get(k)) for k in ("story", "commit", "kind", "evidence", "approver", "date")}
    missing = [k for k, v in values.items() if not isinstance(v, str) or not v.strip()]
    if missing:
        return f"missing or empty: {', '.join(missing)}"
    if values["kind"] not in KINDS:
        return f"kind {values['kind']!r} is not one of {', '.join(KINDS)}"
    if not FULL_SHA.fullmatch(values["commit"]):
        return f"commit {values['commit']!r} is not a full sha"
    if values["commit"] not in reachable:
        return f"commit {values['commit'][:12]} is not reachable from the trunk"
    if story_ids is not None and values["story"] not in story_ids:
        return f"no story {values['story']}"
    if not ISO_DATE.fullmatch(values["date"]) or not valid_date(values["date"]):
        return f"date {values['date']!r} is not a YYYY-MM-DD date"
    if is_delegated(values["approver"]):
        return delegated_problem(values, reviews or {"reviews": {}}, row_key(row))
    return None


def apply_rows(rows: list, story_ids: set | None, reachable: set, where: str,
               bad: list | None = None, reviews: dict | None = None) -> tuple[list[dict], list[dict]]:
    """(the active rows, normalized, in file order; one CORRECTION_INVALID diff per row that cannot count).
    A retract deactivates the earlier active rows of the same story and commit; one with none is invalid."""
    active, diffs = [], []
    for i, row in enumerate(rows, 1):
        problem = row_problem(row, story_ids, reachable, reviews)
        norm = {k: plain_value(row.get(k)) for k in ("story", "commit", "kind", "evidence", "approver", "date")} \
            if not problem else None
        if norm and norm["kind"] == "retract":
            same = [r for r in active if (r["story"], r["commit"]) == (norm["story"], norm["commit"])]
            if same:
                active = [r for r in active if r not in same]
            else:
                problem = "a retract with no earlier row of the same story and commit"
        elif norm:
            active.append(norm)
        if problem:
            if bad is not None:
                bad.append(i)
            label = f"{row.get('story')} {str(row.get('commit'))[:12]}" if isinstance(row, dict) else "?"
            diffs.append({"level": "error", "code": "CORRECTION_INVALID",
                          "detail": f"{where} row {i} ({label}): {problem}"})
    return active, diffs


def file_versions(trunk_sha: str) -> list[tuple[str, str | None]]:
    """(first-parent trunk commit, the file's blob there or None when it was removed), newest first."""
    out = git_read(["log", "--first-parent", "--format=%x00%H", "--raw", "--no-abbrev", "--no-renames", trunk_sha,
                    "--", f":(literal){CORRECTIONS}"]).decode(errors="replace")
    versions = []
    for chunk in out.split("\0")[1:]:
        lines = chunk.strip("\n").split("\n")
        raw = [line for line in lines[1:] if line.startswith(":")]
        if not raw:
            continue
        fields = raw[-1].split("\t")[0].split()
        versions.append((lines[0].strip(), None if fields[4].startswith("D") else fields[3]))
    return versions


def merge_parent_versions(trunk_sha: str, merges: set[str]) -> list[tuple[str, str]]:
    """(merge, blob) for the file as each parent of a merge reachable from the trunk had it, when the merge changed
    it: a row on the trunk that a merge drops (a "foxtrot" merge, where the old trunk becomes a second parent, even
    nested under another merge) is still seen. One log of every commit that touched the file, each merge against
    each parent."""
    if not merges:
        return []
    out = git_read(["log", "--full-history", "--diff-merges=separate", "--format=%x00%H", "--raw", "--no-abbrev",
                    "--no-renames", trunk_sha, "--", f":(literal){CORRECTIONS}"]).decode(errors="replace")
    found = []
    for chunk in out.split("\0")[1:]:
        lines = chunk.strip("\n").split("\n")
        sha = lines[0].strip()
        if sha not in merges:
            continue
        for line in lines[1:]:
            fields = line.split("\t")[0].split() if line.startswith(":") else []
            if len(fields) >= 5 and not fields[4].startswith("A") and set(fields[2]) != {"0"}:
                found.append((sha, fields[2]))
    return found


def absent_versions(trunk_sha: str) -> set[str]:
    """Blobs of the file's versions this partial clone lacks: one walk that prints `?<sha>` instead of fetching."""
    out = git_read(["rev-list", "--objects", "--missing=print", "--no-object-names", trunk_sha,
                    "--", f":(literal){CORRECTIONS}"])
    return {line[1:] for line in out.decode(errors="replace").splitlines() if line.startswith("?")}


def cat_blobs(shas: list[str]) -> dict[str, bytes | None]:
    """Contents of blobs the clone has, in one `cat-file --batch`; None for one git reports missing."""
    unique = sorted(set(shas))
    if not unique:
        return {}
    out = git_read(["cat-file", "--batch"], "".join(f"{s}\n" for s in unique).encode())
    blobs, pos = {}, 0
    for sha in unique:
        end = out.find(b"\n", pos)
        head = out[pos:end].split() if end >= 0 else []
        if len(head) < 2:
            raise LedgerError("git cat-file gave an unexpected answer")
        if head[1] == b"missing":
            blobs[sha], pos = None, end + 1
            continue
        size = int(head[2])
        blobs[sha], pos = out[end + 1:end + 1 + size], end + 1 + size + 1
    return blobs


def corrections_facts(trunk_sha: str, story_ids: set | None, reachable: set, graph: dict | None = None,
                      reviews: dict | None = None) -> dict:
    """The corrections file as the trunk has it: active rows, diffs (CORRECTION_INVALID, CORRECTION_EDITED,
    CORRECTION_UNCHECKED) and `unreadable` (a reason, when the tip's version is absent from a partial clone).
    Two git calls (three in a partial clone) whatever the number of versions."""
    result = {"active": [], "diffs": [], "unreadable": None}
    versions = file_versions(trunk_sha)
    extra = merge_parent_versions(trunk_sha, {c for c in reachable if len((graph or {}).get(c, ())) > 1})
    if not versions and not extra:
        return result
    versions = versions or [(trunk_sha, None)]  # never on the first-parent chain: the tip has no file
    blobs = [b for _, b in versions if b] + [b for _, b in extra]
    absent = absent_versions(trunk_sha) & set(blobs) if is_partial_clone() else set()
    contents = {**cat_blobs([b for b in blobs if b not in absent]), **dict.fromkeys(absent)}
    tip_commit, tip_blob = versions[0]
    tip_rows: list = []
    if tip_blob is not None:
        if contents.get(tip_blob) is None:
            result["unreadable"] = f"{CORRECTIONS} cannot be read from the trunk's tree (a partial clone lacks it)"
            return result
        rows, why = parse_rows(contents[tip_blob])
        if why:  # no row counts, and every earlier row is gone from what can be read
            result["diffs"].append({"level": "error", "code": "CORRECTION_INVALID", "detail": f"{CORRECTIONS}: {why}"})
        else:
            tip_rows = rows
            if reviews and any(isinstance(r, dict) and is_delegated(r.get("approver")) for r in rows):
                at, seen = versions, contents
                if reviews.get("rules_sha"):  # --rules-ref: a row arrives on <rev>'s own history or not at all
                    at = file_versions(reviews["rules_sha"])
                    seen = {**contents, **cat_blobs([b for _, b in at if b and b not in contents])}
                reviews = {**reviews, "arrival": arrival_facts(rows, at, seen, reviews)}
            result["active"], result["diffs"] = apply_rows(rows, story_ids, reachable, CORRECTIONS,
                                                           reviews=with_touched(reviews, rows, reachable))
    tip_keys = [row_key(row) for row in tip_rows]
    unchecked, reported = 0, set()
    # Oldest first, so a row is named where it first was; then the versions merges' parents had.
    for commit, blob in [*reversed(versions[1:]), *extra]:
        if blob is None:
            continue
        if contents.get(blob) is None:
            unchecked += 1
            continue
        rows, why = parse_rows(contents[blob])
        if why:
            continue
        pos = 0  # each earlier row must still be there, in the same order (a subsequence of the tip)
        for row in rows:
            key = row_key(row)
            nxt = next((j for j in range(pos, len(tip_keys)) if tip_keys[j] == key), None)
            if nxt is not None:
                pos = nxt + 1
                continue
            if key not in reported:
                reported.add(key)
                story, sha = (row.get("story"), str(row.get("commit"))[:12]) if isinstance(row, dict) else ("?", "?")
                result["diffs"].append({
                    "level": "error", "code": "CORRECTION_EDITED",
                    "detail": f"{CORRECTIONS}: the row for {story} at {sha} was on the trunk in {commit[:7]} and "
                              f"{'changed, moved or disappeared' if tip_blob else 'disappeared with the file'} "
                              f"(append-only, INV-008: cancel a row with a retract row)"})
    if unchecked:
        result["diffs"].append({"level": "warning", "code": "CORRECTION_UNCHECKED",
                                "detail": f"{unchecked} earlier version(s) of {CORRECTIONS} are not in this partial "
                                          "clone, so append-only is not checked here (a full clone, as in CI, checks it)"})
    return result


def cat_specs(specs: list[str]) -> dict[str, bytes | None]:
    """Contents of `<commit>:<path>` objects in one `cat-file --batch`; None for one that is missing."""
    unique = sorted(set(specs))
    if not unique:
        return {}
    out = git_read(["cat-file", "--batch"], "".join(f"{s}\n" for s in unique).encode())
    found, pos = {}, 0
    for spec in unique:
        end = out.find(b"\n", pos)
        head = out[pos:end].split() if end >= 0 else []
        if len(head) < 3 or head[1] != b"blob":  # missing, ambiguous or not a file
            found[spec], pos = None, end + 1
            continue
        size = int(head[2])
        found[spec], pos = out[end + 1:end + 1 + size], end + 1 + size + 1
    return found


def arrival_facts(rows: list, versions: list, contents: dict, delegation: dict) -> dict:
    """row_key of each delegated row -> {"areas", "story"}: the critical areas and the story's touches
    and dimensions as the trunk had them at the first-parent commit where the row first appeared, so a later area or
    edit of the story never turns an approved row invalid. Rows not found there keep the tip's view."""
    wanted = {}
    for row in rows:
        if isinstance(row, dict) and is_delegated(row.get("approver")):
            wanted[row_key(row)] = (plain_value(row.get("story")), plain_value(row.get("commit")),
                                    plain_value(row.get("kind")))
    first: dict[str, str] = {}
    for commit, blob in reversed(versions):  # oldest first
        if blob is None or contents.get(blob) is None:
            continue
        parsed, why = parse_rows(contents[blob])
        for row in parsed or []:
            key = row_key(row)
            if key in wanted and key not in first:
                first[key] = commit
    stories = delegation.get("stories", {})
    specs = []
    reach = delegation.get("rules_reach")
    if reach is not None:  # `--rules-ref`: a row that arrived after that commit is judged by its rules, not its own
        first = {key: commit for key, commit in first.items() if commit in reach}
    for key, commit in first.items():
        story = stories.get(wanted[key][0])
        specs += [f"{commit}:{CRITICAL_FILE}"] + ([f"{commit}:{story['path']}"] if story else [])
    blobs = cat_specs(specs)
    facts = {}
    for key, commit in first.items():
        sid = wanted[key][0]
        story = stories.get(sid)
        meta = front_matter(blobs[f"{commit}:{story['path']}"].decode("utf-8", errors="replace"))[0] \
            if story and blobs.get(f"{commit}:{story['path']}") is not None else None
        facts[key] = {"areas": critical_areas(blobs.get(f"{commit}:{CRITICAL_FILE}")),
                              "story": {"touches": text_list(meta.get("touches")),
                                        "dimensions": text_list(meta.get("dimensions"))} if meta is not None else story}
    return facts


# ── proposing and accepting corrections ──

def need_history(ctx: dict) -> None:
    if ctx["reason"]:
        raise LedgerError(f"the trunk's history is incomplete, so nothing can be proposed or accepted: {ctx['reason']}")


def story_file_adds(ctx: dict) -> dict[str, set[str]]:
    """commit -> the story ids whose file it added (a plan commit names the id but does not deliver it)."""
    paths = {s["path"]: s["id"] for s in ctx["stories"]}
    if not paths:
        return {}
    out = git_read(["log", "--format=%x00%H", "--diff-filter=A", "--name-only", "--no-renames", ctx["trunk_sha"],
                    "--", *(f":(literal){p}" for p in sorted(paths))]).decode(errors="replace")
    adds: dict[str, set[str]] = {}
    for chunk in out.split("\0")[1:]:
        lines = [line for line in chunk.split("\n") if line.strip()]
        if lines:
            adds[lines[0].strip()] = {paths[p] for p in lines[1:] if p in paths}
    return adds


def merged_branch(subject: str) -> str | None:
    m = MERGE_BRANCH.match(subject)
    return (m.group(1) or m.group(2)) if m else None


def train_commits(log: list[dict], reverted: dict) -> dict[int, list[str]]:
    """train number -> trunk commits that carry it: a `Convoy: N` trailer, `train N` in the subject, or a merge of
    convoy/N or train/N."""
    trains: dict[int, list[str]] = {}
    for c in log:
        if reverted.get(c["sha"]) or c["reverts"]:
            continue
        subject = c["message"].split("\n", 1)[0]
        numbers = {int(n) for n in CONVOY_TRAILER.findall(c["message"]) + TRAIN_WORD.findall(subject) if len(n) <= 9}
        branch = merged_branch(subject) if len(c["parents"]) > 1 else None
        if branch and (m := TRAIN_BRANCH.match(branch)) and len(m.group(1)) <= 9:
            numbers.add(int(m.group(1)))
        for n in numbers:
            trains.setdefault(n, []).append(c["sha"])
    return trains


def evidence_candidates(path: str, ctx: dict, ids: set, reverted: dict) -> list[tuple[str, str, str, str]]:
    """(story, commit, confidence, evidence) from a train sheet, a BOARD.md or Harbor's imported board: each line
    that names ids and a commit, or ids and a train."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise LedgerError(f"cannot read the evidence file {path} ({e})") from e
    reachable = ctx["placed"][0]
    trains = train_commits(ctx["log"], reverted)
    order, arrival = ctx["placed"][1], ctx["placed"][0]
    ct = {c["sha"]: c["ct"] for c in ctx["log"]}
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        named = [i for i in dict.fromkeys(ID_TOKEN.findall(line)) if i in ids]
        if not named:
            continue
        where = f"{path}:{n}: {' '.join(line.split())[:120]}"
        commit, confidence = None, None
        for word in HEX_WORD.findall(line):
            found = [sha for sha in reachable if sha.startswith(word)] if len(word) < 40 else \
                ([word] if word in reachable else [])
            if len(found) == 1 and not reverted.get(found[0]):
                commit, confidence = found[0], "high"
                break
        if commit is None:
            number = TRAIN_WORD.search(line) or TRAIN_T.search(line)
            cells = [c.strip() for c in line.strip().strip("|").split("|")] if line.strip().startswith("|") else []
            if number is None and cells and (cell := TRAIN_CELL.fullmatch(cells[0])):
                number = cell
            shas = trains.get(int(number.group(1)), []) if number else []
            if shas:
                commit = max(shas, key=lambda sha: (order[arrival[sha]], ct[sha], sha))
                confidence = "medium" if len(shas) == 1 else "low"
                where += f" (train {int(number.group(1))}: {len(shas)} commit(s))"
        if commit:
            out += [(sid, commit, confidence, where) for sid in named]
    return out


def proposals(ctx: dict, sources: list[str]) -> list[dict]:
    """One candidate row per story that is not on the trunk yet: the best of its candidates (confidence, then
    the newest arrival), its evidence naming the others."""
    reverted = revert_status(ctx["log"], ctx["graph"])
    open_ids = {sid for sid, rec in ctx["records"].items() if not rec["commit"]}
    adds = story_file_adds(ctx)
    found: dict[str, dict[str, tuple[str, str]]] = {}

    def note(sid: str, sha: str, confidence: str, evidence: str) -> None:
        old = found.setdefault(sid, {}).get(sha)
        if old is None or CONFIDENCE[confidence] > CONFIDENCE[old[0]]:
            found[sid][sha] = (confidence, evidence)

    for c in ctx["log"]:
        if c["no_story"] or c.get("reverts_said", c["reverts"]) or reverted.get(c["sha"]):
            continue
        subject, _, body = c["message"].partition("\n")
        skip = set(c["story"]) | set(c["part_of"]) | adds.get(c["sha"], set())
        in_subject = set(ID_TOKEN.findall(subject))
        for sid in (in_subject | set(ID_TOKEN.findall(body))) & open_ids - skip:
            where = "subject" if sid in in_subject else "body"
            note(sid, c["sha"], "medium" if sid in in_subject else "low",
                 f"the {where} of {c['sha'][:7]} names {sid}: {' '.join(subject.split())[:100]}")
        branch = merged_branch(subject) if len(c["parents"]) > 1 else None
        for sid in {m.upper() for m in BRANCH_ID.findall(branch or "")} & open_ids - skip:
            note(sid, c["sha"], "medium", f"{c['sha'][:7]} merges the branch {branch}")
    for path in sources:
        for sid, sha, confidence, evidence in evidence_candidates(path, ctx, open_ids, reverted):
            note(sid, sha, confidence, evidence)
    order, arrival = ctx["placed"][1], ctx["placed"][0]
    ct = {c["sha"]: c["ct"] for c in ctx["log"]}
    rows = []
    for sid in sorted(found):
        ranked = sorted(found[sid].items(), key=lambda kv: (CONFIDENCE[kv[1][0]], order[arrival[kv[0]]], ct[kv[0]], kv[0]),
                        reverse=True)
        sha, (confidence, evidence) = ranked[0]
        others = [f"{s[:7]} ({c})" for s, (c, _) in ranked[1:4]]
        if others:
            evidence += f"; other candidates: {', '.join(others)}" + (f" and {len(ranked) - 4} more" if len(ranked) > 4 else "")
        rows.append({"story": sid, "commit": sha, "kind": "backfill", "confidence": confidence, "evidence": evidence})
    return rows


def rows_toml(rows: list[dict], keys: tuple) -> str:
    return "".join("\n[[row]]\n" + "".join(f"{k} = {toml_str(str(r[k]))}\n" for k in keys if r.get(k) is not None)
                   for r in rows)


PROPOSED_HEADER = (f"# Proposed corrections, for review: delete the rows that are wrong, keep the rest; then a person runs\n"
                   f"# `python3 .keelokit/bin/ledger.py backfill --accept` in their terminal, which moves them into\n"
                   f"# {CORRECTIONS}. Git-ignored; `backfill --propose` rewrites it.\n")


def cmd_propose(state: dict, sources: list[str]) -> int:
    ctx = read_all(state)
    need_history(ctx)
    rows = proposals(ctx, sources)
    target = ROOT / PROPOSED
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(PROPOSED_HEADER + rows_toml(rows, ("story", "commit", "kind", "confidence", "evidence")),
                      encoding="utf-8")
    counts = ", ".join(f"{k} {sum(1 for r in rows if r['confidence'] == k)}" for k in CONFIDENCE)
    print(f"Keelokit: {len(rows)} row(s) proposed in {PROPOSED} ({counts}). Review them, then a person runs "
          "`python3 .keelokit/bin/ledger.py backfill --accept` in their terminal.")
    return 0


def cmd_correct(state: dict, commit: str, story: str, evidence: str) -> int:
    ctx = read_all(state)
    need_history(ctx)
    sha = git_read(["rev-parse", "--verify", "-q", f"{commit}^{{commit}}"], ok=(0, 1, 128)) \
        .decode().strip() if not commit.startswith("-") else ""
    problems = []
    if not sha:
        problems.append(f"{commit!r} is not a commit")
    elif sha not in ctx["placed"][0]:
        problems.append(f"{sha[:12]} is not reachable from the trunk")
    if story not in ctx["records"]:
        problems.append(f"no story {story}")
    if not evidence.strip():
        problems.append("the evidence is empty")
    if problems:
        print(f"Keelokit: nothing proposed: {'; '.join(problems)}", file=sys.stderr)
        return 1
    target = ROOT / PROPOSED
    target.parent.mkdir(parents=True, exist_ok=True)
    old = target.read_text(encoding="utf-8") if target.exists() else PROPOSED_HEADER
    row = {"story": story, "commit": sha, "kind": "late", "confidence": "high", "evidence": evidence.strip()}
    target.write_text(old + ("" if old.endswith("\n") else "\n")
                      + rows_toml([row], ("story", "commit", "kind", "confidence", "evidence")), encoding="utf-8")
    print(f"Keelokit: a late row for {story} at {sha[:12]} is proposed in {PROPOSED}. A person accepts it with "
          "`python3 .keelokit/bin/ledger.py backfill --accept` in their terminal.")
    return 0


def cmd_accept(state: dict) -> int:
    """A person, in their terminal (the `human` approval mode): the proposed rows, shown and confirmed, are
    appended to the corrections file with the person's name and today's date; nothing else is rewritten."""
    if not person_only("backfill --accept"):
        return 1
    user = git_read(["config", "user.name"], ok=(0, 1)).decode(errors="replace").strip()
    if not user:
        print("Keelokit: set your name first: `git config user.name \"Your Name\"` (it becomes the approver).",
              file=sys.stderr)
        return 1
    source = ROOT / PROPOSED
    try:
        proposed, why = parse_rows(source.read_bytes())
    except OSError:
        proposed, why = None, "missing: run `ledger.py backfill --propose` or `ledger.py correct` first"
    if why or not proposed:
        print(f"Keelokit: nothing to accept: {PROPOSED} {why or 'has no rows'}", file=sys.stderr)
        return 1
    ctx = read_all(state)
    need_history(ctx)
    target = ROOT / CORRECTIONS
    current_text = target.read_text(encoding="utf-8") if target.exists() else ""
    current, why = parse_rows(current_text.encode()) if current_text else ([], None)
    if why:
        print(f"Keelokit: {CORRECTIONS} {why}; fix it first", file=sys.stderr)
        return 1
    today = datetime.now().date().isoformat()
    new = [{**{k: v for k, v in r.items() if k in ("story", "commit", "kind", "evidence")}, "approver": user,
            "date": today} if isinstance(r, dict) else r for r in proposed]
    ids = {s["id"] for s in ctx["stories"] if not s.get("unreadable")}
    known = None if any(s.get("unreadable") for s in ctx["stories"]) else ids
    reviews = local_delegation(ctx, current)
    before, _ = apply_rows(current, known, ctx["placed"][0], CORRECTIONS, reviews=reviews)
    kept, skipped = [], []
    for row in new:
        if isinstance(row, dict) and row.get("kind") != "retract" and any(
                (a["story"], a["commit"], a["kind"]) == (row.get("story"), row.get("commit"), row.get("kind")) for a in before):
            skipped.append(row)
        else:
            kept.append(row)
    rows_bad: list[int] = []
    _, diffs = apply_rows(current + kept, known, ctx["placed"][0], PROPOSED, rows_bad, reviews)
    bad = [d["detail"].replace(f" row {i} ", f" row {i - len(current)} ", 1)
           for i, d in zip(rows_bad, diffs) if i > len(current)]
    if bad:
        print("Keelokit: nothing accepted; fix or delete these proposed rows:\n  " + "\n  ".join(bad), file=sys.stderr)
        return 1
    for row in skipped:
        print(f"  already in {CORRECTIONS}: {row['kind']} {row['story']} {row['commit'][:12]}")
    if not kept:
        print("Keelokit: nothing new to accept.")
        return 0
    for row in kept:
        print(f"  {row['kind']} {row['story']} {row['commit'][:12]} — {row['evidence']}")
    try:
        answer = input(f"Accept {len(kept)} row(s) as {user}? [y/N] ")
    except EOFError:
        answer = ""
    if answer.strip().lower() not in ("y", "yes"):
        print("Keelokit: nothing accepted.")
        return 1
    append_corrections(current_text, kept)
    source.unlink()
    print(f"Keelokit: {len(kept)} row(s) added to {CORRECTIONS}. Commit them yourself with "
          "`git -c keelokit.allowTamper=true commit`, saying why in the message.")
    return 0


def append_corrections(current_text: str, rows: list[dict]) -> None:
    """Append rows to the corrections file without rewriting a byte (the header when the file is new)."""
    target = ROOT / CORRECTIONS
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a" if current_text else "w", encoding="utf-8") as f:
        if not current_text:
            f.write(CORRECTIONS_HEADER)
        elif not current_text.endswith("\n"):
            f.write("\n")
        f.write(rows_toml(rows, ("story", "commit", "kind", "evidence", "approver", "date")))


def person_only(command: str) -> bool:
    """True when this is a person in their own terminal (both ends a terminal, not Claude Code's shell)."""
    if os.environ.get("CLAUDECODE") or not (sys.stdin.isatty() and sys.stdout.isatty()):
        print(f"Keelokit: `{command}` is for a person in their own terminal (no terminal here, or Claude Code's "
              "shell); an agent proposes rows and never accepts them.", file=sys.stderr)
        return False
    return True


# ── approval modes and the delegated review (docs/ledger.md, "Approval modes"; LEDGER-015) ──

def is_delegated(approver) -> bool:
    return isinstance(approver, str) and approver.strip().lower().startswith(DELEGATED)


def delegated_run(approver: str) -> str:
    return approver.strip()[len(DELEGATED):].strip()


def load_toml(content: bytes | None) -> dict | None:
    """A TOML file's data; {} when absent, None when it cannot be read."""
    if content is None:
        return {}
    try:
        return tomllib.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError):
        return None


def approval_config(content: bytes | None) -> dict:
    """`[ledger.approval]` of the trunk's state.toml: mode (human when absent, unreadable or unknown), human_for
    (mixed; the known reasons, all three by default) and sample (a share in [0, 1], 0.05 by default)."""
    state = load_toml(content) or {}
    ledger = state.get("ledger")
    table = ledger.get("approval") if isinstance(ledger, dict) else None
    table = table if isinstance(table, dict) else {}
    mode = table.get("mode")
    reasons = table.get("human_for")
    share = table.get("sample")
    fine = isinstance(share, (int, float)) and not isinstance(share, bool) and math.isfinite(share) and 0 <= share <= 1
    return {"mode": mode if isinstance(mode, str) and mode in MODES else "human",
            "human_for": [h for h in HUMAN_FOR if h in reasons] if isinstance(reasons, list) else list(HUMAN_FOR),
            "sample": share if fine else DEFAULT_SAMPLE}


def critical_areas(content: bytes | None) -> list[str] | None:
    """The paths of the trunk's critical areas; None when critical.toml cannot be read (then every story counts
    as critical: the safe side)."""
    data = load_toml(content)
    if data is None:
        return None
    areas = data.get("area", [])
    if not isinstance(areas, list):
        return None
    return sorted({p.strip() for a in areas if isinstance(a, dict) and isinstance(a.get("paths"), list)
                   for p in a["paths"] if isinstance(p, str) and p.strip()})


def overlaps(a: str, b: str) -> bool:
    """The same path, or one is a directory that holds the other (as the doctor reads `touches`)."""
    a, b = a.strip().strip("/"), b.strip().strip("/")
    return bool(a and b) and (a == b or a.startswith(b + "/") or b.startswith(a + "/"))


def is_critical(story: dict, areas: list[str] | None) -> bool:
    """A story in a critical area (its touches meet one) or with the integrity dimension."""
    return areas is None or "integrity" in story["dimensions"] or any(
        overlaps(t, a) for t in story["touches"] for a in areas)


def parse_review(content: bytes, run: str) -> dict | None:
    """A review file's data when it is an object for this run with a list of rows, else None."""
    try:
        data = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None
    if not isinstance(data, dict) or data.get("run") != run or not isinstance(data.get("rows"), list):
        return None
    return data


def local_reviews() -> dict:
    """{run: parsed or None} of the review files in the work tree (what a run just wrote, not yet committed)."""
    found = {}
    folder = ROOT / REVIEWS
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        run = path.name[:-5]
        if RUN_ID.fullmatch(run) and path.is_file():
            try:
                found[run] = parse_review(path.read_bytes(), run)
            except OSError:
                found[run] = None
    return found


def known_reviews(ctx: dict) -> dict:
    """The trunk's review files, with the work tree's on top (for the commands that write the work tree)."""
    return {**ctx["reviews"], **local_reviews()}


def local_delegation(ctx: dict, rows: list, extra: dict | None = None) -> dict:
    """The delegation context of the work tree: its review files over the trunk's (and `extra`), for these rows."""
    return with_touched({**ctx["delegation"], "reviews": {**known_reviews(ctx), **(extra or {})}}, rows,
                        ctx["placed"][0])


def verdict(row: dict, judge: str) -> str | None:
    v = row.get(judge)
    return v.get("verdict") if isinstance(v, dict) and v.get("verdict") in ("yes", "no") else None


def refuted(row: dict) -> bool | None:
    v = row.get("skeptic")
    return v.get("refuted") if isinstance(v, dict) and isinstance(v.get("refuted"), bool) else None


def verdicts_problem(row) -> str | None:
    """Why a review row lacks the verdicts the decision needs, or None."""
    if not isinstance(row, dict):
        return "not an object"
    a, b = verdict(row, "judge_a"), verdict(row, "judge_b")
    if a is None or b is None:
        return "judge_a and judge_b each need a verdict, yes or no"
    if a == b == "yes" and refuted(row) is None:
        return "both judges said yes, so the skeptic's verdict is needed (refuted: true or false)"
    return None


def judges_approve(row: dict) -> bool:
    """Both judges said yes and the skeptic failed to refute."""
    return verdict(row, "judge_a") == verdict(row, "judge_b") == "yes" and refuted(row) is False


def by_opus(row: dict) -> bool:
    """Every verdict of the row names an Opus model (critical stories in `delegated` are judged by Opus)."""
    return all(isinstance(row.get(k), dict) and isinstance(row[k].get("model"), str)
               and "opus" in row[k]["model"].lower() for k in ("judge_a", "judge_b", "skeptic"))


def decide(row: dict, approval: dict) -> str:
    """approved | person | pending, from the verdicts, the mode and the row's `critical` and `confidence` (both
    computed by ledger.py). Pure: the review file's own `decision` is never read."""
    mode, reasons = approval["mode"], approval["human_for"]
    if mode == "mixed":
        if row.get("critical") and "critical" in reasons:
            return "person"
        if row.get("confidence") == "low" and "low-confidence" in reasons:
            return "person"
        if judges_approve(row):
            return "approved"
        return "person" if "disagreement" in reasons else "pending"
    if mode == "delegated":
        if row.get("critical") and not by_opus(row):
            return "pending"
        return "approved" if judges_approve(row) else "pending"
    return "pending"


def with_touched(delegation: dict | None, rows: list, reachable: set) -> dict:
    """The delegation context plus `touched`: the paths each delegated row's commit changes (one `git log` for all
    of them, none when no row is delegated)."""
    delegation = dict(delegation or {"reviews": {}})
    shas = [plain_value(r.get("commit")) for r in rows if isinstance(r, dict) and is_delegated(r.get("approver"))]
    delegation["touched"] = changed_paths([c for c in shas if isinstance(c, str) and c in reachable])
    return delegation


def review_approval(review: dict) -> dict:
    """The mode and human_for a review file recorded (as approval_config reads the table; mode human otherwise)."""
    reasons = review.get("human_for")
    mode = review.get("mode")
    return {"mode": mode if isinstance(mode, str) and mode in MODES else "human",
            "human_for": [h for h in HUMAN_FOR if h in reasons] if isinstance(reasons, list) else list(HUMAN_FOR)}


def delegated_problem(values: dict, delegation: dict, key: str | None = None) -> str | None:
    """Why a row approved by `delegated:<run>` cannot count. Its review file, on the trunk, recorded mode delegated
    or mixed and holds the same story, commit and kind approved by both judges with the skeptic's refutation failed;
    and ledger.py re-decides it as approved now (the recorded mode, human_for, confidence and models, the story's
    critical flag from the trunk) and the commit's diff touches the story's paths: a review file is only verdicts."""
    run = delegated_run(values["approver"])
    reviews = delegation.get("reviews", {})
    if not RUN_ID.fullmatch(run):
        return f"the delegated approver {values['approver']!r} names no valid run"
    if values["kind"] not in ("backfill", "late"):
        return f"a {values['kind']} row is a person's, never a delegated review's (run {run})"
    if run not in reviews:
        return f"a delegated row of run {run} needs its review file {REVIEWS}/{run}.json on the trunk"
    review = reviews[run]
    if review is None:
        return f"{REVIEWS}/{run}.json is not a review file of run {run}"
    approval = review_approval(review)
    if approval["mode"] not in ("delegated", "mixed"):
        return f"{REVIEWS}/{run}.json does not record a delegated or mixed approval mode"
    at = delegation.get("arrival", {}).get(key) if key is not None else None  # its own arrival, never another row's
    story = at["story"] if at else delegation.get("stories", {}).get(values["story"])
    critical = True if story is None else is_critical(story, at["areas"] if at else delegation.get("areas"))
    same = [r for r in review["rows"] if isinstance(r, dict)
            and (r.get("story"), r.get("commit"), r.get("kind")) == (values["story"], values["commit"], values["kind"])]
    # Under the recorded approval, and under the trunk's when it is mixed: a review cannot record a looser mode
    # than the one the person keeps (mixed sends critical stories to the person).
    current = delegation.get("approval") or {"mode": "human"}
    rules = [approval] + ([current] if current["mode"] == "mixed" else [])
    if not any(r.get("decision") == "approved" and judges_approve(r)
               and all(decide({**r, "critical": critical}, a) == "approved" for a in rules) for r in same):
        return f"run {run} does not approve this row ({REVIEWS}/{run}.json: both judges yes, the skeptic's " \
               "refutation failed, and not left to the person by the mode)"
    touches = story["touches"] if story else []
    if touches and not any(overlaps(p, t) for p in delegation.get("touched", {}).get(values["commit"], ())
                           for t in touches):
        return f"run {run}: the diff of {values['commit'][:12]} touches none of {values['story']}'s paths"
    return None


def pending_reviews(reviews: dict, records: dict) -> list[dict]:
    """One PENDING_REVIEW warning per story a review on the trunk left to the person or pending, while it is not
    on the trunk."""
    diffs, seen = [], set()
    for run in sorted(reviews):
        for row in (reviews[run] or {}).get("rows", []):
            if not isinstance(row, dict) or row.get("decision") not in ("person", "pending"):
                continue
            sid = row.get("story")
            if isinstance(sid, str) and sid in records and not records[sid]["commit"] and sid not in seen:
                seen.add(sid)
                where = "in the person's queue" if row["decision"] == "person" else "pending"
                diffs.append({"level": "warning", "code": "PENDING_REVIEW",
                              "detail": f"{sid}: {where} after the delegated review {run} "
                                        f"({str(row.get('commit'))[:12]}); not on the trunk"})
    return diffs


def changed_paths(shas: list[str]) -> dict[str, set[str]]:
    """commit -> the paths its diff touches (a merge: against its first parent), from one `git log`."""
    unique = sorted(set(shas))
    if not unique:
        return {}
    out = git_read(["-c", "core.quotePath=false", "log", "--no-walk=unsorted", "--stdin", "--format=%x00%H",
                    "--name-only", "--no-renames", "--diff-merges=first-parent"],
                   "".join(f"{s}\n" for s in unique).encode()).decode(errors="replace")
    paths: dict[str, set[str]] = {}
    for chunk in out.split("\0")[1:]:
        lines = [line for line in chunk.split("\n") if line.strip()]
        if lines:
            paths[lines[0].strip()] = set(lines[1:])
    return paths


def left_by_reviews(reviews: dict) -> dict:
    """(story, commit) -> why a review left it to the person or pending: such a row is not judged again by agents."""
    left = {}
    for run in sorted(reviews):
        for r in (reviews[run] or {}).get("rows", []):
            if isinstance(r, dict) and r.get("decision") in ("person", "pending"):
                left.setdefault((r.get("story"), r.get("commit")),
                                f"left to the person by run {run}" if r["decision"] == "person" else f"pending after run {run}")
    return left


def filter_rows(ctx: dict, rows: list, active: set) -> list[tuple[dict | None, str | None]]:
    """The mechanical filter (no model), one (kept row, None) or (None, why it is dropped) per row: the commit
    is a full sha on the trunk, the story exists and is not on the trunk yet, the row repeats no active row
    (`active`: (story, commit)) nor an earlier one, the evidence is there, and the commit's diff touches one of
    the story's `touches` when it has any."""
    stories = {s["id"]: s for s in ctx["stories"]}
    reachable, records, areas = ctx["placed"][0], ctx["records"], ctx["areas"]
    seen, results = set(), []
    left = left_by_reviews(known_reviews(ctx))
    for row in rows:
        if not isinstance(row, dict):
            results.append((None, "not a table"))
            continue
        v = {k: plain_value(row.get(k)) for k in ("story", "commit", "kind", "evidence")}
        missing = [k for k, x in v.items() if not isinstance(x, str) or not x.strip()]
        story = stories.get(v["story"]) if not missing else None
        why = (f"missing or empty: {', '.join(missing)}" if missing
               else f"kind {v['kind']!r} is not backfill or late" if v["kind"] not in ("backfill", "late")
               else f"commit {v['commit'][:12]!r} is not a full sha" if not FULL_SHA.fullmatch(v["commit"])
               else f"commit {v['commit'][:12]} is not reachable from the trunk" if v["commit"] not in reachable
               else f"no story {v['story']}" if story is None
               else f"the story file {story['path']} cannot be read" if story.get("unreadable")
               else f"{v['story']} is already on the trunk" if records[v["story"]]["commit"]
               else f"a duplicate of a row of {v['story']} at {v['commit'][:12]}" if (v["story"], v["commit"]) in active | seen
               else left.get((v["story"], v["commit"])))
        if why:
            results.append((None, why))
            continue
        seen.add((v["story"], v["commit"]))
        confidence = row.get("confidence")
        results.append(({**v, "evidence": v["evidence"].strip(),
                         "confidence": confidence if isinstance(confidence, str) and confidence in CONFIDENCE else "low",
                         "critical": is_critical(story, areas), "title": story["title"], "path": story["path"]}, None))
    touched = changed_paths([k["commit"] for k, _ in results if k and stories[k["story"]]["touches"]])
    for i, (kept, _) in enumerate(results):
        if kept and stories[kept["story"]]["touches"] and not any(
                overlaps(p, t) for p in touched.get(kept["commit"], ()) for t in stories[kept["story"]]["touches"]):
            results[i] = (None, f"the diff of {kept['commit'][:12]} touches none of {kept['story']}'s paths")
    return results


def dropped_entry(row, why: str) -> dict:
    get = row.get if isinstance(row, dict) else (lambda _k: None)
    return {"story": str(get("story")), "commit": str(get("commit")), "kind": str(get("kind")), "reason": why}


def worktree_active(ctx: dict) -> tuple[str, list | None, set]:
    """(the work tree's corrections text, its rows or None when unreadable, the (story, commit) of its active rows)."""
    target = ROOT / CORRECTIONS
    text = target.read_text(encoding="utf-8") if target.exists() else ""
    rows, why = parse_rows(text.encode()) if text else ([], None)
    if why:
        return text, None, set()
    known = None if any(s.get("unreadable") for s in ctx["stories"]) else {s["id"] for s in ctx["stories"]}
    active, _ = apply_rows(rows, known, ctx["placed"][0], CORRECTIONS, reviews=local_delegation(ctx, rows))
    return text, rows, {(r["story"], r["commit"]) for r in active} | \
        {(r["story"], r["commit"]) for r in ctx["corrections"]["active"]}


def read_proposed() -> tuple[list | None, str | None]:
    try:
        rows, why = parse_rows((ROOT / PROPOSED).read_bytes())
    except OSError:
        return None, "missing: run `ledger.py backfill --propose` or `ledger.py correct` first"
    return (rows, None) if not why and rows else (None, why or "has no rows")


def run_id(trunk_sha: str, rows: list[dict]) -> str:
    """A run's id from the trunk and its rows: the same input gives the same id, with no clock."""
    digest = hashlib.sha256((trunk_sha + json.dumps(rows, sort_keys=True)).encode()).hexdigest()
    return "r" + digest[:12]


def cmd_filter(state: dict) -> int:
    """`review --filter`: the proposed rows a delegated review may judge, as JSON; writes nothing."""
    proposed, why = read_proposed()
    if why:
        print(f"Keelokit: nothing to review: {PROPOSED} {why}", file=sys.stderr)
        return 1
    ctx = read_all(state)
    need_history(ctx)
    _, rows, active = worktree_active(ctx)
    if rows is None:
        print(f"Keelokit: {CORRECTIONS} cannot be read; fix it first", file=sys.stderr)
        return 1
    results = filter_rows(ctx, proposed, active)
    kept = [k for k, _ in results if k]
    approval = ctx["approval"]
    print(json.dumps({"schema": 1, "run": run_id(ctx["trunk_sha"], kept), "mode": approval["mode"],
                      "human_for": approval["human_for"], "sample": approval["sample"], "rows": kept,
                      "dropped": [dropped_entry(r, why) for r, (_, why) in zip(proposed, results) if why]}, indent=1))
    return 0


def sample_of(run: str, rows: list[dict], share: float) -> list[dict]:
    """The rows the person is shown for a spot check: ordered by a hash of the run and the row, the first
    ceil(share × n). The same run always gives the same sample."""
    if share <= 0 or not rows:
        return []
    ranked = sorted(rows, key=lambda r: hashlib.sha256(f"{run}{r['story']}{r['commit']}".encode()).hexdigest())
    return [{"story": r["story"], "commit": r["commit"]} for r in ranked[:math.ceil(share * len(rows))]]


def refuse(message: str) -> int:
    print(f"Keelokit: nothing accepted: {message}", file=sys.stderr)
    return 1


def cmd_accept_delegated(state: dict, run: str) -> int:
    """`backfill --accept --delegated <run>`: with `[ledger.approval]` delegated or mixed on the trunk, decide every
    row of the run's review file from its verdicts (the mechanical filter again first), write the decisions into
    the file, append the approved rows as `delegated:<run>` and leave the person's queue and the pending rows in
    the proposed file."""
    if not RUN_ID.fullmatch(run):
        return refuse(f"{run!r} is not a run id")
    ctx = read_all(state)
    need_history(ctx)
    approval = ctx["approval"]
    if approval["mode"] not in ("delegated", "mixed"):
        return refuse("the project approves by a person (mode human): the trunk's .keelokit/state.toml does not "
                      "delegate approval ([ledger.approval] mode = "
                      "\"delegated\" or \"mixed\", a person's commit): only a person accepts rows, with "
                      "`ledger.py backfill --accept` in their terminal")
    path = ROOT / REVIEWS / f"{run}.json"
    try:
        review = parse_review(path.read_bytes(), run)
    except OSError:
        return refuse(f"no review file {REVIEWS}/{run}.json")
    if review is None:
        return refuse(f"{REVIEWS}/{run}.json is not a review file of run {run} (JSON with run and rows)")
    if any(isinstance(r, dict) and "decision" in r for r in review["rows"]):
        return refuse(f"run {run} was already decided; start a new review")
    problems = [f"row {i}: {p}" for i, r in enumerate(review["rows"], 1) if (p := verdicts_problem(r))]
    if not review["rows"] or problems:
        return refuse(f"{REVIEWS}/{run}.json " + ("has no rows" if not problems else "\n  " + "\n  ".join(problems)))
    current_text, current, active = worktree_active(ctx)
    if current is None:
        return refuse(f"{CORRECTIONS} cannot be read; fix it first")
    if any(isinstance(r, dict) and is_delegated(r.get("approver")) and delegated_run(r["approver"]) == run
           for r in current):
        return refuse(f"{CORRECTIONS} already has rows of run {run}; commit them with {REVIEWS}/{run}.json")
    results = filter_rows(ctx, review["rows"], active)
    for row, (kept, why) in zip(review["rows"], results):
        if why:
            row.update(decision="dropped", reason=why)
        else:
            row.update(critical=kept["critical"], confidence=kept["confidence"])
            row["decision"] = decide(row, approval)
    approved = [k for row, (k, _) in zip(review["rows"], results) if row["decision"] == "approved"]
    review.update(mode=approval["mode"], human_for=approval["human_for"],
                  sample=sample_of(run, approved, approval["sample"]))
    new = [{"story": k["story"], "commit": k["commit"], "kind": k["kind"], "evidence": k["evidence"],
            "approver": f"{DELEGATED}{run}", "date": datetime.now().date().isoformat()} for k in approved]
    known = None if any(s.get("unreadable") for s in ctx["stories"]) else {s["id"] for s in ctx["stories"]}
    bad: list[int] = []
    _, diffs = apply_rows(current + new, known, ctx["placed"][0], CORRECTIONS, bad,
                          local_delegation(ctx, current + new, {run: review}))
    if [i for i in bad if i > len(current)]:
        return refuse("; ".join(d["detail"] for i, d in zip(bad, diffs) if i > len(current)))
    path.write_text(json.dumps(review, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    if new:
        append_corrections(current_text, new)
    settled = {(r.get("story"), r.get("commit"), r.get("kind")) for r in review["rows"]
               if r["decision"] in ("approved", "dropped")}
    proposed, _ = read_proposed()
    if proposed:
        left = [r for r in proposed if not isinstance(r, dict) or
                (plain_value(r.get("story")), plain_value(r.get("commit")), plain_value(r.get("kind"))) not in settled]
        (ROOT / PROPOSED).write_text(PROPOSED_HEADER + rows_toml(
            [r for r in left if isinstance(r, dict)], ("story", "commit", "kind", "confidence", "evidence")),
            encoding="utf-8")
    count = {d: [r for r in review["rows"] if r["decision"] == d] for d in ("approved", "person", "pending", "dropped")}
    print(f"Keelokit: delegated review {run} ({approval['mode']}): {len(count['approved'])} approved, "
          f"{len(count['person'])} for the person, {len(count['pending'])} pending, {len(count['dropped'])} dropped.")
    for label, key in (("approved", "approved"), ("for the person (`backfill --accept`, in their terminal)", "person"),
                       ("pending (PENDING_REVIEW)", "pending"), ("dropped by the filter", "dropped")):
        for r in count[key]:
            print(f"  {label}: {r['story']} {str(r['commit'])[:12]}" + (f" — {r['reason']}" if key == "dropped" else ""))
    for r in review["sample"]:
        print(f"  sample for the person to check: {r['story']} {r['commit'][:12]}")
    if review["sample"]:
        print(f"  A wrong one sends the whole run back: `python3 .keelokit/bin/ledger.py review --reject-sample {run}`"
              " (a person, in their terminal).")
    print(f"Commit {CORRECTIONS} and {REVIEWS}/{run}.json together.")
    return 0


def cmd_reject_sample(state: dict, run: str) -> int:
    """`review --reject-sample <run>`, a person in their terminal: a retract row for every active row the run
    approved, and those rows back in the proposed file for another review."""
    if not person_only(f"review --reject-sample {run}"):
        return 1
    if not RUN_ID.fullmatch(run):
        print(f"Keelokit: {run!r} is not a run id", file=sys.stderr)
        return 1
    user = git_read(["config", "user.name"], ok=(0, 1)).decode(errors="replace").strip()
    if not user:
        print("Keelokit: set your name first: `git config user.name \"Your Name\"` (it becomes the approver).",
              file=sys.stderr)
        return 1
    ctx = read_all(state)
    need_history(ctx)
    current_text, current, _ = worktree_active(ctx)
    if current is None:
        print(f"Keelokit: {CORRECTIONS} cannot be read; fix it first", file=sys.stderr)
        return 1
    known = None if any(s.get("unreadable") for s in ctx["stories"]) else {s["id"] for s in ctx["stories"]}
    active, _ = apply_rows(current, known, ctx["placed"][0], CORRECTIONS, reviews=local_delegation(ctx, current))
    mine = [r for r in active if is_delegated(r["approver"]) and delegated_run(r["approver"]) == run]
    if not mine:
        print(f"Keelokit: nothing to send back: no active row of {CORRECTIONS} was approved by run {run}",
              file=sys.stderr)
        return 1
    for r in mine:
        print(f"  {r['kind']} {r['story']} {r['commit'][:12]} — {r['evidence']}")
    try:
        answer = input(f"Retract these {len(mine)} row(s) of run {run} as {user} and send them back to review? [y/N] ")
    except EOFError:
        answer = ""
    if answer.strip().lower() not in ("y", "yes"):
        print("Keelokit: nothing retracted.")
        return 1
    today = datetime.now().date().isoformat()
    append_corrections(current_text, [{"story": r["story"], "commit": r["commit"], "kind": "retract",
                                       "evidence": f"sample of delegated run {run} rejected", "approver": user,
                                       "date": today} for r in mine])
    proposed = ROOT / PROPOSED
    old = proposed.read_text(encoding="utf-8") if proposed.exists() else PROPOSED_HEADER
    proposed.parent.mkdir(parents=True, exist_ok=True)
    proposed.write_text(old + ("" if old.endswith("\n") else "\n") + rows_toml(
        [{**r, "confidence": "low"} for r in mine], ("story", "commit", "kind", "confidence", "evidence")),
        encoding="utf-8")
    print(f"Keelokit: {len(mine)} row(s) of run {run} retracted in {CORRECTIONS} and proposed again in {PROPOSED}. "
          "Commit the retractions yourself with `git -c keelokit.allowTamper=true commit`, then review them again.")
    return 0


# ── check: every difference (docs/ledger.md, "Exit codes and difference codes") ──

def short(sha: str) -> str:
    return sha[:12]


def since_range(cfg: dict, log: list[dict], graph: dict) -> list[dict] | None:
    """The trunk commits after `[ledger] since` (not reachable from it), children first; None without a `since`
    that names exactly one commit of the trunk's history."""
    since = cfg["since"]
    matches = [s for s in graph if s.startswith(since.lower())] if since else []
    if len(matches) != 1:
        return None
    held = set(first_reach(graph, [matches[0]]))
    return [c for c in log if c["sha"] not in held]


def category(value: str) -> str:
    """The category of a `No-story:` value: what comes before the first space, dash (any) or colon."""
    return re.split(r"[\s—–:,-]", value.strip(), maxsplit=1)[0].strip()


def corrected(corrections: dict | None) -> set:
    """The commits an active correction row names: attributed late (`ledger.py correct`, then `backfill --accept`)."""
    return {r["commit"] for r in (corrections or {}).get("active", ()) if isinstance(r.get("commit"), str)}


def unattributed_fix(c: dict, on_trunk: bool) -> str:
    """How to attribute an UNATTRIBUTED commit: on the trunk, the exact `ledger.py correct` command (history is
    not rewritten); before it gets there, its message."""
    if on_trunk:
        return (f"; fix: python3 .keelokit/bin/ledger.py correct {c['sha']} --story <ID> --evidence \"<why it is "
                "work of <ID>>\", then a person runs `ledger.py backfill --accept`")
    return (f"; fix before it reaches the trunk: give it a Story:, Part-of: or No-story: trailer (`git rebase -i "
            f"{short(c['sha'])}^` and reword it, `git commit --amend` for the last one), or bring it with a merge commit "
            "that carries one")


def attribution_diffs(ctx: dict, in_range: list[dict] | None = None, on_trunk: bool = True) -> list[dict]:
    """UNKNOWN_STORY, UNATTRIBUTED, SQUASH_LOST_TRAILERS, BAD_CATEGORY and STORY_NO_BODY on the trunk commits after
    `since` (the rules hold from there on); without a `since`, UNKNOWN_STORY on every trunk commit and nothing else
    (attribution is not required). Errors under `enforce = "block"`, warnings under "warn". `in_range` given: those
    commits instead (a push or a pull request: `range_ctx`), which are not on the trunk yet when not `on_trunk`."""
    cfg, log, graph = ctx["cfg"], ctx["log"], ctx["graph"]
    level = "error" if cfg["enforce"] == "block" else "warning"
    diffs = []

    def add(code: str, c: dict, detail: str, at: str | None = None) -> None:
        subject = c["message"].split("\n", 1)[0].strip()[:80]
        diffs.append({"level": at or level, "code": code, "detail": f"{short(c['sha'])} {subject!r}: {detail}"})

    known = {s["id"] for s in ctx["stories"]}
    if in_range is None:
        in_range = since_range(cfg, log, graph)
    for c in reversed(log if in_range is None else in_range):
        if ctx["unreadable"]:
            break  # an unreadable story file may hold the id
        unknown = sorted({i for i in c["story"] + c["part_of"] if i not in known})
        junk = sorted({p.strip() for key in ("Story", "Part-of") for v in trailer_values(c["trailers"], key)
                       for p in v.split(",") if not STORY_ID.fullmatch(p.strip())})
        if unknown:
            add("UNKNOWN_STORY", c, f"names {', '.join(unknown)}, which no story file of the trunk has")
        if junk:
            add("UNKNOWN_STORY", c, f"Story:/Part-of: {', '.join(map(repr, junk))} is not an id (EPIC-NNN)")
    if in_range is None:
        return diffs
    in_shas = {c["sha"] for c in in_range}
    held = {sha for sha in graph if sha not in in_shas}
    covered = attributed_in_range(log, in_range, graph, ctx["placed"][0], held, corrected(ctx.get("corrections")))
    where = ("the only one where git reads trailers; put it in the same final paragraph as the other trailers, with no "
             "blank line between them")
    for c in reversed(in_range):
        lost = [i for key, i in SQUASHED_TRAILER.findall(c["message"]) if key.lower() == "story" and i not in c["story"]]
        if lost and c["sha"] in covered:
            add("SQUASH_LOST_TRAILERS", c, f"its Story: {', '.join(sorted(set(lost)))} line is outside the "
                f"message's last paragraph, {where}")
        if c["sha"] not in covered:
            if SQUASHED_TRAILER.search(c["message"]):
                add("SQUASH_LOST_TRAILERS", c, "its Story:/Part-of: line is outside the message's last paragraph, "
                    f"{where}")
            elif len(c["parents"]) > 1:
                add("UNATTRIBUTED", c, "a merge with no Story:, Part-of: or No-story: that brings commits without one"
                    + unattributed_fix(c, on_trunk))
            else:
                add("UNATTRIBUTED", c, "no Story:, Part-of: or No-story:, and no merge that brings it has one"
                    + unattributed_fix(c, on_trunk))
        bad = [v for v in trailer_values(c["trailers"], "No-story") if v.strip() and category(v) not in cfg["no_story"]]
        if bad:
            add("BAD_CATEGORY", c, f"No-story: {bad[0]!r} is not one of [ledger] no_story ({', '.join(cfg['no_story'])})")
        if c["story"] and not split_message(c["message"], c["trailers"])[1]:
            add("STORY_NO_BODY", c, f"closes {', '.join(c['story'])} with no body (what was decided, what was left out)")
    for c, branch, lost, how in squashes(ctx, in_range):
        if how == "tree":
            fix = (f" (on the trunk: `python3 .keelokit/bin/ledger.py correct {c['sha']} --story <ID> --evidence "
                   f"\"squash of {branch}\"` for each, then `ledger.py backfill --accept`)") if on_trunk else ""
            add("SQUASH_LOST_TRAILERS", c, f"its tree is the tip of {branch}, which is not integrated: a squash of it "
                f"that lost {', '.join(lost)}; carry every Story: and Part-of: of the branch in its last paragraph{fix}")
        else:  # the same change is weaker evidence than the same tree (ESC-240): a warning, and no correction to copy
            add("SQUASH_LOST_TRAILERS", c, f"its change is {branch}'s since it forked, which is not integrated: if it "
                f"is a squash of it, it lost {', '.join(lost)}; if it is not (the same change made twice), nothing "
                "to do", at="warning")
    return diffs


def origin_branches(refs: dict, trunk: str) -> dict[str, str]:
    """origin/<name> -> tip, every origin branch but the trunk (and origin/HEAD)."""
    skip = {f"refs/remotes/origin/{trunk}", "refs/remotes/origin/HEAD"}
    return {name[len("refs/remotes/"):]: sha for name, sha in refs.items()
            if name.startswith("refs/remotes/origin/") and name not in skip}


def trees_of(shas: list[str]) -> dict[str, str]:
    """commit -> its tree, one `cat-file --batch-check`; a commit that cannot be read is left out."""
    unique = sorted(set(shas))
    if not unique:
        return {}
    out = git_read(["cat-file", "--batch-check=%(objectname) %(objecttype)"],
                   "".join(f"{s}^{{tree}}\n" for s in unique).encode()).decode(errors="replace").splitlines()
    if len(out) != len(unique):
        raise LedgerError("git cat-file gave an unexpected answer")
    return {s: line.split()[0] for s, line in zip(unique, out) if line.split()[1:2] == ["tree"]}


def patch_ids(diff: bytes) -> dict[str, str]:
    """commit (or the all-zero id for a bare diff) -> `git patch-id --stable` of its change; an empty change has none."""
    out = git_read(["patch-id", "--stable"], diff).decode(errors="replace").split("\n")
    return {line.split()[1]: line.split()[0] for line in out if len(line.split()) == 2}


def paths_of(shas: list[str]) -> dict[str, frozenset]:
    """commit -> the paths it changes (none for a merge), one `log --name-only` for all."""
    if not shas:
        return {}
    named = git_read(["log", "--no-walk=unsorted", "--name-only", "--no-renames", "--format=%x00%H", "--stdin"],
                     "".join(f"{sha}\n" for sha in shas).encode()).decode(errors="replace")
    paths = {}
    for chunk in named.split("\0")[1:]:
        lines = [line for line in chunk.split("\n") if line]
        if lines:
            paths[lines[0]] = frozenset(lines[1:])
    return paths


def squashes(ctx: dict, in_range: list[dict]) -> list[tuple[dict, str, list[str], str]]:
    """(commit, origin/<branch>, lost, "tree" or "patch") for each non-merge commit of `in_range` that is a squash of
    an origin branch `ctx["tip"]` does not reach (JOUNA's trains) and lacks a Story: or Part-of: of that branch's own
    commits (those the tip does not reach) that the trunk does not already carry from the branch's fork on.
    - A squash: its tree is the branch tip's (an error), or, the trunk having moved, its change has the patch-id of
      the branch's change since its merge base with the tip (a warning only: the same change made twice is no
      proof, ESC-240). Never a commit the branch reaches; never from a branch that changes nothing (ESC-199), of
      fewer than two commits of its own (ESC-202, ESC-203), or under the unverified prefixes (ESC-241); a tree the
      trunk already had since the fork is a revert back to it (ESC-207).
    - Kept: a branch's Story: must stay a Story:; its Part-of: is kept by either; both count on the commit, on every
      trunk commit from the fork of the branch's own oldest commits to it (not from the merge base, which a sync
      merge of main moves: ESC-238, ESC-239, ESC-242..ESC-244), and in an active correction row naming the commit.
    - Cost: one log of the branches' own commits and their paths, one `--name-only` log and one tree lookup for the
      range; a branch costs git calls of its own only when its tip's tree, or a range commit's paths within the paths
      it touches, match (ESC-204, ESC-245)."""
    tip, graph = ctx.get("tip"), ctx["graph"]
    skip = tuple(f"origin/{p}" for p in ctx.get("unverified", ()))
    branches = {n: sha for n, sha in origin_branches(ctx.get("refs") or {}, ctx.get("trunk") or "").items()
                if not n.startswith(skip)}  # wip/ and archive/ never land, so they are never squashed (ESC-241)
    singles = [c for c in in_range if len(c["parents"]) < 2]
    if not tip or not branches or not singles:
        return []
    reach = set(first_reach(graph, [tip]))
    loose = {name: sha for name, sha in sorted(branches.items()) if sha not in reach and sha in graph}
    if not loose:
        return []
    tips = sorted(set(loose.values()))
    own = {c["sha"]: c for c in read_trunk_log(tips[0], (*tips[1:], "--not", tip))}
    needs = {}
    for name, sha in loose.items():
        mine = [m for m in reach_until(graph, [sha], reach) if m in own]
        stories = {i for m in mine for i in own[m]["story"]}
        parts = {i for m in mine for i in own[m]["part_of"]} - stories
        if (stories or parts) and sum(1 for m in mine if len(own[m]["parents"]) < 2) >= 2:
            needs[name] = (stories, parts, mine)
    if not needs:
        return []
    own_paths = paths_of(sorted({m for _, _, mine in needs.values() for m in mine}))
    single_paths = paths_of([c["sha"] for c in singles])
    trees = trees_of([c["sha"] for c in singles] + [loose[n] for n in needs])
    by_path: dict[str, list[str]] = {}
    for sha, changed in single_paths.items():
        for path in changed:
            by_path.setdefault(path, []).append(sha)
    by_sha = {c["sha"]: c for c in singles}
    ranged = {c["sha"]: c for c in in_range}
    rowed: dict[str, set] = {}
    for r in (ctx.get("corrections") or {}).get("active", ()):
        rowed.setdefault(r.get("commit"), set()).add(r.get("story"))
    found = []
    for name, (stories, parts, mine) in needs.items():
        btip = loose[name]
        touched = frozenset().union(*(own_paths.get(m, frozenset()) for m in mine))
        tree_hits = {c["sha"] for c in singles if trees.get(c["sha"]) is not None and trees.get(c["sha"]) == trees.get(btip)}
        path_hits = {sha for path in touched for sha in by_path.get(path, ())
                     if single_paths[sha] and single_paths[sha] <= touched} - tree_hits
        if not tree_hits and not path_hits:
            continue  # no call of its own (ESC-245)
        base = git_read(["merge-base", tip, btip], ok=(0, 1)).decode().strip() or None
        if base and trees_of([base]).get(base) == trees.get(btip):
            continue  # the branch changes nothing: its tree is its base's (ESC-199)
        patch_hits = set()
        if path_hits and base:
            net_paths = frozenset(line for line in git_read(["diff-tree", "-r", "--name-only", "--no-renames", base, btip])
                                  .decode(errors="replace").split("\n") if line)
            same = sorted(sha for sha in path_hits if single_paths[sha] == net_paths)
            if same:
                net = patch_ids(git_read(["diff-tree", "-p", "--no-color", base, btip])).get("0" * len(btip))
                ids = patch_ids(git_read(["log", "--no-walk=unsorted", "-p", "--no-color", "--format=commit %H",
                                          "--stdin"], "".join(f"{sha}\n" for sha in same).encode()))
                patch_hits = {sha for sha in same if net and ids.get(sha) == net}
        hits = tree_hits | patch_hits
        if not hits:
            continue
        forked = set(first_reach(graph, [btip]))
        # The fork of the branch's own oldest commits: their parents the tip reaches (a sync merge's are skipped).
        forks = sorted({p for m in mine if len(graph.get(m, ())) < 2 for p in graph.get(m, ()) if p in reach}) or \
            ([base] if base else [])
        for c in (by_sha[sha] for sha in sorted(hits)):
            if c["sha"] in forked:
                continue
            same_tree = c["sha"] in tree_hits
            if forks:
                carried = read_trunk_log(c["sha"], ("--not", *forks))
                earlier = set(git_read(["log", "--format=%T", f"{c['sha']}^", "--not", *forks], ok=(0, 128))
                              .decode().split())
            else:
                carried = [ranged[x] for x in reach_until(graph, [c["sha"]], set(graph) - set(ranged))]
                earlier = set()
            if same_tree and trees.get(btip) in earlier:
                continue  # the trunk had this tree before: a revert back to it, not a squash (ESC-207)
            kept_story = {i for k in carried for i in k["story"]} | rowed.get(c["sha"], set())
            kept_any = kept_story | {i for k in carried for i in k["part_of"]}
            lost = [f"Story: {i}" for i in sorted(stories - kept_story)] + \
                   [f"Part-of: {i}" for i in sorted(parts - kept_any)]
            if lost:
                found.append((c, name, lost, "tree" if same_tree else "patch"))
    return found


def unverified_prefixes(state: dict) -> list[str]:
    """The branch prefixes whose work never lands as it is (LEDGER-008): `[verify] wip_branches` (wip/ when unset)
    and archive/."""
    wip = (state.get("verify") or {}).get("wip_branches") if isinstance(state.get("verify"), dict) else None
    wip = wip.strip() if isinstance(wip, str) and wip.strip() else "wip/"
    return sorted({wip if wip.endswith("/") else wip + "/", "archive/"})


def range_ctx(state: dict, cfg: dict, tip: str, exclude: list[str]) -> dict | None:
    """What attribution_diffs needs for the commits `tip` reaches and none of `exclude` (nor `since`) does: a push to
    the trunk, or a pull request over it. None without a `since` naming one commit tip reaches (attribution is not
    required there). Stories are read from tip's tree, where a new story file already is."""
    trunk = trunk_name(state)
    refs = read_refs(trunk, cfg["snapshot"])
    graph = read_graph(sorted({tip, *exclude, *origin_branches(refs, trunk).values()}))
    since = cfg["since"]
    matches = [s for s in graph if s.startswith(since.lower())] if since else []
    if len(matches) == 1:
        stops = sorted({*exclude, matches[0]})
    elif since and len(matches) == 0 and is_shallow():
        # A shallow clone cut before `since` (ESC-198): what the remote already has bounds the new commits.
        if not exclude:
            raise LedgerError(f"this shallow clone does not reach [ledger] since and nothing bounds the new commits; {FIX}")
        stops = sorted(exclude)
    else:
        return None
    log = read_trunk_log(tip, ("--not", *stops))
    stories, unreadable = read_stories(tip, cfg)
    return {"cfg": cfg, "log": log, "graph": graph, "stories": stories, "unreadable": unreadable, "tip": tip,
            "placed": arrivals(graph, tip), "refs": refs, "trunk": trunk, "unverified": unverified_prefixes(state)}


def done_twice(ctx: dict) -> list[dict]:
    """DONE_TWICE: a story whose live Story: commits arrived on the trunk in more than one first-parent commit."""
    reverted = revert_status(ctx["log"], ctx["graph"])
    arrival = ctx["placed"][0]
    seen: dict[str, dict[str, str]] = {}
    for c in reversed(ctx["log"]):
        if not reverted[c["sha"]]:
            for sid in c["story"]:
                if sid in ctx["records"]:
                    seen.setdefault(sid, {}).setdefault(arrival[c["sha"]], c["sha"])
    return [{"level": "warning", "code": "DONE_TWICE",
             "detail": f"{sid}: Story: commits {', '.join(short(s) for s in found.values())} arrived separately"}
            for sid, found in sorted(seen.items()) if len(found) > 1]


def stale_branches(ctx: dict) -> list[dict]:
    days = ctx["cfg"]["stale_days"]
    return [{"level": "warning", "code": "STALE_BRANCH",
             "detail": f"{r['id']}: in progress on {', '.join(r['branches'])} with no commit in {days:g} days "
                       f"(newest {iso(ctx['branches'][r['id']]['newest'])[:10]})"}
            for r in ctx["facts"]["stories"] if "stale" in r["signals"]]


def snapshot_behind(ctx: dict) -> list[dict]:
    """SNAPSHOT_BEHIND: origin/<snapshot> exists and its ledger.json is not of the trunk's head (one `cat-file`,
    only when the branch exists)."""
    name = ctx["cfg"]["snapshot"]
    head = ctx["refs"].get("snapshot") if name else None
    if not head:
        return []
    content = cat_specs([f"{head}:ledger.json"]).get(f"{head}:ledger.json")
    try:
        at = json.loads(content.decode("utf-8")).get("trunk_sha") if content is not None else None
    except (UnicodeDecodeError, ValueError, AttributeError):
        at = None
    if at == ctx["trunk_sha"]:
        return []
    where = f"is of {short(at)}" if isinstance(at, str) else "has no readable ledger.json"
    return [{"level": "warning", "code": "SNAPSHOT_BEHIND",
             "detail": f"origin/{name} {where}; the trunk is at {short(ctx['trunk_sha'])}"}]


def pull_request(trunk: str) -> bool:
    """True in a GitHub Actions run of a pull request into the trunk (GITHUB_EVENT_NAME, GITHUB_BASE_REF)."""
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    return event in ("pull_request", "pull_request_target") and os.environ.get("GITHUB_BASE_REF", trunk) == trunk


def pull_request_diffs(state: dict, ctx: dict) -> list[dict]:
    """A pull request's commits, as they would reach the trunk: those the checked-out HEAD (GitHub's merge of the
    branch into the trunk, refs/pull/N/merge) reaches and the trunk does not. That merge stands for the one GitHub
    makes, attributed when what it brings is; a sync merge of the trunk into the branch brings nothing new."""
    head = git_read(["rev-parse", "--verify", "-q", "HEAD^{commit}"], ok=(0, 1)).decode().strip()
    if not head or head == ctx["trunk_sha"]:
        return []
    breaker = pull_request_breaker(ctx, head)
    rctx = range_ctx(state, ctx["cfg"], head, [ctx["trunk_sha"]])
    if rctx is None:
        return breaker
    if cut_reason(rctx["graph"], is_shallow() is not False):
        return [{"level": "error", "code": "HISTORY_INCOMPLETE",
                 "detail": "the pull request's history is cut: the CI checks it out with `fetch-depth: 0`"}]
    return attribution_diffs(rctx, rctx["log"], on_trunk=False) + breaker


def pull_request_breaker(ctx: dict, head: str) -> list[dict]:
    """HARN-021: the risky stories a pull request closes, judged by the trunk's risky.toml (or --rules-ref's) and
    the trunk's committed `[ledger]` (where stories live, how ids are read), never the pull request's own (ESC-312);
    the story files as the pull request leaves them, else as the trunk has them. Every commit the trunk lacks counts:
    the rule already holds on the trunk."""
    rules = ctx.get("risky")
    if rules is None:
        if not rule_adds(ctx["trunk_sha"]):
            return []
        rules = removed_rules()  # the trunk already lost it: the trunk's check says so; this pull request is judged
    cfg = read_config(committed_state(ctx["trunk_sha"]))
    graph = read_graph(sorted({head, ctx["trunk_sha"]}))
    if cut_reason(graph, is_shallow() is not False):
        return [{"level": "error", "code": "HISTORY_INCOMPLETE",
                 "detail": "the pull request's history is cut: the CI checks it out with `fetch-depth: 0`"}]
    log = read_trunk_log(head, ("--not", ctx["trunk_sha"]))
    base = read_stories(ctx["trunk_sha"], cfg)[0]
    stories = {s["id"]: s for s in base}
    stories.update({s["id"]: s for s in read_stories(head, cfg)[0]})
    hits = risky_commits(rules, head, [])
    own = merge_own_hits(rules, head, [ctx["trunk_sha"]])
    found = risky_no_story(log, hits, own)
    every = log + ctx["log"]  # the pull request's commits, then the trunk's (as the trunk's check read them)
    arrival, order = ctx["placed"]
    found += risky_after_close(log, every, graph, hits, own,
                               lambda sha: order[arrival[sha]] if sha in arrival else len(order))
    earlier = base + story_versions(head, closed_paths(log, list(stories.values()), base), cfg, closed_ids(log))
    return found + breaker_diffs(rules, log, every, graph, list(stories.values()),
                                 config_diffs=False, hits=hits, earlier=earlier)


def all_diffs(state: dict, ci: bool, rules_sha: str | None = None) -> list[dict]:
    """The facts' differences and those only `check` gives (docs/ledger.md: the "Given by" column). `ci` in a pull
    request into the trunk: its commits too (LEDGER-010). `rules_sha`: the rule files from that commit (--rules-ref)."""
    ctx = read_all(state, rules_sha)
    diffs = list(ctx["facts"]["diffs"])
    if ctx["reason"] is None:
        diffs += attribution_diffs(ctx) + stale_branches(ctx) + done_twice(ctx) + snapshot_behind(ctx)
        diffs += trunk_breaker_diffs(ctx)
        if ci and pull_request(trunk_name(state)):
            diffs += pull_request_diffs(state, ctx)
    if ci:
        diffs = [{**d, "level": "error"} if d["code"] == "HISTORY_INCOMPLETE" else d for d in diffs]
    return diffs


def cmd_check(state: dict, args: tuple) -> int:
    """Every difference: one line each, or `{"schema": 1, "diffs": [...]}`. Exit 1 on an error-level one. `--ci`
    reads as the CI does (HISTORY_INCOMPLETE is an error). `--rules-ref REV` (LEDGER-013, Harbor's ok): every rule file
    the ledger reads from the trunk's committed tree ([ledger.approval] in state.toml, critical.toml, the review
    files, and critical.toml at a delegated row's arrival) is read from REV instead; a REV that is no commit: exit 2."""
    as_json, ci, rules_ref = args
    rules_sha = None
    if rules_ref is not None:
        rules_sha = resolve_commit(rules_ref)
        if rules_sha is None:
            print(f"Keelokit: check: --rules-ref {rules_ref!r} does not resolve to a commit here", file=sys.stderr)
            return 2
        # `[ledger]` (enforce, since, no_story, stories, trunk) is a rule as well: <rev>'s committed state.toml, never
        # the checked-out one (absent or unreadable there: the defaults, as read_state).
        state = committed_state(rules_sha)
    elif ci and os.environ.get("GITHUB_EVENT_NAME", "") in ("pull_request", "pull_request_target"):
        # A pull request is judged by the base branch's committed [ledger] when it has one, never by the state.toml the
        # pull request brings: its own `trunk` would move what it is judged on (ESC-317).
        base = os.environ.get("GITHUB_BASE_REF", "")
        sha = resolve_commit(f"refs/remotes/origin/{base}") if base and not base.startswith("-") else None
        if sha and git_read(["ls-tree", sha, "--", STATE_FILE]).strip():
            state = committed_state(sha)
    diffs = all_diffs(state, ci, rules_sha)
    if as_json:
        print(json.dumps({"schema": 1, "diffs": diffs}, indent=1))
    else:
        for d in diffs:  # details quote paths, subjects and names: nothing in them reaches the terminal (HARN-022)
            print(CONTROL.sub("?", f"{d['level']} {d['code']} {d['detail']}"))
    return 1 if any(d["level"] == "error" for d in diffs) else 0


# ── breaker rounds (HARN-021) ──
# A risky story (`risky = true`, a dimension or a path of .keelokit/risky.toml, in its touches or in what its trunk
# commits change) closes only after cold breaker rounds, recorded in its file under `## Breaker rounds`: one line per
# round, `- Round <n> · head <sha> · clean` or `· <findings> · <fixes>`, and when the last round left findings, a
# person's `- Decision · <name> · <YYYY-MM-DD> · <what>`. `check` gives BREAKER_MISSING (error) for a risky story
# closed with no round, BREAKER_UNRESOLVED (warning) when its last round is not clean with no Decision after it (the
# last round decides, whatever its number: HARN-022), BREAKER_CONFIG for a risky.toml it cannot use (an error: every closed story counts as risky then)
# and BREAKER_BAD_ENTRY (warning) for a line under the heading that is neither. The rule holds for Story: commits after
# `[ledger] since` that the commit which brought risky.toml to the trunk (or its `since`) does not reach; without
# risky.toml on the trunk, nothing. The line is a record, as a trailer is: the ledger checks it is there, not that the
# round happened.

ROUND_LINE = re.compile(r"- Round ([0-9]{1,3}) · head ([0-9a-f]{40}|[0-9a-f]{64}) · (.+)")
DECISION_LINE = re.compile(r"- Decision · ([^·]*\S[^·]*) · ([0-9]{4}-[0-9]{2}-[0-9]{2}) · (.*\S.*)")
# Without `deciders` in risky.toml, a Decision naming one of these is no person's (ESC-314): a long word anywhere in
# the name's letters (`subagent`, `ClaudeCode`, `Breaker2`), a short one as a word of its own (`AI`, `the bots`).
AGENT_WORDS = ("claude", "agent", "breaker", "builder", "reviewer", "verifier", "orchestrator", "coordinator",
               "delegated", "copilot", "assistant", "subagent", "sonnet", "haiku", "fable", "gemini", "chatgpt",
               "openai", "anthropic", "model", "harbor", "skipper", "dispatcher", "harbormaster", "swarm",
               "grok", "deepseek", "llama", "devin", "mistral", "mixtral", "qwen", "gemma", "cohere", "perplexity",
               "kimi", "windsurf", "cline", "aider", "bard", "dependabot", "renovate", "github", "gitlab",
               "actions", "keelokit", "robot", "automation", "automated", "devstral", "nemotron", "jenkins",
               "circleci", "workflow", "pipeline", "script")
AGENT_SHORT = ("ai", "bot", "llm", "gpt", "opus", "codex", "cursor", "glm", "phi", "o1", "o3", "ci", "cd")
ROUNDS_HEADING = re.compile(r"##[ \t]+Breaker rounds[ \t]*")
ROUND_FORMAT = ("`- Round <n> · head <full sha> · clean` (or `· <findings> · <fixes>`), or "
                "`- Decision · <person> · <YYYY-MM-DD> · <what was decided>`")


def breaker_record(body: str) -> dict:
    """The `## Breaker rounds` section(s) of a story's text, outside code fences: entries in order (("round", n, head,
    clean) or ("decision", name)), and the lines under it that are neither (`bad`, with why). Only top-level `- ` lines
    are entries; indented and other lines are the round's detail."""
    entries, bad = [], []
    inside, fence, comment = False, None, False
    for raw in body.splitlines():
        line = raw.rstrip()
        bare = line.lstrip()
        if fence:  # a fence closes only with its own character, at least as long, and nothing after it (ESC-328)
            if re.fullmatch(re.escape(fence[0]) + "{%d,}" % len(fence), bare):
                fence = None
            continue
        if comment:  # nothing inside an HTML comment is a record
            comment = "-->" not in line
            continue
        opening = re.match(r"(`{3,}|~{3,})", bare)
        if opening:
            fence = opening.group(1)
            continue
        if bare.startswith("<!--"):
            comment = "-->" not in bare[4:]
            continue
        if ROUNDS_HEADING.fullmatch(line):
            inside = True
            continue
        if line.startswith(("# ", "## ")):
            inside = False
            continue
        if not inside or not line.startswith("- "):
            continue
        m = ROUND_LINE.fullmatch(line)
        if m:
            # `clean` is the whole result, nothing after it: a round that lists findings is not clean (ESC-341)
            entries.append(("round", int(m.group(1)), m.group(2), m.group(3).strip() == "clean"))
            continue
        m = DECISION_LINE.fullmatch(line)
        if m and valid_date(m.group(2)):
            entries.append(("decision", m.group(1).strip(), line[:80]))
        else:
            bad.append(f"{line[:80]!r} is not {ROUND_FORMAT}")
    numbers = [e[1] for e in entries if e[0] == "round"]
    if numbers != list(range(1, len(numbers) + 1)):
        # Rounds numbered other than 1, 2, … are no record of rounds at all (ESC-328): none of them counts.
        bad.append(f"its rounds are numbered {', '.join(map(str, numbers))}, not 1, 2, … in order: none counts")
        entries = [e for e in entries if e[0] != "round"]
    return {"entries": entries, "bad": bad}


def agent_like(name: str) -> bool:
    """A name that reads as an agent's or a model's, never a person's (AGENT_WORDS, AGENT_SHORT)."""
    name = unicodedata.normalize("NFKC", name)  # fullwidth and other compatibility forms read as what they show
    if re.search(r"[0-9]", name):  # people's names carry no digits: `o3`, `C1aude`, `Breaker2` (ESC-329)
        return True
    # A letter of another script (Cherokee `Ꮯ`, small capitals, …) cannot be told from a look-alike here: only a name
    # in `deciders` can carry one (ESC-344). Latin letters with accents (José) are letters of a person's name.
    if any(ch.isalpha() and not unicodedata.name(ch, "").startswith("LATIN ") for ch in name):
        return True
    if any(unicodedata.name(ch, "").startswith("LATIN LETTER SMALL CAPITAL") for ch in name):
        return True
    name = "".join(ch for ch in unicodedata.normalize("NFKD", name) if not unicodedata.combining(ch))
    if any(not ch.isascii() and unicodedata.name(ch, "").startswith(("CYRILLIC", "GREEK")) for ch in name) \
            and re.search(r"[A-Za-z]", name):  # Latin mixed with look-alike letters: `Сlaude` with a Cyrillic С
        return True
    letters = re.sub(r"[^a-z]", "", name.lower())
    words = {v for w in re.findall(r"[a-z0-9]+", name.lower()) for v in (w, w[:-1] if w.endswith("s") else w)}
    return any(w in letters for w in AGENT_WORDS) or bool(words & set(AGENT_SHORT))


def is_decider(name: str, rules: dict) -> bool:
    """Who may decide: one of risky.toml's `deciders` (case aside) when it lists any, else any name that is not
    agent-like."""
    if rules["deciders"]:
        return name.casefold() in {d.casefold() for d in rules["deciders"]}
    return not agent_like(name)


def risky_config(content: bytes | None, present: bool) -> dict | None:
    """.keelokit/risky.toml as the ledger uses it: None when the tree has no such file. `problem` when it cannot be
    used as written (not TOML, unreadable here, a wrong type): then `all`, every closed story counts as risky."""
    if not present:
        return None
    rules = {"rounds": DEFAULT_ROUNDS, "paths": list(ALWAYS_RISKY), "dimensions": [], "deciders": [], "since": None,
             "problem": None, "all": False}
    data = load_toml(content) if content is not None else None
    if not isinstance(data, dict):
        return {**rules, "problem": f"{RISKY_FILE} cannot be read as TOML here", "all": True}
    problems = []
    unknown = sorted(set(data) - {"rounds", "paths", "dimensions", "deciders", "since"})
    if unknown:  # a misspelt key or a table header would read as no rule (ESC-322)
        problems.append(f"unknown key{'s' if len(unknown) > 1 else ''} {', '.join(map(repr, unknown[:3]))}")
    rounds = data.get("rounds", DEFAULT_ROUNDS)
    if is_int(rounds) and 1 <= rounds <= MAX_ROUNDS:
        rules["rounds"] = rounds
    else:
        problems.append(f"`rounds` is a whole number from 1 to {MAX_ROUNDS}")
    for key in ("paths", "dimensions", "deciders"):
        value = data.get(key, [])
        if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
            problems.append(f"`{key}` is a list of non-empty strings")
        else:
            rules[key] = sorted({v.strip().lstrip("/") for v in value} - {""} | (set(ALWAYS_RISKY) if key == "paths"
                                                                                 else set()))
            if key == "paths":  # git reads them as pathspecs: nothing outside the repo, no pathspec magic (ESC-330)
                odd = [v for v in rules[key] if v.startswith((":", "!")) or "\\" in v
                       or any(part in ("..", ".") for part in v.split("/")) or CONTROL.search(v)
                       or "\n" in v or "\t" in v]
                if odd:
                    problems.append(f"`paths` stay inside the repo, without `..`, `.` or a leading `:` ({odd[0]!r})")
                    rules[key] = [v for v in rules[key] if v not in odd]
    rules["dimensions"] = sorted({d.lower() for d in rules["dimensions"]})
    since = data.get("since", "")
    if not isinstance(since, str) or since.strip() and not HEX_SHA.fullmatch(since.strip()):
        problems.append("`since` is a commit sha")
    elif since.strip():
        rules["since"] = since.strip().lower()
    if problems:
        rules.update(problem=f"{RISKY_FILE}: {'; '.join(problems)}", all=True)
    return rules


def literal_prefix(pattern: str) -> str:
    """What a glob says before its first wildcard."""
    m = re.search(r"[*?]", pattern)
    return pattern[:m.start()] if m else pattern


def touch_meets(touch: str, pattern: str) -> bool:
    """A story's touch can name a file the pattern covers: the file itself, a directory that holds one (`scripts`
    for `scripts/verify.sh`, `apps/api/auth` for `**/auth/**`), or, for a touch that is a glob, one whose literal start
    and the pattern's run into each other (when in doubt, risky)."""
    t = touch.strip()
    while t.startswith("./"):
        t = t[2:]
    t = t.lstrip("/").rstrip("/")
    if not t:
        return False
    if re.search(r"[*?]", t):
        a, b = literal_prefix(t), literal_prefix(pattern)
        return a.startswith(b) or b.startswith(a)
    regex = glob_regex(pattern)
    if regex.fullmatch(t) or regex.fullmatch(t + "/") or literal_prefix(pattern).startswith(t + "/"):
        return True
    # A touch that names a directory touches everything under it (HARN-022): it meets every glob that can match a path
    # beneath it (`apps/api` for `**/migrations/**`). A directory is a touch ending in `/`, or whose last part has no
    # extension (`apps/api`, `.github`, `scripts`); `apps/api/page.ts` stays a file.
    last = t.rsplit("/", 1)[-1]
    if touch.rstrip().endswith("/") or "." not in last.lstrip("."):
        return glob_beneath(pattern, t)
    return False


def glob_beneath(pattern: str, directory: str) -> bool:
    """Whether the glob can match some path strictly beneath `directory` (`*` and `?` within one part, `**` any number
    of parts; a part with `**` inside it may cross parts, so it counts as matching: when in doubt, risky)."""
    pat, parts = pattern.split("/"), directory.split("/")
    seen: set = set()
    stack = [(0, 0)]
    while stack:
        i, j = stack.pop()
        if (i, j) in seen:
            continue
        seen.add((i, j))
        if j == len(parts):
            if i < len(pat) and any(pat[i:]):
                return True
            continue
        if i == len(pat):
            continue
        if pat[i] == "**":
            stack += [(i + 1, j), (i, j + 1)]
        elif "**" in pat[i]:
            return True
        elif glob_regex(pat[i]).fullmatch(parts[j]):
            stack.append((i + 1, j + 1))
    return False


def risky_reasons(story: dict, rules: dict | None, changed: set, hits: list | tuple = ()) -> list[str]:
    """Why a story is risky (empty: it is not): its front matter, a dimension, a touch, a changed path, or a commit of
    it that git found changing a path of risky.toml (`hits`)."""
    if rules is None:
        return ["risky = true"] if story.get("risky") else []
    why = [f"{RISKY_FILE} cannot be used, so every story counts"] if rules["all"] else []
    why += ["risky = true"] if story.get("risky") else []
    why += [f"dimension {d}" for d in story.get("risk_dims", story["dimensions"]) if d in rules["dimensions"]]
    why += [f"its commit {short(sha)} changes a path of {RISKY_FILE}" for sha in hits]
    for pattern in rules["paths"]:
        regex = glob_regex(pattern)
        why += [f"touches {t} ({pattern})" for t in story["touches"] if touch_meets(t, pattern)]
        why += [f"changes {p} ({pattern})" for p in sorted(changed) if regex.fullmatch(p)]
    return list(dict.fromkeys(why))


def risky_commits(rules: dict, tip: str, exclude: list[str]) -> set[str]:
    """The commits `tip` reaches and `exclude` does not that change a path of risky.toml: git filters them (one
    path-limited `git log`), so no commit's file list is read (ESC-323)."""
    if not rules["paths"]:
        return set()
    out = git_read(["log", "--full-history", "--format=%H", tip, *(["--not", *exclude] if exclude else []), "--",
                    *(f":(glob){p}" for p in rules["paths"])]).decode()
    return set(out.split())


def missing_story(sid: str) -> dict:
    """What stands for a closed story whose file is gone, moved or unreadable as a story: no front matter to make it
    risky, no rounds; its commits still can (ESC-316)."""
    return {"id": sid, "path": "(no story file)", "unreadable": False, "touches": [], "dimensions": [],
            "risk_dims": [], "risky": False, "breaker": {"entries": [], "bad": []}}


def breaker_diffs(rules: dict | None, in_range: list[dict], log: list[dict], graph: dict, stories: list[dict],
                  config_diffs: bool = True, hits: set = frozenset(), earlier: list[dict] = ()) -> list[dict]:
    """BREAKER_* for the stories a live Story: commit of `in_range` closes (story files as `stories` has them, every
    copy of an id). What makes a story risky also comes from `earlier` versions of its file (the trunk's before the
    change under judgment: rewriting the front matter while closing opts nothing out, ESC-327) and from every commit
    of it in `log` that git found changing a risky path (`hits`), before the rule or already on the trunk (ESC-325,
    ESC-326); the rounds only from the files as they are now."""
    if rules is None:
        return []
    diffs = []
    if rules["problem"] and config_diffs:
        diffs.append({"level": "error", "code": "BREAKER_CONFIG", "detail": f"{rules['problem']}; until it is fixed "
                      "every story closed after the rule holds counts as risky"})
    reverted = revert_status(log, graph)
    closing: dict[str, str] = {}
    naming: dict[str, list[str]] = {}
    for c in reversed(in_range):  # oldest first
        if not reverted.get(c["sha"], False):
            for sid in c["story"]:
                closing.setdefault(sid, c["sha"])
    for c in reversed(log):
        for sid in dict.fromkeys(c["story"] + c["part_of"]):
            naming.setdefault(sid, []).append(c["sha"])
    by_id = {s["id"]: s for s in stories}
    before: dict[str, list[dict]] = {}
    for s in earlier:
        before.setdefault(s["id"], []).extend([s, *s.get("copies", [])])
    for sid, sha in sorted(closing.items()):
        story = by_id.get(sid) or missing_story(sid)
        if story["unreadable"]:
            diffs.append({"level": "error", "code": "BREAKER_MISSING", "detail": f"{sid}: closed by {short(sha)}, and "
                          f"its file {story['path']} cannot be read here, so its breaker rounds cannot be checked"})
            continue
        current = [story, *story.get("copies", [])]
        own = [x for x in naming.get(sid, ()) if x in hits]
        why = list(dict.fromkeys(w for v in current + before.get(sid, []) if not v.get("unreadable")
                                 for w in risky_reasons(v, rules, set(), own)))
        if not why:
            continue
        reason = "; ".join(why[:3]) + (f"; +{len(why) - 3} more" if len(why) > 3 else "")
        if len(current) > 1:
            diffs.append({"level": "warning", "code": "BREAKER_BAD_ENTRY", "detail": (
                f"{sid}: {len(current)} story files have this id ({', '.join(v['path'] for v in current)}); each is "
                "read for its risk, the rounds from the one that records them")})
        with_rounds = [v for v in current if any(e[0] == "round" for e in v["breaker"]["entries"])]
        story = with_rounds[0] if with_rounds else story
        record = story["breaker"]
        if record["bad"]:
            diffs.append({"level": "warning", "code": "BREAKER_BAD_ENTRY",
                          "detail": f"{sid} ({story['path']}): {record['bad'][0]}"})
        rounds = [(i, e) for i, e in enumerate(record["entries"]) if e[0] == "round"]
        if not rounds:
            diffs.append({"level": "error", "code": "BREAKER_MISSING", "detail": (
                f"{sid} is risky ({reason}) and {short(sha)} closed it with no breaker round recorded; fix: run the "
                f"cold breaker rounds (/keelokit:build-story, step 5) and record each under `## Breaker rounds` in "
                f"{story['path']}: {ROUND_FORMAT}")})
            continue
        decisions = [i for i, e in enumerate(record["entries"]) if e[0] == "decision" and is_decider(e[1], rules)]
        refused = [e for e in record["entries"] if e[0] == "decision" and not is_decider(e[1], rules)]
        if refused:
            who = (f"one of {RISKY_FILE}'s deciders ({', '.join(rules['deciders'])})" if rules["deciders"]
                   else "a person, never an agent or a model")
            diffs.append({"level": "warning", "code": "BREAKER_BAD_ENTRY",
                          "detail": f"{sid} ({story['path']}): {refused[0][2]!r}: a Decision is taken by {who}"})
        # The last round decides, whatever its number (HARN-022): clean, the story is resolved, past the cap too. The
        # cap is where the build stops and asks: findings left there wait for a person's Decision.
        last_at, last = rounds[-1]
        if not last[3] and not any(i > last_at for i in decisions):
            if len(rounds) >= rules["rounds"]:
                then = (f"the cap of {rules['rounds']} rounds ({RISKY_FILE}) is reached, so a person decides: another "
                        "round, or land as it is (`- Decision · <person> · <YYYY-MM-DD> · <what>`)")
            else:
                then = (f"below the cap of {rules['rounds']}: round {len(rounds) + 1} runs with a new cold breaker on "
                        "the fixed head (or a person's Decision line lands it as it is)")
            diffs.append({"level": "warning", "code": "BREAKER_UNRESOLVED", "detail": (
                f"{sid}: its last breaker round ({last[1]}, head {short(last[2])}) left findings, and no person's "
                f"Decision line follows it in {story['path']}; {then}")})
    return diffs


def rule_adds(tip: str) -> list[str]:
    """The commits `tip` reaches that added risky.toml (one path-limited `git log`)."""
    # -m: a merge whose own resolution adds the file is an add too (ESC-337).
    out = git_read(["log", "--full-history", "-m", "--format=%H", "--diff-filter=A", tip, "--", RISKY_FILE]).decode()
    return list(dict.fromkeys(out.split()))


def removed_rules() -> dict:
    """The rule when risky.toml was on the trunk and is gone or no file the ledger reads: it fails closed (ESC-331)."""
    return {**risky_config(None, True), "problem": f"{RISKY_FILE} was on the trunk and is gone: the rule still holds"}


def merge_own_hits(rules: dict, tip: str, exclude: list[str]) -> set[str]:
    """The merges whose OWN change (the combined diff against every parent: a resolution, a file neither side had)
    touches a risky path, from one `git log --cc` (ESC-333)."""
    out = git_read(["-c", "core.quotePath=false", "log", "--merges", "--full-history", "--cc", "--name-only",
                    "--format=%x00%H", tip, *(["--not", *exclude] if exclude else []), "--",
                    *(f":(glob){p}" for p in rules["paths"])]).decode(errors="replace")
    found = set()
    for chunk in out.split("\0")[1:]:
        lines = [line for line in chunk.split("\n") if line.strip()]
        if len(lines) > 1:
            found.add(lines[0].strip())
    return found


def release_only(c: dict) -> bool:
    """A `No-story: release` commit that changes only what a release writes (RELEASE_FILES; any package.json)."""
    if not any(category(v) == "release" for v in trailer_values(c["trailers"], "No-story")):
        return False
    paths = changed_paths([c["sha"]]).get(c["sha"], set())
    return bool(paths) and all(p in RELEASE_FILES or p.endswith("/package.json") for p in paths)


def risky_no_story(in_range: list[dict], hits: set, merges: set) -> list[dict]:
    """RISKY_NO_STORY: a commit after the rule's start that changes a risky path and names no story (a `No-story:`
    commit, an unattributed one, a merge whose own resolution does it): it is work of a story, which then needs its
    rounds (ESC-332, ESC-333). A release commit that touches only the release files is not."""
    diffs = []
    for c in reversed(in_range):
        if c["story"] or c["part_of"]:
            continue
        merge = len(c["parents"]) > 1
        if not (c["sha"] in merges if merge else c["sha"] in hits) or not merge and release_only(c):
            continue
        subject = c["message"].split("\n", 1)[0].strip()[:80]
        what = "a merge whose own resolution changes" if merge else "a commit that changes"
        diffs.append({"level": "error", "code": "RISKY_NO_STORY", "detail": (
            f"{short(c['sha'])} {subject!r}: {what} a risky path ({RISKY_FILE}, or one of {', '.join(ALWAYS_RISKY)}) "
            "and names no story; such a change is work of a story (Part-of:/Story:), which then needs its breaker "
            "rounds")})
    return diffs


def risky_after_close(in_range: list[dict], log: list[dict], graph: dict, hits: set, merges: set,
                      landing) -> list[dict]:
    """RISKY_AFTER_CLOSE (HARN-022): a commit of `in_range` (after the rule's start) that changes a risky path, or a
    merge whose own resolution does, under Story:/Part-of: of stories that were all closed already, by a live Story:
    commit of `log` with an earlier landing (`landing(sha)`: the position of the trunk commit that brought it; a pull
    request's commits land after every trunk commit). The closed story's rounds never saw the change, and it is not
    closed again: such a change is new work of an open story, which then needs its rounds. The closing branch's own
    later commits land with the close and are judged with it; a revert restores what was judged before."""
    reverted = revert_status(log, graph)
    closed: dict[str, tuple[int, str]] = {}
    for c in log:
        if reverted.get(c["sha"], False):
            continue
        for sid in c["story"]:
            at = landing(c["sha"])
            if sid not in closed or at < closed[sid][0]:
                closed[sid] = (at, c["sha"])
    diffs = []
    for c in reversed(in_range):
        ids = list(dict.fromkeys(c["story"] + c["part_of"]))
        merge = len(c["parents"]) > 1
        if not ids or c["reverts"] or reverted.get(c["sha"], False) \
                or not (c["sha"] in merges if merge else c["sha"] in hits):
            continue
        at = landing(c["sha"])
        if not all(sid in closed and closed[sid][0] < at for sid in ids):
            continue  # it names an open story: that story records the rounds when it closes
        subject = c["message"].split("\n", 1)[0].strip()[:80]
        what = "a merge whose own resolution changes" if merge else "a commit that changes"
        by = ", ".join(f"{sid} ({short(closed[sid][1])})" for sid in ids)
        diffs.append({"level": "error", "code": "RISKY_AFTER_CLOSE", "detail": (
            f"{short(c['sha'])} {subject!r}: {what} a risky path ({RISKY_FILE}) under stories already closed: {by}; "
            "their breaker rounds never saw it and they are not closed again, so name an open story (Part-of:/Story:) "
            "for it, which then needs its own breaker rounds")})
    return diffs


def story_versions(tip: str, paths: set[str], cfg: dict, ids: set[str] = frozenset(), cap: int = 20000) -> list[dict]:
    """Every committed version of these story files that `tip` reaches, under their earlier names too (renames are
    followed back, ESC-336), and of any story file named after one of `ids` (one `git log --raw -M` over the stories'
    glob and one `cat-file`, at most `cap` versions): risk is sticky, a risky version keeps the story risky (ESC-334)."""
    if not paths and not ids:
        return []
    out = git_read(["-c", "core.quotePath=false", "log", "--full-history", "--format=%x00%H", "--raw", "--no-abbrev",
                    "-M", tip, "--", f":(glob){cfg['stories']}"]).decode(errors="replace")
    # Every version of every story file is read, and each counts for the id its own front matter gives: a story moved
    # to a name that says nothing of its id keeps the risk of its earlier versions (ESC-345).
    versions: dict[str, str] = {}
    for line in out.splitlines():
        meta, tab, rest = line.partition("\t")
        fields, names = meta.split(), rest.split("\t")
        if not line.startswith(":") or not tab or len(fields) < 5:
            continue
        old, new = names[0], names[-1]
        for blob, path in ((fields[3], new), (fields[2], old)):
            if set(blob) != {"0"} and len(versions) < cap:
                versions.setdefault(blob, path)
    blobs = read_blobs(list(versions), tip)
    found = []
    for blob, path in versions.items():
        try:
            story = build_story(path, blobs.get(blob), cfg["id_from"]) if blobs.get(blob) is not None else None
        except LedgerError:
            story = None
        if story:
            found.append(story)
    return found


def closed_ids(in_range: list[dict]) -> set[str]:
    return {sid for c in in_range for sid in c["story"]}


def closed_paths(in_range: list[dict], *groups: list[dict]) -> set[str]:
    """The story files (every copy) of the ids a Story: commit of `in_range` names."""
    ids = {sid for c in in_range for sid in c["story"]}
    return {v["path"] for stories in groups for s in stories if s["id"] in ids
            for v in [s, *s.get("copies", [])] if not v.get("unreadable")}


def breaker_start(ctx: dict, rules: dict) -> tuple[list[str], list[dict]]:
    """The commits that mark where the rule starts on the trunk: the first to bring risky.toml to it (one
    path-limited `git log`), and its `since` when it names exactly one commit (else a warning). Empty: the trunk's history never added
    it (a merge's own resolution, a rules ref that brings it): no start, so every commit after `[ledger] since`."""
    graph = ctx["graph"]
    adds = [sha for sha in rule_adds(ctx["trunk_sha"]) if sha in graph]
    # The first add to reach the trunk is the start; a later one (the file deleted and added again, a side branch
    # that brings its own) moves nothing (ESC-311), nor does a later `since` (ESC-340).
    arrival, order = ctx["placed"]
    ct = {c["sha"]: c["ct"] for c in ctx["log"]}
    starts = [min(adds, key=lambda sha: (order[arrival[sha]], ct.get(sha, 0), sha))] if adds else []
    diffs = []
    # `since` counts as the file first had it: a later edit never exempts a closure already judged (ESC-340).
    first = None
    if starts:
        spec = f"{starts[0]}:{RISKY_FILE}"
        first = risky_config(cat_specs([spec]).get(spec), True)
    since = first["since"] if first and not first["problem"] else None
    if rules["since"] and rules["since"] != since:
        diffs.append({"level": "warning", "code": "BREAKER_CONFIG", "detail": (
            f"{RISKY_FILE}: since = {rules['since']!r} was not in the file when it reached the trunk; only that first "
            "version's since counts, so it exempts nothing")})
    if since:
        matches = [sha for sha in graph if sha.startswith(since)]
        if len(matches) == 1:
            starts.append(matches[0])
        else:
            diffs.append({"level": "warning", "code": "BREAKER_CONFIG", "detail": (
                f"{RISKY_FILE}: since = {since!r} names {'no commit' if not matches else 'several commits'} "
                "of the trunk's history; it exempts nothing")})
    return starts, diffs


def trunk_breaker_diffs(ctx: dict) -> list[dict]:
    """BREAKER_* for the trunk: the risky stories closed after the rule holds (the first commit that brought
    risky.toml, or its `since`; and `[ledger] since` when set), judged by the committed risky.toml (`--rules-ref`'s when given)."""
    rules = ctx.get("risky")
    if rules is None:
        if not rule_adds(ctx["trunk_sha"]):
            return []
        rules = removed_rules()  # deleting risky.toml never turns the rule off (ESC-331)
        diffs0 = [{"level": "error", "code": "BREAKER_CONFIG", "detail": f"{rules['problem']}; every story closed "
                   "after it started counts as risky"}]
    else:
        diffs0 = []
    # `[ledger] since` narrows the range when it names a commit; without one the rule still holds from the commit
    # that brought risky.toml (ESC-313): attribution may be optional there, the breaker rounds are not.
    in_range = since_range(ctx["cfg"], ctx["log"], ctx["graph"])
    in_range = ctx["log"] if in_range is None else in_range
    starts, diffs = breaker_start(ctx, rules)
    if starts:
        held = set(first_reach(ctx["graph"], starts))
        # A trunk commit that arrived before the add did is no later for coming off another branch (ESC-318).
        arrival, order = ctx["placed"]
        first = order[arrival[starts[0]]]
        in_range = [c for c in in_range if c["sha"] not in held and order[arrival[c["sha"]]] >= first]
    hits = risky_commits(rules, ctx["trunk_sha"], [])
    own = merge_own_hits(rules, ctx["trunk_sha"], [])
    diffs += risky_no_story(in_range, hits, own)
    arrival, order = ctx["placed"]
    diffs += risky_after_close(in_range, ctx["log"], ctx["graph"], hits, own, lambda sha: order[arrival[sha]])
    earlier = read_stories(starts[0], ctx["cfg"])[0] if starts else []  # the files as the rule found them
    earlier += story_versions(ctx["trunk_sha"], closed_paths(in_range, ctx["stories"], earlier), ctx["cfg"],
                              closed_ids(in_range))
    return diffs0 + diffs + breaker_diffs(rules, in_range, ctx["log"], ctx["graph"], ctx["stories"], hits=hits,
                                          earlier=earlier)


def work_tree_story(cfg: dict, sid: str) -> dict | None:
    """The story <ID> as the work tree's file has it (the branch may have just written it), else None."""
    pattern = glob_regex(cfg["stories"])
    base = Path(ROOT)
    head = cfg["stories"].split("*", 1)[0].rsplit("/", 1)[0]
    folder = base / head if head else base
    if not folder.is_dir():
        return None
    for path in sorted(folder.rglob("*")):
        rel = path.relative_to(base).as_posix()
        if path.is_file() and not path.is_symlink() and pattern.fullmatch(rel):
            try:
                story = build_story(rel, path.read_bytes(), cfg["id_from"])
            except (OSError, LedgerError):
                continue
            if story and story["id"] == sid:
                return story
    return None


def read_log_of(shas: list[str]) -> list[dict]:
    """The log records (trailers parsed) of exactly these commits, from one `git log --no-walk --stdin`."""
    fmt = ("%H%x00%P%x00%ct%x00%(trailers:key=Story,valueonly,separator=%x2C,unfold)%x00"
           "%(trailers:key=Part-of,valueonly,separator=%x2C,unfold)%x00")
    out = git_read(["log", "--no-walk=unsorted", "--stdin", "-z", f"--format={fmt}"],
                   "".join(f"{s}\n" for s in shas).encode()).decode(errors="replace").split("\0")
    return [{"sha": out[i], "story": story_ids(out[i + 3]), "part_of": story_ids(out[i + 4])}
            for i in range(0, len(out) - 5, 6)]


def merge_rules(a: dict | None, b: dict | None) -> dict | None:
    """The stricter reading of two risky.toml: either's paths and dimensions, the lower round cap."""
    if a is None or b is None:
        return a or b
    return {**a, "paths": sorted(set(a["paths"]) | set(b["paths"])),
            "dimensions": sorted(set(a["dimensions"]) | set(b["dimensions"])),
            "rounds": min(a["rounds"], b["rounds"]), "all": a["all"] or b["all"],
            "deciders": sorted(set(a["deciders"]) & set(b["deciders"])) if a["deciders"] and b["deciders"]
            else a["deciders"] or b["deciders"],
            "problem": a["problem"] or b["problem"]}


def cmd_risky(state: dict, sid: str) -> int:
    """`risky <ID>`: is the story risky, why, and the round cap. Rules: the trunk's committed risky.toml and the work
    tree's, the stricter of the two; the story: the work tree's file, else the trunk's; what changes: its touches and
    the branch's commits since it left the trunk (`git diff --name-only <trunk>...HEAD`). Exit 0, 2 no such story."""
    cfg = read_config(state)
    trunk = trunk_name(state)
    refs = read_refs(trunk, cfg["snapshot"])
    trunk_sha = refs.get(f"refs/remotes/origin/{trunk}") or refs.get(f"refs/heads/{trunk}")
    committed, story = None, work_tree_story(cfg, sid)
    if trunk_sha:
        tree = read_tree(trunk_sha)
        committed = read_trunk_files(trunk_sha, tree)["risky"]
        if story is None:
            story = next((s for s in read_stories(trunk_sha, cfg, tree)[0] if s["id"] == sid), None)
    local_path = Path(ROOT) / RISKY_FILE
    try:
        local = risky_config(local_path.read_bytes(), True) if local_path.is_file() else None
    except OSError:
        local = risky_config(None, True)
    rules = merge_rules(committed, local)
    if story is None:
        print(f"Keelokit: no story {sid} in the work tree or on the trunk", file=sys.stderr)
        return 2
    changed: set[str] = set()
    if trunk_sha:
        out = git_read(["-c", "core.quotePath=false", "diff", "--name-only", "--no-renames", f"{trunk_sha}...HEAD"],
                       ok=(0, 128)).decode(errors="replace")
        changed = {line for line in out.splitlines() if line.strip()}
    hits: list[str] = []
    if trunk_sha and rules:  # the story's commits already on the trunk count too (ESC-319)
        found = risky_commits(rules, trunk_sha, [])
        if found:
            hits = [c["sha"] for c in read_log_of(sorted(found)) if sid in c["story"] + c["part_of"]]
    why = risky_reasons(story, rules, changed, hits)
    cap = rules["rounds"] if rules else DEFAULT_ROUNDS
    if rules is None:
        print(f"Keelokit: no {RISKY_FILE} on the trunk or in the work tree: only `risky = true` makes a story risky")
    if rules and rules["problem"]:
        print(f"Keelokit: {rules['problem']} (every story counts as risky until it is fixed)")
    if why:
        print(f"{sid}: risky — {'; '.join(why[:6])}{f'; +{len(why) - 6} more' if len(why) > 6 else ''}")
        print(f"  build it with the cold breaker loop, each round recorded under `## Breaker rounds`: the last round "
              f"decides; at round {cap} with findings left, stop and ask a person")
    else:
        print(f"{sid}: not risky (breaker rounds: optional; cap {cap})")
    return 0


# ── attribution of a range (LEDGER-013: Harbor's `convoy add` asks it before it records a vessel) ──
# The contract, which Harbor builds against (docs/ledger.md, "attribution"): exit 0 when it answered, even with
# unattributed commits; 2 for a usage error or a range whose ends do not resolve; 3 when the history is incomplete.

RANGE_END = re.compile(r"[^\s.\-~^:][^\s]*")


def committed_state(sha: str) -> dict:
    """The committed .keelokit/state.toml of a commit, read as read_state reads the work tree's (absent or not TOML:
    the defaults); LedgerError when the commit has it and this (partial) clone lacks it."""
    return load_toml(read_trunk_files(sha, read_tree(sha), True)["state"]) or {}


def resolve_commit(rev: str) -> str | None:
    """The full sha of the commit `rev` names here, or None (an option-like or malformed rev included)."""
    if not RANGE_END.fullmatch(rev) or ".." in rev:
        return None
    sha = git_read(["rev-parse", "--verify", "-q", "--end-of-options", f"{rev}^{{commit}}"], ok=(0, 1, 128))
    sha = sha.decode().strip()
    return sha if FULL_SHA.fullmatch(sha) else None


def via_of(in_range: list[dict], fixed: set, covered: set) -> dict:
    """sha -> how attributed_in_range attributed it, for the commits in `covered` (which it computed): "own" (its own
    trailer, a merge's included), "correction" (an active correction row names it), else "merge" (a merge with one
    brings it or, for a merge, everything it brings is attributed)."""
    return {c["sha"]: "own" if c["attributed"] else "correction" if c["sha"] in fixed else "merge"
            for c in in_range if c["sha"] in covered}


def cmd_attribution(state: dict, args: tuple) -> int:
    """attribution <a>..<b> [--json]: each commit `b` reaches and `a` does not, in `git rev-list --reverse` order,
    attributed or not as `check` attributes it (attributed_in_range: its own trailer, an active correction row, a
    merge that brings it, a merge whose every commit it brings is attributed), with the arrivals of `b`'s first-parent
    chain (as `check --ci` reads a pull request). Commits `[ledger] since` reaches are left out, as `check` leaves
    them out; a `since` that names no commit here leaves the whole range. `diffs` adds what `check` would say of
    those commits (BAD_CATEGORY, UNKNOWN_STORY, STORY_NO_BODY, SQUASH_LOST_TRAILERS), stories read from `b`'s tree."""
    rng, as_json, rules_ref = args
    rules_sha = None
    if rules_ref is not None:
        rules_sha = resolve_commit(rules_ref)
        if rules_sha is None:
            print(f"Keelokit: attribution: --rules-ref {rules_ref!r} does not resolve to a commit here", file=sys.stderr)
            return 2
    ends = rng.split("..")
    if len(ends) != 2 or not all(RANGE_END.fullmatch(e) for e in ends):
        print(f"Keelokit: attribution needs one range <a>..<b> (two revisions, `..` between), not {rng!r}",
              file=sys.stderr)
        return 2
    shas = []
    for end in ends:
        sha = resolve_commit(end)
        if sha is None:
            print(f"Keelokit: attribution: {end!r} does not resolve to a commit here", file=sys.stderr)
            return 2
        shas.append(sha)
    a, b = shas
    # `[ledger]` (since, no_story, stories) is the trunk's committed state.toml, or <rev>'s: never the checkout's, which
    # the vessel under judgment writes.
    trunk = trunk_name(state)
    check_trunk(trunk)
    state = committed_state(rules_sha or resolve_trunk(trunk, read_refs(trunk)))
    ctx = read_all(state, rules_sha)
    if ctx["reason"] is not None:
        print(f"Keelokit: attribution: the history is incomplete ({ctx['reason']})", file=sys.stderr)
        return 3
    cfg = ctx["cfg"]
    graph = read_graph(sorted({a, b}))
    if cut_reason(graph, is_shallow() is not False):
        print(f"Keelokit: attribution: the history of {rng} is cut (a shallow clone); {FIX}", file=sys.stderr)
        return 3
    since = cfg["since"]
    matches = [x for x in graph if x.startswith(since.lower())] if since else []
    stops = sorted({a, *matches[:1]}) if len(matches) == 1 else [a]
    order = git_read(["rev-list", "--reverse", b, "--not", *stops]).decode().split()
    log = read_trunk_log(b, ("--not", *stops))
    in_shas = {c["sha"] for c in log}
    held = {x for x in graph if x not in in_shas}
    placed = arrivals(graph, b)
    fixed = corrected(ctx.get("corrections"))
    covered = attributed_in_range(log, log, graph, placed[0], held, fixed)
    via = via_of(log, fixed, covered)
    by_sha = {c["sha"]: c for c in log}
    commits = []
    for sha in order:
        c = by_sha[sha]
        no_story = ", ".join(v.strip() for v in trailer_values(c["trailers"], "No-story") if v.strip()) or None
        commits.append({"sha": sha, "subject": c["message"].split("\n", 1)[0].strip(), "story": list(c["story"]),
                        "part_of": list(c["part_of"]), "no_story": no_story, "merge": len(c["parents"]) > 1,
                        "attributed": sha in covered, "via": via.get(sha)})
    stories, unreadable = read_stories(b, cfg)
    rctx = {"cfg": cfg, "log": log, "graph": graph, "stories": stories, "unreadable": unreadable, "tip": b,
            "placed": placed, "refs": ctx["refs"], "trunk": ctx["trunk"],
            "unverified": ctx["unverified"], "corrections": ctx["corrections"]}
    diffs = [d for d in attribution_diffs(rctx, log, on_trunk=False) if d["code"] != "UNATTRIBUTED"]
    answer = {"schema": 1, "range": rng, "ok": all(c["attributed"] for c in commits if not c["merge"]),
              "commits": commits, "unattributed": [c["sha"] for c in commits if not c["attributed"]],
              "stories": sorted({i for c in commits for i in c["story"] + c["part_of"]}),
              "since": matches[0] if len(matches) == 1 else None, "diffs": diffs}
    if as_json:
        print(json.dumps(answer, indent=1))
        return 0
    for c in commits:
        if not c["attributed"]:
            kind = "a merge that brings commits without one" if c["merge"] else "no Story:, Part-of: or No-story:"
            print(CONTROL.sub("?", f"UNATTRIBUTED {short(c['sha'])} {c['subject'][:80]!r}: {kind}"))
    for d in diffs:
        print(CONTROL.sub("?", f"{d['level']} {d['code']} {d['detail']}"))
    print(f"{rng}: {len(commits)} commits, {len(answer['unattributed'])} unattributed"
          + (f"; stories: {', '.join(answer['stories'])}" if answer["stories"] else ""))
    return 0


# ── the CI snapshot and the deploy branches (LEDGER-011) ──
# keelokit/ledger (`[ledger] snapshot`) is an orphan branch only the CI writes: LEDGER.md and ledger.json (the facts of a
# trunk commit, for a session whose history is cut) and moves.toml (when each trunk commit reached the trunk, as the
# CI saw it). It is written with plumbing in a temporary index, never through a checkout, and a push the remote rejects
# starts again from the new tip, up to SNAPSHOT_TRIES times. deploy/staging and deploy/production point at the commit
# each environment runs; the template's deploy jobs move them with `ledger.py deploy`.

MOVES = "moves.toml"
SNAPSHOT_TRIES = 5
SNAPSHOT_AT = "KEELOKIT_SNAPSHOT_AT"  # the time the CI saw the push (epoch seconds or ISO 8601); now when unset
SNAPSHOT_IDENTITY = {"GIT_AUTHOR_NAME": "Keelokit ledger", "GIT_AUTHOR_EMAIL": "ledger@keelokit.invalid",
                     "GIT_COMMITTER_NAME": "Keelokit ledger", "GIT_COMMITTER_EMAIL": "ledger@keelokit.invalid"}
ISO_TIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
MOVES_HEADER = ("# Written by `ledger.py snapshot` in the CI, never by hand: when each trunk commit reached the trunk.\n"
                "# seen: the time the CI saw it; exact = false when a later run filled it in (its own run never\n"
                "# recorded it), so it reached the trunk at or before `seen`. left: a later run found it off the trunk\n"
                "# (forced away), so this row no longer says when it arrived.\n")
NULL_SHA = re.compile(r"0+")


def parse_moves(content: bytes | None) -> list[dict] | None:
    """The rows of a moves.toml ([] when there is none); None when it cannot be read or a row is malformed."""
    if content is None:
        return []
    try:
        data = tomllib.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    rows = data.get("move", [])
    if not isinstance(rows, list):
        return None
    out = []
    for r in rows:
        if not (isinstance(r, dict) and isinstance(r.get("sha"), str) and FULL_SHA.fullmatch(r["sha"])
                and isinstance(r.get("seen"), str) and ISO_TIME.fullmatch(r["seen"])
                and isinstance(r.get("run"), str) and isinstance(r.get("exact"), bool)
                and ("left" not in r or isinstance(r["left"], str) and ISO_TIME.fullmatch(r["left"]))):
            return None
        out.append({k: r[k] for k in ("sha", "seen", "run", "exact", "left") if k in r})
    return out


def moves_toml(moves: list[dict]) -> str:
    rows = [f'[[move]]\nsha = "{m["sha"]}"\nseen = "{m["seen"]}"\nrun = {toml_str(m["run"])}\n'
            f'exact = {"true" if m["exact"] else "false"}\n' + (f'left = "{m["left"]}"\n' if "left" in m else "")
            for m in moves]
    return MOVES_HEADER + "".join(f"\n{r}" for r in rows)


def better_move(old: dict, new: dict) -> bool:
    """True when `new` says more about the same commit than `old`. Exact beats not exact: a not-exact row is filled in
    by a later push's run, so its time is an upper bound and the exact one is the truth (ESC-246). Of two exact rows
    the later wins: only a commit that landed again (pushed, forced away, pushed again) has two, and its arrival is
    the last landing (ESC-247). Of two not-exact rows the earlier, the tighter bound."""
    if "left" in old and new["seen"] > old["left"]:
        return True  # the commit came back after it was forced away: the old row says nothing now (round 4)
    if "left" in new and new["seen"] > new["left"]:
        return False
    if (new["sha"], new["seen"], new["run"]) == (old["sha"], old["seen"], old["run"]):
        return new.get("left", "") > old.get("left", "")  # the same row, now known to have left
    if new["exact"] != old["exact"]:
        return new["exact"]
    return new["seen"] > old["seen"] if new["exact"] else new["seen"] < old["seen"]


def moves_map(moves: list[dict] | None) -> dict[str, dict]:
    found: dict[str, dict] = {}
    for m in moves or ():
        if m["sha"] not in found or better_move(found[m["sha"]], m):
            found[m["sha"]] = m
    return found


def snapshot_moves(refs: dict) -> dict[str, dict]:
    """sha -> move of origin/<snapshot>'s moves.toml (one `cat-file`, only when the branch is here); {} otherwise."""
    head = refs.get("snapshot")
    if not head:
        return {}
    return moves_map(parse_moves(cat_specs([f"{head}:{MOVES}"]).get(f"{head}:{MOVES}")))


def apply_moves(records: list[dict], moves: dict[str, dict], graph: dict) -> None:
    """A story's time from the recorded moves (a row marked `left` says nothing). Its commit's own exact move first:
    that push brought it, even when a later merge made it a second parent (a foxtrot merge, round 4). Else its
    first-parent arrival's move, exact as that move is, when no earlier move already held the commit; when one did,
    the commit was on the trunk by then: that time, not exact. A commit whose arrival has no move keeps its date."""
    live = sorted((m for m in moves.values() if "left" not in m), key=lambda m: m["seen"])
    if not live:
        return
    held = first_reach(graph, [m["sha"] for m in live])
    for rec in records:
        commit = rec.get("commit")
        own = moves.get(commit or "")
        if not commit:
            continue
        if own and own["exact"] and "left" not in own:
            rec["since"], rec["since_exact"] = own["seen"], True
            continue
        at = moves.get(rec.get("arrival") or "")
        if not at or "left" in at or commit not in held:
            continue
        first = live[held[commit]]
        rec["since"], rec["since_exact"] = first["seen"], first is at and at["exact"]


def parse_snapshot(content: bytes | None) -> dict | None:
    """A snapshot's ledger.json when it is schema 1 of a full trunk sha with well-formed stories; else None."""
    try:
        data = json.loads(content.decode("utf-8")) if content is not None else None
    except (UnicodeDecodeError, ValueError):
        return None
    if not (isinstance(data, dict) and data.get("schema") == 1 and not isinstance(data.get("schema"), bool)
            and isinstance(data.get("trunk_sha"), str) and FULL_SHA.fullmatch(data["trunk_sha"])
            and isinstance(data.get("stories"), list)):
        return None
    for rec in data["stories"]:
        env = rec.get("environments") if isinstance(rec, dict) else None
        if not (isinstance(rec, dict) and isinstance(rec.get("id"), str) and rec.get("state") in (*STATES, "unknown")
                and (rec.get("commit") is None or isinstance(rec["commit"], str) and FULL_SHA.fullmatch(rec["commit"]))
                and isinstance(env, dict) and set(env) == set(ENVIRONMENTS)
                and all(v is None or isinstance(v, str) and FULL_SHA.fullmatch(v) for v in env.values())
                and (rec.get("version") is None or isinstance(rec["version"], str))
                and all(k not in rec or k == "swarm" or carried_ok(k, rec[k]) for k in CARRIED)):
            return None
    return data


def carried_ok(key: str, value) -> bool:
    """A value of a story record a snapshot carries has the type `--json` gives it (ESC-253: a hand edit is no crash)."""
    if key in ("since_exact", "reconstructed", "reverted"):
        return isinstance(value, bool)
    if key in ("since",):
        return value is None or isinstance(value, str) and bool(ISO_TIME.fullmatch(value))
    if key in ("commit", "arrival"):
        return value is None or isinstance(value, str) and bool(FULL_SHA.fullmatch(value))
    if key == "convoy":
        return value is None or isinstance(value, int) and not isinstance(value, bool)
    if key in ("version", "candidate", "reconstructed_by", "reason"):
        return value is None or isinstance(value, str)
    if key == "correction":
        return value is None or isinstance(value, dict)
    if key in ("branches", "signals"):
        return isinstance(value, list) and all(isinstance(x, str) for x in value)
    if key == "attempts":
        return isinstance(value, list) and all(isinstance(x, dict) and isinstance(x.get("commit"), str)
                                               and isinstance(x.get("date"), str) and isinstance(x.get("reason"), str)
                                               and isinstance(x.get("branches"), list) for x in value)
    if key == "swarm":
        return isinstance(value, list) and all(swarm_entry_ok(x) for x in value)
    return value is None or isinstance(value, str)


def swarm_entry_ok(x) -> bool:
    """A `swarm` entry of a snapshot has the shape apply_swarm gives it (a hand edit is no crash in `show`)."""
    sha = lambda v: isinstance(v, str) and bool(FULL_SHA.fullmatch(v))  # noqa: E731
    text = lambda v: isinstance(v, str) and not SWARM_UNSAFE.search(v)  # noqa: E731
    return (isinstance(x, dict) and set(x) == SWARM_KEYS and isinstance(x["task"], str)
            and bool(SWARM_TASK.fullmatch(x["task"])) and x["state"] in SWARM_STATES
            and (x["branch"] is None or text(x["branch"])) and (x["head"] is None or sha(x["head"]))
            and isinstance(x["commits"], list) and all(sha(c) for c in x["commits"])
            and isinstance(x["authors"], list) and all(text(a) for a in x["authors"])
            and (x["convoy"] is None or is_int(x["convoy"])))


def reach_info(graph: dict, cut: set, head: str) -> tuple[set, bool]:
    """(what `head` reaches in this clone, whether the walk met the end of the clone's history)."""
    seen, stack, met = set(), [head], False
    while stack:
        sha = stack.pop()
        if sha in seen:
            continue
        seen.add(sha)
        if sha not in graph or sha in cut:
            met = True
        stack.extend(graph.get(sha, ()))
    return seen, met


def contains(info: tuple[set, bool], sha: str) -> bool | None:
    """True or False when this clone proves it, None when the commit may be past the end of its history."""
    reached, met = info
    return True if sha in reached else None if met else False


CARRIED = ("state", "since", "since_exact", "commit", "arrival", "convoy", "version", "candidate", "reconstructed",
           "reconstructed_by", "correction", "reverted", "branches", "attempts", "swarm", "signals", "reason")


def snapshot_view(cfg: dict, trunk: str, trunk_sha: str, refs: dict, graph: dict, stories: list[dict],
                  tree: list | None = None) -> dict | None:
    """The states of a shallow clone from origin/<snapshot>: each as of the snapshot's trunk commit (`as_of`), then
    what this clone can still prove since: a Story: commit or a revert after it, a tag or a deploy branch that moved
    (proved both ways, else unknown, never a lower state). None when there is no readable snapshot."""
    head = refs.get("snapshot") if cfg["snapshot"] else None
    if not head:
        return None
    blobs = cat_specs([f"{head}:ledger.json", f"{head}:{MOVES}"])
    snap = parse_snapshot(blobs.get(f"{head}:ledger.json"))
    if snap is None:
        return None
    moves = moves_map(parse_moves(blobs.get(f"{head}:{MOVES}")))
    sha = snap["trunk_sha"]
    meta = snap.get("snapshot") if isinstance(snap.get("snapshot"), dict) else {}
    # When the snapshot's own commit was seen, from its move only: a run's time is its push's, and its checkout may
    # already hold a later push (round 4).
    seen = moves[sha]["seen"] if sha in moves and "left" not in moves[sha] else None
    old = {r["id"]: r for r in snap["stories"]}
    story_shas = meta.get("story_commits")
    if not (isinstance(story_shas, dict) and all(isinstance(v, list) and all(isinstance(x, str) and FULL_SHA.fullmatch(x)
                                                                              for x in v) for v in story_shas.values())):
        story_shas = None
    undone_shas = meta.get("reverted_commits")
    if not (isinstance(undone_shas, dict) and all(isinstance(v, list) for v in undone_shas.values())):
        undone_shas = None
    cut = shallow_marks() & set(graph)
    records = {}
    for story in stories:
        rec = new_story(story)
        if story["id"] in old and not story.get("unreadable"):
            rec.update({k: old[story["id"]].get(k, rec[k]) for k in CARRIED})
            # Swarm's lists are data a push to a swarm branch wrote: a bad entry is left out, never the snapshot (ESC-348)
            rec["swarm"] = [x for x in rec["swarm"] if swarm_entry_ok(x)] if isinstance(rec["swarm"], list) else []
            rec["environments"] = dict(old[story["id"]]["environments"])
        elif not story.get("unreadable"):  # ESC-251: a story file written after the snapshot
            if story_shas is None:
                mark_unknown([rec], f"the snapshot predates the story file and does not list its commits; {FIX}")
            elif story_shas.get(story["id"]):
                rec.update(commit=story_shas[story["id"]][0], state="on-trunk", _fresh=True)
        rec["as_of"] = sha
        records[story["id"]] = rec
    diffs = []
    # What reached the trunk after the snapshot's commit, as far as this clone sees.
    if sha != trunk_sha and sha in graph and sha not in first_reach(graph, [trunk_sha]):
        # ESC-248: the snapshot is of a commit the trunk no longer holds (forced back or rewritten)
        diffs.append({"level": "warning", "code": "SNAPSHOT_BEHIND",
                      "detail": f"origin/{cfg['snapshot']} is of {short(sha)}, which {trunk} ({short(trunk_sha)}) no "
                                "longer holds: the trunk was rewritten since, so nothing it says holds now"})
        mark_unknown(list(records.values()), f"the snapshot is of {short(sha)}, which {trunk} no longer holds; {FIX}")
        trunk_swarm_stale(records)
        in_progress_stale(records, None)
    elif sha != trunk_sha:
        newer: set = set()
        if sha in graph:
            newer = reach_until(graph, [trunk_sha], set(first_reach(graph, [sha])))
            complete = not (newer & cut)
            log = read_trunk_log(trunk_sha, ("--not", sha))
        else:
            complete, log = False, read_trunk_log(trunk_sha)
        count = (f"{len(log)} commit{'s' if len(log) != 1 else ''} behind" if complete
                 else "behind by a number of commits this clone cannot count")
        diffs.append({"level": "warning", "code": "SNAPSHOT_BEHIND",
                      "detail": f"origin/{cfg['snapshot']} is of {trunk}@{short(sha)}"
                                f"{f', seen {seen}' if seen else ''}, {count} ({trunk} is at {short(trunk_sha)}); "
                                "states are as of that commit, with what this clone proves since"})
        if not complete:  # ESC-212: what reached the trunk since may be past this clone; nothing can be proved
            mark_unknown([r for r in records.values() if r["state"] != "unknown"],
                         f"the snapshot is of {short(sha)} and this clone does not reach back to it, so what reached "
                         f"{trunk} since cannot be read; {FIX}")
        else:
            settle_newer(records, log, graph, cut, trunk_sha, moves, story_shas, undone_shas)
        if not complete or any(c["reverts_said"] for c in log):  # ESC-349: what landed since may undo a delivery
            trunk_swarm_stale(records)
        in_progress_stale(records, newer if complete else None)
    settle_corrections(records, tree or [], trunk_sha, meta)
    settle_refs(records, refs, graph, cut, meta.get("refs") if isinstance(meta.get("refs"), dict) else {})
    settle_snapshot_states(stories, records)
    return {"sha": sha, "stories": list(records.values()), "diffs": diffs, "seen": seen}


def trunk_swarm_stale(records: dict) -> None:
    """Leave out the deliveries a snapshot read on the trunk (on-trunk, reverted) when this clone cannot vouch for
    them now: a revert landed since (or may have), or the trunk was rewritten. Information only, so it is dropped,
    never guessed (ESC-349); a full history reads them again."""
    for rec in records.values():
        rec["swarm"] = [e for e in rec["swarm"] if e["state"] == "in-progress"]


def in_progress_stale(records: dict, landed: set | None) -> None:
    """Leave out a snapshot's in-progress deliveries that may have landed since (HARN-022): one whose head or any commit
    is among the trunk commits after the snapshot's (`landed`), or every one when this clone cannot list those (None:
    the trunk was rewritten, or what landed since is past the clone). A delivery merged since is on the trunk or was
    reverted, never in progress; information only, so it is dropped, never guessed (as ESC-349)."""
    for rec in records.values():
        rec["swarm"] = [e for e in rec["swarm"] if e["state"] != "in-progress" or landed is not None
                        and e["head"] not in landed and not landed.intersection(e["commits"])]


def settle_newer(records: dict, log: list[dict], graph: dict, cut: set, trunk_sha: str, moves: dict,
                 story_shas: dict | None = None, undone_shas: dict | None = None) -> None:
    """Story: commits and reverts in the trunk commits after the snapshot's commit (the log holds exactly those). A
    revert of a commit older than the snapshot that is no story's commit may undo an old revert (ESC-213) or a merge
    this clone cannot read: the stories it could change are unknown."""
    reverted = revert_status(log, graph)
    in_log = {c["sha"] for c in log}
    landed = {r["commit"] for r in records.values() if r["commit"]}
    undone, unsure, unrevert = set(), False, False
    for c in log:
        if reverted[c["sha"]]:
            continue
        for target in c["reverts"]:
            if target in in_log:
                continue  # revert_status already read it
            parents = graph.get(target)
            if parents is None or target in cut or len(parents) > 1 and reach_info(graph, cut, target)[1]:
                unsure = unrevert = True  # past this clone: a merge, a revert, anything
            elif len(parents) < 2 and target not in landed:
                unrevert = True
            undone.update(brought_by(graph, target))
    placed = arrivals(graph, trunk_sha)
    ct = {c["sha"]: c["ct"] for c in log}
    commits, _ = story_commits(log, reverted, *placed)
    for sid, rec in records.items():
        if rec["state"] == "unknown":
            continue
        if unrevert and ((rec["reverted"] and not rec["commit"]) or undone_shas is None or undone_shas.get(sid)):
            # a reverted Story: commit of it may be back (round 4: also when a later one is its commit now)
            mark_unknown([rec], "a revert after the snapshot may undo the revert the snapshot read; " + FIX)
            continue
        others = None if story_shas is None else [c for c in story_shas.get(sid, ()) if c not in undone]
        if rec["commit"] and rec["commit"] in undone and others != []:
            # ESC-250: another Story: commit of it may still be on the trunk (or the snapshot does not say)
            mark_unknown([rec], f"a revert after the snapshot undid {short(rec['commit'])}, and another Story: commit of "
                                f"it may still be on the trunk; {FIX}")
            continue
        if rec["commit"] and rec["commit"] in undone:
            rec.update(commit=None, arrival=None, since=None, since_exact=False, version=None, candidate=None,
                       environments=dict.fromkeys(ENVIRONMENTS), reverted=True, reconstructed=False, correction=None,
                       reconstructed_by=None, state="ready")
        elif rec["commit"] and unsure and rec["commit"] not in ct:
            mark_unknown([rec], "a revert of a merge after the snapshot reaches past this clone's history; " + FIX)
            continue
        if sid in commits and not rec["commit"]:
            c = commits[sid]
            arrival = placed[0][c]
            rec.update(commit=c, arrival=arrival, since=iso(ct.get(arrival, ct[c])), since_exact=False,
                       reverted=False, state="on-trunk", environments=dict.fromkeys(ENVIRONMENTS), version=None,
                       candidate=None)
            own = moves.get(c)
            if own and own["exact"] and "left" not in own:
                rec["since"], rec["since_exact"] = own["seen"], True
            elif arrival in moves and "left" not in moves[arrival]:
                rec["since"], rec["since_exact"] = moves[arrival]["seen"], moves[arrival]["exact"]


def settle_corrections(records: dict, tree: list, trunk_sha: str, meta: dict | None = None) -> None:
    """The trunk's corrections file, which this clone can read even when its history is cut, against the one the
    snapshot was computed with (`meta["corrections"]`, its blob). The same file: nothing to do. Otherwise (ESC-214,
    ESC-252) a reconstructed story may have lost its row, and a story a row names that the snapshot has no commit for
    may have gained one: unknown. An unreadable file makes every story without a commit unknown too."""
    blob = next((sha for path, sha in tree if path == CORRECTIONS), None)
    if isinstance(meta, dict) and "corrections" in meta and meta["corrections"] == blob:
        return
    why = f"{CORRECTIONS} changed since the snapshot; {FIX}"
    for rec in records.values():
        if rec["state"] != "unknown" and rec["reconstructed"]:
            mark_unknown([rec], why)
    if blob is None:
        return
    content = read_blobs([blob], trunk_sha).get(blob)
    rows, err = parse_rows(content) if content is not None else (None, "not in this clone")
    named = {r.get("story") for r in rows or () if isinstance(r, dict) and r.get("kind") != "retract"}
    for sid, rec in records.items():
        if rec["state"] != "unknown" and not rec["commit"] and (rows is None or sid in named):
            mark_unknown([rec], why if rows is not None else f"{CORRECTIONS} cannot be read ({err}); {FIX}")


def settle_refs(records: dict, refs: dict, graph: dict, cut: set, then: dict) -> None:
    """Deploy branches and version tags against what the snapshot saw (`then`: its refs). A deploy branch this clone
    does not have keeps the snapshot's reading; one that moved is proved to contain the commit or not, else (or a
    forward move from the snapshot's head) the state is unknown. A new tag can give a version the snapshot lacked."""
    deploys = then.get("deploy") if isinstance(then.get("deploy"), dict) else None
    tags_then = then.get("tags") if isinstance(then.get("tags"), dict) else None
    infos: dict[str, tuple] = {}

    def info(head: str) -> tuple:
        if head not in infos:
            infos[head] = reach_info(graph, cut, head)
        return infos[head]

    local_tags = {name: sha for key, name, sha in version_tags(refs)}
    new_tags = [(name, sha) for key, name, sha in version_tags(refs) if key[1] == 1
                and (tags_then is None or tags_then.get(name) != sha)]
    all_tags = [(name, sha) for key, name, sha in version_tags(refs) if key[1] == 1]
    for rec in records.values():
        fresh = rec.pop("_fresh", False)  # a commit the snapshot read for no story: every ref is read for it
        if rec["state"] == "unknown" or not rec["commit"]:
            continue
        for env in ENVIRONMENTS:
            head = refs.get(f"refs/remotes/origin/deploy/{env}")
            was = deploys.get(env) if deploys is not None else None
            if head is None and (rec["environments"][env] or was):
                # ESC-215: the snapshot saw this environment and the clone has no branch to say where it is now (a
                # single-branch clone; a deploy writes no snapshot): a rollback may have happened.
                mark_unknown([rec], f"this clone has no origin/deploy/{env} to tell where {env} is now; {FIX}")
                break
            if head is None or (not fresh and deploys is not None and env in deploys and head == was):
                continue
            proved = contains(info(head), rec["commit"])
            if proved is None and rec["environments"][env] and was and contains(info(head), was):
                proved = True  # a forward move from a head that already held the commit
            if proved is None:
                mark_unknown([rec], f"deploy/{env} moved to {short(head)} after the snapshot and this clone's history "
                                    f"cannot tell whether it holds {short(rec['commit'])}; {FIX}")
                break
            rec["environments"][env] = head if proved else None
        version = rec["version"]
        if version and version in local_tags and tags_then is not None and local_tags[version] != tags_then.get(version):
            rec["version"] = None  # ESC-216: the tag moved since the snapshot; read it again with the new tags
        if rec["state"] == "unknown" or rec["version"]:
            continue
        for name, sha in (all_tags if fresh else new_tags):
            proved = contains(info(sha), rec["commit"])
            if proved is None:
                mark_unknown([rec], f"tag {name} came after the snapshot and this clone's history cannot tell whether "
                                    f"it holds {short(rec['commit'])}; {FIX}")
                break
            if proved:
                rec["version"] = name
                break


def settle_snapshot_states(stories: list[dict], records: dict) -> None:
    """The state from the facts carried and proved: an environment, a version, the trunk; without a commit, ready when
    every dependency has one (unknown when one is unknown), in progress when the snapshot saw a branch."""
    for rec in records.values():
        if rec["state"] == "unknown" or not rec["commit"]:
            continue
        envs = rec["environments"]
        rec["state"] = ("in-production" if envs["production"] else "in-staging" if envs["staging"]
                        else "in-version" if rec["version"] else "on-trunk")
    for story in stories:
        rec = records[story["id"]]
        if story.get("unreadable"):
            mark_unknown([rec], f"the story file {story['path']} cannot be read from the trunk's tree")
        if rec["state"] == "unknown" or rec["commit"]:
            continue
        deps = [records.get(d) for d in story["depends_on"]]
        if any(d is not None and d["state"] == "unknown" for d in deps):
            mark_unknown([rec], "a dependency is unknown")
            continue
        ready = all(d is not None and d["commit"] for d in deps)
        rec["state"] = "in-progress" if rec["branches"] else "ready" if ready else "defined"
        rec["convoy"] = None  # a delivery the snapshot saw is not this clone's to state (LEDGER-013)


def snapshot_time() -> int:
    """KEELOKIT_SNAPSHOT_AT as epoch seconds: digits, or an ISO 8601 time with its zone (a zoneless one would be read
    in the runner's zone), between 1970 and 9999 (ESC-254); now when unset."""
    raw = os.environ.get(SNAPSHOT_AT, "").strip()
    if not raw:
        return int(time.time())
    epoch = None
    if raw.isdigit():
        epoch = int(raw)
    else:
        try:
            when = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            epoch = int(when.timestamp()) if when.tzinfo is not None else None
        except (ValueError, OverflowError):
            epoch = None
    if epoch is None or not 0 < epoch <= 253402300799:
        raise LedgerError(f"{SNAPSHOT_AT}={raw[:40]!r} is not epoch seconds nor an ISO 8601 time with its zone, "
                          "between 1970 and 9999")
    return epoch


def check_snapshot_name(name: str) -> None:
    if name.startswith("-") or git_out("check-ref-format", f"refs/heads/{name}")[0]:
        raise LedgerError(f"[ledger] snapshot = {name!r} is not a branch name")


def fetch_snapshot(name: str) -> tuple[bool, str | None, str]:
    """(fetched, origin/<name>'s commit or None when origin has no such branch, git's error)."""
    code, err = run_git(["fetch", "-q", "--no-tags", "origin", f"+refs/heads/{name}:refs/remotes/origin/{name}"], 60)
    if code == 0:
        return True, commit_of(f"refs/remotes/origin/{name}"), ""
    if code is not None and "couldn't find remote ref" in err.lower():
        git_out("update-ref", "-d", f"refs/remotes/origin/{name}")
        return True, None, ""
    return False, None, last_error(err) if code is not None else "the fetch took over 60s"


def new_moves(graph: dict, known: dict, push: tuple, seen: str, run: str) -> list[dict]:
    """The moves this run records, only from its own push (`push`: before, after, whether before was all zeros), along
    `after`'s own first-parent chain (a later foxtrot merge may have taken it off the trunk's, round 4). Exact: the
    commits from `after` down that `before` does not hold, which that push brought. Not exact: the commits below them
    back to the newest recorded one still on the trunk (`known`), which a run of their own never recorded (GitHub's
    concurrency replaces a pending run with a newer one): they had arrived by this push. Nothing above `after` (later
    pushes this checkout already sees, ESC-246), nothing without a push (a tag's run), nothing when this clone lacks
    `before` (a forced push: what it brought cannot be told), and only `after` for an all-zero `before` (a history
    pushed to a new remote: its old commits were not just written)."""
    before, after, null = push
    if after is None or after not in graph or (before is None and not null):
        return []
    if null:
        return [{"sha": after, "seen": seen, "run": run, "exact": True}]
    chain = first_parent_chain(graph, after)
    held = set(first_reach(graph, [before]))
    i, rows = 0, []
    while i < len(chain) and chain[i] not in held:
        rows.append({"sha": chain[i], "seen": seen, "run": run, "exact": True})
        i += 1
    filled = []
    while i < len(chain) and chain[i] not in known:
        filled.append(chain[i])
        i += 1
    if i < len(chain):  # bounded by a recorded move: never back to the root on a first snapshot
        rows += [{"sha": sha, "seen": seen, "run": run, "exact": False} for sha in filled]
    return rows


def merge_moves(old: list[dict], new: list[dict], graph: dict, trunk_sha: str) -> list[dict]:
    """Every move once (the better one of the same commit), oldest first along this trunk; the moves of commits this
    clone does not have (pushed after its checkout) keep their order after them."""
    pos = {sha: i for i, sha in enumerate(reversed(first_parent_chain(graph, trunk_sha)))}
    merged: dict[str, dict] = {}
    order: dict[str, int] = {}
    for i, m in enumerate(old + new):
        if m["sha"] not in merged or better_move(merged[m["sha"]], m):
            merged[m["sha"]] = m
        order.setdefault(m["sha"], i)
    return sorted(merged.values(), key=lambda m: (pos.get(m["sha"], len(pos)), order[m["sha"]]))


def keep_theirs(theirs: dict | None, mine: str, seen: str, graph: dict) -> bool:
    """True when the branch's ledger.json is of a newer trunk than this run's (a descendant of its trunk, or a commit
    this run does not have that a later push brought), so a stale run never puts an older reading back. A commit this
    run does not have counts as newer only when it was seen later: after a rewrite of the trunk the old reading's
    commit never comes back, and the current trunk gets its reading again (ESC-209)."""
    if theirs is None:
        return False
    sha = theirs["trunk_sha"]
    meta = theirs.get("snapshot") if isinstance(theirs.get("snapshot"), dict) else {}
    later = isinstance(meta.get("seen"), str) and meta["seen"] > seen
    if sha != mine and sha in graph and sha in first_reach(graph, [mine]):
        return False  # theirs is of an ancestor of this trunk
    return later  # the same commit, or one this trunk does not hold (newer, or a trunk forced back: ESC-248)


def ledger_md(facts: dict, meta: dict) -> str:
    lines = [f"# Ledger — {facts['trunk']}@{short(facts['trunk_sha'])}", "",
             f"Written by `ledger.py snapshot` in the CI (run {meta['run']}, for the push of {meta['seen']}), never by "
             "hand. Ask "
             "`python3 .keelokit/bin/ledger.py`: a session reads this only when its history is incomplete.", "",
             "| Story | State | Since | Commit | Version | Staging | Production |", "|---|---|---|---|---|---|---|"]
    for r in sorted(facts["stories"], key=lambda r: id_key(r["id"])):
        since = f"{r['since']} ({'exact' if r['since_exact'] else 'approximate'})" if r["since"] else "—"
        cells = [r["id"], r["state"], since, short(r["commit"]) if r["commit"] else "—", r["version"] or "—",
                 *(short(r["environments"][e]) if r["environments"][e] else "—" for e in ENVIRONMENTS)]
        lines.append("| " + " | ".join(c.replace("|", "\\|") for c in cells) + " |")
    return "\n".join(lines) + "\n"


def snapshot_commit(files: dict[str, bytes], parent: str | None, message: str, epoch: int) -> str:
    """A commit of exactly these files, on `parent`: blobs, a temporary index, a tree and commit-tree. The checkout,
    its index and HEAD are never touched."""
    with tempfile.TemporaryDirectory(prefix="keelokit-snapshot-") as tmp:
        env = {"GIT_INDEX_FILE": os.path.join(tmp, "index"), **SNAPSHOT_IDENTITY,
               "GIT_AUTHOR_DATE": f"@{epoch} +0000", "GIT_COMMITTER_DATE": f"@{epoch} +0000"}
        entries = []
        for path, data in sorted(files.items()):
            blob = git_read(["hash-object", "-w", "--stdin"], data, env=env).decode().strip()
            entries.append(f"100644 {blob}\t{path}\n")
        git_read(["update-index", "--add", "--index-info"], "".join(entries).encode(), env=env)
        tree = git_read(["write-tree"], env=env).decode().strip()
        return git_read(["commit-tree", tree, *(["-p", parent] if parent else []), "-F", "-"], message.encode(),
                        env=env).decode().strip()


def push_range(text: str | None) -> tuple[str | None, str | None, bool]:
    """(before, after, before is all zeros) of `--push BEFORE..AFTER` as commits here; an unknown sha is None."""
    if not text:
        return None, None, False
    before, sep, after = text.partition("..")
    if not sep:
        raise LedgerError(f"--push {text!r}: expected BEFORE..AFTER")
    null = bool(NULL_SHA.fullmatch(before))
    return (commit_of(before) if before and not null else None,
            commit_of(after) if after and not NULL_SHA.fullmatch(after) else None, null)


def cmd_snapshot(state: dict, args: tuple) -> int:
    """`snapshot [--run ID] [--push BEFORE..AFTER]`: the CI's job. `snapshot --branch`: the branch, empty when off."""
    run, push, branch_only = args
    cfg = read_config(state)
    name = cfg["snapshot"]
    if branch_only:
        print(name)
        return 0
    if not name:
        print('Keelokit: [ledger] snapshot = "": the snapshot is off; nothing written.')
        return 0
    check_snapshot_name(name)
    if not snapshot_usable(name, trunk_name(state)):
        raise LedgerError(f"[ledger] snapshot = {name!r} is the trunk or a deploy branch: the snapshot needs a branch "
                          f"of its own (the default is {DEFAULT_SNAPSHOT})")
    if not run:
        gh = os.environ.get("GITHUB_RUN_ID", "").strip()
        run = f"{gh}.{os.environ.get('GITHUB_RUN_ATTEMPT', '1').strip() or '1'}" if gh else "local"
    if not RUN_ID.fullmatch(run):
        raise LedgerError(f"--run {run!r}: letters, digits, dots, dashes and underscores")
    epoch = snapshot_time()
    seen = iso(epoch)
    fetched, tip, err = fetch_snapshot(name)
    ctx = read_all(state)
    if ctx["reason"] is not None:
        raise LedgerError(f"the snapshot needs the trunk's whole history (the CI checks out with fetch-depth: 0): "
                          f"{ctx['reason']}")
    push_at = push_range(push)
    trunk, trunk_sha, graph = ctx["trunk"], ctx["trunk_sha"], ctx["graph"]
    refs_seen = {"tags": {n: sha for _, n, sha in version_tags(ctx["refs"])},
                 "deploy": {e: ctx["refs"].get(f"refs/remotes/origin/deploy/{e}") for e in ENVIRONMENTS}}
    reverted = revert_status(ctx["log"], graph)
    story_shas: dict[str, list[str]] = {}
    undone_shas: dict[str, list[str]] = {}
    for c in reversed(ctx["log"]):  # oldest first
        for sid in c["story"]:
            (undone_shas if reverted[c["sha"]] else story_shas).setdefault(sid, []).append(c["sha"])
    corrections_blob = next((sha for path, sha in ctx["tree"] if path == CORRECTIONS), None)
    # What a shallow reader needs to prove a state since: every live Story: commit of every id, also ids with no story
    # file yet (ESC-250, ESC-251), and the corrections file the states were computed with (ESC-252).
    meta = {"seen": seen, "run": run, "refs": refs_seen, "story_commits": story_shas, "reverted_commits": undone_shas,
            "corrections": corrections_blob}
    for attempt in range(1, SNAPSHOT_TRIES + 1):
        if attempt > 1:
            time.sleep(random.uniform(0.05, 0.3) * attempt)
            fetched, tip, err = fetch_snapshot(name)
        if not fetched:
            continue
        if tip and not set(git_read(["ls-tree", "--name-only", tip]).decode().split()) <= {MOVES, "ledger.json", "LEDGER.md"}:
            raise LedgerError(f"origin/{name} holds files other than a snapshot's ({MOVES}, ledger.json, LEDGER.md): it "
                              "is a branch of the project, never overwritten; set [ledger] snapshot to a branch of its own")
        blobs = cat_specs([f"{tip}:ledger.json", f"{tip}:{MOVES}", f"{tip}:LEDGER.md"]) if tip else {}
        old = parse_moves(blobs.get(f"{tip}:{MOVES}"))
        if old is None:
            raise LedgerError(f"{MOVES} on origin/{name} ({short(tip)}) cannot be read: nothing written, so no move "
                              "recorded there is lost; fix it there first")
        on_trunk = set(first_reach(graph, [trunk_sha]))
        # Round 4: a recorded commit this trunk no longer holds, recorded before this push, was forced away: its row
        # is marked `left` and says nothing about when it came back.
        old = [{**m, "left": seen} if "left" not in m and m["seen"] <= seen and m["sha"] not in on_trunk else m
               for m in old]
        known = {sha: m for sha, m in moves_map(old).items() if "left" not in m}
        moves = merge_moves(old, new_moves(graph, known, push_at, seen, run), graph, trunk_sha)
        theirs = parse_snapshot(blobs.get(f"{tip}:ledger.json"))
        files = {MOVES: moves_toml(moves).encode()}
        if keep_theirs(theirs, trunk_sha, seen, graph):
            files["ledger.json"] = blobs[f"{tip}:ledger.json"]
            files["LEDGER.md"] = blobs.get(f"{tip}:LEDGER.md") or b""
        else:
            facts = json.loads(json.dumps(ctx["facts"]))
            apply_moves(facts["stories"], moves_map(moves), graph)
            facts["snapshot"] = meta
            files["ledger.json"] = (json.dumps(facts, indent=1) + "\n").encode()
            files["LEDGER.md"] = ledger_md(facts, meta).encode()
        message = (f"ledger: snapshot of {trunk}@{short(trunk_sha)} (run {run})\n\n"
                   "No-story: ci — written by `ledger.py snapshot` in the CI\n")
        commit = snapshot_commit(files, tip, message, epoch)
        code, err = run_git(["push", "-q", "origin", f"{commit}:refs/heads/{name}"], 60)
        if code == 0:
            git_out("update-ref", f"refs/remotes/origin/{name}", commit)
            print(f"Keelokit: {name} at {short(commit)}: {trunk}@{short(trunk_sha)} seen {seen} (run {run}, "
                  f"try {attempt})")
            return 0
        err = last_error(err) if code is not None else "the push took over 60s"
    print(f"Keelokit: the snapshot was not written to {name} after {SNAPSHOT_TRIES} tries ({err}); the next run "
          "records this push too, not exact", file=sys.stderr)
    return 1


def cmd_deploy(state: dict, env: str, rev: str) -> int:
    """`deploy <staging|production> <commit>`: what a deploy job runs once its deploy succeeded. deploy/<env> points
    at that commit, backwards too (a rollback deploys an older tag)."""
    if env not in ENVIRONMENTS:
        print(f"Keelokit: no environment {env!r} (one of {', '.join(ENVIRONMENTS)})", file=sys.stderr)
        return 1
    sha = commit_of(rev)
    if sha is None:
        print(f"Keelokit: {rev!r} is no commit of this clone", file=sys.stderr)
        return 1
    err = ""
    for attempt in range(1, SNAPSHOT_TRIES + 1):
        code, err = run_git(["push", "-q", "origin", f"+{sha}:refs/heads/deploy/{env}"], 60)
        if code == 0:
            git_out("update-ref", f"refs/remotes/origin/deploy/{env}", sha)
            print(f"Keelokit: deploy/{env} at {short(sha)}")
            return 0
        err = last_error(err) if code is not None else "the push took over 60s"
        time.sleep(0.5 * attempt)
    print(f"Keelokit: deploy/{env} was not moved to {short(sha)} ({err})", file=sys.stderr)
    return 1


# ── show, next, --release ──

SHOW_LABELS = {
    "en": {"state": "state", "since": "since", "approx": "approximate", "exact": "exact", "version": "version",
           "candidate": "candidate", "branches": "branches", "file": "file", "commits": "commits",
           "attempts": "attempts (Dropped:)", "corrections": "corrections", "escapes": "escapes", "findings": "findings",
           "none": "no commits yet", "more": "more lines: `ledger.py show {id} --full`", "on": "on",
           "body_more": "more lines: git show {sha}", "no_story": "no story {id} among the stories of the trunk",
           "ready_none": "no story is ready", "wave": "wave", "release": "{tag} (after {prev}): {n} {stories}",
           "release_first": "{tag} (from the start): {n} {stories}", "story_one": "story", "story_many": "stories", "no_tag": "no version tag {tag}",
           "session": "session", "delivered": "delivered: convoy {n} ({state}), {branch}@{head}",
           "convoy": "convoy", "workers": "workers (Harbor)", "events": "convoy {n} events",
           "swarm": "swarm deliveries", "by": "by"},
    "es": {"state": "estado", "since": "desde", "approx": "aproximada", "exact": "exacta", "version": "versión",
           "candidate": "candidata", "branches": "ramas", "file": "archivo", "commits": "commits",
           "attempts": "intentos (Dropped:)", "corrections": "correcciones", "escapes": "escapes",
           "findings": "hallazgos", "none": "todavía sin commits", "more": "líneas más: `ledger.py show {id} --full`",
           "on": "en", "body_more": "líneas más: git show {sha}", "no_story": "no hay historia {id} en el trunk",
           "ready_none": "ninguna historia está lista", "wave": "ola", "release": "{tag} (después de {prev}): {n} {stories}",
           "release_first": "{tag} (desde el principio): {n} {stories}", "story_one": "historia",
           "story_many": "historias", "no_tag": "no hay tag de versión {tag}",
           "session": "sesión", "delivered": "entregada: convoy {n} ({state}), {branch}@{head}",
           "convoy": "convoy", "workers": "workers (Harbor)", "events": "eventos del convoy {n}",
           "swarm": "entregas del enjambre", "by": "de"},
}
EVENTS_SHOWN = 8
BODY_LINES = 6


def id_pattern(ids) -> re.Pattern | None:
    ids = sorted(set(ids))
    return re.compile(r"(?<![A-Za-z0-9])(?:" + "|".join(map(re.escape, ids)) + r")(?![0-9])") if ids else None


def text_lines(content: bytes | None) -> list[str]:
    return content.decode("utf-8", errors="replace").replace("\r\n", "\n").split("\n") if content else []


def addendum_headings(path: str, content: bytes | None) -> list[str]:
    found, fenced = [], False
    for n, line in enumerate(text_lines(content), 1):
        if line.lstrip().startswith("```"):
            fenced = not fenced
        elif not fenced and ADDENDUM_HEADING.match(line):
            found.append(f"{path}:{n} {line.strip()}")
    return found


def card(ctx: dict, sid: str, lang: str, full: bool) -> list[str]:
    """The lines of `show`: the facts first, then the why, each with where it lives."""
    t, names = SHOW_LABELS[lang], STATE_NAMES[lang]
    rec = next(r for r in ctx["facts"]["stories"] if r["id"] == sid)
    lines = [f"{sid} — {rec['title']}"]
    state = f"{t['state']}: {names.get(rec['state'], rec['state'])}"
    if rec["since"]:
        state += f" {t['since']} {rec['since']} ({t['exact'] if rec['since_exact'] else t['approx']})"
    marks = []
    if rec["reconstructed"]:
        marks.append(LABELS[lang]["by_delegated" if rec["reconstructed_by"] == "delegated" else "by_person"])
    if rec["reverted"]:
        marks.append(LABELS[lang]["reverted"])
    if "stale" in rec["signals"]:
        marks.append(LABELS[lang]["stale"])
    lines.append(" · ".join([state, *marks]))
    if rec["reason"]:
        lines.append(f"  {rec['reason']}")
    facts = []
    if rec["version"] or rec["candidate"]:
        facts.append(f"{t['version']}: {rec['version']}" if rec["version"]
                     else f"{t['candidate']}: {rec['candidate']}")
    facts += [f"{env}: {short(head)}" for env, head in rec["environments"].items() if head]
    if facts:
        lines.append(" · ".join(facts))
    if rec["branches"]:
        lines.append(f"{t['branches']}: {', '.join(rec['branches'])}")
    if rec.get("delivered"):
        d = rec["delivered"]
        lines.append(t["delivered"].format(n=d["convoy"], state=d["convoy_state"], branch=d["branch"], head=short(d["head"])))
    elif rec.get("convoy") is not None:
        lines.append(f"{t['convoy']}: {rec['convoy']}")
    if rec.get("workers"):
        lines.append(f"{t['workers']}: {', '.join(rec['workers'])}")
    if rec.get("swarm"):
        lines.append(f"{t['swarm']}:")
        for e in rec["swarm"]:
            parts = [e["task"], names.get(e["state"], e["state"])]
            if e["branch"] and e["head"]:
                parts.append(f"{e['branch']}@{short(e['head'])}")
            if e["convoy"] is not None:
                parts.append(f"{t['convoy']} {e['convoy']}")
            if e["authors"]:
                parts.append(f"{t['by']} {', '.join(e['authors'])}")
            lines.append(f"  {' · '.join(parts)}")
    lines.append(f"{t['file']}: {rec['path']}")
    if rec.get("as_of"):
        lines.append(LABELS[lang]["snapshot"].format(sha=short(rec["as_of"])))
    if ctx["reason"] is not None:
        return lines
    why = why_of(ctx, sid, rec)
    lines += [f"  {h}" for h in why["addenda"]]
    lines.append(f"{t['commits']}:" if why["commits"] else f"{t['commits']}: {t['none']}")
    for c in why["commits"]:
        where = f" ({t['on']} {', '.join(c['branches'])})" if c["branches"] else ""
        lines.append(f"  {short(c['sha'])} {c['date'][:10]} {c['kind']}{where}: {c['subject']}")
        if c["session"]:
            lines.append(f"    {t['session']}: {c['session']}")
        if c["swarm_task"]:
            lines.append(f"    swarm: {c['swarm_task']} · {c['author']}")
        body = c["body"]
        shown = body if full or len(body) <= BODY_LINES else body[:BODY_LINES - 1]
        lines += [f"    {line}" if line else "" for line in shown]
        if len(shown) < len(body):
            lines.append(f"    … {len(body) - len(shown)} {t['body_more'].format(sha=short(c['sha']))}")
    if rec["attempts"]:
        lines.append(f"{t['attempts']}:")
        for a in rec["attempts"]:
            reason = a["reason"].split("\n")
            lines.append(f"  {short(a['commit'])} {a['date'][:10]} {t['on']} {', '.join(a['branches'])}: {reason[0]}")
            lines += [f"    {line}" for line in (reason[1:] if full else reason[1:BODY_LINES])]
    if why["corrections"]:
        lines.append(f"{t['corrections']}:")
        lines += [f"  {r['kind']} {short(r['commit'])} {r['approver']} {r['date']}: {r['evidence']}"
                  for r in why["corrections"]]
    if why["escapes"]:
        lines += [f"{t['escapes']}:", *(f"  {e}" for e in why["escapes"])]
    if why["findings"]:
        lines += [f"{t['findings']}:", *(f"  {f}" for f in why["findings"])]
    if why["convoy_events"]:
        events = why["convoy_events"] if full else why["convoy_events"][-EVENTS_SHOWN:]
        lines.append(f"{t['events'].format(n=rec['convoy'])}:")
        lines += [f"  {e['at']} {e['what']} {e['detail']} ({e['by']})" for e in events]
    return lines


def why_of(ctx: dict, sid: str, rec: dict) -> dict:
    """The why of a story, as data (`show` prints it, `show --json` gives it): the Addendum headings of its file; its
    commits, Story: first (the decision), then Part-of: newest first, the trunk's then the branches'; its correction
    rows; the rows of docs/escapes.md and the findings of docs/bugbash/ that name it or arrive through `Finding:`; and
    the events of its convoy in Harbor's logbook."""
    blobs = read_blobs([sha for path, sha in ctx["tree"] if path == rec["path"] or path == ESCAPES
                        or (path.startswith(BUGBASH) and path.endswith(".md"))], ctx["trunk_sha"])
    by_path = {path: blobs.get(sha) for path, sha in ctx["tree"] if sha in blobs}
    entry = ctx["branches"].get(sid, {})
    trunk_commits = [c for c in ctx["log"] if sid in c["story"] or sid in c["part_of"]]
    found_commits = [(c, None) for c in trunk_commits] + [(c, held_by(c)) for c in entry.get("commits", [])
                                                           if c["sha"] not in {x["sha"] for x in trunk_commits}]
    found_commits.sort(key=lambda x: (sid not in x[0].get("story", []), -x[0]["ct"], x[0]["sha"]))
    commits, findings = [], set()
    tasks = {sha: e["task"] for e in rec.get("swarm") or [] for sha in e["commits"]}
    known = ctx.get("authors") or {}
    if known and known["asked"].issuperset(c["sha"] for c, _ in found_commits):
        authors = known["names"]  # read_all asked for them with the swarm's (HARN-022): one git call per show
    else:
        try:
            authors = authors_of([c["sha"] for c, _ in found_commits], ctx["trunk_sha"])
        except LedgerError:
            authors = {}
    for c, held in found_commits:
        subject, body = split_message(c["message"], c["trailers"])
        commits.append({"sha": c["sha"], "date": iso(c["ct"]), "kind": "Story" if sid in c.get("story", []) else "Part-of",
                        "branches": list(held or []), "subject": subject,
                        "session": next(iter(trailer_values(c["trailers"], "Claude-Session")), None), "body": body,
                        "author": authors.get(c["sha"]), "swarm_task": tasks.get(c["sha"])})
        findings.update(i for v in trailer_values(c["trailers"], "Finding") for i in ID_TOKEN.findall(v))
    names_it, by_finding = id_pattern([sid]), id_pattern(findings)
    escapes = [f"{ESCAPES}:{n} {line.strip()}" for n, line in enumerate(text_lines(by_path.get(ESCAPES)), 1)
               if line.lstrip().startswith("|") and (names_it.search(line) or by_finding and by_finding.search(line))]
    found = []
    for path in sorted(p for p in by_path if p.startswith(BUGBASH)):
        for n, line in enumerate(text_lines(by_path[path]), 1):
            hit = by_finding.search(line) if by_finding and line.lstrip().startswith("#") else None
            if hit:
                found.append(f"{hit.group(0)} {path}:{n} {line.strip()}")
            elif names_it.search(line):
                found.append(f"{path}:{n} {line.strip()}")
    convoy = (ctx.get("harbor") or {}).get("convoys", {}).get(rec.get("convoy"))
    return {"addenda": addendum_headings(rec["path"], by_path.get(rec["path"])), "commits": commits,
            "corrections": [r for r in ctx["corrections"]["active"] if r["story"] == sid],
            "escapes": escapes, "findings": found, "convoy_events": convoy["events"] if convoy else []}


def bounded(lines: list[str], sid: str, lang: str, full: bool) -> list[str]:
    """At most SHOW_LINES lines of at most SHOW_WIDTH characters, the last saying how to see the rest. A value with
    newlines becomes several lines and terminal control characters never reach the terminal (with --full too)."""
    lines = [CONTROL.sub("?", part.replace("\t", " ")) for line in lines for part in line.replace("\r", "").split("\n")]
    if full:
        return lines
    lines = [line if len(line) <= SHOW_WIDTH else line[:SHOW_WIDTH - 1] + "…" for line in lines]
    if len(lines) <= SHOW_LINES:
        return lines
    rest = len(lines) - (SHOW_LINES - 1)
    return lines[:SHOW_LINES - 1] + [f"… {rest} {SHOW_LABELS[lang]['more'].format(id=sid)}"]


def story_named(ctx: dict, sid: str) -> str | None:
    """The trunk's story id `sid` names: itself, else the one id equal to it without case (Harbor's ids)."""
    ids = [r["id"] for r in ctx["facts"]["stories"]]
    if sid in ids:
        return sid
    same = [i for i in ids if i.casefold() == sid.casefold()]
    return same[0] if len(same) == 1 else None


def cmd_show(state: dict, args: tuple) -> int:
    """show <ID> [--full]: the card. show <ID> --json: `{"schema": 1, ...the record, "history", "why": {...}}`, the
    record as `--json` gives it and the why as data (docs/ledger.md, "show --json"); exit 1, with `error`, when the
    trunk has no such story."""
    sid, mode = args
    lang = read_config(state)["lang"]
    ctx = read_all(state, show=sid)
    found = story_named(ctx, sid)
    if found is None:
        message = SHOW_LABELS[lang]['no_story'].format(id=sid)
        print(json.dumps({"schema": 1, "id": sid, "error": message}, indent=1) if mode == "json" else f"Keelokit: {message}")
        return 1
    if mode == "json":
        rec = next(r for r in ctx["facts"]["stories"] if r["id"] == found)
        why = why_of(ctx, found, rec) if ctx["reason"] is None else None
        print(json.dumps({"schema": 1, **rec, "history": ctx["facts"]["history"], "why": why}, indent=1))
        return 0
    full = mode == "full"
    print("\n".join(bounded(card(ctx, found, lang, full), found, lang, full)))
    return 0


def id_key(sid: str) -> tuple:
    epic, _, number = sid.rpartition("-")
    return (epic, int(number) if number.isdigit() else 0, sid)


def cmd_next(state: dict) -> int:
    """The ready stories (ready already excludes in-progress), by wave (none last) and id."""
    lang = read_config(state)["lang"]
    ctx = read_all(state)
    if ctx["reason"] is not None and "snapshot" not in ctx:
        print(f"Keelokit: {ctx['reason']}")
        return 1
    if "snapshot" in ctx:  # as of the snapshot's commit: who took a story since is not seen
        print(f"Keelokit: {LABELS[lang]['snapshot'].format(sha=short(ctx['snapshot']['sha']))}", file=sys.stderr)
    unknown = [r for r in ctx["facts"]["stories"] if r["state"] == "unknown"]
    if unknown:
        print(f"Keelokit: {len(unknown)} stories are unknown, so what is ready cannot be said: "
              f"{listed([r['id'] for r in unknown], 'more')} ({unknown[0]['reason']})")
        return 1
    ready = sorted((r for r in ctx["facts"]["stories"] if r["state"] == "ready"),
                   key=lambda r: (r["wave"] is None, r["wave"] or 0, id_key(r["id"])))
    t = SHOW_LABELS[lang]
    for r in ready:
        print(f"{r['id']}  {t['wave']} {r['wave'] if r['wave'] is not None else '—'}  {r['title']}")
    if not ready:
        print(t["ready_none"])
    return 0


def cmd_release(state: dict, tag: str) -> int:
    """The stories whose commit (Story:, or a correction's) is in the tag and not in the previous final version
    tag (in version order); the first version takes everything before it."""
    lang = read_config(state)["lang"]
    t = SHOW_LABELS[lang]
    ctx = read_all(state)
    if ctx["reason"] is not None:
        print(f"Keelokit: {ctx['reason']}")
        return 1
    refs = ctx.get("refs", {})
    tags = version_tags(refs)
    key = version_key(tag)
    if key is None or f"refs/tags/{tag}" not in refs:
        print(f"Keelokit: {t['no_tag'].format(tag=tag)}")
        return 1
    previous = [(k, name, sha) for k, name, sha in tags if k[1] == 1 and k < key and name != tag]
    held = set(first_reach(ctx["graph"], [previous[-1][2]])) if previous else set()
    inside = set(first_reach(ctx["graph"], [refs[f"refs/tags/{tag}"]])) - held
    records = ctx["records"]
    entered = {sid for c in ctx["log"] if c["sha"] in inside for sid in c["story"] if sid in records}
    entered |= {r["story"] for r in ctx["corrections"]["active"] if r["commit"] in inside and r["story"] in records}
    entered |= {sid for sid, r in records.items() if r["commit"] in inside}
    stories = sorted((records[sid] for sid in entered), key=lambda r: id_key(r["id"]))
    word = t["story_one"] if len(stories) == 1 else t["story_many"]
    head = (t["release"].format(tag=tag, prev=previous[-1][1], n=len(stories), stories=word) if previous
            else t["release_first"].format(tag=tag, n=len(stories), stories=word))
    print("\n".join([head, *(f"{r['id']}  {r['title']}" for r in stories)]))
    return 0


# ── take and drop (LEDGER-008) ──

TAKE_LABELS = {
    "en": {"no_story": "no story {id} among the stories of the trunk", "taken": "this worktree works on {id}",
           "was": " (it was {old})", "on_trunk": "{id} is already {state}: nothing to take",
           "unknown": "warning: the state of {id} cannot be said ({reason}); taken all the same",
           "elsewhere": "warning: {id} already has Part-of: commits on {branches}: someone may be on it",
           "cleared": "this worktree works on no story", "no_reason": "drop needs a reason: --motivo \"...\"",
           "commit_failed": "the drop commit could not be made: {err}",
           "archived": "{id} dropped: {sha} pushed to {ref} (no verify: archive/ never lands)",
           "fallback": "the push to {ref} was refused ({err}); committing the drop on {branch} and pushing it",
           "on_branch": "{id} dropped: {sha} pushed on {branch}",
           "stays": "{id} not dropped: the push to {ref} was refused ({err}) and {why}; the story stays taken",
           "unpushed": "{id}: the drop commit {sha} is on {branch} but its push failed ({err}; the pre-push's "
                       "lines above say why); push it, then `ledger.py take --clear`",
           "no_branch": "there is no branch to fall back to (a detached HEAD, or the trunk)",
           "delivered": "warning: {id} is already delivered in convoy {n}: someone built it",
           "harbor_old": "Harbor's harbor.py has no `story take` ({why}): taken without the logbook's lock",
           "harbor_silent": "harbor.py story {action} {id} did not answer in {s:g} s: {id} is not taken here; the "
                            "logbook may hold it all the same (harbor.py story release {id} lifts it)",
           "harbor_refused": "{id} is not taken: {line}",
           "harbor_failed": "{id} is not taken: harbor.py story take exited {code}{line}",
           "release_refused": "this worktree works on no story, but Harbor did not release {id}: {line}"},
    "es": {"no_story": "no hay historia {id} en el trunk", "taken": "este worktree trabaja en {id}",
           "was": " (era {old})", "on_trunk": "{id} ya está {state}: no hay nada que tomar",
           "unknown": "aviso: no se puede decir el estado de {id} ({reason}); tomada igual",
           "elsewhere": "aviso: {id} ya tiene commits Part-of: en {branches}: puede haber alguien en ella",
           "cleared": "este worktree no trabaja en ninguna historia",
           "no_reason": "drop necesita un motivo: --motivo \"...\"",
           "commit_failed": "no se pudo hacer el commit de drop: {err}",
           "archived": "{id} abandonada: {sha} subido a {ref} (sin verify: archive/ nunca aterriza)",
           "fallback": "el push a {ref} fue rechazado ({err}); se hace el drop en {branch} y se sube",
           "on_branch": "{id} abandonada: {sha} subido en {branch}",
           "stays": "{id} no abandonada: el push a {ref} fue rechazado ({err}) y {why}; la historia sigue tomada",
           "unpushed": "{id}: el commit de drop {sha} está en {branch} pero su push falló ({err}; las líneas del "
                       "pre-push de arriba dicen por qué); subilo y luego `ledger.py take --clear`",
           "no_branch": "no hay rama a la que volver (HEAD suelto, o el trunk)",
           "delivered": "aviso: {id} ya está entregada en el convoy {n}: alguien la construyó",
           "harbor_old": "el harbor.py de Harbor no tiene `story take` ({why}): tomada sin el lock de la bitácora",
           "harbor_silent": "harbor.py story {action} {id} no respondió en {s:g} s: {id} no se toma acá; la bitácora "
                            "puede tenerla igual (harbor.py story release {id} la libera)",
           "harbor_refused": "{id} no se toma: {line}",
           "harbor_failed": "{id} no se toma: harbor.py story take salió con {code}{line}",
           "release_refused": "este worktree no trabaja en ninguna historia, pero Harbor no liberó {id}: {line}"},
}
ON_TRUNK_STATES = ("on-trunk", "in-version", "in-staging", "in-production")
ARCHIVE = "archive/"


def find_story(state: dict, sid: str, t: dict) -> dict | None:
    """The story's record (ledger_facts), or None after saying it is no story of the trunk."""
    ctx = read_all(state)
    rec = next((r for r in ctx["facts"]["stories"] if r["id"] == sid), None)
    if rec is None:
        print(f"Keelokit: {t['no_story'].format(id=sid)}")
    return rec


def current_branch() -> str | None:
    code, out = git_out("symbolic-ref", "--quiet", "--short", "HEAD")
    return out if code == 0 and out else None


def clear_story() -> None:
    """Unset keelokit.story in this worktree's own config (nothing to do when take never enabled it)."""
    if git_out("config", "--local", "--type=bool", "--get", "extensions.worktreeConfig")[1] == "true":
        git_out("config", "--worktree", "--unset-all", "keelokit.story")
        git_out("config", "--worktree", "--unset-all", "keelokit.storyGitDir")


# Harbor (LEDGER-013): with `git config harbor.py` (Harbor records its own path there when it adopts a project) and a
# harbor.py that has `story take` (asked by feature: `story take --help` exits 0, never by version), taking a story is
# Harbor's lock in its logbook: `take` runs `harbor.py story take <ID>` and sets nothing unless it exits 0. harbor.py
# is code the ledger runs, so only `take` runs it (never `show`, `check`, the summary or a hook's path), with the
# interpreter that runs the ledger, the hardened git environment, CLAUDE_PROJECT_DIR set to this checkout, no stdin,
# its own session (killed whole at the timeout) and its output read from files, at most HARBOR_OUTPUT bytes of it.
HARBOR_SECONDS = 180.0  # Harbor's take asks the ledger twice (60 s each) and pushes the logbook, retrying
HARBOR_PROBE_SECONDS = 30.0
HARBOR_OUTPUT = 65536
HARBOR_LINE = re.compile(r"harbor: [A-Z][A-Z0-9_]*: .*")
SESSION_ID = re.compile(r"[A-Za-z0-9._-]{1,200}")


def harbor_seconds() -> float:
    try:
        value = float(os.environ.get("KEELOKIT_HARBOR_SECONDS") or HARBOR_SECONDS)
    except ValueError:
        return HARBOR_SECONDS
    return min(max(value, 0.1), 3600.0) if math.isfinite(value) else HARBOR_SECONDS


def harbor_tool() -> str | None:
    """The harbor.py `git config --local harbor.py` names: an absolute path to a file called harbor.py; else None."""
    path = config_get("harbor.py")
    if not path or not os.path.isabs(path) or os.path.basename(path) != "harbor.py" or not os.path.isfile(path):
        return None
    return path


def run_harbor(tool: str, args: list[str], timeout: float) -> tuple[int | None, str, str]:
    """(exit, stdout, stderr) of harbor.py; exit None when it did not end in `timeout` (its process group is gone)."""
    env = {**{k: v for k, v in git_env().items() if k not in GIT_SCRUB or k == "GIT_ASKPASS"},
           "CLAUDE_PROJECT_DIR": str(ROOT)}
    # The session id stays in the environment, where Harbor reads it (HARBOR_SESSION, then CLAUDE_SESSION_ID); Claude
    # Code sets only CLAUDE_CODE_SESSION_ID, handed over as HARBOR_SESSION. Nothing from the environment is an argument.
    if not (env.get("HARBOR_SESSION") or env.get("CLAUDE_SESSION_ID")) \
            and SESSION_ID.fullmatch(env.get("CLAUDE_CODE_SESSION_ID", "")):
        env["HARBOR_SESSION"] = env["CLAUDE_CODE_SESSION_ID"]
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        try:
            proc = subprocess.Popen([sys.executable, "-E", "-s", tool, *args], cwd=ROOT, env=env,
                                    stdin=subprocess.DEVNULL, stdout=out, stderr=err, start_new_session=True)
        except OSError as e:
            return 127, "", f"harbor.py could not run ({e.strerror or e})"
        try:
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            code = None
            try:
                os.killpg(proc.pid, signal.SIGKILL)  # its whole session: a git it started goes with it
            except (ProcessLookupError, PermissionError):
                proc.kill()
            proc.wait()
        texts = []
        for f in (out, err):
            f.seek(0)
            texts.append(f.read(HARBOR_OUTPUT).decode("utf-8", errors="replace"))
    return code, texts[0], texts[1]


def one_line(text: str) -> str:
    """A line of harbor.py's output as one terminal-safe line of at most 300 characters."""
    return CONTROL.sub("?", " ".join(text.split()))[:300]


def harbor_line(out: str, err: str) -> str:
    """What harbor.py said: its `harbor: CODE: why` line, else its last non-empty line, else ""."""
    lines = [line.strip() for line in (err + "\n" + out).splitlines() if line.strip()]
    coded = [line for line in lines if HARBOR_LINE.fullmatch(line)]
    return one_line(coded[0] if coded else lines[-1] if lines else "")


class HarborSilent(Exception):
    """harbor.py could not be asked whether it has `story take`: no answer, or an exit that is no usage error."""


def harbor_take_ready(t: dict) -> str | None:
    """The harbor.py to take stories with, or None: no Harbor, or one whose parser has no `story take` (exit 2 with
    argparse's "invalid choice": nothing changes). HarborSilent when it could not be asked (a timeout, a crash)."""
    tool = harbor_tool()
    if tool is None:
        return None
    code, out, err = run_harbor(tool, ["story", "take", "--help"], HARBOR_PROBE_SECONDS)
    if code == 0:
        return tool
    if code == 2 and "invalid choice" in err:
        print(t["harbor_old"].format(why="`story take --help` exited 2"))
        return None
    raise HarborSilent(f"exit {code}" if code is not None else f"no answer in {HARBOR_PROBE_SECONDS:g} s")


def cmd_take(state: dict, sid: str | None) -> int:
    """take <ID>: keelokit.story in this worktree's config (extensions.worktreeConfig: each worktree of the clone has
    its own). Refuses an id that is no story or a story already on the trunk; a Part-of: commit of the story on
    another origin branch, or its delivery, is a warning, never a refusal (without Harbor in-progress is a signal).
    With Harbor, `harbor.py story take <ID>` decides first: any exit but 0 is one line, and nothing is set (exit 1
    when Harbor refused, 2 when it could not answer). take --clear: with Harbor, `story release` of this worktree's
    story too; the worktree is cleared whatever Harbor says, and a release Harbor refused is exit 1."""
    t = TAKE_LABELS[read_config(state)["lang"]]
    if sid is None:
        held = taken_story()
        try:
            tool = harbor_take_ready(t) if held else None
        except HarborSilent as e:
            clear_story()
            print(t["cleared"])
            print(f"Keelokit: {t['release_refused'].format(id=held, line=f'harbor.py could not be asked ({e})')}")
            return 2
        clear_story()
        print(t["cleared"])
        if tool is None:
            return 0
        timeout = harbor_seconds()
        code, out, err = run_harbor(tool, ["story", "release", held], timeout)
        if code is None:
            print(f"Keelokit: {t['harbor_silent'].format(action='release', id=held, s=timeout)}")
            return 2
        if code != 0:
            print(f"Keelokit: {t['release_refused'].format(id=held, line=harbor_line(out, err) or f'exit {code}')}")
            return 1
        if line := harbor_line(out, ""):
            print(line)
        return 0
    rec = find_story(state, sid, t)
    if rec is None:
        return 1
    if rec["state"] in ON_TRUNK_STATES:
        print(f"Keelokit: {t['on_trunk'].format(id=sid, state=rec['state'])}")
        return 1
    if rec["state"] == "unknown":
        print(t["unknown"].format(id=sid, reason=rec["reason"]))
    if rec["state"] == "delivered":
        print(t["delivered"].format(id=sid, n=rec["convoy"]))
    mine = {b for b in (current_branch(),) if b}
    code, upstream = git_out("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    if code == 0 and upstream.startswith("origin/"):
        mine.add(upstream.removeprefix("origin/"))
    others = [b for b in rec["branches"] if b not in mine]
    if others:
        print(t["elsewhere"].format(id=sid, branches=listed(others, "more")))
    try:
        tool = harbor_take_ready(t)
    except HarborSilent as e:
        print(f"Keelokit: {t['harbor_failed'].format(id=sid, code='?', line=f' (harbor.py could not be asked: {e})')}")
        return 2
    if tool is not None:
        timeout = harbor_seconds()
        code, out, err = run_harbor(tool, ["story", "take", sid], timeout)
        if code is None:
            print(f"Keelokit: {t['harbor_silent'].format(action='take', id=sid, s=timeout)}")
            return 2
        if code != 0:
            line = harbor_line(out, err)
            if code == 1 and line:
                print(f"Keelokit: {t['harbor_refused'].format(id=sid, line=line)}")
            else:
                print(f"Keelokit: {t['harbor_failed'].format(id=sid, code=code, line=f' ({line})' if line else '')}")
            return 1 if code == 1 else 2
        if line := harbor_line(out, ""):
            print(line)
    code, old = git_out("config", "--get", "keelokit.story")
    old = old if code == 0 else None
    # keelokit.storyGitDir: which worktree took it. `git worktree add` copies config.worktree into the new worktree
    # (git 2.4x), and a copied story there is none (ESC-188): the commit hooks read it only in the worktree that took it.
    code, gitdir = git_out("rev-parse", "--absolute-git-dir")
    if code != 0 or not gitdir:
        raise LedgerError("git rev-parse --absolute-git-dir failed")
    for args in (("config", "extensions.worktreeConfig", "true"), ("config", "--worktree", "keelokit.story", sid),
                 ("config", "--worktree", "keelokit.storyGitDir", gitdir)):
        code, err = run_git(list(args))
        if code != 0:
            raise LedgerError(f"git {' '.join(args)} failed: {last_error(err)}")
    print(t["taken"].format(id=sid) + (t["was"].format(old=old) if old and old != sid else ""))
    return 0


def archive_ref(sid: str, day: str) -> str:
    """archive/<id>-<YYYYMMDD>, or the first -2, -3… that origin does not have yet (two drops in one day)."""
    base = f"{ARCHIVE}{sid.lower()}-{day}"
    code, out = git_out("ls-remote", "--heads", "origin", f"refs/heads/{base}*")
    taken = {line.split()[1].removeprefix("refs/heads/") for line in out.splitlines() if len(line.split()) == 2} \
        if code == 0 else set()
    n, name = 1, base
    while name in taken:
        n += 1
        name = f"{base}-{n}"
    return name


def cmd_drop(state: dict, sid: str, reason: str, day: str | None = None) -> int:
    """drop <ID> --motivo: an empty commit `drop(<ID>): <reason>` (the reason in the body, `Dropped: <ID>` as its
    trailer) whose parent is HEAD, made with commit-tree so neither HEAD nor the index moves, pushed to
    archive/<id>-<YYYYMMDD>, where the pre-push runs no verify. Refused there (a session may push only its own
    branch): the same message is committed on the current branch, one second later so it is another commit (the
    pre-push remembered the first as an unverified tip), and that branch is pushed with its usual gate; never on
    the trunk, main, master or release. Then keelokit.story is cleared. Not pushed anywhere: exit 1, the story
    stays taken."""
    t = TAKE_LABELS[read_config(state)["lang"]]
    reason = reason.strip()
    if not reason:
        print(f"Keelokit: {t['no_reason']}")
        return 1
    if find_story(state, sid, t) is None:
        return 1
    subject = " ".join(reason.split("\n", 1)[0].split())
    subject = subject if len(subject) <= 72 else subject[:71] + "…"
    message = ["-m", f"drop({sid}): {subject}", "-m", reason, "-m", f"Dropped: {sid}"]
    code, sha = git_out("commit-tree", "HEAD^{tree}", "-p", "HEAD", *message)
    if code != 0 or not sha:
        print(f"Keelokit: {t['commit_failed'].format(err='git commit-tree failed (no HEAD?)')}")
        return 1
    ref = archive_ref(sid, day or datetime.now(timezone.utc).strftime("%Y%m%d"))
    code, err = run_git(["push", "origin", f"{sha}:refs/heads/{ref}"])
    if code == 0:
        print(t["archived"].format(id=sid, sha=short(sha), ref=ref))
        clear_story()
        return 0
    branch = current_branch()
    if branch is None or branch in {trunk_name(state), "main", "master", "release"}:
        print(f"Keelokit: {t['stays'].format(id=sid, ref=ref, err=last_error(err), why=t['no_branch'])}")
        return 1
    print(t["fallback"].format(ref=ref, err=last_error(err), branch=branch))
    when = f"@{int(git_out('log', '-1', '--format=%ct', sha)[1]) + 1} +0000"
    code, err = run_git(["commit", "-q", "--only", "--allow-empty", *message],
                        env={"GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when})
    if code != 0:
        print(f"Keelokit: {t['commit_failed'].format(err=last_error(err))}")
        return 1
    sha = git_out("rev-parse", "HEAD")[1]
    code, err = run_git(["push", "origin", f"HEAD:refs/heads/{branch}"])
    if code != 0:
        print(err.rstrip(), file=sys.stderr)
        print(f"Keelokit: {t['unpushed'].format(id=sid, sha=short(sha), branch=branch, err=last_error(err))}")
        return 1
    print(t["on_branch"].format(id=sid, sha=short(sha), branch=branch))
    clear_story()
    return 0


# ── the git hooks: prepare-commit-msg and commit-msg (LEDGER-009) ──

ATTRIBUTING = ("story", "part-of", "no-story")  # as `check` counts them (a Dropped: commit gets Part-of: too)
EXEMPT_SUBJECT = ("fixup! ", "squash! ", "amend! ")
LEDGER_CMD = "python3 .keelokit/bin/ledger.py"


def comment_char() -> str:
    """core.commentChar when it is one character, else `#` (git's default; "auto" picks per message and
    leaves `#` for every message an editor did not touch)."""
    # core.commentString (git 2.45+) and core.commentChar are one setting: the last one git reads wins.
    code, out = git_out("config", "--get-regexp", r"^core\.comment(char|string)$")
    values = [line.split(" ", 1)[1] for line in out.splitlines() if " " in line] if code == 0 else []
    return values[-1] if values and values[-1] != "auto" else "#"


def readings(raw: str, source: str | None) -> str:
    """The message as git will store it, nothing from the scissors line of `commit -v` on. Git drops comment lines
    only when it cleans up with `strip`, which by default it does only when the editor ran: `-m "#123 fix"` keeps
    its line (ESC-190). `commit.cleanup`, when set, decides; else git's source, as prepare-commit-msg got it: none
    or `template` (the editor) or `message-edit` (-e with -m) → without comment lines, `message` (-m, -F) → with
    them; unknown (no record, an
    amend, a merge) → without them, unless nothing else is left."""
    c = comment_char()
    scissors = re.compile(rf"^{re.escape(c)} -+ >8 -+$")
    kept = []
    for line in raw.replace("\r\n", "\n").split("\n"):
        if scissors.match(line):
            break
        kept.append(line)
    stripped = "\n".join(line for line in kept if not line.startswith(c)).strip("\n") + "\n"
    whole = "\n".join(kept).strip("\n") + "\n"
    mode = git_out("config", "--get", "commit.cleanup")[1].strip().lower()
    if mode == "strip":
        return stripped
    if mode in ("verbatim", "whitespace", "scissors") or source == "message":
        return whole
    return stripped if stripped.strip() or source in ("", "template", "message-edit") else whole


def message_trailers(text: str) -> list[tuple[str, str]]:
    """(key, value) of the trailers git reads from the message (its last paragraph): `interpret-trailers --parse`,
    with `--no-divider`, as `git log`'s %(trailers) reads them: a `---` line is no patch divider there (ESC-189)."""
    r = subprocess.run(["git", "interpret-trailers", "--parse", "--no-divider"], cwd=ROOT, env=git_env(), input=text,
                       capture_output=True, text=True, errors="replace")
    if r.returncode != 0:
        raise LedgerError(f"git interpret-trailers failed: {last_error(r.stderr)}")
    return parse_trailers(r.stdout)


def merging() -> bool:
    code, path = git_out("rev-parse", "--git-path", "MERGE_HEAD")
    return code == 0 and bool(path) and (Path(path) if os.path.isabs(path) else ROOT / path).is_file()


def exempt_subject(text: str) -> bool:
    return text.lstrip("\n").startswith(EXEMPT_SUBJECT)


def attributed(trailers: list[tuple[str, str]]) -> bool:
    return any(k.lower() in ATTRIBUTING for k, _ in trailers)


def taken_story() -> str | None:
    """keelokit.story, unless keelokit.storyGitDir says another worktree took it: `git worktree add` copies
    config.worktree, story included, into the new worktree (ESC-188). A story set by hand, without the key, counts."""
    code, sid = git_out("config", "--get", "keelokit.story")
    if code != 0 or not STORY_ID.fullmatch(sid):
        return None
    code, owner = git_out("config", "--get", "keelokit.storyGitDir")
    if code == 0 and owner:
        here = git_out("rev-parse", "--absolute-git-dir")[1]
        if os.path.realpath(owner) != os.path.realpath(here):
            return None
    return sid


SOURCE_FILE = "keelokit-commit-source"


def source_path() -> Path | None:
    code, path = git_out("rev-parse", "--git-path", SOURCE_FILE)
    return (Path(path) if os.path.isabs(path) else ROOT / path) if code == 0 and path else None


def editor_template(raw: str) -> bool:
    """Whether git appended its help text for the editor (`commit -e -m …`): the message ends in a paragraph of
    comment lines only, at least two (git's shortest, with commit.status off, has two; the words are in the
    person's language, so they are not read). A `-m` message alone gets no such paragraph."""
    c = comment_char()
    paragraphs = [q for q in re.split(r"\n[ \t]*\n", raw.replace("\r\n", "\n").strip("\n")) if q.strip()]
    last = paragraphs[-1].split("\n") if len(paragraphs) > 1 else []
    return len(last) >= 2 and all(line.startswith(c) for line in last)


def recorded_source() -> str | None:
    """git's source for this commit as prepare-commit-msg wrote it, read once (the file goes, so a later commit
    whose prepare did not run reads no stale value); None when there is no record."""
    where = source_path()
    if where is None:
        return None
    try:
        source = where.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    try:
        where.unlink()
    except OSError:
        pass
    return source


def add_part_of(path: Path, source: str = "") -> None:
    """prepare-commit-msg's work: `Part-of: <keelokit.story>` when the message has content, is no merge or
    fixup!, and names no story yet. A message with only comments (the editor is about to open) is left alone:
    a trailer there would turn an aborted commit into a commit called `Part-of: …`; commit-msg adds it after."""
    if source == "merge" or merging():
        return
    sid = taken_story()
    if sid is None:
        return
    text = readings(path.read_text(encoding="utf-8", errors="replace"), source)
    if not text.strip() or exempt_subject(text) or attributed(message_trailers(text)):
        return
    code, err = run_git(["interpret-trailers", "--in-place", "--no-divider", "--if-missing", "add", "--trailer",
                         f"Part-of: {sid}", str(path)])
    if code != 0:
        raise LedgerError(f"git interpret-trailers failed: {last_error(err)}")


def known_story_ids(state: dict, cfg: dict) -> tuple[set[str], bool]:
    """(the ids of the configured stories, whether some story file could not be read): the trunk's tree, read as
    every other command reads it, plus the story files staged or committed here (a branch may add the story it works on; an untracked one
    would never reach the trunk, where `check` looks)."""
    ids, unreadable = set(), False
    trunk = trunk_name(state)
    for ref in (f"refs/remotes/origin/{trunk}", f"refs/heads/{trunk}"):
        code, sha = git_out("rev-parse", "--verify", "-q", f"{ref}^{{commit}}")
        if code == 0 and sha:
            stories, bad = read_stories(sha, cfg)
            ids |= {s["id"] for s in stories}
            unreadable = bool(bad)
            break
    pattern = glob_regex(cfg["stories"])
    code, out = git_out("ls-files", "-z", "--cached")
    for rel in out.split("\0") if code == 0 else []:
        if rel and pattern.fullmatch(rel):
            try:
                story = build_story(rel, (ROOT / rel).read_bytes(), cfg["id_from"])
            except OSError:
                continue
            if story:
                ids.add(story["id"])
    return ids, unreadable


def trailer_lines(cfg: dict, sid: str = "<ID>") -> list[str]:
    return [f"    Part-of: {sid}", f"    Story: {sid}", "    No-story: <category> — <reason>"]


def message_problems(state: dict, cfg: dict, text: str) -> list[tuple[str, list[str]]]:
    """(code, lines that explain it and name what to write) for each rule of docs/ledger.md, "Trailers", the
    message breaks. A merge and a fixup!/squash!/amend! need no attribution; their trailers are still checked."""
    trailers = message_trailers(text)
    categories = ", ".join(cfg["no_story"])
    last = ("as the message's last paragraph: after a blank line, together with any Co-Authored-By: or "
            "Claude-Session: line, with no blank line between them (git reads trailers only there)")
    problems: list[tuple[str, list[str]]] = []
    story = trailer_ids(trailers, "Story")
    named = story + trailer_ids(trailers, "Part-of")
    junk = sorted({p.strip() for key in ("Story", "Part-of") for v in trailer_values(trailers, key)
                   for p in v.split(",") if not STORY_ID.fullmatch(p.strip())})
    squashed = SQUASHED_TRAILER.findall(text)
    if not attributed(trailers) and not merging() and not exempt_subject(text):
        if squashed:
            moved = sorted({f"{k.capitalize() if k.lower() == 'story' else 'Part-of'}: {i}" for k, i in squashed})
            problems.append(("SQUASH_LOST_TRAILERS", [
                f"{', '.join(moved)} is not in the message's last paragraph, so git does not read it and the commit "
                "names no story.", f"Move it {last}:", *(f"    {m}" for m in moved)]))
        else:
            problems.append(("UNATTRIBUTED", [
                "this commit names no story: the message has no Story:, Part-of: or No-story: trailer.",
                f"Add one of these lines {last}:", *trailer_lines(cfg),
                "Part-of: <ID> is work of story <ID> that does not close it; Story: <ID> closes it (the message then "
                "needs a body); No-story: is work outside stories, its category one of: " + categories + ".",
                f"`{LEDGER_CMD} take <ID>` makes this worktree's commits carry Part-of: <ID> by themselves."]))
    else:
        lost = sorted({i for k, i in squashed if k.lower() == "story" and i not in story})
        if lost:
            problems.append(("SQUASH_LOST_TRAILERS", [
                f"Story: {', '.join(lost)} is not in the message's last paragraph, so git does not read it and the "
                "story is not closed.", f"Move it {last}:", *(f"    Story: {i}" for i in lost)]))
    ids, unreadable = known_story_ids(state, cfg)
    unknown = sorted({i for i in named if i not in ids})
    if unknown and not unreadable:
        problems.append(("UNKNOWN_STORY", [
            f"{', '.join(unknown)} is no story of [ledger] stories ({cfg['stories']}).",
            f"Name a story that exists (`{LEDGER_CMD} next` lists the ready ones), or write No-story: <category> — "
            f"<reason> for work outside stories (categories: {categories})."]))
    if junk:
        problems.append(("UNKNOWN_STORY", [
            f"Story:/Part-of: {', '.join(map(repr, junk))} is not a story id (EPIC-NNN, e.g. AUTH-001).",
            "Write it as:", *trailer_lines(cfg)[:2]]))
    bad = [v for v in trailer_values(trailers, "No-story") if not v.strip() or category(v) not in cfg["no_story"]]
    if bad:
        problems.append(("BAD_CATEGORY", [
            f"No-story: {bad[0]!r} is not one of [ledger] no_story: {categories}.",
            "Write it as `No-story: <category> — <reason>`, for example:", f"    No-story: {cfg['no_story'][0]} — <reason>"
            if cfg["no_story"] else "    (the list [ledger] no_story is empty: name a story instead)"]))
    if story and not split_message(text, trailers)[1]:
        problems.append(("STORY_NO_BODY", [
            f"Story: {', '.join(story)} closes the story, and a closing commit needs a body: at least one line "
            "between the subject and the trailers, saying what was decided and what was left out.",
            "For example:", "    <subject>", "", "    Decided: … Left out: …", "", f"    Story: {story[0]}"]))
    return problems


def cmd_hook(state: dict, args: tuple) -> int:
    """`hook prepare <file> [<source> [<sha>]]` (prepare-commit-msg): always exit 0. `hook msg <file>`
    (commit-msg): exit 1 when the message breaks the trailer grammar under `enforce = "block"`, else 0. Either
    one, when it cannot run (no git, an unreadable file), says so in one line and lets the commit through: the
    pre-push and the CI check again (LEDGER-010), and a broken hook must not stop every commit."""
    which, given, source = args
    try:
        path = Path(os.path.abspath(given))
        where = source_path()
        if which == "prepare" and source == "message" and editor_template(path.read_text(encoding="utf-8",
                                                                                         errors="replace")):
            source = "message-edit"  # -e with -m/-F: the editor runs, so git drops the comment lines
        if which == "prepare" and where:
            where.write_text(source + "\n", encoding="utf-8")
        if which == "msg":
            source = recorded_source()
        add_part_of(path, source)
        if which == "prepare":
            return 0
        cfg = read_config(state)
        text = readings(path.read_text(encoding="utf-8", errors="replace"), source)
        if not text.strip():
            return 0  # only the editor's comments: git aborts the commit itself ("empty commit message")
        problems = message_problems(state, cfg, text)
    except Exception as e:  # noqa: BLE001 - a broken hook must not stop every commit
        hook = "prepare-commit-msg" if which == "prepare" else "commit-msg"
        print(f"Keelokit: the {hook} hook could not check this commit ({' '.join(str(e).split())[:160]}); "
              "it goes through unchecked", file=sys.stderr)
        return 0
    if not problems:
        return 0
    for code, lines in problems:
        print(f"Keelokit: {code} — {lines[0]}", file=sys.stderr)
        for line in lines[1:]:
            print(f"  {line}" if line else "", file=sys.stderr)
    if cfg["enforce"] == "warn":
        print('Keelokit: the commit goes through ([ledger] enforce = "warn"); `git commit --amend` adds the line.',
              file=sys.stderr)
        return 0
    print('Keelokit: commit refused ([ledger] enforce = "block"): fix the message and commit again '
          f"(git keeps it: `git commit -e -F {given}`).", file=sys.stderr)
    return 1


def commit_of(ref: str) -> str | None:
    """The commit a sha or ref names in this clone, or None (an object the clone lacks, an all-zero sha)."""
    if not ref or ref.startswith("-") or not ref.strip("0"):
        return None
    return git_read(["rev-parse", "--verify", "-q", f"{ref}^{{commit}}"], ok=(0, 1, 128)).decode().strip() or None


def cmd_prepush(state: dict, remote: str, lines: list[str]) -> int:
    """`prepush <remote> [<url>]` (the pre-push hook, before the verify): git's lines on stdin, "<local ref> <local
    sha> <remote ref> <remote sha>". Each push to the trunk is checked over its new commits (those its remote sha,
    origin's trunk and `since` do not reach) as `check` checks the trunk: attribution, a merge that brings them, a
    squash of an origin branch that lost its trailers. A push to any other branch, or a deletion, is not checked;
    nor is anything without a `since`. Exit 1 refuses under `enforce = "block"`; with "warn" the same text, exit 0."""
    trunk = trunk_name(state)
    cfg = read_config(state)
    diffs = []
    for line in lines:
        parts = line.split()
        if len(parts) != 4 or parts[2] != f"refs/heads/{trunk}":
            continue
        tip = commit_of(parts[1])
        if tip is None:
            continue  # a deletion pushes nothing
        # What the remote this push goes to already has: its sha, and its remote-tracking trunk when it is a name.
        named = remote and not remote.startswith("-") and "/" not in remote and ":" not in remote
        exclude = [c for c in {commit_of(parts[3]), commit_of(f"refs/remotes/{remote}/{trunk}") if named else None}
                   if c]
        rctx = range_ctx(state, cfg, tip, exclude)
        if rctx is None:
            continue
        found = attribution_diffs(rctx, rctx["log"], on_trunk=False)
        source = commit_of(parts[3]) or commit_of(f"refs/remotes/origin/{trunk}")
        if found and source:
            # Approved rows attribute what they name (ESC-201), read from the trunk the remote (or origin) already
            # has, never from the pushed tip: a row pushed with its commit is accepted by nobody (ESC-205).
            try:
                held = read_graph([source])
                rctx["corrections"] = corrections_facts(source, None, set(held), held)
                found = attribution_diffs(rctx, rctx["log"], on_trunk=False)
            except LedgerError:
                pass  # unreadable corrections: the refusal stands
        diffs += found
    if not diffs:
        return 0
    for d in diffs:
        print(f"Keelokit: {d['code']} — {d['detail']}", file=sys.stderr)
    if not any(d["level"] == "error" for d in diffs):
        print(f"Keelokit: the push to {trunk} goes through (warnings only).", file=sys.stderr)
        return 0
    if cfg["enforce"] == "warn":
        print(f'Keelokit: the push to {trunk} goes through ([ledger] enforce = "warn"); the CI reports the same.',
              file=sys.stderr)
        return 0
    print(f'Keelokit: push to {trunk} refused ([ledger] enforce = "block"): nothing unattributed reaches the trunk '
          "(INV-007). Fix the commits named above and push again.", file=sys.stderr)
    return 1


def parse_command(argv: list[str]) -> tuple | None:
    """(command, arguments) for the corrections commands and check, or None for any other spelling."""
    if argv[:1] == ["check"]:
        rest, rules = list(argv[1:]), None
        if "--rules-ref" in rest:
            at = rest.index("--rules-ref")
            if at + 1 >= len(rest) or rest[at + 1].startswith("-"):
                return None
            rules = rest[at + 1]
            del rest[at:at + 2]
        if len(set(rest)) == len(rest) and set(rest) <= {"--json", "--ci"}:
            return "check", ("--json" in rest, "--ci" in rest, rules)
        return None
    if argv[:1] == ["show"] and len(argv) in (2, 3) and not argv[1].startswith("-") \
            and argv[2:] in ([], ["--full"], ["--json"]):
        return "show", (argv[1], argv[2][2:] if len(argv) == 3 else "card")
    if argv == ["next"]:
        return "next", None
    if argv[:1] == ["risky"] and len(argv) == 2 and STORY_ID.fullmatch(argv[1]):
        return "risky", argv[1]
    if argv[:1] == ["attribution"] and len(argv) >= 2 and not argv[1].startswith("-"):
        rest, rules = list(argv[2:]), None
        if "--rules-ref" in rest:
            at = rest.index("--rules-ref")
            if at + 1 >= len(rest) or rest[at + 1].startswith("-"):
                return None
            rules = rest[at + 1]
            del rest[at:at + 2]
        if rest in ([], ["--json"]):
            return "attribution", (argv[1], rest == ["--json"], rules)
        return None
    if argv == ["snapshot", "--branch"]:
        return "snapshot", (None, None, True)
    if argv[:1] == ["snapshot"]:
        opts = dict(zip(argv[1::2], argv[2::2]))
        if len(argv) % 2 == 1 and len(opts) == len(argv[1::2]) and set(opts) <= {"--run", "--push"} \
                and all(v and not v.startswith("-") for v in opts.values()):
            return "snapshot", (opts.get("--run"), opts.get("--push"), False)
        return None
    if argv[:1] == ["deploy"] and len(argv) == 3 and not argv[2].startswith("-"):
        return "deploy", (argv[1], argv[2])
    if argv[:1] == ["prepush"] and len(argv) in (2, 3):
        return "prepush", argv[1]
    if argv[:2] == ["hook", "prepare"] and 3 <= len(argv) <= 5:
        return "hook", ("prepare", argv[2], argv[3] if len(argv) > 3 else "")
    if argv[:2] == ["hook", "msg"] and len(argv) == 3:
        return "hook", ("msg", argv[2], "")
    if argv == ["take", "--clear"]:
        return "take", None
    if argv[:1] == ["take"] and len(argv) == 2 and STORY_ID.fullmatch(argv[1]):
        return "take", argv[1]
    if argv[:1] == ["drop"] and len(argv) == 4 and STORY_ID.fullmatch(argv[1]) and argv[2] == "--motivo":
        return "drop", (argv[1], argv[3])
    if argv[:1] == ["--release"] and len(argv) == 2 and not argv[1].startswith("-"):
        return "release", argv[1]
    if argv == ["backfill", "--accept"]:
        return "accept", None
    if argv[:3] == ["backfill", "--accept", "--delegated"] and len(argv) == 4:
        return "accept-delegated", argv[3]
    if argv == ["review", "--filter"]:
        return "filter", None
    if argv[:2] == ["review", "--reject-sample"] and len(argv) == 3:
        return "reject-sample", argv[2]
    if argv[:2] == ["backfill", "--propose"]:
        rest, sources = argv[2:], []
        while rest:
            if rest[0] != "--from" or len(rest) < 2 or not rest[1]:
                return None
            sources.append(rest[1])
            rest = rest[2:]
        return "propose", sources
    if argv[:1] == ["correct"] and len(argv) == 6 and not argv[1].startswith("--"):
        opts = dict(zip(argv[2::2], argv[3::2]))
        if sorted(opts) == ["--evidence", "--story"] and STORY_ID.fullmatch(opts["--story"]):
            return "correct", (argv[1], opts["--story"], opts["--evidence"])
    return None


def run_command(state: dict, command: str, args) -> int:
    try:
        if command == "check":
            return cmd_check(state, args)
        if command == "show":
            return cmd_show(state, args)
        if command == "next":
            return cmd_next(state)
        if command == "risky":
            return cmd_risky(state, args)
        if command == "attribution":
            return cmd_attribution(state, args)
        if command == "hook":
            return cmd_hook(state, args)
        if command == "prepush":
            return cmd_prepush(state, args, [] if sys.stdin.isatty() else sys.stdin.read().splitlines())
        if command == "take":
            return cmd_take(state, args)
        if command == "snapshot":
            return cmd_snapshot(state, args)
        if command == "deploy":
            return cmd_deploy(state, *args)
        if command == "drop":
            return cmd_drop(state, *args)
        if command == "release":
            return cmd_release(state, args)
        if command == "propose":
            return cmd_propose(state, args)
        if command == "correct":
            return cmd_correct(state, *args)
        if command == "filter":
            return cmd_filter(state)
        if command == "accept-delegated":
            return cmd_accept_delegated(state, args)
        if command == "reject-sample":
            return cmd_reject_sample(state, args)
        return cmd_accept(state)
    except LedgerError as e:
        print(f"Keelokit: {e}", file=sys.stderr)
        return 2


# ── the summary ──

def listed(items: list[str], more: str, limit: int = 6) -> str:
    return ", ".join(items[:limit]) + (f", +{len(items) - limit} {more}" if len(items) > limit else "")


def summary(facts: dict, lang: str) -> list[str]:
    """At most 10 lines: trunk and history, counts per state, then what needs a look."""
    t = LABELS[lang]
    head = f"{facts['trunk']}@{facts['trunk_sha'][:7]}"
    stories = facts["stories"]
    if facts["history"] == "incomplete":
        return [f"{head}: {t['cut']}", stories[0]["reason"] if stories else FIX,
                f"{len(stories)} {t['stories']}: {STATE_NAMES[lang]['unknown']} {len(stories)}"]
    if facts["history"].startswith("snapshot:"):
        lines = [f"{head}: {t['snapshot'].format(sha=facts['history'][9:16])}"]
    else:
        lines = [f"{head}: {t['complete']}"]
    counts = {s: sum(1 for r in stories if r["state"] == s) for s in (*STATES, "unknown")}
    shown = ", ".join(f"{STATE_NAMES[lang][s]} {n}" for s, n in counts.items() if n)
    lines.append(f"{len(stories)} {t['stories']}: {shown}" if stories else t["none"])
    progress = [f"{r['id']} ({', '.join(r['branches'][:2])}{'; ' + t['stale'] if r['signals'] else ''})"
                for r in stories if r["state"] == "in-progress"]
    delivered = [f"{r['id']} (convoy {r['convoy']})" if r.get("convoy") is not None else r["id"]
                 for r in stories if r["state"] == "delivered"]
    ready = [r["id"] for r in stories if r["state"] == "ready"]
    reverted = [r["id"] for r in stories if r["reverted"]]
    unknown = [r["id"] for r in stories if r["state"] == "unknown"]
    person = [r["id"] for r in stories if r.get("reconstructed") and r.get("reconstructed_by") != "delegated"]
    delegated = [r["id"] for r in stories if r.get("reconstructed") and r.get("reconstructed_by") == "delegated"]
    for label, items in (("progress", progress), ("delivered", delivered), ("ready", ready), ("reverted", reverted),
                         ("unknown", unknown),
                         ("by_person", person), ("by_delegated", delegated)):
        if items:
            lines.append(f"{t[label]}: {listed(items, t['more'])}")
    loose = facts["unattributed"]
    if loose["commits"]:
        lines.append(f"{t['unattributed']} {loose['since'][:7]}: {loose['commits']} ({loose['ratio']:.0%})")
    return lines


def show(state: dict, as_json: bool) -> int:
    """`ledger.py` and `ledger.py --json`: exit 1 when `diffs` is not empty, 2 when a fact cannot be read."""
    try:
        facts = ledger_facts(state)
    except LedgerError as e:
        print(f"Keelokit: {e}", file=sys.stderr)
        return 2
    if as_json:
        print(json.dumps(facts, indent=1))
    else:
        print("\n".join(summary(facts, read_config(state)["lang"])))
    return 1 if facts["diffs"] else 0


def main(argv: list[str]) -> int:
    if PLUGIN_MODE and (why := git_dir_problem()):  # ESC-280: run by the plugin's hooks, no git where git can't be trusted
        if argv != ["history", "--ensure"]:
            print(f"Keelokit: {why}.", file=sys.stdout if not argv else sys.stderr)
        return 0 if argv in ([], ["history", "--ensure"]) else 2
    state = read_state()
    if argv in ([], ["--json"]):
        try:
            return show(state, bool(argv))
        except Exception as e:  # noqa: BLE001 - a bug is an environment failure, never a lower answer
            print(f"Keelokit: the ledger failed ({type(e).__name__}: {' '.join(str(e).split())[:120]})",
                  file=sys.stderr)
            return 2
    if (parsed := parse_command(argv)) is not None:
        try:
            return run_command(state, *parsed)
        except Exception as e:  # noqa: BLE001 - a bug is an environment failure, never a lower answer
            print(f"Keelokit: the ledger failed ({type(e).__name__}: {' '.join(str(e).split())[:120]})",
                  file=sys.stderr)
            return 2
    if argv[:1] != ["history"] or any(a != "--ensure" for a in argv[1:]) or len(argv) > 2:
        print(USAGE, file=sys.stderr)
        return 2
    do_ensure = "--ensure" in argv
    trunk = trunk_name(state)
    try:
        return history(do_ensure, state, trunk)
    except Exception as e:  # noqa: BLE001 - the hook must never fail a session
        if not do_ensure:
            raise
        print(f"Keelokit: history check failed ({type(e).__name__}: {' '.join(str(e).split())[:120]}); "
              f"run `git fetch --unshallow origin {trunk}`")
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
