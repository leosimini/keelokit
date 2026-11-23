#!/usr/bin/env python3
"""Keelokit ledger. Stdlib only (Python 3.11+ for tomllib).

    python3 .keelokit/bin/ledger.py                    summary of every story's state, at most 10 lines
    python3 .keelokit/bin/ledger.py --json             the same facts, schema 1 (docs/ledger.md)
                                                       (exit 0 no difference, 1 differences, 2 no git or no trunk)
    python3 .keelokit/bin/ledger.py history            report: is the trunk's history complete?
                                                       (exit 0 complete, 1 incomplete, 2 not a git repo)
    python3 .keelokit/bin/ledger.py history --ensure   complete it (SessionStart hook); always exit 0

Any other command line prints the usage and exits 2.

The states are derived from git alone, never declared (docs/ledger.md, "States"): defined, ready,
in-progress, on-trunk, in-version, in-staging, in-production, or unknown. Stories are read from the
trunk's tree (`[ledger] stories`, `id_from`), the trunk is origin/<trunk> else the local branch (never
HEAD). A fixed number of git calls whatever the number of stories, commits or tags: the parent graph
comes from one `rev-list --parents` and arrivals, tags and deploys are walked in Python. Fail closed:
a cut history makes every state unknown with the reason, and a failing git call exits 2 (no partial
answer). `delivered` (Harbor) and corrections are not read here.

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
           "unattributed": "unattributed commits since"},
    "es": {"complete": "historia completa", "cut": "historia INCOMPLETA: todos los estados son desconocidos",
           "stories": "historias", "progress": "en curso", "ready": "listas", "reverted": "revertidas",
           "unknown": "desconocidas", "stale": "estancada", "more": "más", "none": "no hay historias",
           "unattributed": "commits sin atribuir desde"},
}


class LedgerError(Exception):
    """A fact could not be read: the run ends with exit 2 and this reason, never a partial answer."""


def git_read(args: list[str], data: bytes | None = None) -> bytes:
    """stdout of one git call (LC_ALL=C, no prompts); LedgerError when it cannot run or fails."""
    kwargs = {"input": data} if data is not None else {"stdin": subprocess.DEVNULL}
    try:
        r = subprocess.run(["git", *NOPROMPT, *READ_CONFIG, *args], cwd=ROOT,
                           env={**git_env(), "GIT_NO_LAZY_FETCH": "1"},  # reading never fetches a missing object
                           capture_output=True, **kwargs)
    except OSError as e:
        raise LedgerError(f"cannot run git ({e})") from e
    if r.returncode:
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


def read_blobs(shas: list[str], trunk_sha: str) -> dict[str, bytes | None]:
    """Contents of blobs by sha in one `cat-file --batch`; None for one the clone lacks (never fetched)."""
    unique = sorted(set(shas))
    if not unique:
        return {}
    absent = missing_objects(trunk_sha)
    present = [sha for sha in unique if sha not in absent]
    out = git_read(["cat-file", "--batch"], "".join(f"{s}\n" for s in present).encode()) if present else b""
    blobs, pos = {sha: None for sha in absent & set(unique)}, 0
    for sha in present:
        end = out.find(b"\n", pos)
        head = out[pos:end].split() if end >= 0 else []
        if len(head) < 2:
            raise LedgerError("git cat-file gave an unexpected answer")
        if head[1] == b"missing":
            raise LedgerError(f"git cat-file lost the object {sha}")
        size = int(head[2])
        blobs[sha], pos = out[end + 1:end + 1 + size], end + 1 + size + 1
    return blobs


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
                "unreadable": True}
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
            "path": path, "unreadable": False}


def read_stories(trunk_sha: str, cfg: dict) -> list[dict]:
    """The stories of the trunk's tree: `ls-tree` and one `cat-file --batch`; a duplicate id keeps the first path."""
    pattern = glob_regex(cfg["stories"])
    found = []
    for rec in git_read(["ls-tree", "-r", "-z", "--full-tree", trunk_sha]).decode(errors="replace").split("\0"):
        meta, _, path = rec.partition("\t")
        fields = meta.split()
        if len(fields) == 3 and fields[0] != "120000" and fields[1] == "blob" and pattern.fullmatch(path):
            found.append((path, fields[2]))
    found.sort()
    blobs = read_blobs([sha for _, sha in found], trunk_sha)
    stories = {}
    for path, sha in found:
        story = build_story(path, blobs[sha], cfg["id_from"])
        if story and story["id"] not in stories:
            stories[story["id"]] = story
    return sorted(stories.values(), key=lambda s: s["id"])


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
             "reverts": REVERTS.findall(body)}
            for sha, parents, ct, story, part, nostory, body in read_log(["--topo-order", trunk_sha])]


def read_branches(trunk_sha: str, refs: dict, graph: dict, on_trunk: set) -> dict[str, dict]:
    """story id -> {branches, newest}: every origin branch whose commits off the trunk include a Part-of
    commit of the story. One log finds the Part-of commits; the branches' tips walk the parent graph."""
    fmt = "%H%x00%ct%x00%(trailers:key=Part-of,valueonly,separator=%x2C,unfold)"
    out = git_read(["log", "-z", f"--format={fmt}", "--remotes=origin", "--not", trunk_sha]).decode(errors="replace")
    parts = out.split("\0")
    if parts and parts[-1] == "":
        parts.pop()
    if len(parts) % 3:
        raise LedgerError("git log gave an unexpected answer")
    marked = {sha: (story_ids(trailer), int(ct)) for sha, ct, trailer in (parts[i:i + 3] for i in range(0, len(parts), 3))
              if story_ids(trailer)}
    result: dict[str, dict] = {}
    for name, tip in sorted(refs.items()):
        if not name.startswith("refs/remotes/origin/") or name == "refs/remotes/origin/HEAD" or not marked:
            continue
        branch = name.removeprefix("refs/remotes/origin/")
        stack, seen = [tip], set()
        while stack:
            sha = stack.pop()
            if sha in seen or sha in on_trunk:
                continue
            seen.add(sha)
            stack.extend(graph.get(sha, ()))
            for sid in marked.get(sha, ((), 0))[0]:
                entry = result.setdefault(sid, {"branches": set(), "newest": 0})
                entry["branches"].add(branch)
                entry["newest"] = max(entry["newest"], marked[sha][1])
    return result


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

def revert_status(log: list[dict], arrival: dict) -> dict[str, bool]:
    """sha -> reverted. A revert on the trunk counts unless it is itself reverted (children come first).
    Reverting a trunk commit reverts every commit it brought: a merge reverts what it merged."""
    brought: dict[str, list[str]] = {}
    for sha, via in arrival.items():
        brought.setdefault(via, []).append(sha)
    reverters: dict[str, list[str]] = {}
    for c in log:
        for target in c["reverts"]:
            for sha in brought.get(target, [target]):
                reverters.setdefault(sha, []).append(c["sha"])
    status: dict[str, bool] = {}
    for c in log:
        status[c["sha"]] = any(not status.get(r, False) for r in reverters.get(c["sha"], ()))
    return status


def story_commits(log: list[dict], arrival: dict, order: dict) -> tuple[dict, set]:
    """({id: its oldest Story: commit not reverted}, {ids whose Story: commits are all reverted})."""
    reverted = revert_status(log, arrival)
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
            "reconstructed": False, "reverted": False, "branches": [], "attempts": [], "swarm": [],
            "signals": [], "reason": None, "path": story["path"]}


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


def settle_dependencies(stories: list[dict], records: dict) -> None:
    """Unreadable stories are unknown, and so is whatever depends on them, through any chain and in any id
    order (a walk from them over the dependents); every other story without a Story: commit is ready
    when each dependency has one, else defined."""
    dependents: dict[str, list[str]] = {}
    for story in stories:
        for d in story["depends_on"]:
            dependents.setdefault(d, []).append(story["id"])
    queue = []
    for story in stories:
        if story.get("unreadable"):
            mark_unknown([records[story["id"]]], f"the story file {story['path']} cannot be read from the trunk's tree")
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


def compute_states(stories: list[dict], log: list[dict], graph: dict, refs: dict, arrivals_: tuple,
                   branches: dict, stale_days: float, now: float) -> list[dict]:
    """The record of every story, from the facts."""
    arrival, order = arrivals_
    ct = {c["sha"]: c["ct"] for c in log}
    tags, deploys = tag_containment(graph, refs), deploy_heads(graph, refs)
    commits, all_reverted = story_commits(log, arrival, order)
    records = {s["id"]: new_story(s) for s in stories}
    for sid, rec in records.items():
        if sid in commits:
            on_trunk_facts(rec, commits[sid], arrival, ct, tags, deploys)
        rec["reverted"] = sid in all_reverted
        rec["branches"] = sorted(branches[sid]["branches"]) if sid in branches else []
    settle_dependencies(stories, records)
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
    cfg = read_config(state)
    trunk = trunk_name(state)
    shallow = git_read(["rev-parse", "--is-shallow-repository"]).decode().strip() == "true"
    check_trunk(trunk)
    refs = read_refs(trunk)
    trunk_sha = resolve_trunk(trunk, refs)
    stories = read_stories(trunk_sha, cfg)
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
        return facts
    log = read_trunk_log(trunk_sha)
    placed = arrivals(graph, trunk_sha)
    facts["stories"] = compute_states(stories, log, graph, refs, placed, read_branches(trunk_sha, refs, graph, set(placed[0])),
                                      cfg["stale_days"], time.time())
    facts["unattributed"] = unattributed(cfg, log, graph, placed[0])
    return facts


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
    for label, items in (("progress", progress), ("ready", ready), ("reverted", reverted), ("unknown", unknown)):
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
