"""The doctor's process checks: CI budget (CI-1), the verify map (CI-2), formatting (FMT-1), migrations
(MIG-1), flaky-test knobs (FLAKY-1) and the pre-launch debt ledger (DEBT-1).
Run: python3 -m unittest discover -s tests"""
import re
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
        steps = re.findall(r"step\s+(?:[\w-]+\s+)?['\"]([^'\"]+)['\"]", verify)  # step [ID] 'Title'
        self.assertEqual(jobs - set(data["jobs"]) - set(data["ci_only"]), set())
        for job, entry in data["jobs"].items():
            self.assertTrue(any(entry["step"] in s for s in steps), f"{job}: no verify step '{entry['step']}'")
        # and the doctor's own reading of verify.sh agrees (CI-2), on the template's real files
        self.write("scripts/verify.sh", verify)
        self.write(".keelokit/verify-map.toml", (TEMPLATE / ".keelokit/verify-map.toml").read_text())
        self.assertNotIn("has no such step", self.doctor())

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
        self.assertNotIn(".gitattributes: can't be read", out)  # a missing file is the warning, not a second error
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


REPO = Path(__file__).resolve().parents[1]

# FLEET-005: what a money story is, worded the same in breaker.md, build-story and invariants.md (ESC-101).
MONEY_STORY = "a money story: the integrity dimension, or a story that moves money in a project with the payments trait"
# The changed shipped files that must not name the project the examples came from.
FLEET_005_SHIPPED = ["agents/breaker.md", "agents/reviewer.md", "references/invariants.md",
                     "references/dimensions.md", "skills/build-story/SKILL.md"]

# FLEET-005: the six failure paths of a money story, by the key phrase each must carry wherever the
# list appears (agents/breaker.md, references/invariants.md, and build-story when it spells them out).
FAILURE_PATHS = {
    "an automatic retry still running": "retry still running",
    "a response lost after the money moved": "response lost",
    "the connection or credential removed mid-flight": "credential removed",
    "a double submit": "double submit",
    "a close, cancel or delete with operations pending": "operations pending",
    "a manual instruction shown while an automatic one is still running": "manual instruction",
}


def _norm(text: str) -> str:
    """Lowercase, hyphens and backticks dropped, whitespace collapsed (phrases may wrap lines)."""
    return " ".join(text.lower().replace("-", " ").replace("`", "").split())


def _section(text: str, heading_pattern: str) -> str:
    """The markdown section whose heading matches the regex, up to the next heading of the same or a
    higher level (headings inside code fences don't count). Empty when no heading matches."""
    import re
    lines, fence, start, level = text.splitlines(), False, None, 0
    for i, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            fence = not fence
            continue
        m = None if fence else re.match(r"^(#{1,6})\s+(.*)$", line)
        if not m:
            continue
        if start is None:
            if re.search(heading_pattern, m.group(2), re.I):
                start, level = i, len(m.group(1))
        elif len(m.group(1)) <= level:
            return "\n".join(lines[start:i])
    return "" if start is None else "\n".join(lines[start:])


def _items(text: str) -> list[str]:
    """Top-level-or-nested list items (`- `, `* `, `1. `) with their continuation lines."""
    import re
    items: list[str] = []
    for line in text.splitlines():
        if re.match(r"^\s*([-*]|\d+\.)\s+", line):
            items.append(line)
        elif items and line.strip() and not line.lstrip().startswith("#"):
            items[-1] += " " + line
        elif not line.strip() and items:
            items.append("")
    return [i for i in items if i]


def _code_block_after(text: str, heading_pattern: str) -> str:
    sec = _section(text, heading_pattern)
    parts = sec.split("```")
    return parts[1] if len(parts) > 2 else ""


class MoneyFailurePathsTest(unittest.TestCase):
    """FLEET-005: a money story's breaker walks every failure path, and its copy cannot make anyone
    move money twice (docs/fleet-lessons.md, lesson 9)."""

    def read(self, rel: str) -> str:
        return (REPO / rel).read_text()

    def assertAllPathsInDistinctItems(self, section: str, where: str):
        items = [_norm(i) for i in _items(section)]
        for name, phrase in FAILURE_PATHS.items():
            hits = [i for i in items if phrase in i]
            self.assertTrue(hits, f"{where}: no list item names '{name}' (key phrase '{phrase}')")
        owners = {phrase: next(n for n, i in enumerate(items) if phrase in i) for phrase in FAILURE_PATHS.values()}
        self.assertEqual(len(set(owners.values())), len(FAILURE_PATHS),
                         f"{where}: each failure path needs its own list item, got {owners}")

    # S1 — agents/breaker.md: a section whose heading mentions "failure path(s)".
    def breaker_section(self) -> str:
        sec = _section(self.read("agents/breaker.md"), r"failure path")
        self.assertTrue(sec, "agents/breaker.md has no heading mentioning 'failure path'")
        return sec

    def test_FLEET_005_S1_breaker_lists_the_six_failure_paths(self):
        self.assertAllPathsInDistinctItems(self.breaker_section(), "agents/breaker.md failure-path section")

    def test_FLEET_005_S1_breaker_applies_them_to_integrity_and_payments_stories(self):
        sec = _norm(self.breaker_section())
        self.assertIn("integrity", sec)
        self.assertIn("payments", sec)

    def test_FLEET_005_S1_breaker_requires_one_line_per_path_with_a_test_or_a_reason(self):
        sec = _norm(self.breaker_section())
        self.assertIn("one line per", sec)
        self.assertIn("test", sec)
        self.assertIn("reason", sec)
        self.assertIn("cannot happen", sec)

    def test_FLEET_005_S1_breaker_output_has_a_place_for_failure_path_lines(self):
        block = _norm(_code_block_after(self.read("agents/breaker.md"), r"^output$"))
        self.assertTrue(block, "agents/breaker.md: no code block under '## Output'")
        self.assertIn("failure path", block)

    # S2 — agents/reviewer.md's COPY-1 item, and the `copy` row of references/dimensions.md.
    def test_FLEET_005_S2_reviewer_copy_item_asks_about_moving_money_twice_or_not_at_all(self):
        items = [_norm(i) for i in _items(self.read("agents/reviewer.md")) if "COPY-1" in i]
        self.assertTrue(items, "agents/reviewer.md: no list item cites COPY-1")
        item = items[0]
        self.assertIn("near money", item)
        self.assertIn("move money twice", item)
        self.assertIn("not at all", item)

    def test_FLEET_005_S2_dimensions_copy_row_carries_the_money_question(self):
        rows = [_norm(l) for l in self.read("references/dimensions.md").splitlines() if l.startswith("| `copy` |")]
        self.assertEqual(len(rows), 1, "references/dimensions.md: expected one `copy` row")
        self.assertIn("move money twice", rows[0])
        self.assertIn("not at all", rows[0])

    # S3 — skills/build-story/SKILL.md, step "## 2. Contract" (it runs before "## 3. Acceptance tests first").
    def contract(self) -> str:
        text = self.read("skills/build-story/SKILL.md")
        sec = _section(text, r"^2\. Contract")
        self.assertTrue(sec, "build-story: no '## 2. Contract' section")
        self.assertLess(text.index(sec), text.index("## 3. Acceptance tests first"))
        return sec

    def test_FLEET_005_S3_contract_lists_a_money_storys_failure_paths(self):
        sec = self.contract()
        items = [_norm(i) for i in _items(sec) if "failure path" in _norm(i)]
        self.assertTrue(items, "build-story contract: no item about failure paths")
        item = items[0]
        self.assertIn("money", item)
        spelled_out = all(p in _norm(sec) for p in FAILURE_PATHS.values())
        self.assertTrue(spelled_out or "invariants.md" in item or "breaker.md" in item,
                        "the failure-path item must spell out the six paths or point at the list in "
                        "invariants.md / breaker.md")

    def test_FLEET_005_S3_contract_says_money_decisions_are_reversible_and_new_ones_wait(self):
        items = [_norm(i) for i in _items(self.contract()) if "reversible" in _norm(i)]
        self.assertTrue(items, "build-story contract: no item about reversible money decisions")
        item = items[0]
        self.assertIn("money", item)
        self.assertTrue("told" in item or "tell" in item, "the person is told")
        self.assertIn("waits for the person", item)

    # S4 — references/invariants.md: a failure-path section tied to `once` and replay, with two examples.
    def invariants_section(self) -> str:
        sec = _section(self.read("references/invariants.md"), r"failure path")
        self.assertTrue(sec, "references/invariants.md has no heading mentioning 'failure path'")
        return sec

    def test_FLEET_005_S4_invariants_has_the_six_paths_under_once_and_replay(self):
        sec = self.invariants_section()
        self.assertAllPathsInDistinctItems(sec, "references/invariants.md failure-path section")
        self.assertIn("once", _norm(sec))
        self.assertIn("replay", _norm(sec))

    def test_FLEET_005_S4_invariants_has_two_anonymized_examples(self):
        sec = _norm(self.invariants_section())
        self.assertIn("refund by hand", sec)
        self.assertIn("retrying", sec)
        self.assertIn("connection", sec)
        self.assertIn("in flight", sec)
        whole = self.read("references/invariants.md").lower()
        self.assertNotIn("jouna", whole)
        self.assertNotIn("mercado pago", whole)

    # Round 1: review and breaker findings.

    def test_FLEET_005_S1_ESC_100_the_report_limit_exempts_the_failure_path_lines(self):
        import re
        paragraphs = [" ".join(p.split()) for p in self.read("agents/breaker.md").split("```")[0::2]
                      for p in p.split("\n\n")]
        sentences = [x for p in paragraphs for x in re.split(r"(?<=\.)\s", p) if "10 lines" in x]
        self.assertTrue(sentences, "agents/breaker.md: no sentence with the report limit '10 lines'")
        for sentence in sentences:
            self.assertIn("BROKEN", sentence)
            self.assertIn("FAILURE PATHS", sentence, f"the limit must exempt the FAILURE PATHS lines: {sentence!r}")

    def test_FLEET_005_S1_ESC_101_breaker_defines_a_money_story_like_the_others(self):
        self.assertIn(MONEY_STORY, _norm(self.read("agents/breaker.md")))

    def test_FLEET_005_S3_ESC_101_build_story_defines_a_money_story_like_the_others(self):
        self.assertIn(MONEY_STORY, _norm(self.read("skills/build-story/SKILL.md")))

    def test_FLEET_005_S4_ESC_101_invariants_defines_a_money_story_like_the_others(self):
        self.assertIn(MONEY_STORY, _norm(self.read("references/invariants.md")))

    def test_FLEET_005_S3_ESC_101_a_money_story_is_always_full_tier(self):
        sec = _section(self.read("skills/build-story/SKILL.md"), r"^0\. Choose the tier")
        self.assertTrue(sec, "build-story: no '## 0. Choose the tier' section")
        rules = sec.split("Rules for the choice", 1)
        self.assertEqual(len(rules), 2, "build-story step 0: no 'Rules for the choice'")
        items = [i for i in _items(rules[1]) if "a money story" in _norm(i)]
        self.assertTrue(items, "step 0's rules don't mention 'a money story'")
        self.assertTrue(any("**full**" in i for i in items), f"a money story must be always **full**: {items}")

    def test_FLEET_005_S3_ESC_102_reversible_money_decisions_keep_what_is_reserved_for_the_human(self):
        items = [_norm(i) for i in _items(self.contract()) if "reversible" in _norm(i)]
        self.assertTrue(items, "build-story contract: no item about reversible money decisions")
        item = items[0]
        self.assertTrue("moves money" in item or "moving money" in item, item)
        self.assertIn("payment configuration", item)
        self.assertIn("reserved", item)

    def test_FLEET_005_S3_the_failure_path_item_comes_before_the_verifier_writes(self):
        items = [_norm(i) for i in _items(self.contract()) if "failure path" in _norm(i)]
        self.assertTrue(items, "build-story contract: no item about failure paths")
        self.assertIn("before the verifier writes", items[0])

    def test_FLEET_005_S4_the_failure_path_section_directly_follows_the_once_replay_test(self):
        import re
        text = self.read("references/invariants.md")
        h3 = [l for l in text.splitlines() if re.match(r"^###\s", l)]
        self.assertIn("### once: a replay test", h3)
        following = h3[h3.index("### once: a replay test") + 1]
        self.assertIn("failure path", following.lower())
        self.assertIn("once", following.lower())

    def test_FLEET_005_S4_no_changed_shipped_file_names_the_project(self):
        for rel in FLEET_005_SHIPPED:
            whole = self.read(rel).lower()
            for name in ("jouna", "mercado pago"):
                self.assertNotIn(name, whole, f"{rel} names '{name}'")

    def test_FLEET_005_S1_S3_the_section_name_they_quote_is_an_invariants_heading(self):
        import re
        headings = [_norm(l.lstrip("#")) for l in self.read("references/invariants.md").splitlines()
                    if re.match(r"^#{1,6}\s", l)]
        name = "the failure paths of a money movement"
        self.assertTrue(any(name in h for h in headings), f"no invariants.md heading contains '{name}'")
        for rel in ("agents/breaker.md", "skills/build-story/SKILL.md"):
            text = " ".join(self.read(rel).split())
            self.assertIn(f'"{name}"', text, f"{rel} doesn't quote \"{name}\"")
            # every quoted name right after a pointer to invariants.md must be one of its headings
            for quoted in re.findall(r'invariants\.md`?,? ?\(?"([^"]+)"', text):
                self.assertTrue(any(_norm(quoted) in h for h in headings),
                                f"{rel} points at invariants.md section \"{quoted}\", which no heading carries")


class SkillsReadTheLedgerTest(unittest.TestCase):
    """LEDGER-006: the skills ask `ledger.py` for story states instead of reading `Story:` trailers in git log
    themselves (docs/ledger.md, "The principle": one reader; INV-005 lives in the ledger)."""

    ROOT = Path(__file__).resolve().parents[1]

    def read(self, rel: str) -> str:
        return " ".join((self.ROOT / rel).read_text(encoding="utf-8").split())

    def test_LEDGER_006_S4_ship_release_lists_a_versions_stories_with_release(self):
        text = self.read("skills/ship-release/SKILL.md")
        self.assertIn("ledger.py --release", text)

    def test_LEDGER_006_S5_build_story_asks_the_ledger_before_the_contract_and_writes_a_body(self):
        raw = (self.ROOT / "skills/build-story/SKILL.md").read_text(encoding="utf-8")
        contract = raw.index("## 2. Contract")
        show = raw.find("ledger.py show <ID>")
        self.assertTrue(0 <= show < contract, "build-story runs `ledger.py show <ID>` before the contract")
        land = " ".join(raw[raw.index("## 7. Land"):].split())
        self.assertRegex(land, r"(?i)body", "step 7 says the Story: commit carries a body")
        self.assertRegex(land, r"(?i)decided", "the body says what was decided")
        self.assertRegex(land, r"(?i)left out", "and what was left out")

    def test_LEDGER_006_every_reader_skill_names_the_ledger(self):
        wants = {"skills/coordinate/SKILL.md": "ledger.py show", "skills/plan-backlog/SKILL.md": "ledger.py",
                 "skills/keelokit/SKILL.md": "ledger.py", "skills/check-health/SKILL.md": "ledger.py",
                 "skills/project-report/SKILL.md": "ledger.py", "skills/ship-release/SKILL.md": "ledger.py --release",
                 "skills/build-story/SKILL.md": "ledger.py show"}
        for rel, want in wants.items():
            self.assertIn(want, self.read(rel), rel)
        # No skill finds a landing by reading `Story:` trailers in git log itself.
        for rel in wants:
            self.assertNotRegex(self.read(rel), r"git log[^.]*`Story: <ID>`", rel)


class AgentBriefFleetLessonsTest(unittest.TestCase):
    """FLEET-006: the agent brief carries the habits the JOUNA fleet paid for (docs/fleet-lessons.md, lesson 8 and
    coordination): push before waiting, wait on state, ranges, archive on delivery, never --no-verify; coordinate and
    build-story say the same where they start sessions and agents. The brief stays one page (90 lines)."""

    ROOT = Path(__file__).resolve().parents[1]
    BRIEF = "template/.keelokit/harness/agent-brief.md"

    def read(self, rel: str) -> str:
        return (self.ROOT / rel).read_text(encoding="utf-8")

    def norm(self, rel: str) -> str:
        return _norm(self.read(rel))

    def waiting(self) -> str:
        sec = _section(self.read(self.BRIEF), r"^Waiting$")
        self.assertTrue(sec, "the brief has no Waiting section")
        return sec

    def test_FLEET_006_S1_brief_says_push_before_a_long_wait(self):
        text = _norm(self.waiting())
        self.assertIn("push before any wait longer than a few minutes", text)
        self.assertIn("idle cloud session can lose its container", text)

    def test_FLEET_006_S1_brief_says_how_to_push_branch_or_wip_with_the_same_commits(self):
        text = _norm(self.waiting())
        self.assertIn("the storys branch when verified", text.replace("'", ""))
        self.assertIn("wip/<topic> with the same commits", text)
        self.assertIn("never commits that exist only there", text)
        self.assertIn("wip 1", text)

    def test_FLEET_006_S2_waiting_names_state_not_log_lines(self):
        sec = self.waiting()
        text = _norm(sec)
        self.assertNotIn("(a log line, an exit status", text, "a log line is no longer something to wait on")
        self.assertNotRegex(text, r"\(a log line", "the old list of conditions is gone")
        self.assertIn("never a log line", text)
        for state in ("status.py", "the exit code", "a ci run's", "a remote ref", "git ls remote"):
            self.assertIn(state, text, f"Waiting names {state!r} as a state to wait on")

    def test_FLEET_006_S2_no_wait_on_a_log_line_anywhere_in_the_brief(self):
        """Only the negation may mention a log line; no sentence lists one as a condition."""
        text = self.norm(self.BRIEF)
        for m in re.finditer(r"log line", text):
            self.assertIn("never", text[max(0, m.start() - 12):m.start()], text[max(0, m.start() - 60):m.end()])

    def test_FLEET_006_S3_brief_asks_for_ranges_from_status_py(self):
        text = _norm(self.waiting())
        self.assertIn("range status.py prints", text)
        self.assertIn("never one figure", text)
        # The range the brief shows is the shape status.py prints (FLEET-002).
        self.assertIn('f"about {lo}–{hi} min left"', self.read("template/.keelokit/bin/status.py"))
        self.assertIn("about 13–23 min left", text)

    def test_FLEET_006_S3_brief_says_a_cloud_session_archives_itself_on_delivery(self):
        report = _norm(_section(self.read(self.BRIEF), r"^The report"))
        self.assertIn("pushed and reported, a cloud session archives itself", report)

    def test_FLEET_006_S3_every_delegated_prompt_forbids_no_verify(self):
        intro = _norm(self.read(self.BRIEF).split("\n## ", 1)[0])
        self.assertIn("a prompt for a session or agent says", intro)
        self.assertIn("plus one line, **never no verify**", intro)

    def test_FLEET_006_S3_the_brief_stays_one_page(self):
        self.assertLessEqual(len(self.read(self.BRIEF).splitlines()), 90, "the brief is one page")

    def test_FLEET_006_S4_coordinate_repeats_it_where_it_starts_sessions(self):
        start = _norm(_section(self.read("skills/coordinate/SKILL.md"), r"^Start sessions$"))
        for line in ("never no verify.", "every prompt you delegate", "push before any wait longer than a few minutes",
                     "wip/<topic> with the same commits", "never on a log line", "status.py or the verify's exit code",
                     "a ci run's state", "a remote ref", "range status.py prints", "archive itself once its work is pushed"):
            self.assertIn(line, start, f"coordinate's Start sessions lacks {line!r}")
        rounds = _norm(_section(self.read("skills/coordinate/SKILL.md"), r"^Every round"))
        self.assertIn("never on a log line", rounds)
        self.assertNotIn("one condition", rounds)

    def test_FLEET_006_S4_build_story_repeats_it_where_it_starts_agents_and_sessions(self):
        raw = self.read("skills/build-story/SKILL.md")
        agents = _norm(_section(raw, r"^Spend less"))
        for line in ("every prompt you delegate says **never no verify**", "push before any wait longer than a few minutes",
                     "wip/<topic> with the same commits", "never on a log line", "status.py or the verify's exit code",
                     "a ci run's state", "a remote ref", "range status.py prints"):
            self.assertIn(line, agents, f"build-story's Spend less lacks {line!r}")
        self.assertNotIn("until on its log", agents)
        sessions = _norm(_section(raw, r"^1\. Pick"))
        for line in ("each prompt adds never no verify.", "push before waiting", "wait on state", "ranges",
                     "a cloud session archives itself once its work is pushed and reported"):
            self.assertIn(line, sessions, f"build-story's Pick lacks {line!r}")


if __name__ == "__main__":
    unittest.main()
