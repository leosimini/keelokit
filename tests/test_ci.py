"""ci.py: CI health of main (cancelled is not green), time budget per job, failing step, slowest tests.
Run: python3 -m unittest discover -s tests"""
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

CI = Path(__file__).resolve().parents[1] / "template/.keelokit/bin/ci.py"


def run(root: Path, *args: str, env: dict | None = None):
    return subprocess.run([sys.executable, str(root / ".keelokit/bin/ci.py"), *args], cwd=root, capture_output=True,
                          text=True, env={**os.environ, "GITHUB_STEP_SUMMARY": "", **(env or {})})


class CiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".keelokit/bin").mkdir(parents=True)
        (self.root / ".keelokit/bin/ci.py").write_text(CI.read_text())
        (self.root / ".github/workflows").mkdir(parents=True)
        (self.root / ".github/workflows/ci.yml").write_text(textwrap.dedent("""\
            name: CI
            jobs:
              unit:
                name: Unit tests
                timeout-minutes: 10
                runs-on: ubuntu-latest
                steps:
                  - run: pnpm test
              e2e:
                name: End-to-end journeys
                timeout-minutes: 20
                runs-on: ubuntu-latest
                steps:
                  - run: pnpm e2e
            """))
        self.addCleanup(self.tmp.cleanup)

    def write(self, name: str, data) -> str:
        p = self.root / name
        p.write_text(json.dumps(data))
        return str(p)

    def runs(self, *conclusions):
        return [{"name": "CI", "status": "completed", "conclusion": c, "run_number": 100 - i,
                 "created_at": f"2026-10-10T{23 - i:02d}:00:00Z"} for i, c in enumerate(conclusions)]

    def test_cancelled_runs_in_a_row_are_an_alarm_like_a_red(self):
        f = self.write("runs.json", self.runs("cancelled", "cancelled", "success"))
        out = run(self.root, "health", "--runs-file", f)
        self.assertEqual(out.returncode, 1, out.stdout)
        self.assertIn("ALARM", out.stdout)
        self.assertIn("2 cancelled", out.stdout)
        self.assertIn("last green before #99", out.stdout)

    def test_a_red_head_is_an_alarm_and_green_is_quiet(self):
        self.assertEqual(run(self.root, "health", "--runs-file", self.write("a.json", self.runs("failure", "success"))).returncode, 1)
        out = run(self.root, "health", "--runs-file", self.write("b.json", self.runs("success", "cancelled")))
        self.assertEqual(out.returncode, 0)
        self.assertIn("green", out.stdout)

    def test_one_cancelled_run_is_only_watched(self):
        out = run(self.root, "health", "--runs-file", self.write("c.json", self.runs("cancelled", "success")))
        self.assertEqual(out.returncode, 0)
        self.assertIn("watch", out.stdout)

    def test_no_green_in_the_window_says_so(self):
        out = run(self.root, "health", "--runs-file", self.write("d.json", self.runs("cancelled", "failure")))
        self.assertIn("no green run in the last 2", out.stdout)

    def jobs(self):
        return {"jobs": [
            {"name": "Unit tests", "status": "completed", "conclusion": "success",
             "started_at": "2026-10-10T10:00:00Z", "completed_at": "2026-10-10T10:08:00Z", "steps": []},
            {"name": "End-to-end journeys", "status": "completed", "conclusion": "cancelled",
             "started_at": "2026-10-10T10:00:00Z", "completed_at": "2026-10-10T10:20:00Z",
             "steps": [{"number": 6, "name": "pnpm e2e", "conclusion": "cancelled"}]},
        ]}

    def test_budget_flags_jobs_above_two_thirds_and_never_suggests_a_longer_timeout(self):
        f = self.write("jobs.json", self.jobs())
        out = run(self.root, "budget", "--jobs-file", f)
        self.assertEqual(out.returncode, 0)
        self.assertIn("Unit tests: over 2/3 of its 10 min", out.stdout)
        self.assertIn("End-to-end journeys: cancelled AT its timeout", out.stdout)
        self.assertIn("Do not raise the timeout", out.stdout)
        self.assertEqual(run(self.root, "budget", "--strict", "--jobs-file", f).returncode, 1)

    def test_jobs_names_the_failing_step(self):
        out = run(self.root, "jobs", "--jobs-file", self.write("jobs.json", self.jobs()))
        self.assertEqual(out.returncode, 1)
        self.assertIn("End-to-end journeys: cancelled — step 6 “pnpm e2e”", out.stdout)
        self.assertIn("service containers", out.stdout)

    def test_summary_lists_job_times_and_the_ten_slowest_tests(self):
        timings = self.root / "ci-timings"
        timings.mkdir()
        (timings / "unit.json").write_text(json.dumps({"testResults": [{"assertionResults": [
            {"fullName": f"t{i}", "duration": i * 10} for i in range(15)]}]}))
        (timings / "e2e.json").write_text(json.dumps({"suites": [{"title": "web.spec.ts", "specs": [
            {"title": "checkout", "tests": [{"results": [{"duration": 99000}]}]}]}]}))
        summary = self.root / "summary.md"
        out = run(self.root, "summary", "--jobs-file", self.write("jobs.json", self.jobs()), "--tests", str(timings),
                  env={"GITHUB_STEP_SUMMARY": str(summary)})
        self.assertEqual(out.returncode, 0, out.stderr)
        text = summary.read_text()
        self.assertIn("| Unit tests | 8m00s | 10 min | 80%", text)
        self.assertIn("1. 99.0s — web.spec.ts › checkout", text)
        self.assertEqual(sum(1 for line in text.splitlines() if line[:1].isdigit() and ". " in line[:4]), 10)

    def test_a_bad_command_line_exits_2(self):
        self.assertEqual(run(self.root, "nope").returncode, 2)


if __name__ == "__main__":
    unittest.main()
