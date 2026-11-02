"""HARN-009: the first commit of a generated project gets past the project's own guard.

project-new generates the monorepo, runs `pnpm install` (whose `prepare` turns the git hooks on) and
then commits, so the guard's pre-commit (QA-4) reads every file of the template as added. A line it
blocks in the template (a `continue-on-error` set to true in ci.yml did) stops the first commit, and only a
human may allow that. These render the template with copier, turn the hooks on as `prepare` does and
make that commit. They need uv (CI's unit job installs it); without it they skip locally.

Run: python3 -m unittest discover -s tests"""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COPIER = "copier==9.18.2"  # the version every skill and scripts/test-template.sh run
UV = shutil.which("uv")


def run(cwd: Path, *cmd: str) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=600)


@unittest.skipUnless(UV, "needs uv to run copier")
class FirstCommitTest(unittest.TestCase):
    def generate(self, *data: str, existing: bool = False) -> Path:
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

    def first_commit(self, dest: Path) -> subprocess.CompletedProcess:
        self.assertEqual(run(dest, "git", "config", "core.hooksPath", ".githooks").returncode, 0)  # what `prepare` runs
        run(dest, "git", "add", "-A")
        return run(dest, "git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "first commit")

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


if __name__ == "__main__":
    unittest.main()
