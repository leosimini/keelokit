"""Guard behaviour: what it blocks and what it must let through. Run: python3 -m unittest discover -s tests"""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
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

    def test_CPY_1_block_reasons_name_no_package_manager(self):
        """The guard runs in adopted repos that may have no package.json: its reason for a block
        can't send anyone to `pnpm install` (it did for `git config core.hooksPath`)."""
        event = json.dumps({"tool_name": "Bash", "tool_input": {"command": "git config core.hooksPath /tmp"}})
        run = subprocess.run(["python3", str(self.repo / ".keelokit/bin/guard.py"), "--claude"],
                             input=event, capture_output=True, text=True)
        self.assertEqual(run.returncode, 2)
        self.assertIn("ask a human", run.stderr)
        self.assertNotRegex(GUARD.read_text(), r"\b(pnpm|npm|yarn|bun)\b")

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

    def module(self):
        """The guard loaded in-process, for checks too many to run one process each."""
        if not hasattr(self, "_guard"):
            spec = importlib.util.spec_from_file_location("guard", self.repo / ".keelokit/bin/guard.py")
            self._guard = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self._guard)
        return self._guard

    def blocks(self, command: str) -> bool:
        """The guard's verdict on a Bash command, in-process (claude() only prints and exits on it)."""
        return self.module().bash_problem(command) is not None

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

    def test_DOC_1_guard_names_every_rule_rules_toml_says_it_enforces(self):
        # rules.toml listed claude-hook:guard.py under REL-1, but the guard never cited REL-1 and
        # its docstring left it out; doctor only checks that guard.py exists. Both copies (the
        # template and this repo's own adopted harness) must agree with their rules.toml.
        import tomllib
        repo = Path(__file__).resolve().parents[1]
        for base in (repo / "template/.keelokit", repo / ".keelokit"):
            with self.subTest(base=base.relative_to(repo).as_posix()):
                rules = tomllib.loads((base / "harness/rules.toml").read_text())["rule"]
                claimed = {r["id"] for r in rules if "claude-hook:guard.py" in r.get("enforced_by", [])}
                src = (base / "bin/guard.py").read_text()
                listed = re.search(r"^Rules enforced: (.+?) \(", src, re.M)
                self.assertIsNotNone(listed, "guard.py's docstring has no 'Rules enforced:' line")
                self.assertEqual(set(listed.group(1).split(", ")), claimed)
                body = src[src.index('"""', 3):]  # past the module docstring
                for rid in sorted(claimed):
                    self.assertRegex(body, rf'"[^"\n]*\b{re.escape(rid)}\b[^"\n]*:',
                                     f"no block reason in guard.py cites {rid}")
                # the git pre-commit hook runs this same guard
                pre_commit = {r["id"] for r in rules if "git-hook:pre-commit" in r.get("enforced_by", [])}
                self.assertLessEqual(pre_commit, claimed)
        out = subprocess.run(["python3", str(self.repo / ".keelokit/bin/guard.py"), "--claude"],
                             input=json.dumps({"tool_name": "Bash", "tool_input": {
                                 "command": "fly deploy --config apps/api/fly.production.toml"}}),
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 2)
        self.assertIn("REL-1", out.stderr)

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
        for secret in ["github_pat_" + "A" * 50, "AIza" + "B" * 35, "postgres://u:" + "p4ss@db.example.com:5432/x"]:
            with self.subTest(secret=secret[:12]):
                self.assertEqual(self.claude("Write", file_path=target, content=secret), 2)
        self.assertEqual(self.claude("Write", file_path=target, content="postgresql://app:app@localhost:5432/app"), 0)

    def test_LOG_3_deleting_or_touching_an_env_file_says_so(self):
        """LOG-3: rm/touch of .env was blocked with a message about writing real values."""
        for cmd in ["rm .env", "touch apps/api/.env", "ln -s x .env"]:
            with self.subTest(cmd=cmd):
                run = subprocess.run(["python3", str(self.repo / ".keelokit/bin/guard.py"), "--claude"], cwd=self.repo,
                                     input=json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}}),
                                     capture_output=True, text=True)
                self.assertEqual(run.returncode, 2)
                self.assertIn("don't delete, create or link", run.stderr)
        self.assertEqual(self.bash("echo X=1 > .env"), 2)

    def test_sec_1_more_token_families_and_split_keys(self):
        """SEC-1 (bug bash 2026-09-27): npm, GitLab, JWT and Azure keys, and a key split over a MultiEdit's edits."""
        target = str(self.repo / "a.ts")
        jwt = "eyJ" + "hbGciOiJIUzI1NiJ9" + ".eyJ" + "zdWIiOiIxMjM0In0" + "." + "dozjgNryP4J3jVmNHl0w5N"
        for secret in ["npm_" + "a1B2" * 9, "glpat-" + "x" * 20, jwt, "AccountKey=" + "Ab1+" * 16 + "=="]:
            with self.subTest(secret=secret[:8]):
                self.assertEqual(self.claude("Write", file_path=target, content=f"k = '{secret}'"), 2)
        halves = [{"old_string": "a", "new_string": 'const k="AKIA1234567'}, {"old_string": "b", "new_string": '890ABCDEF";'}]
        self.assertEqual(self.claude("MultiEdit", file_path=target, edits=halves), 2)
        self.assertEqual(self.claude("Write", file_path=target, content="const npm_version = 'npm_config'"), 0)

    def test_tampering(self):
        target = str(self.repo / "a.test.ts")
        for code in ["it.skip('x', () => {})", "test.only('x', () => {})", "xit('x')", "// eslint-disable-next-line", "// @ts-ignore"]:
            with self.subTest(code=code):
                self.assertEqual(self.claude("Edit", file_path=target, old_string="a", new_string=code), 2)
        ci = str(self.repo / ".github/workflows/ci.yml")
        self.assertEqual(self.claude("Write", file_path=ci, content="continue-on-error: true"), 2)
        self.assertEqual(self.claude("Write", file_path=str(self.repo / "docs/x.md"), content="never use it.skip("), 0)

    def test_LOG_202_continue_on_error_in_every_spelling(self):
        ci = str(self.repo / ".github/workflows/ci.yml")
        # Bare, capitalised or as an expression, each with no quote or a single or double one around
        # it: YAML reads `"${{ true }}"` as `${{ true }}`.
        forms = ["true", "True", "TRUE", "${{ true }}", "${{true}}", "${{ True }}"]
        for value in [q + form + q for q in ("", "'", '"') for form in forms]:
            with self.subTest(value=value):
                self.assertEqual(self.claude("Write", file_path=ci, content=f"    continue-on-error: {value}\n"), 2)
        for value in ["false", "${{ false }}", "'${{ false }}'", "${{ matrix.experimental }}",
                      "\"${{ matrix.experimental }}\""]:
            with self.subTest(value=value):
                self.assertEqual(self.claude("Write", file_path=ci, content=f"    continue-on-error: {value}\n"), 0)

    def run_guard(self, *argv: str, stdin: str = "") -> subprocess.CompletedProcess:
        return subprocess.run(["python3", str(self.repo / ".keelokit/bin/guard.py"), *argv],
                              input=stdin, capture_output=True, text=True)

    def test_DX_6_unknown_mode_blocks_and_says_so(self):
        # Any mode but the two it has used to exit 0 without a word, like a clean run.
        for argv in [(), ("--help",), ("claude",), ("--Claude",), ("--bogus-mode",)]:
            with self.subTest(argv=argv):
                run = self.run_guard(*argv)
                self.assertEqual(run.returncode, 2)
                self.assertIn("unknown mode", run.stderr)
                self.assertIn("--claude or git-pre-commit", run.stderr)

    def test_DX_6_unreadable_hook_input_blocks_with_the_reason(self):
        # A crash exits 1, which Claude Code treats as non-blocking: the call went through.
        for stdin in ["", "not json {{{", "[]", '"Bash"', "42", "null", '{"tool_name": "Bash", "tool_input": "oops"}',
                      '{"tool_name": "Write", "tool_input": ["a"]}', '{"tool_name": "Bash", "tool_input": 3}',
                      # Nesting past the recursion limit raises RecursionError, not ValueError.
                      "[" * 100000, '{"tool_name": "Bash", "tool_input": {"command": "ls", "x": ' + "[" * 100000 + "]" * 100000 + "}}"]:
            with self.subTest(stdin=stdin[:60]):
                run = self.run_guard("--claude", stdin=stdin)
                self.assertNotIn("Traceback", run.stderr)
                if '"command": "ls"' in stdin and stdin.endswith("}" * 1):
                    # Deeply nested but valid JSON: Python 3.14 parses it (older ones raise
                    # RecursionError), and the command is `ls`. Either answer is fine; a crash is not.
                    self.assertIn(run.returncode, (0, 2))
                    continue
                self.assertEqual(run.returncode, 2)
                self.assertIn("Keelokit guard: couldn't read the hook input", run.stderr)

    def test_DX_6_every_raw_stdin_gets_block_or_pass(self):
        """The parse step itself, fed stdin of every kind: whatever the reader or the JSON decoder
        raises (bad bytes, deep nesting, a closed stdin) must end in 0 or 2, never a crash."""
        import contextlib
        import io
        import sys

        guard = self.module()
        ok = '{"tool_name": "Bash", "tool_input": {"command": "ls"}}'
        raws = ["", " ", ok, ok[:-1], ok + ok, "\ufeff" + ok, "\x00", "NaN", "1e999", '"\\ud800"',
                "[" * 100000, "{" * 100000, '{"a":' * 100000, "[" * 100000 + "]" * 100000,
                '{"tool_name": "Bash", "tool_input": {"command": ' + "[" * 100000 + "]" * 100000 + "}}"]
        streams = [io.StringIO(r) for r in raws] + [None, io.BytesIO(b"\xff\xfe"), io.TextIOWrapper(io.BytesIO(b"\xff\xfe"))]
        for i, stream in enumerate(streams):
            with self.subTest(case=i, raw=raws[i][:40] if i < len(raws) else repr(stream)):
                err = io.StringIO()
                stdin, sys.stdin = sys.stdin, stream
                try:
                    with contextlib.redirect_stderr(err):
                        code = guard.main(["--claude"])
                finally:
                    sys.stdin = stdin
                self.assertIn(code, (0, 2), err.getvalue())
                if code == 2:
                    self.assertTrue(err.getvalue().strip(), "a block must say why")

    def test_DX_6_every_hook_input_shape_gets_block_or_pass(self):
        """The contract is exactly {0: let through, 2: block}; any other outcome (a crash exits 1)
        lets the call through unchecked. Every field the guard reads, in every tool, with every
        JSON type, must end in one of the two — checked in-process through main()."""
        import contextlib
        import io
        import sys

        guard = self.module()
        fields = ["command", "file_path", "notebook_path", "content", "new_string", "new_source", "edits"]
        values = [None, True, 7, 1.5, "x", ["x"], [{"new_string": 7}], {"k": "v"}]
        for tool in [None, 7, "Bash", "Edit", "Write", "MultiEdit", "NotebookEdit", "Read"]:
            for field in fields:
                for value in values:
                    event = json.dumps({"tool_name": tool, "tool_input": {field: value}})
                    with self.subTest(tool=tool, field=field, value=value):
                        err = io.StringIO()
                        stdin, sys.stdin = sys.stdin, io.StringIO(event)
                        try:
                            with contextlib.redirect_stderr(err):
                                code = guard.main(["--claude"])
                        finally:
                            sys.stdin = stdin
                        self.assertIn(code, (0, 2), err.getvalue())
                        if code == 2:
                            self.assertTrue(err.getvalue().strip(), "a block must say why")

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

        # SEC-1: the whole staged file is scanned, so a key finished by a later commit is caught.
        (self.repo / "k.js").write_text('const k = "AKIA1234567\n')
        sh(self.repo, "git", "add", "k.js")
        self.assertEqual(self.pre_commit(), 0)
        sh(self.repo, "git", "commit", "-qm", "half", "--no-verify")
        (self.repo / "k.js").write_text('const k = "AKIA' + '1234567890ABCDEF";\n')
        sh(self.repo, "git", "add", "k.js")
        self.assertEqual(self.pre_commit(), 1)
        sh(self.repo, "git", "reset", "-q", "k.js")

        mig = self.repo / "apps/api/prisma/migrations/0001_init/migration.sql"
        mig.write_text("select 2;\n")
        sh(self.repo, "git", "add", str(mig))
        self.assertEqual(self.pre_commit(), 1)


REGISTRY = ".keelokit/guard-allow.toml"
GOOGLE_JSON = "apps/mobile/google-services.json"
GOOGLE_KEY = "AIza" + "B" * 35
AWS_KEY = "AKIA" + "1234567890ABCDEF"
STRIPE_KEY = "sk_live_" + "a" * 24
GITHUB_TOKEN = "ghp_" + "A" * 36
# Where a URL's password goes: references to a variable (HARN-020.S1) and literals (S2).
REFERENCES = ["${DB_PASSWORD}", "$DB_PASSWORD", "${{ secrets.DB_PASSWORD }}", "${{secrets.DB_PASSWORD}}",
              "${{  secrets.DB_PASSWORD  }}", "${{ env.DB_PASSWORD }}", "${{ vars.DB_PASSWORD }}",
              "${{ inputs.password }}", "${{ github.token }}", "${{ matrix.password }}", "${{ needs.password }}",
              "${{ steps.password }}", "${{ job.password }}", "${{ runner.password }}"]
LITERALS = ["p4ssw0rd", "pa${X}ss", "${X}:real", "${X}real", "real${X}", "$X:real", "${{ secrets.X }}real",
            "real${{ secrets.X }}"]
DB_SCHEMES = ["postgres", "postgresql", "mysql", "mongodb", "mongodb+srv", "redis"]


def db_url(scheme: str, password: str) -> str:
    return f"{scheme}://app:{password}@db.example.com:5432/app"


def git_url(password: str) -> str:
    return f"https://deploy:{password}@github.com/acme/app.git"


def allow(**fields) -> str:
    """One [[allow]] table; each field is a TOML literal, None leaves it out. Defaults: an active
    SEC-1 entry for apps/mobile/google-services.json."""
    entry = {"rule": '"SEC-1"', "path": f'"{GOOGLE_JSON}"', "reason": '"Firebase key, public by design"',
             "approver": '"Leo"', **fields}
    return "[[allow]]\n" + "".join(f"{k} = {v}\n" for k, v in entry.items() if v is not None)


class GuardRegistryTest(unittest.TestCase):
    """HARN-020: a variable reference in a URL's password is no secret, and .keelokit/guard-allow.toml
    registers the few paths SEC-1 or SEC-2 let through. The registry is the human's (QA-4)."""

    setUp = GuardTest.setUp
    tearDown = GuardTest.tearDown
    module = GuardTest.module

    def env(self, fake_gitleaks: Path | None = None) -> dict:
        """The environment with no real gitleaks on PATH (so a test sees only the guard), or a fake first."""
        dirs = [d for d in os.environ.get("PATH", "").split(os.pathsep) if d and not (Path(d) / "gitleaks").exists()]
        if fake_gitleaks:
            dirs.insert(0, str(fake_gitleaks))
        return {**os.environ, "PATH": os.pathsep.join(dirs)}

    def run_claude(self, tool: str, **tool_input) -> subprocess.CompletedProcess:
        return subprocess.run(["python3", str(self.repo / ".keelokit/bin/guard.py"), "--claude"], cwd=self.repo,
                              input=json.dumps({"tool_name": tool, "tool_input": tool_input}),
                              capture_output=True, text=True, env=self.env())

    def claude(self, tool: str, **tool_input) -> int:
        run = self.run_claude(tool, **tool_input)
        self.assertNotIn("Traceback", run.stderr)
        return run.returncode

    def bash(self, command: str) -> int:
        return self.claude("Bash", command=command)

    def write(self, rel: str, content: str) -> int:
        """The Claude hook on a Write of `content` to `rel`, given as Claude Code gives it: absolute."""
        return self.claude("Write", file_path=str(self.repo / rel), content=content)

    def registry(self, text: str | bytes, commit: bool = True) -> None:
        path = self.repo / REGISTRY
        path.write_bytes(text if isinstance(text, bytes) else text.encode())
        if commit:  # the human's commit (no hooks are installed in this repo)
            sh(self.repo, "git", "add", "-f", REGISTRY)
            sh(self.repo, "git", "commit", "-qm", "registry", "--no-verify")

    def run_pre_commit(self, fake_gitleaks: Path | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(["python3", ".keelokit/bin/guard.py", "git-pre-commit"], cwd=self.repo,
                              capture_output=True, text=True, env=self.env(fake_gitleaks))

    def pre_commit(self, fake_gitleaks: Path | None = None) -> int:
        run = self.run_pre_commit(fake_gitleaks)
        self.assertNotIn("Traceback", run.stderr)
        return run.returncode

    def stage(self, rel: str, content: str | bytes) -> None:
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode())
        sh(self.repo, "git", "add", "-f", rel)

    def staged_verdict(self, rel: str, content: str, fake_gitleaks: Path | None = None) -> int:
        """pre-commit's exit code with only `rel` staged; the index is back at HEAD afterwards."""
        self.stage(rel, content)
        try:
            return self.pre_commit(fake_gitleaks)
        finally:
            sh(self.repo, "git", "reset", "-q", "--", rel)
            (self.repo / rel).unlink()

    def install_hook(self) -> None:
        hook = self.repo / ".git/hooks/pre-commit"
        hook.write_text("#!/bin/sh\nexec python3 .keelokit/bin/guard.py git-pre-commit\n")
        hook.chmod(0o755)

    def git_commit(self, *config: str) -> subprocess.CompletedProcess:
        """A real `git [-c …] commit` that runs the guard as its pre-commit hook."""
        cmd = ["git", *(a for c in config for a in ("-c", c)), "commit", "-qm", "x"]
        return subprocess.run(cmd, cwd=self.repo, capture_output=True, text=True, env=self.env())

    def fake_gitleaks(self, code: int) -> tuple[Path, Path]:
        """A `gitleaks` that records its arguments (→ log.argv) and its --config file (→ log.config)."""
        bin_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, bin_dir)
        log = bin_dir / "log"
        script = bin_dir / "gitleaks"
        script.write_text(f"""#!/bin/sh
printf '%s\\n' "$@" > '{log}.argv'
prev=""
for a in "$@"; do
  if [ "$prev" = "--config" ] || [ "$prev" = "-c" ]; then cat "$a" > '{log}.config'; fi
  case "$a" in --config=*) cat "${{a#--config=}}" > '{log}.config';; esac
  prev="$a"
done
exit {code}
""")
        script.chmod(0o755)
        return bin_dir, log

    # S1/S2: a variable reference in a URL's password vs a literal there

    def test_HARN_020_S1_a_variable_reference_in_a_urls_password_is_not_a_secret(self):
        urls = [db_url(s, ref) for s in DB_SCHEMES for ref in REFERENCES] + [git_url(ref) for ref in REFERENCES]
        target = "deploy/compose.prod.yml"
        for url in urls:
            with self.subTest(url=url, where="Write"):
                self.assertEqual(self.write(target, f"DATABASE_URL: {url}\n"), 0)
            with self.subTest(url=url, where="Edit"):
                self.assertEqual(self.claude("Edit", file_path=str(self.repo / target), old_string="x",
                                             new_string=f"url: {url}"), 0)
            with self.subTest(url=url, where="MultiEdit"):
                self.assertEqual(self.claude("MultiEdit", file_path=str(self.repo / target),
                                             edits=[{"old_string": "a", "new_string": f"url: {url}"}]), 0)
            with self.subTest(url=url, where="Bash"):
                self.assertEqual(self.bash(f"psql {url} -c 'select 1'"), 0)
        for url in [db_url("postgresql", "${DB_PASSWORD}"), db_url("mongodb+srv", "${{ secrets.MONGO_PW }}"),
                    db_url("redis", "$REDIS_PASSWORD"), git_url("${{ secrets.GH_TOKEN }}"), git_url("$GH_TOKEN")]:
            with self.subTest(url=url, where="pre-commit"):
                self.assertEqual(self.staged_verdict(".github/workflows/deploy.yml", f"env:\n  URL: {url}\n"), 0)

    def test_HARN_020_S2_a_literal_in_a_urls_password_is_still_a_secret(self):
        urls = [db_url(s, lit) for s in DB_SCHEMES for lit in LITERALS] + [git_url(lit) for lit in LITERALS]
        target = "deploy/compose.prod.yml"
        for url in urls:
            with self.subTest(url=url, where="Write"):
                self.assertEqual(self.write(target, f"DATABASE_URL: {url}\n"), 2)
            with self.subTest(url=url, where="MultiEdit"):
                self.assertEqual(self.claude("MultiEdit", file_path=str(self.repo / target),
                                             edits=[{"old_string": "a", "new_string": f"url: {url}"}]), 2)
            with self.subTest(url=url, where="Bash"):
                self.assertEqual(self.bash(f"psql {url} -c 'select 1'"), 2)
        for url in [db_url("postgresql", "p4ssw0rd"), db_url("mysql", "pa${X}ss"), db_url("redis", "${X}:real"),
                    db_url("postgres", "${{ secrets.X }}real"), git_url("p4ssw0rd"), git_url("real${X}")]:
            with self.subTest(url=url, where="pre-commit"):
                self.assertEqual(self.staged_verdict(".github/workflows/deploy.yml", f"env:\n  URL: {url}\n"), 1)
        # A reference URL doesn't vouch for the rest of the file.
        mixed = f"URL: {db_url('postgresql', '${DB_PASSWORD}')}\nAWS: {AWS_KEY}\n"
        with self.subTest("an unrelated key next to a reference URL"):
            self.assertEqual(self.write(target, mixed), 2)
            self.assertEqual(self.staged_verdict(target, mixed), 1)
        # The hosts of this machine stay exempt, as before.
        for url in ["postgresql://app:app@localhost:5432/app", "postgres://u:p4ss@127.0.0.1/x",
                    "postgres://u:p4ss@postgres:5432/x", "mysql://u:p4ss@db/x"]:
            with self.subTest(url=url, where="local host"):
                self.assertEqual(self.write(target, url), 0)

    # S3: a registered path is let through, for its rule only

    def test_HARN_020_S3_a_sec_1_path_entry_lets_a_key_through_at_that_path_only(self):
        content = f'{{"client": [{{"api_key": [{{"current_key": "{GOOGLE_KEY}"}}]}}]}}\n'
        for expires in [None, '"permanent"', '"2999-12-31"']:
            with self.subTest(expires=expires):
                self.registry(allow(expires=expires))
                self.assertEqual(self.write(GOOGLE_JSON, content), 0)
                self.assertEqual(self.claude("Write", file_path=GOOGLE_JSON, content=content), 0)  # relative
                self.assertEqual(self.claude("Edit", file_path=str(self.repo / GOOGLE_JSON), old_string="x",
                                             new_string=GOOGLE_KEY), 0)
                self.assertEqual(self.claude("MultiEdit", file_path=str(self.repo / GOOGLE_JSON),
                                             edits=[{"old_string": "a", "new_string": AWS_KEY}]), 0)
                self.assertEqual(self.staged_verdict(GOOGLE_JSON, content), 0)
        for other in ["apps/mobile/other.json", "apps/mobile/google-services.json.bak", "apps/google-services.json",
                      "apps/mobile/x/google-services.json", "x/apps/mobile/google-services.json",
                      "apps/mobile/my-google-services.json"]:
            with self.subTest(other=other):
                self.assertEqual(self.write(other, content), 2)
                self.assertEqual(self.staged_verdict(other, content), 1)
        with self.subTest("a SEC-1 entry doesn't exempt a command line"):
            self.assertEqual(self.bash(f"echo '{GOOGLE_KEY}' > {GOOGLE_JSON}"), 2)
            self.assertEqual(self.bash(f"curl -H 'k: {GOOGLE_KEY}' https://example.com"), 2)

    def test_HARN_020_S3_a_sec_1_glob_entry_matches_files_directly_in_its_directory(self):
        self.registry(allow(path=None, glob='"apps/mobile/*.json"'))
        content = f'{{"current_key": "{GOOGLE_KEY}"}}\n'
        for rel in [GOOGLE_JSON, "apps/mobile/other.json"]:
            with self.subTest(rel=rel):
                self.assertEqual(self.write(rel, content), 0)
                self.assertEqual(self.staged_verdict(rel, content), 0)
        for rel in ["apps/mobile/sub/google-services.json", "apps/google-services.json", "apps/mobile/keys.ts",
                    "x/apps/mobile/google-services.json"]:
            with self.subTest(rel=rel):
                self.assertEqual(self.write(rel, content), 2)
                self.assertEqual(self.staged_verdict(rel, content), 1)

    def test_HARN_020_S3_a_sec_2_entry_lets_that_env_file_through_but_not_a_key_in_it(self):
        self.registry(allow(rule='"SEC-2"', path='"apps/api/.env.production"', reason='"placeholders the deploy guide names"')
                      + allow(rule='"SEC-2"', path=None, glob='"infra/03-env-templates/*.env"'))
        placeholders = "DATABASE_URL=postgresql://app:${DB_PASSWORD}@db.example.com/app\nAPI_KEY=change-me\n"
        for rel in ["apps/api/.env.production", "infra/03-env-templates/prod.env", "infra/03-env-templates/staging.env"]:
            with self.subTest(rel=rel, where="Write"):
                self.assertEqual(self.write(rel, placeholders), 0)
                self.assertEqual(self.claude("Edit", file_path=str(self.repo / rel), old_string="a", new_string="B=1"), 0)
            with self.subTest(rel=rel, where="pre-commit"):
                self.assertEqual(self.staged_verdict(rel, placeholders), 0)
            for secret in [f"KEY={STRIPE_KEY}\n", f"URL={db_url('postgresql', 'p4ssw0rd')}\n"]:
                with self.subTest(rel=rel, secret=secret[:12]):
                    self.assertEqual(self.write(rel, secret), 2)
                    self.assertEqual(self.staged_verdict(rel, secret), 1)
        for cmd in ["cp x infra/03-env-templates/prod.env", "echo A= > infra/03-env-templates/prod.env",
                    "echo A= >> apps/api/.env.production", "tee infra/03-env-templates/prod.env < x"]:
            with self.subTest(cmd=cmd):
                self.assertEqual(self.bash(cmd), 0)
        for cmd in ["cp x infra/prod.env", "cp x infra/03-env-templates/sub/prod.env", "echo A= > apps/api/.env",
                    "echo A= > apps/web/.env.production", f"echo K={STRIPE_KEY} > infra/03-env-templates/prod.env"]:
            with self.subTest(cmd=cmd):
                self.assertEqual(self.bash(cmd), 2)
        for rel in ["apps/api/.env", "apps/web/.env.production", "infra/03-env-templates/sub/prod.env", "infra/prod.env"]:
            with self.subTest(rel=rel, where="unregistered"):
                self.assertEqual(self.write(rel, "A=\n"), 2)
                self.assertEqual(self.staged_verdict(rel, "A=\n"), 1)

    def test_HARN_020_S3_each_entry_exempts_its_own_rule_only(self):
        self.registry(allow(path='"apps/api/.env.production"') + allow(rule='"SEC-2"'))
        # SEC-1 at a .env path: still a .env file (SEC-2).
        self.assertEqual(self.write("apps/api/.env.production", "A=\n"), 2)
        self.assertEqual(self.staged_verdict("apps/api/.env.production", "A=\n"), 1)
        self.assertEqual(self.bash("echo A= > apps/api/.env.production"), 2)
        # SEC-2 at a path: a key there is still a key (SEC-1).
        content = f'{{"current_key": "{GOOGLE_KEY}"}}\n'
        self.registry(allow(rule='"SEC-2"'))
        self.assertEqual(self.write(GOOGLE_JSON, content), 2)
        self.assertEqual(self.staged_verdict(GOOGLE_JSON, content), 1)

    # S4: the registry is narrow; an entry that isn't valid and bounded exempts nothing

    def test_HARN_020_S4_an_invalid_or_unbounded_entry_exempts_nothing(self):
        content = f'{{"current_key": "{GOOGLE_KEY}"}}\n'
        cases = {
            "another rule": allow(rule='"QA-4"'), "a made-up rule": allow(rule='"SEC-3"'), "no rule": allow(rule=None),
            "no reason": allow(reason=None), "empty reason": allow(reason='""'),
            "no approver": allow(approver=None), "empty approver": allow(approver='""'),
            "expired": allow(expires='"2000-01-01"'), "expired as a TOML date": allow(expires="2000-01-01"),
            "expires is no date": allow(expires='"soon"'),
            "path and glob": allow(glob='"apps/mobile/*.json"'), "neither path nor glob": allow(path=None),
            "absolute path": allow(path=f'"/{GOOGLE_JSON}"'), "the repo's absolute path": allow(path=json.dumps(str(self.repo / GOOGLE_JSON))),
            "./ path": allow(path=f'"./{GOOGLE_JSON}"'), ".. in the path": allow(path='"apps/../apps/mobile/google-services.json"'),
            "wildcard in a path": allow(path='"apps/mobile/google-*.json"'), "? in a path": allow(path='"apps/mobile/google-services.jso?"'),
            "[ in a path": allow(path='"apps/mobile/google-services.[j]son"'),
            "glob with **": allow(path=None, glob='"**/google-services.json"'),
            "glob with ** in the middle": allow(path=None, glob='"apps/**/google-services.json"'),
            "wildcard directory": allow(path=None, glob='"apps/*/google-services.json"'),
            "no literal directory": allow(path=None, glob='"*.json"'),
            "bare *": allow(path=None, glob='"apps/mobile/*"'), "*.*": allow(path=None, glob='"apps/mobile/*.*"'),
            "bare ?": allow(path=None, glob='"apps/mobile/?"'), "one literal": allow(path=None, glob='"apps/mobile/*n"'),
            "absolute glob": allow(path=None, glob='"/apps/mobile/*.json"'),
            ".. in a glob": allow(path=None, glob='"apps/../apps/mobile/*.json"'),
        }
        for why, text in cases.items():
            with self.subTest(why):
                self.registry(text)
                self.assertEqual(self.write(GOOGLE_JSON, content), 2)
                self.assertEqual(self.staged_verdict(GOOGLE_JSON, content), 1)
        # Control: the same entry, valid, does exempt it.
        self.registry(allow())
        self.assertEqual(self.write(GOOGLE_JSON, content), 0)

    # S6: the registry is the human's

    def test_HARN_020_S6_the_claude_hook_blocks_every_write_to_the_registry(self):
        self.registry("# empty\n")
        for path in [REGISTRY, str(self.repo / REGISTRY)]:
            for tool, extra in [("Write", {"content": allow()}), ("Edit", {"old_string": "#", "new_string": allow()}),
                                ("MultiEdit", {"edits": [{"old_string": "#", "new_string": allow()}]})]:
                with self.subTest(tool=tool, path=path):
                    run = self.run_claude(tool, file_path=path, **extra)
                    self.assertEqual(run.returncode, 2)
                    self.assertIn("QA-4", run.stderr)
            with self.subTest(tool="NotebookEdit", path=path):
                run = self.run_claude("NotebookEdit", notebook_path=path, new_source="x")
                self.assertEqual(run.returncode, 2)
                self.assertIn("QA-4", run.stderr)
        for cmd in [f"echo '[[allow]]' >> {REGISTRY}", f"echo x > {REGISTRY}", f"tee {REGISTRY} < x",
                    f"tee -a {REGISTRY} < x", f"cp /tmp/x {REGISTRY}", f"mv /tmp/x {REGISTRY}",
                    f"sed -i 's/a/b/' {REGISTRY}", f"rm {REGISTRY}", f"rm -f {REGISTRY}", f"truncate -s 0 {REGISTRY}",
                    f"touch {REGISTRY}", f"ln -sf /tmp/x {REGISTRY}", f"perl -pi -e 's/a/b/' {REGISTRY}",
                    f"cat x > {self.repo / REGISTRY}", f"cd .keelokit && ls && cp /tmp/x {REGISTRY}"]:
            with self.subTest(cmd=cmd):
                run = self.run_claude("Bash", command=cmd)
                self.assertEqual(run.returncode, 2)
                self.assertIn("QA-4", run.stderr)
        for cmd in [f"cat {REGISTRY}", f"git diff {REGISTRY}", f"grep SEC {REGISTRY}", f"git log -p -- {REGISTRY}"]:
            with self.subTest(cmd=cmd):
                self.assertEqual(self.bash(cmd), 0)

    def test_HARN_020_S6_a_commit_that_changes_the_registry_needs_allow_tamper(self):
        self.install_hook()
        content = f'{{"current_key": "{GOOGLE_KEY}"}}\n'
        head = lambda: sh(self.repo, "git", "rev-parse", "HEAD").stdout.strip()
        # Added: refused, then the human's yes; its entries apply to that same commit.
        self.stage(REGISTRY, allow())
        self.stage(GOOGLE_JSON, content)
        before = head()
        run = self.git_commit()
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("QA-4", run.stderr)
        self.assertEqual(head(), before)
        run = self.git_commit("keelokit.allowTamper=true")
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertNotEqual(head(), before)
        # Once committed, it applies to later commits without the human.
        (self.repo / GOOGLE_JSON).write_text(content + "\n")
        sh(self.repo, "git", "add", GOOGLE_JSON)
        self.assertEqual(self.git_commit().returncode, 0)
        # Modified and deleted: the same.
        self.stage(REGISTRY, allow() + allow(path=None, glob='"apps/mobile/*.plist"'))
        with self.subTest("modified"):
            self.assertEqual(self.pre_commit(), 1)
            self.assertEqual(self.git_commit("keelokit.allowTamper=true").returncode, 0)
        sh(self.repo, "git", "rm", "-q", REGISTRY)
        with self.subTest("deleted"):
            run = self.git_commit()
            self.assertNotEqual(run.returncode, 0)
            self.assertIn("QA-4", run.stderr)
            self.assertEqual(self.git_commit("keelokit.allowTamper=true").returncode, 0)

    def test_HARN_020_S6_pre_commit_reads_the_registry_as_staged(self):
        content = f'{{"current_key": "{GOOGLE_KEY}"}}\n'
        with self.subTest("untracked, never staged"):
            self.registry(allow(), commit=False)
            self.assertEqual(self.staged_verdict(GOOGLE_JSON, content), 1)
            (self.repo / REGISTRY).unlink()
        with self.subTest("committed empty, edited but not staged"):
            self.registry("# no entries yet\n")
            (self.repo / REGISTRY).write_text("# no entries yet\n" + allow())
            self.assertEqual(self.staged_verdict(GOOGLE_JSON, content), 1)
        with self.subTest("committed, removed from the working tree but not staged"):
            self.registry(allow())
            (self.repo / REGISTRY).unlink()
            self.assertEqual(self.staged_verdict(GOOGLE_JSON, content), 0)
            sh(self.repo, "git", "checkout", "--", REGISTRY)
        with self.subTest("staged, with the human's yes"):
            self.registry("# no entries yet\n")
            self.stage(REGISTRY, allow())
            sh(self.repo, "git", "config", "keelokit.allowTamper", "true")
            try:
                self.assertEqual(self.staged_verdict(GOOGLE_JSON, content), 0)
            finally:
                sh(self.repo, "git", "config", "--unset", "keelokit.allowTamper")

    def test_HARN_020_S6_a_key_in_the_registry_is_blocked_like_anywhere_else(self):
        """Design amendment 6: the registry is no longer exempt from SEC-1 (nor from gitleaks' allowlist),
        so a key pasted into a reason doesn't ride in on the human's allowTamper commit."""
        self.install_hook()
        for reason in [f"was leaked as {GOOGLE_KEY}; rotated", "was postgres://u:p4ss@db.example.com/x; rotated"]:
            with self.subTest(reason=reason[:20]):
                self.stage(REGISTRY, allow(reason=json.dumps(reason)))
                run = self.git_commit("keelokit.allowTamper=true")
                self.assertNotEqual(run.returncode, 0, run.stderr)
                self.assertIn("SEC-1", run.stderr)
                sh(self.repo, "git", "reset", "-q")
        with self.subTest("a plain reason passes"):
            self.stage(REGISTRY, allow(reason='"Firebase client key, public by design"'))
            self.assertEqual(self.git_commit("keelokit.allowTamper=true").returncode, 0)
        with self.subTest("the shipped template holds nothing key-shaped"):
            shipped = (GUARD.parents[1] / "guard-allow.toml").read_text()
            self.stage(REGISTRY, shipped)
            self.assertEqual(self.git_commit("keelokit.allowTamper=true").returncode, 0)
            self.assertIsNone(self.module().secret_in(shipped))

    # gitleaks at pre-commit (S3: both hooks let a registered path through)

    def test_HARN_020_S3_gitleaks_gets_an_allowlist_of_the_active_sec_1_paths(self):
        content = f'{{"current_key": "{GOOGLE_KEY}"}}\n'
        self.registry(allow())
        bin_dir, log = self.fake_gitleaks(0)
        self.assertEqual(self.staged_verdict(GOOGLE_JSON, content, bin_dir), 0)
        argv = Path(f"{log}.argv").read_text().splitlines()
        self.assertTrue(any(a in ("--config", "-c") or a.startswith("--config=") for a in argv), argv)
        config = Path(f"{log}.config").read_text()
        self.assertIn("allowlist", config)
        self.assertIn("google", config)
        self.assertIn("json", config)
        # Design amendment 6: the registry itself is scanned like any file.
        self.assertNotRegex(config, r"guard\W*-?\W*allow")
        with self.subTest("gitleaks finds something: still refused"):
            bin_dir, _ = self.fake_gitleaks(1)
            self.assertEqual(self.staged_verdict("README.md", "# hi\n", bin_dir), 1)
        with self.subTest("the project's own .gitleaks.toml is extended"):
            (self.repo / ".gitleaks.toml").write_text('[allowlist]\npaths = ["fixtures/"]\n')
            sh(self.repo, "git", "add", ".gitleaks.toml")
            sh(self.repo, "git", "commit", "-qm", "gitleaks config", "--no-verify")
            bin_dir, log = self.fake_gitleaks(0)
            self.assertEqual(self.staged_verdict(GOOGLE_JSON, content, bin_dir), 0)
            config = Path(f"{log}.config").read_text()
            self.assertRegex(config, r"(?s)\bextend\b.*\.gitleaks\.toml")
            self.assertIn("google", config)

    def test_HARN_020_S7_gitleaks_runs_as_before_without_active_sec_1_entries(self):
        before = ["git", "--pre-commit", "--staged", "--redact", "--no-banner"]
        for why, text in [("no registry", None), ("comments only", "# nothing\n"),
                          ("only SEC-2", allow(rule='"SEC-2"', path='"infra/prod.env"')),
                          ("SEC-1 expired", allow(expires='"2000-01-01"'))]:
            with self.subTest(why):
                if text is None:
                    if (self.repo / REGISTRY).exists():
                        sh(self.repo, "git", "rm", "-q", REGISTRY)
                        sh(self.repo, "git", "commit", "-qm", "rm", "--no-verify")
                else:
                    self.registry(text)
                bin_dir, log = self.fake_gitleaks(0)
                self.assertEqual(self.staged_verdict("README.md", "# hi\n", bin_dir), 0)
                self.assertEqual(Path(f"{log}.argv").read_text().splitlines(), before)
                self.assertFalse(Path(f"{log}.config").exists())

    # S7: no registry, or an empty one: the normal case is as before

    def test_HARN_020_S7_without_entries_everything_is_blocked_as_before(self):
        for why, text in [("no registry", None), ("empty", ""), ("comments only", "# [[allow]]\n# rule = \"SEC-1\"\n")]:
            if text is not None:
                self.registry(text)
            for rel, content in [("apps/api/.env", "A=1\n"), (".env.local", "A=1\n"), ("src/pay.ts", f"k = '{STRIPE_KEY}'"),
                                 ("src/gh.ts", f"t = '{GITHUB_TOKEN}'"), ("src/aws.ts", f"k = '{AWS_KEY}'"),
                                 (GOOGLE_JSON, f'{{"k": "{GOOGLE_KEY}"}}'),
                                 ("deploy/compose.yml", db_url("postgresql", "p4ssw0rd"))]:
                with self.subTest(why, rel=rel):
                    self.assertEqual(self.write(rel, content), 2)
                    self.assertEqual(self.staged_verdict(rel, content), 1)
            with self.subTest(why, what="a clean file"):
                self.assertEqual(self.write("src/ok.ts", "export {}\n"), 0)
                self.assertEqual(self.staged_verdict("src/ok.ts", "export {}\n"), 0)
            with self.subTest(why, what="shell"):
                self.assertEqual(self.bash("echo X=1 > apps/api/.env"), 2)
                self.assertEqual(self.bash(f"curl -H 'k: {STRIPE_KEY}' x"), 2)

    # Findings of the review and the breaker (2026-11-11), reproduced

    def timed(self, fn) -> tuple[int | None, float]:
        """(exit code, seconds) of a guard run; None when it ran past 10 s."""
        import time
        start = time.monotonic()
        try:
            code = fn()
        except subprocess.TimeoutExpired:
            code = None
        return code, time.monotonic() - start

    def test_HARN_020_S2_a_url_password_is_judged_in_linear_time(self):
        """ReDoS: `${{a}}` matched both alternatives of the password pattern, so 40 of them before a
        failing `@` backtracked 2^40 times and the hook hung instead of blocking the real URL after it."""
        real = "postgres://app:Sup3rRealPw@prod.example.com/db"
        fills = ["${{a}}" * 40, "${{a}}" * 2000, "${" * 5000, "$" * 5000, "{" * 5000, "}" * 5000, "${{" * 2500,
                 "}}" * 2500, "${{ secrets.X }}" * 400, "${{a}" * 1200, "${a}" * 1500, "$A" * 2500,
                 ("${" + "{" + "$" + "}") * 1250]
        hook = lambda tool, **ti: subprocess.run(
            ["python3", str(self.repo / ".keelokit/bin/guard.py"), "--claude"], cwd=self.repo, timeout=10,
            input=json.dumps({"tool_name": tool, "tool_input": ti}), capture_output=True, text=True).returncode
        for fill in fills:
            content = f"url1=postgres://u:{fill}@localhost/x\nurl2={real}\n"
            label = f"{fill[:12]}…×{len(fill)}"
            with self.subTest(fill=label, where="Write"):
                code, took = self.timed(lambda: hook("Write", file_path=str(self.repo / "deploy/a.env.yml"), content=content))
                self.assertEqual(code, 2)
                self.assertLess(took, 2)
            with self.subTest(fill=label, where="Bash"):
                cmd = f"psql postgres://u:{fill}@localhost/x && psql {real}"
                code, took = self.timed(lambda: hook("Bash", command=cmd))
                self.assertEqual(code, 2)
                self.assertLess(took, 2)
        for fill in ["${{a}}" * 40, "${" * 5000, "${{" * 2500]:
            with self.subTest(fill=fill[:12], where="pre-commit"):
                self.stage("deploy/compose.yml", f"url1=postgres://u:{fill}@localhost/x\nurl2={real}\n")
                try:
                    code, took = self.timed(lambda: subprocess.run(
                        ["python3", ".keelokit/bin/guard.py", "git-pre-commit"], cwd=self.repo, timeout=10,
                        capture_output=True, env=self.env()).returncode)
                finally:
                    sh(self.repo, "git", "reset", "-q")
                self.assertEqual(code, 1)
                self.assertLess(took, 2)

    def test_HARN_020_S2_an_unclosed_expression_in_a_password_is_a_literal(self):
        """The linear-time rewrite stopped matching a URL whose password holds an unclosed `${{`."""
        for url in ["postgres://u:${{pw@prod.example.com/db", "postgres://u:pa${{ss@prod.example.com/db",
                    "https://u:${{x@github.com/o/r"]:
            with self.subTest(url=url):
                self.assertEqual(self.write("deploy/compose.yml", f"URL: {url}\n"), 2)
                self.assertEqual(self.bash(f"psql {url}"), 2)
                self.assertEqual(self.staged_verdict("deploy/compose.yml", f"URL: {url}\n"), 1)

    def test_HARN_020_S2_a_bare_dollar_word_is_a_reference_only_in_capitals(self):
        """`$uperSecret2024` read as the variable `uperSecret2024`: a bare `$NAME` counts only when NAME is
        ALL-CAPS and ends the password; in braces any identifier is fine."""
        for url in ["postgres://admin:$uperSecret2024@prod.example.com/app", "postgres://u:$X1abc@prod.io/x",
                    "postgres://u:$Abc@prod.io/x", "mysql://u:$db_password@prod.io/x", git_url("$ghToken"),
                    "redis://u:$PW.x@prod.io/0", db_url("postgres", "$DB_PASSWORD-x")]:
            with self.subTest(url=url):
                self.assertEqual(self.write("deploy/compose.yml", f"URL: {url}\n"), 2)
                self.assertEqual(self.bash(f"psql {url}"), 2)
        for url in [db_url("postgres", "$DB_PASSWORD"), db_url("postgres", "$_PW2"), db_url("postgres", "${db_password}"),
                    db_url("mysql", "${dbPassword}"), db_url("postgres", "${{ secrets.X }}"), git_url("${gh_token}")]:
            with self.subTest(url=url):
                self.assertEqual(self.write("deploy/compose.yml", f"URL: {url}\n"), 0)

    def test_HARN_020_S6_the_claude_hook_reads_only_the_committed_registry(self):
        """The hook honoured the working-tree registry, so an agent that slipped one write past the
        shell check exempted itself; it reads HEAD's, and a human's commit is what turns an entry on."""
        content = f'{{"current_key": "{GOOGLE_KEY}"}}\n'
        with self.subTest("untracked"):
            self.registry(allow(), commit=False)
            self.assertEqual(self.write(GOOGLE_JSON, content), 2)
        with self.subTest("staged, not committed"):
            sh(self.repo, "git", "add", "-f", REGISTRY)
            self.assertEqual(self.write(GOOGLE_JSON, content), 2)
            sh(self.repo, "git", "reset", "-q")
        with self.subTest("committed empty, an entry added in the working tree"):
            self.registry("# none yet\n")
            (self.repo / REGISTRY).write_text("# none yet\n" + allow())
            self.assertEqual(self.write(GOOGLE_JSON, content), 2)
        with self.subTest("committed, then removed from the working tree"):
            self.registry(allow())
            (self.repo / REGISTRY).unlink()
            self.assertEqual(self.write(GOOGLE_JSON, content), 0)
            sh(self.repo, "git", "checkout", "--", REGISTRY)
        with self.subTest("committed, then emptied in the working tree"):
            (self.repo / REGISTRY).write_text("")
            self.assertEqual(self.write(GOOGLE_JSON, content), 0)
            sh(self.repo, "git", "checkout", "--", REGISTRY)

    def test_HARN_020_S6_quoted_or_recased_spellings_still_need_the_human(self):
        """The shell check read targets from the unquoted command, so a quoted registry path got
        through, and `keelokit.allowtamper` in another case or in quotes passed the QA-4 check."""
        for cmd in [f'cp x "{REGISTRY}"', f"echo a > '{REGISTRY}'", f'tee -a "{REGISTRY}" < x', f"mv x '{REGISTRY}'",
                    f'sed -i "s/a/b/" "{REGISTRY}"', f'rm "{REGISTRY}"', f'cp x ".keelokit/"guard-allow.toml',
                    f'printf "%s" x >> "{self.repo / REGISTRY}"']:
            with self.subTest(cmd=cmd):
                run = self.run_claude("Bash", command=cmd)
                self.assertEqual(run.returncode, 2)
                self.assertIn("QA-4", run.stderr)
        for cmd in ["git -c keelokit.allowtamper=true commit -m x", "git -c 'keelokit.allowTamper=true' commit -m x",
                    'git -c "KEELOKIT.ALLOWTAMPER=true" commit -m x', "git -c Keelokit.AllowTamper=1 commit -m x",
                    "git config keelokit.allowtamper true", "git config 'keelokit.allowTamper' true"]:
            with self.subTest(cmd=cmd):
                run = self.run_claude("Bash", command=cmd)
                self.assertEqual(run.returncode, 2)
                self.assertIn("QA-4", run.stderr)
        for cmd in ["git commit -m 'never use keelokit.allowTamper casually'",
                    'git commit -m "docs: KEELOKIT.ALLOWTAMPER is the human\'s"', f"cat '{REGISTRY}'"]:
            with self.subTest(cmd=cmd):
                self.assertEqual(self.bash(cmd), 0)

    def test_HARN_020_S4_a_glob_with_a_bracket_is_refused(self):
        """`[!]x][!]x]*` passed the two-literal-characters bound while matching almost any name: only `*`
        and `?` are wildcards, and any `[` or `]` in a glob makes the entry inactive."""
        content = f'{{"current_key": "{GOOGLE_KEY}"}}\n'
        for glob in ["apps/mobile/[!]x][!]x]*", "apps/mobile/google-[a-z]*.json", "apps/mobile/[g]oogle-services.json",
                     "apps/mobile/google-services.json]", "apps/mobile/*.[j]son"]:
            with self.subTest(glob=glob):
                self.registry(allow(path=None, glob=json.dumps(glob)))
                self.assertEqual(self.write(GOOGLE_JSON, content), 2)
                self.assertEqual(self.staged_verdict(GOOGLE_JSON, content), 1)

    def test_HARN_020_S3_no_bash_exemption_once_the_command_changes_directory(self):
        """A relative target is only the registered path from the repo root: after `cd`, `pushd` or
        `popd` the guard can't know where the shell is, so no registered path is let through."""
        self.registry(allow(rule='"SEC-2"', path=None, glob='"infra/*.env"'))
        self.assertEqual(self.bash("cp x infra/prod.env"), 0)
        for cmd in ["cd apps && cp x infra/prod.env", "cd apps; echo A= > infra/prod.env", "pushd apps && cp x infra/prod.env",
                    "popd && cp x infra/prod.env", "(cd apps && cp x infra/prod.env)", "true && cd /tmp && tee infra/prod.env < x"]:
            with self.subTest(cmd=cmd):
                self.assertEqual(self.bash(cmd), 2)

    # INV-002: whatever the registry holds, the guard only blocks or lets through

    def test_INV_002_a_malformed_registry_never_crashes_the_guard_and_exempts_nothing(self):
        content = f'{{"current_key": "{GOOGLE_KEY}"}}\n'
        malformed = {
            "invalid TOML": "[[allow]\nrule =\n", "allow is text": "allow = 'x'\n", "allow holds numbers": "allow = [1, 2]\n",
            "allow is a table": "[allow]\n" + allow()[len("[[allow]]\n"):],
            "every field the wrong kind": "[[allow]]\nrule = 7\npath = 7\nglob = 1.5\nreason = []\napprover = {}\nexpires = 7\n",
            "path is a list": allow(path=f'["{GOOGLE_JSON}"]'), "rule is a list": allow(rule='["SEC-1"]'),
            "expires is a datetime": allow(expires="2999-01-01T00:00:00Z"),
            "not UTF-8": b"[[allow]]\nreason = \"raz\xf3n\"\n" + allow()[len("[[allow]]\n"):].encode(),
            "a NUL": allow(path='"apps/mobile/google-services.json\\u0000"'),
        }
        for why, text in malformed.items():
            with self.subTest(why):
                self.registry(text)
                for verdict, rel, body in [(2, GOOGLE_JSON, content), (0, "src/ok.ts", "export {}\n")]:
                    run = self.run_claude("Write", file_path=str(self.repo / rel), content=body)
                    self.assertIn(run.returncode, (0, 2), run.stderr)
                    self.assertNotIn("Traceback", run.stderr)
                    self.assertEqual(run.returncode, verdict, run.stderr)
                for verdict, rel, body in [(1, GOOGLE_JSON, content), (0, "src/ok.ts", "export {}\n")]:
                    self.stage(rel, body)
                    run = self.run_pre_commit()
                    sh(self.repo, "git", "reset", "-q", "--", rel)
                    self.assertIn(run.returncode, (0, 1), run.stderr)
                    self.assertNotIn("Traceback", run.stderr)
                    self.assertEqual(run.returncode, verdict, run.stderr)
        with self.subTest("the registry is a directory"):
            sh(self.repo, "git", "rm", "-q", REGISTRY)
            sh(self.repo, "git", "commit", "-qm", "rm", "--no-verify")
            (self.repo / REGISTRY).mkdir()
            run = self.run_claude("Write", file_path=str(self.repo / GOOGLE_JSON), content=content)
            self.assertEqual(run.returncode, 2, run.stderr)
            self.assertNotIn("Traceback", run.stderr)
            self.assertEqual(self.claude("Write", file_path=str(self.repo / "src/ok.ts"), content="export {}\n"), 0)
            self.assertEqual(self.staged_verdict("src/ok.ts", "export {}\n"), 0)


DOCTOR = GUARD.parent / "doctor.py"
# (fields as TOML literals, active?) — None: either verdict, as long as guard and doctor agree.
V = {"rule": '"SEC-1"', "path": f'"{GOOGLE_JSON}"', "reason": '"r"', "approver": '"Leo"'}
G = {**V, "path": None, "glob": '"apps/mobile/*.json"'}
ENTRIES = [
    (V, True), ({**V, "rule": '"SEC-2"', "path": '"apps/api/.env.production"'}, True),
    ({**G, "rule": '"SEC-2"', "glob": '"infra/03-env-templates/*.env"'}, True), (G, True),
    ({**G, "glob": '"apps/mobile/google-*.json"'}, True), ({**G, "glob": '"apps/mobile/?oogle-services.json"'}, True),
    ({**V, "expires": '"permanent"'}, True), ({**V, "expires": '"2999-12-31"'}, True), ({**V, "reason": '"razón"'}, True),
    ({**V, "expires": "2999-12-31"}, None),
    ({**V, "rule": '"sec-1"'}, False), ({**V, "rule": '"Sec-2"'}, False), ({**V, "rule": '"SEC-3"'}, False),
    ({**V, "rule": '"QA-4"'}, False), ({**V, "rule": None}, False), ({**V, "rule": "7"}, False),
    ({**V, "reason": None}, False), ({**V, "reason": '""'}, False), ({**V, "reason": '"  "'}, False),
    ({**V, "approver": None}, False), ({**V, "approver": '""'}, False), ({**V, "reason": "[]"}, False),
    ({**V, "glob": '"apps/mobile/*.json"'}, False), ({**V, "path": None}, False),
    ({**V, "path": f'"/{GOOGLE_JSON}"'}, False), ({**V, "path": f'"./{GOOGLE_JSON}"'}, False),
    ({**V, "path": '"apps/../apps/mobile/google-services.json"'}, False), ({**V, "path": '"apps//mobile/google-services.json"'}, False),
    ({**V, "path": '"apps/mobile/"'}, False), ({**V, "path": '"apps/mobile/google-*.json"'}, False),
    ({**V, "path": '"apps/mobile/google-services.jso?"'}, False), ({**V, "path": '"apps/mobile/[g]oogle-services.json"'}, False),
    ({**V, "path": json.dumps("apps\\mobile\\google-services.json")}, False), ({**V, "path": f'["{GOOGLE_JSON}"]'}, False),
    ({**V, "path": "7"}, False),
    ({**G, "glob": '"**/*.json"'}, False), ({**G, "glob": '"apps/**/*.json"'}, False),
    ({**G, "glob": '"apps/*/google-services.json"'}, False), ({**G, "glob": '"*.json"'}, False),
    ({**G, "glob": '"apps/mobile/*"'}, False), ({**G, "glob": '"apps/mobile/*.*"'}, False), ({**G, "glob": '"apps/mobile/?"'}, False),
    ({**G, "glob": '"apps/mobile/*n"'}, False), ({**G, "glob": '"/apps/mobile/*.json"'}, False),
    ({**G, "glob": '"apps/../apps/mobile/*.json"'}, False), ({**G, "glob": '"apps/mobile/[!]x][!]x]*"'}, False),
    ({**G, "glob": '"apps/mobile/google-[a-z]*.json"'}, False), ({**G, "glob": '"apps/mobile/*.json]"'}, False),
    ({**V, "expires": '"2000-01-01"'}, False), ({**V, "expires": "2000-01-01"}, False), ({**V, "expires": '"soon"'}, False),
    ({**V, "expires": '"2026-13-01"'}, False), ({**V, "expires": "7"}, False), ({**V, "expires": "2999-01-01T00:00:00Z"}, False),
]


class GuardDoctorAgreementTest(unittest.TestCase):
    """HARN-020: the guard and the doctor each keep the registry's bounds; the reviewer found them able to
    drift. One table, both verdicts: an entry the guard honours is one the doctor lists, and back."""

    def test_HARN_020_S4_guard_and_doctor_agree_on_every_entry(self):
        import contextlib
        import io
        import sys
        self.assertGreaterEqual(len(ENTRIES), 40)
        spec = importlib.util.spec_from_file_location("guard_eq", GUARD)
        guard = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(guard)
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root)
        for rel in [GOOGLE_JSON, "apps/mobile/other.json", "apps/api/.env.production", "infra/03-env-templates/prod.env",
                    ".keelokit/harness/rules.toml"]:
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text("\n")
        for f in ("product", "domain", "constraints", "environments", "gaps"):
            (root / f"docs/context/{f}.md").parent.mkdir(parents=True, exist_ok=True)
            (root / f"docs/context/{f}.md").write_text(f"# {f}\n")
        (root / ".keelokit/bin").mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
        code = compile(DOCTOR.read_text(), str(DOCTOR), "exec")
        for fields, expected in ENTRIES:
            text = allow(**{**{k: None for k in V}, **fields})  # exactly these fields
            with self.subTest(entry=text.replace("\n", " ")):
                guard_active = bool(guard.active_allowed(text))
                (root / ".keelokit/guard-allow.toml").write_text(text)
                out, argv = io.StringIO(), sys.argv
                sys.argv = ["doctor.py"]
                try:
                    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                        exec(code, {"__name__": "__main__", "__file__": str(root / ".keelokit/bin/doctor.py")})
                except SystemExit:
                    pass
                finally:
                    sys.argv = argv
                doctor_active = not re.search(r"(?m)^  ERROR .*guard-allow\.toml", out.getvalue())
                self.assertEqual(guard_active, doctor_active, out.getvalue())
                if expected is not None:
                    self.assertEqual(guard_active, expected)



# HARN-004: which copy the plugin's hooks run. hooks/hooks.json runs hooks/trusted.py, which runs the plugin's copy
# of the guard, the doctor and the ledger against the project (`--root`), or the project's own copy only when a
# person approved it as it is now; a project's file never runs before that check.
REPO = Path(__file__).resolve().parents[1]
BUNDLED = REPO / "template/.keelokit/bin"
TRUSTED = REPO / "hooks/trusted.py"
BLOCKED = {"tool_name": "Bash", "tool_input": {"command": "git commit --no-verify -m x"}}
HARMLESS = {"tool_name": "Bash", "tool_input": {"command": "ls"}}


def load_trusted():
    spec = importlib.util.spec_from_file_location("keelokit_trusted", TRUSTED)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def hook_command(event: str) -> str:
    data = json.loads((REPO / "hooks/hooks.json").read_text())
    return next(h["command"] for g in data["hooks"][event] for h in g["hooks"] if h.get("type") == "command")


class TrustedProject:
    """A project whose .keelokit/bin is the template's, in a git repo, under a path with a space and a quote."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.proj = self.tmp / "a proj's dir"
        shutil.copytree(BUNDLED, self.proj / ".keelokit/bin", ignore=shutil.ignore_patterns("__pycache__"))
        story = self.proj / "backlog/stories/DEMO-001-x.md"
        story.parent.mkdir(parents=True)
        story.write_text('+++\nid = "DEMO-001"\nepic = "DEMO"\ntitle = "x"\nwave = 1\ndepends_on = []\n+++\n')
        self.git("init", "-q", "-b", "main")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "x")
        self.marks = self.tmp / "marks"
        self.marks.mkdir()

    def env(self, **extra) -> dict:
        env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "CLAUDE_", "PYTHON"))}
        env.update({"HOME": str(self.tmp), "CLAUDE_PROJECT_DIR": str(self.proj), "CLAUDE_PLUGIN_ROOT": str(REPO),
                    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                    "GIT_COMMITTER_EMAIL": "t@t"})
        env.update(extra)
        return env

    def git(self, *args):
        subprocess.run(["git", *args], cwd=self.proj, env=self.env(), check=True, capture_output=True)

    def mark_code(self, name: str) -> str:
        return f"import pathlib; pathlib.Path({str(self.marks / name)!r}).write_text('ran')\n"

    def tamper(self, *names: str) -> None:
        """Each named script, first writing a mark when it runs, then doing what the plugin's copy does."""
        for name in names:
            f = self.proj / ".keelokit/bin" / name
            f.write_text(self.mark_code(name) + f.read_text())

    def ran(self) -> list[str]:
        return sorted(p.name for p in self.marks.iterdir())

    def hook(self, event: str, stdin: dict | None = None, **env) -> subprocess.CompletedProcess:
        return subprocess.run(["/bin/sh", "-c", hook_command(event)], cwd=self.proj, env=self.env(**env),
                              input=json.dumps(stdin or {}), capture_output=True, text=True, timeout=60)

    def with_store(self, *argv: str, stdin: dict | None = None) -> subprocess.CompletedProcess:
        """trusted.py's main, run as the hooks run it."""
        return subprocess.run([sys_python(), "-I", str(TRUSTED), *argv], cwd=self.proj, env=self.env(),
                              input=json.dumps(stdin or {}), capture_output=True, text=True, timeout=60)


class HooksRunTrustedCode(TrustedProject, unittest.TestCase):
    """HARN-004: which copy the hooks run, and the first breaker round."""

    # S1 -------------------------------------------------------------------------------------------------------------

    def test_HARN_004_S1_a_tampered_guard_is_not_executed_and_its_rules_still_hold(self):
        self.tamper("guard.py")
        r = self.hook("PreToolUse", BLOCKED)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("QA-2", r.stderr)
        r = self.hook("PreToolUse", HARMLESS)
        self.assertEqual((r.returncode, r.stdout), (0, ""), r.stderr)
        self.assertEqual(self.ran(), [])

    def test_HARN_004_S1_the_session_start_runs_none_of_the_project_s_copy_and_says_so_once(self):
        self.tamper("guard.py", "doctor.py", "ledger.py", "ux_gate.py")
        r = self.hook("SessionStart")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.ran(), [])
        out = r.stdout.splitlines()
        self.assertLessEqual(len(out), 12, out)
        warned = [l for l in out if "differ from the plugin's" in l]
        self.assertEqual(len(warned), 1, out)
        for name in ("guard.py", "doctor.py", "ledger.py", "ux_gate.py", "harness-upgrade", "git hooks"):
            self.assertIn(name, warned[0])
        self.assertIn("Backlog: 0/1 done", r.stdout, "the doctor still reads this project's backlog")
        self.assertTrue(any(l.startswith("main@") for l in out), "the ledger still reads this project's git")

    def test_HARN_004_S1_only_the_doctor_s_children_tampered_still_run_nothing(self):
        """The doctor runs ledger.py and ux_gate.py: the plugin's doctor runs the plugin's, never the project's."""
        self.tamper("ledger.py", "ux_gate.py")
        r = self.hook("SessionStart")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.ran(), [])
        self.assertIn("Backlog: 0/1 done", r.stdout)

    def test_HARN_004_S1_show_escapes_what_a_terminal_would_hide(self):
        f = self.proj / ".keelokit/bin/guard.py"
        f.write_text(f.read_text() + "x = 1  # ‮)(lave‬ ​ \x1b[2K\r tab\there\n")
        out = self.with_store("show", str(self.proj)).stdout
        self.assertIn("\\u202e", out)
        self.assertIn("\\u200b", out)
        self.assertIn("\\x1b", out)
        self.assertIn("\\x0d", out)
        self.assertIn("\\x09", out)
        for raw in ("‮", "‬", "​", "\x1b", "\r", "\t"):
            self.assertNotIn(raw, out)

    # S2 -------------------------------------------------------------------------------------------------------------

    def test_HARN_004_S2_a_matching_project_sees_what_it_saw_before(self):
        """The plugin's copy with --root says what the project's own copy says, and nothing is warned about."""
        r = self.hook("SessionStart")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("differ from the plugin's", r.stdout)
        today = subprocess.run([sys_python(), ".keelokit/bin/doctor.py", "--brief"], cwd=self.proj, env=self.env(),
                               capture_output=True, text=True, timeout=60).stdout.splitlines()
        self.assertTrue(today)
        self.assertEqual(r.stdout.splitlines()[-len(today):], today)
        summary = subprocess.run([sys_python(), ".keelokit/bin/ledger.py"], cwd=self.proj, env=self.env(),
                                 capture_output=True, text=True, timeout=60).stdout.splitlines()
        for line in summary:
            self.assertIn(line, r.stdout.splitlines())
        for payload in (BLOCKED, HARMLESS, {"tool_name": "Write", "tool_input": {"file_path": ".env", "content": "A=1"}},
                        {"tool_name": "Bash", "tool_input": {"command": "rm .keelokit/guard-allow.toml"}}):
            with self.subTest(payload=payload):
                hooked = self.hook("PreToolUse", payload)
                direct = subprocess.run([sys_python(), ".keelokit/bin/guard.py", "--claude"], cwd=self.proj,
                                        env=self.env(), input=json.dumps(payload), capture_output=True, text=True,
                                        timeout=60)
                self.assertEqual((hooked.returncode, hooked.stdout, hooked.stderr),
                                 (direct.returncode, direct.stdout, direct.stderr))
        self.assertEqual(self.with_store("check").stdout, "")

    def test_HARN_004_S2_the_choice_runs_the_plugin_s_bytes_with_root(self):
        trusted = load_trusted()
        trusted.store_path = lambda: self.store
        for tool in ("guard", "doctor", "ledger"):
            with self.subTest(tool=tool):
                path, data, before = trusted.choose(tool, self.proj)
                self.assertEqual(path, BUNDLED / f"{tool}.py")
                self.assertEqual(data, (BUNDLED / f"{tool}.py").read_bytes())
                self.assertEqual(before, ["--root", str(self.proj)])
        (self.proj / ".keelokit/bin/ledger.py").unlink()
        self.assertIsNone(trusted.choose("ledger", self.proj), "a project without the script: the hook does nothing")

    # Breaker round: ways to get the project's code run before, or instead of, the check. --------------------------

    def test_HARN_004_S1_breaker_planted_modules_and_python_variables_are_never_imported(self):
        planted = ("json", "hashlib", "pathlib", "subprocess", "tomllib", "re", "sitecustomize", "usercustomize",
                   "difflib", "types", "pwd", "shlex", "stat", "tempfile", "unicodedata", "builtins")
        for where in (self.proj, self.proj / ".keelokit/bin", self.proj / ".keelokit"):
            for name in planted:
                (where / f"{name}.py").write_text(self.mark_code(f"{name}-{where.name}"))
        startup = self.proj / "startup.py"
        startup.write_text(self.mark_code("startup"))
        env = {"PYTHONPATH": f"{self.proj}{os.pathsep}{self.proj / '.keelokit/bin'}", "PYTHONSTARTUP": str(startup),
               "PYTHONINSPECT": "1", "PYTHONHOME": str(self.proj)}
        r = self.hook("PreToolUse", BLOCKED, **env)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        r = self.hook("SessionStart", **env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.ran(), [])

    def test_HARN_004_S1_breaker_relative_path_entries_find_no_python3_or_git_of_the_project(self):
        for name in ("python3", "git", "sh", "head", "wc"):
            exe = self.proj / name
            exe.write_text(f"#!/bin/sh\n: > {str(self.marks / name)!r}\nexit 1\n")
            exe.chmod(0o755)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "planted")
        real = os.environ["PATH"]
        for path in (f".{os.pathsep}{real}", f"{os.pathsep}{real}", f"{real}{os.pathsep}", f"bin{os.pathsep}.{os.pathsep}{real}"):
            with self.subTest(path=path):
                r = self.hook("PreToolUse", BLOCKED, PATH=path)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                r = self.hook("SessionStart", PATH=path)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertIn("Backlog: 0/1 done", r.stdout)
                self.assertEqual(self.ran(), [])

    def test_HARN_004_S1_breaker_symlinks_and_special_files_run_nothing_and_hang_nothing(self):
        evil = self.tmp / "evil.py"
        evil.write_text(self.mark_code("evil") + (BUNDLED / "guard.py").read_text())
        guard = self.proj / ".keelokit/bin/guard.py"
        guard.unlink()
        guard.symlink_to(evil)
        r = self.hook("PreToolUse", BLOCKED)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        guard.unlink()
        guard.symlink_to(BUNDLED / "guard.py")  # a link to the plugin's own copy is the plugin's copy
        self.assertEqual(self.hook("PreToolUse", BLOCKED).returncode, 2)
        ledger = self.proj / ".keelokit/bin/ledger.py"
        ledger.unlink()
        os.mkfifo(ledger)  # opened blocking, a FIFO would hang every session start
        r = self.hook("SessionStart")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("differ from the plugin's", r.stdout)
        self.assertEqual(self.ran(), [])

    def test_HARN_004_S1_breaker_hook_environment_edge_cases(self):
        self.tamper("guard.py", "doctor.py", "ledger.py")
        for env in ({"CLAUDE_PLUGIN_ROOT": ""}, {"CLAUDE_PLUGIN_ROOT": str(self.proj)},
                    {"CLAUDE_PLUGIN_ROOT": str(self.tmp / "missing")}):
            for event in ("PreToolUse", "SessionStart"):
                with self.subTest(env=env, event=event):
                    r = self.hook(event, BLOCKED, **env)
                    self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                    if env["CLAUDE_PLUGIN_ROOT"] != str(self.proj):
                        self.assertIn("Reinstall the plugin", r.stdout + r.stderr)
        self.assertEqual(self.ran(), [])
        odd = self.tmp / "-x $(touch pwned) `id` 'q\""
        self.proj.rename(odd)
        self.proj = odd
        r = self.hook("PreToolUse", BLOCKED)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        r = self.hook("SessionStart")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.ran(), [])
        self.assertFalse((self.tmp / "pwned").exists())
        self.assertFalse(Path("pwned").exists())

GITHOOK_MARK = "#!/bin/sh\necho \"$0 $*\" >> {mark}\n"


class HooksRunTrustedCodeRound2(TrustedProject, unittest.TestCase):
    """HARN-004, breaker rounds 2 to 4 (ESC-271, ESC-276..282)."""

    def githook(self, where: Path, name: str) -> None:
        (where / ".githooks").mkdir(exist_ok=True)
        f = where / ".githooks" / name
        f.write_text(GITHOOK_MARK.format(mark=shlex_quote(str(self.marks / name))))
        f.chmod(0o755)

    def config(self, key: str, cwd: Path | None = None) -> str | None:
        r = subprocess.run(["git", "config", "--get", key], cwd=cwd or self.proj, env=self.env(), capture_output=True,
                           text=True)
        return r.stdout.strip() if r.returncode == 0 else None

    # ESC-271: the session start turned the repo's own .githooks on, so its code ran with no approval.

    def test_HARN_004_S1_ESC_271_a_repo_s_own_githooks_stay_off_and_a_commit_runs_none(self):
        self.githook(self.proj, "pre-commit")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "githooks")
        r = self.hook("SessionStart")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIsNone(self.config("core.hooksPath"), "the repo's own .githooks were turned on")
        said = [l for l in r.stdout.splitlines() if ".githooks" in l]
        self.assertEqual(len(said), 1, r.stdout)
        self.assertIn("are off", said[0])
        self.assertIn("git config core.hooksPath .githooks", said[0])
        (self.proj / "notes.txt").write_text("x\n")
        self.git("add", "notes.txt")
        self.git("commit", "-q", "-m", "notes")
        self.assertEqual(self.ran(), [])

    def test_HARN_004_S1_ESC_271_the_plugin_s_own_fetch_fires_no_repo_hook(self):
        """A shallow clone whose hooks path is already .githooks: the ledger's fetch at the session start runs with
        no hooks of the repo's (reference-transaction fires on every ref a fetch writes)."""
        up = self.proj
        self.githook(up, "reference-transaction")
        self.githook(up, "pre-commit")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "githooks")
        (up / "f").write_text("x\n")
        self.git("add", "f")
        self.git("commit", "-q", "-m", "two")
        self.git("branch", "deploy/staging")
        victim = self.tmp / "victim"
        subprocess.run(["git", "clone", "-q", "--depth", "1", f"file://{up}", str(victim)], env=self.env(),
                       check=True, capture_output=True)
        subprocess.run(["git", "config", "core.hooksPath", ".githooks"], cwd=victim, env=self.env(), check=True)
        self.assertEqual(self.ran(), [])
        self.proj = victim
        r = self.hook("SessionStart")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.ran(), [], r.stdout)
        r = self.hook("PreToolUse", BLOCKED)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertEqual(self.ran(), [])

    def test_HARN_004_S1_ESC_271_plugin_githooks_over_a_tampered_bin_stay_off(self):
        """The template's pre-commit runs .keelokit/bin/guard.py: turning it on over a tampered guard.py would run
        the repo's guard at the next commit."""
        shutil.copytree(REPO / "template/.githooks", self.proj / ".githooks")
        self.tamper("guard.py")
        r = self.hook("SessionStart")
        self.assertIsNone(self.config("core.hooksPath"), r.stdout + r.stderr)
        self.assertEqual(self.ran(), [])

    # ESC-277: no hooks of the repo's are ever turned on by the plugin.

    def agent_commit(self) -> None:
        (self.proj / "notes.txt").write_text("x\n")
        subprocess.run("git add notes.txt && git commit -qm 'add notes' -m 'No-story: notes'", shell=True,
                       cwd=self.proj, env=self.env(), capture_output=True)

    def test_HARN_004_S1_ESC_277_even_the_plugin_s_own_githooks_are_never_turned_on(self):
        """The template's hooks run `python3 .keelokit/bin/guard.py` without -I: any module in .keelokit/bin (here a
        fnmatch.py) shadows the standard library there, so even byte-checked hooks would run repo code."""
        shutil.copytree(REPO / "template/.githooks", self.proj / ".githooks")
        (self.proj / ".keelokit/bin/fnmatch.py").write_text(self.mark_code("fnmatch.py"))
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "hooks")
        r = self.hook("SessionStart")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIsNone(self.config("core.hooksPath"), r.stdout)
        said = [l for l in r.stdout.splitlines() if ".githooks" in l]
        self.assertEqual(len(said), 1, r.stdout)
        self.assertIn("are off", said[0])
        self.agent_commit()
        self.assertEqual(self.ran(), [])

    def test_HARN_004_S1_ESC_277_a_branch_s_own_hooks_do_not_run_after_a_switch(self):
        shutil.copytree(REPO / "template/.githooks", self.proj / ".githooks")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "hooks")
        self.git("switch", "-q", "-c", "feature")
        self.githook(self.proj, "post-checkout")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "a branch with its own hook")
        self.git("switch", "-q", "main")
        self.hook("SessionStart")
        self.assertEqual(self.ran(), [])
        self.git("switch", "-q", "feature")
        self.assertEqual(self.ran(), [], "a hook the session start never saw ran at the switch")

    # ESC-278: there is no approval of a project's code, so nothing to forge or race.

    def test_HARN_004_S1_ESC_278_there_is_no_approval_to_forge(self):
        self.tamper("guard.py", "doctor.py", "ledger.py")
        for argv in (["trust", str(self.proj)], ["untrust", str(self.proj)], ["trust"]):
            with self.subTest(argv=argv):
                r = self.with_store(*argv)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        trusted = load_trusted()
        for gone in ("store_path", "read_store", "write_store", "approved", "trust", "ask", "fingerprint"):
            self.assertFalse(hasattr(trusted, gone), f"trusted.py still has {gone}")

        def never(path):
            raise AssertionError(f"the project's {path} was read to decide what runs")

        trusted.regular_bytes = never
        for tool in ("guard", "doctor", "ledger"):
            with self.subTest(tool=tool):
                path, data, before = trusted.choose(tool, self.proj)
                self.assertEqual((path, before), (BUNDLED / f"{tool}.py", ["--root", str(self.proj)]))
        r = self.hook("SessionStart")
        self.assertNotIn("trust", r.stdout.replace("trusted", ""), "the start no longer offers an approval")
        self.assertEqual(self.ran(), [])

    # ESC-279: the guard's own CPU.

    def test_HARN_004_S1_ESC_279_the_guard_s_patterns_finish_on_pathological_input(self):
        code = ("import sys; sys.argv = ['g']\n"
                f"sys.path.insert(0, {str(BUNDLED)!r}); import guard\n"
                "pre, piece, fn = sys.stdin.read().split('\\0')\n"
                "s = pre + piece * (200_000 // len(piece))\n"
                "getattr(guard, fn)(*([s, []] if fn == 'bash_problem' else [s]))\n")
        cases = [("postgres://a:", "${{", "secret_in"), ("https://u:", "${{", "secret_in"),
                 ("// postgres://a:", "${{", "secret_in"), ("git ", "-C ", "bash_problem"),
                 ("git -C ", "-c ", "bash_problem"), ("git ", "--git-dir ", "bash_problem"), ("", "git ", "bash_problem"),
                 ("git ", "-c a=b ", "bash_problem"), ("", "${{ true }}", "tamper_in"), ("", "it.skip ", "tamper_in"),
                 ("", "\n", "bash_problem"), ("git ", "|", "bash_problem"), ("echo x > ", "|", "bash_problem"),
                 ("", "echo x|", "bash_problem")]
        for pre, piece, fn in cases:
            with self.subTest(pre=pre, piece=piece, fn=fn):
                r = subprocess.run([sys_python(), "-I", "-c", code], input=f"{pre}\0{piece}\0{fn}", text=True,
                                   capture_output=True, timeout=20, env=self.env())
                self.assertEqual(r.returncode, 0, r.stderr)
        payload = {"tool_name": "Write", "tool_input": {"file_path": str(self.proj / "src/a.ts"),
                                                         "content": "// postgres://a:" + "${{" * 45000 + "\n"}}
        r = subprocess.run(["/bin/sh", "-c", hook_command("PreToolUse")], cwd=self.proj, env=self.env(),
                           input=json.dumps(payload), capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_HARN_004_S1_ESC_279_a_guard_that_does_not_answer_is_killed_and_the_call_blocked(self):
        plugin = self.tmp / "plugin"
        (plugin / "hooks").mkdir(parents=True)
        shutil.copy(TRUSTED, plugin / "hooks/trusted.py")
        (plugin / "template/.keelokit/bin").mkdir(parents=True)
        (plugin / "template/.keelokit/bin/guard.py").write_text(
            "import pathlib, subprocess, time\n"
            f"subprocess.Popen(['sleep', '30'])\n"
            f"pathlib.Path({str(self.marks / 'started')!r}).write_text('x')\n"
            "time.sleep(30)\n")
        r = self.hook("PreToolUse", HARMLESS, CLAUDE_PLUGIN_ROOT=str(plugin), KEELOKIT_GUARD_SECONDS="1")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertEqual(len(r.stderr.strip().splitlines()), 1, r.stderr)
        self.assertIn("did not answer", r.stderr)
        self.assertEqual(self.ran(), ["started"], "the guard did run, and was stopped")

    def test_HARN_004_ESC_279_the_guard_s_time_is_never_more_than_its_bound(self):
        trusted = load_trusted()
        cases = {"1000": trusted.GUARD_SECONDS, "abc": trusted.GUARD_SECONDS, "nan": trusted.GUARD_SECONDS,
                 "-5": 0.1, "0.5": 0.5, "": trusted.GUARD_SECONDS}
        for value, expected in cases.items():
            with self.subTest(value=value), unittest.mock.patch.dict(os.environ, {"KEELOKIT_GUARD_SECONDS": value}):
                self.assertEqual(trusted.guard_seconds(), expected)
        data = json.loads((REPO / "hooks/hooks.json").read_text())
        self.assertGreaterEqual(data["hooks"]["PreToolUse"][0]["hooks"][0]["timeout"], trusted.GUARD_SECONDS + 10)

    # ESC-280: a bare-repository-looking directory the repo ships is not a repository to the plugin's git.

    def shipped_bare(self, lazy: bool) -> Path:
        """A repo whose pkg/ looks like a bare repository (HEAD, config, objects/, refs/ are ordinary files), with a
        pkg/config whose remote runs a command; the clone's pkg/ is the project opened."""
        up = self.tmp / "up"
        pkg = up / "pkg"
        shutil.copytree(BUNDLED, pkg / ".keelokit/bin", ignore=shutil.ignore_patterns("__pycache__"))
        (pkg / "objects/info").mkdir(parents=True)
        (pkg / "refs/heads").mkdir(parents=True)
        (pkg / "objects/info/.keep").write_text("")
        (pkg / "refs/heads/.keep").write_text("")
        (pkg / "HEAD").write_text("ref: refs/heads/main\n")
        if lazy:  # a commit whose tree is missing: reading it makes git fetch from the promisor remote
            scratch = self.tmp / "scratch"
            env0 = self.env(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
            subprocess.run(["git", "init", "-q", str(scratch)], env=env0, check=True, capture_output=True)
            (scratch / "f").write_text("x\n")
            subprocess.run(["git", "-C", str(scratch), "add", "f"], env=env0, check=True, capture_output=True)
            tree = subprocess.run(["git", "-C", str(scratch), "write-tree"], env=env0, check=True, capture_output=True,
                                  text=True).stdout.strip()
            commit = subprocess.run(["git", "-C", str(scratch), "commit-tree", "-m", "x", tree], env=env0, check=True,
                                    capture_output=True, text=True).stdout.strip()
            (pkg / "objects" / commit[:2]).mkdir()
            shutil.copy(scratch / ".git/objects" / commit[:2] / commit[2:], pkg / "objects" / commit[:2] / commit[2:])
            (pkg / "refs/heads/main").write_text(commit + "\n")
        mark = shlex_quote(str(self.marks / ("lazy" if lazy else "fetch")))
        url = f"ext::sh -c touch% {mark.replace(' ', '% ')}"
        lazy_cfg = "[extensions]\n\tpartialClone = origin\n" if lazy else ""
        (pkg / "config").write_text(f"[core]\n\trepositoryformatversion = {1 if lazy else 0}\n{lazy_cfg}"
                                    f"[protocol \"ext\"]\n\tallow = always\n[remote \"origin\"]\n"
                                    f"\tpromisor = true\n\turl = \"{url}\"\n")
        env = self.env(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
        for argv in (["init", "-q", "-b", "main", str(up)], ["-C", str(up), "add", "-A"],
                     ["-C", str(up), "commit", "-q", "-m", "one"],
                     ["clone", "-q", f"file://{up}", str(self.tmp / "victim")]):
            subprocess.run(["git", *argv], env=env, check=True, capture_output=True)
        return self.tmp / "victim/pkg"

    def test_HARN_004_S1_ESC_280_a_shipped_bare_repo_runs_nothing_at_the_session_start(self):
        self.proj = self.shipped_bare(lazy=False)
        r = self.hook("SessionStart", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.ran(), [], r.stdout + r.stderr)

    def test_HARN_004_S1_ESC_280_a_shipped_bare_repo_runs_nothing_from_the_guard(self):
        self.proj = self.shipped_bare(lazy=True)
        env = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
        r = self.hook("PreToolUse", HARMLESS, **env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = self.hook("PreToolUse", {"tool_name": "Write", "tool_input": {"file_path": str(self.proj / "notes.md"),
                                                                         "content": "hi"}}, **env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = self.hook("PreToolUse", BLOCKED, **env)
        self.assertEqual(r.returncode, 2, "the guard still answers: " + r.stderr)
        self.assertEqual(self.ran(), [])

    def test_HARN_004_S1_ESC_280_a_git_dir_inside_the_project_blocks_the_guard(self):
        inner = self.proj / "inner.git"
        subprocess.run(["git", "init", "-q", "--bare", str(inner)], env=self.env(), check=True, capture_output=True)
        shutil.rmtree(self.proj / ".git")
        (self.proj / ".git").write_text("gitdir: inner.git\n")
        r = self.hook("PreToolUse", HARMLESS)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertEqual(len(r.stderr.strip().splitlines()), 1, r.stderr)
        self.assertIn("inner.git", r.stderr)
        r = self.hook("SessionStart")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("inner.git", r.stdout)

    def test_HARN_004_ESC_280_every_git_call_of_the_plugin_runs_hardened(self):
        """Each script, run with --root, sets the same git environment before its first git call."""
        for name in ("guard.py", "ledger.py", "doctor.py", "ux_gate.py"):
            with self.subTest(script=name):
                code = ("import os, runpy, sys, json\n"
                        f"sys.argv = [{str(BUNDLED / name)!r}, '--root', {str(self.proj)!r}, '--help']\n"
                        "try:\n"
                        f"    runpy.run_path(sys.argv[0], run_name='not_main')\n"
                        "except SystemExit:\n    pass\n"
                        "n = int(os.environ.get('GIT_CONFIG_COUNT', '0'))\n"
                        "cfg = {os.environ[f'GIT_CONFIG_KEY_{i}']: os.environ[f'GIT_CONFIG_VALUE_{i}'] for i in range(n)}\n"
                        "print(json.dumps({'cfg': cfg, 'env': {k: os.environ.get(k) for k in "
                        "('GIT_NO_LAZY_FETCH', 'GIT_TERMINAL_PROMPT', 'GIT_PROTOCOL_FROM_USER')}}))\n")
                r = subprocess.run([sys_python(), "-I", "-c", code], env=self.env(GIT_DIR="/elsewhere"),
                                   capture_output=True, text=True, timeout=60)
                got = json.loads(r.stdout.strip().splitlines()[-1])
                for key, value in (("safe.bareRepository", "explicit"), ("protocol.ext.allow", "never"),
                                   ("core.fsmonitor", "false")):
                    self.assertEqual(got["cfg"].get(key), value, (key, r.stderr))
                self.assertEqual(got["env"], {"GIT_NO_LAZY_FETCH": "1", "GIT_TERMINAL_PROMPT": "0",
                                              "GIT_PROTOCOL_FROM_USER": "0"})

    # ESC-281: any failure of the hook's own path is a block, never Python's exit 1.

    def test_HARN_004_S1_ESC_281_a_fork_that_fails_blocks(self):
        code = ("import errno, os, runpy, sys\n"
                "def fork(): raise BlockingIOError(errno.EAGAIN, 'Resource temporarily unavailable')\n"
                "os.fork = fork\n"
                f"sys.argv = [{str(TRUSTED)!r}, 'run', 'guard', '--claude']\n"
                "runpy.run_path(sys.argv[0], run_name='__main__')\n")
        r = subprocess.run([sys_python(), "-I", "-c", code], cwd=self.proj, env=self.env(), input=json.dumps(HARMLESS),
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertEqual(len(r.stderr.strip().splitlines()), 1, r.stderr)

    def test_HARN_004_S1_ESC_281_a_guard_that_crashes_or_exits_1_blocks(self):
        for body in ("raise RuntimeError('boom')\n", "import sys; sys.exit(1)\n", "import os, signal\nos.kill(os.getpid(), signal.SIGINT)\n",
                     "import os, signal\nos.kill(os.getpid(), signal.SIGTERM)\n"):
            with self.subTest(body=body):
                plugin = self.tmp / "plugin"
                shutil.rmtree(plugin, ignore_errors=True)
                (plugin / "hooks").mkdir(parents=True)
                shutil.copy(TRUSTED, plugin / "hooks/trusted.py")
                (plugin / "template/.keelokit/bin").mkdir(parents=True)
                (plugin / "template/.keelokit/bin/guard.py").write_text(body)
                r = self.hook("PreToolUse", HARMLESS, CLAUDE_PLUGIN_ROOT=str(plugin))
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertTrue(r.stderr.strip().splitlines()[-1].startswith("Keelokit guard:"), r.stderr)

    # ESC-282: the guard ran only while the project's guard.py was there, though it never runs that file.

    def test_HARN_004_S1_ESC_282_removing_the_project_s_guard_py_leaves_the_guard_on(self):
        (self.proj / ".keelokit/bin/guard.py").unlink()
        r = self.hook("PreToolUse", BLOCKED)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        shutil.rmtree(self.proj / ".keelokit/bin")
        r = self.hook("PreToolUse", BLOCKED)
        self.assertEqual(r.returncode, 2, "a .keelokit without bin/ is still a Keelokit project: " + r.stderr)

    def test_HARN_004_S1_ESC_282_the_guard_refuses_removing_the_harness_as_a_whole(self):
        for cmd in ("rm -rf .keelokit", "rm -r .keelokit/", "rm -rf ./.keelokit/bin", "mv .keelokit /tmp/x",
                    "git rm -r -q .keelokit/bin", "find .keelokit -delete", "rmdir .keelokit/bin",
                    f"rm -rf {shlex_quote(str(self.proj / '.keelokit'))}", "mv .keelokit/bin .keelokit/old"):
            with self.subTest(cmd=cmd):
                r = self.hook("PreToolUse", {"tool_name": "Bash", "tool_input": {"command": cmd}})
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertIn("QA-2", r.stderr)
        for cmd in ("rm .keelokit/bin/notes.tmp", "ls .keelokit", "rm -rf node_modules", "cat .keelokit/bin/guard.py"):
            with self.subTest(allowed=cmd):
                r = self.hook("PreToolUse", {"tool_name": "Bash", "tool_input": {"command": cmd}})
                self.assertEqual(r.returncode, 0, r.stderr)

    # Cold breaker, round 1 (ESC-283..285).

    def bash(self, cmd: str, tool: str = "Bash") -> subprocess.CompletedProcess:
        return self.hook("PreToolUse", {"tool_name": tool, "tool_input": {"command": cmd}})

    def test_HARN_004_S1_ESC_283_quoted_spellings_of_a_hook_bypass_are_blocked(self):
        for cmd in ("git commit '--no-verify' -m x", 'git commit --no-ver""ify -m x', "git commit -\"n\" -m x",
                    "git -c alias.c='commit --no-verify' c -m x", "git -c core.hooks''Path=/dev/null commit -m x",
                    "git push '--no-verify'", "git commit --no-veri\\fy -m x"):
            with self.subTest(cmd=cmd):
                r = self.bash(cmd)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertIn("QA-2", r.stderr)
        for cmd in ('git commit -m "why we never use --no-verify"', "git commit -m 'a -n flag'", "git log -n 3"):
            with self.subTest(allowed=cmd):
                self.assertEqual(self.bash(cmd).returncode, 0)

    def test_HARN_004_S1_ESC_284_globs_and_target_directories_cannot_remove_the_harness(self):
        for cmd in ("rm -rf .keel*", "rm -rf .keelokit/b?n", "rm -rf .[k]eelokit", "mv -t /tmp/x .keelokit",
                    "mv --target-directory=/tmp/x .keelokit/bin", "mv --target-directory /tmp/x .keelokit"):
            with self.subTest(cmd=cmd):
                r = self.bash(cmd)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertIn("QA-2", r.stderr)
        for cmd in ("rm -rf *.log", "rm -rf build/*", "mv -t /tmp/x notes.txt"):
            with self.subTest(allowed=cmd):
                self.assertEqual(self.bash(cmd).returncode, 0)

    def test_HARN_004_S1_ESC_284_a_committed_harness_gone_from_disk_keeps_the_guard_on(self):
        shutil.rmtree(self.proj / ".keelokit")
        r = self.bash("git commit --no-verify -m x")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        other = self.tmp / "plain repo"
        subprocess.run(["git", "init", "-q", str(other)], env=self.env(), check=True, capture_output=True)
        r = subprocess.run(["/bin/sh", "-c", hook_command("PreToolUse")], cwd=other,
                           env=self.env(CLAUDE_PROJECT_DIR=str(other)), input=json.dumps(BLOCKED),
                           capture_output=True, text=True, timeout=60)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""), "a repo that never had Keelokit is left alone")

    def test_HARN_004_S1_ESC_285_every_tool_that_runs_a_shell_command_is_guarded(self):
        data = json.loads((REPO / "hooks/hooks.json").read_text())
        matcher = data["hooks"]["PreToolUse"][0]["matcher"]
        for tool in ("Bash", "Monitor", "PowerShell", "Edit", "Write", "MultiEdit", "NotebookEdit"):
            self.assertTrue(re.fullmatch(f"(?:{matcher})", tool), tool)
        for tool in ("Monitor", "PowerShell"):
            with self.subTest(tool=tool):
                r = self.bash("git commit --no-verify -m x", tool=tool)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)

    # Cold breaker, round 2 (ESC-286..289).

    def test_HARN_004_S1_ESC_286_an_orphan_branch_or_a_path_spelt_through_pwd_cannot_turn_the_guard_off(self):
        self.git("remote", "add", "origin", str(self.proj))
        self.git("fetch", "-q", "origin")
        self.git("remote", "set-head", "origin", "main")
        for cmd in ('rm -rf "$PWD/.keelokit"', "rm -rf $(pwd)/.keelokit", "rm -rf ${PWD}/.keelokit/bin",
                    "cd .. && rm -rf proj/.keelokit", "rm -rf `pwd`/.keelokit"):
            with self.subTest(cmd=cmd):
                r = self.bash(cmd)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.git("switch", "-q", "--orphan", "empty")
        shutil.rmtree(self.proj / ".keelokit", ignore_errors=True)
        r = self.bash("git commit --no-verify -m x")
        self.assertEqual(r.returncode, 2, "the trunk the clone came from still has .keelokit: " + r.stderr)

    def test_HARN_004_S1_ESC_287_more_ways_to_skip_the_hooks_are_blocked(self):
        for cmd in ("bash -c 'git commit --no-verify -m x'", 'eval "git commit -n -m x"', "sh -c \"git push -f\"",
                    "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.hooksPath GIT_CONFIG_VALUE_0=/dev/null git commit -m x",
                    "GIT_CONFIG_PARAMETERS=\"'core.hooksPath'='/dev/null'\" git commit -m x",
                    "export GIT_CONFIG_KEY_0=core.hookspath", "git -c include.path=/tmp/x.cfg commit -m x",
                    "git config include.path /tmp/x.cfg", "git config alias.ci 'commit --no-verify'",
                    "git config --local alias.ci 'commit -n'", "printf '[core]\\n\\thooksPath = /dev/null\\n' >> .git/config",
                    "git -c remote.origin.push=+refs/heads/main:refs/heads/main push",
                    "git config remote.origin.push '+refs/heads/*:refs/heads/*'"):
            with self.subTest(cmd=cmd):
                r = self.bash(cmd)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        for tool, args in (("Write", {"file_path": ".git/config", "content": "[core]\n\thooksPath = /dev/null\n"}),
                           ("Edit", {"file_path": str(self.proj / ".git/config"), "old_string": "a", "new_string": "b"}),
                           ("Write", {"file_path": ".git/hooks/pre-commit", "content": "exit 0\n"})):
            with self.subTest(tool=tool, args=args):
                r = self.hook("PreToolUse", {"tool_name": tool, "tool_input": args})
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        for cmd in ("bash -c 'git status'", "git config user.name T", "git config alias.st status", "eval \"ls\""):
            with self.subTest(allowed=cmd):
                self.assertEqual(self.bash(cmd).returncode, 0)

    def test_HARN_004_S1_ESC_288_only_the_repo_s_own_env_example_seeds_a_real_env(self):
        for cmd in ("cp /tmp/mine.example .env", "cp x.example .env.production", "cp ../x.example .envrc",
                    "cp /tmp/.env.example .env"):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.bash(cmd).returncode, 2)
        for cmd in ("cp .env.example .env", "cp apps/api/.env.example apps/api/.env", "cp .env.local.example .env.local"):
            with self.subTest(allowed=cmd):
                self.assertEqual(self.bash(cmd).returncode, 0, self.bash(cmd).stderr)

    def test_HARN_004_S1_ESC_289_the_plugin_s_own_files_cannot_be_removed_or_rewritten(self):
        home_plugins = Path(load_trusted().__file__).parent  # stands in for nothing: the env names the root
        for cmd in (f"rm {TRUSTED}", f"rm -rf {REPO / 'hooks'}", f"mv {TRUSTED} /tmp/x", f"echo x > {TRUSTED}",
                    "rm -rf ~/.claude/plugins/cache"):
            with self.subTest(cmd=cmd):
                r = self.bash(cmd)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        r = self.hook("PreToolUse", {"tool_name": "Write", "tool_input": {"file_path": str(TRUSTED), "content": "x"}})
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertTrue(home_plugins.exists())

    # Cold breaker, round 3 (ESC-290..294).

    def test_HARN_004_S1_ESC_290_git_mv_and_an_orphan_branch_cannot_take_the_harness_away(self):
        for cmd in ("git mv .keelokit .keelokit-old", "git mv -f .keelokit/bin old-bin", "git switch --orphan scratch",
                    "git checkout --orphan scratch", "git switch -q --orphan=x"):
            with self.subTest(cmd=cmd):
                r = self.bash(cmd)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        for cmd in ("git mv src/a.py src/b.py", "git switch -c feature", "git checkout main"):
            with self.subTest(allowed=cmd):
                self.assertEqual(self.bash(cmd).returncode, 0)

    def test_HARN_004_S1_ESC_291_hooks_a_person_turned_on_cannot_be_rewritten_or_removed(self):
        shutil.copytree(REPO / "template/.githooks", self.proj / ".githooks")
        cmds = ("rm -rf .githooks", "chmod -x .githooks/pre-commit", "echo 'exit 0' > .githooks/pre-commit",
                "printf 'x' > .keelokit/bin/guard.py", "mv .githooks/commit-msg /tmp/x")
        writes = ({"file_path": ".githooks/pre-commit", "content": "exit 0\n"},
                  {"file_path": str(self.proj / ".keelokit/bin/guard.py"), "content": "x"},
                  {"file_path": ".keelokit/bin/ledger.py", "content": "x"})
        for cmd in cmds:  # hooks off: these are the repo's files like any other
            with self.subTest(off=cmd):
                self.assertEqual(self.bash(cmd).returncode, 0)
        self.git("config", "core.hooksPath", ".githooks")
        for cmd in cmds:
            with self.subTest(on=cmd):
                r = self.bash(cmd)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertIn("QA-2", r.stderr)
        for args in writes:
            with self.subTest(write=args["file_path"]):
                r = self.hook("PreToolUse", {"tool_name": "Write", "tool_input": args})
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertEqual(self.bash("echo x > src/notes.txt").returncode, 0)

    def test_HARN_004_S1_ESC_292_the_hooks_path_cannot_go_through_a_section_or_the_worktree_config(self):
        for cmd in ("git config --remove-section core", "git config --rename-section core old",
                    "printf '[core]\\n\\thooksPath = /dev/null\\n' >> .git/config.worktree"):
            with self.subTest(cmd=cmd):
                r = self.bash(cmd)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        r = self.hook("PreToolUse", {"tool_name": "Write", "tool_input": {"file_path": ".git/config.worktree",
                                                                         "content": "[core]\n"}})
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertEqual(self.bash("git config --remove-section alias").returncode, 0)

    def test_HARN_004_S1_ESC_293_clobber_redirects_continuations_and_install_are_read(self):
        for cmd in ("echo KEY=1 >| .env", "echo x >| .git/hooks/pre-commit", "echo x >| .keelokit/guard-allow.toml",
                    "printf '[core]' >| .git/config", "git \\\n  commit -n -m x", "git commit \\\n --no-verify -m x",
                    "install -m 600 /dev/null .env"):
            with self.subTest(cmd=cmd):
                r = self.bash(cmd)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertEqual(self.bash("ls | wc -l").returncode, 0)

    def test_HARN_004_S1_ESC_294_claude_code_s_own_hooks_and_the_plugin_cannot_be_switched_off(self):
        for cmd in ("echo '{\"disableAllHooks\":true}' > .claude/settings.local.json", "claude plugin disable keelokit",
                    "claude plugin uninstall keelokit@keelokit", "rm -rf ~/.claude", "mv ~/.claude ~/.claude.bak",
                    "rm -rf $HOME/.claude/plugins"):
            with self.subTest(cmd=cmd):
                r = self.bash(cmd)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        for path in (".claude/settings.local.json", ".claude/settings.json", "~/.claude/settings.json"):
            with self.subTest(path=path):
                r = self.hook("PreToolUse", {"tool_name": "Write", "tool_input": {
                    "file_path": path, "content": '{"disableAllHooks": true}'}})
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        r = self.hook("PreToolUse", {"tool_name": "Write", "tool_input": {
            "file_path": ".claude/settings.json", "content": '{"permissions": {"allow": ["Bash(ls)"]}}'}})
        self.assertEqual(r.returncode, 0, "ordinary settings are the project's: " + r.stderr)

    # ESC-276: a guard that outlives the hook's timeout lets the call through.

    def test_HARN_004_S1_ESC_276_the_guard_blocks_on_data_it_cannot_read_in_bounds(self):
        state = self.proj / ".keelokit/state.toml"
        edit = {"tool_name": "Edit", "tool_input": {"file_path": str(state), "old_string": "a", "new_string": "b"}}
        os.mkfifo(state)
        r = self.hook("PreToolUse", edit)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertEqual(len(r.stderr.strip().splitlines()), 1, r.stderr)
        state.unlink()
        state.write_text("[ledger]\n" + "# pad\n" * (300 << 10))
        r = self.hook("PreToolUse", edit)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertEqual(len(r.stderr.strip().splitlines()), 1, r.stderr)
        state.unlink()
        allow = self.proj / ".keelokit/guard-allow.toml"
        allow.write_text("# pad\n" * (300 << 10))
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "a big registry")
        r = self.hook("PreToolUse", {"tool_name": "Write", "tool_input": {"file_path": ".env", "content": "A=1"}})
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        r = self.hook("PreToolUse", HARMLESS)
        self.assertEqual(r.returncode, 2, "a registry over the bound blocks every call: " + r.stderr)
        self.assertEqual(len(r.stderr.strip().splitlines()), 1, r.stderr)

    def test_HARN_004_ESC_276_the_pre_tool_use_hook_has_room_for_the_guard_s_own_limits(self):
        data = json.loads((REPO / "hooks/hooks.json").read_text())
        hook = data["hooks"]["PreToolUse"][0]["hooks"][0]
        guard = (BUNDLED / "guard.py").read_text()
        limit = int(re.search(r"^GIT_SECONDS = (\d+)", guard, re.M).group(1))
        self.assertIn("timeout", hook, "the hook's timeout is stated, not Claude Code's default")
        self.assertGreaterEqual(hook["timeout"], limit + 20, "the guard's git calls end well within the hook's timeout")


def shlex_quote(s: str) -> str:
    import shlex
    return shlex.quote(s)


def sys_python() -> str:
    return shutil.which("python3") or "python3"


if __name__ == "__main__":
    unittest.main()
