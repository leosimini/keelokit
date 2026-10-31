"""report.py (what the process cost) and the verify line of status.py (a cut run is noticed).
Run: python3 -m unittest discover -s tests"""
import json
import runpy
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

BIN = Path(__file__).resolve().parents[1] / "template/.keelokit/bin"


class ReportTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.root)
        (self.root / ".keelokit/bin").mkdir(parents=True)
        shutil.copy(BIN / "report.py", self.root / ".keelokit/bin/report.py")
        (self.root / "docs").mkdir()
        (self.root / "docs/escapes.md").write_text("| Id | Date | Found by | What | Class | Check |\n|---|---|---|---|---|---|\n"
                                                    "| ESC-001 | 2026-10-01 | a | w | once | test: x |\n| ESC-002 | 2026-10-05 | b | w | once | lint: y |\n"
                                                    "| ESC-003 | 2026-10-06 | c | w | limit | test: z |\n")

    def report(self, *a):
        return subprocess.run([sys.executable, ".keelokit/bin/report.py", *a], cwd=self.root, capture_output=True, text=True).stdout

    def test_verify_escapes_and_what_is_not_measured(self):
        now = int(time.time())
        rows = [{"t": now - 100, "head": "abc", "level": "all", "result": "fail", "rc": 1, "steps": [["Unit tests", 600], ["Lint", 30]], "failed": ["Unit tests"], "causes": ["heap"]},
                {"t": now - 50, "head": "def", "level": "changed", "result": "pass", "rc": 0, "steps": [["Unit tests", 120]], "failed": [], "causes": []},
                {"t": now - 90 * 86400, "head": "old", "level": "all", "result": "fail", "rc": 1, "steps": [], "failed": [], "causes": ["disk"]}]
        (self.root / ".git/keelokit-verify.history").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        out = self.report("--since", "7d")
        self.assertIn("2 runs (1 full), 1 red", out)
        self.assertIn("heap ×1", out)
        self.assertNotIn("disk", out)  # outside the window
        self.assertIn("| Unit tests | 2 | 6m00s | 10m00s |", out)
        self.assertIn("3 logged, 2 classes; 1 repeated a class", out)
        self.assertIn("Tokens per role and per tier: nothing records them", out)

    def test_a_bad_period_is_refused(self):
        r = subprocess.run([sys.executable, ".keelokit/bin/report.py", "--since", "soon"], cwd=self.root, capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)


class StatusLineTest(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d)
        self.line = runpy.run_path(str(BIN / "status.py"), run_name="status")["verify_line"]

    def write(self, **kv):
        base = {"state": "running", "pid": "999999", "step": "Unit tests", "since": str(int(time.time()) - 5400), "head": "abcdef0123", "level": "all", "rc": "", "log": "/x/log"}
        (self.d / "keelokit-verify.state").write_text("\n".join(f"{k}={v}" for k, v in {**base, **kv}.items()) + "\n")

    def test_a_run_whose_process_is_gone_is_called_cut(self):
        self.write()
        out = self.line(self.d)
        self.assertIn("CUT", out)
        self.assertIn("'Unit tests' after 90 min", out)

    def test_running_passed_failed_and_none(self):
        import os
        self.write(pid=str(os.getpid()))
        self.assertIn("running 'Unit tests' for 90 min", self.line(self.d))
        self.write(state="pass", rc="0")
        self.assertIn("last pass (exit 0) on abcdef0", self.line(self.d))
        self.write(state="fail", rc="143")
        self.assertIn("last fail (exit 143)", self.line(self.d))
        (self.d / "keelokit-verify.state").unlink()
        self.assertIn("no run recorded", self.line(self.d))


if __name__ == "__main__":
    unittest.main()
