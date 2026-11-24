"""HARN-009: the first commit of a generated project gets past the project's own guard.

project-new generates the monorepo, runs `pnpm install` (whose `prepare` turns the git hooks on) and
then commits, so the guard's pre-commit (QA-4) reads every file of the template as added. A line it
blocks in the template (a `continue-on-error` set to true in ci.yml did) stops the first commit, and only a
human may allow that. These render the template with copier, turn the hooks on as `prepare` does and
make that commit. They need uv, like copier everywhere in Keelokit (CI's unit job installs it);
without it they fail and say so: a skipped test cites no scenario (TRACE-1).

Run: python3 -m unittest discover -s tests"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COPIER = "copier==9.18.2"  # the version every skill and scripts/test-template.sh run
UV = shutil.which("uv")


VERSION = json.loads((ROOT / ".claude-plugin/plugin.json").read_text())["version"]
ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}  # no inherited GIT_* (ESC-090)


def run(cwd: Path, *cmd: str) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, env=ENV, capture_output=True, text=True, timeout=600)


class FirstCommitTest(unittest.TestCase):
    def generate(self, *data: str, existing: bool = False) -> Path:
        self.assertTrue(UV, "these tests need uv, which runs copier: https://docs.astral.sh/uv/")
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        dest = tmp / "demo"
        dest.mkdir()
        run(dest, "git", "init", "-q", "-b", "main")
        if existing:  # an existing repo that adopts the harness: its own history comes first
            (dest / "README.md").write_text("# legacy\n")
            run(dest, "git", "add", "-A")
            run(dest, "git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "existing")
        args = ["copy", "--vcs-ref", "HEAD", "--defaults", "--data", "project_name=Demo"]
        for d in data:
            args += ["--data", d]
        out = run(tmp, UV, "tool", "run", "--quiet", COPIER, *args, str(ROOT), str(dest))
        self.assertEqual(out.returncode, 0, out.stderr[-2000:])
        return dest

    def first_commit(self, dest: Path, *messages: str) -> subprocess.CompletedProcess:
        """The commit project-new makes: every message is its own -m (paragraph), the trailer last."""
        self.assertEqual(run(dest, "git", "config", "core.hooksPath", ".githooks").returncode, 0)  # what `prepare` runs
        run(dest, "git", "add", "-A")
        args = [a for m in (messages or ("first commit", "No-story: harness")) for a in ("-m", m)]
        return run(dest, "git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", *args)

    def test_HARN_009_S1_the_first_commit_of_a_new_product_passes_the_guard(self):
        dest = self.generate('apps=["api","web","mobile","site"]', "postgis=true")
        out = self.first_commit(dest)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("continue-on-error", (ROOT / "template/.keelokit/bin/guard.py").read_text(),
                      "the guard still blocks continue-on-error: the template must not need it")

    def test_HARN_009_S2_the_commit_that_adopts_the_harness_passes_the_guard(self):
        dest = self.generate("mode=harness", existing=True)
        out = self.first_commit(dest)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)

    def test_LEDGER_009_S8_the_first_commit_project_new_makes_passes_the_guard_and_both_hooks(self):
        dest = self.generate('apps=["api","web"]')
        for name in ("pre-commit", "prepare-commit-msg", "commit-msg"):
            hook = dest / ".githooks" / name
            self.assertTrue(hook.is_file() and os.access(hook, os.X_OK), f"the project has no {name} hook")
        subject = f"chore: skeleton from Keelokit v{VERSION}"
        out = self.first_commit(dest, subject, "No-story: harness")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        msg = run(dest, "git", "log", "-1", "--format=%B").stdout.strip()
        self.assertEqual(msg, f"{subject}\n\nNo-story: harness")

    def test_LEDGER_009_S8_the_same_commit_without_the_trailer_is_refused(self):
        """Proves commit-msg is live in a generated project, which starts in enforce = "block"."""
        dest = self.generate('apps=["api","web"]')
        out = self.first_commit(dest, f"chore: skeleton from Keelokit v{VERSION}")
        self.assertNotEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("Keelokit: UNATTRIBUTED", out.stderr)
        self.assertNotEqual(run(dest, "git", "rev-parse", "-q", "--verify", "HEAD").returncode, 0, "no commit was made")


if __name__ == "__main__":
    unittest.main()
