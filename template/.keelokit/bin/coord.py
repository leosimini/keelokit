#!/usr/bin/env python3
"""Who is on watch, and which convoys are sailing. Stdlib only (Python 3.11+).

    coord.py status [--json]                     the logbook in a few lines
    coord.py claim --id S [--ttl MIN]            take the watch if nobody holds it (or it expired)
    coord.py heartbeat --id S                    the captain's check-in; extends the watch
    coord.py handoff --id S --note FILE|-        pass the watch on, with a short note
    coord.py tick --id S [--observe-only]        for the scheduled check: ok, or take the watch; with
                                                 --observe-only it only records that the watch lapsed
    coord.py note TEXT [--id S]                  a line in the logbook's questions (for the owner)
    coord.py session add|done|list ...           the sessions the captain is running
    coord.py convoy new|add|piece|pending|docs|ready|seam|ship ...
    coord.py note-limit                          a session was stopped by a usage limit
    coord.py budget                              low / medium / high, and what to do about it

The state lives on its own branch, `coord/board`, in `LEASE.json`, `STATE.json`, `HANDOFF.md` and the
generated `BOARD.md` and `convoys/<n>.md`. A push to that branch does not touch main or run the CI.
Every change is "fetch, edit, small commit, plain push": a rejected push is refetched and retried, never
forced. The watch is taken by the first push that changes `LEASE.json`; a second claimant's push is
rejected and it reads who won. A convoy is a wave of stories that sails together: one `verify --all`,
one push to main (on JOUNA: a "tren"). Docs: docs/orchestrator.md in the Keelokit repo, and the
`/keelokit:orquestador` skill.
"""
import sys

if sys.version_info < (3, 11):
    print(f"Keelokit needs Python 3.11+ (found {sys.version.split()[0]}).")
    sys.exit(1)

import json  # noqa: E402
import math  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import tomllib  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
BRANCH = "coord/board"
DEFAULT_TTL = 180  # minutes without a check-in before another session may take the watch
CONVOY_STATES = ["armando", "esperando-piezas", "listo-para-el-ok", "verificando", "en-main"]
PENDING_REASONS = {"owner", "production-config", "machine"}  # the only reasons to leave something out of a convoy
DECISIONS_FOR_OWNER = "money, prices, fees, production, third-party accounts, legal data"


def now() -> datetime:
    override = os.environ.get("KEELOKIT_NOW")
    return datetime.fromisoformat(override.replace("Z", "+00:00")) if override else datetime.now(timezone.utc)


def iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def git(*args: str, cwd: Path | None = None, check: bool = False) -> subprocess.CompletedProcess:
    env = {**os.environ}
    for k in [k for k in env if k.startswith("GIT_") and k not in ("GIT_SSH_COMMAND", "GIT_ASKPASS")]:
        del env[k]  # a hook's GIT_DIR would point every command at the wrong repository
    res = subprocess.run(["git", *args], cwd=cwd or ROOT, capture_output=True, text=True, env=env)
    if check and res.returncode:
        sys.exit(f"coord: git {' '.join(args)} failed: {res.stderr.strip()[:300]}")
    return res


def common_dir() -> Path:
    out = git("rev-parse", "--git-common-dir", check=True).stdout.strip()
    return (ROOT / out).resolve()


def settings() -> dict:
    try:
        return tomllib.loads((ROOT / ".keelokit/state.toml").read_text(encoding="utf-8")).get("coord", {})
    except (OSError, ValueError):
        return {}


# ── the logbook branch, checked out in a worktree of its own ─────────────────────────────────────
def wt_path() -> Path:
    return common_dir() / "keelokit-coord"


def ensure_wt() -> Path:
    """The worktree, on the newest `coord/board` (or a new orphan one when the branch doesn't exist yet)."""
    if git("remote", "get-url", "origin").returncode:
        sys.exit("coord: this repository has no `origin`; the logbook branch is shared through it.")
    git("fetch", "--quiet", "origin", BRANCH)
    remote = git("rev-parse", "--verify", "--quiet", f"origin/{BRANCH}").stdout.strip()
    wt = wt_path()
    if not (wt / ".git").exists():
        git("worktree", "prune")
        git("worktree", "add", "--detach", str(wt), remote or "HEAD", check=True)
    if remote:
        git("checkout", "--quiet", "--detach", "-f", remote, cwd=wt, check=True)
        git("clean", "-fdq", cwd=wt)
    elif not (wt / "LEASE.json").exists():
        git("checkout", "--quiet", "--orphan", "keelokit-coord-new", cwd=wt, check=True)
        git("rm", "-rfq", "--ignore-unmatch", ".", cwd=wt)
        git("clean", "-fdq", cwd=wt)
    return wt


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def load(wt: Path) -> tuple[dict, dict]:
    lease = read_json(wt / "LEASE.json", {"holder": None, "epoch": 0})
    state = read_json(wt / "STATE.json", {})
    state.setdefault("convoys", {})
    state.setdefault("sessions", {})
    state.setdefault("limit_hits", [])
    return lease, state


def mutate(apply, message: str, retries: int = 5):
    """Fetch the newest logbook, apply `apply(lease, state)` (returns a result, or raises SystemExit to
    abort), render, commit, push without force. A rejected push refetches and tries again."""
    for _ in range(retries):
        wt = ensure_wt()
        lease, state = load(wt)
        result = apply(lease, state)
        write(wt, lease, state)
        git("add", "-A", cwd=wt)
        if git("diff", "--cached", "--quiet", cwd=wt).returncode == 0:
            return result
        ident = [] if git("config", "user.email", cwd=wt).stdout.strip() else ["-c", "user.name=keelokit-coord", "-c", "user.email=coord@keelokit.invalid"]
        git(*ident, "commit", "-q", "-m", message, cwd=wt, check=True)
        if git("push", "--quiet", "origin", f"HEAD:refs/heads/{BRANCH}", cwd=wt).returncode == 0:
            return result
    sys.exit("coord: could not push the logbook after several tries (the remote keeps moving, or refuses). Nothing was forced.")


def write(wt: Path, lease: dict, state: dict) -> None:
    (wt / "LEASE.json").write_text(json.dumps(lease, indent=2, sort_keys=True) + "\n")
    (wt / "STATE.json").write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    (wt / "BOARD.md").write_text(render_board(lease, state))
    (wt / "convoys").mkdir(exist_ok=True)
    for n, c in state["convoys"].items():
        (wt / "convoys" / f"{n}.md").write_text(render_convoy(n, c))


# ── rendering: generated, never edited by hand ───────────────────────────────────────────────────
def watch_text(lease: dict) -> str:
    if not lease.get("holder"):
        return "nobody on watch" + (f" (released by {lease['released_by']} at {lease.get('released_at')})" if lease.get("released_by") else "")
    return f"{lease['holder']} since {lease['since']} · last check {lease['heartbeat']} · watch expires {lease['expires']} (epoch {lease['epoch']})"


def render_board(lease: dict, state: dict) -> str:
    out = ["# Logbook", "", "Generated by `.keelokit/bin/coord.py`; do not edit by hand.", "", "## Watch", "", f"- {watch_text(lease)}", ""]
    out += ["## Convoys", "", "| Convoy | Conductor | Branch | State | Pieces ready |", "|---|---|---|---|---|"]
    for n, c in sorted(state["convoys"].items(), key=lambda kv: int(kv[0])):
        done = sum(1 for p in c["pieces"].values() if p.get("state") == "lista")
        out.append(f"| {n} | {c.get('conductor') or '—'} | `{c.get('branch', '')}` | {c.get('status')} | {done}/{len(c['pieces'])} |")
    out += ["", "## Sessions", "", "| Session | Task | Convoy | Branch | State |", "|---|---|---|---|---|"]
    for sid, s in sorted(state["sessions"].items()):
        out.append(f"| {sid} | {s.get('task', '')} | {s.get('convoy', '—')} | `{s.get('branch', '')}` | {s.get('state', 'active')} |")
    if state.get("questions"):
        out += ["", "## Questions", ""] + [f"- {q}" for q in state["questions"]]
    return "\n".join(out) + "\n"


def render_convoy(n: str, c: dict) -> str:
    out = [f"# Convoy {n}", "", f"- State: {c.get('status')} · conductor: {c.get('conductor') or '—'} · branch `{c.get('branch', '')}`",
           f"- Docs up to date: {'yes' if c.get('docs_ok') else 'no'}" + (f" · sailed with {c['shipped']}" if c.get("shipped") else ""), "",
           "| Piece | Branch | Hash | Tests | Review | Captures | State | Note |", "|---|---|---|---|---|---|---|---|"]
    for pid, p in sorted(c["pieces"].items()):
        out.append(f"| {pid} | `{p.get('branch', '')}` | {p.get('hash', '')[:9]} | {p.get('tests') or '—'} | {p.get('review') or '—'} | "
                   f"{p.get('captures') or ('—' if p.get('ui') else 'n/a')} | {p.get('state')} | {p.get('note', '')} |")
    out += ["", "## Left out, and why", ""]
    out += [f"- {x['text']} — {x['reason']}" for x in c.get("pending", [])] or ["- nothing"]
    return "\n".join(out) + "\n"


# ── the watch ────────────────────────────────────────────────────────────────────────────────────
def arg(args: list[str], name: str, default: str | None = None) -> str | None:
    return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else default


def need_id(args: list[str]) -> str:
    sid = arg(args, "--id")
    if not sid:
        sys.exit("coord: --id <your session id> is required")
    return sid


def alive(lease: dict) -> bool:
    return bool(lease.get("holder")) and parse(lease["expires"]) > now()


def ttl_minutes(args: list[str]) -> int:
    raw = arg(args, "--ttl") or settings().get("ttl_minutes") or DEFAULT_TTL
    return int(raw)


def cmd_claim(args: list[str]) -> int:
    sid, ttl = need_id(args), ttl_minutes(args)

    def apply(lease, state):
        if alive(lease) and lease["holder"] != sid:
            return ("held", dict(lease))
        t = now()
        lease.update(holder=sid, since=lease["since"] if lease.get("holder") == sid else iso(t), heartbeat=iso(t),
                     expires=iso(t + timedelta(minutes=ttl)), epoch=lease.get("epoch", 0) + (0 if lease.get("holder") == sid else 1))
        lease.pop("released_by", None)
        lease.pop("released_at", None)
        return ("claimed", dict(lease))

    kind, lease = mutate(apply, f"watch: {sid} takes the watch")
    # The push may have been the one that lost the race: read the truth after it.
    wt = ensure_wt()
    truth, _ = load(wt)
    if kind == "claimed" and truth.get("holder") == sid:
        print(f"claimed: {sid} is on watch (epoch {truth['epoch']}) until {truth['expires']}")
        return 0
    print(f"not claimed: {truth.get('holder')} holds the watch until {truth.get('expires')}")
    return 1


def cmd_heartbeat(args: list[str]) -> int:
    sid, ttl = need_id(args), ttl_minutes(args)

    def apply(lease, state):
        if lease.get("holder") != sid:
            return False
        t = now()
        lease.update(heartbeat=iso(t), expires=iso(t + timedelta(minutes=ttl)))
        return True

    if mutate(apply, f"watch: {sid} checks in"):
        print(f"check-in recorded; the watch runs until {iso(now() + timedelta(minutes=ttl))}")
        return 0
    print(f"you ({sid}) are not on watch; run `coord.py tick --id {sid}` to see who is")
    return 1


def cmd_handoff(args: list[str]) -> int:
    sid = need_id(args)
    src = arg(args, "--note", "-")
    text = (sys.stdin.read() if src == "-" else Path(src).read_text()).strip()
    if len(text.splitlines()) > 40:
        sys.exit("coord: the handoff note is longer than 40 lines. The next captain reads this and the logbook, nothing else: cut it to what they need.")

    def apply(lease, state):
        if lease.get("holder") != sid:
            return False
        lease.update(holder=None, released_by=sid, released_at=iso(now()))
        (wt_path() / "HANDOFF.md").write_text(f"# Handoff from {sid} at {iso(now())}\n\n{text}\n")
        return True

    if mutate(apply, f"watch: {sid} hands over"):
        print("watch released. The next captain gets the note with `coord.py tick`.")
        return 0
    print(f"you ({sid}) are not on watch; nothing released")
    return 1


def cmd_tick(args: list[str]) -> int:
    """For the scheduled check. Exit 0: the watch is held and fresh (nothing to do). Exit 10: this session
    took the watch and must act as captain. Exit 1: someone else took it first."""
    sid = need_id(args)
    wt = ensure_wt()
    lease, state = load(wt)
    if alive(lease) and lease["holder"] != sid:
        age = int((now() - parse(lease["heartbeat"])).total_seconds() // 60)
        print(f"WATCH-OK {lease['holder']} checked in {age} min ago; expires {lease['expires']}. Nothing to do.")
        return 0
    if alive(lease) and lease["holder"] == sid:
        cmd_heartbeat(args)
        print(f"WATCH-OK you hold the watch; check-in renewed.")
        return 0
    prev = lease.get("holder") or lease.get("released_by") or "nobody"
    if "--observe-only" in args:
        # A session that cannot start or message other sessions must not hold the watch: it would block
        # one that can for hours. It records the lapse (once per watch period) so the owner is told.
        def apply(lease, state):
            qs = state.setdefault("questions", [])
            recent = qs and qs[-1].startswith("WATCH-LAPSED") and (now() - parse(qs[-1].split(" at ")[1].split(" ")[0])) < timedelta(minutes=DEFAULT_TTL)
            if not recent:
                qs.append(f"WATCH-LAPSED at {iso(now())} (last holder {prev}): nobody is captain. Open a session with the skill /keelokit:orquestador and run `coord.py tick --id <its id>`.")
                state["questions"] = qs[-20:]
            return not recent
        new = mutate(apply, "watch: lapsed (observed)")
        print(f"WATCH-LAPSED the watch is free or expired (last holder {prev}). " + ("Recorded in the logbook." if new else "Already recorded."))
        print("Tell the owner: a captain session is needed (see skill /keelokit:orquestador).")
        return 11
    if cmd_claim(args) != 0:
        return 1
    wt = ensure_wt()
    print(f"TAKE-ROLE you are the captain now (the watch was {'expired for ' + prev if lease.get('holder') else 'free, last ' + prev}).")
    handoff = wt / "HANDOFF.md"
    if handoff.exists():
        print("--- HANDOFF.md ---")
        print(handoff.read_text())
    print("--- BOARD.md ---")
    print((wt / "BOARD.md").read_text() if (wt / "BOARD.md").exists() else "(empty logbook)")
    return 10


def cmd_status(args: list[str]) -> int:
    wt = ensure_wt()
    lease, state = load(wt)
    if "--json" in args:
        print(json.dumps({"lease": lease, "state": state, "alive": alive(lease)}, indent=2))
        return 0
    print(f"watch: {watch_text(lease)}" + ("" if alive(lease) or not lease.get("holder") else "  ← EXPIRED, anyone may take it"))
    open_convoys = {n: c for n, c in state["convoys"].items() if c.get("status") != "en-main"}
    print(f"convoys: {len(open_convoys)} open" + "".join(f" · {n}: {c['status']} ({sum(1 for p in c['pieces'].values() if p.get('state') == 'lista')}/{len(c['pieces'])})" for n, c in sorted(open_convoys.items())))
    active = [s for s, v in state["sessions"].items() if v.get("state", "active") == "active"]
    print(f"sessions: {len(active)} active" + (": " + ", ".join(active[:6]) if active else ""))
    return 0


# ── sessions, convoys ────────────────────────────────────────────────────────────────────────────
def cmd_session(args: list[str]) -> int:
    sub = args[0] if args else ""
    if sub == "list":
        _, state = load(ensure_wt())
        for sid, s in sorted(state["sessions"].items()):
            print(f"{sid}\t{s.get('state', 'active')}\tconvoy {s.get('convoy', '—')}\t{s.get('branch', '')}\t{s.get('task', '')}")
        return 0
    if sub not in ("add", "done") or len(args) < 2:
        sys.exit("usage: coord.py session add ID --task T [--convoy N] [--branch B] | done ID | list")
    sid = args[1]

    def apply(lease, state):
        if sub == "add":
            state["sessions"][sid] = {"task": arg(args, "--task", ""), "convoy": arg(args, "--convoy", "—"), "branch": arg(args, "--branch", ""), "state": "active", "since": iso(now())}
        elif sid in state["sessions"]:
            state["sessions"][sid]["state"] = "done"
        return True

    mutate(apply, f"session {sub}: {sid}")
    print(f"session {sid}: {sub}")
    return 0


def cmd_note(args: list[str]) -> int:
    if not args or args[0].startswith("--"):
        sys.exit("usage: coord.py note TEXT [--id S]")
    text, who = args[0], arg(args, "--id", "someone")

    def apply(lease, state):
        state.setdefault("questions", []).append(f"{iso(now())} {who}: {text}")
        state["questions"] = state["questions"][-20:]

    mutate(apply, "note")
    print("noted in the logbook (BOARD.md, Questions)")
    return 0


def cmd_note_limit(args: list[str]) -> int:
    def apply(lease, state):
        state["limit_hits"] = (state["limit_hits"] + [iso(now())])[-20:]

    mutate(apply, "usage limit hit")
    print("recorded; `coord.py budget` will say high for the next hours")
    return 0


def cmd_budget(args: list[str]) -> int:
    lease, state = load(ensure_wt())
    try:
        run = tomllib.loads((ROOT / ".keelokit/state.toml").read_text(encoding="utf-8")).get("run", {})
    except (OSError, ValueError):
        run = {}
    cap = int(settings().get("parallel") or run.get("parallel") or 3)
    active = [s for s, v in state["sessions"].items() if v.get("state", "active") == "active"]
    hits = [parse(h) for h in state["limit_hits"]]
    recent = [h for h in hits if now() - h < timedelta(hours=3)]
    day = [h for h in hits if now() - h < timedelta(hours=24)]
    verify_running = False
    try:
        verify_running = "state=running" in (common_dir() / "keelokit-verify.state").read_text()
    except OSError:
        pass
    if recent or len(active) > cap:
        level, why = "high", ("a usage limit stopped sessions in the last 3 hours" if recent else f"{len(active)} sessions are active and the cap is {cap}")
        todo = "start nothing new; pause the biggest convoy (the one with the most pieces not ready); resume paused sessions when the limit resets"
    elif day or len(active) >= max(1, math.ceil(cap / 2)) or verify_running:
        level, why = "medium", ("a limit was hit in the last day" if day else "half the cap is in use" if len(active) >= max(1, math.ceil(cap / 2)) else "a verify is running")
        todo = "start new sessions one at a time and only if a convoy needs them"
    else:
        level, why, todo = "low", f"{len(active)} active session(s), cap {cap}, no limit hits lately", "room for more sessions, up to the cap"
    biggest = max(((n, sum(1 for p in c["pieces"].values() if p.get("state") != "lista")) for n, c in state["convoys"].items() if c.get("status") != "en-main"), key=lambda x: x[1], default=None)
    print(f"budget: {level} — {why}. {todo}." + (f" Biggest open convoy: {biggest[0]} ({biggest[1]} pieces not ready)." if biggest and level == "high" else ""))
    return 0


def cmd_convoy(args: list[str]) -> int:
    sub = args[0] if args else ""
    if sub not in ("new", "add", "piece", "pending", "docs", "ready", "seam", "ship") or len(args) < 2:
        sys.exit("usage: coord.py convoy new N [--conductor S] | add N PIECE --branch B --hash H [--ui] | piece N PIECE --tests ok --review ok --captures ok|n/a --state lista --note T | pending N TEXT --reason owner|production-config|machine | docs N ok | ready N [--offline] | seam N | ship N --hash H")
    n = args[1]
    rest = args[2:]
    if sub == "ready":
        return convoy_ready(n, "--offline" in rest)
    if sub == "seam":
        return convoy_seam(n)

    def apply(lease, state):
        c = state["convoys"].get(n)
        if sub == "new":
            if c:
                sys.exit(f"coord: convoy {n} already exists")
            state["convoys"][n] = {"conductor": arg(rest, "--conductor"), "branch": f"convoy/{n}", "status": "armando", "pieces": {}, "pending": [], "docs_ok": False}
            return
        if not c:
            sys.exit(f"coord: no convoy {n}")
        if sub == "add":
            pid = rest[0]
            if not arg(rest, "--branch") or not arg(rest, "--hash"):
                sys.exit("coord: a piece enters a convoy with its branch AND its hash")
            c["pieces"][pid] = {"branch": arg(rest, "--branch"), "hash": arg(rest, "--hash"), "tests": "", "review": "", "captures": "" if "--ui" in rest else "n/a", "ui": "--ui" in rest, "state": "en-curso", "note": ""}
            c["status"] = "esperando-piezas"
        elif sub == "piece":
            p = c["pieces"].get(rest[0]) or sys.exit(f"coord: convoy {n} has no piece {rest[0]}")
            for key in ("tests", "review", "captures", "state", "note", "hash", "branch"):
                if (v := arg(rest, f"--{key}")) is not None:
                    p[key] = v
            if all(q.get("state") == "lista" for q in c["pieces"].values()):
                c["status"] = "listo-para-el-ok"
        elif sub == "pending":
            reason = arg(rest, "--reason", "")
            if reason not in PENDING_REASONS:
                sys.exit(f"coord: leave something out of a convoy only for one of: {', '.join(sorted(PENDING_REASONS))}. Anything else that can still be finished is finished first.")
            c["pending"].append({"text": rest[0], "reason": reason})
        elif sub == "docs":
            c["docs_ok"] = rest[0] == "ok"
        elif sub == "ship":
            if not arg(rest, "--hash"):
                sys.exit("coord: record the hash that reached main (a convoy is not done without it)")
            c["status"], c["shipped"] = "en-main", arg(rest, "--hash")
        return

    mutate(apply, f"convoy {n}: {sub}")
    print(f"convoy {n}: {sub} ok")
    return 0


def convoy_ready(n: str, offline: bool) -> int:
    _, state = load(ensure_wt())
    c = state["convoys"].get(n) or sys.exit(f"coord: no convoy {n}")
    missing = []
    if not c["pieces"]:
        missing.append("the convoy has no pieces")
    for pid, p in sorted(c["pieces"].items()):
        if not p.get("hash") or not p.get("branch"):
            missing.append(f"{pid}: no branch and hash")
        for key in ("tests", "review"):
            if p.get(key) != "ok":
                missing.append(f"{pid}: {key} is not ok")
        if p.get("ui") and p.get("captures") != "ok":
            missing.append(f"{pid}: a screen without captures")
        if p.get("state") != "lista":
            missing.append(f"{pid}: state is '{p.get('state')}', not 'lista'")
    for x in c.get("pending", []):
        if x["reason"] not in PENDING_REASONS:
            missing.append(f"pending '{x['text']}' has no valid reason")
    if not c.get("docs_ok"):
        missing.append("docs (manual, environments) not confirmed up to date: coord.py convoy docs N ok")
    if not offline:
        ci = subprocess.run([sys.executable, str(ROOT / ".keelokit/bin/ci.py"), "health"], cwd=ROOT, capture_output=True, text=True)
        if ci.returncode != 0:
            missing.append("main is not green: " + (ci.stdout.strip().splitlines() or ci.stderr.strip().splitlines() or ["CI health unknown"])[0])
    if missing:
        print(f"convoy {n} is NOT ready to sail:")
        print("\n".join(f"  - {m}" for m in missing))
        return 1
    print(f"convoy {n} is ready: every piece has tests, review and (if it has a screen) captures; nothing left out that can be finished; docs confirmed; main green. The captain may give the ok for `verify --all` and one push.")
    return 0


def convoy_seam(n: str) -> int:
    """Files changed by more than one piece: where two branches green alone can be red together."""
    _, state = load(ensure_wt())
    c = state["convoys"].get(n) or sys.exit(f"coord: no convoy {n}")
    base = "origin/main" if git("rev-parse", "--verify", "--quiet", "origin/main").returncode == 0 else "main"
    touched: dict[str, list[str]] = {}
    for pid, p in sorted(c["pieces"].items()):
        res = git("diff", "--name-only", f"{base}...{p.get('hash')}")
        if res.returncode:
            print(f"warn: cannot read {pid} at {p.get('hash')} (not fetched?)", file=sys.stderr)
            continue
        for f in res.stdout.split():
            touched.setdefault(f, []).append(pid)
    shared = {f: ps for f, ps in touched.items() if len(ps) > 1}
    if not shared:
        print("no file is changed by two pieces. Still read the merged result: payloads, links, constants and key tables can break without sharing a file.")
        return 0
    print("Seams: files changed by more than one piece. After merging, run the tests of BOTH sides and read these first:")
    for f, ps in sorted(shared.items()):
        print(f"  {f}  ← {', '.join(ps)}")
    return 0


COMMANDS = {"claim": cmd_claim, "heartbeat": cmd_heartbeat, "handoff": cmd_handoff, "tick": cmd_tick, "status": cmd_status,
            "session": cmd_session, "convoy": cmd_convoy, "note-limit": cmd_note_limit, "budget": cmd_budget, "note": cmd_note}


def main() -> int:
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if a[0] not in COMMANDS:
        print(f"coord.py: unknown command {a[0]}\n{__doc__}", file=sys.stderr)
        return 2
    return COMMANDS[a[0]](a[1:])


if __name__ == "__main__":
    sys.exit(main())
