"""LEDGER-013: the ledger reads Harbor's logbook (origin/harbor/log) and works with Harbor's harbor.py.

- delivered, in-progress from a worker, the convoy and exact time of an on-trunk story (S1, S2, S4);
- `take` delegating to `harbor.py story take` / `story release` (S3, S7), against a stub harbor.py that reads the
  logbook as Harbor does and logs every call;
- `ledger.py attribution <a>..<b> [--json]`, Harbor's contract, checked against `check`'s own attribution (S5);
- `ledger.py show <ID> --json` (S6);
- hostile logbook content and harbor.py output: no crash, no verdict changed, no harbor.py from a hook's path (S8);
- `check --json`'s schema, which Harbor's HRB-3 reads (S9).
Run: python3 -m unittest discover -s tests (real git, local remotes, never the network)."""
import json
import os
import subprocess
import textwrap
import unittest
from pathlib import Path

from test_ledger import (CORR, CRITICAL, CRITICAL_TOML, REVIEWS, GitRepo, LedgerCase, approval, build_delegated, by_id, clean_env,
                         commit_harness, corrections, delegated_row, read_json, review_row, review_text, story15)

REPO = Path(__file__).resolve().parents[1]

# A stand-in for Harbor's lib/harbor.py: `story take|release ID`, `--session`, `story take --help`. Its lock reads the
# logbook as Harbor does (an active worker other than this session holding the story: STORY_TAKEN naming it). Every
# call is logged as one JSON line: argv, cwd, CLAUDE_PROJECT_DIR. STUB_MODE changes what it does.
STUB = r'''
import json, os, subprocess, sys, time, tomllib
log = os.environ.get("STUB_LOG")
if log:
    with open(log, "a") as f:
        f.write(json.dumps({"argv": sys.argv[1:], "cwd": os.getcwd(),
                            "project": os.environ.get("CLAUDE_PROJECT_DIR")}) + "\n")
mode = os.environ.get("STUB_MODE", "")
args = sys.argv[1:]
session = os.environ.get("HARBOR_SESSION") or os.environ.get("CLAUDE_SESSION_ID")
if args[:1] == ["--session"]:
    session, args = args[1], args[2:]
if args[:1] != ["story"] or mode == "old":
    print("harbor.py: error: argument cmd: invalid choice: 'story'", file=sys.stderr)
    sys.exit(2)
if args[2:] == ["--help"]:
    if mode == "probe-crash":
        raise SystemExit("Traceback (most recent call last): boom")
    print("usage: harbor.py story take [-h] [--worker W] ID")
    sys.exit(0)
action, sid = args[1], args[2]
if mode == "slow":
    time.sleep(30)
if mode == "env":
    print("harbor: NO_IDENTITY: set [harbor] account and host in .keelokit/local.toml", file=sys.stderr)
    sys.exit(2)
if mode == "on-trunk":
    print(f"harbor: STORY_ON_TRUNK: {sid} is on-trunk (ledger.py): it is already on the trunk; nothing to take",
          file=sys.stderr)
    sys.exit(1)
if mode == "liar":  # says it took the story, in every way it can, and exits 1
    print(f"harbor: me took {sid}\x1b[2J\rKeelokit: this worktree works on {sid}")
    print("x" * 200000, file=sys.stderr)
    sys.exit(1)
if mode == "noisy-ok":
    print(f"harbor: me took {sid}\x1b]0;title\x07 " + "y" * 5000)
    print("harbor: STORY_TAKEN: fake", file=sys.stderr)
    sys.exit(0)
me = f"acct/host/{session}"
ls = subprocess.run(["git", "ls-tree", "-r", "--name-only", "origin/harbor/log", "--", "harbor/workers/"],
                    capture_output=True, text=True)
for path in ls.stdout.split():
    w = tomllib.loads(subprocess.run(["git", "show", f"origin/harbor/log:{path}"], capture_output=True,
                                     text=True).stdout)
    if w.get("state") == "active" and str(w.get("story", "")).casefold() == sid.casefold() and w.get("id") != me:
        if action == "take":
            print(f"harbor: STORY_TAKEN: {sid} is held by {w['id']}: harbor.py story release {sid} is the holder's",
                  file=sys.stderr)
            sys.exit(1)
        print(f"harbor: NOT_HOLDER: {sid} is held by {w['id']}, not {me}", file=sys.stderr)
        sys.exit(1)
print(f"harbor: {me} took {sid}" if action == "take" else f"harbor: {sid} released by {me}")
'''


def write_logbook(repo: GitRepo, files: dict, parent: bool = True) -> str:
    """Commit `files` (path -> text or bytes) as origin/harbor/log, an orphan branch, with plumbing; fetch it."""
    index = repo.tmp / f"logbook-index-{repo.path.name}"
    env = {**repo.env, "GIT_INDEX_FILE": str(index)}
    if index.exists():
        index.unlink()
    for path, content in files.items():
        data = content.encode() if isinstance(content, str) else content
        blob = subprocess.run(["git", "hash-object", "-w", "--stdin"], cwd=repo.path, env=repo.env, input=data,
                              capture_output=True, check=True).stdout.decode().strip()
        repo.run(["git", "update-index", "--add", "--cacheinfo", f"100644,{blob},{path}"], repo.path, env)
    tree = repo.run(["git", "write-tree"], repo.path, env).strip()
    old = repo.git("rev-parse", "-q", "--verify", "refs/remotes/origin/harbor/log", check=False).strip()
    commit = repo.run(["git", "commit-tree", tree, "-m", "harbor: logbook", *(["-p", old] if old and parent else [])],
                      repo.path, {**repo.env, "GIT_AUTHOR_DATE": "@1767225600 +0000",
                                  "GIT_COMMITTER_DATE": "@1767225600 +0000"}).strip()
    repo.git("push", "-q", "-f", "origin", f"{commit}:refs/heads/harbor/log")
    repo.git("fetch", "-q", "--prune", "origin")
    return commit


def convoy_toml(number: int, state: str, vessels: list[tuple[str, str, str]] = (), sail: tuple | None = None,
                events: list[tuple[str, str, str, str]] = ()) -> str:
    out = f'schema = 1\nnumber = {number}\ntitle = "wave"\nstate = "{state}"\nbranch = "convoy/{number}"\n'
    if sail:
        out += f'\n[sail]\nby = "acct/host/s0"\nat = "2026-11-20T10:00:00Z"\nmain_before = "{sail[0]}"\nmain_after = "{sail[1]}"\n'
    for branch, head, story in vessels:
        out += f'\n[[vessels]]\nbranch = "{branch}"\nhead = "{head}"\nstory = "{story}"\ntier = "light"\n'
    for at, by, what, detail in events:
        out += f'\n[[events]]\nat = "{at}"\nby = "{by}"\nwhat = "{what}"\ndetail = "{detail}"\n'
    return out


def worker_toml(wid: str, state: str, story: str | None = None) -> str:
    return f'schema = 1\nid = "{wid}"\nrole = "vessel"\nstate = "{state}"\n' + (f'story = "{story}"\n' if story else "")


def run_toml(head: str, exit_code: int = 0) -> str:
    return f'schema = 1\nkind = "vessel"\nhead = "{head}"\nexit = {exit_code}\n'


def json_of(test: unittest.TestCase, r: subprocess.CompletedProcess) -> dict:
    test.assertNotIn("Traceback", r.stderr)
    try:
        return json.loads(r.stdout)
    except ValueError:
        test.fail(f"not JSON (exit {r.returncode}):\n{r.stdout[:2000]}\n{r.stderr[:2000]}")


def without_harbor_keys(data: dict) -> dict:
    """--json minus what LEDGER-013 added (the `harbor` key, each story's `delivered` and `workers`)."""
    out = {k: v for k, v in data.items() if k != "harbor"}
    out["stories"] = [{k: v for k, v in s.items() if k not in ("delivered", "workers")} for s in data["stories"]]
    return out


class HarborProject(LedgerCase):
    """AUTH-001 built on claude/auth-001 and sailed in convoy 8 (the trailer on its merge, the sail in the logbook,
    the move in main.toml); AUTH-002 delivered by claude/auth-002 into convoy 9, assembling; AUTH-003 held by an
    active worker; AUTH-004 nobody's; AUTH-005 delivered by a vessel whose branch moved on, AUTH-006 by a red seal."""

    def project(self, logbook: bool = True) -> GitRepo:
        repo = GitRepo(self.tmp)
        repo.plan("AUTH-001", "AUTH-002", "AUTH-003", "AUTH-004", "AUTH-005", "AUTH-006")
        repo.publish()
        self.before = repo.sha()
        repo.on_branch("claude/auth-001", "feat: AUTH-001\n\nWhat was decided.\n\nStory: AUTH-001", keep=True)
        self.s1 = repo.sha("claude/auth-001")
        repo.git("checkout", "-q", "-b", "convoy/8")
        self.merge8 = repo.merge("claude/auth-001", f"convoy 8: merge claude/auth-001@{self.s1[:12]}\n\nConvoy: 8")
        repo.git("checkout", "-q", "main")
        repo.git("merge", "-q", "--ff-only", "convoy/8")
        self.after = repo.sha()
        repo.publish("main", "convoy/8")
        self.v2 = repo.on_branch("claude/auth-002", "feat: half of AUTH-002\n\nPart-of: AUTH-002", keep=True)[0]
        self.v5 = repo.on_branch("claude/auth-005", "feat: AUTH-005\n\nPart-of: AUTH-005", keep=True)[0]
        self.v6 = repo.on_branch("claude/auth-006", "feat: AUTH-006\n\nPart-of: AUTH-006", keep=True)[0]
        repo.git("checkout", "-q", "claude/auth-005")
        repo.commit("feat: more of AUTH-005, after the delivery\n\nPart-of: AUTH-005")
        repo.git("push", "-q", "origin", "claude/auth-005")
        repo.git("checkout", "-q", "main")
        repo.git("fetch", "-q", "origin")
        if logbook:
            write_logbook(repo, self.logbook_files())
        return repo

    def logbook_files(self) -> dict:
        return {
            "harbor/convoys/8.toml": convoy_toml(8, "sailed", [("claude/auth-001", self.s1, "AUTH-001")],
                                                 sail=(self.before, self.after),
                                                 events=[("2026-11-20T09:00:00Z", "acct/host/s0", "add",
                                                          f"claude/auth-001@{self.s1[:12]}"),
                                                         ("2026-11-20T10:00:00Z", "acct/host/s0", "sailed",
                                                          f"main {self.after[:12]}")]),
            "harbor/convoys/9.toml": convoy_toml(9, "assembling", [("claude/auth-002", self.v2, "auth-002"),
                                                                   ("claude/auth-005", self.v5, "AUTH-005"),
                                                                   ("claude/auth-006", self.v6, "AUTH-006")]),
            f"harbor/runs/{self.v2}.toml": run_toml(self.v2),
            f"harbor/runs/{self.v5}.toml": run_toml(self.v5),
            f"harbor/runs/{self.v6}.toml": run_toml(self.v6, 1),
            "harbor/workers/acct/host/s1.toml": worker_toml("acct/host/s1", "active", "AUTH-003"),
            "harbor/workers/acct/host/s2.toml": worker_toml("acct/host/s2", "ended", "AUTH-004"),
            "harbor/main.toml": (f'schema = 1\nhead = "{self.after}"\n\n[[moves]]\nfrom = "{self.before}"\n'
                                 f'to = "{self.after}"\nseen = "2026-11-20T10:00:07Z"\ncause = "convoy 8"\n'),
        }


class LedgerHarborStatesTest(HarborProject):
    def test_LEDGER_013_S1_a_sealed_vessel_in_an_open_convoy_is_delivered_with_its_convoy(self):
        repo = self.project()
        data = read_json(self, repo)
        s = by_id(data)["AUTH-002"]
        self.assertEqual(s["state"], "delivered")
        self.assertEqual(s["convoy"], 9)
        self.assertEqual(s["delivered"], {"convoy": 9, "convoy_state": "assembling", "branch": "claude/auth-002",
                                          "head": self.v2})
        self.assertEqual(data["harbor"]["logbook"], repo.sha("refs/remotes/origin/harbor/log"))
        summary = repo.ledger()
        self.assertIn("AUTH-002 (convoy 9)", summary.stdout)

    def test_LEDGER_013_S1_a_commit_after_the_delivery_or_a_red_seal_is_no_delivery(self):
        stories = self.stories(self.project())
        self.assertEqual(stories["AUTH-005"]["state"], "in-progress", "its branch moved past the delivered head")
        self.assertIsNone(stories["AUTH-005"]["delivered"])
        self.assertEqual(stories["AUTH-006"]["state"], "in-progress", "its seal is red")
        self.assertIsNone(stories["AUTH-006"]["convoy"])

    def test_LEDGER_013_S1_an_aborted_convoy_delivers_nothing(self):
        repo = self.project()
        files = self.logbook_files()
        files["harbor/convoys/9.toml"] = files["harbor/convoys/9.toml"].replace('state = "assembling"', 'state = "aborted"')
        write_logbook(repo, files)
        self.assertEqual(self.stories(repo)["AUTH-002"]["state"], "in-progress")

    def test_LEDGER_013_S2_a_sailed_convoy_names_the_convoy_and_the_exact_time(self):
        s = self.stories(self.project())["AUTH-001"]
        self.assertEqual(s["state"], "on-trunk")
        self.assertEqual(s["commit"], self.s1)
        self.assertEqual(s["convoy"], 8)
        self.assertEqual(s["since"], "2026-11-20T10:00:07Z")
        self.assertIs(s["since_exact"], True)

    def test_LEDGER_013_S2_the_trailer_names_the_convoy_without_a_logbook(self):
        s = self.stories(self.project(logbook=False))["AUTH-001"]
        self.assertEqual(s["convoy"], 8, "the Convoy: trailer of the merge that brought it")
        self.assertIs(s["since_exact"], False, "no move of the trunk to date it")

    def test_LEDGER_013_S2_the_sail_names_the_convoy_when_the_merge_has_no_trailer(self):
        repo = GitRepo(self.tmp)
        repo.plan("AUTH-001")
        repo.publish()
        before = repo.sha()
        repo.on_branch("claude/auth-001", "feat: AUTH-001\n\nWhy.\n\nStory: AUTH-001", keep=True)
        repo.merge("claude/auth-001", "Merge claude/auth-001\n\nNo-story: release")
        after = repo.sha()
        repo.publish()
        write_logbook(repo, {"harbor/convoys/12.toml": convoy_toml(12, "sailed", sail=(before, after))})
        s = self.stories(repo)["AUTH-001"]
        self.assertEqual(s["convoy"], 12)
        self.assertIs(s["since_exact"], False, "a sail without its move in main.toml gives no exact time")

    def test_LEDGER_013_S2_a_loose_move_gives_no_exact_time(self):
        repo = self.project()
        files = self.logbook_files()
        files["harbor/main.toml"] = files["harbor/main.toml"].replace('cause = "convoy 8"', 'cause = "loose"')
        write_logbook(repo, files)
        s = self.stories(repo)["AUTH-001"]
        self.assertIs(s["since_exact"], False)
        self.assertEqual(s["convoy"], 8)

    def test_LEDGER_013_S1_an_active_worker_holding_a_story_makes_it_in_progress(self):
        stories = self.stories(self.project())
        self.assertEqual(stories["AUTH-003"]["state"], "in-progress")
        self.assertEqual(stories["AUTH-003"]["workers"], ["acct/host/s1"])
        self.assertEqual(stories["AUTH-004"]["state"], "ready", "an ended worker holds nothing")
        self.assertEqual(stories["AUTH-004"]["workers"], [])

    def test_LEDGER_013_S4_without_a_logbook_every_state_is_as_before(self):
        repo = self.project(logbook=False)
        data = read_json(self, repo)
        states = {sid: s["state"] for sid, s in by_id(data).items()}
        self.assertEqual(states, {"AUTH-001": "on-trunk", "AUTH-002": "in-progress", "AUTH-003": "ready",
                                  "AUTH-004": "ready", "AUTH-005": "in-progress", "AUTH-006": "in-progress"})
        self.assertEqual(data["harbor"], {"logbook": None, "skipped": 0, "error": None})
        for s in data["stories"]:
            self.assertIsNone(s["delivered"])
            self.assertEqual(s["workers"], [])
            if s["id"] != "AUTH-001":
                self.assertIsNone(s["convoy"])

    def test_LEDGER_013_S4_the_logbook_never_changes_what_check_says(self):
        repo = self.project(logbook=False)
        repo.state('[ledger]\nsince = "%s"\nenforce = "block"\n' % self.before)
        plain = repo.ledger("check", "--json")
        write_logbook(repo, self.logbook_files())
        with_book = repo.ledger("check", "--json")
        self.assertEqual((plain.returncode, plain.stdout), (with_book.returncode, with_book.stdout))

    def test_LEDGER_013_S1_show_names_the_delivery_the_workers_and_the_convoy_events(self):
        repo = self.project()
        card = repo.ledger("show", "AUTH-002").stdout
        self.assertIn(f"delivered: convoy 9 (assembling), claude/auth-002@{self.v2[:12]}", card)
        self.assertIn("workers (Harbor): acct/host/s1", repo.ledger("show", "AUTH-003").stdout)
        one = repo.ledger("show", "AUTH-001").stdout
        self.assertIn("convoy: 8", one)
        self.assertIn("convoy 8 events:", one)
        self.assertIn(f"2026-11-20T10:00:00Z sailed main {self.after[:12]} (acct/host/s0)", one)


class LedgerShowJsonTest(HarborProject):
    def test_LEDGER_013_S6_show_json_is_the_record_and_its_why(self):
        repo = self.project()
        r = repo.ledger("show", "AUTH-001", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json_of(self, r)
        record = by_id(read_json(self, repo))["AUTH-001"]
        self.assertEqual(d["schema"], 1)
        self.assertEqual({k: d[k] for k in record}, record, "the record as --json gives it")
        self.assertEqual(d["history"], "complete")
        self.assertEqual((d["id"], d["state"], d["version"], d["convoy"], d["delivered"]),
                         ("AUTH-001", "on-trunk", None, 8, None))
        why = d["why"]
        self.assertLessEqual({"addenda", "commits", "corrections", "escapes", "findings", "convoy_events"}, set(why))
        self.assertEqual([c["sha"] for c in why["commits"]], [self.s1])
        self.assertEqual(why["commits"][0]["kind"], "Story")
        self.assertEqual(why["commits"][0]["body"], ["What was decided."])
        self.assertEqual([e["what"] for e in why["convoy_events"]], ["add", "sailed"])

    def test_LEDGER_013_S6_show_json_of_a_delivered_story_and_without_case(self):
        repo = self.project()
        d = json_of(self, repo.ledger("show", "auth-002", "--json"))
        self.assertEqual((d["id"], d["state"], d["convoy"]), ("AUTH-002", "delivered", 9))
        self.assertEqual(d["delivered"]["head"], self.v2)

    def test_LEDGER_013_S6_show_json_of_no_story_exits_1_with_an_error(self):
        repo = self.project(logbook=False)
        r = repo.ledger("show", "NOPE-001", "--json")
        self.assertEqual(r.returncode, 1)
        d = json_of(self, r)
        self.assertEqual((d["schema"], d["id"]), (1, "NOPE-001"))
        self.assertIn("NOPE-001", d["error"])
        self.assertNotIn("state", d, "Harbor reads no state from it")
        for bad in (["show", "AUTH-001", "--json", "--full"], ["show", "--json"], ["show", "AUTH-001", "--jsonx"]):
            with self.subTest(bad=bad):
                self.assertEqual(repo.ledger(*bad).returncode, 2)


class HarborStubCase(HarborProject):
    def harbor(self, repo: GitRepo) -> Path:
        tool = self.tmp / "plugin" / "lib" / "harbor.py"
        tool.parent.mkdir(parents=True, exist_ok=True)
        tool.write_text(STUB)
        repo.git("config", "--local", "harbor.py", str(tool))
        self.log = self.tmp / "harbor-calls.jsonl"
        return tool

    def calls(self) -> list[dict]:
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def take(self, repo: GitRepo, *args: str, mode: str = "", **env) -> subprocess.CompletedProcess:
        extra = {"STUB_LOG": str(self.log), "STUB_MODE": mode, "HARBOR_SESSION": "s9", **env}
        return repo.ledger("take", *args, extra_env=extra, timeout=120)

    def story_of(self, repo: GitRepo) -> str | None:
        r = subprocess.run(["git", "config", "--get", "keelokit.story"], cwd=repo.path, env=clean_env(self.tmp),
                           capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else None


class LedgerHarborTakeTest(HarborStubCase):
    def test_LEDGER_013_S3_take_relays_story_taken_naming_the_worker_and_sets_nothing(self):
        repo = self.project()
        self.harbor(repo)
        r = self.take(repo, "AUTH-003")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        out = r.stdout + r.stderr
        self.assertIn("STORY_TAKEN", out)
        self.assertIn("acct/host/s1", out)
        self.assertEqual(len([line for line in r.stdout.splitlines() if "STORY_TAKEN" in line]), 1, "one line")
        self.assertIsNone(self.story_of(repo))
        self.assertIn(["story", "take", "AUTH-003"], [c["argv"] for c in self.calls()])

    def test_LEDGER_013_S7_take_with_harbor_takes_the_lock_then_sets_the_story(self):
        repo = self.project()
        self.harbor(repo)
        r = self.take(repo, "AUTH-004")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("harbor: acct/host/s9 took AUTH-004", r.stdout)
        self.assertEqual(self.story_of(repo), "AUTH-004")
        argvs = [c["argv"] for c in self.calls()]
        self.assertEqual(argvs, [["story", "take", "--help"], ["story", "take", "AUTH-004"]])
        for c in self.calls():
            self.assertEqual(Path(c["project"]).resolve(), repo.path.resolve(), "CLAUDE_PROJECT_DIR is this checkout")
            self.assertEqual(Path(c["cwd"]).resolve(), repo.path.resolve())

    def test_LEDGER_013_S7_take_relays_story_on_trunk_and_an_environment_failure(self):
        repo = self.project()
        self.harbor(repo)
        r = self.take(repo, "AUTH-004", mode="on-trunk")
        self.assertEqual(r.returncode, 1)
        self.assertIn("STORY_ON_TRUNK", r.stdout)
        self.assertIsNone(self.story_of(repo))
        r = self.take(repo, "AUTH-004", mode="env")
        self.assertEqual(r.returncode, 2, "Harbor could not answer: not taken, and no refusal either")
        self.assertIn("NO_IDENTITY", r.stdout)
        self.assertIsNone(self.story_of(repo))

    def test_LEDGER_013_S7_a_harbor_that_does_not_answer_takes_nothing(self):
        repo = self.project()
        self.harbor(repo)
        r = self.take(repo, "AUTH-004", mode="slow", KEELOKIT_HARBOR_SECONDS="1")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("did not answer", r.stdout)
        self.assertIsNone(self.story_of(repo))

    def test_LEDGER_013_S7_a_harbor_that_cannot_be_asked_takes_nothing(self):
        repo = self.project()
        self.harbor(repo)
        r = self.take(repo, "AUTH-004", mode="probe-crash")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("could not be asked", r.stdout)
        self.assertIsNone(self.story_of(repo))

    def test_LEDGER_013_S7_a_harbor_without_story_take_changes_nothing(self):
        repo = self.project()
        self.harbor(repo)
        r = self.take(repo, "AUTH-004", mode="old")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.story_of(repo), "AUTH-004")
        self.assertEqual([c["argv"] for c in self.calls()], [["story", "take", "--help"]])

    def test_LEDGER_013_S7_without_harbor_nothing_runs(self):
        repo = self.project()
        self.log = self.tmp / "harbor-calls.jsonl"
        self.assertEqual(self.take(repo, "AUTH-004").returncode, 0)
        self.assertEqual(self.story_of(repo), "AUTH-004")
        for bad in ("relative/harbor.py", str(self.tmp / "missing" / "harbor.py")):
            repo.git("config", "--local", "harbor.py", bad)
            self.assertEqual(self.take(repo, "AUTH-005").returncode, 0)
        other = self.tmp / "plugin" / "lib" / "other.py"
        other.parent.mkdir(parents=True)
        other.write_text(STUB)
        repo.git("config", "--local", "harbor.py", str(other))
        self.assertEqual(self.take(repo, "AUTH-004").returncode, 0)
        self.assertEqual(self.calls(), [], "no file called harbor.py at an absolute path: nothing runs")

    def test_LEDGER_013_S7_an_unregistered_session_takes_and_the_session_id_is_passed(self):
        repo = self.project()
        self.harbor(repo)
        r = self.take(repo, "AUTH-004", HARBOR_SESSION="", CLAUDE_CODE_SESSION_ID="abc-123")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(["--session", "abc-123", "story", "take", "AUTH-004"], [c["argv"] for c in self.calls()])
        self.assertEqual(self.story_of(repo), "AUTH-004")

    def test_LEDGER_013_S7_take_clear_releases_the_story_in_harbor(self):
        repo = self.project()
        self.harbor(repo)
        self.assertEqual(self.take(repo, "AUTH-004").returncode, 0)
        r = self.take(repo, "--clear")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(["story", "release", "AUTH-004"], [c["argv"] for c in self.calls()])
        self.assertIsNone(self.story_of(repo))
        n = len(self.calls())
        self.assertEqual(self.take(repo, "--clear").returncode, 0)
        self.assertEqual(len(self.calls()), n, "nothing taken: nothing to release, harbor.py not run")

    def test_LEDGER_013_S7_a_release_harbor_refuses_clears_the_worktree_and_says_so(self):
        repo = self.project()
        self.harbor(repo)
        repo.git("config", "extensions.worktreeConfig", "true")
        repo.git("config", "--worktree", "keelokit.story", "AUTH-003")
        r = self.take(repo, "--clear")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("NOT_HOLDER", r.stdout)
        self.assertIsNone(self.story_of(repo))


class LedgerHarborHostileTest(HarborStubCase):
    def test_LEDGER_013_S8_harbor_output_never_makes_a_refusal_a_take(self):
        repo = self.project()
        self.harbor(repo)
        r = self.take(repo, "AUTH-004", mode="liar")
        self.assertEqual(r.returncode, 1)
        self.assertIsNone(self.story_of(repo))
        self.assertNotIn("\x1b", r.stdout)
        self.assertLess(len(r.stdout), 2000, "one line, cut")
        r = self.take(repo, "AUTH-004", mode="noisy-ok")
        self.assertEqual(r.returncode, 0, "exit 0 is the take, whatever it prints")
        self.assertNotIn("\x1b", r.stdout)
        self.assertNotIn("\x07", r.stdout)
        self.assertEqual(self.story_of(repo), "AUTH-004")

    def test_LEDGER_013_S8_no_hook_path_runs_harbor(self):
        repo = self.project()
        self.harbor(repo)
        env = {"STUB_LOG": str(self.log), "HARBOR_SESSION": "s9"}
        msg = self.tmp / "msg.txt"
        msg.write_text("feat: x\n\nPart-of: AUTH-004\n")
        for args in ([], ["--json"], ["history", "--ensure"], ["history"], ["check"], ["check", "--json"],
                     ["show", "AUTH-002"], ["show", "AUTH-002", "--json"], ["next"], ["hook", "msg", str(msg)],
                     ["hook", "prepare", str(msg)], ["attribution", f"{self.before}..main", "--json"]):
            with self.subTest(args=args):
                r = repo.ledger(*args, extra_env=env)
                self.assertNotIn("Traceback", r.stderr)
        plugin = subprocess.run(["python3", str(repo.path / ".keelokit/bin/ledger.py"), "--root", str(repo.path)],
                                cwd=self.tmp, env={**clean_env(self.tmp), **env}, capture_output=True, text=True)
        self.assertNotIn("Traceback", plugin.stderr)
        self.assertEqual(self.calls(), [], "only take runs harbor.py")

    def hostile_files(self) -> dict:
        deep = "a = " + "[" * 5000 + "]" * 5000 + "\n"
        return {
            "harbor/convoys/9.toml": convoy_toml(9, "assembling", [("claude/auth-002", self.v2, "AUTH-002")]),
            f"harbor/runs/{self.v2}.toml": run_toml(self.v2),
            "harbor/convoys/10.toml": deep,
            "harbor/convoys/11.toml": b"\xff\xfe not utf-8",
            "harbor/convoys/12.toml": 'number = 13\nstate = "assembling"\n',
            "harbor/convoys/13.toml": 'state = "assembling"\nvessels = "no"\nevents = [1, "x", {at = 3}]\nsail = 5\n',
            "harbor/convoys/14.toml": ('state = "assembling"\n[[vessels]]\nbranch = 7\nhead = "x"\n[[vessels]]\n'
                                       'branch = "b"\nhead = "' + "g" * 40 + '"\nstory = "AUTH-004"\n'),
            "harbor/convoys/15.toml": 'number = true\nstate = "sailed"\n[sail]\nmain_before = 1\nmain_after = "x"\n',
            "harbor/convoys/16.toml": "x" * (1 << 21),
            "harbor/convoys/0017.toml": convoy_toml(17, "assembling", [("claude/auth-004", self.v2, "AUTH-004")]),
            "harbor/convoys/18.toml": convoy_toml(18, "assembling", [("claude/auth-004", "0" * 40, "AUTH-004")]),
            f"harbor/runs/{'0' * 40}.toml": 'exit = true\nhead = "' + "0" * 40 + '"\n',
            "harbor/workers/a/b/c.toml": 'id = 5\nstate = "active"\nstory = "AUTH-004"\n',
            "harbor/workers/a/b/d.toml": 'id = "a/b/d"\nstate = ["active"]\nstory = "AUTH-004"\n',
            "harbor/workers/a/b/e.toml": 'id = "a/b/e"\nstate = "active"\nstory = 4\n',
            "harbor/workers/a/b/f.toml": 'id = "a/b/f"\nstate = "active"\nstory = "AUTH-999, ‮AUTH-004"\n',
            "harbor/workers/x.toml": 'id = "x"\nstate = "active"\nstory = "AUTH-004"\n',
            "harbor/main.toml": ('[[moves]]\nfrom = "nope"\nto = 3\nseen = "yesterday"\ncause = "convoy 8"\n'
                                 '[[moves]]\nseen = "2026-01-01T00:00:00Z"\ncause = "convoy 99999999999"\n'),
        }

    def test_LEDGER_013_S8_hostile_logbook_content_is_left_out_and_never_crashes(self):
        repo = self.project(logbook=False)
        plain = read_json(self, repo)
        write_logbook(repo, self.hostile_files())
        data = read_json(self, repo)
        self.assertIsNone(data["harbor"]["error"])
        self.assertGreater(data["harbor"]["skipped"], 5)
        stories = by_id(data)
        self.assertEqual(stories["AUTH-002"]["state"], "delivered", "the one well-formed convoy still counts")
        self.assertEqual(stories["AUTH-004"]["state"], "ready", "no malformed file raises a story")
        self.assertEqual(stories["AUTH-004"]["workers"], [])
        self.assertEqual(plain["diffs"], data["diffs"])
        for args in (["show", "AUTH-002"], ["show", "AUTH-002", "--json"], [], ["check", "--json"], ["next"]):
            with self.subTest(args=args):
                r = repo.ledger(*args)
                self.assertNotIn("Traceback", r.stderr)
                self.assertNotIn("the ledger failed", r.stderr)

    def test_LEDGER_013_S8_a_logbook_git_cannot_read_is_none(self):
        repo = self.project(logbook=False)
        plain = read_json(self, repo)
        commit = write_logbook(repo, self.logbook_files())
        tree = repo.git("rev-parse", f"{commit}^{{tree}}").strip()
        obj = repo.path / ".git/objects" / tree[:2] / tree[2:]
        obj.chmod(0o644)
        obj.unlink()
        data = read_json(self, repo)
        self.assertIsNotNone(data["harbor"]["error"])
        self.assertEqual(without_harbor_keys(plain)["stories"], without_harbor_keys(data)["stories"])

    def test_LEDGER_013_S8_a_logbook_story_on_the_trunk_is_never_lowered_nor_an_unknown_raised(self):
        """INV-005: on the trunk only by its Story: commit or a correction, never by the logbook."""
        repo = self.project()
        files = self.logbook_files()
        files["harbor/workers/acct/host/s3.toml"] = worker_toml("acct/host/s3", "active", "AUTH-001")
        files["harbor/convoys/9.toml"] = convoy_toml(9, "assembling", [("claude/auth-001", self.s1, "AUTH-001")])
        files[f"harbor/runs/{self.s1}.toml"] = run_toml(self.s1)
        write_logbook(repo, files)
        s = self.stories(repo)["AUTH-001"]
        self.assertEqual((s["state"], s["convoy"], s["delivered"]), ("on-trunk", 8, None))


class LedgerConvoyNumberTest(LedgerCase):
    def test_LEDGER_013_S8_breaker2_a_huge_convoy_number_in_a_merge_subject_crashes_nothing(self):
        """Cold breaker round 2, finding 1: `Merge branch 'convoy/<5000 digits>'` on the trunk."""
        repo = GitRepo(self.tmp)
        repo.plan("AUTH-001")
        repo.publish()
        repo.on_branch("feat", "feat: AUTH-001\n\nWhy.\n\nStory: AUTH-001", keep=True)
        repo.merge("feat", f"Merge branch 'convoy/{'9' * 5000}'\n\nNo-story: docs")
        repo.publish()
        s = self.stories(repo)["AUTH-001"]
        self.assertEqual((s["state"], s["convoy"]), ("on-trunk", None))
        for args in ([], ["check"], ["show", "AUTH-001"], ["show", "AUTH-001", "--json"], ["next"]):
            with self.subTest(args=args):
                r = repo.ledger(*args)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class LedgerAttributionTest(LedgerCase):
    """`attribution <a>..<b> [--json]`: Harbor's contract, and the same attribution `check` makes."""

    def project(self) -> GitRepo:
        repo = GitRepo(self.tmp)
        repo.plan("AUTH-001", "AUTH-002")
        repo.publish()
        self.base = repo.sha()
        repo.state('[ledger]\nsince = "%s"\nenforce = "block"\n' % self.base)
        repo.git("checkout", "-q", "-b", "claude/vessel")
        self.own = repo.commit("feat: part\n\nWhy.\n\nPart-of: AUTH-001")
        self.loose = repo.commit("chore: nothing said")
        self.docs = repo.commit("docs: notes\n\nNo-story: docs — the README")
        self.bad = repo.commit("docs: odd\n\nNo-story: whatever")
        repo.git("checkout", "-q", "-b", "inner")
        self.inner = repo.commit("feat: inner\n\nWhy.\n\nPart-of: AUTH-002")
        repo.git("checkout", "-q", "claude/vessel")
        self.clean_merge = repo.merge("inner", "Merge inner")
        repo.git("checkout", "-q", "-b", "inner2", self.base)
        self.inner_loose = repo.commit("chore: unsaid inside")
        repo.git("checkout", "-q", "claude/vessel")
        self.dirty_merge = repo.merge("inner2", "Merge inner2")
        repo.git("checkout", "-q", "-b", "inner3", self.base)
        self.carried = repo.commit("chore: carried by its merge")
        repo.git("checkout", "-q", "claude/vessel")
        self.trailer_merge = repo.merge("inner3", "Merge inner3\n\nPart-of: AUTH-002")
        repo.git("push", "-q", "origin", "claude/vessel")
        repo.git("fetch", "-q", "origin")
        return repo

    def attribution(self, repo: GitRepo, rng: str) -> tuple[subprocess.CompletedProcess, dict]:
        r = repo.ledger("attribution", rng, "--json")
        return r, json_of(self, r) if r.returncode == 0 else {}

    def test_LEDGER_013_S5_the_contract_shape_and_order(self):
        repo = self.project()
        r, d = self.attribution(repo, f"{self.base}..claude/vessel")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(d["schema"], 1)
        self.assertEqual(d["range"], f"{self.base}..claude/vessel")
        order = repo.git("rev-list", "--reverse", f"{self.base}..claude/vessel").split()
        self.assertEqual([c["sha"] for c in d["commits"]], order)
        for c in d["commits"]:
            self.assertEqual(set(c) >= {"sha", "subject", "story", "part_of", "no_story", "merge", "attributed", "via"},
                             True)
            self.assertRegex(c["sha"], r"^[0-9a-f]{40}$")
            self.assertIn(c["via"], ("own", "merge", "correction", None))
            self.assertEqual(c["via"] is None, not c["attributed"])
        by = {c["sha"]: c for c in d["commits"]}
        self.assertEqual((by[self.own]["part_of"], by[self.own]["via"]), (["AUTH-001"], "own"))
        self.assertEqual(by[self.own]["subject"], "feat: part")
        self.assertEqual((by[self.loose]["attributed"], by[self.loose]["via"]), (False, None))
        self.assertEqual((by[self.docs]["no_story"], by[self.docs]["via"]), ("docs — the README", "own"))
        self.assertEqual((by[self.clean_merge]["merge"], by[self.clean_merge]["attributed"], by[self.clean_merge]["via"]),
                         (True, True, "merge"), "a merge counts when everything it brings is attributed")
        self.assertEqual(by[self.dirty_merge]["attributed"], False, "a merge that brings an unattributed commit")
        self.assertEqual(by[self.inner_loose]["attributed"], False)
        self.assertEqual((by[self.trailer_merge]["via"], by[self.carried]["via"]), ("own", "merge"))
        self.assertEqual(sorted(d["unattributed"]), sorted([self.loose, self.inner_loose, self.dirty_merge]))
        self.assertIs(d["ok"], False)
        self.assertEqual(d["stories"], ["AUTH-001", "AUTH-002"])
        self.assertIn("BAD_CATEGORY", [x["code"] for x in d["diffs"]])

    def test_LEDGER_013_S5_attribution_is_checks_attribution(self):
        repo = self.project()
        _, d = self.attribution(repo, "main..claude/vessel")
        repo.git("checkout", "-q", "--detach", "claude/vessel")
        check = repo.ledger("check", "--ci", "--json", extra_env={"GITHUB_EVENT_NAME": "pull_request",
                                                                   "GITHUB_BASE_REF": "main", "CI": "true"})
        diffs = json_of(self, check)["diffs"]
        flagged = {x["detail"][:12] for x in diffs if x["code"] == "UNATTRIBUTED"}
        self.assertEqual(flagged, {sha[:12] for sha in d["unattributed"]})
        self.assertTrue(flagged)

    def test_LEDGER_013_S5_a_correction_row_attributes_a_trunk_commit(self):
        repo = GitRepo(self.tmp)
        repo.plan("AUTH-001")
        base = repo.sha()
        loose = repo.commit("feat: AUTH-001 without a trailer")
        repo.commit("docs: the row\n\nNo-story: docs", files={"backlog/ledger-corrections.toml": textwrap.dedent(f'''\
            [[row]]
            story = "AUTH-001"
            commit = "{loose}"
            kind = "late"
            evidence = "the subject names it"
            approver = "Leo"
            date = "2026-11-25"
            ''')})
        repo.publish()
        _, d = self.attribution(repo, f"{base}..main")
        by = {c["sha"]: c for c in d["commits"]}
        self.assertEqual((by[loose]["attributed"], by[loose]["via"]), (True, "correction"))
        self.assertIs(d["ok"], True)

    def test_LEDGER_013_S5_exit_codes_for_usage_and_unresolved_ends(self):
        repo = self.project()
        for rng in ("main", "main...claude/vessel", "..main", "main..", "nope..main", "main..nope", "-x..main",
                    "main..--output=/tmp/x", "main..claude/vessel..x", " main..claude/vessel"):
            with self.subTest(rng=rng):
                r = repo.ledger("attribution", rng, "--json")
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertNotIn("Traceback", r.stderr)
        for bad in (["attribution"], ["attribution", "a..b", "--json", "x"], ["attribution", "a..b", "--full"]):
            with self.subTest(bad=bad):
                self.assertEqual(repo.ledger(*bad).returncode, 2)

    def test_LEDGER_013_S5_a_cut_history_exits_3(self):
        repo = self.project()
        shallow = repo.clone("shallow", depth=1)
        shallow.git("fetch", "-q", "--depth=1", "origin", "claude/vessel:refs/remotes/origin/claude/vessel")
        r = shallow.ledger("attribution", "origin/main..origin/claude/vessel", "--json")
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)

    def test_LEDGER_013_S5_text_mode_lists_each_unattributed_commit_and_a_summary(self):
        repo = self.project()
        r = repo.ledger("attribution", f"{self.base}..claude/vessel")
        self.assertEqual(r.returncode, 0)
        lines = r.stdout.splitlines()
        self.assertEqual(len([line for line in lines if line.startswith("UNATTRIBUTED")]), 3)
        self.assertIn(self.loose[:12], r.stdout)
        self.assertIn("3 unattributed", lines[-1])

    def test_LEDGER_013_S5_commits_before_since_are_left_out_as_check_leaves_them(self):
        repo = GitRepo(self.tmp)
        repo.plan("AUTH-001")
        first = repo.sha()
        old = repo.commit("chore: before the rules")
        repo.state('[ledger]\nsince = "%s"\n' % old)
        new = repo.commit("feat: after\n\nPart-of: AUTH-001")
        repo.publish()
        _, d = self.attribution(repo, f"{first}..main")
        self.assertEqual([c["sha"] for c in d["commits"]], [new])
        self.assertEqual(d["since"], old)


class LedgerCheckJsonSchemaTest(LedgerCase):
    def test_LEDGER_013_S9_check_json_keeps_its_schema(self):
        repo = GitRepo(self.tmp)
        repo.plan("AUTH-001")
        base = repo.sha()
        repo.state('[ledger]\nsince = "%s"\nenforce = "block"\n' % base)
        repo.commit("chore: nothing said")
        repo.publish()
        r = repo.ledger("check", "--json")
        self.assertEqual(r.returncode, 1)
        d = json_of(self, r)
        self.assertEqual(d["schema"], 1)
        self.assertIsInstance(d["diffs"], list)
        self.assertTrue(d["diffs"])
        for x in d["diffs"]:
            self.assertLessEqual({"level", "code", "detail"}, set(x))
            self.assertIn(x["level"], ("error", "warning"))
            self.assertRegex(x["code"], r"^[A-Z][A-Z_]+$")
            self.assertIsInstance(x["detail"], str)


class LedgerRulesRefTest(LedgerCase):
    """`check --rules-ref REV` (Harbor's ok, HRB-3): the rule files of the committed tree come from REV, so a convoy
    judged as landed cannot relax its own rules."""

    def test_LEDGER_013_S10_a_convoy_that_relaxes_critical_toml_is_judged_by_the_rules_at_rules_ref(self):
        repo, c = build_delegated(self.tmp, approval("delegated"))
        commit_harness(repo, "chore: a review\n\nNo-story: ledger",
                       {f"{REVIEWS}/rpay.json": review_text("rpay", [review_row("UXC-303", c["UXC-303"])])})
        repo.publish()
        rules = repo.sha()
        commit_harness(repo, "chore: convoy relaxes the rules\n\nNo-story: ledger",
                       {CRITICAL: "", CORR: corrections(delegated_row("UXC-303", c["UXC-303"], "rpay"))})
        repo.publish()  # origin/main is the convoy's tip, as landed
        own = json_of(self, repo.ledger("check", "--json"))
        self.assertFalse([d for d in own["diffs"] if d["code"] == "CORRECTION_INVALID"],
                         "by its own rules the relaxed convoy passes: the hole --rules-ref closes")
        r = repo.ledger("check", "--json", "--rules-ref", rules)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        invalid = [d["detail"] for d in json_of(self, r)["diffs"] if d["code"] == "CORRECTION_INVALID"]
        self.assertEqual(len(invalid), 1, invalid)
        self.assertIn("UXC-303", invalid[0])
        ci = repo.ledger("check", "--ci", "--rules-ref", rules, "--json")
        self.assertEqual(json_of(self, ci)["diffs"], json_of(self, r)["diffs"], "any order of the flags")

    def test_LEDGER_013_S10_breaker1_a_convoy_cannot_narrow_the_storys_touches_past_the_rules(self):
        """Cold breaker round 1, finding 1: the story's touches and dimensions decide the critical flag; under
        --rules-ref they are read as <rev> has them, not as the convoy rewrote them."""
        repo, c = build_delegated(self.tmp, approval("delegated"))
        commit_harness(repo, "chore: a review\n\nNo-story: ledger",
                       {f"{REVIEWS}/rpay.json": review_text("rpay", [review_row("UXC-303", c["UXC-303"])])})
        repo.publish()
        rules = repo.sha()
        commit_harness(repo, "chore: convoy narrows the story\n\nNo-story: ledger",
                       {"backlog/stories/UXC-303-s.md": story15("UXC-303", ("apps/api/pay/x.ts",), ("logic",)),
                        CORR: corrections(delegated_row("UXC-303", c["UXC-303"], "rpay"))})
        repo.publish()
        r = repo.ledger("check", "--json", "--rules-ref", rules)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertTrue([d for d in json_of(self, r)["diffs"] if d["code"] == "CORRECTION_INVALID"
                         and "UXC-303" in d["detail"]])

    def test_LEDGER_013_S10_breaker1_the_ledger_table_comes_from_the_rules_ref(self):
        """Cold breaker round 1, finding 2: `[ledger]` (enforce, since, no_story, stories) is a rule too: under
        --rules-ref it is <rev>'s committed state.toml, not the checked-out convoy's."""
        repo = GitRepo(self.tmp)
        repo.plan("AUTH-001")
        since = repo.sha()
        block = '[ledger]\nsince = "%s"\nenforce = "block"\n' % since
        commit_harness(repo, "chore: rules\n\nNo-story: harness", {".keelokit/state.toml": block})
        repo.publish()
        rules = repo.sha()
        repo.commit("chore: unattributed convoy commit")
        commit_harness(repo, "chore: relax\n\nNo-story: harness",
                       {".keelokit/state.toml": block.replace('"block"', '"warn"')})
        repo.publish()
        self.assertEqual(repo.ledger("check", "--json").returncode, 0, "by its own rules, a warning")
        r = repo.ledger("check", "--json", "--rules-ref", rules)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("UNATTRIBUTED", [d["code"] for d in json_of(self, r)["diffs"] if d["level"] == "error"])

    def test_LEDGER_013_S10_breaker2_a_row_main_never_held_is_judged_by_the_rules_ref(self):
        """Cold breaker round 2, finding 2: a convoy whose first-parent chain runs through an old side-branch commit
        (critical.toml emptied, the row added, both undone before main merged it) cannot have its row judged by that
        commit's critical.toml: under --rules-ref a row's arrival is read on <rev>'s own history only."""
        repo, c = build_delegated(self.tmp, approval("delegated"))
        commit_harness(repo, "chore: a review\n\nNo-story: ledger",
                       {f"{REVIEWS}/rpay.json": review_text("rpay", [review_row("UXC-303", c["UXC-303"])])})
        repo.publish()
        repo.git("checkout", "-q", "-b", "side")
        p1 = commit_harness(repo, "chore: wip\n\nNo-story: harness",
                            {CRITICAL: "", CORR: corrections(delegated_row("UXC-303", c["UXC-303"], "rpay"))})
        repo.git("rm", "-q", CORR)
        commit_harness(repo, "chore: undo wip\n\nNo-story: harness", {CRITICAL: CRITICAL_TOML})
        repo.git("checkout", "-q", "main")
        repo.merge("side", "Merge side\n\nNo-story: harness")
        repo.publish()
        rules = repo.sha()
        repo.git("checkout", "-q", "-b", "convoy/1", p1)
        commit_harness(repo, "chore: convoy\n\nNo-story: harness", {CRITICAL: CRITICAL_TOML})
        repo.git("merge", "-q", "--no-ff", "-m", "Merge main\n\nNo-story: harness", "main", when=repo.next_date())
        commit_harness(repo, "chore: keep the corrections file\n\nNo-story: harness",
                       {CORR: corrections(delegated_row("UXC-303", c["UXC-303"], "rpay"))})
        repo.git("push", "-q", "origin", "convoy/1:main")
        repo.git("fetch", "-q", "origin")
        r = repo.ledger("check", "--json", "--rules-ref", rules)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertTrue([d for d in json_of(self, r)["diffs"] if d["code"] == "CORRECTION_INVALID"
                         and "UXC-303" in d["detail"]])

    def test_LEDGER_013_S10_the_same_rules_give_the_same_verdict(self):
        repo, _ = build_delegated(self.tmp, approval("delegated"))
        plain = repo.ledger("check", "--json")
        same = repo.ledger("check", "--json", "--rules-ref", "main")
        self.assertEqual((plain.returncode, plain.stdout), (same.returncode, same.stdout))

    def test_LEDGER_013_S10_an_unknown_rules_ref_is_exit_2(self):
        repo, _ = build_delegated(self.tmp, approval("delegated"))
        for rev in ("nope", "-x", "main..main", "0" * 40):
            with self.subTest(rev=rev):
                r = repo.ledger("check", "--json", "--rules-ref", rev)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertNotIn("Traceback", r.stderr)
        for bad in (["check", "--rules-ref"], ["check", "--rules-ref", "main", "--rules-ref", "main"]):
            with self.subTest(bad=bad):
                self.assertEqual(repo.ledger(*bad).returncode, 2)


class LedgerTemplateCopyTest(unittest.TestCase):
    def test_LEDGER_013_S8_the_plugins_ledger_is_the_projects(self):
        self.assertEqual((REPO / "template/.keelokit/bin/ledger.py").read_bytes(),
                         (REPO / ".keelokit/bin/ledger.py").read_bytes())


if __name__ == "__main__":
    unittest.main()
