"""ci.py: CI health of main (cancelled is not green), time budget per job, failing step, slowest tests.
Run: python3 -m unittest discover -s tests"""
import json
import os
import re
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



def jobs_of(text: str) -> dict[str, str]:
    """job id -> its text, from a workflow's `jobs:` block (two-space job keys)."""
    body = text.split("\njobs:\n", 1)[1]
    jobs, name = {}, None
    for line in body.splitlines():
        if line.startswith("  ") and not line.startswith("   ") and line.rstrip().endswith(":") and not line.lstrip().startswith("#"):
            name = line.strip()[:-1]
            jobs[name] = ""
        elif name and not (line and not line.startswith(" ")):
            jobs[name] += line + "\n"
    return jobs


class LedgerStepTest(unittest.TestCase):
    """LEDGER-010: `ledger.py check --ci` runs in the job that already runs the doctor with fetch-depth 0, in the
    template's CI and in this repo's (a PR's commits and the trunk since `since` need the full history)."""

    ROOT = Path(__file__).resolve().parents[1]
    FILES = (".github/workflows/ci.yml", "template/.github/workflows/ci.yml.jinja")

    def test_LEDGER_010_S5_the_ci_step_exists_in_the_doctor_job_with_fetch_depth_0_INV_007(self):
        for rel in self.FILES:
            with self.subTest(workflow=rel):
                jobs = jobs_of((self.ROOT / rel).read_text())
                with_step = [name for name, text in jobs.items() if "python3 .keelokit/bin/ledger.py check --ci" in text]
                self.assertEqual(len(with_step), 1, f"one job runs the ledger step: {with_step}")
                job = jobs[with_step[0]]
                self.assertIn("python3 .keelokit/bin/doctor.py --ci", job, "the doctor's job")
                self.assertRegex(job, r"(?m)^\s+fetch-depth: 0\b")
                self.assertLess(job.index("doctor.py --ci"), job.index("ledger.py check --ci"))

    def test_LEDGER_010_S5_the_workflows_run_on_pull_requests_and_on_pushes_to_main(self):
        for rel in self.FILES:
            with self.subTest(workflow=rel):
                head = (self.ROOT / rel).read_text().split("\njobs:\n", 1)[0]
                self.assertIn("pull_request:", head)
                self.assertRegex(head, r"push:\s*\n\s+branches: \[main\]")


class LedgerSnapshotJobTest(unittest.TestCase):
    """LEDGER-011: the template's CI writes the snapshot on every push to main and every tag, and its deploy jobs move
    deploy/staging and deploy/production after a deploy that succeeded. Only those jobs may write to the repo."""

    ROOT = Path(__file__).resolve().parents[1]
    CI = "template/.github/workflows/ci.yml.jinja"
    RELEASE = "template/.github/workflows/release.yml.jinja"

    def text(self, rel: str) -> str:
        return (self.ROOT / rel).read_text()

    def jobs(self, rel: str) -> dict[str, str]:
        return jobs_of(self.text(rel))

    def test_LEDGER_011_S1_the_snapshot_job_runs_on_pushes_to_main_and_on_tags(self):
        for rel, event in ((self.CI, "push"), (self.RELEASE, "push")):
            with self.subTest(workflow=rel):
                jobs = self.jobs(rel)
                self.assertIn("ledger-snapshot", jobs)
                job = jobs["ledger-snapshot"]
                self.assertIn("python3 .keelokit/bin/ledger.py snapshot --run", job)
                self.assertRegex(job, r"(?m)^\s+fetch-depth: 0\b", "the snapshot needs the full history")
                self.assertRegex(job, r"(?m)^\s+group: ledger-snapshot\s*$")
                self.assertRegex(job, r"(?m)^\s+cancel-in-progress: false\s*$", "a running snapshot is never cancelled")
        head = self.text(self.RELEASE).split("\njobs:\n", 1)[0]
        self.assertRegex(head, r"tags: \['v\*\.\*\.\*'\]")
        ci_job = self.jobs(self.CI)["ledger-snapshot"]
        self.assertIn("github.event.before", ci_job, "a push names what it brought: --push before..after")
        self.assertIn("--push", ci_job)

    def test_LEDGER_011_S1_only_the_writing_jobs_get_contents_write(self):
        for rel in (self.CI, self.RELEASE):
            with self.subTest(workflow=rel):
                text = self.text(rel)
                head = text.split("\njobs:\n", 1)[0]
                self.assertRegex(head, r"(?m)^permissions:\n  contents: read\s*$", "the workflow reads by default")
                writers = sorted(n for n, t in self.jobs(rel).items() if "contents: write" in t)
                allowed = {"ledger-snapshot", "deploy-staging", "deploy-production"}
                self.assertTrue(writers and set(writers) <= allowed, writers)
                self.assertIn("ledger-snapshot", writers)

    def test_LEDGER_011_S1_no_push_the_ci_makes_starts_a_workflow(self):
        """keelokit/ledger and deploy/* are pushed by the CI: no workflow may run on them (no loop)."""
        for rel in (".github/workflows/ci.yml", self.CI, self.RELEASE):
            with self.subTest(workflow=rel):
                head = "\n".join(line for line in self.text(rel).split("\njobs:\n", 1)[0].splitlines()
                                 if not line.lstrip().startswith("#"))
                self.assertNotIn("branches-ignore", head)
                for branches in re.findall(r"branches: \[([^\]]*)\]", head):
                    self.assertEqual([b.strip() for b in branches.split(",")], ["main"], head)
                self.assertNotRegex(head, r"keelokit/|deploy/|'\*\*'|\"\*\*\"")

    def test_LEDGER_011_S4_the_deploy_jobs_move_their_branch_after_a_deploy_that_succeeded(self):
        for rel, job_name, env in ((self.CI, "deploy-staging", "staging"), (self.RELEASE, "deploy-production", "production")):
            with self.subTest(job=job_name):
                job = self.jobs(rel)[job_name]
                move = f'python3 .keelokit/bin/ledger.py deploy {env} "$GITHUB_SHA"'
                self.assertIn(move, job)
                self.assertLess(job.index("flyctl deploy"), job.index(move), "after the deploy, never before")
                step = job[job.rindex("- ", 0, job.index(move)):]
                self.assertIn("steps.fly.outputs.ready == 'yes'", step, "only when a deploy really ran")
                self.assertIn("contents: write", job)
                self.assertRegex(job, rf"(?m)^\s+group: deploy-{env}\s*$", "deploys of one environment take turns")

    def test_LEDGER_011_S5_a_rollback_is_the_release_run_again_from_an_older_tag(self):
        head = self.text(self.RELEASE).split("\njobs:\n", 1)[0]
        self.assertIn("workflow_dispatch:", head)

    def test_LEDGER_011_S6_the_snapshot_job_runs_only_when_the_project_keeps_a_snapshot(self):
        for rel in (self.CI, self.RELEASE):
            with self.subTest(workflow=rel):
                jobs = self.jobs(rel)
                gate = jobs["ledger-config"]
                self.assertIn("python3 .keelokit/bin/ledger.py snapshot --branch", gate)
                self.assertNotIn("contents: write", gate)
                job = jobs["ledger-snapshot"]
                self.assertRegex(job, r"(?m)^    needs: ledger-config\s*$")
                self.assertIn("if: needs.ledger-config.outputs.branch != ''", job)


if __name__ == "__main__":
    unittest.main()
