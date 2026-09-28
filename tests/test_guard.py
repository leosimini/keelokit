"""Guard behaviour: what it blocks and what it must let through. Run: python3 -m unittest discover -s tests"""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

GUARD = Path(__file__).resolve().parents[1] / "template/.keelokit/bin/guard.py"


def sh(cwd: Path, *cmd: str) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def short_options(cwd: Path, sub: str) -> tuple[set[str], set[str]]:
    """(flags that take no value, flags that take one) among `git <sub> -h`'s short options."""
    out = sh(cwd, "git", sub, "-h")
    shorts = dict(re.findall(r"^\s+-(\w), --\S+?(\s*<|\[=|(?=\s))", out.stdout + out.stderr, re.M))
    return {c for c, arg in shorts.items() if not arg.strip()}, {c for c, arg in shorts.items() if arg.strip()}


# git's own options, some with their value in the next word, before the subcommand
# (`git -C dir commit -n` got past the guard).
GIT_PREFIXES = ["-C .", "-C 'my dir'", "-C my\\ dir", "-c user.name=T", "--git-dir .git --work-tree .",
                "--git-dir=.git", "--namespace ns", "--config-env user.name=HOME", "--no-pager", "-P"]


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

    def blocks(self, command: str) -> bool:
        """The guard's verdict on a Bash command, in-process (claude() only prints and exits on it)."""
        if not hasattr(self, "_guard"):
            spec = importlib.util.spec_from_file_location("guard", self.repo / ".keelokit/bin/guard.py")
            self._guard = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self._guard)
        return self._guard.bash_problem(command) is not None

    def test_LOG_4_hook_bypass_follows_git_option_grammar(self):
        """LOG-4: `-uno` was blocked as `commit -n` because the token held an n, while
        `git -C dir commit -n` and `git push -uf` got through. The guard must read git's own
        option grammar: a short-option bundle counts only when n (or push's f) is one of its
        option letters, not an option's value; a long option counts in every abbreviation git
        accepts; and git's own options, some taking the next word, may come before the
        subcommand. The letters come from `git commit -h` and `git push -h`, so a new git option
        the guard doesn't know fails here instead of blocking or passing by accident."""
        flags, takes_value = short_options(self.repo, "commit")
        self.assertIn("n", flags, "git commit -n is no longer an argument-less flag")
        flags -= {"n"}
        self.assertTrue({"a", "q", "v"} <= flags and {"m", "u", "S"} <= takes_value)
        push_flags, push_values = short_options(self.repo, "push")
        self.assertIn("f", push_flags, "git push -f is no longer an argument-less flag")
        push_flags -= {"f"}
        self.assertTrue({"u", "v", "q"} <= push_flags and "o" in push_values)

        blocked = ["git commit -n", "git commit -nuno -m x", "git commit -nmx"]
        blocked += [f"git commit -{c}n -m x" for c in sorted(flags)]
        blocked += [f"git commit -n{c} -m x" for c in sorted(flags)]
        blocked += [f"git commit -n{c}val" for c in sorted(takes_value)]
        blocked += [f"git commit {o} -m x" for o in ["--no-veri", "--no-verif", "--no-verify"]]
        blocked += ["git push --no-veri origin main", "git commit -m x -n; echo done"]
        blocked += [f"git push -{c}f origin main" for c in sorted(push_flags)]
        blocked += [f"git push -f{c} origin main" for c in sorted(push_flags)]
        blocked += [f"git push -f{c}val origin main" for c in sorted(push_values)]
        blocked += [f"git push {o} origin" for o in ["--force", "--force-if-includes", "--mirror", "--mirr", "--m"]]
        blocked += ["git push origin +main", "git config core.hooksPath /tmp", "git config core.hookspath /tmp",
                    "git -c core.hooksPath=/dev/null commit -m x", "git -c CORE.HOOKSPATH=/dev/null commit",
                    "git --config-env=core.hooksPath=HOME commit", "git --config-env core.hooksPath=HOME commit"]
        allowed = ["git commit -uno -m x", "git commit -unormal -m x", "git commit -uall",
                   "git commit --untracked-files=no -m x", "git commit -Sn -m x", "git commit -m x -- -n",
                   "git merge --no-verify-signatures feature", "git commit --no-verbose -m x",
                   "git push --force-with-lease origin main", "git push --force-w origin main",
                   "git push -of origin main", "git push -o f origin main", "git log -n 5",
                   "git -c core.editor=vi commit -m x", "git config core.editor vi"]
        allowed += [f"git commit -{c}n" for c in sorted(takes_value)]
        allowed += [f"git push -{c}f origin main" for c in sorted(push_values)]
        allowed += [f"git push -{c} origin main" for c in sorted(push_flags)]
        for git in ["git ", *(f"git {p} " for p in GIT_PREFIXES)]:
            for cmd in blocked:
                cmd = cmd.replace("git ", git, 1)
                with self.subTest(cmd=cmd):
                    self.assertTrue(self.blocks(cmd))
            for cmd in allowed:
                cmd = cmd.replace("git ", git, 1)
                with self.subTest(cmd=cmd):
                    self.assertFalse(self.blocks(cmd))
        self.assertEqual(self.bash("git -C . commit -uno -m x"), 0)
        self.assertEqual(self.bash("git -C . commit -n -m x"), 2)

    def test_LOG_4_guard_agrees_with_git(self):
        """LOG-4, the class: the hook and force-push rules read git's command line, so they are
        checked against git itself. Each commit runs for real with a pre-commit hook that fails:
        one that got through skipped the hooks and must be blocked, one the hook stopped must
        pass. Each push runs for real against a remote whose history it would rewrite: one that
        rewrote it must be blocked (--force-with-lease is allowed on purpose)."""
        prefixes = ["", "-C .", "-c user.name=T", "--git-dir .git --work-tree .", "--no-pager"]
        env = {**os.environ, "GIT_EDITOR": "true", "GIT_CONFIG_NOSYSTEM": "1"}
        run = lambda cmd: subprocess.run(["bash", "-c", cmd], cwd=self.repo, capture_output=True, text=True, env=env)
        head = lambda: sh(self.repo, "git", "rev-parse", "HEAD").stdout.strip()

        remote = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, remote)
        sh(remote, "git", "init", "-q", "--bare")
        sh(self.repo, "git", "remote", "add", "origin", str(remote))
        sh(self.repo, "git", "push", "-q", "origin", "main")
        old = head()
        sh(self.repo, "git", "commit", "-q", "--amend", "--no-verify", "-m", "rewritten")
        forced_any = False
        for prefix in prefixes:
            for args in ["-f origin main", "-uf origin main", "-fu origin main", "-vf origin main",
                         "-4f origin main", "--force origin main", "--mirror origin", "--mirr origin",
                         "origin +main", "origin +HEAD:main", "--force-with-lease origin main",
                         "-u origin main", "-v origin main", "-of origin main", "-q origin main"]:
                cmd = f"git {prefix} push {args}".replace("  ", " ")
                sh(remote, "git", "update-ref", "refs/heads/main", old)
                out = run(cmd)
                forced = sh(remote, "git", "rev-parse", "main").stdout.strip() == head()
                forced_any |= forced
                with self.subTest(cmd=cmd, forced=forced, stderr=out.stderr[-300:]):
                    if "--force-with-lease" in args:
                        self.assertFalse(self.blocks(cmd))
                    elif forced:
                        self.assertTrue(self.blocks(cmd))
                    else:
                        self.assertFalse(self.blocks(cmd))
        self.assertTrue(forced_any)

        marker = remote / "hook-ran"
        (self.repo / "-n").write_text("0\n")
        sh(self.repo, "git", "add", "-A")
        sh(self.repo, "git", "commit", "-q", "--no-verify", "-m", "tracked -n")
        base = head()
        hook = self.repo / ".git/hooks/pre-commit"
        hook.write_text(f"#!/bin/sh\ntouch '{marker}'\nexit 1\n")
        hook.chmod(0o755)
        for prefix in prefixes:
            for opts in ["-n", "-an", "-na", "-qn", "-nq", "-nuno", "-nmy", "--no-verify", "--no-verif",
                         "--no-veri", "-uno", "-unormal", "-uall", "--untracked-files=no", "--no-verbose",
                         "-a", "-q", "-- -n"]:
                cmd = f"git {prefix} commit -m x {opts}".replace("  ", " ")
                (self.repo / "-n").write_text(cmd + "\n")
                sh(self.repo, "git", "add", "-A")
                out = run(cmd)
                committed, hook_ran = head() != base, marker.exists()
                marker.unlink(missing_ok=True)
                sh(self.repo, "git", "reset", "-q", "--hard", base)
                with self.subTest(cmd=cmd, committed=committed, hook_ran=hook_ran, stderr=out.stderr[-300:]):
                    self.assertTrue(committed or hook_ran, "git refused the command itself")
                    if hook_ran:
                        self.assertFalse(self.blocks(cmd))
                    elif committed:
                        self.assertTrue(self.blocks(cmd))

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
