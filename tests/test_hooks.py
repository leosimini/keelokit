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


class SessionStartCompletesHistory(unittest.TestCase):
    """LEDGER-002.S6: ledger.py history --ensure runs before doctor.py --brief, each guarded."""

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

    def test_LEDGER_002_S6_session_start_runs_ledger_history_before_the_doctor(self):
        self.stub("ledger.py")
        self.stub("doctor.py")
        for sh in SHELLS:
            with self.subTest(shell=sh):
                (self.proj / SESSION_LOG).unlink(missing_ok=True)
                r = self.hook(sh=sh)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertEqual(self.calls(), ["ledger.py history --ensure", "doctor.py --brief"])

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
        self.assertEqual(self.calls(), ["ledger.py history --ensure"])

    def test_LEDGER_002_S6_a_failing_ledger_py_does_not_stop_the_doctor(self):
        for name, extra in (("exit 1", "raise SystemExit(1)\n"), ("crash", "raise RuntimeError('boom')\n")):
            with self.subTest(ledger=name):
                (self.proj / SESSION_LOG).unlink(missing_ok=True)
                self.stub("ledger.py", extra)
                self.stub("doctor.py")
                r = self.hook()
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertEqual(self.calls(), ["ledger.py history --ensure", "doctor.py --brief"])

    def test_LEDGER_002_S6_ledger_output_reaches_the_session(self):
        """The ledger's one line is on stdout, before the doctor's summary."""
        self.stub("ledger.py", "print('Keelokit: history completed (7 commits of main) in 0.4s')\n")
        self.stub("doctor.py", "print('Keelokit: doctor')\n")
        r = self.hook()
        self.assertEqual(r.stdout.splitlines(),
                         ["Keelokit: history completed (7 commits of main) in 0.4s", "Keelokit: doctor"])

    def test_LEDGER_002_S6_a_project_without_keelokit_bin_is_left_alone(self):
        other = Path(self.tmp) / "other"
        other.mkdir()
        hooks = session_start()
        for path in (self.path, str(Path(self.tmp))):
            with self.subTest(path=path):
                r = run(["/bin/sh", "-c", hooks[0]["command"]], other, path)
                self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))


if __name__ == "__main__":
    unittest.main()
