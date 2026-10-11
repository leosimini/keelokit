"""The doctor's process checks: CI budget (CI-1), the verify map (CI-2), formatting (FMT-1), migrations
(MIG-1), flaky-test knobs (FLAKY-1) and the pre-launch debt ledger (DEBT-1).
Run: python3 -m unittest discover -s tests"""
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

DOCTOR = Path(__file__).resolve().parents[1] / "template/.keelokit/bin/doctor.py"
TEMPLATE = Path(__file__).resolve().parents[1] / "template"

WORKFLOW = """\
name: CI
on:
  pull_request:
    branches: [main]
jobs:
  checks:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - run: pnpm lint
  unit:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - run: pnpm test
"""
VERIFY = "step 'Lint'\nstep 'Unit tests'\n"
STORY = """\
+++
id = "{id}"
epic = "DB"
title = "t"
wave = {wave}
depends_on = []
touches = [{touches}]
dimensions = ["data"]
+++
```gherkin
Scenario: [S1] works
```
"""


def sh(cwd: Path, *cmd: str) -> str:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True).stdout


class ProcessTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        self.write(".keelokit/bin/doctor.py", DOCTOR.read_text())
        self.write(".github/workflows/ci.yml", WORKFLOW)
        self.write("scripts/verify.sh", VERIFY)
        for f in ("product", "domain", "constraints", "environments"):
            self.write(f"docs/context/{f}.md", f"# {f}\n")
        self.write("docs/context/gaps.md", "| Id | File | Missing | Owner | Question | Blocking |\n|---|---|---|---|---|---|\n")
        sh(self.root, "git", "init", "-q", "-b", "main")
        sh(self.root, "git", "config", "user.email", "t@example.com")
        sh(self.root, "git", "config", "user.name", "T")

    def write(self, rel: str, text: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text))

    def commit(self) -> None:
        sh(self.root, "git", "add", "-A")
        sh(self.root, "git", "commit", "-qm", "c", "--allow-empty")

    def doctor(self, *args: str) -> str:
        res = subprocess.run(["python3", ".keelokit/bin/doctor.py", *args], cwd=self.root, capture_output=True, text=True)
        return res.stdout + res.stderr

    def test_a_job_without_a_timeout_warns(self):
        self.write(".github/workflows/ci.yml", WORKFLOW.replace("    timeout-minutes: 10\n", "", 1))
        self.assertIn("CI-1: job 'checks'", self.doctor())
        self.assertNotIn("CI-1: job 'unit'", self.doctor())

    def test_raising_a_timeout_fails_and_a_lower_one_does_not(self):
        self.commit()
        self.write(".github/workflows/ci.yml", WORKFLOW.replace("timeout-minutes: 10", "timeout-minutes: 20", 1))
        out = self.doctor()
        self.assertIn("ERROR CI-1: job 'checks'", out)
        self.assertIn("10 → 20", out)
        self.assertIn("Split the job", out)
        self.write(".github/workflows/ci.yml", WORKFLOW.replace("timeout-minutes: 10", "timeout-minutes: 5", 1))
        self.assertNotIn("CI-1", self.doctor())

    def test_every_ci_job_must_be_in_the_verify_map_with_a_real_step(self):
        out = self.doctor()
        self.assertIn("warn  CI-2: no .keelokit/verify-map.toml", out)
        self.write(".keelokit/verify-map.toml", """\
            [jobs]
            checks = { step = "Lint", when = "always" }
            gone = { step = "Nothing", when = "never" }
            """)
        out = self.doctor()
        self.assertIn("ERROR CI-2: CI job 'unit' is not in .keelokit/verify-map.toml", out)
        self.assertIn("verify step 'Nothing'", out)
        self.assertNotIn("CI job 'checks'", out)
        self.write(".keelokit/verify-map.toml", """\
            ci_only = ["unit"]
            [jobs]
            checks = { step = "Lint", when = "always" }
            """)
        self.assertNotIn("CI-2", self.doctor())

    def test_a_release_workflow_is_not_a_gating_ci_and_needs_no_map_entry(self):
        self.write(".github/workflows/release.yml", "name: Release\non:\n  push:\n    tags: ['v*']\njobs:\n  check:\n    runs-on: ubuntu-latest\n    timeout-minutes: 5\n    steps:\n      - run: echo\n")
        self.write(".keelokit/verify-map.toml", '[jobs]\nchecks = { step = "Lint", when = "always" }\nunit = { step = "Unit tests", when = "always" }\n')
        self.assertNotIn("CI-2", self.doctor())

    def test_the_templates_own_map_covers_the_templates_own_workflow(self):
        """Every job the template's ci.yml can render is in its verify-map or ci_only, and every step exists."""
        import re
        import tomllib
        ci = (TEMPLATE / ".github/workflows/ci.yml.jinja").read_text()
        jobs = set(re.findall(r"(?m)^  ([\w-]+):\s*$", ci.split("\njobs:\n", 1)[1]))
        data = tomllib.loads((TEMPLATE / ".keelokit/verify-map.toml").read_text())
        verify = (TEMPLATE / "scripts/verify.sh").read_text()
        steps = re.findall(r"step\s+['\"]([^'\"]+)['\"]", verify)
        self.assertEqual(jobs - set(data["jobs"]) - set(data["ci_only"]), set())
        for job, entry in data["jobs"].items():
            self.assertTrue(any(entry["step"] in s for s in steps), f"{job}: no verify step '{entry['step']}'")

    def test_a_new_migration_must_sort_after_mains_last(self):
        for name in ("20261001_a", "20261005_c"):
            self.write(f"apps/api/prisma/migrations/{name}/migration.sql", "select 1;")
        self.commit()
        self.write("apps/api/prisma/migrations/20261003_b/migration.sql", "select 1;")
        out = self.doctor()
        self.assertIn("ERROR MIG-1", out)
        self.assertIn("20261003_b sort before '20261005_c'", out)
        shutil.rmtree(self.root / "apps/api/prisma/migrations/20261003_b")
        self.write("apps/api/prisma/migrations/20261007_d/migration.sql", "select 1;")
        self.assertNotIn("MIG-1", self.doctor())

    def test_two_stories_of_a_wave_cannot_both_add_migrations(self):
        self.write("backlog/stories/DB-001-a.md", STORY.format(id="DB-001", wave=1, touches='"apps/api/prisma/migrations/20261010_a"'))
        self.write("backlog/stories/DB-002-b.md", STORY.format(id="DB-002", wave=1, touches='"apps/api/prisma/migrations/20261011_b"'))
        out = self.doctor()
        self.assertIn("ERROR MIG-1: stories DB-001, DB-002 share wave 1 and all add migrations", out)
        self.write("backlog/stories/DB-002-b.md", STORY.format(id="DB-002", wave=2, touches='"apps/api/prisma/migrations/20261011_b"'))
        self.assertNotIn("MIG-1", self.doctor())

    def test_raising_retries_or_a_test_timeout_is_refused(self):
        self.write("apps/web/playwright.config.ts", "export default { retries: 0, timeout: 30_000 };\n")
        self.commit()
        self.write("apps/web/playwright.config.ts", "export default { retries: 2, timeout: 30_000 };\n")
        out = self.doctor()
        self.assertIn("ERROR FLAKY-1", out)
        self.assertIn("`retries` raised from 0 to 2", out)
        self.write("apps/web/playwright.config.ts", "export default { retries: 0, timeout: 60 * 1000 };\n")
        self.assertIn("`timeout` raised from 30000 to 60000", self.doctor())
        self.write("apps/web/playwright.config.ts", "export default { retries: 0, timeout: 10_000 };\n")
        self.assertNotIn("FLAKY-1", self.doctor())

    def test_an_approved_exception_turns_the_error_into_a_warning(self):
        self.write(".keelokit/harness/rules.toml", '[[rule]]\nid = "CI-1"\nlevel = "MUST NOT"\nrule = "r"\nwhy = "w"\nenforced_by = ["script:.keelokit/bin/doctor.py"]\n')
        self.write(".keelokit/exceptions.toml", '[[exception]]\nrule = "CI-1"\nreason = "r"\napprover = "A"\nexpires = "2999-01-01"\n')
        self.commit()
        self.write(".github/workflows/ci.yml", WORKFLOW.replace("timeout-minutes: 10", "timeout-minutes: 20", 1))
        out = self.doctor()
        self.assertIn("warn  CI-1: job 'checks'", out)
        self.assertNotIn("ERROR CI-1", out)

    def test_formatting_needs_pinned_line_endings_and_a_check_script(self):
        self.write("package.json", '{"scripts": {"format": "prettier --write ."}}')
        self.write(".prettierrc", "{}")
        out = self.doctor()
        self.assertIn("warn  FMT-1: no `* text=auto eol=lf`", out)
        self.assertIn("ERROR FMT-1: package.json has no `format:check`", out)
        self.write(".gitattributes", "* text=auto eol=lf\n")
        self.write("package.json", '{"scripts": {"format:check": "prettier --check ."}}')
        self.assertNotIn("FMT-1", self.doctor())

    LEDGER = """\
        # Pre-launch debt ledger

        ## Findings

        | Id | Found | Finding | Status | Fix (commit) or decision with recommendation |
        |---|---|---|---|---|
        {rows}

        ## Needs the owner

        | Id | What is needed | Why / what it blocks | Status |
        |---|---|---|---|
        {owner}
        """

    def ledger(self, rows="", owner=""):
        self.write("docs/prelaunch-debt-ledger.md", self.LEDGER.format(rows=rows, owner=owner))

    def test_the_debt_ledger_accepts_fixed_and_decided_with_a_recommendation(self):
        self.ledger("| D-001 | 2026-10-01 | Slow list | fixed | abc1234 |\n        | D-002 | 2026-10-02 | No dark mode | decided | Not now; I recommend after launch, costs 3 days |",
                    "| N-001 | Company tax id | invoices | provided |")
        out = self.doctor("--launch")
        self.assertIn("0 open finding(s), 0 item(s) waiting on the owner", out)
        self.assertEqual(subprocess.run(["python3", ".keelokit/bin/doctor.py", "--launch"], cwd=self.root, capture_output=True).returncode, 0)

    def test_the_debt_ledger_rejects_known_issues_and_decisions_without_a_recommendation(self):
        self.ledger("| D-001 | 2026-10-01 | Crash on rotate | decided | Known issue, fix later |\n        | D-002 | 2026-10-02 | Slow | decided | not now |\n        | D-003 | 2026-10-02 | Odd | parked | x |")
        out = self.doctor()
        self.assertIn("D-001 reads as a 'known issue / later'", out)
        self.assertIn("D-002 is 'decided' without a recommendation", out)
        self.assertIn("D-003 status must be open, fixed or decided", out)

    def test_launch_is_blocked_by_open_findings_and_what_waits_for_the_owner(self):
        self.ledger("| D-001 | 2026-10-01 | Slow list | open | in progress |", "| N-001 | Privacy policy text | store listing | needed |")
        res = subprocess.run(["python3", ".keelokit/bin/doctor.py", "--launch"], cwd=self.root, capture_output=True, text=True)
        self.assertEqual(res.returncode, 1)
        self.assertIn("1 open finding(s), 1 item(s) waiting on the owner", res.stdout)

    def test_a_ledger_needs_its_owner_section(self):
        self.write("docs/prelaunch-debt-ledger.md", "# Ledger\n\n| Id | Found | Finding | Status | Fix |\n|---|---|---|---|---|\n")
        self.assertIn("missing the section 'Needs the owner'", self.doctor())

    def test_the_templates_ledger_is_well_formed_and_empty(self):
        self.write("docs/prelaunch-debt-ledger.md", (TEMPLATE / "docs/prelaunch-debt-ledger.md").read_text())
        out = self.doctor("--launch")
        self.assertNotIn("ERROR", out)
        self.assertIn("0 open finding(s), 0 item(s)", out)


class VerifyLockTest(unittest.TestCase):
    """One `pnpm verify` per machine at a time (parallel sessions starve each other into fake timeouts)."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        (self.root / "scripts").mkdir()
        (self.root / "scripts/verify.sh").write_text((TEMPLATE / "scripts/verify.sh").read_text())
        sh(self.root, "git", "init", "-q", "-b", "main")
        self.lock = self.root / ".git/keelokit-verify.lock"

    def verify(self, **env):
        import os
        stub = self.root / "bin"
        stub.mkdir(exist_ok=True)
        (stub / "pnpm").write_text("#!/bin/sh\nexit 0\n")
        (stub / "pnpm").chmod(0o755)
        (stub / "python3").write_text("#!/bin/sh\nexit 0\n")
        (stub / "python3").chmod(0o755)
        return subprocess.run(["bash", "scripts/verify.sh"], cwd=self.root, capture_output=True, text=True, timeout=60,
                              env={**os.environ, "PATH": f"{stub}:{os.environ['PATH']}", **env})

    def test_a_live_holder_makes_verify_wait_and_give_up(self):
        holder = subprocess.Popen(["sleep", "30"])
        self.addCleanup(holder.wait)
        self.addCleanup(holder.kill)
        self.lock.mkdir()
        (self.lock / "pid").write_text(str(holder.pid))
        res = self.verify(VERIFY_LOCK_WAIT="0")
        self.assertEqual(res.returncode, 1)
        self.assertIn("Another verify is running on this machine", res.stdout)
        self.assertIn("Gave up", res.stdout)
        self.assertTrue(self.lock.is_dir())  # not ours: left alone

    def test_a_dead_holders_lock_is_taken_over_and_released_at_the_end(self):
        dead = subprocess.Popen(["true"])
        dead.wait()
        self.lock.mkdir()
        (self.lock / "pid").write_text(str(dead.pid))
        res = self.verify(VERIFY_LOCK_WAIT="0")
        self.assertNotIn("Another verify is running", res.stdout)
        self.assertFalse(self.lock.exists(), res.stdout + res.stderr)


if __name__ == "__main__":
    unittest.main()
