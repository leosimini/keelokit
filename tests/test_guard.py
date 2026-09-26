"""Guard behaviour: what it blocks and what it must let through. Run: python3 -m unittest discover -s tests"""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

GUARD = Path(__file__).resolve().parents[1] / "template/.keelokit/bin/guard.py"


def sh(cwd: Path, *cmd: str) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


class GuardTest(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        (self.repo / ".keelokit/bin").mkdir(parents=True)
        shutil.copy(GUARD, self.repo / ".keelokit/bin/guard.py")
        sh(self.repo, "git", "init", "-q", "-b", "main")
        sh(self.repo, "git", "config", "user.email", "t@example.com")
        sh(self.repo, "git", "config", "user.name", "T")
        mig = self.repo / "apps/api/prisma/migrations/0001_init/migration.sql"
        mig.parent.mkdir(parents=True)
        mig.write_text("select 1;\n")
        sh(self.repo, "git", "add", "-A")
        sh(self.repo, "git", "commit", "-qm", "init", "--no-verify")
        sh(self.repo, "git", "update-ref", "refs/remotes/origin/main", "HEAD")

    def tearDown(self):
        shutil.rmtree(self.repo)

    def claude(self, tool: str, **tool_input) -> int:
        event = json.dumps({"tool_name": tool, "tool_input": tool_input})
        return subprocess.run(
            ["python3", str(self.repo / ".keelokit/bin/guard.py"), "--claude"],
            input=event, capture_output=True, text=True,
        ).returncode

    def bash(self, command: str) -> int:
        return self.claude("Bash", command=command)

    def test_blocks_hook_bypasses(self):
        for cmd in [
            "git commit -m x --no-verify",
            "git commit -n -m x",
            "git commit -anm x",
            "git -c core.hooksPath=/dev/null commit -m x",
            "git config core.hooksPath /tmp",
            "git push --force origin main",
            "git push -f",
            "git push origin +main",
            "git -c keelokit.allowTamper=true commit -m x",
        ]:
            with self.subTest(cmd=cmd):
                self.assertEqual(self.bash(cmd), 2)

    def test_allows_normal_git(self):
        for cmd in [
            "git commit -m 'docs: explain why --no-verify is banned'",
            "git push --force-with-lease origin feature",
            "git log -n 5",
            "git merge --no-ff feature",
            "grep 'fly deploy' README.md",
            "pnpm test",
        ]:
            with self.subTest(cmd=cmd):
                self.assertEqual(self.bash(cmd), 0)

    def test_deploys(self):
        self.assertEqual(self.bash("fly deploy --config apps/api/fly.production.toml"), 2)
        self.assertEqual(self.bash("fly deploy --config apps/api/fly.production.toml # staging"), 2)
        self.assertEqual(self.bash("npx eas-cli submit -p ios"), 2)
        self.assertEqual(self.bash("flyctl deploy --config apps/api/fly.staging.toml --remote-only"), 0)

    def test_env_files_from_shell(self):
        for cmd in [
            "echo X=1 > apps/api/.env",
            "cat > .env <<EOF",
            "printf 'A=1' >> apps/web/.env.local",
            "tee secrets.env < x",
            "sed -i '' s/a/b/ .env",
        ]:
            with self.subTest(cmd=cmd):
                self.assertEqual(self.bash(cmd), 2)
        self.assertEqual(self.bash("cp apps/api/.env.example apps/api/.env"), 0)
        self.assertEqual(self.bash("cat apps/api/.env.example"), 0)

    def test_applied_migrations(self):
        path = str(self.repo / "apps/api/prisma/migrations/0001_init/migration.sql")
        self.assertEqual(self.claude("Edit", file_path=path, old_string="1", new_string="2"), 2)
        self.assertEqual(self.bash(f"sed -i '' s/1/2/ {path}"), 2)
        new = str(self.repo / "apps/api/prisma/migrations/0002_next/migration.sql")
        self.assertEqual(self.claude("Write", file_path=new, content="select 2;"), 0)

    def test_env_files_from_edit_tools(self):
        for name in [".env", ".env.local", ".envrc", "secrets.env", "prod.env"]:
            with self.subTest(name=name):
                self.assertEqual(self.claude("Write", file_path=str(self.repo / name), content="X=1"), 2)
        self.assertEqual(self.claude("Write", file_path=str(self.repo / ".env.example"), content="X="), 0)

    def test_secrets_in_every_edit_tool(self):
        key = "sk-ant-" + "a" * 40
        target = str(self.repo / "a.ts")
        self.assertEqual(self.claude("Write", file_path=target, content=f"const k = '{key}'"), 2)
        self.assertEqual(self.claude("MultiEdit", file_path=target, edits=[{"old_string": "a", "new_string": key}]), 2)
        self.assertEqual(self.claude("NotebookEdit", notebook_path=str(self.repo / "n.ipynb"), new_source=key), 2)
        for secret in ["github_pat_" + "A" * 50, "AIza" + "B" * 35, "postgres://u:p4ss@db.example.com:5432/x"]:
            with self.subTest(secret=secret[:12]):
                self.assertEqual(self.claude("Write", file_path=target, content=secret), 2)
        self.assertEqual(self.claude("Write", file_path=target, content="postgresql://app:app@localhost:5432/app"), 0)

    def test_tampering(self):
        target = str(self.repo / "a.test.ts")
        for code in ["it.skip('x', () => {})", "test.only('x', () => {})", "xit('x')", "// eslint-disable-next-line", "// @ts-ignore"]:
            with self.subTest(code=code):
                self.assertEqual(self.claude("Edit", file_path=target, old_string="a", new_string=code), 2)
        ci = str(self.repo / ".github/workflows/ci.yml")
        self.assertEqual(self.claude("Write", file_path=ci, content="continue-on-error: true"), 2)
        self.assertEqual(self.claude("Write", file_path=str(self.repo / "docs/x.md"), content="never use it.skip("), 0)

    def pre_commit(self) -> int:
        return sh(self.repo, "python3", ".keelokit/bin/guard.py", "git-pre-commit").returncode

    def test_pre_commit(self):
        (self.repo / "apps/api/.env").write_text("A=1\n")
        sh(self.repo, "git", "add", "-f", "apps/api/.env")
        self.assertEqual(self.pre_commit(), 1)
        sh(self.repo, "git", "rm", "-q", "--cached", "apps/api/.env")

        (self.repo / "a.test.ts").write_text("it.skip('x', () => {})\n")
        sh(self.repo, "git", "add", "a.test.ts")
        self.assertEqual(self.pre_commit(), 1)
        sh(self.repo, "git", "config", "keelokit.allowTamper", "true")
        self.assertEqual(self.pre_commit(), 0)
        sh(self.repo, "git", "config", "--unset", "keelokit.allowTamper")
        sh(self.repo, "git", "rm", "-q", "--cached", "a.test.ts")

        mig = self.repo / "apps/api/prisma/migrations/0001_init/migration.sql"
        mig.write_text("select 2;\n")
        sh(self.repo, "git", "add", str(mig))
        self.assertEqual(self.pre_commit(), 1)


if __name__ == "__main__":
    unittest.main()
