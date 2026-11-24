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


def run(argv, proj, path, stdin="", plugin=ROOT):
    env = {"PATH": path, "HOME": str(proj.parent), "CLAUDE_PROJECT_DIR": str(proj), "CLAUDE_PLUGIN_ROOT": str(plugin)}
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
        subprocess.run(["git", "init", "-q", str(self.proj)], check=True, env=clean_env(self.tmp), capture_output=True)
        # pre-push runs the verify after its python3 check: a pnpm that passes stands in for it here.
        stub = Path(self.tmp) / "stub-bin"
        stub.mkdir()
        (stub / "pnpm").write_text("#!/bin/sh\nexit 0\n")
        (stub / "pnpm").chmod(0o755)
        # the message hooks take the message file git gives them: an attributed one passes.
        msg = Path(self.tmp) / "COMMIT_EDITMSG"
        for hook in git_hooks():
            if "python3" in hook.read_text():
                with self.subTest(hook=hook.name):
                    msg.write_text("x\n\nNo-story: harness\n")
                    args = [str(msg)] if hook.name in ("commit-msg", "prepare-commit-msg") else []
                    r = run(["/bin/sh", str(hook), *args], self.proj, f"{stub}{os.pathsep}{path}")
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
# A stub stands in for a script both in the project and in the plugin (HARN-004: the hooks run the plugin's copy
# when the project's matches it, with `--root <project>` first), and logs into the project it ran on.
STUB = """import sys
from pathlib import Path
root = Path(__file__).resolve().parents[2]
if sys.argv[1:2] == ["--root"]:
    root = Path(sys.argv[2])
    del sys.argv[1:3]
with open(root / "calls.log", "a") as f:
    f.write(" ".join([Path(__file__).name, *sys.argv[1:]]) + "\\n")
"""


def session_start():
    """The SessionStart command hook entries of hooks/hooks.json."""
    data = json.loads((ROOT / "hooks/hooks.json").read_text())
    return [h for group in data["hooks"]["SessionStart"] for h in group["hooks"] if h.get("type") == "command"]


class SessionStartHook:
    """A project with stub scripts in .keelokit/bin, a plugin whose bundled scripts are the same stubs, and the
    SessionStart command run in the project."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.proj = Path(self.tmp) / "my project's dir"
        (self.proj / ".keelokit/bin").mkdir(parents=True)
        self.path = os.environ["PATH"]
        self.plugin = Path(self.tmp) / "the plugin"
        (self.plugin / "hooks").mkdir(parents=True)
        (self.plugin / "template/.keelokit/bin").mkdir(parents=True)
        shutil.copy(ROOT / "hooks/trusted.py", self.plugin / "hooks/trusted.py")

    def stub(self, name, extra=""):
        for d in (self.proj / ".keelokit/bin", self.plugin / "template/.keelokit/bin"):
            (d / name).write_text(STUB + extra)

    def calls(self):
        log = self.proj / SESSION_LOG
        return log.read_text().splitlines() if log.exists() else []

    def hook(self, path=None, sh="/bin/sh"):
        hooks = session_start()
        self.assertEqual(len(hooks), 1, "one SessionStart command runs both, in order")
        return run([sh, "-c", hooks[0]["command"]], self.proj, path or self.path, plugin=self.plugin)


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
                r = run(["/bin/sh", "-c", hooks[0]["command"]], other, path, plugin=self.plugin)
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
        self.plugin = ROOT
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
        self.plugin = ROOT
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


def clean_env(home, **extra):
    """os.environ without any GIT_* variable (the sandbox's GIT_CONFIG_*, GIT_EDITOR; a hook's GIT_DIR: ESC-090),
    with a fixed identity and HOME in the test's own directory."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({"HOME": str(home), "XDG_CONFIG_HOME": str(Path(home) / ".config"),
                "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_NOSYSTEM": "1"})
    env.pop("CLAUDE_PROJECT_DIR", None)
    env.update(extra)
    return env


STORY = '+++\nid = "{id}"\nepic = "{epic}"\ntitle = "x"\nwave = 1\ndepends_on = []\n+++\n'
CATEGORIES = ("harness", "docs", "release", "deps", "ci")
COAUTHOR = "Co-Authored-By: A <a@a>"


class CommitHooks(unittest.TestCase):
    """LEDGER-009: prepare-commit-msg writes Part-of: from the worktree's story, commit-msg checks the trailers.
    A temp repo with the template's .keelokit/bin and .githooks (as they are at run time), story AUTH-001 on main,
    core.hooksPath = .githooks, and the commits made on a branch `work`."""

    def setUp(self):
        if not shutil.which("git"):
            self.skipTest("git not installed")
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.proj = self.tmp / "my repo"
        shutil.copytree(ROOT / "template/.keelokit/bin", self.proj / ".keelokit/bin")
        self.plugin = ROOT
        shutil.copytree(ROOT / "template/.githooks", self.proj / ".githooks")
        story = self.proj / "backlog/stories/AUTH-001-x.md"
        story.parent.mkdir(parents=True)
        story.write_text(STORY.format(id="AUTH-001", epic="AUTH"))
        self.enforce("block")
        self.git("init", "-q", "-b", "main")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "plan")  # before the hooks are on
        self.git("config", "core.hooksPath", ".githooks")
        self.git("checkout", "-q", "-b", "work")
        self.n = 0

    def env(self, **extra):
        return clean_env(self.tmp, **extra)

    def git(self, *args, cwd=None, check=True, **extra):
        r = subprocess.run(["git", *args], cwd=cwd or self.proj, env=self.env(**extra), capture_output=True,
                           text=True, timeout=120, stdin=subprocess.DEVNULL)
        if check:
            self.assertEqual(r.returncode, 0, f"git {' '.join(args)}\n{r.stdout}{r.stderr}")
        return r

    def enforce(self, level, extra=""):
        (self.proj / ".keelokit/state.toml").write_text(f'[ledger]\nenforce = "{level}"\n{extra}')

    def take(self, sid="AUTH-001", cwd=None):
        self.git("config", "extensions.worktreeConfig", "true", cwd=cwd)
        self.git("config", "--worktree", "keelokit.story", sid, cwd=cwd)

    def head(self, cwd=None):
        return self.git("rev-parse", "HEAD", cwd=cwd).stdout.strip()

    def message(self, cwd=None):
        return self.git("log", "-1", "--format=%B", cwd=cwd).stdout.strip()

    def stage(self, cwd=None):
        self.n += 1
        root = Path(cwd or self.proj)
        (root / "f.txt").write_text(f"change {self.n}\n")
        self.git("add", "f.txt", cwd=cwd)

    def commit(self, message=None, *args, cwd=None, **extra):
        """Stage a trivial change and commit it with `message` (via -F, exactly), or with `args` only."""
        self.stage(cwd)
        argv = ["commit", "-q", *args]
        if message is not None:
            f = self.tmp / f"msg-{self.n}"
            f.write_text(message)
            argv += ["-F", str(f)]
        return self.git(*argv, cwd=cwd, check=False, **extra)

    def last_paragraph(self, cwd=None):
        return self.message(cwd).split("\n\n")[-1].splitlines()

    def assert_refused(self, r, code, before):
        out = r.stdout + r.stderr
        self.assertNotEqual(r.returncode, 0, out)
        self.assertEqual(self.head(), before, "a refused commit leaves HEAD where it was")
        self.assertIn(f"Keelokit: {code}", r.stderr, out)
        last = [l for l in r.stderr.splitlines() if l.strip()][-1]
        self.assertIn("refused", last.lower(), r.stderr)

    def assert_hooks_live(self):
        """The commit-msg and prepare-commit-msg hooks are installed: a commit that passes went through them."""
        for name in ("prepare-commit-msg", "commit-msg"):
            hook = self.proj / ".githooks" / name
            self.assertTrue(hook.is_file() and os.access(hook, os.X_OK), f"{name} is not in .githooks")

    def hook(self, cmd, text, *args, cwd=None):
        """`ledger.py hook <cmd> <file> [args]` run directly; returns (result, the file's text afterwards)."""
        f = self.tmp / "direct-msg"
        f.write_text(text)
        r = subprocess.run(["python3", ".keelokit/bin/ledger.py", "hook", cmd, str(f), *args], cwd=cwd or self.proj,
                           env=self.env(), capture_output=True, text=True, timeout=60)
        return r, f.read_text()

    # S1 ---------------------------------------------------------------------------------------------------

    def test_LEDGER_009_S1_part_of_is_added_from_the_worktree_s_story(self):
        self.take()
        self.stage()
        r = self.git("commit", "-q", "-m", "x", check=False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.message(), "x\n\nPart-of: AUTH-001")
        self.assertNotIn("Keelokit", r.stdout + r.stderr, "a clean commit says nothing")

    def test_LEDGER_009_S1_part_of_joins_the_existing_trailer_paragraph(self):
        self.take()
        r = self.commit(f"x\n\nThe body.\n\n{COAUTHOR}\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.last_paragraph(), [COAUTHOR, "Part-of: AUTH-001"])
        self.assertIn("The body.", self.message())

    def test_LEDGER_009_S1_an_attributed_message_is_left_untouched(self):
        self.assert_hooks_live()
        self.take()
        for text in ("x\n\nNo-story: docs — the readme", "x\n\nThe body.\n\nStory: AUTH-001",
                     f"x\n\nPart-of: AUTH-001\n{COAUTHOR}", f"x\n\nThe body.\n\n{COAUTHOR}\nStory: AUTH-001"):
            with self.subTest(text=text):
                r = self.commit(text + "\n")
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertEqual(self.message(), text)

    def test_LEDGER_009_S1_the_editor_flow_gets_part_of_once_a_subject_is_written(self):
        self.take()
        editor = self.tmp / "editor.sh"
        editor.write_text("#!/bin/sh\nprintf 'from the editor\\n' | cat - \"$1\" > \"$1.new\" && mv \"$1.new\" \"$1\"\n")
        editor.chmod(0o755)
        for args in ((), ("-v",)):  # -v: the diff below the scissors line is in the file the hooks read
            with self.subTest(args=args):
                r = self.commit(None, *args, GIT_EDITOR=str(editor))
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertEqual(self.message(), "from the editor\n\nPart-of: AUTH-001")

    def test_LEDGER_009_S1_an_aborted_editor_commit_stays_aborted(self):
        """The editor leaves only the comments: prepare saw nothing to attribute and must not add Part-of, or the
        aborted commit would be made with `Part-of: AUTH-001` as its message."""
        self.assert_hooks_live()
        self.take()
        before = self.head()
        for level in ("block", "warn"):
            with self.subTest(enforce=level):
                self.enforce(level)
                r = self.commit(None, GIT_EDITOR="true")
                self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertEqual(self.head(), before)

    def ledger_take(self, *args, cwd=None):
        """`ledger.py take <args>`, the supported way to set (or, with --clear, unset) the worktree's story."""
        r = subprocess.run(["python3", ".keelokit/bin/ledger.py", "take", *args], cwd=cwd or self.proj,
                           env=self.env(), capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r

    def worktree_config(self, key, cwd=None):
        r = self.git("config", "--worktree", "--get", key, cwd=cwd, check=False)
        return r.stdout.strip() if r.returncode == 0 else None

    def test_LEDGER_009_S1_the_story_is_worktree_local(self):
        self.ledger_take("AUTH-001")
        other = self.tmp / "other"
        self.git("worktree", "add", "-q", "-b", "other", str(other), "main")
        before = self.head(other)
        r = self.commit("x\n", cwd=other)
        self.assertNotEqual(r.returncode, 0, "the other worktree took no story: nothing attributes it")
        self.assertIn("Keelokit: UNATTRIBUTED", r.stderr)
        self.assertEqual(self.head(other), before)
        r = self.commit("x\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.message(), "x\n\nPart-of: AUTH-001")

    def test_LEDGER_009_S1_ESC_188_a_worktree_added_after_take_does_not_inherit_the_story(self):
        """git 2.43 copies config.worktree into a worktree added later, keelokit.story with it: the hooks must not
        stamp the new worktree's commits with the story another worktree took."""
        self.ledger_take("AUTH-001")
        other = self.tmp / "added after take"
        self.git("worktree", "add", "-q", "-b", "later", str(other), "main")
        before = self.head(other)
        r = self.commit("x\n", cwd=other)
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Keelokit: UNATTRIBUTED", r.stderr)
        self.assertEqual(self.head(other), before)
        r = self.commit("x\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.message(), "x\n\nPart-of: AUTH-001")
        self.assertIsNotNone(self.worktree_config("keelokit.storyGitDir"))
        self.ledger_take("--clear")
        self.assertIsNone(self.worktree_config("keelokit.story"))
        self.assertIsNone(self.worktree_config("keelokit.storyGitDir"), "take --clear unsets it too")

    def test_LEDGER_009_S1_prepare_does_nothing_where_the_contract_says_so(self):
        self.take()
        cases = {
            "fixup": ("fixup! x\n", ()), "squash": ("squash! x\n", ()), "amend": ("amend! x\n", ()),
            "source merge": ("Merge branch 'side'\n", ("merge",)),
            "only comments (the editor is about to open)": ("\n# Please enter the commit message\n#\n", ()),
            "lower-case trailer": ("x\n\npart-of: AUTH-001\n", ("message",)),
        }
        for name, (text, args) in cases.items():
            with self.subTest(name):
                r, after = self.hook("prepare", text, *args)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertEqual(after, text)
        # Dropped: is no attribution (ledger.py check does not count it): prepare adds the taken story's Part-of.
        r, after = self.hook("prepare", "drop(AUTH-001): no\n\nDropped: AUTH-001\n", "message")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(after, "drop(AUTH-001): no\n\nDropped: AUTH-001\nPart-of: AUTH-001\n")
        self.git("config", "--worktree", "keelokit.story", "not an id")
        r, after = self.hook("prepare", "x\n", "message")
        self.assertEqual((r.returncode, after), (0, "x\n"), r.stderr)
        self.git("config", "--worktree", "--unset", "keelokit.story")
        r, after = self.hook("prepare", "x\n")
        self.assertEqual((r.returncode, after), (0, "x\n"), r.stderr)

    def test_LEDGER_009_S1_prepare_appends_part_of_and_always_exits_0(self):
        self.take()
        r, after = self.hook("prepare", "x\n", "message")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(after.strip(), "x\n\nPart-of: AUTH-001")

    # S2 ---------------------------------------------------------------------------------------------------

    def assert_explains(self, err):
        self.assertIn("Keelokit: UNATTRIBUTED", err)
        lines = [l.strip() for l in err.splitlines()]
        for start in ("Part-of: ", "Story: ", "No-story: "):
            with self.subTest(line=start):
                self.assertTrue(any(l.startswith(start) for l in lines), err)
        for cat in CATEGORIES:
            self.assertIn(cat, err)
        self.assertIn("python3 .keelokit/bin/ledger.py take", err)

    def test_LEDGER_009_S2_INV_007_unattributed_commit_is_refused_with_block(self):
        before = self.head()
        r = self.commit("x\n")
        self.assert_refused(r, "UNATTRIBUTED", before)
        self.assert_explains(r.stderr)

    def test_LEDGER_009_S2_a_missing_or_unreadable_state_means_block(self):
        for name, text in (("absent", None), ("not toml", "[ledger\nenforce = \n")):
            with self.subTest(name):
                state = self.proj / ".keelokit/state.toml"
                state.unlink(missing_ok=True)
                if text is not None:
                    state.write_text(text)
                before = self.head()
                self.assert_refused(self.commit("x\n"), "UNATTRIBUTED", before)

    def test_LEDGER_009_S2_with_warn_the_commit_is_made_and_the_same_text_printed(self):
        self.enforce("warn")
        before = self.head()
        r = self.commit("x\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotEqual(self.head(), before, "warn lets the commit through")
        self.assertEqual(self.message(), "x")
        self.assert_explains(r.stderr)
        self.assertIn("git commit --amend", r.stderr)

    def test_LEDGER_009_S2_an_attributed_commit_passes_silently(self):
        self.assert_hooks_live()
        for text in ("x\n\nNo-story: docs — the readme\n", f"x\n\nPart-of: AUTH-001\n{COAUTHOR}\n",
                     "x\n\nNo-story: harness\n"):
            with self.subTest(text=text):
                r = self.commit(text)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertNotIn("Keelokit", r.stdout + r.stderr)

    def test_LEDGER_009_S2_SQUASH_LOST_TRAILERS_for_part_of_in_its_own_paragraph(self):
        before = self.head()
        r = self.commit(f"x\n\nPart-of: AUTH-001\n\n{COAUTHOR}\n")
        self.assert_refused(r, "SQUASH_LOST_TRAILERS", before)
        self.assertNotIn("UNATTRIBUTED", r.stderr, "given instead of UNATTRIBUTED")

    def test_LEDGER_009_S2_SQUASH_LOST_TRAILERS_for_a_lost_story_line(self):
        before = self.head()
        r = self.commit(f"x\n\nThe body.\n\nStory: AUTH-001\n\nPart-of: AUTH-001\n{COAUTHOR}\n")
        self.assert_refused(r, "SQUASH_LOST_TRAILERS", before)
        self.assertIn("AUTH-001", r.stderr)

    # S3 ---------------------------------------------------------------------------------------------------

    def test_LEDGER_009_S3_BAD_CATEGORY_lists_the_default_categories(self):
        for text in ("x\n\nNo-story: misc — tidy\n", f"x\n\nNo-story:\n{COAUTHOR}\n"):
            with self.subTest(text=text):
                before = self.head()
                r = self.commit(text)
                self.assert_refused(r, "BAD_CATEGORY", before)
                for cat in CATEGORIES:
                    self.assertIn(cat, r.stderr)

    def test_LEDGER_009_S3_BAD_CATEGORY_reads_the_configured_list(self):
        self.enforce("block", 'no_story = ["harness", "spike"]\n')
        r = self.commit("x\n\nNo-story: spike — try a thing\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        before = self.head()
        r = self.commit("x\n\nNo-story: docs — the readme\n")
        self.assert_refused(r, "BAD_CATEGORY", before)
        self.assertIn("harness", r.stderr)
        self.assertIn("spike", r.stderr)

    # S4 ---------------------------------------------------------------------------------------------------

    def test_LEDGER_009_S4_INV_005_STORY_NO_BODY_for_a_story_commit_with_only_a_subject(self):
        for text in ("x\n\nStory: AUTH-001\n", f"x\n\nStory: AUTH-001\n{COAUTHOR}\n"):
            with self.subTest(text=text):
                before = self.head()
                self.assert_refused(self.commit(text), "STORY_NO_BODY", before)

    def test_LEDGER_009_S4_a_story_commit_with_a_body_passes(self):
        self.assert_hooks_live()
        r = self.commit(f"x\n\nWhat was built and why.\n\nStory: AUTH-001\n{COAUTHOR}\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Story: AUTH-001", self.message())

    # S5 ---------------------------------------------------------------------------------------------------

    def test_LEDGER_009_S5_UNKNOWN_STORY_names_the_id(self):
        for text, sid in (("x\n\nPart-of: NOPE-9\n", "NOPE-9"), ("x\n\nThe body.\n\nStory: NOPE-9\n", "NOPE-9"),
                          ("x\n\nPart-of: AUTH\n", "AUTH")):
            with self.subTest(text=text):
                before = self.head()
                r = self.commit(text)
                self.assert_refused(r, "UNKNOWN_STORY", before)
                self.assertIn(sid, r.stderr)

    def test_LEDGER_009_S2_a_dropped_only_message_without_a_story_is_unattributed(self):
        """`Dropped:` alone attributes nothing (on the trunk `ledger.py check` would say UNATTRIBUTED)."""
        before = self.head()
        r = self.commit("drop(AUTH-001): no\n\nDropped: AUTH-001\n")
        self.assert_refused(r, "UNATTRIBUTED", before)

    def test_LEDGER_009_S5_an_untracked_story_file_is_not_known(self):
        """Only staged or committed story files count: an untracked one never reaches the trunk `check` reads."""
        (self.proj / "backlog/stories/NEW-003-z.md").write_text(STORY.format(id="NEW-003", epic="NEW"))
        before = self.head()
        r = self.commit("x\n\nPart-of: NEW-003\n")
        self.assert_refused(r, "UNKNOWN_STORY", before)
        self.assertIn("NEW-003", r.stderr)

    def test_LEDGER_009_S4_ESC_191_the_editor_flow_still_needs_a_body(self):
        """git's help comments below what the editor wrote are no body: git strips them (commit.cleanup unset)."""
        self.assert_hooks_live()
        self.git("config", "--unset", "commit.cleanup", check=False)
        editor = self.tmp / "editor-story.sh"
        editor.write_text("#!/bin/sh\nprintf 'feat: x\\n\\nStory: AUTH-001\\n' | cat - \"$1\" > \"$1.new\" "
                          "&& mv \"$1.new\" \"$1\"\n")
        editor.chmod(0o755)
        before = self.head()
        r = self.commit(None, GIT_EDITOR=str(editor))
        self.assert_refused(r, "STORY_NO_BODY", before)

    def test_LEDGER_009_S2_the_source_record_is_removed_and_a_stale_one_changes_nothing(self):
        """prepare-commit-msg records git's source in $(git rev-parse --git-path keelokit-commit-source); commit-msg
        reads and deletes it. A stale record (an editor's "" left behind) does not turn a -m commit into an abort."""
        self.assert_hooks_live()
        record = self.proj / self.git("rev-parse", "--git-path", "keelokit-commit-source").stdout.strip()
        r = self.commit("x\n\nNo-story: docs — y\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(record.exists(), "commit-msg deletes the record")
        record.write_text("")
        before = self.head()
        self.stage()
        r = self.git("commit", "-q", "-m", "#5 fix", check=False)
        self.assert_refused(r, "UNATTRIBUTED", before)
        self.assertFalse(record.exists(), "commit-msg deletes the record after a refusal too")

    def test_LEDGER_009_S2_ESC_192_commit_e_is_read_as_git_stores_it(self):
        """`commit -e -m …` with an editor that leaves the file: git strips its help comments (cleanup unset) though
        the source is `message`; the hook reads what git stores."""
        self.assert_hooks_live()
        self.git("config", "--unset", "commit.cleanup", check=False)
        for args, code in ((("-m", "subj", "-m", "Story: AUTH-001"), "STORY_NO_BODY"),
                           (("-m", "#12 fix", "-m", "why", "-m", "Story: AUTH-001"), "STORY_NO_BODY"),
                           (("-m", "#123 fix", "-m", "Part-of: AUTH-001"), "SQUASH_LOST_TRAILERS")):
            with self.subTest(args=args):
                before = self.head()
                self.stage()
                r = self.git("commit", "-q", "-e", *args, check=False, GIT_EDITOR="true")
                self.assert_refused(r, code, before)
        self.take()
        before = self.head()
        self.stage()
        r = self.git("commit", "-q", "-e", "-m", "#123 fix", check=False, GIT_EDITOR="true")
        self.assertNotEqual(r.returncode, 0, f"git aborts an empty message\n{self.message()!r}")
        self.assertEqual(self.head(), before, "never a commit called `Part-of: AUTH-001`")

    def test_LEDGER_009_S5_a_story_only_in_the_work_tree_is_known(self):
        self.assert_hooks_live()
        new = self.proj / "backlog/stories/NEW-002-y.md"
        new.write_text(STORY.format(id="NEW-002", epic="NEW"))
        self.git("add", str(new))
        r = self.commit("x\n\nPart-of: NEW-002\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    # S6 ---------------------------------------------------------------------------------------------------

    def side_branch(self, conflict=False):
        """side and work each get an attributed commit; with `conflict` both change f.txt."""
        self.git("checkout", "-q", "-b", "side")
        self.assertEqual(self.commit("side\n\nNo-story: docs — x\n").returncode, 0)
        self.git("checkout", "-q", "work")
        name = "f.txt" if conflict else "g.txt"
        (self.proj / name).write_text("work\n")
        self.git("add", name)
        self.assertEqual(self.git("commit", "-q", "-m", "work\n\nNo-story: docs — y", check=False).returncode, 0)

    def test_LEDGER_009_S6_a_merge_commit_without_trailers_passes(self):
        self.assert_hooks_live()
        self.take()  # and prepare does not stamp the merge with Part-of
        self.side_branch()
        r = self.git("merge", "--no-ff", "--no-edit", "side", check=False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(len(self.git("log", "-1", "--format=%P").stdout.split()), 2)
        self.assertNotIn("Part-of:", self.message())

    def test_LEDGER_009_S6_a_conflicted_merge_concluded_with_commit_passes(self):
        self.assert_hooks_live()
        self.side_branch(conflict=True)
        r = self.git("merge", "--no-ff", "--no-edit", "side", check=False)  # both changed f.txt
        self.assertNotEqual(r.returncode, 0, "the merge was meant to conflict")
        (self.proj / "f.txt").write_text("resolved\n")
        self.git("add", "f.txt")
        self.assertTrue((self.proj / ".git/MERGE_HEAD").exists())
        r = self.git("commit", "-q", "--no-edit", check=False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(len(self.git("log", "-1", "--format=%P").stdout.split()), 2)

    def test_LEDGER_009_S6_a_merge_s_trailers_are_still_checked(self):
        self.side_branch()
        before = self.head()
        r = self.git("merge", "--no-ff", "-m", "Merge side\n\nPart-of: NOPE-9", "side", check=False)
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Keelokit: UNKNOWN_STORY", r.stderr)
        self.git("merge", "--abort", check=False)
        self.assertEqual(self.head(), before)

    def test_LEDGER_009_S6_a_fixup_commit_without_trailers_passes(self):
        self.assert_hooks_live()
        self.assertEqual(self.commit("x\n\nNo-story: docs — z\n").returncode, 0)
        r = self.commit(None, "--fixup", "HEAD")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(self.message().startswith("fixup! x"), self.message())
        r = self.commit("squash! x\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_LEDGER_009_S6_a_fixup_s_trailers_are_still_checked(self):
        before = self.head()
        self.assert_refused(self.commit("fixup! x\n\nNo-story: misc — y\n"), "BAD_CATEGORY", before)

    # breaker round 1 ----------------------------------------------------------------------------------------

    def log_trailer(self, key, cwd=None):
        """The values of `key` as git log's %(trailers) reads them in HEAD's stored message."""
        out = self.git("log", "-1", f"--format=%(trailers:key={key},valueonly)", cwd=cwd).stdout
        return [l.strip() for l in out.splitlines() if l.strip()]

    def test_LEDGER_009_S1_ESC_189_a_dashes_line_does_not_hide_part_of(self):
        """interpret-trailers takes a `---` line for a patch divider and writes Part-of above it; git log does not,
        so the stored Part-of would be outside the trailers git (and ledger.py check) reads."""
        self.take()
        self.stage()
        r = self.git("commit", "-q", "-m", "x", "-m", "body\n---\nnotes", check=False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.log_trailer("Part-of"), ["AUTH-001"], self.message())

    def test_LEDGER_009_S2_ESC_189_part_of_above_a_dashes_line_is_not_accepted_unread(self):
        """Without a story taken, `Part-of:` above a `---` line is no trailer for git log: the hook refuses it, or the
        stored message's trailers carry it."""
        before = self.head()
        self.stage()
        r = self.git("commit", "-q", "-m", "x", "-m", "Part-of: AUTH-001\n---\nnotes", check=False)
        if r.returncode == 0:
            self.assertEqual(self.log_trailer("Part-of"), ["AUTH-001"],
                             f"accepted, but git log reads no Part-of:\n{self.message()}")
        else:
            self.assertEqual(self.head(), before)
            self.assertIn("Keelokit: ", r.stderr)

    def test_LEDGER_009_S2_ESC_190_a_hash_line_in_a_dash_m_message_is_kept_and_passes(self):
        """Without the editor git's cleanup is `whitespace`: a `#` line stays in the message, it is no comment."""
        for args, key in ((("-m", "#123 fix", "-m", "Part-of: AUTH-001"), "Part-of"),
                          (("-m", "fix", "-m", "#42 why", "-m", "Story: AUTH-001"), "Story")):
            with self.subTest(args=args):
                self.stage()
                r = self.git("commit", "-q", *args, check=False)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertIn(args[1] if args[1].startswith("#") else args[3], self.message())
                self.assertEqual(self.log_trailer(key), ["AUTH-001"])
        f = self.tmp / "hash-msg"
        f.write_text("#7 from a file\n\nPart-of: AUTH-001\n")
        self.stage()
        r = self.git("commit", "-q", "-F", str(f), check=False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_LEDGER_009_S1_an_aborted_editor_commit_prints_nothing_from_keelokit(self):
        """git's own "Aborting commit due to empty commit message" is enough."""
        self.assert_hooks_live()
        self.take()
        for level in ("block", "warn"):
            with self.subTest(enforce=level):
                self.enforce(level)
                r = self.commit(None, GIT_EDITOR="true")
                self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertNotIn("Keelokit", r.stdout + r.stderr)

    def test_LEDGER_009_S2_ESC_189_ESC_190_the_hook_and_ledger_check_agree(self):
        """On the trunk after `[ledger] since`, a commit the hook accepts has no attribution error in
        `ledger.py check`, and one it refuses (made again with --no-verify) has one: both read the trailers git reads."""
        self.assert_hooks_live()
        self.git("checkout", "-q", "main")
        since = self.head()
        self.enforce("block", f'since = "{since}"\n')
        editor = self.tmp / "editor-agree.sh"
        editor.write_text("#!/bin/sh\nprintf 'from the editor\\n\\nPart-of: AUTH-001\\n' | cat - \"$1\" > \"$1.new\" "
                          "&& mv \"$1.new\" \"$1\"\n")
        editor.chmod(0o755)
        crlf = self.tmp / "crlf-msg"
        crlf.write_bytes(b"x\r\n\r\nThe body.\r\n\r\nPart-of: AUTH-001\r\n")
        corpus = {  # name: (story taken, commit args, extra env)
            "dashes, taken": (True, ("-m", "x", "-m", "body\n---\nnotes"), {}),
            "Part-of above dashes": (False, ("-m", "x", "-m", "Part-of: AUTH-001\n---\nnotes"), {}),
            "dashes in the body, trailer last": (False, ("-m", "x", "-m", "a\n---\nb", "-m", "Part-of: AUTH-001"), {}),
            "hash subject": (False, ("-m", "#123 fix", "-m", "Part-of: AUTH-001"), {}),
            "hash body, Story": (False, ("-m", "fix", "-m", "#42 why", "-m", "Story: AUTH-001"), {}),
            "hash line, nothing else": (False, ("-m", "#5 fix"), {}),
            "editor -v (scissors)": (False, ("-v",), {"GIT_EDITOR": str(editor)}),
            "editor -v, taken": (True, ("-v",), {"GIT_EDITOR": "sh -c 'printf \"subject only\\n\" > \"$1\"' -"}),
            "CRLF": (False, ("-F", str(crlf)), {}),
            "plain, unattributed": (False, ("-m", "x"), {}),
            "Part-of in its own paragraph": (False, ("-m", "x", "-m", "Part-of: AUTH-001", "-m", COAUTHOR), {}),
            # ESC-192: -e with an editor that leaves the file: the source is `message`, but git strips the comments.
            "-e, Story without body": (False, ("-e", "-m", "subj", "-m", "Story: AUTH-001"), {"GIT_EDITOR": "true"}),
            "-e, hash subject, Story": (False, ("-e", "-m", "#12 fix", "-m", "why", "-m", "Story: AUTH-001"),
                                        {"GIT_EDITOR": "true"}),
            "-e, hash subject, Part-of": (False, ("-e", "-m", "#123 fix", "-m", "Part-of: AUTH-001"),
                                          {"GIT_EDITOR": "true"}),
            "-e, body and Story": (False, ("-e", "-m", "subj", "-m", "why", "-m", "Story: AUTH-001"),
                                   {"GIT_EDITOR": "true"}),
            # commit.cleanup = strip drops the `#` line: git stores `Part-of: AUTH-001` alone, one paragraph.
            "cleanup strip, hash subject": (False, ("-c", "commit.cleanup=strip", "-m", "#5 fix", "-m",
                                                    "Part-of: AUTH-001"), {}),
        }
        codes = ("UNATTRIBUTED", "SQUASH_LOST_TRAILERS", "BAD_CATEGORY", "UNKNOWN_STORY", "STORY_NO_BODY")
        for name, (taken, args, extra) in corpus.items():
            opts = args[:2] if args[:1] == ("-c",) else ()  # git options, before `commit`
            args = args[len(opts):]
            with self.subTest(name):
                self.enforce("block", f'since = "{since}"\n')  # the reset below restores the tracked state.toml
                if taken:
                    self.take()
                else:
                    self.git("config", "--worktree", "--unset-all", "keelokit.story", check=False)
                before = self.head()
                self.stage()
                r = self.git(*opts, "commit", "-q", *args, check=False, **extra)
                accepted = r.returncode == 0
                if not accepted:
                    self.assertEqual(self.head(), before)
                    r2 = self.git(*opts, "commit", "-q", "--no-verify", *args, check=False, **extra)
                    self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)
                sha = self.head()
                chk = subprocess.run(["python3", ".keelokit/bin/ledger.py", "check"], cwd=self.proj, env=self.env(),
                                     capture_output=True, text=True, timeout=60)
                mine = [l for l in chk.stdout.splitlines() if len(l.split()) > 2 and l.split()[1] in codes
                        and sha.startswith(l.split()[2])]
                self.assertEqual(accepted, not mine,
                                 f"hook {'accepted' if accepted else 'refused'}: {r.stderr}\ncheck: {mine}\n"
                                 f"stored: {self.message()!r}\n{chk.stdout}{chk.stderr}")
                self.git("reset", "-q", "--hard", before)
                self.git("config", "--worktree", "--unset-all", "keelokit.story", check=False)

class SessionStartTurnsOnTheGitHooks(SessionStartHook, unittest.TestCase):
    """LEDGER-009.S7: a fresh clone with .githooks/ and no core.hooksPath gets it set at the session start."""

    def setUp(self):
        super().setUp()
        if not shutil.which("git"):
            self.skipTest("git not installed")
        self.stub("ledger.py")
        self.stub("doctor.py", "print('doctor 0')\n")

    def git(self, *args, check=True):
        return subprocess.run(["git", *args], cwd=self.proj, env=clean_env(self.tmp), capture_output=True,
                              text=True, check=check, timeout=60)

    def hooks_path(self):
        r = self.git("config", "--get", "core.hooksPath", check=False)
        return r.stdout.strip() if r.returncode == 0 else None

    def repo(self, githooks=True):
        self.git("init", "-q", "-b", "main")
        if githooks:
            (self.proj / ".githooks").mkdir()
            (self.proj / ".githooks/pre-commit").write_text("#!/bin/sh\n")

    def test_LEDGER_009_S7_session_start_sets_core_hooks_path_and_says_so_in_one_line(self):
        for sh in SHELLS:
            with self.subTest(shell=sh):
                self.git("config", "--unset", "core.hooksPath", check=False) if (self.proj / ".git").exists() \
                    else self.repo()
                r = self.hook(sh=sh)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertEqual(self.hooks_path(), ".githooks")
                said = [l for l in (r.stdout + r.stderr).splitlines() if "core.hooksPath" in l]
                self.assertEqual(len(said), 1, r.stdout + r.stderr)
                self.assertTrue(said[0].startswith("Keelokit:"), said)
                self.assertIn("doctor 0", r.stdout, "the rest of the start still runs")

    def test_LEDGER_009_S7_the_line_counts_in_the_12_line_budget(self):
        self.repo()
        self.stub("ledger.py", SessionStartShowsWhereTheTruthIs.LEDGER.replace("{n}", "10"))
        self.stub("doctor.py", "print('\\n'.join(f'doctor {i}' for i in range(8)))\n")
        r = self.hook()
        out = r.stdout.splitlines()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.hooks_path(), ".githooks")
        self.assertLessEqual(len(out), 12, out)
        self.assertEqual(sum("core.hooksPath" in l for l in out), 1, out)
        for i in range(2):
            self.assertIn(f"doctor {i}", out)

    def test_LEDGER_009_S7_a_set_hooks_path_is_left_alone_and_nothing_is_said(self):
        self.repo()
        for value in (".husky", ".githooks", "/somewhere/else"):
            with self.subTest(value=value):
                self.git("config", "core.hooksPath", value)
                r = self.hook()
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertEqual(self.hooks_path(), value)
                self.assertNotIn("core.hooksPath", r.stdout + r.stderr)

    def test_LEDGER_009_S7_no_githooks_or_no_git_repo_means_nothing(self):
        self.repo(githooks=False)
        r = self.hook()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIsNone(self.hooks_path())
        self.assertNotIn("core.hooksPath", r.stdout + r.stderr)
        shutil.rmtree(self.proj / ".git")
        (self.proj / ".githooks").mkdir()
        r = self.hook()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse((self.proj / ".git").exists())
        self.assertNotIn("core.hooksPath", r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
