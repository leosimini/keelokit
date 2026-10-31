"""The risk floor (doctor --tier), review rounds and report formats, the escape log and flaky.sh.
Run: python3 -m unittest discover -s tests"""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

T = Path(__file__).resolve().parents[1] / "template"


def run(root, *cmd, stdin=None):
    r = subprocess.run(cmd, cwd=root, capture_output=True, text=True, input=stdin)
    return r.returncode, r.stdout + r.stderr


class Project(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        shutil.copytree(T / ".keelokit", self.root / ".keelokit", ignore=shutil.ignore_patterns("answers.yml.jinja"))
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.root)
        (self.root / "docs").mkdir()
        (self.root / "docs/escapes.md").write_text((T / "docs/escapes.md").read_text())
        for f in ("product", "domain", "constraints", "environments"):
            (self.root / f"docs/context/{f}.md").parent.mkdir(parents=True, exist_ok=True)
            (self.root / f"docs/context/{f}.md").write_text(f"# {f}\n")
        (self.root / "docs/context/gaps.md").write_text("| Id | File | Missing | Owner | Question | Blocking |\n|---|---|---|---|---|---|\n")

    def doctor(self, *a):
        return run(self.root, sys.executable, ".keelokit/bin/doctor.py", *a)


class TierTest(Project):
    n = 0

    def floor(self, *files):
        """The floor for a story that touches `files`."""
        TierTest.n += 1
        sid = f"T-{TierTest.n:03d}"
        touches = ", ".join(f'"{f}"' for f in files)
        (self.root / "backlog/stories").mkdir(parents=True, exist_ok=True)
        (self.root / f"backlog/stories/{sid}-x.md").write_text(
            f'+++\nid = "{sid}"\nepic = "T"\ntitle = "t"\nwave = {TierTest.n}\ndepends_on = []\ntouches = [{touches}]\n'
            'dimensions = ["api"]\n+++\n```gherkin\nScenario: [S1] a\n```\n')
        code, out = self.doctor("--tier", sid)
        self.assertEqual(code, 0, out)
        return out.split("tier floor: ")[1].split(" ")[0]

    def test_docs_only_is_trivial_and_code_is_never_trivial(self):
        self.assertEqual(self.floor("docs/a.md", "README.md"), "trivial")
        self.assertEqual(self.floor("docs/a.md", "apps/web/src/Home.tsx"), "light")
        self.assertEqual(self.floor("apps/web/src/Home.test.tsx"), "light")

    def test_the_dangerous_list_and_the_unknown_go_up(self):
        self.assertEqual(self.floor("apps/api/src/billing/charge.ts"), "full")
        self.assertEqual(self.floor("apps/api/src/orders/create.dto.ts"), "full")
        self.assertEqual(self.floor("docs/a.md", "some/new/thing.bin"), "full")  # no rule knows it: up, never down

    def test_a_tiny_diff_in_a_dangerous_file_is_still_full(self):
        self.assertEqual(self.floor("packages/shared/src/index.ts"), "full")

    def test_a_folder_in_touches_counts_as_its_files(self):
        self.assertEqual(self.floor("apps/api/src/payments/"), "full")

    def test_a_story_without_touches_has_no_floor_yet(self):
        self.assertIn("declares no `touches`", self.floor_raw_no_touches())

    def floor_raw_no_touches(self):
        (self.root / "backlog/stories").mkdir(parents=True, exist_ok=True)
        (self.root / "backlog/stories/N-001-x.md").write_text(
            '+++\nid = "N-001"\nepic = "N"\ntitle = "t"\nwave = 1\ndepends_on = []\ndimensions = ["api"]\n+++\n```gherkin\nScenario: [S1] a\n```\n')
        return self.doctor("--tier", "N-001")[1]

    def test_the_branch_diff_is_read_too(self):
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=T", "commit", "-q", "--allow-empty", "-m", "init"], cwd=self.root)
        (self.root / "apps/api/src/billing").mkdir(parents=True)
        (self.root / "apps/api/src/billing/a.ts").write_text("x\n")
        code, out = self.doctor("--tier", "--branch")
        self.assertIn("tier floor: full", out)

    def test_extra_arguments_are_refused_like_every_other_mode(self):
        self.assertEqual(self.doctor("--tier")[0], 2)
        self.assertEqual(self.doctor("--tier", "A-1", "extra")[0], 2)

    def test_without_the_file_the_agent_decides_and_a_bad_min_is_an_error(self):
        (self.root / ".keelokit/risk.toml").unlink()
        self.assertIn("the tier is the agent's call", self.doctor("--tier", "--branch")[1])
        (self.root / ".keelokit/risk.toml").write_text('[[rule]]\npaths = ["**"]\nmin = "tiny"\n')
        code, out = self.doctor()
        self.assertEqual(code, 1)
        self.assertIn("min = 'tiny'", out)


class ReviewTest(Project):
    def review(self, *a, stdin=None):
        return run(self.root, sys.executable, ".keelokit/bin/review.py", *a, stdin=stdin)

    def test_the_third_round_is_refused_unless_a_blocking_item_is_open(self):
        self.assertEqual(self.review("round", "AUTH-1")[0], 0)
        self.assertEqual(self.review("round", "AUTH-1")[0], 0)
        code, out = self.review("round", "AUTH-1")
        self.assertEqual(code, 1)
        self.assertIn("NON-BLOCKING", out)
        self.assertEqual(self.review("round", "AUTH-1", "--blocking-open")[0], 0)
        self.assertEqual(self.review("rounds", "AUTH-1")[1].strip(), "3")
        self.review("reset", "AUTH-1")
        self.assertEqual(self.review("rounds", "AUTH-1")[1].strip(), "0")

    def test_a_review_must_follow_the_fixed_format(self):
        good = "VERDICT: CHANGES REQUESTED\nBLOCKING  - src/a.ts:12 · double charge · money · lock the row\nNON-BLOCKING - src/b.ts:3 · name · unclear · rename\n"
        self.assertEqual(self.review("lint-review", "-", stdin=good)[0], 0)
        for bad, why in [("looks fine to me\n", "VERDICT"), ("VERDICT: APPROVE\nBLOCKING - a.ts:1 · p · w · f\n", "APPROVE with BLOCKING"),
                         ("VERDICT: CHANGES REQUESTED\nNON-BLOCKING - a.ts:1 · p · w · f\n", "without a BLOCKING"),
                         ("VERDICT: CHANGES REQUESTED\nBLOCKING - no location here\n", "not `BLOCKING")]:
            code, out = self.review("lint-review", "-", stdin=bad)
            self.assertEqual(code, 1, bad)
            self.assertIn(why, out)

    def test_a_final_report_has_at_most_eight_lines_a_hash_and_no_pasted_blocks(self):
        self.assertEqual(self.review("lint-report", "-", stdin="AUTH-3 landed, ad61f68. Tests: 12. Nothing for you.\n")[0], 0)
        self.assertIn("8 lines", self.review("lint-report", "-", stdin="\n".join(f"line {i} ad61f68" for i in range(10)))[1])
        self.assertIn("no commit hash", self.review("lint-report", "-", stdin="done, all good\n")[1])
        self.assertIn("pasted code block", self.review("lint-report", "-", stdin="ad61f68\n```\ncode\n```\n")[1])


class EscapesTest(Project):
    def escapes(self, *a):
        return run(self.root, sys.executable, ".keelokit/bin/escapes.py", *a)

    ARGS = ["add", "--found-by", "bug bash", "--what", "double refund", "--class", "once", "--date", "2026-10-31"]

    def test_an_escape_needs_a_guard_of_its_whole_class(self):
        code, out = self.escapes(*self.ARGS, "--guard", "none")
        self.assertEqual(code, 1)
        self.assertIn("not enough", out)
        self.assertEqual(self.escapes(*self.ARGS, "--guard", "test")[0], 2)  # a guard needs its check
        code, out = self.escapes(*self.ARGS, "--guard", "concurrency", "--check", "race() test in refunds.spec.ts")
        self.assertEqual(code, 0, out)
        row = (self.root / "docs/escapes.md").read_text().splitlines()[-1]
        self.assertTrue(row.startswith("| ESC-001 | 2026-10-31 | bug bash | double refund | once | concurrency: race() test"), row)

    def test_the_doctor_still_reads_the_row_and_a_repeated_class_is_called_out(self):
        self.escapes(*self.ARGS, "--guard", "lint", "--check", "no-restricted-syntax")
        code, out = self.escapes(*self.ARGS, "--guard", "none", "--because", "needs product input", "--owner", "Ana")
        self.assertEqual(code, 0, out)
        self.assertIn("already bitten before (ESC-001)", out)
        self.assertIn("Escapes logged: 2", self.doctor()[1])
        self.assertNotIn("ESC-00", "\n".join(l for l in self.doctor()[1].splitlines() if "ERROR" in l))

    def test_bad_guard_kinds_are_refused(self):
        self.assertEqual(self.escapes(*self.ARGS, "--guard", "hope", "--check", "x")[0], 2)


class FlakyTest(unittest.TestCase):
    SCRIPT = T / ".keelokit/bin/flaky.sh"

    def flaky(self, *a):
        return run(None, "bash", str(self.SCRIPT), *a)

    def test_a_passing_command_is_not_called_fixed(self):
        code, out = self.flaky("-n", "3", "--", "true")
        self.assertEqual(code, 0)
        self.assertIn("no failure in 3 runs", out)

    def test_an_intermittent_failure_is_reproduced_with_its_tail(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        counter = Path(tmp) / "n"
        counter.write_text("0")
        cmd = f"n=$(cat {counter}); echo $((n+1)) > {counter}; [ $((n % 2)) -eq 0 ] || {{ echo boom-$n; exit 1; }}"
        code, out = self.flaky("-n", "4", "--", "bash", "-c", cmd)
        self.assertEqual(code, 1)
        self.assertIn("2 of 4 runs failed", out)
        self.assertIn("boom-1", out)
        self.assertIn("never a longer timeout", out)

    def test_time_zones_are_run_one_by_one_and_options_are_checked(self):
        code, out = self.flaky("-n", "1", "--tz", "UTC Asia/Tokyo", "--", "true")
        self.assertEqual(code, 0)
        self.assertIn("Asia/Tokyo: 0 of 1", out)
        self.assertEqual(self.flaky("-n", "x", "--", "true")[0], 2)
        self.assertEqual(self.flaky("--tz")[0], 2)
        self.assertEqual(self.flaky("-n", "2")[0], 2)  # no command


if __name__ == "__main__":
    unittest.main()
