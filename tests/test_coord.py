"""coord.py: the watch (lease), its handoff, convoys and the budget, against a real bare remote.
Run: python3 -m unittest discover -s tests"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BIN = Path(__file__).resolve().parents[1] / "template/.keelokit/bin"


def sh(cwd, *cmd, env=None):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=env)
    if r.returncode:
        raise AssertionError(f"{cmd}: {r.stdout}{r.stderr}")
    return r.stdout.strip()


class CoordBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.origin = self.tmp / "origin.git"
        sh(self.tmp, "git", "init", "-q", "--bare", "-b", "main", str(self.origin))
        self.a = self.clone("a")
        (self.a / "README.md").write_text("x\n")
        sh(self.a, "git", "add", "-A")
        sh(self.a, "git", "commit", "-qm", "init")
        sh(self.a, "git", "push", "-q", "origin", "HEAD:main")
        self.b = self.clone("b")
        self.main_hash = sh(self.origin, "git", "rev-parse", "main")

    def clone(self, name):
        d = self.tmp / name
        sh(self.tmp, "git", "clone", "-q", str(self.origin), str(d))
        sh(d, "git", "config", "user.email", "t@t")
        sh(d, "git", "config", "user.name", "T")
        (d / ".keelokit/bin").mkdir(parents=True, exist_ok=True)
        for f in ("coord.py", "ci.py"):
            shutil.copy(BIN / f, d / ".keelokit/bin" / f)
        return d

    def coord(self, repo, *args, now="2026-10-31T10:00:00Z", expect=0, stdin=None):
        r = subprocess.run([sys.executable, ".keelokit/bin/coord.py", *args], cwd=repo, capture_output=True, text=True,
                           input=stdin, env={**os.environ, "KEELOKIT_NOW": now})
        self.assertEqual(r.returncode, expect, f"{args}: {r.stdout}{r.stderr}")
        return r.stdout + r.stderr


class WatchTest(CoordBase):
    def test_the_first_claim_wins_and_the_second_is_told_who_holds_it(self):
        self.assertIn("claimed: s1", self.coord(self.a, "claim", "--id", "s1"))
        out = self.coord(self.b, "claim", "--id", "s2", expect=1)
        self.assertIn("s1 holds the watch", out)
        self.assertIn("s1", self.coord(self.b, "status"))

    def test_two_sessions_claiming_at_once_leave_exactly_one_captain(self):
        for round_ in range(3):
            self.tearDown_remote()
            procs = [subprocess.Popen([sys.executable, ".keelokit/bin/coord.py", "claim", "--id", f"s{i}"], cwd=repo,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                      env={**os.environ, "KEELOKIT_NOW": "2026-10-31T10:00:00Z"})
                     for i, repo in enumerate((self.a, self.b))]
            codes = sorted(p.wait() for p in procs)
            for p in procs:
                p.stdout.close()
                p.stderr.close()
            self.assertEqual(codes, [0, 1], f"round {round_}")

    def tearDown_remote(self):
        sh(self.origin, "git", "update-ref", "-d", "refs/heads/coord/board") if subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", "refs/heads/coord/board"], cwd=self.origin).returncode == 0 else None
        for repo in (self.a, self.b):
            shutil.rmtree(repo.parent.joinpath("x"), ignore_errors=True)
            wt = sh(repo, "git", "rev-parse", "--git-common-dir")
            shutil.rmtree(Path(repo, wt, "keelokit-coord"), ignore_errors=True)
            subprocess.run(["git", "worktree", "prune"], cwd=repo)

    def test_the_watch_expires_and_a_tick_takes_it_with_the_handoff(self):
        self.coord(self.a, "claim", "--id", "s1")
        ok = self.coord(self.b, "tick", "--id", "s2", now="2026-10-31T11:00:00Z")
        self.assertIn("WATCH-OK s1", ok)
        self.coord(self.a, "handoff", "--id", "s1", "--note", "-", stdin="Convoy 6 waits for QA-11.\nDecisions in force: none new.")
        took = self.coord(self.b, "tick", "--id", "s2", now="2026-10-31T11:30:00Z", expect=10)
        self.assertIn("TAKE-ROLE", took)
        self.assertIn("Convoy 6 waits for QA-11", took)
        self.assertIn("s2", self.coord(self.a, "status", now="2026-10-31T11:31:00Z"))

    def test_a_session_without_the_tools_only_observes_and_does_not_hold_the_watch(self):
        self.coord(self.a, "claim", "--id", "s1", "--ttl", "60")
        out = self.coord(self.b, "tick", "--id", "weak", "--observe-only", now="2026-10-31T12:00:00Z", expect=11)
        self.assertIn("WATCH-LAPSED", out)
        again = self.coord(self.b, "tick", "--id", "weak", "--observe-only", now="2026-10-31T12:30:00Z", expect=11)
        self.assertIn("Already recorded", again)
        status = json.loads(self.coord(self.b, "status", "--json", now="2026-10-31T12:31:00Z"))
        self.assertEqual(sum(1 for q in status["state"]["questions"] if q.startswith("WATCH-LAPSED")), 1)
        self.assertEqual(status["lease"]["holder"], "s1")  # nobody took it: a capable session still can
        self.assertIn("TAKE-ROLE", self.coord(self.a, "tick", "--id", "s2", now="2026-10-31T12:40:00Z", expect=10))

    def test_an_observer_stays_quiet_while_the_watch_is_alive(self):
        self.coord(self.a, "claim", "--id", "s1")
        self.assertIn("WATCH-OK", self.coord(self.b, "tick", "--id", "weak", "--observe-only", now="2026-10-31T10:30:00Z"))

    def test_notes_reach_the_board(self):
        self.coord(self.a, "note", "Fly secret is missing; needs the owner", "--id", "s7")
        sh(self.a, "git", "fetch", "-q", "origin", "coord/board")
        self.assertIn("s7: Fly secret is missing", sh(self.a, "git", "show", "origin/coord/board:BOARD.md"))

    def test_an_expired_watch_is_taken_without_a_handoff(self):
        self.coord(self.a, "claim", "--id", "s1", "--ttl", "60")
        out = self.coord(self.b, "tick", "--id", "s2", now="2026-10-31T12:00:00Z", expect=10)
        self.assertIn("TAKE-ROLE", out)
        status = json.loads(self.coord(self.b, "status", "--json", now="2026-10-31T12:01:00Z"))
        self.assertEqual((status["lease"]["holder"], status["lease"]["epoch"]), ("s2", 2))

    def test_only_the_holder_can_check_in_or_hand_over(self):
        self.coord(self.a, "claim", "--id", "s1")
        self.coord(self.b, "heartbeat", "--id", "s2", expect=1)
        self.coord(self.b, "handoff", "--id", "s2", "--note", "-", stdin="x", expect=1)
        self.assertIn("check-in recorded", self.coord(self.a, "heartbeat", "--id", "s1", now="2026-10-31T10:30:00Z"))

    def test_a_long_handoff_is_refused(self):
        self.coord(self.a, "claim", "--id", "s1")
        out = self.coord(self.a, "handoff", "--id", "s1", "--note", "-", stdin="\n".join(["line"] * 41), expect=1)
        self.assertIn("longer than 40 lines", out)

    def test_the_logbook_never_touches_main(self):
        self.coord(self.a, "claim", "--id", "s1")
        self.coord(self.a, "convoy", "new", "4")
        self.assertEqual(sh(self.origin, "git", "rev-parse", "main"), self.main_hash)
        self.assertTrue(sh(self.origin, "git", "rev-parse", "coord/board"))

    def test_the_board_is_generated_from_the_data(self):
        self.coord(self.a, "claim", "--id", "s1")
        self.coord(self.a, "session", "add", "s9", "--task", "QA-8", "--convoy", "6", "--branch", "qa-8")
        sh(self.a, "git", "fetch", "-q", "origin", "coord/board")
        board = sh(self.a, "git", "show", "origin/coord/board:BOARD.md")
        self.assertIn("s1 since", board)
        self.assertIn("| s9 | QA-8 | 6 | `qa-8` | active |", board)


class ConvoyTest(CoordBase):
    def piece(self, name, files):
        sh(self.a, "git", "checkout", "-q", "-b", name, "origin/main")
        for f, text in files.items():
            (self.a / f).write_text(text)
        sh(self.a, "git", "add", "-A")
        sh(self.a, "git", "commit", "-qm", name)
        return sh(self.a, "git", "rev-parse", "HEAD")

    def test_a_convoy_sails_only_when_every_condition_holds(self):
        self.coord(self.a, "convoy", "new", "6", "--conductor", "j1")
        h1 = self.piece("p1", {"a.txt": "1"})
        self.coord(self.a, "convoy", "add", "6", "QA-1", "--branch", "p1", "--hash", h1)
        self.coord(self.a, "convoy", "add", "6", "QA-2", "--branch", "p2", expect=1)  # no hash: it doesn't enter
        out = self.coord(self.a, "convoy", "ready", "6", "--offline", expect=1)
        for missing in ("tests is not ok", "review is not ok", "not 'lista'", "docs (manual, environments)"):
            self.assertIn(missing, out)
        self.coord(self.a, "convoy", "piece", "6", "QA-1", "--tests", "ok", "--review", "ok", "--state", "lista")
        self.coord(self.a, "convoy", "docs", "6", "ok")
        self.assertIn("is ready", self.coord(self.a, "convoy", "ready", "6", "--offline"))
        self.coord(self.a, "convoy", "ship", "6", "--hash", "abc1234")
        sh(self.a, "git", "fetch", "-q", "origin", "coord/board")
        self.assertIn("en-main", sh(self.a, "git", "show", "origin/coord/board:BOARD.md"))

    def test_a_screen_needs_captures_and_a_leftover_needs_a_valid_reason(self):
        self.coord(self.a, "convoy", "new", "7")
        h = self.piece("p1", {"a.txt": "1"})
        self.coord(self.a, "convoy", "add", "7", "UI-1", "--branch", "p1", "--hash", h, "--ui")
        self.coord(self.a, "convoy", "piece", "7", "UI-1", "--tests", "ok", "--review", "ok", "--state", "lista")
        self.coord(self.a, "convoy", "docs", "7", "ok")
        self.assertIn("a screen without captures", self.coord(self.a, "convoy", "ready", "7", "--offline", expect=1))
        self.coord(self.a, "convoy", "piece", "7", "UI-1", "--captures", "ok")
        self.coord(self.a, "convoy", "pending", "7", "polish the empty state", "--reason", "later", expect=1)
        self.coord(self.a, "convoy", "pending", "7", "Fly secret", "--reason", "production-config")
        self.assertIn("is ready", self.coord(self.a, "convoy", "ready", "7", "--offline"))

    def test_seam_lists_files_two_pieces_both_change(self):
        self.coord(self.a, "convoy", "new", "8")
        h1 = self.piece("p1", {"shared.ts": "one", "only1.ts": "x"})
        h2 = self.piece("p2", {"shared.ts": "two", "only2.ts": "y"})
        self.coord(self.a, "convoy", "add", "8", "A", "--branch", "p1", "--hash", h1)
        self.coord(self.a, "convoy", "add", "8", "B", "--branch", "p2", "--hash", h2)
        out = self.coord(self.a, "convoy", "seam", "8")
        self.assertIn("shared.ts  ← A, B", out)
        self.assertNotIn("only1.ts", out)

    def test_budget_goes_up_with_sessions_and_limit_hits(self):
        self.assertIn("budget: low", self.coord(self.a, "budget"))
        for i in range(2):
            self.coord(self.a, "session", "add", f"s{i}", "--task", "t")
        self.assertIn("budget: medium", self.coord(self.a, "budget"))
        self.coord(self.a, "note-limit")
        out = self.coord(self.a, "budget")
        self.assertIn("budget: high", out)
        self.assertIn("pause the biggest convoy", out)
        self.assertIn("budget: medium", self.coord(self.a, "budget", now="2026-10-31T20:00:00Z"))


if __name__ == "__main__":
    unittest.main()
