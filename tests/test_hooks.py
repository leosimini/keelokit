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
        for hook in git_hooks():
            if "python3" in hook.read_text():
                with self.subTest(hook=hook.name):
                    r = run(["/bin/sh", str(hook)], self.proj, path)
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


if __name__ == "__main__":
    unittest.main()
