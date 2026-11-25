"""LEDGER-014: the ledger sees the swarm's deliveries.

A swarm helper delivers a branch `swarm/<task-id>` in the code repo; its commits carry `Part-of: <ID>` and
`Swarm-Task: <task-id>`. The ledger never reads the swarm repo: it reads those branches and trailers here, and
Harbor's logbook for the convoy that carries or sailed them.

- S1: an unintegrated delivery: in-progress, and the story's `swarm` list has the task, the branch and the head;
- S2: an integrated delivery: show lists the task with its author among the story's commits;
- S3: a swarm branch without those trailers is no delivery of any story;
- S4: Swarm data is data: hostile content crashes nothing and changes no difference or exit code;
- S5: a delivery never attributes a commit on its own, and nothing in it relaxes `check --rules-ref`;
- S6: the phase gate (Harbor 0.6.0): a convoy carrying swarm deliveries lands, and show (text and --json) says each
  piece's story, who made it and which convoy sailed it.
Run: python3 -m unittest discover -s tests (real git, local remotes, never the network)."""
import json
import subprocess
import unittest
from pathlib import Path

from test_ledger import GitRepo, LedgerCase, by_id, commit_harness, read_json
from test_ledger_harbor import convoy_toml, json_of, run_toml, write_logbook

REPO = Path(__file__).resolve().parents[1]
TASK = "t-20261201-ab12"
TASK2 = "t-20261201-cd34"
TASK3 = "t-20261202-ef56"


def commit_as(repo: GitRepo, author: str, message: str) -> str:
    """A commit on the current branch whose author is `author` (the committer stays T)."""
    repo.changes += 1
    repo.write(f"changes/{repo.changes}.txt", message + "\n")
    repo.git("add", "-A")
    when = repo.next_date()
    env = {**repo.env, "GIT_AUTHOR_NAME": author, "GIT_AUTHOR_EMAIL": "helper@example.com",
           "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
    repo.run(["git", "commit", "-q", "-m", message], repo.path, env)
    return repo.sha()


def swarm_branch(repo: GitRepo, task: str, author: str, *messages: str, branch: str | None = None,
                 push: bool = True) -> list[str]:
    """The swarm helper's delivery: `swarm/<task>` (or `branch`) off the current branch, pushed, left as it was."""
    current = repo.git("symbolic-ref", "--short", "HEAD").strip()
    name = branch or f"swarm/{task}"
    repo.git("checkout", "-q", "-b", name)
    shas = [commit_as(repo, author, m) for m in messages]
    if push:
        repo.git("push", "-q", "origin", name)
    repo.git("checkout", "-q", current)
    return shas


def delivery(story: str, task: str) -> str:
    return f"feat: a piece of {story}\n\nPart-of: {story}\nSwarm-Task: {task}"


def show_text(test: unittest.TestCase, repo: GitRepo, sid: str, *more: str) -> str:
    r = repo.ledger("show", sid, *more)
    test.assertNotIn("Traceback", r.stderr)
    test.assertEqual(r.returncode, 0, r.stdout + r.stderr)
    return r.stdout


def show_json(test: unittest.TestCase, repo: GitRepo, sid: str) -> dict:
    r = repo.ledger("show", sid, "--json")
    test.assertEqual(r.returncode, 0, r.stdout + r.stderr)
    return json_of(test, r)


def check_json(test: unittest.TestCase, repo: GitRepo, *more: str) -> tuple[int, list]:
    r = repo.ledger("check", "--json", *more)
    test.assertNotIn("Traceback", r.stderr)
    return r.returncode, json_of(test, r)["diffs"]


class SwarmDeliveryTest(LedgerCase):
    def project(self) -> GitRepo:
        repo = GitRepo(self.tmp)
        repo.plan("AUTH-008", "AUTH-009")
        repo.publish()
        repo.state("[ledger]\nstale_days = 100000\n")
        return repo

    def test_LEDGER_014_S1_a_delivery_not_yet_integrated_is_in_progress_with_its_task_branch_and_head(self):
        repo = self.project()
        head = swarm_branch(repo, TASK, "Ana Helper", delivery("AUTH-008", TASK))[0]
        repo.git("fetch", "-q", "origin")
        s = by_id(read_json(self, repo))["AUTH-008"]
        self.assertEqual(s["state"], "in-progress")
        self.assertEqual(s["branches"], [f"swarm/{TASK}"])
        self.assertEqual(s["swarm"], [{"task": TASK, "state": "in-progress", "branch": f"swarm/{TASK}",
                                       "head": head, "commits": [head], "authors": ["Ana Helper"],
                                       "convoy": None}])
        self.assertEqual(by_id(read_json(self, repo))["AUTH-009"]["swarm"], [])
        out = show_text(self, repo, "AUTH-008")
        self.assertIn("state: in-progress", out)
        self.assertIn("swarm deliveries:", out)
        self.assertIn(f"  {TASK} · in-progress · swarm/{TASK}@{head[:12]} · by Ana Helper", out)
        self.assertEqual(show_json(self, repo, "AUTH-008")["swarm"], s["swarm"])
        self.assertNotIn("AUTH-008", repo.ledger("next").stdout, "someone (the swarm) is on it")

    def test_LEDGER_014_S1_the_head_is_the_branch_tip_and_every_delivery_commit_is_listed_oldest_first(self):
        repo = self.project()
        first, second = swarm_branch(repo, TASK, "Ana Helper", delivery("AUTH-008", TASK),
                                     delivery("AUTH-008", TASK).replace("a piece", "another piece"))
        repo.git("fetch", "-q", "origin")
        (entry,) = by_id(read_json(self, repo))["AUTH-008"]["swarm"]
        self.assertEqual((entry["head"], entry["commits"]), (second, [first, second]))

    def test_LEDGER_014_S1_a_delivery_in_an_open_convoy_sealed_on_its_head_names_that_convoy(self):
        repo = self.project()
        head = swarm_branch(repo, TASK, "Ana Helper", delivery("AUTH-008", TASK))[0]
        write_logbook(repo, {"harbor/convoys/13.toml": convoy_toml(13, "assembling", [(f"swarm/{TASK}", head, "AUTH-008")]),
                             f"harbor/runs/{head}.toml": run_toml(head)})
        s = by_id(read_json(self, repo))["AUTH-008"]
        self.assertEqual(s["state"], "delivered")
        self.assertEqual(s["swarm"][0]["convoy"], 13)
        self.assertIn(f"swarm/{TASK}@{head[:12]} · convoy 13 · by Ana Helper", show_text(self, repo, "AUTH-008"))

    def test_LEDGER_014_S1_a_red_seal_or_a_moved_branch_names_no_convoy(self):
        repo = self.project()
        head = swarm_branch(repo, TASK, "Ana Helper", delivery("AUTH-008", TASK))[0]
        write_logbook(repo, {"harbor/convoys/13.toml": convoy_toml(13, "assembling", [(f"swarm/{TASK}", head, "AUTH-008")]),
                             f"harbor/runs/{head}.toml": run_toml(head, 1)})
        self.assertIsNone(by_id(read_json(self, repo))["AUTH-008"]["swarm"][0]["convoy"])

    def test_LEDGER_014_S2_an_integrated_delivery_lists_its_task_and_author_among_the_commits(self):
        repo = self.project()
        head = swarm_branch(repo, TASK, "Ana Helper", delivery("AUTH-008", TASK))[0]
        repo.git("fetch", "-q", "origin")
        merge = repo.merge(f"origin/swarm/{TASK}", f"Merge branch 'swarm/{TASK}'")
        repo.publish()
        s = by_id(read_json(self, repo))["AUTH-008"]
        self.assertEqual(s["swarm"], [{"task": TASK, "state": "on-trunk", "branch": None, "head": None,
                                       "commits": [head], "authors": ["Ana Helper"], "convoy": None}])
        self.assertEqual(s["state"], "ready", "a Part-of: on the trunk closes nothing")
        why = show_json(self, repo, "AUTH-008")["why"]
        (c,) = [c for c in why["commits"] if c["sha"] == head]
        self.assertEqual((c["kind"], c["swarm_task"], c["author"]), ("Part-of", TASK, "Ana Helper"))
        out = show_text(self, repo, "AUTH-008")
        line = next(i for i, x in enumerate(out.splitlines()) if x.startswith(f"  {head[:12]} "))
        self.assertEqual(out.splitlines()[line + 1], f"    swarm: {TASK} · Ana Helper")
        self.assertIn(f"  {TASK} · on-trunk · by Ana Helper", out)
        self.assertNotIn(merge[:12], json.dumps(s["swarm"]))

    def test_LEDGER_014_S2_a_delivery_without_part_of_is_its_story_through_the_merge_that_attributes_it(self):
        repo = self.project()
        head = swarm_branch(repo, TASK, "Ana Helper", f"feat: a piece\n\nSwarm-Task: {TASK}")[0]
        repo.git("fetch", "-q", "origin")
        self.assertEqual(by_id(read_json(self, repo))["AUTH-008"]["swarm"], [], "S3 until a merge attributes it")
        repo.merge(f"origin/swarm/{TASK}", f"Merge branch 'swarm/{TASK}'\n\nPart-of: AUTH-008")
        repo.publish()
        stories = by_id(read_json(self, repo))
        self.assertEqual([(e["task"], e["state"], e["commits"]) for e in stories["AUTH-008"]["swarm"]],
                         [(TASK, "on-trunk", [head])])
        self.assertEqual(stories["AUTH-009"]["swarm"], [])

    def test_LEDGER_014_S2_through_a_nested_merge_too(self):
        """The helper's commit reaches the trunk through convoy/12 merged with --no-ff: the merge of the swarm branch
        inside it attributes it."""
        repo = self.project()
        head = swarm_branch(repo, TASK, "Ana Helper", f"feat: a piece\n\nSwarm-Task: {TASK}")[0]
        repo.git("fetch", "-q", "origin")
        repo.git("checkout", "-q", "-b", "convoy/12")
        repo.merge(f"origin/swarm/{TASK}", f"convoy 12: merge swarm/{TASK}\n\nPart-of: AUTH-008")
        repo.git("checkout", "-q", "main")
        repo.merge("convoy/12", "Merge pull request #3 from x/convoy/12")
        repo.publish()
        (entry,) = by_id(read_json(self, repo))["AUTH-008"]["swarm"]
        self.assertEqual((entry["task"], entry["commits"]), (TASK, [head]))

    def test_LEDGER_014_S3_a_swarm_branch_without_trailers_is_not_counted(self):
        repo = self.project()
        swarm_branch(repo, TASK, "Ana Helper", "feat: something AUTH-008 needs")
        swarm_branch(repo, TASK2, "Bo Helper", f"feat: only the task\n\nSwarm-Task: {TASK2}")
        repo.git("fetch", "-q", "origin")
        stories = by_id(read_json(self, repo))
        for sid in ("AUTH-008", "AUTH-009"):
            self.assertEqual((stories[sid]["state"], stories[sid]["swarm"], stories[sid]["branches"]), ("ready", [], []))
        self.assertNotIn("swarm deliveries", show_text(self, repo, "AUTH-008"))

    def test_LEDGER_014_S3_part_of_without_swarm_task_is_any_branch_not_a_delivery(self):
        """`Part-of:` alone is LEDGER-003's in-progress, on any branch; without `Swarm-Task:` it is no swarm delivery."""
        repo = self.project()
        swarm_branch(repo, TASK, "Ana Helper", "feat: x\n\nPart-of: AUTH-008")
        repo.git("fetch", "-q", "origin")
        s = by_id(read_json(self, repo))["AUTH-008"]
        self.assertEqual((s["state"], s["swarm"]), ("in-progress", []))

    def test_LEDGER_014_S3_a_task_that_is_not_its_branchs_or_a_branch_outside_swarm_is_no_delivery(self):
        repo = self.project()
        swarm_branch(repo, TASK, "Ana Helper", delivery("AUTH-008", TASK2))
        swarm_branch(repo, TASK3, "Bo Helper", delivery("AUTH-009", TASK3), branch=f"claude/{TASK3}")
        swarm_branch(repo, TASK3, "Bo Helper", delivery("AUTH-009", TASK3), branch=f"swarm/x/{TASK3}")
        repo.git("fetch", "-q", "origin")
        stories = by_id(read_json(self, repo))
        self.assertEqual(stories["AUTH-008"]["swarm"], [], "Swarm-Task names another task than its branch")
        self.assertEqual(stories["AUTH-009"]["swarm"], [], "not swarm/<task>")
        self.assertEqual(stories["AUTH-008"]["state"], "in-progress", "its Part-of still counts, as on any branch")

    def test_LEDGER_014_S3_two_tasks_on_one_commit_are_no_delivery(self):
        repo = self.project()
        swarm_branch(repo, TASK, "Ana Helper", f"feat: x\n\nPart-of: AUTH-008\nSwarm-Task: {TASK}\nSwarm-Task: {TASK2}")
        repo.git("fetch", "-q", "origin")
        self.assertEqual(by_id(read_json(self, repo))["AUTH-008"]["swarm"], [])


class SwarmHostileTest(LedgerCase):
    """S4 and S5: Swarm state is data anyone who can push writes."""

    def project(self) -> GitRepo:
        repo = GitRepo(self.tmp)
        self.since = repo.plan("AUTH-008", "AUTH-009")
        commit_harness(repo, "chore: adopt\n\nNo-story: harness",
                       {".keelokit/state.toml": f'[ledger]\nstale_days = 100000\nsince = "{self.since}"\n'})
        repo.publish()
        self.good = swarm_branch(repo, TASK, "Ana Helper", delivery("AUTH-008", TASK))[0]
        repo.git("fetch", "-q", "origin")
        return repo

    def raw_commit(self, repo: GitRepo, message: bytes, author: bytes = b"Mallory", parent: str | None = None) -> str:
        """A commit of the trunk's tree with exactly these bytes as its message and author name (plumbing)."""
        parent = parent or repo.sha("origin/main")
        tree = repo.git("rev-parse", f"{parent}^{{tree}}").strip()
        body = (f"tree {tree}\nparent {parent}\n".encode() + b"author " + author +
                b" <m@example.com> 1767225600 +0000\ncommitter T <t@example.com> 1767225600 +0000\n\n" + message)
        return subprocess.run(["git", "hash-object", "-t", "commit", "-w", "--stdin", "--literally"], cwd=repo.path,
                              env=repo.env, input=body, capture_output=True, check=True).stdout.decode().strip()

    def hostile(self, repo: GitRepo) -> None:
        bad = [
            (b"swarm/t-ctl", b"feat: \x1b[2J\x07\r\n\nPart-of: AUTH-008\nSwarm-Task: t-ctl\n", b"Ev\x1b]0;x\x07il"),
            (b"swarm/t-utf", b"feat: \xff\xfe\xc3\x28 bad\n\nPart-of: AUTH-008\nSwarm-Task: t-utf\n", b"\xff\xfeName"),
            (b"swarm/t-huge", b"feat: huge\n\n" + b"x" * (2 << 20) + b"\n\nPart-of: AUTH-009\nSwarm-Task: t-huge\n",
             b"A" * 5000),
            (b"swarm/t-bomb", b"feat: [[[[[[[[[[\n\n" + b"{" * 100000 + b"\n\nPart-of: AUTH-009\nSwarm-Task: t-bomb\n",
             b"Bomb"),
            (b"swarm/t-many", b"feat: many\n\nPart-of: AUTH-009\n" + b"".join(b"Swarm-Task: t-%d\n" % i for i in range(3000)),
             b"Many"),
            (b"swarm/" + b"t" * 200, b"feat: long\n\nPart-of: AUTH-009\nSwarm-Task: " + b"t" * 200 + b"\n", b"Long"),
            (b"swarm/t-odd", b"feat: odd\n\nPart-of: AUTH-009\nSwarm-Task: t-odd\x1b[31m\n", b"Odd"),
            (b"swarm/t-wrong", b"feat: wrong\n\nPart-of: NOPE-1, auth-008, \nSwarm-Task: t-wrong\n", b"Wrong"),
        ]
        for name, message, author in bad:
            sha = self.raw_commit(repo, message, author)
            repo.git("push", "-q", "origin", f"{sha}:refs/heads/{name.decode()}")
        # a symlink and a TOML bomb in the delivery's tree: the ledger reads no tree of a swarm branch
        repo.git("checkout", "-q", "-b", "swarm/t-tree")
        (repo.path / "link").symlink_to("/etc/passwd")
        repo.write("swarm.toml", "a = " + "[" * 50000 + "]" * 50000 + "\n")
        repo.git("add", "-A")
        repo.git("commit", "-q", "-m", "feat: tree\n\nPart-of: AUTH-009\nSwarm-Task: t-tree")
        repo.git("push", "-q", "origin", "swarm/t-tree")
        repo.git("checkout", "-q", "main")
        repo.git("fetch", "-q", "origin")

    def test_LEDGER_014_S4_hostile_swarm_data_crashes_nothing_and_changes_no_difference(self):
        repo = self.project()
        before = check_json(self, repo)
        before_ci = check_json(self, repo, "--ci")
        self.hostile(repo)
        self.assertEqual(check_json(self, repo), before)
        self.assertEqual(check_json(self, repo, "--ci"), before_ci)
        data = read_json(self, repo)
        stories = by_id(data)
        for args in (["show", "AUTH-008"], ["show", "AUTH-009", "--full"], ["show", "AUTH-008", "--json"],
                     ["show", "AUTH-009", "--json"], [], ["next"], ["--json"], ["check"]):
            with self.subTest(args=args):
                r = repo.ledger(*args)
                self.assertNotIn("Traceback", r.stderr)
                self.assertNotIn("the ledger failed", r.stderr)
                self.assertIn(r.returncode, (0, 1))
                if "--json" not in args:
                    for ch in ("\x1b", "\x07", "\r"):
                        self.assertNotIn(ch, r.stdout)
        tasks = {e["task"] for s in stories.values() for e in s["swarm"]}
        self.assertEqual(tasks, {TASK, "t-ctl", "t-utf", "t-huge", "t-bomb", "t-tree"},
                         "a task id that is not one (control characters, 200 characters, 3000 of them) is no delivery")
        authors = {a for s in stories.values() for e in s["swarm"] for a in e["authors"]}
        self.assertTrue(all(len(a) <= 200 for a in authors), "an author name is cut")
        self.assertEqual(stories["AUTH-009"]["state"], "in-progress")

    def test_LEDGER_014_S4_a_snapshot_with_a_malformed_swarm_list_is_no_crash(self):
        """A shallow clone reads the CI's snapshot; a hand-edited `swarm` list of the wrong shape is no crash."""
        repo = self.project()
        commit_harness(repo, "chore: snapshot on\n\nNo-story: harness",
                       {".keelokit/state.toml": '[ledger]\nstale_days = 100000\nsnapshot = "keelokit/ledger"\n'})
        repo.publish()
        r = repo.ledger("snapshot", extra_env={"KEELOKIT_SNAPSHOT_AT": "2026-11-20T10:00:00Z"})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        repo.git("fetch", "-q", "origin")
        blob = repo.git("show", "origin/keelokit/ledger:ledger.json")
        snap = json.loads(blob)
        self.assertEqual([e["task"] for e in by_id(snap)["AUTH-008"]["swarm"]], [TASK], "the snapshot carries it")
        for bad in ([1, "x", None], [{"task": 3}], [{"task": "t", "authors": "x"}], "x"):
            with self.subTest(bad=bad):
                for s in snap["stories"]:
                    if s["id"] == "AUTH-008":
                        s["swarm"] = bad
                write_snapshot(repo, json.dumps(snap))
                shallow = repo.clone(f"shallow-{abs(hash(str(bad)))}", depth=1)
                shallow.state('[ledger]\nstale_days = 100000\nsnapshot = "keelokit/ledger"\n')
                shallow.git("fetch", "-q", "--depth=1", "origin", "keelokit/ledger:refs/remotes/origin/keelokit/ledger")
                for args in (["show", "AUTH-008"], ["--json"], ["show", "AUTH-008", "--json"]):
                    r = shallow.ledger(*args)
                    self.assertNotIn("Traceback", r.stderr)
                    self.assertIn(r.returncode, (0, 1), r.stderr)

    def test_LEDGER_014_S5_a_swarm_task_alone_never_attributes_a_commit(self):
        repo = self.project()
        loose = commit_as(repo, "Ana Helper", f"feat: a piece\n\nSwarm-Task: {TASK}")
        repo.publish()
        code, diffs = check_json(self, repo)
        self.assertEqual(code, 1)
        self.assertIn(loose[:7], " ".join(d["detail"] for d in diffs if d["code"] == "UNATTRIBUTED"))
        r = repo.ledger("attribution", f"{self.since}..origin/main", "--json")
        self.assertEqual(json_of(self, r)["unattributed"], [loose], "Harbor's convoy add refuses it (NO_STORY)")
        self.assertEqual(by_id(read_json(self, repo))["AUTH-008"]["swarm"],
                         [{"task": TASK, "state": "in-progress", "branch": f"swarm/{TASK}", "head": self.good,
                           "commits": [self.good], "authors": ["Ana Helper"], "convoy": None}],
                         "the loose trunk commit is no delivery of any story")

    def test_LEDGER_014_S5_rules_ref_judges_the_same_with_or_without_swarm_data(self):
        repo = self.project()
        rules = repo.sha("origin/main")
        commit_as(repo, "Ana Helper", "chore: loose")
        repo.publish()
        before = check_json(self, repo, "--rules-ref", rules)
        self.assertEqual(before[0], 1)
        self.hostile(repo)
        # swarm commits that land on the trunk, attributed by their Part-of: the same differences
        repo.merge(f"origin/swarm/{TASK}", f"Merge branch 'swarm/{TASK}'")
        repo.publish()
        after = check_json(self, repo, "--rules-ref", rules)
        self.assertEqual(after, before)
        self.assertEqual(check_json(self, repo, "--ci", "--rules-ref", rules), before)


def write_snapshot(repo: GitRepo, ledger_json: str) -> None:
    """Replace ledger.json on origin/keelokit/ledger, keeping its other files."""
    head = repo.sha("origin/keelokit/ledger")
    index = repo.tmp / "snap-index"
    env = {**repo.env, "GIT_INDEX_FILE": str(index)}
    repo.run(["git", "read-tree", head], repo.path, env)
    blob = subprocess.run(["git", "hash-object", "-w", "--stdin"], cwd=repo.path, env=repo.env,
                          input=ledger_json.encode(), capture_output=True, check=True).stdout.decode().strip()
    repo.run(["git", "update-index", "--add", "--cacheinfo", f"100644,{blob},ledger.json"], repo.path, env)
    tree = repo.run(["git", "write-tree"], repo.path, env).strip()
    commit = repo.run(["git", "commit-tree", tree, "-p", head, "-m", "snapshot: hand edit"], repo.path).strip()
    repo.git("push", "-q", "-f", "origin", f"{commit}:refs/heads/keelokit/ledger")
    repo.git("fetch", "-q", "origin")


class SwarmBreakerRound1Test(LedgerCase):
    """Breaker round 1 (ESC-346, ESC-347)."""

    def test_LEDGER_014_S4_breaker1_a_snapshot_entry_missing_its_keys_is_no_crash(self):
        """ESC-346: a hand-edited snapshot entry without branch, head or convoy crashed show (KeyError)."""
        repo = GitRepo(self.tmp)
        repo.plan("AUTH-008")
        commit_harness(repo, "chore: snapshot on\n\nNo-story: harness",
                       {".keelokit/state.toml": '[ledger]\nstale_days = 100000\nsnapshot = "keelokit/ledger"\n'})
        repo.publish()
        r = repo.ledger("snapshot", extra_env={"KEELOKIT_SNAPSHOT_AT": "2026-11-20T10:00:00Z"})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        repo.git("fetch", "-q", "origin")
        snap = json.loads(repo.git("show", "origin/keelokit/ledger:ledger.json"))
        for n, bad in enumerate(({"task": "t1", "state": "on-trunk", "commits": [], "authors": []},
                                 {"task": "t1", "state": "on-trunk", "branch": None, "commits": [], "authors": []},
                                 {"task": "t1", "state": "on-trunk", "branch": "b", "head": None, "commits": [],
                                  "authors": ["a\nb"], "convoy": None})):
            with self.subTest(bad=bad):
                for s in snap["stories"]:
                    if s["id"] == "AUTH-008":
                        s["swarm"] = [bad]
                write_snapshot(repo, json.dumps(snap))
                shallow = repo.clone(f"shallow-r1-{n}", depth=1)
                shallow.state('[ledger]\nstale_days = 100000\nsnapshot = "keelokit/ledger"\n')
                shallow.git("fetch", "-q", "--depth=1", "origin", "keelokit/ledger:refs/remotes/origin/keelokit/ledger")
                r = shallow.ledger("show", "AUTH-008")
                self.assertNotIn("the ledger failed", r.stderr)
                self.assertIn(r.returncode, (0, 1), r.stderr)
                self.assertNotIn("t1 ·", r.stdout, "an entry of the wrong shape is left out: not shown")

    def test_LEDGER_014_S2_breaker1_a_reverted_delivery_is_not_on_the_trunk(self):
        """ESC-347: a delivery merged and then reverted still read `on-trunk` in the swarm list."""
        repo = GitRepo(self.tmp)
        repo.plan("AUTH-008")
        repo.publish()
        repo.state("[ledger]\nstale_days = 100000\n")
        head = swarm_branch(repo, TASK, "Ana Helper", f"feat: AUTH-008 done\n\nBody.\n\nStory: AUTH-008\nSwarm-Task: {TASK}")[0]
        repo.git("fetch", "-q", "origin")
        repo.git("merge", "-q", "--ff-only", f"origin/swarm/{TASK}")
        repo.revert(head)
        repo.publish()
        s = by_id(read_json(self, repo))["AUTH-008"]
        self.assertEqual((s["state"], s["reverted"]), ("ready", True))
        self.assertEqual([(e["task"], e["state"], e["commits"]) for e in s["swarm"]], [(TASK, "reverted", [head])])
        out = show_text(self, repo, "AUTH-008")
        self.assertIn(f"  {TASK} · reverted · by Ana Helper", out)
        self.assertNotIn("on-trunk", out)

    def test_LEDGER_014_S2_breaker1_a_merge_reverted_reverts_the_deliveries_it_brought(self):
        repo = GitRepo(self.tmp)
        repo.plan("AUTH-008")
        repo.publish()
        repo.state("[ledger]\nstale_days = 100000\n")
        head = swarm_branch(repo, TASK, "Ana Helper", delivery("AUTH-008", TASK))[0]
        repo.git("fetch", "-q", "origin")
        merge = repo.merge(f"origin/swarm/{TASK}", f"Merge branch 'swarm/{TASK}'")
        repo.git("revert", "--no-edit", "-m", "1", merge, when=repo.next_date())
        repo.publish()
        s = by_id(read_json(self, repo))["AUTH-008"]
        self.assertEqual([(e["task"], e["state"], e["commits"]) for e in s["swarm"]], [(TASK, "reverted", [head])])


class SwarmBreakerRound2Test(LedgerCase):
    """Breaker round 2 (ESC-348)."""

    def snapshot_clone(self, author: str, name: str) -> GitRepo:
        repo = GitRepo(self.tmp / name)
        repo.plan("AUTH-001", "AUTH-002")
        repo.commit("feat: AUTH-001\n\nBody.\n\nStory: AUTH-001")
        commit_harness(repo, "chore: snapshot on\n\nNo-story: harness",
                       {".keelokit/state.toml": '[ledger]\nstale_days = 100000\nsnapshot = "keelokit/ledger"\n'})
        repo.publish()
        swarm_branch(repo, TASK, author, delivery("AUTH-002", TASK))
        repo.git("fetch", "-q", "origin")
        r = repo.ledger("snapshot", extra_env={"KEELOKIT_SNAPSHOT_AT": "2026-11-20T10:00:00Z"})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        repo.git("fetch", "-q", "origin")
        shallow = repo.clone("shallow", depth=1)
        shallow.state('[ledger]\nstale_days = 100000\nsnapshot = "keelokit/ledger"\n')
        shallow.git("fetch", "-q", "--depth=1", "origin", "keelokit/ledger:refs/remotes/origin/keelokit/ledger")
        return shallow

    def test_LEDGER_014_S4_breaker2_an_author_with_a_tab_or_newline_never_poisons_the_snapshot(self):
        """ESC-348: a TAB in a swarm commit's author name went into the snapshot, which then read as none: every
        shallow clone's states turned unknown."""
        for n, author in enumerate(("Ana\tHelper", "Ana\x0bHelper")):
            with self.subTest(author=author):
                shallow = self.snapshot_clone(author, f"r{n}")
                data = json.loads(shallow.ledger("--json").stdout)
                self.assertTrue(data["history"].startswith("snapshot:"), data["history"])
                s = by_id(data)
                self.assertEqual((s["AUTH-001"]["state"], s["AUTH-002"]["state"]), ("on-trunk", "in-progress"))
                self.assertEqual(s["AUTH-002"]["swarm"][0]["authors"], ["Ana?Helper"])

    def test_LEDGER_014_S4_breaker2_a_bad_swarm_entry_drops_that_entry_never_the_snapshot(self):
        shallow = self.snapshot_clone("Ana Helper", "r")
        before = json.loads(shallow.ledger("--json").stdout)
        snap = json.loads(shallow.git("show", "origin/keelokit/ledger:ledger.json"))
        for s in snap["stories"]:
            if s["id"] == "AUTH-002":
                s["swarm"] = [{"task": "x", "state": "on-trunk"}, *s["swarm"], 7]
            if s["id"] == "AUTH-001":
                s["swarm"] = "not a list"
        write_snapshot(shallow, json.dumps(snap))
        shallow.git("fetch", "-q", "--depth=1", "origin", "+keelokit/ledger:refs/remotes/origin/keelokit/ledger")
        self.assertIn('"x"', shallow.git("show", "origin/keelokit/ledger:ledger.json"), "the hand edit is read")
        data = json.loads(shallow.ledger("--json").stdout)
        self.assertTrue(data["history"].startswith("snapshot:"))
        self.assertEqual([(s["id"], s["state"], s["swarm"]) for s in data["stories"]],
                         [(s["id"], s["state"], s["swarm"]) for s in before["stories"]])


class SwarmBreakerRound3Test(LedgerCase):
    """Breaker round 3 (ESC-349)."""

    def test_LEDGER_014_S2_breaker3_a_revert_after_the_snapshot_never_leaves_a_delivery_on_the_trunk(self):
        """ESC-349: a shallow clone reading the CI's snapshot settled the story to `ready · reverted` after a revert
        that landed later, but kept the snapshot's delivery `on-trunk`."""
        repo = GitRepo(self.tmp)
        repo.plan("AUTH-001", "AUTH-002")
        commit_harness(repo, "chore: snapshot on\n\nNo-story: harness",
                       {".keelokit/state.toml": '[ledger]\nstale_days = 100000\nsnapshot = "keelokit/ledger"\n'})
        repo.publish()
        swarm_branch(repo, TASK, "Ana Helper", f"feat: piece\n\nStory: AUTH-001\nSwarm-Task: {TASK}")
        repo.git("fetch", "-q", "origin")
        merge = repo.merge(f"origin/swarm/{TASK}", f"Merge swarm/{TASK}\n\nStory: AUTH-001")
        repo.publish()
        r = repo.ledger("snapshot", extra_env={"KEELOKIT_SNAPSHOT_AT": "2026-11-20T10:00:00Z"})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        repo.git("revert", "--no-edit", "-m", "1", merge, when=repo.next_date())
        repo.publish()
        shallow = repo.clone("shallow", depth=3)
        shallow.state('[ledger]\nstale_days = 100000\nsnapshot = "keelokit/ledger"\n')
        shallow.git("fetch", "-q", "--depth=1", "origin", "keelokit/ledger:refs/remotes/origin/keelokit/ledger")
        data = json.loads(shallow.ledger("--json").stdout)
        self.assertTrue(data["history"].startswith("snapshot:"), data["history"])
        s = by_id(data)["AUTH-001"]
        self.assertEqual((s["state"], s["reverted"]), ("ready", True))
        self.assertNotIn("on-trunk", [e["state"] for e in s["swarm"]])
        self.assertNotIn(f"{TASK} · on-trunk", show_text(self, shallow, "AUTH-001"))

    def test_LEDGER_014_S2_breaker3_a_snapshot_of_the_trunks_tip_keeps_its_deliveries(self):
        """The snapshot of the very commit the trunk is at still says each delivery (nothing landed since)."""
        repo = GitRepo(self.tmp)
        repo.plan("AUTH-001")
        commit_harness(repo, "chore: snapshot on\n\nNo-story: harness",
                       {".keelokit/state.toml": '[ledger]\nstale_days = 100000\nsnapshot = "keelokit/ledger"\n'})
        repo.publish()
        piece = swarm_branch(repo, TASK, "Ana Helper", delivery("AUTH-001", TASK))[0]
        repo.git("fetch", "-q", "origin")
        repo.merge(f"origin/swarm/{TASK}", f"Merge swarm/{TASK}")
        repo.publish()
        r = repo.ledger("snapshot", extra_env={"KEELOKIT_SNAPSHOT_AT": "2026-11-20T10:00:00Z"})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        shallow = repo.clone("shallow", depth=1)
        shallow.state('[ledger]\nstale_days = 100000\nsnapshot = "keelokit/ledger"\n')
        shallow.git("fetch", "-q", "--depth=1", "origin", "keelokit/ledger:refs/remotes/origin/keelokit/ledger")
        s = by_id(json.loads(shallow.ledger("--json").stdout))["AUTH-001"]
        self.assertEqual([(e["task"], e["state"], e["commits"]) for e in s["swarm"]], [(TASK, "on-trunk", [piece])])


class SwarmPhaseGateTest(LedgerCase):
    """S6, the gate of phase 3 (docs/ledger.md, "Plan") for Harbor 0.6.0: convoy 12 carries two swarm deliveries of
    AUTH-008 (Ana's and Bo's) and the session's own closing commit, and sails; convoy 13, open, carries a swarm
    delivery of AUTH-009 sealed on its head. A Harbor logbook, Swarm state (the swarm/* branches and their trailers)
    and trunk commits, nothing else."""

    def project(self) -> GitRepo:
        repo = GitRepo(self.tmp)
        repo.plan("AUTH-008", "AUTH-009")
        repo.publish()
        repo.state("[ledger]\nstale_days = 100000\n")
        self.before = repo.sha()
        self.ana = swarm_branch(repo, TASK, "Ana Helper", delivery("AUTH-008", TASK))[0]
        self.bo = swarm_branch(repo, TASK2, "Bo Helper", delivery("AUTH-008", TASK2))[0]
        self.close = repo.on_branch("claude/auth-008", "feat: AUTH-008\n\nWhat was decided.\n\nStory: AUTH-008",
                                    keep=True)[0]
        repo.git("fetch", "-q", "origin")
        repo.git("checkout", "-q", "-b", "convoy/12")
        for branch, head in ((f"swarm/{TASK}", self.ana), (f"swarm/{TASK2}", self.bo), ("claude/auth-008", self.close)):
            repo.merge(f"origin/{branch}", f"convoy 12: merge {branch}@{head[:12]}\n\nConvoy: 12")
        repo.git("checkout", "-q", "main")
        repo.git("merge", "-q", "--ff-only", "convoy/12")
        self.after = repo.sha()
        repo.publish("main", "convoy/12")
        self.cy = swarm_branch(repo, TASK3, "Cy Helper", delivery("AUTH-009", TASK3))[0]
        repo.git("fetch", "-q", "origin")
        write_logbook(repo, {
            "harbor/convoys/12.toml": convoy_toml(12, "sailed", [(f"swarm/{TASK}", self.ana, "AUTH-008"),
                                                                 (f"swarm/{TASK2}", self.bo, "AUTH-008"),
                                                                 ("claude/auth-008", self.close, "AUTH-008")],
                                                  sail=(self.before, self.after),
                                                  events=[("2026-11-20T10:00:00Z", "acct/host/s0", "sailed",
                                                           f"main {self.after[:12]}")]),
            "harbor/convoys/13.toml": convoy_toml(13, "assembling", [(f"swarm/{TASK3}", self.cy, "AUTH-009")]),
            f"harbor/runs/{self.cy}.toml": run_toml(self.cy),
            "harbor/main.toml": (f'schema = 1\nhead = "{self.after}"\n\n[[moves]]\nfrom = "{self.before}"\n'
                                 f'to = "{self.after}"\nseen = "2026-11-20T10:00:07Z"\ncause = "convoy 12"\n'),
        })
        return repo

    def test_LEDGER_014_S6_show_says_each_pieces_story_author_and_convoy(self):
        repo = self.project()
        data = show_json(self, repo, "AUTH-008")
        self.assertEqual((data["id"], data["state"], data["convoy"], data["since_exact"]), ("AUTH-008", "on-trunk", 12, True))
        self.assertEqual(data["swarm"], [
            {"task": TASK, "state": "on-trunk", "branch": None, "head": None, "commits": [self.ana],
             "authors": ["Ana Helper"], "convoy": 12},
            {"task": TASK2, "state": "on-trunk", "branch": None, "head": None, "commits": [self.bo],
             "authors": ["Bo Helper"], "convoy": 12}])
        pieces = {c["sha"]: c for c in data["why"]["commits"]}
        self.assertEqual({k: (pieces[k]["kind"], pieces[k]["swarm_task"], pieces[k]["author"])
                          for k in (self.ana, self.bo, self.close)},
                         {self.ana: ("Part-of", TASK, "Ana Helper"), self.bo: ("Part-of", TASK2, "Bo Helper"),
                          self.close: ("Story", None, "T")})
        out = show_text(self, repo, "AUTH-008")
        self.assertIn("state: on-trunk since 2026-11-20T10:00:07Z (exact)", out)
        self.assertIn("convoy: 12", out)
        self.assertIn(f"  {TASK} · on-trunk · convoy 12 · by Ana Helper", out)
        self.assertIn(f"  {TASK2} · on-trunk · convoy 12 · by Bo Helper", out)
        self.assertIn(f"    swarm: {TASK} · Ana Helper", out)
        self.assertIn(f"    swarm: {TASK2} · Bo Helper", out)

    def test_LEDGER_014_S6_an_open_convoy_carrying_a_swarm_delivery_names_it_before_it_lands(self):
        repo = self.project()
        data = show_json(self, repo, "AUTH-009")
        self.assertEqual((data["state"], data["convoy"]), ("delivered", 13))
        self.assertEqual(data["swarm"], [{"task": TASK3, "state": "in-progress", "branch": f"swarm/{TASK3}",
                                          "head": self.cy, "commits": [self.cy], "authors": ["Cy Helper"],
                                          "convoy": 13}])
        self.assertIn(f"  {TASK3} · in-progress · swarm/{TASK3}@{self.cy[:12]} · convoy 13 · by Cy Helper",
                      show_text(self, repo, "AUTH-009"))

    def test_LEDGER_014_S6_the_spanish_card_says_the_same(self):
        repo = self.project()
        repo.state('[ledger]\nstale_days = 100000\n[dashboard]\nlang = "es"\n')
        out = show_text(self, repo, "AUTH-008")
        self.assertIn("entregas del enjambre:", out)
        self.assertIn(f"  {TASK} · en trunk · convoy 12 · de Ana Helper", out)

    def test_LEDGER_014_S6_check_is_clean_and_the_plugins_ledger_is_the_projects(self):
        repo = self.project()
        self.assertEqual(check_json(self, repo), (0, []))
        self.assertEqual((REPO / "template/.keelokit/bin/ledger.py").read_bytes(),
                         (REPO / ".keelokit/bin/ledger.py").read_bytes())


if __name__ == "__main__":
    unittest.main()
