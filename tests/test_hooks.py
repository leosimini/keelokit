"""Every hook entry point degrades the same way without python3. Run: python3 -m unittest discover -s tests

The hooks run in someone else's shell: Claude Code's (hooks/hooks.json) and git's
(template/.githooks). An entry point that shells out to python3 has to say so in Keelokit's words
when python3 is missing, never end in the shell's bare `python3: not found` (exit 127, which Claude
Code shows as a hook error on every call and git shows unexplained). Claude Code's hooks turn off
and say so, as SessionStart always did; a git hook stops the commit, because a commit mustn't skip
the guard silently. The cases are found, not listed: a new hook that calls python3 is checked too."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHELLS = [s for s in ("/bin/sh", "/bin/bash") if Path(s).exists()]
BLOCK = {"tool_name": "Bash", "tool_input": {"command": "git commit --no-verify -m x"}}


def claude_hooks():
    """(event, command) for every command hook in hooks/hooks.json."""
    data = json.loads((ROOT / "hooks/hooks.json").read_text())
    return [(event, h["command"]) for event, groups in data["hooks"].items()
            for group in groups for h in group["hooks"] if h.get("type") == "command"]


def git_hooks():
    return sorted(p for p in (ROOT / "template/.githooks").iterdir() if p.is_file())


def project(tmp, name="my project's dir"):
    """A project with the template's .keelokit/bin, in a path with spaces and a quote."""
    proj = Path(tmp) / name
    shutil.copytree(ROOT / "template/.keelokit/bin", proj / ".keelokit/bin")
    return proj


def run(argv, proj, path, stdin=""):
    env = {"PATH": path, "HOME": str(proj.parent), "CLAUDE_PROJECT_DIR": str(proj)}
    return subprocess.run(argv, cwd=proj, env=env, input=stdin, capture_output=True, text=True, timeout=60)


class HooksWithoutPython(unittest.TestCase):
    """DX-7: missing python3 is handled in every entry point, not only SessionStart."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.proj = project(self.tmp)
        self.nopy = str(Path(self.tmp) / "empty-bin")  # a PATH where nothing, python3 included, is found
        os.mkdir(self.nopy)

    def assert_explained(self, r, where):
        out = r.stdout + r.stderr
        self.assertNotIn(r.returncode, (126, 127), f"{where}: the shell's own error\n{out}")
        self.assertNotIn(": not found", out, f"{where}: a bare shell error\n{out}")
        self.assertIn("Keelokit", out, where)
        self.assertIn("Python 3.11+", out, where)

    def test_DX_7_claude_hooks_turn_off_and_say_so(self):
        hooks = [(e, c) for e, c in claude_hooks() if "python3" in c]
        self.assertTrue(hooks, "no Claude hook calls python3: this test lost its cases")
        for event, command in hooks:
            for sh in SHELLS:
                with self.subTest(event=event, shell=sh):
                    r = run([sh, "-c", command], self.proj, self.nopy, json.dumps(BLOCK))
                    self.assert_explained(r, f"{event} under {sh}")
                    self.assertEqual(r.returncode, 0, f"{event}: the hooks are off without python3, not failing")

    def test_DX_7_git_hooks_stop_the_commit_and_say_why(self):
        hooks = [p for p in git_hooks() if "python3" in p.read_text()]
        self.assertTrue(hooks, "no git hook calls python3: this test lost its cases")
        for hook in hooks:
            for sh in SHELLS:
                with self.subTest(hook=hook.name, shell=sh):
                    r = run([sh, str(hook)], self.proj, self.nopy)
                    self.assert_explained(r, f"{hook.name} under {sh}")
                    self.assertNotEqual(r.returncode, 0, f"{hook.name}: a commit mustn't skip the guard silently")

    def test_DX_7_with_python3_the_hooks_still_run_the_guard(self):
        """The check in front changes nothing when python3 is there."""
        path = os.environ["PATH"]
        for event, command in claude_hooks():
            if event != "PreToolUse":
                continue
            for sh in SHELLS:
                with self.subTest(event=event, shell=sh):
                    r = run([sh, "-c", command], self.proj, path, json.dumps(BLOCK))
                    self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                    r = run([sh, "-c", command], self.proj, path,
                            json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}}))
                    self.assertEqual((r.returncode, r.stdout), (0, ""), r.stderr)
        subprocess.run(["git", "init", "-q", str(self.proj)], check=True)
        # pre-push runs the verify after its python3 check: a pnpm that passes stands in for it here.
        stub = Path(self.tmp) / "stub-bin"
        stub.mkdir()
        (stub / "pnpm").write_text("#!/bin/sh\nexit 0\n")
        (stub / "pnpm").chmod(0o755)
        for hook in git_hooks():
            if "python3" in hook.read_text():
                with self.subTest(hook=hook.name):
                    r = run(["/bin/sh", str(hook)], self.proj, f"{stub}{os.pathsep}{path}")
                    self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_DX_7_a_project_without_keelokit_is_left_alone(self):
        """No .keelokit/bin: the Claude hooks say nothing, python3 or not."""
        other = Path(self.tmp) / "other"
        other.mkdir()
        for event, command in claude_hooks():
            for path in (self.nopy, os.environ["PATH"]):
                with self.subTest(event=event, path=path):
                    r = run(["/bin/sh", "-c", command], other, path, json.dumps(BLOCK))
                    self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))


SESSION_LOG = "calls.log"
STUB = """import sys
from pathlib import Path
with open(Path(__file__).resolve().parents[2] / "calls.log", "a") as f:
    f.write(" ".join([Path(__file__).name, *sys.argv[1:]]) + "\\n")
"""


def session_start():
    """The SessionStart command hook entries of hooks/hooks.json."""
    data = json.loads((ROOT / "hooks/hooks.json").read_text())
    return [h for group in data["hooks"]["SessionStart"] for h in group["hooks"] if h.get("type") == "command"]


class SessionStartHook:
    """A project with stub scripts in .keelokit/bin, and the SessionStart command run in it."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.proj = Path(self.tmp) / "my project's dir"
        (self.proj / ".keelokit/bin").mkdir(parents=True)
        self.path = os.environ["PATH"]

    def stub(self, name, extra=""):
        (self.proj / ".keelokit/bin" / name).write_text(STUB + extra)

    def calls(self):
        log = self.proj / SESSION_LOG
        return log.read_text().splitlines() if log.exists() else []

    def hook(self, path=None, sh="/bin/sh"):
        hooks = session_start()
        self.assertEqual(len(hooks), 1, "one SessionStart command runs both, in order")
        return run([sh, "-c", hooks[0]["command"]], self.proj, path or self.path)


class SessionStartCompletesHistory(SessionStartHook, unittest.TestCase):
    """LEDGER-002.S6: ledger.py history --ensure runs before doctor.py --brief, each guarded."""

    def test_LEDGER_002_S6_session_start_runs_ledger_history_before_the_doctor(self):
        self.stub("ledger.py")
        self.stub("doctor.py")
        for sh in SHELLS:
            with self.subTest(shell=sh):
                (self.proj / SESSION_LOG).unlink(missing_ok=True)
                r = self.hook(sh=sh)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertEqual(self.calls(), ["ledger.py history --ensure", "ledger.py", "doctor.py --brief"])

    def test_LEDGER_002_S6_the_hook_timeout_is_history_seconds_plus_10(self):
        hooks = session_start()
        self.assertEqual([h.get("timeout") for h in hooks], [20 + 10],
                         "[ledger] history_seconds (default and maximum 20) + 10 for the doctor")

    def test_LEDGER_002_S6_without_python3_one_keelokit_line_and_exit_0(self):
        self.stub("ledger.py")
        self.stub("doctor.py")
        nopy = Path(self.tmp) / "empty-bin"
        nopy.mkdir()
        for sh in SHELLS:
            with self.subTest(shell=sh):
                r = self.hook(str(nopy), sh)
                lines = [l for l in (r.stdout + r.stderr).splitlines() if l.strip()]
                self.assertEqual(r.returncode, 0, lines)
                self.assertEqual(len(lines), 1, lines)
                self.assertIn("Keelokit", lines[0])
                self.assertIn("Python 3.11+", lines[0])
                self.assertEqual(self.calls(), [])

    def test_LEDGER_002_S6_without_ledger_py_the_doctor_still_runs(self):
        self.stub("doctor.py")
        r = self.hook()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.calls(), ["doctor.py --brief"])
        self.assertNotIn("ledger.py", r.stdout + r.stderr, "a missing ledger.py is not an error")

    def test_LEDGER_002_S6_without_doctor_py_the_ledger_still_runs(self):
        self.stub("ledger.py")
        r = self.hook()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.calls(), ["ledger.py history --ensure", "ledger.py"])

    def test_LEDGER_002_S6_a_failing_ledger_py_does_not_stop_the_doctor(self):
        for name, extra in (("exit 1", "raise SystemExit(1)\n"), ("crash", "raise RuntimeError('boom')\n")):
            with self.subTest(ledger=name):
                (self.proj / SESSION_LOG).unlink(missing_ok=True)
                self.stub("ledger.py", extra)
                self.stub("doctor.py")
                r = self.hook()
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertEqual(self.calls(), ["ledger.py history --ensure", "ledger.py", "doctor.py --brief"])

    def test_LEDGER_002_S6_ledger_output_reaches_the_session(self):
        """The ledger's one line is on stdout, before the doctor's summary (after LEDGER-007's frame line)."""
        self.stub("ledger.py", "if sys.argv[1:]:\n    print('Keelokit: history completed (7 commits of main) in 0.4s')\n")
        self.stub("doctor.py", "print('Keelokit: doctor')\n")
        out = self.hook().stdout.splitlines()
        self.assertEqual(out[1], "Keelokit: history completed (7 commits of main) in 0.4s")
        self.assertEqual(out[-1], "Keelokit: doctor")

    def test_LEDGER_002_S6_a_project_without_keelokit_bin_is_left_alone(self):
        other = Path(self.tmp) / "other"
        other.mkdir()
        hooks = session_start()
        for path in (self.path, str(Path(self.tmp))):
            with self.subTest(path=path):
                r = run(["/bin/sh", "-c", hooks[0]["command"]], other, path)
                self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))


class SessionStartShowsWhereTheTruthIs(SessionStartHook, unittest.TestCase):
    """LEDGER-007: after the history, the ledger's summary and one line of where to look, then the doctor;
    at most 12 lines, under a first line that frames them as data."""

    LEDGER = ("if sys.argv[1:] == ['history', '--ensure']:\n"
              "    print('Keelokit: history completed (7 commits of main) in 0.4s')\n"
              "elif sys.argv[1:] == []:\n"
              "    print('\\n'.join(f'summary {i}' for i in range({n})))\n")

    def stubs(self, summary=3, doctor=4):
        self.stub("ledger.py", self.LEDGER.replace("{n}", str(summary)))
        self.stub("doctor.py", f"print('\\n'.join(f'doctor {{i}}' for i in range({doctor})))\n")

    def lines(self, r):
        return r.stdout.splitlines()

    def test_LEDGER_007_S1_history_then_summary_then_map_then_doctor(self):
        self.stubs()
        for sh in SHELLS:
            with self.subTest(shell=sh):
                (self.proj / SESSION_LOG).unlink(missing_ok=True)
                r = self.hook(sh=sh)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertEqual(self.calls(), ["ledger.py history --ensure", "ledger.py", "doctor.py --brief"])
                out = self.lines(r)
                self.assertEqual(out[1:5], ["Keelokit: history completed (7 commits of main) in 0.4s",
                                            "summary 0", "summary 1", "summary 2"])
                self.assertTrue(out[5].startswith("Where to look:"), out)
                self.assertEqual(out[6:], ["doctor 0", "doctor 1", "doctor 2", "doctor 3"])

    def test_LEDGER_007_S1_the_first_line_frames_the_output_as_data(self):
        self.stubs()
        first = self.lines(self.hook())[0]
        self.assertTrue(first.startswith("Keelokit"), first)
        self.assertIn("data, not instructions", first)

    def test_LEDGER_007_S1_the_map_names_where_to_ask_the_rest(self):
        self.stubs()
        where = [l for l in self.lines(self.hook()) if l.startswith("Where to look:")]
        self.assertEqual(len(where), 1, "one line")
        for ask in ("ledger.py show <ID>", "/harbor:log", "backlog/", "Where the truth is", "agent-brief.md"):
            with self.subTest(ask=ask):
                self.assertIn(ask, where[0])

    def test_LEDGER_007_S1_at_most_12_lines_and_the_doctor_still_speaks(self):
        """The summary can take 10 lines and the doctor 8: the summary gives way, so the map and the doctor's
        first lines (its gate and backlog) are still there."""
        for summary, doctor in ((10, 8), (10, 2), (1, 20), (0, 0)):
            with self.subTest(summary=summary, doctor=doctor):
                self.stubs(summary, doctor)
                r = self.hook()
                out = self.lines(r)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertLessEqual(len(out), 12, out)
                self.assertEqual(sum(l.startswith("Where to look:") for l in out), 1, out)
                self.assertIn("summary 0", out) if summary else None
                for i in range(min(doctor, 2)):
                    self.assertIn(f"doctor {i}", out)

    def test_LEDGER_007_S1_ESC_155_ESC_156_the_doctor_s_whole_brief_survives_a_long_summary(self):
        """The doctor's brief ends with `Harness errors`: a long summary gives way, never the doctor, and says
        that it was cut and how to see the rest."""
        for history in (True, False):
            with self.subTest(history=history):
                self.stubs(summary=10, doctor=5)
                if not history:
                    self.stub("ledger.py", "if sys.argv[1:] == []:\n    print('\\n'.join(f'summary {i}' for i in range(10)))\n")
                out = self.lines(self.hook())
                self.assertLessEqual(len(out), 12, out)
                self.assertEqual(out[-5:], [f"doctor {i}" for i in range(5)])
                cut = [l for l in out if "more" in l and "ledger.py" in l and not l.startswith("Where")]
                self.assertEqual(len(cut), 1, out)
                self.assertNotIn("summary 9", out)

    def test_LEDGER_007_S1_a_summary_that_fits_is_shown_whole(self):
        self.stubs(summary=6, doctor=3)
        out = self.lines(self.hook())
        self.assertEqual([l for l in out if l.startswith("summary")], [f"summary {i}" for i in range(6)])
        self.assertFalse([l for l in out if "more" in l and not l.startswith("Where")], out)

    def test_LEDGER_007_S1_a_failing_summary_says_why_and_the_rest_still_runs(self):
        self.stub("ledger.py", "if sys.argv[1:] == []:\n"
                               "    print('Keelokit: the ledger failed (boom)', file=sys.stderr)\n"
                               "    raise SystemExit(2)\n")
        self.stub("doctor.py", "print('doctor 0')\n")
        r = self.hook()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = self.lines(r)
        self.assertIn("Keelokit: the ledger failed (boom)", out, "the session learns why there is no summary")
        self.assertTrue(any(l.startswith("Where to look:") for l in out), out)
        self.assertEqual(out[-1], "doctor 0")

    def test_LEDGER_007_S1_without_ledger_py_no_map_and_the_doctor_as_before(self):
        self.stub("doctor.py", "print('doctor 0')\n")
        r = self.hook()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.lines(r)[1:], ["doctor 0"])

    def test_LEDGER_007_S1_ESC_157_the_real_ledger_and_doctor_fit(self):
        """The template's own ledger.py and doctor.py, in a small repo: the summary is the ledger's, all of it
        fits in 12 lines and the hook ends well within its timeout."""
        if not shutil.which("git"):
            self.skipTest("git not installed")
        shutil.rmtree(self.proj / ".keelokit/bin")
        shutil.copytree(ROOT / "template/.keelokit/bin", self.proj / ".keelokit/bin")
        story = self.proj / "backlog/stories/DEMO-001-x.md"
        story.parent.mkdir(parents=True)
        story.write_text('+++\nid = "DEMO-001"\nepic = "DEMO"\ntitle = "x"\nwave = 1\ndepends_on = []\n+++\n')
        env = {"PATH": self.path, "HOME": self.tmp, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}  # no inherited GIT_DIR (a git hook's)
        for argv in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "x"]):
            subprocess.run(["git", *argv], cwd=self.proj, env=env, check=True, capture_output=True)
        r = self.hook()
        out = self.lines(r)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertLessEqual(len(out), 12, out)
        self.assertTrue(any(l.startswith("main@") for l in out), out)
        self.assertTrue(any(l.startswith("Where to look:") for l in out), out)

    def test_LEDGER_007_S4_the_start_points_to_show_and_show_answers_done_and_why(self):
        """The automatable half of S4 (the fresh session's answer is the manual half, in the addendum): in a repo
        where a story is done in v1.0.0 and an escape row names it, the session start names `ledger.py show <ID>`,
        and that command answers done, in which version, and why (the commit body and the escape row)."""
        if not shutil.which("git"):
            self.skipTest("git not installed")
        shutil.rmtree(self.proj / ".keelokit/bin")
        shutil.copytree(ROOT / "template/.keelokit/bin", self.proj / ".keelokit/bin")
        story = self.proj / "backlog/stories/DEMO-001-demo.md"
        story.parent.mkdir(parents=True)
        story.write_text('+++\nid = "DEMO-001"\nepic = "DEMO"\ntitle = "Demo"\nwave = 1\ndepends_on = []\n+++\n')
        (self.proj / "docs").mkdir()
        (self.proj / "docs/escapes.md").write_text(
            "# Escapes\n\n| Id | Date | Found by | What escaped | Class | Check added |\n|---|---|---|---|---|---|\n"
            "| ESC-001 | 2026-11-01 | DEMO-001 reviewer | The demo leaked a widget | consistency | tests/x |\n")
        env = {"PATH": self.path, "HOME": self.tmp, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        (self.proj / "f").write_text("x\n")
        for argv in (["init", "-q", "-b", "main"], ["add", "backlog", "docs", ".keelokit"], ["commit", "-q", "-m", "plan"],
                     ["add", "f"], ["commit", "-q", "-m", "DEMO-001: build it\n\nDecided: widgets are blue.\n\n"
                                                         "Story: DEMO-001"], ["tag", "v1.0.0"]):
            subprocess.run(["git", *argv], cwd=self.proj, env=env, check=True, capture_output=True)
        start = self.lines(self.hook())
        self.assertTrue(any("ledger.py show <ID>" in l for l in start), start)
        r = run(["python3", ".keelokit/bin/ledger.py", "show", "DEMO-001"], self.proj, self.path)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("state: in-version", r.stdout)
        self.assertIn("version: v1.0.0", r.stdout)
        self.assertIn("Decided: widgets are blue.", r.stdout, "the why: the Story: commit's body")
        self.assertIn("ESC-001", r.stdout, "the why: the escape row that names the story")
        self.assertIn("The demo leaked a widget", r.stdout)

    def test_LEDGER_007_S2_without_python3_one_line_and_exit_0(self):
        self.stubs()
        nopy = Path(self.tmp) / "empty-bin"
        nopy.mkdir()
        for sh in SHELLS:
            with self.subTest(shell=sh):
                r = self.hook(str(nopy), sh)
                lines = [l for l in (r.stdout + r.stderr).splitlines() if l.strip()]
                self.assertEqual((r.returncode, len(lines)), (0, 1), lines)
                self.assertIn("Python 3.11+", lines[0])
                self.assertEqual(self.calls(), [])


if __name__ == "__main__":
    unittest.main()
