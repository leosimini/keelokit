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
                self.assertEqual(run.returncode, 2)
                self.assertIn("Keelokit guard: couldn't read the hook input", run.stderr)
                self.assertNotIn("Traceback", run.stderr)

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


if __name__ == "__main__":
    unittest.main()
