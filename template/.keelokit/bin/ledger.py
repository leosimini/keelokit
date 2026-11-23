#!/usr/bin/env python3
"""Keelokit ledger. Stdlib only (Python 3.11+ for tomllib).

    python3 .keelokit/bin/ledger.py                    summary of every story's state, at most 10 lines
    python3 .keelokit/bin/ledger.py --json             the same facts, schema 1 (docs/ledger.md)
                                                       (exit 0 no difference, 1 differences, 2 no git or no trunk)
    python3 .keelokit/bin/ledger.py history            report: is the trunk's history complete?
                                                       (exit 0 complete, 1 incomplete, 2 not a git repo)
    python3 .keelokit/bin/ledger.py history --ensure   complete it (SessionStart hook); always exit 0
    python3 .keelokit/bin/ledger.py check [--json]     every difference (exit 1 on an error-level one)
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
answer). `delivered` (Harbor) is not read here.

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
import math  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import signal  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402
import tomllib  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
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


def run_git(args: list[str], timeout: float | None = None) -> tuple[int | None, str]:
    """(returncode, stderr). returncode None: cut at `timeout`, the process group is gone."""
    proc = subprocess.Popen(["git", *NOPROMPT, *args], cwd=ROOT, env=git_env(), stdin=subprocess.DEVNULL,
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


def ensure(trunk: str, cap: float) -> str:
    """Complete the history; the one line to print."""
    fix = f"`git fetch --unshallow origin {trunk}`"
    if git_out("remote", "get-url", "origin")[0]:
        return f"Keelokit: no origin: history incomplete; add a remote, then run {fix}"
    snapshot = {k: config_get(k) for k in KEYS}
    honoured = False
    try:
        line, honoured = fetch_history(trunk, cap, fix)
        return line
    finally:
        # git writes the promisor config before it contacts the server: whatever does not end as a
        # complete fetch whose filter the server honoured (failed, cut, ignored, plain fallback)
        # leaves the config as it was, so a later fetch neither warns forever nor comes back partial.
        if not honoured:
            restore_config(snapshot)


def fetch_history(trunk: str, cap: float, fix: str) -> tuple[str, bool]:
    """(the one line, whether a complete fetch's filter was honoured)."""
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
        return f"Keelokit: cut at {cap:g}s: history incomplete; run {fix}", False
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
        return 0
    if trunk.startswith("-") or git_out("check-ref-format", "--branch", trunk)[0]:
        print(f"Keelokit: trunk {trunk!r} is not a branch name: history incomplete")
        return 0 if do_ensure else 1
    if not do_ensure:
        print("Keelokit: history incomplete (shallow clone); run `python3 .keelokit/bin/ledger.py history --ensure`")
        return 1
    print(ensure(trunk, cap_seconds(state)))
    return 0


# ───────────────────────── states of every story (LEDGER-003) ─────────────────────────

STATES = ("defined", "ready", "in-progress", "on-trunk", "in-version", "in-staging", "in-production")
ENVIRONMENTS = ("staging", "production")
READ_CONFIG = ["-c", "log.showSignature=false", "-c", "i18n.logOutputEncoding=UTF-8"]
STORY_ID = re.compile(r"[A-Z][A-Z0-9]*-[0-9]+")
VERSION_TAG = re.compile(r"v([0-9]+(?:\.[0-9]+)*)(?:-rc\.([0-9]+))?")
REVERTS = re.compile(r"^This reverts commit ([0-9a-f]{40}|[0-9a-f]{64})(?=[.,]|$)", re.M)
FRONT_MATTER = re.compile(r"\+\+\+\n(.*?)\n\+\+\+(?:\n|$)", re.S)
HEX_SHA = re.compile(r"[0-9a-fA-F]{7,64}")
DEFAULT_STORIES = "backlog/stories/*.md"
DEFAULT_STALE_DAYS = 7
FIX = "run `python3 .keelokit/bin/ledger.py history --ensure`"
CORRECTIONS = "backlog/ledger-corrections.toml"
PROPOSED = ".keelokit/ledger-corrections.proposed.toml"
KINDS = ("backfill", "late", "retract")
REVIEWS = ".keelokit/ledger-reviews"
STATE_FILE = ".keelokit/state.toml"
CRITICAL_FILE = ".keelokit/critical.toml"
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
    "es": {"defined": "definida", "ready": "lista", "in-progress": "en curso", "on-trunk": "en trunk",
           "in-version": "en versión", "in-staging": "en staging", "in-production": "en producción",
           "unknown": "desconocida"},
}
LABELS = {
    "en": {"complete": "history complete", "cut": "history INCOMPLETE: every state is unknown",
           "stories": "stories", "progress": "in progress", "ready": "ready", "reverted": "reverted",
           "unknown": "unknown", "stale": "stale", "more": "more", "none": "no stories found",
           "unattributed": "unattributed commits since", "reconstructed": "reconstructed",
           "by_person": "reconstructed (person)", "by_delegated": "reconstructed (delegated)"},
    "es": {"complete": "historia completa", "cut": "historia INCOMPLETA: todos los estados son desconocidos",
           "stories": "historias", "progress": "en curso", "ready": "listas", "reverted": "revertidas",
           "unknown": "desconocidas", "stale": "estancada", "more": "más", "none": "no hay historias",
           "unattributed": "commits sin atribuir desde", "reconstructed": "reconstruidas",
           "by_person": "reconstruidas (persona)", "by_delegated": "reconstruidas (delegada)"},
}


class LedgerError(Exception):
    """A fact could not be read: the run ends with exit 2 and this reason, never a partial answer."""


def git_read(args: list[str], data: bytes | None = None, ok: tuple = (0,)) -> bytes:
    """stdout of one git call (LC_ALL=C, no prompts); LedgerError when it cannot run or exits outside `ok`."""
    kwargs = {"input": data} if data is not None else {"stdin": subprocess.DEVNULL}
    try:
        r = subprocess.run(["git", *NOPROMPT, *READ_CONFIG, *args], cwd=ROOT,
                           env={**git_env(), "GIT_NO_LAZY_FETCH": "1"},  # reading never fetches a missing object
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
    return {"stories": setting(state, "stories", str, DEFAULT_STORIES).strip(),
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

def read_refs(trunk: str) -> dict[str, str]:
    """Commit of each ref that matters: v* tags (fully peeled), every origin branch, the local trunk."""
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
    return refs


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
    path = Path(git_read(["rev-parse", "--git-path", "shallow"]).decode().strip() or "shallow")
    try:
        marked = set((path if path.is_absolute() else ROOT / path).read_text().split())
    except OSError as e:  # shallow, yet its file cannot be read: no answer from a possibly cut history
        raise LedgerError(f"the shallow file cannot be read ({e.strerror or e})") from e
    reach = sorted(marked & set(graph))
    if reach and git_cut(reach, graph):
        return f"the clone is shallow and cut the history ({len(graph)} commits reachable); {FIX}"
    return None


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
                "unreadable": True, "touches": [], "dimensions": []}
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
            "dimensions": text_list(meta.get("dimensions"))}


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


def read_trunk_files(trunk_sha: str, tree: list[tuple[str, str]]) -> dict:
    """What the approval modes read from the trunk's tree, in one `cat-file`: state.toml, critical.toml and the
    review files ({run: bytes}). A file the clone lacks reads as absent."""
    wanted = {path: sha for path, sha in tree if path in (STATE_FILE, CRITICAL_FILE)
              or (path.startswith(REVIEWS + "/") and path.endswith(".json")
                  and RUN_ID.fullmatch(path[len(REVIEWS) + 1:-5]) and "/" not in path[len(REVIEWS) + 1:])}
    blobs = read_blobs(list(wanted.values()), trunk_sha)
    content = {path: blobs.get(sha) for path, sha in wanted.items()}
    reviews = {path[len(REVIEWS) + 1:-5]: data for path, data in content.items()
               if path.startswith(REVIEWS + "/") and data is not None}
    return {"state": content.get(STATE_FILE), "critical": content.get(CRITICAL_FILE), "reviews": reviews}


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
            stories[story["id"]] = story
    return sorted(stories.values(), key=lambda s: s["id"]), unreadable


def read_log(args: list[str]) -> list[list[str]]:
    """Records of a NUL-separated log: 7 fields, the last the raw body, so no message can break the parsing."""
    fmt = ("%H%x00%P%x00%ct%x00%(trailers:key=Story,valueonly,separator=%x2C,unfold)%x00"
           "%(trailers:key=Part-of,valueonly,separator=%x2C,unfold)%x00"
           "%(trailers:key=No-story,valueonly,separator=%x2C,unfold)%x00%B")
    parts = git_read(["log", "-z", f"--format={fmt}", *args]).decode(errors="replace").split("\0")
    if parts and parts[-1] == "":
        parts.pop()
    if len(parts) % 7:
        raise LedgerError("git log gave an unexpected answer")
    return [parts[i:i + 7] for i in range(0, len(parts), 7)]


def story_ids(field: str) -> list[str]:
    return [i for i in (p.strip() for p in field.split(",")) if STORY_ID.fullmatch(i)]


def read_trunk_log(trunk_sha: str) -> list[dict]:
    """Every trunk commit, children before parents: sha, parents, ct, trailers, the commits it reverts."""
    return [{"sha": sha, "parents": parents.split(), "ct": int(ct), "story": story_ids(story),
             "part_of": story_ids(part), "attributed": bool(story.strip() or part.strip() or nostory.strip()),
             "no_story": bool(nostory.strip()), "reverts": REVERTS.findall(body), "message": body}
            for sha, parents, ct, story, part, nostory, body in read_log(["--topo-order", trunk_sha])]


def read_branches(trunk_sha: str, refs: dict, graph: dict, on_trunk: set) -> dict[str, dict]:
    """story id -> {branches, newest}: every origin branch whose commits off the trunk include a Part-of
    commit of the story. One log finds the Part-of commits; each branch tip gets a bit, and the bits flow from
    the tips to their parents in one pass over the off-trunk commits (children before parents)."""
    fmt = "%H%x00%ct%x00%(trailers:key=Part-of,valueonly,separator=%x2C,unfold)"
    out = git_read(["log", "-z", f"--format={fmt}", "--remotes=origin", "--not", trunk_sha]).decode(errors="replace")
    parts = out.split("\0")
    if parts and parts[-1] == "":
        parts.pop()
    if len(parts) % 3:
        raise LedgerError("git log gave an unexpected answer")
    marked = {sha: (story_ids(trailer), int(ct)) for sha, ct, trailer in (parts[i:i + 3] for i in range(0, len(parts), 3))
              if story_ids(trailer)}
    if not marked:
        return {}
    names = [n for n in sorted(refs) if n.startswith("refs/remotes/origin/") and n != "refs/remotes/origin/HEAD"]
    masks = flow_masks(graph, on_trunk, [(1 << i, refs[n]) for i, n in enumerate(names)])
    result: dict[str, dict] = {}
    for sha, (ids, ct) in marked.items():
        for sid in ids:
            entry = result.setdefault(sid, {"mask": 0, "newest": 0})
            entry["mask"] |= masks.get(sha, 0)
            entry["newest"] = max(entry["newest"], ct)
    return {sid: {"branches": {names[i].removeprefix("refs/remotes/origin/") for i in set_bits(e["mask"])},
                  "newest": e["newest"]} for sid, e in result.items() if e["mask"]}


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
            "swarm": [], "signals": [], "reason": None, "path": story["path"]}


def mark_unknown(records: list[dict], reason: str) -> None:
    for r in records:
        r["state"], r["reason"] = "unknown", reason


def on_trunk_facts(rec: dict, sha: str, arrival: dict, ct: dict, tags: tuple, deploys: dict) -> None:
    """Fill what a Story: commit on the trunk gives: its approximate date, the first final tag, the deploys."""
    rec.update(commit=sha, since=iso(ct[arrival[sha]]), since_exact=False, version=tags[0].get(sha),
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
                   corrections: dict | None = None) -> list[dict]:
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
    if corrections["unreadable"]:
        for rec in records.values():
            if not rec["commit"]:
                mark_unknown([rec], corrections["unreadable"])
    settle_dependencies(stories, records, unreadable)
    for sid, rec in records.items():
        if sid in branches and rec["state"] in ("defined", "ready"):
            rec["state"] = "in-progress"
            if now - branches[sid]["newest"] > stale_days * 86400:
                rec["signals"] = ["stale"]
    return list(records.values())


def unattributed(cfg: dict, log: list[dict], graph: dict, arrival_of: dict) -> dict:
    """Trunk commits after `since` with no Story:/Part-of:/No-story:, nor a merge that brought them with one."""
    since = cfg["since"]
    base = {"since": since, "commits": 0, "ratio": 0.0}
    if since is None:
        return base
    matches = [s for s in graph if s.startswith(since.lower())]
    if len(matches) != 1:
        return base
    held = set(first_reach(graph, [matches[0]]))
    by_sha = {c["sha"]: c for c in log}
    in_range = [c for c in log if c["sha"] not in held]
    loose = sum(1 for c in in_range if not c["attributed"] and not by_sha[arrival_of[c["sha"]]]["attributed"])
    return {**base, "commits": loose, "ratio": loose / len(in_range) if in_range else 0.0}


def ledger_facts(state: dict) -> dict:
    """Everything `--json` prints (schema 1): reads git, raises LedgerError when a fact cannot be read."""
    return read_all(state)["facts"]


def read_all(state: dict) -> dict:
    """The facts and what they were computed from (for the commands that propose or accept corrections):
    facts, and with a complete history also stories, log, graph, placed (arrivals), corrections, records."""
    cfg = read_config(state)
    trunk = trunk_name(state)
    shallow = git_read(["rev-parse", "--is-shallow-repository"]).decode().strip() == "true"
    check_trunk(trunk)
    refs = read_refs(trunk)
    trunk_sha = resolve_trunk(trunk, refs)
    tree = read_tree(trunk_sha)
    stories, unreadable = read_stories(trunk_sha, cfg, tree)
    extra = read_trunk_files(trunk_sha, tree)
    reviews = {run: parse_review(data, run) for run, data in extra["reviews"].items()}
    tags = [sha for _, _, sha in version_tags(refs)]
    remotes = [sha for name, sha in refs.items() if name.startswith("refs/remotes/origin/")]
    graph = read_graph(sorted({trunk_sha, *tags, *remotes}))
    reason = cut_reason(graph, shallow)
    facts = {"schema": 1, "trunk": trunk, "trunk_sha": trunk_sha, "history": "incomplete" if reason else "complete",
             "stories": [], "unattributed": {"since": cfg["since"], "commits": 0, "ratio": 0.0}, "diffs": []}
    if reason:
        facts["stories"] = [new_story(s) for s in stories]
        mark_unknown(facts["stories"], reason)
        level = "error" if os.environ.get("CI", "").lower() not in ("", "0", "false") else "warning"
        facts["diffs"].append({"level": level, "code": "HISTORY_INCOMPLETE", "detail": reason})
        return {"facts": facts, "reason": reason}
    log = read_trunk_log(trunk_sha)
    placed = arrivals(graph, trunk_sha)
    corrections = corrections_facts(trunk_sha, {s["id"] for s in stories if not s.get("unreadable")} if not unreadable
                                    else None, set(placed[0]), graph, reviews)
    facts["stories"] = compute_states(stories, unreadable, log, graph, refs, placed, read_branches(trunk_sha, refs, graph, set(placed[0])),
                                      cfg["stale_days"], time.time(), corrections)
    facts["unattributed"] = unattributed(cfg, log, graph, placed[0])
    facts["diffs"] += corrections["diffs"]
    records = {r["id"]: r for r in facts["stories"]}
    facts["diffs"] += pending_reviews(reviews, records)
    return {"facts": facts, "reason": None, "cfg": cfg, "trunk_sha": trunk_sha, "stories": stories, "log": log,
            "graph": graph, "placed": placed, "corrections": corrections, "records": records, "reviews": reviews,
            "approval": approval_config(extra["state"]), "areas": critical_areas(extra["critical"])}


# ── corrections (docs/ledger.md, "Corrections file") ──

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
    `reviews`: {run: parsed review file or None} of the trunk, which back the rows a delegated review approved."""
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
        return delegated_problem(values, reviews or {})
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
            result["active"], result["diffs"] = apply_rows(rows, story_ids, reachable, CORRECTIONS, reviews=reviews)
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
        numbers = {int(n) for n in CONVOY_TRAILER.findall(c["message"])} | {int(n) for n in TRAIN_WORD.findall(subject)}
        branch = merged_branch(subject) if len(c["parents"]) > 1 else None
        if branch and (m := TRAIN_BRANCH.match(branch)):
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
        if c["no_story"] or c["reverts"] or reverted.get(c["sha"]):
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
    reviews = known_reviews(ctx)
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


def delegated_problem(values: dict, reviews: dict) -> str | None:
    """Why a row approved by `delegated:<run>` cannot count: its review file, on the trunk, must hold the same
    story, commit and kind with decision approved, both judges yes and the skeptic's refutation failed."""
    run = delegated_run(values["approver"])
    if not RUN_ID.fullmatch(run):
        return f"the delegated approver {values['approver']!r} names no valid run"
    if run not in reviews:
        return f"a delegated row needs its review file {REVIEWS}/{run}.json on the trunk"
    review = reviews[run]
    if review is None:
        return f"{REVIEWS}/{run}.json is not a review file of run {run}"
    same = [r for r in review["rows"] if isinstance(r, dict)
            and (r.get("story"), r.get("commit"), r.get("kind")) == (values["story"], values["commit"], values["kind"])]
    if not any(r.get("decision") == "approved" and judges_approve(r) for r in same):
        return f"{REVIEWS}/{run}.json does not show this row approved by both judges with the skeptic's refutation failed"
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


def filter_rows(ctx: dict, rows: list, active: set) -> list[tuple[dict | None, str | None]]:
    """The mechanical filter (no model), one (kept row, None) or (None, why it is dropped) per row: the commit
    is a full sha on the trunk, the story exists and is not on the trunk yet, the row repeats no active row
    (`active`: (story, commit)) nor an earlier one, the evidence is there, and the commit's diff touches one of
    the story's `touches` when it has any."""
    stories = {s["id"]: s for s in ctx["stories"]}
    reachable, records, areas = ctx["placed"][0], ctx["records"], ctx["areas"]
    seen, results = set(), []
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
               else None)
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
    active, _ = apply_rows(rows, known, ctx["placed"][0], CORRECTIONS, reviews=known_reviews(ctx))
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
                          {**known_reviews(ctx), run: review})
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
    active, _ = apply_rows(current, known, ctx["placed"][0], CORRECTIONS, reviews=known_reviews(ctx))
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


def cmd_check(state: dict, as_json: bool) -> int:
    """Every difference: one line each, or `{"schema": 1, "diffs": [...]}`. Exit 1 on an error-level one."""
    facts = ledger_facts(state)
    if as_json:
        print(json.dumps({"schema": 1, "diffs": facts["diffs"]}, indent=1))
    else:
        for d in facts["diffs"]:
            print(f"{d['level']} {d['code']} {d['detail']}")
    return 1 if any(d["level"] == "error" for d in facts["diffs"]) else 0


def parse_command(argv: list[str]) -> tuple | None:
    """(command, arguments) for the corrections commands and check, or None for any other spelling."""
    if argv[:1] == ["check"] and argv[1:] in ([], ["--json"]):
        return "check", bool(argv[1:])
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
    lines = [f"{head}: {t['complete']}"]
    counts = {s: sum(1 for r in stories if r["state"] == s) for s in (*STATES, "unknown")}
    shown = ", ".join(f"{STATE_NAMES[lang][s]} {n}" for s, n in counts.items() if n)
    lines.append(f"{len(stories)} {t['stories']}: {shown}" if stories else t["none"])
    progress = [f"{r['id']} ({', '.join(r['branches'][:2])}{'; ' + t['stale'] if r['signals'] else ''})"
                for r in stories if r["state"] == "in-progress"]
    ready = [r["id"] for r in stories if r["state"] == "ready"]
    reverted = [r["id"] for r in stories if r["reverted"]]
    unknown = [r["id"] for r in stories if r["state"] == "unknown"]
    person = [r["id"] for r in stories if r.get("reconstructed") and r.get("reconstructed_by") != "delegated"]
    delegated = [r["id"] for r in stories if r.get("reconstructed") and r.get("reconstructed_by") == "delegated"]
    for label, items in (("progress", progress), ("ready", ready), ("reverted", reverted), ("unknown", unknown),
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
