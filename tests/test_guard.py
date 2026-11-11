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


if __name__ == "__main__":
    unittest.main()
