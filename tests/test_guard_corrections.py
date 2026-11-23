"""LEDGER-004.S3: the guard keeps agents off the ledger's corrections; LEDGER-015: the approval mode and the
delegated accept (GuardApprovalModeTest). Run: python3 -m unittest discover -s tests

In a file of its own: tests/test_guard.py holds secret-shaped fixtures that the guard's whole-file SEC-1 scan
refuses, so a commit that touches it cannot pass the pre-commit hook until a person registers it (ESC-091)."""
import json
import os
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


# ── LEDGER-015: the approval mode is the person's (S1, D2); the delegated accept's gate (D7, D8) ──

STATE = ".keelokit/state.toml"
REVIEW = ".keelokit/ledger-reviews/r1.json"
ACCEPT_DELEGATED = "python3 .keelokit/bin/ledger.py backfill --accept --delegated r1"
SHA = "a" * 40
DELEGATED_ROW = ('\n[[row]]\nstory = "UXC-113"\ncommit = "' + SHA + '"\nkind = "backfill"\n'
                 'evidence = "train sheet 18"\napprover = "delegated:r1"\ndate = "2026-11-25"\n')


def approval_toml(mode: str | None) -> str:
    return '[ledger]\ntrunk = "main"\n' + (f'\n[ledger.approval]\nmode = "{mode}"\n' if mode else "")


def review_json(decision: str | None = "approved", b: str | None = "yes", skeptic: bool = True, run: str = "r1",
                mode: str | None = "delegated", kind: str = "backfill", critical: bool = False,
                confidence: str = "medium", model: str | None = None) -> str:
    """A review file of run `run` with one row for DELEGATED_ROW; `mode` is the recorded mode (None leaves it out)."""
    m = {"model": model} if model else {}
    row = {"story": "UXC-113", "commit": SHA, "kind": kind, "evidence": "train sheet 18", "confidence": confidence,
           "critical": critical, "title": "t", "path": "backlog/stories/UXC-113-a.md",
           "judge_a": {"verdict": "yes", "reason": "S1 in apps/api/a.ts", **m},
           "skeptic": {"refuted": False, "reason": "no revert, in scope", **m} if skeptic else None}
    if b is not None:
        row["judge_b"] = {"verdict": b, "reason": "the diff does S1", **m}
    if decision is not None:
        row["decision"] = decision
    data = {"schema": 1, "run": run, "rows": [row], "dropped": []}
    if mode is not None:
        data["mode"] = mode
        if mode == "mixed":
            data["human_for"] = ["critical", "disagreement", "low-confidence"]
    return json.dumps(data)


def branch(repo: Path, name: str, state: str) -> None:
    """A local branch `name` off HEAD whose committed .keelokit/state.toml is `state`; the work tree is left as it was."""
    for cmd in (["git", "checkout", "-q", "-b", name], None, ["git", "add", "-f", STATE],
                ["git", "commit", "-qm", f"state on {name}", "--no-verify", "--allow-empty"], ["git", "checkout", "-q", "-"]):
        if cmd is None:
            (repo / STATE).write_text(state)
            continue
        run = sh(repo, *cmd)
        assert run.returncode == 0, f"fixture: {' '.join(cmd)}\n{run.stderr}"


class GuardApprovalModeTest(unittest.TestCase):
    """LEDGER-015: [ledger.approval] in .keelokit/state.toml is the person's (S1): the Claude hook blocks a tool edit
    that changes it and any shell write to state.toml, and a commit that changes it needs keelokit.allowTamper. The
    delegated accept passes the hook only in delegated or mixed mode with a complete review file (D7); its rows pass
    the pre-commit hook only when the staged review file approves them (D8). INV-002: exit 0 or 2, nothing else."""

    setUp = test_guard.GuardTest.setUp
    tearDown = test_guard.GuardTest.tearDown
    env = test_guard.GuardRegistryTest.env
    run_claude = test_guard.GuardRegistryTest.run_claude
    claude = test_guard.GuardRegistryTest.claude
    bash = test_guard.GuardRegistryTest.bash
    stage = test_guard.GuardRegistryTest.stage
    run_pre_commit = test_guard.GuardRegistryTest.run_pre_commit
    pre_commit = test_guard.GuardRegistryTest.pre_commit
    assert_blocked = GuardCorrectionsTest.assert_blocked

    def commit_trunk(self, files: dict) -> None:
        """The person's commit on the trunk (no hooks here), with origin/main moved to it as setUp does."""
        for rel, text in files.items():
            self.stage(rel, text)
        sh(self.repo, "git", "commit", "-qm", "harness", "--no-verify")
        sh(self.repo, "git", "update-ref", "refs/remotes/origin/main", "HEAD")

    def assert_passes(self, run: subprocess.CompletedProcess) -> None:
        self.assertNotIn("Traceback", run.stderr)
        self.assertEqual(run.returncode, 0, run.stderr)

    def refused_then_allowed(self) -> None:
        refused = self.run_pre_commit()
        self.assertNotIn("Traceback", refused.stderr)
        self.assertEqual(refused.returncode, 1, refused.stderr)
        self.assertIn("QA-4", refused.stderr)
        self.assertIn("[ledger.approval]", refused.stderr)
        sh(self.repo, "git", "config", "keelokit.allowTamper", "true")
        try:
            self.assertEqual(self.pre_commit(), 0)
        finally:
            sh(self.repo, "git", "config", "--unset", "keelokit.allowTamper")

    # S1 (D2): the Claude hook on the edit tools

    def test_LEDGER_015_S1_INV_002_a_tool_edit_that_enables_delegation_is_blocked_in_every_spelling(self):
        self.commit_trunk({STATE: approval_toml(None)})
        spellings = ['[ledger.approval]\nmode = "delegated"\n',
                     '[ledger]\ntrunk = "main"\napproval = {mode = "delegated"}\n',
                     '[ledger]\ntrunk = "main"\napproval.mode = "delegated"\n',
                     'ledger.approval.mode = "delegated"\n']
        for path in [STATE, str(self.repo / STATE)]:
            for content in spellings:
                with self.subTest(path=path, content=content):
                    self.assert_blocked(self.run_claude("Write", file_path=path, content=content), "QA-4",
                                        "[ledger.approval]")
            with self.subTest(path=path, tool="Edit"):
                self.assert_blocked(self.run_claude("Edit", file_path=path, old_string='trunk = "main"',
                                                    new_string='trunk = "main"\napproval = {mode = "mixed"}'),
                                    "QA-4", "[ledger.approval]")
            with self.subTest(path=path, tool="MultiEdit"):
                edits = [{"old_string": 'trunk = "main"', "new_string": 'trunk = "dev"'},
                         {"old_string": 'trunk = "dev"', "new_string": 'trunk = "main"\napproval.mode = "mixed"'}]
                self.assert_blocked(self.run_claude("MultiEdit", file_path=path, edits=edits), "QA-4",
                                    "[ledger.approval]")

    def test_LEDGER_015_S1_INV_002_removing_or_changing_the_table_is_blocked(self):
        current = approval_toml("mixed") + "sample = 0.05\n"
        self.commit_trunk({STATE: current})
        self.assert_blocked(self.run_claude("Write", file_path=STATE, content=approval_toml(None)), "[ledger.approval]")
        self.assert_blocked(self.run_claude("Edit", file_path=STATE, old_string='mode = "mixed"',
                                            new_string='mode = "human"'), "[ledger.approval]")
        self.assert_blocked(self.run_claude("Edit", file_path=STATE, old_string="sample = 0.05",
                                            new_string="sample = 0.5"), "[ledger.approval]")
        self.assert_blocked(self.run_claude("Edit", file_path=STATE, old_string='"mixed"', new_string='"delegated"',
                                            replace_all=True), "[ledger.approval]")

    def test_LEDGER_015_S1_INV_002_other_edits_of_state_toml_pass(self):
        self.commit_trunk({STATE: approval_toml("mixed") + '\n[run]\nnote = "mixed"\n'})
        current = (self.repo / STATE).read_text()
        self.assert_passes(self.run_claude("Edit", file_path=STATE, old_string='note = "mixed"', new_string='note = "x"'))
        self.assert_passes(self.run_claude("Write", file_path=STATE, content=current + '\n[dashboard]\nlang = "es"\n'))
        self.assert_passes(self.run_claude("Edit", file_path=str(self.repo / STATE), old_string='trunk = "main"',
                                           new_string='trunk = "main"\nstale_days = 9'))

    # S1 (D2): the Claude hook on the shell

    def test_LEDGER_015_S1_INV_002_every_shell_write_to_state_toml_is_blocked(self):
        f = STATE
        for cmd in [f"echo '[ledger.approval]' >> {f}", f"echo x > {f}", f"tee -a {f} < x", f"cp /tmp/x {f}",
                    f"mv /tmp/x {f}", f"sed -i 's/human/delegated/' {f}", f"perl -pi -e 's/a/b/' {f}", f"rm -f {f}",
                    f"truncate -s 0 {f}", f"touch {f}", f"dd if=/tmp/x of={f}", f"ln -sf /tmp/x {f}",
                    f"install -m644 /tmp/x {f}", f"git checkout feat -- {f}", f"git restore --source=feat {f}",
                    f"git diff --output={f} HEAD~1", f"python3 -c \"open('{f}','a').write('x')\"",
                    f'printf "%s" x >> "{self.repo / f}"', "cd .keelokit && echo x >> state.toml"]:
            with self.subTest(cmd=cmd):
                self.assert_blocked(self.run_claude("Bash", command=cmd), "QA-4", "state.toml")

    def test_LEDGER_015_S1_INV_002_reads_of_state_toml_pass(self):
        self.commit_trunk({STATE: approval_toml("mixed")})
        for cmd in [f"cat {STATE}", f"grep mode {STATE}", f"sed -n 1,20p {STATE}", f"git diff {STATE}",
                    f"git log -p -- {STATE}", f"head -5 {STATE}"]:
            with self.subTest(cmd=cmd):
                self.assert_passes(self.run_claude("Bash", command=cmd))

    # S1 (D2): the git pre-commit hook

    def test_LEDGER_015_S1_a_commit_that_changes_the_approval_table_needs_allow_tamper(self):
        with self.subTest("added with the table"):
            self.stage(STATE, approval_toml("delegated"))
            self.refused_then_allowed()
            sh(self.repo, "git", "rm", "-q", "--cached", STATE)
        self.commit_trunk({STATE: approval_toml("mixed")})
        for why, text in {"mode changed": approval_toml("delegated"), "table removed": approval_toml(None),
                          "invalid TOML": "[ledger.approval\n"}.items():
            with self.subTest(why):
                self.stage(STATE, text)
                self.refused_then_allowed()
                sh(self.repo, "git", "reset", "-q", "--", STATE)
        with self.subTest("deleted"):
            rm = sh(self.repo, "git", "rm", "-qf", STATE)
            self.assertEqual(rm.returncode, 0, f"fixture: git rm failed\n{rm.stderr}")
            self.refused_then_allowed()

    def test_LEDGER_015_S1_a_commit_that_leaves_the_table_equal_passes(self):
        with self.subTest("added without the table"):
            self.stage(STATE, approval_toml(None))
            self.assertEqual(self.pre_commit(), 0)
            sh(self.repo, "git", "rm", "-q", "--cached", STATE)
        self.commit_trunk({STATE: approval_toml("mixed")})
        self.stage(STATE, approval_toml("mixed") + '\n[dashboard]\nlang = "es"\n')
        self.assertEqual(self.pre_commit(), 0)

    # D7: the delegated accept's gate in the Claude hook

    def test_LEDGER_015_D7_INV_002_the_delegated_accept_passes_in_delegated_or_mixed_with_a_complete_review(self):
        for mode in ("delegated", "mixed"):
            with self.subTest(mode=mode):
                self.commit_trunk({STATE: approval_toml(mode)})
                (self.repo / REVIEW).parent.mkdir(parents=True, exist_ok=True)
                (self.repo / REVIEW).write_text(review_json(decision=None))
                self.assert_passes(self.run_claude("Bash", command=ACCEPT_DELEGATED))

    def test_LEDGER_015_D7_INV_002_the_delegated_accept_is_blocked_otherwise(self):
        review = self.repo / REVIEW
        review.parent.mkdir(parents=True, exist_ok=True)
        review.write_text(review_json(decision=None))
        with self.subTest("human: no table"):
            self.commit_trunk({STATE: approval_toml(None)})
            self.assert_blocked(self.run_claude("Bash", command=ACCEPT_DELEGATED), "QA-4")
        with self.subTest("delegated only in the work tree"):
            (self.repo / STATE).write_text(approval_toml("delegated"))
            self.assert_blocked(self.run_claude("Bash", command=ACCEPT_DELEGATED), "QA-4")
        self.commit_trunk({STATE: approval_toml("delegated")})
        for why, text in {"no review file": None, "not JSON": "{", "no judge_b": review_json(decision=None, b=None),
                          "both yes and no skeptic": review_json(decision=None, skeptic=False)}.items():
            with self.subTest(why):
                if text is None:
                    review.unlink(missing_ok=True)
                else:
                    review.write_text(text)
                self.assert_blocked(self.run_claude("Bash", command=ACCEPT_DELEGATED), "QA-4")
        review.write_text(review_json(decision=None))
        for cmd in [ACCEPT_DELEGATED + " --force", "python3 .keelokit/bin/ledger.py backfill --accept",
                    "python3 .keelokit/bin/ledger.py backfill --accept --delegated ../ledger-reviews/r1",
                    f"script -qc '{ACCEPT_DELEGATED}' /dev/null", f"echo '{ACCEPT_DELEGATED}' | sh",
                    "xargs python3 .keelokit/bin/ledger.py <<< 'backfill --accept --delegated r1'"]:
            with self.subTest(cmd=cmd):
                self.assert_blocked(self.run_claude("Bash", command=cmd), "QA-4")

    def test_LEDGER_015_S8_INV_002_reject_sample_is_always_blocked(self):
        for mode in (None, "delegated", "mixed"):
            with self.subTest(mode=mode):
                self.commit_trunk({STATE: approval_toml(mode)})
                for cmd in ["python3 .keelokit/bin/ledger.py review --reject-sample r1",
                            "cd .keelokit/bin && python3 ledger.py review --reject-sample r1",
                            "script -qc 'python3 .keelokit/bin/ledger.py review --reject-sample r1' /dev/null"]:
                    with self.subTest(cmd=cmd):
                        self.assert_blocked(self.run_claude("Bash", command=cmd), "QA-4")

    def test_LEDGER_015_S2_INV_002_the_filter_passes(self):
        self.assert_passes(self.run_claude("Bash", command="python3 .keelokit/bin/ledger.py review --filter"))

    # D8: the pre-commit hook lets delegated rows backed by their staged review file through

    def test_LEDGER_015_D8_delegated_rows_with_their_approved_review_commit_without_allow_tamper(self):
        self.commit_trunk({STATE: approval_toml("delegated"), CORRECTIONS: CORRECTIONS_HEADER})
        self.stage(CORRECTIONS, CORRECTIONS_HEADER + DELEGATED_ROW)
        self.stage(REVIEW, review_json())
        run = self.run_pre_commit()
        self.assertNotIn("Traceback", run.stderr)
        self.assertEqual(run.returncode, 0, run.stderr)

    def test_LEDGER_015_D8_any_other_change_of_the_corrections_file_still_needs_allow_tamper(self):
        person = DELEGATED_ROW.replace("delegated:r1", "Leo")
        cases = {"human mode": (None, CORRECTIONS_HEADER + DELEGATED_ROW, review_json()),
                 "no review file staged": ("delegated", CORRECTIONS_HEADER + DELEGATED_ROW, None),
                 "review decision person": ("mixed", CORRECTIONS_HEADER + DELEGATED_ROW, review_json(decision="person")),
                 "judge_b said no": ("delegated", CORRECTIONS_HEADER + DELEGATED_ROW, review_json(b="no")),
                 "review of another run": ("delegated", CORRECTIONS_HEADER + DELEGATED_ROW, review_json(run="r2")),
                 "a person's row appended too": ("delegated", CORRECTIONS_HEADER + DELEGATED_ROW + person, review_json()),
                 "a byte rewritten": ("delegated", "# edited\n" + DELEGATED_ROW, review_json())}
        for why, (mode, corrections, review) in cases.items():
            with self.subTest(why):
                self.commit_trunk({STATE: approval_toml(mode), CORRECTIONS: CORRECTIONS_HEADER})
                sh(self.repo, "git", "rm", "-q", "--cached", "--ignore-unmatch", REVIEW)
                (self.repo / REVIEW).unlink(missing_ok=True)
                self.stage(CORRECTIONS, corrections)
                if review is not None:
                    self.stage(REVIEW, review)
                run = self.run_pre_commit()
                self.assertNotIn("Traceback", run.stderr)
                self.assertEqual(run.returncode, 1, run.stderr)
                self.assertIn("QA-4", run.stderr)
                sh(self.repo, "git", "reset", "-q", "--", CORRECTIONS, REVIEW)



class GuardApprovalRound1Test(unittest.TestCase):
    """LEDGER-015 review round 1 (ESC-110..113, ESC-115, ESC-118): an alias of a protected file, a trunk switch, an
    Edit the guard could not apply, the delegated exception's recorded fields and a foreign ledger.py."""

    setUp = test_guard.GuardTest.setUp
    tearDown = test_guard.GuardTest.tearDown
    env = test_guard.GuardRegistryTest.env
    run_claude = test_guard.GuardRegistryTest.run_claude
    stage = test_guard.GuardRegistryTest.stage
    run_pre_commit = test_guard.GuardRegistryTest.run_pre_commit
    assert_blocked = GuardCorrectionsTest.assert_blocked
    commit_trunk = GuardApprovalModeTest.commit_trunk
    assert_passes = GuardApprovalModeTest.assert_passes

    def test_LEDGER_015_S1_ESC_110_INV_002_a_tool_write_through_a_symlink_is_judged_as_its_target(self):
        self.commit_trunk({STATE: approval_toml(None)})
        for link, target in [("s.toml", STATE), ("s2.toml", CORRECTIONS), ("s3.toml", ".keelokit/guard-allow.toml"),
                             ("k", ".keelokit")]:
            os.symlink(target, self.repo / link)
        for path, content, word in [("s.toml", approval_toml("delegated"), "[ledger.approval]"),
                                    ("k/state.toml", approval_toml("delegated"), "[ledger.approval]"),
                                    ("s2.toml", CORRECTION_ROW, "QA-4"), ("s3.toml", "# x\n", "QA-4")]:
            with self.subTest(path=path):
                self.assert_blocked(self.run_claude("Write", file_path=path, content=content), word)
        with self.subTest("Edit through the link"):
            self.assert_blocked(self.run_claude("Edit", file_path="s.toml", old_string='trunk = "main"',
                                                new_string='trunk = "main"\napproval = {mode = "mixed"}'),
                                "[ledger.approval]")

    def test_LEDGER_015_S1_ESC_111_INV_002_ln_naming_a_protected_file_is_blocked_in_any_form(self):
        for cmd in [f"ln -s {STATE} s.toml", f"ln {STATE} s.toml", f"ln -sf {CORRECTIONS} c.toml",
                    f"ln -s {CORRECTIONS} c.toml", f'ln -s "$PWD/{STATE}" /tmp/s.toml',
                    "cd .keelokit && ln -s state.toml s.toml"]:
            with self.subTest(cmd=cmd):
                self.assert_blocked(self.run_claude("Bash", command=cmd), "QA-4")

    def test_LEDGER_015_S1_ESC_112_INV_002_an_edit_that_moves_the_trunk_to_a_branch_that_delegates_is_blocked(self):
        """G3 (round 2, a contract change of F3): moving the trunk is blocked only when the [ledger.approval] committed
        at the new trunk differs from the current trunk's; the reason names the trunk."""
        self.commit_trunk({STATE: '[run]\nnote = "x"\n'})
        branch(self.repo, "evil", '[ledger.approval]\nmode = "delegated"\n')
        branch(self.repo, "develop", '[run]\nnote = "x"\n')
        self.assert_blocked(self.run_claude("Edit", file_path=STATE, old_string='note = "x"',
                                            new_string='note = "x"\n\n[ledger]\ntrunk = "evil"'), "QA-4", "evil")
        self.assert_blocked(self.run_claude("Write", file_path=STATE, content='[harbor]\ntrunk = "evil"\n'), "evil")
        self.assert_passes(self.run_claude("Write", file_path=STATE,
                                           content='[run]\nnote = "x"\n\n[ledger]\ntrunk = "main"\n'))
        self.assert_passes(self.run_claude("Write", file_path=STATE,
                                           content='[run]\nnote = "x"\n\n[harbor]\ntrunk = "develop"\n'))
        self.commit_trunk({STATE: '[ledger]\ntrunk = "main"\n'})
        self.assert_blocked(self.run_claude("Edit", file_path=STATE, old_string='trunk = "main"',
                                            new_string='trunk = "evil"'), "evil")
        self.assert_passes(self.run_claude("Edit", file_path=STATE, old_string='trunk = "main"',
                                           new_string='trunk = "develop"'))

    def test_LEDGER_015_S1_ESC_113_INV_002_an_edit_whose_old_string_is_not_in_the_file_counts_as_a_change(self):
        self.commit_trunk({STATE: approval_toml("mixed")})
        self.assert_blocked(self.run_claude("Edit", file_path=STATE, old_string="mode = \u201cmixed\u201d",
                                            new_string='mode = "delegated"'), "QA-4")
        self.assert_blocked(self.run_claude("MultiEdit", file_path=STATE, edits=[
            {"old_string": "no such text", "new_string": 'mode = "delegated"'}]), "QA-4")

    def test_LEDGER_015_D7_ESC_118_INV_002_the_delegated_accept_passes_only_for_the_projects_own_ledger_py(self):
        self.commit_trunk({STATE: approval_toml("delegated")})
        (self.repo / REVIEW).parent.mkdir(parents=True, exist_ok=True)
        (self.repo / REVIEW).write_text(review_json(decision=None))
        tail = "backfill --accept --delegated r1"
        for cmd in [f"python3 /tmp/x/ledger.py {tail}", f"python3 ledger.py {tail}", f"python3 scripts/ledger.py {tail}",
                    f"python3 ../other/.keelokit/bin/ledger.py {tail}"]:
            with self.subTest(cmd=cmd):
                self.assert_blocked(self.run_claude("Bash", command=cmd), "QA-4")
        for cmd in [f"python3 .keelokit/bin/ledger.py {tail}", f"./.keelokit/bin/ledger.py {tail}",
                    f"python3 {self.repo}/.keelokit/bin/ledger.py {tail}"]:
            with self.subTest(cmd=cmd):
                self.assert_passes(self.run_claude("Bash", command=cmd))

    def pre_commit_verdict(self, head_mode: str | None, corrections: str, review: str | None) -> int:
        self.commit_trunk({STATE: approval_toml(head_mode), CORRECTIONS: CORRECTIONS_HEADER})
        sh(self.repo, "git", "rm", "-q", "--cached", "--ignore-unmatch", REVIEW)
        (self.repo / REVIEW).unlink(missing_ok=True)
        self.stage(CORRECTIONS, corrections)
        if review is not None:
            self.stage(REVIEW, review)
        run = self.run_pre_commit()
        self.assertNotIn("Traceback", run.stderr)
        sh(self.repo, "git", "reset", "-q", "--", CORRECTIONS, REVIEW)
        return run.returncode

    def test_LEDGER_015_D8_ESC_115_the_delegated_exception_re_decides_from_the_recorded_fields(self):
        row = CORRECTIONS_HEADER + DELEGATED_ROW
        retract = CORRECTIONS_HEADER + DELEGATED_ROW.replace('kind = "backfill"', 'kind = "retract"')
        refused = {"a delegated retract": ("delegated", retract, review_json(kind="retract")),
                   "recorded mode differs from HEAD's": ("delegated", row, review_json(mode="mixed")),
                   "no recorded mode": ("delegated", row, review_json(mode=None)),
                   "mixed, recorded critical": ("mixed", row, review_json(mode="mixed", critical=True)),
                   "mixed, recorded low confidence": ("mixed", row, review_json(mode="mixed", confidence="low")),
                   "delegated, critical without opus": ("delegated", row, review_json(critical=True, model="sonnet"))}
        for why, args in refused.items():
            with self.subTest(why):
                self.assertEqual(self.pre_commit_verdict(*args), 1)
        allowed = {"mixed, clear row": ("mixed", row, review_json(mode="mixed")),
                   "delegated, critical judged by opus": ("delegated", row, review_json(critical=True,
                                                                                        model="claude-opus-4"))}
        for why, args in allowed.items():
            with self.subTest(why):
                self.assertEqual(self.pre_commit_verdict(*args), 0)

    def test_LEDGER_015_D8_a_newly_added_corrections_file_in_delegated_mode(self):
        """F10: HEAD has no corrections file (status A): backed delegated rows pass, unbacked ones are refused."""
        self.commit_trunk({STATE: approval_toml("delegated")})
        for why, review, expected in [("backed", review_json(), 0), ("not backed", None, 1)]:
            with self.subTest(why):
                (self.repo / REVIEW).unlink(missing_ok=True)
                self.stage(CORRECTIONS, CORRECTIONS_HEADER + DELEGATED_ROW)
                if review is not None:
                    self.stage(REVIEW, review)
                run = self.run_pre_commit()
                self.assertNotIn("Traceback", run.stderr)
                self.assertEqual(run.returncode, expected, run.stderr)
                sh(self.repo, "git", "rm", "-q", "--cached", "--ignore-unmatch", CORRECTIONS, REVIEW)


class GuardHardLinkTest(unittest.TestCase):
    """LEDGER-015 review round 2 (ESC-119, G1): hard links and cp's link forms are aliases of a protected file too."""

    setUp = test_guard.GuardTest.setUp
    tearDown = test_guard.GuardTest.tearDown
    env = test_guard.GuardRegistryTest.env
    run_claude = test_guard.GuardRegistryTest.run_claude
    stage = test_guard.GuardRegistryTest.stage
    assert_blocked = GuardCorrectionsTest.assert_blocked
    commit_trunk = GuardApprovalModeTest.commit_trunk
    assert_passes = GuardApprovalModeTest.assert_passes

    def test_LEDGER_015_S1_ESC_119_INV_002_link_and_cp_link_forms_naming_a_protected_file_are_blocked(self):
        for f in (STATE, CORRECTIONS):
            for cmd in [f"link {f} h.toml", f"cp -l {f} h.toml", f"cp --link {f} h.toml", f"cp -s {f} h.toml",
                        f"cp --symbolic-link {f} h.toml", f"cp -al {f} h.toml"]:
                with self.subTest(cmd=cmd):
                    self.assert_blocked(self.run_claude("Bash", command=cmd), "QA-4")

    def test_LEDGER_015_S1_ESC_119_INV_002_a_tool_write_to_a_hard_link_is_judged_as_its_target(self):
        self.commit_trunk({STATE: approval_toml(None), CORRECTIONS: CORRECTIONS_HEADER})
        branch(self.repo, "evil", approval_toml("delegated"))
        os.link(self.repo / STATE, self.repo / "h.toml")
        os.link(self.repo / CORRECTIONS, self.repo / "h2.toml")
        for path in ["h.toml", str(self.repo / "h.toml")]:
            with self.subTest(path=path, what="approval"):
                self.assert_blocked(self.run_claude("Write", file_path=path, content=approval_toml("delegated")),
                                    "[ledger.approval]")
            with self.subTest(path=path, what="trunk"):
                self.assert_blocked(self.run_claude("Edit", file_path=path, old_string='trunk = "main"',
                                                    new_string='trunk = "evil"'), "QA-4")
            with self.subTest(path=path, what="corrections"):
                self.assert_blocked(self.run_claude("Write", file_path=path.replace("h.toml", "h2.toml"),
                                                    content=CORRECTIONS_HEADER + CORRECTION_ROW), "QA-4")
        self.assert_passes(self.run_claude("Edit", file_path="h.toml", old_string='trunk = "main"',
                                           new_string='trunk = "main"\nstale_days = 9'))


if __name__ == "__main__":
    unittest.main()
