"""LEDGER-004.S3: the guard keeps agents off the ledger's corrections. Run: python3 -m unittest discover -s tests

In a file of its own: tests/test_guard.py holds secret-shaped fixtures that the guard's whole-file SEC-1 scan
refuses, so a commit that touches it cannot pass the pre-commit hook until a person registers it (ESC-091)."""
import subprocess
from pathlib import Path
import unittest

import test_guard
from test_guard import sh


CORRECTIONS = "backlog/ledger-corrections.toml"
PROPOSED = ".keelokit/ledger-corrections.proposed.toml"
CORRECTIONS_HEADER = "# Ledger corrections: append-only, the human's (QA-4).\n"
CORRECTION_ROW = ('\n[[row]]\nstory = "UXC-113"\ncommit = "' + "a" * 40 + '"\nkind = "backfill"\n'
                  'evidence = "train sheet 18"\napprover = "Leo"\ndate = "2026-11-25"\n')


class GuardCorrectionsTest(unittest.TestCase):
    """LEDGER-004.S3: backlog/ledger-corrections.toml is the human's, like guard-allow.toml (QA-4): the Claude
    hook blocks every write to it and every `ledger.py backfill --accept`, and a commit that changes it needs
    keelokit.allowTamper. The proposed file is the agents' to write. INV-002: the guard only blocks (2) or
    lets through (0), whatever the command."""

    setUp = test_guard.GuardTest.setUp
    tearDown = test_guard.GuardTest.tearDown
    env = test_guard.GuardRegistryTest.env
    run_claude = test_guard.GuardRegistryTest.run_claude
    claude = test_guard.GuardRegistryTest.claude
    bash = test_guard.GuardRegistryTest.bash
    stage = test_guard.GuardRegistryTest.stage
    run_pre_commit = test_guard.GuardRegistryTest.run_pre_commit
    pre_commit = test_guard.GuardRegistryTest.pre_commit

    def assert_blocked(self, run: subprocess.CompletedProcess, *words: str) -> None:
        self.assertNotIn("Traceback", run.stderr)
        self.assertEqual(run.returncode, 2, run.stderr)
        for word in words:
            self.assertIn(word, run.stderr)

    def commit_file(self, text: str) -> None:
        """The human's commit of the corrections file (no hooks are installed in this repo)."""
        self.stage(CORRECTIONS, text)
        sh(self.repo, "git", "commit", "-qm", "corrections", "--no-verify")

    def test_LEDGER_004_S3_INV_002_the_claude_hook_blocks_every_tool_write_to_the_corrections_file(self):
        self.commit_file(CORRECTIONS_HEADER)
        for path in [CORRECTIONS, str(self.repo / CORRECTIONS)]:
            for tool, extra in [("Write", {"content": CORRECTION_ROW}),
                                ("Edit", {"old_string": "#", "new_string": CORRECTION_ROW}),
                                ("MultiEdit", {"edits": [{"old_string": "#", "new_string": CORRECTION_ROW}]})]:
                with self.subTest(tool=tool, path=path):
                    self.assert_blocked(self.run_claude(tool, file_path=path, **extra), "QA-4")
            with self.subTest(tool="NotebookEdit", path=path):
                self.assert_blocked(self.run_claude("NotebookEdit", notebook_path=path, new_source="x"), "QA-4")

    def test_LEDGER_004_S3_INV_002_the_claude_hook_blocks_every_shell_write_to_the_corrections_file(self):
        f = CORRECTIONS
        for cmd in [f"echo '[[row]]' >> {f}", f"echo x > {f}", f"tee {f} < x", f"tee -a {f} < x", f"cp /tmp/x {f}",
                    f"mv /tmp/x {f}", f"sed -i 's/a/b/' {f}", f"rm {f}", f"rm -f {f}", f"truncate -s 0 {f}",
                    f"touch {f}", f"ln -sf /tmp/x {f}", f"perl -pi -e 's/a/b/' {f}", f"dd if=/tmp/x of={f}",
                    f"cat x > {self.repo / f}", f'cp x "{f}"', f"echo a > '{f}'", f'printf "%s" x >> "{self.repo / f}"',
                    f"cd backlog && ls && cp /tmp/x {f}", f"git status && cat x >> {f}"]:
            with self.subTest(cmd=cmd):
                self.assert_blocked(self.run_claude("Bash", command=cmd), "QA-4")

    def test_LEDGER_004_S3_INV_002_reads_of_the_corrections_file_pass(self):
        self.commit_file(CORRECTIONS_HEADER)
        for cmd in [f"cat {CORRECTIONS}", f"grep UXC {CORRECTIONS}", f"git diff {CORRECTIONS}",
                    f"git log -p -- {CORRECTIONS}", f"cat '{CORRECTIONS}'"]:
            with self.subTest(cmd=cmd):
                self.assertEqual(self.bash(cmd), 0)

    def test_LEDGER_004_S3_INV_002_the_proposed_file_is_writable(self):
        self.assertEqual(self.claude("Write", file_path=str(self.repo / PROPOSED), content=CORRECTION_ROW), 0)
        self.assertEqual(self.claude("Write", file_path=PROPOSED, content=CORRECTION_ROW), 0)
        self.assertEqual(self.claude("Edit", file_path=PROPOSED, old_string="a", new_string="b"), 0)
        for cmd in [f"echo x > {PROPOSED}", f"rm -f {PROPOSED}", f"cat {PROPOSED}"]:
            with self.subTest(cmd=cmd):
                self.assertEqual(self.bash(cmd), 0)

    def test_LEDGER_004_S3_INV_002_backfill_accept_is_blocked_in_every_form(self):
        for cmd in ["python3 .keelokit/bin/ledger.py backfill --accept",
                    ".keelokit/bin/ledger.py backfill --accept",
                    "./.keelokit/bin/ledger.py backfill --accept",
                    "ledger.py backfill --accept",
                    'python3 "$CLAUDE_PROJECT_DIR/.keelokit/bin/ledger.py" backfill --accept',
                    "python3 $CLAUDE_PROJECT_DIR/.keelokit/bin/ledger.py backfill --accept",
                    f"python3 {self.repo}/.keelokit/bin/ledger.py backfill --accept",
                    "python3 '.keelokit/bin/ledger.py' 'backfill' '--accept'",
                    'python3 .keelokit/bin/ledger.py "backfill" "--accept"',
                    'bash -c "python3 .keelokit/bin/ledger.py backfill --accept"',
                    "git status && python3 .keelokit/bin/ledger.py backfill --accept",
                    "cd .keelokit/bin && python3 ledger.py backfill --accept"]:
            with self.subTest(cmd=cmd):
                self.assert_blocked(self.run_claude("Bash", command=cmd), "backfill --accept")

    def test_LEDGER_004_S3_INV_002_propose_correct_check_and_a_quoted_message_pass(self):
        for cmd in ["python3 .keelokit/bin/ledger.py backfill --propose",
                    "python3 .keelokit/bin/ledger.py backfill --propose --from docs/trains.md --from BOARD.md",
                    'python3 .keelokit/bin/ledger.py correct abc1234 --story UXC-113 --evidence "PR #40"',
                    "python3 .keelokit/bin/ledger.py check", "python3 .keelokit/bin/ledger.py check --json",
                    "python3 .keelokit/bin/ledger.py --json",
                    'git commit -m "ledger.py backfill --accept docs"',
                    "git commit -m 'docs: explain ledger.py backfill --accept'"]:
            with self.subTest(cmd=cmd):
                self.assertEqual(self.bash(cmd), 0)

    def test_LEDGER_004_S3_a_commit_that_changes_the_corrections_file_needs_allow_tamper(self):
        def verdicts() -> tuple[subprocess.CompletedProcess, int]:
            refused = self.run_pre_commit()
            sh(self.repo, "git", "config", "keelokit.allowTamper", "true")
            try:
                allowed = self.pre_commit()
            finally:
                sh(self.repo, "git", "config", "--unset", "keelokit.allowTamper")
            return refused, allowed

        with self.subTest("added with a row"):
            self.stage(CORRECTIONS, CORRECTIONS_HEADER + CORRECTION_ROW)
            refused, allowed = verdicts()
            self.assertNotIn("Traceback", refused.stderr)
            self.assertEqual(refused.returncode, 1)
            self.assertIn("QA-4", refused.stderr)
            self.assertEqual(allowed, 0)
            sh(self.repo, "git", "rm", "-q", "--cached", CORRECTIONS)
        self.commit_file(CORRECTIONS_HEADER)
        with self.subTest("modified"):
            self.stage(CORRECTIONS, CORRECTIONS_HEADER + CORRECTION_ROW)
            refused, allowed = verdicts()
            self.assertEqual(refused.returncode, 1)
            self.assertIn("QA-4", refused.stderr)
            self.assertEqual(allowed, 0)
            sh(self.repo, "git", "commit", "-qm", "row", "--no-verify")
        with self.subTest("deleted"):
            sh(self.repo, "git", "rm", "-q", CORRECTIONS)
            refused, allowed = verdicts()
            self.assertEqual(refused.returncode, 1)
            self.assertIn("QA-4", refused.stderr)
            self.assertEqual(allowed, 0)

    def test_LEDGER_004_S3_an_added_file_with_only_the_header_passes(self):
        """The template's file arrives in a project's first commit: comments, no [[row]]."""
        shipped = Path(__file__).resolve().parents[1] / "template" / CORRECTIONS
        for text in [CORRECTIONS_HEADER, shipped.read_text() if shipped.exists() else CORRECTIONS_HEADER]:
            with self.subTest(text=text[:40]):
                self.stage(CORRECTIONS, text)
                self.assertEqual(self.pre_commit(), 0)
                sh(self.repo, "git", "rm", "-q", "--cached", CORRECTIONS)


    # Review round 1 (ESC-092, ESC-096): what got past the first guard

    def test_LEDGER_004_S3_ESC_092_accept_through_a_pty_wrapper_or_another_shell_is_blocked(self):
        """A segment whose words, quotes removed, hold `ledger.py … backfill … --accept` in order is blocked
        unless it is a git command (a commit message)."""
        for cmd in ['echo y | script -qec "python3 .keelokit/bin/ledger.py backfill --accept" /dev/null',
                    "script -qc 'python3 .keelokit/bin/ledger.py backfill --accept' /dev/null",
                    "unbuffer python3 .keelokit/bin/ledger.py backfill --accept",
                    "tmux new -d 'python3 .keelokit/bin/ledger.py backfill --accept'",
                    "xargs python3 .keelokit/bin/ledger.py <<< 'backfill --accept'",
                    "echo 'python3 .keelokit/bin/ledger.py backfill --accept' | sh"]:
            with self.subTest(cmd=cmd):
                self.assert_blocked(self.run_claude("Bash", command=cmd))

    def test_LEDGER_004_S3_ESC_092_a_commit_message_propose_and_a_grep_still_pass(self):
        for cmd in ['git commit -m "docs: ledger.py backfill --accept needs a person"',
                    "python3 .keelokit/bin/ledger.py backfill --propose",
                    "grep -n accept .keelokit/bin/ledger.py"]:
            with self.subTest(cmd=cmd):
                self.assertEqual(self.bash(cmd), 0)

    def test_LEDGER_004_S3_ESC_096_every_segment_naming_the_file_that_is_no_read_is_blocked(self):
        f = CORRECTIONS
        for cmd in [f"git checkout feat -- {f}", f"git restore --source=feat {f}",
                    f"python3 -c \"open('{f}','a').write('x')\"", f"install -m644 /tmp/x {f}",
                    "echo x >> backlog/Ledger-Corrections.toml", "cp /tmp/x BACKLOG/LEDGER-CORRECTIONS.TOML"]:
            with self.subTest(cmd=cmd):
                self.assert_blocked(self.run_claude("Bash", command=cmd), "QA-4")

    def test_LEDGER_004_S3_ESC_096_a_write_tool_on_the_file_in_another_case_is_blocked(self):
        for path in ["backlog/Ledger-Corrections.toml", str(self.repo / "backlog/LEDGER-corrections.toml")]:
            with self.subTest(path=path):
                self.assert_blocked(self.run_claude("Write", file_path=path, content=CORRECTION_ROW), "QA-4")

    def test_LEDGER_004_S3_ESC_096_reads_still_pass(self):
        self.commit_file(CORRECTIONS_HEADER)
        f = CORRECTIONS
        for cmd in [f"cat {f}", f"grep -n UXC {f}", f"git diff {f}", f"git log -p -- {f}", f"head -5 {f}",
                    f"wc -l {f}", f"git show HEAD:{f}", f"git blame {f}", f"ls -l {f}"]:
            with self.subTest(cmd=cmd):
                self.assertEqual(self.bash(cmd), 0)


    # Review round 2 (ESC-097): the rule must not block a read, a mention or another file

    def test_LEDGER_004_S3_ESC_097_mentions_reads_and_other_files_pass(self):
        f = CORRECTIONS
        for cmd in [f'git commit -m "fix(guard): protect {f}"', "git add template/backlog/ledger-corrections.toml",
                    f"git add {f}", f"cat {f} 2>/dev/null", f"git show HEAD:{f} 2>/dev/null", f"grep -c row {f} 2>&1",
                    f"sed -n 1,40p {f}", f"awk '{{print}}' {f}", "find . -name ledger-corrections.toml",
                    "cp template/backlog/ledger-corrections.toml /tmp/x",
                    "sed -i 's/ledger-corrections.toml/x/' docs/design.md",
                    'echo "run python3 .keelokit/bin/ledger.py backfill --accept yourself"',
                    'gh pr comment 12 --body "a person runs ledger.py backfill --accept"']:
            with self.subTest(cmd=cmd):
                run = self.run_claude("Bash", command=cmd)
                self.assertNotIn("Traceback", run.stderr)
                self.assertEqual(run.returncode, 0, run.stderr)

    def test_LEDGER_004_S3_ESC_097_INV_002_writes_and_the_accept_are_still_blocked(self):
        f = CORRECTIONS
        accept = [("echo 'python3 .keelokit/bin/ledger.py backfill --accept' | sh", "backfill --accept"),
                  ('echo y | script -qec "python3 .keelokit/bin/ledger.py backfill --accept" /dev/null',
                   "backfill --accept")]
        writes = [f"cat x > {f}", f"cat x 2>/dev/null > {f}", f"git checkout feat -- {f}",
                  f"git restore --source=feat {f}", f"python3 -c \"open('{f}','a').write('x')\"",
                  f"install -m644 /tmp/x {f}", f"git diff --output={f} HEAD~1", f"cp /tmp/x {f}"]
        for cmd, word in accept + [(w, "QA-4") for w in writes]:
            with self.subTest(cmd=cmd):
                self.assert_blocked(self.run_claude("Bash", command=cmd), word)


if __name__ == "__main__":
    unittest.main()
