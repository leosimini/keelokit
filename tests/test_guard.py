"""Guard behaviour: what it blocks and what it must let through. Run: python3 -m unittest discover -s tests"""
import importlib.util
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

GUARD = Path(__file__).resolve().parents[1] / "template/.keelokit/bin/guard.py"
_spec = importlib.util.spec_from_file_location("keelokit_guard", GUARD)
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)

# One sample per content rule. Adding a TAMPER or SECRETS pattern without a sample here fails
# test_LOG1_every_content_rule_holds_on_every_bash_writer, so no rule is checked on Edit only.
TAMPER_SAMPLES = ["it.skip(", "test.only(", "xit(", "// eslint-disable-next-line", "// @ts-nocheck",
                  "continue-on-error: true"]
SECRET_SAMPLES = ["AKIA" + "A" * 16, "-----BEGIN RSA PRIVATE KEY-----", "ghp_" + "a" * 36,
                  "github_pat_" + "A" * 50, "xoxb-" + "1" * 12, "sk_live_" + "a" * 20, "sk-ant-" + "a" * 30,
                  "sk-proj-" + "a" * 40, "AIza" + "B" * 35, "https://u:tok@github.com",
                  "postgres://u:p4ss@db.example.com:5432/x"]
# Every shell-level way a command puts text into a file: {x} is the text, {f} the file.
BASH_WRITERS = [
    "echo '{x}' >> {f}",
    "printf '%s\\n' \"{x}\" > {f}",
    "cat > {f} <<'EOF'\nconst a = 1\n{x}\nEOF",
    "cat <<EOF | tee -a {f}\n{x}\nEOF",
    "echo '{x}' | tee {f} >/dev/null",
    "tee {f} <<< '{x}'",
    "sed -i '1i {x}' {f}",
    "sed -i '/^import/a {x}' {f}",
    "perl -pi -e 's/^/{x}/' {f}",
    "bash -c \"echo '{x}' >> {f}\"",
]
# Every program the guard treats as running code (guard.INTERPRETERS), with how it takes code
# inline and code that writes {x} into {f}. An interpreter added to the guard without a sample
# here fails test_LOG1_every_content_rule_holds_on_every_bash_writer.
NODE_CODE = "require('fs').appendFileSync('{f}', '{x}')"
INTERPRETER_SAMPLES = {
    "python3": (["-c "], "open('{f}', 'a').write('{x}')"),
    "pypy3": (["-c "], "open('{f}', 'a').write('{x}')"),
    "node": (["-e ", "--eval=", "-p "], NODE_CODE),
    "deno": (["eval "], "Deno.writeTextFileSync('{f}', '{x}')"),
    "bun": (["-e ", "--eval="], NODE_CODE),
    "tsx": (["-e ", "--eval="], NODE_CODE),
    "ts-node": (["-e ", "--eval="], NODE_CODE),
    "ruby": (["-e "], "File.write('{f}', '{x}')"),
    "perl": (["-e ", "-E "], "open(F, '>>{f}'); print F '{x}'"),
    "php": (["-r "], "file_put_contents('{f}', '{x}');"),
    "lua": (["-e "], "io.open('{f}', 'a'):write('{x}')"),
}
# Every way to hand an interpreter its code: {i} the program, {e} its inline flag, {c} the code.
CODE_ROUTES = [
    "{i} {e}\"{c}\"",
    "npx {i} {e}\"{c}\"",
    "{i} <<'EOF'\n{c}\nEOF",
    "{i} <<< \"{c}\"",
    "echo \"{c}\" | {i}",
]
# awk takes its program as the first argument and writes with print … > "file".
AWK_WRITERS = ["awk 'BEGIN {{ print \"{x}\" > \"{f}\" }}'", "gawk 'BEGIN {{ printf \"{x}\" >> \"{f}\" }}' /dev/null"]


def every_writer(x: str, f: str) -> list[str]:
    """Every Bash command in the tests that writes x into f."""
    cmds = [form.format(x=x, f=f) for form in BASH_WRITERS + AWK_WRITERS]
    for name, (flags, code) in INTERPRETER_SAMPLES.items():
        c = code.format(x=x, f=f)
        for route in CODE_ROUTES:
            for e in flags if "{e}" in route else [""]:
                cmds.append(route.replace("{i}", name).replace("{e}", e).replace("{c}", c))
    return cmds

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

    def test_LOG1_bash_writes_get_the_edit_content_rules(self):
        """LOG-1: an Edit that adds it.skip is blocked; the same text written from Bash went through."""
        for cmd in [
            "echo 'it.skip(x)' >> src/foo.test.ts",
            "cat >> src/foo.test.ts <<EOF\nit.skip('x', () => {})\nEOF",
            "sed -i '1i // eslint-disable' src/foo.ts",
            "sed -i '1i /* eslint-disable */' src/foo.ts",
            "sed -i '/describe(/a it.only(1)' src/a.test.ts",
            "sed -i '/eslint-disable/a // @ts-ignore' src/a.ts",
            "sed -i '1i\\\n/* eslint-disable */ declare const a: 1' src/a.ts",
            "git add -A && echo '// @ts-ignore' >> src/a.ts",
            "python3 -c \"print('it.skip(1)')\" > src/a.test.ts",
            "perl -e 'open(F, \">>src/a.ts\"); print F \"// eslint-disable\\n\"'",
            "npx tsx -e \"require('fs').writeFileSync('src/a.test.ts', 'it.only(1)')\"",
            "awk 'BEGIN{print \"// eslint-disable\" > \"src/a.ts\"}'",
            "python3 - <<'PY'\np = open('src/a.ts', 'a')\np.write('x'.replace('x', '// eslint-disable'))\nPY",
        ]:
            with self.subTest(cmd=cmd):
                self.assertEqual(self.bash(cmd), 2)
        # SEC-2 from the same finding: an interpreter writing .env with no recognisable secret in it.
        for cmd in [
            "python3 -c \"open('.env','a').write('STRIPE_WEBHOOK_SECRET=whsec_a1b2c3d4e5f6')\"",
            "node -e \"require('fs').writeFileSync('apps/api/.env', 'A=1')\"",
            "python3 <<'EOF'\nfrom pathlib import Path\nPath(\"apps/web/.env.local\").write_text(\"A=1\")\nEOF",
            "bash -c 'echo A=1 > .env'",
            "echo \"open('.env','w').write('A=1')\" | python3",
            "node --eval=\"require('fs').writeFileSync('.env','A=1')\"",
            "npx tsx -e \"require('fs').writeFileSync('.env','A=1')\"",
            "awk 'BEGIN{print \"A=1\" > \".env\"}'",
            "python3 -c \"import sys; open(sys.argv[1],'w').write('A=1')\" .env",
            "printf 'A=1' | node -e \"process.stdin.pipe(require('fs').createWriteStream('.env'))\"",
        ]:
            with self.subTest(cmd=cmd):
                self.assertEqual(self.bash(cmd), 2)

    def test_LOG1_every_content_rule_holds_on_every_bash_writer(self):
        """The class: every rule the Edit path checks on new text holds for every Bash writer,
        and every program the guard knows runs code is tried on every way of handing it code."""
        for rules, samples in [(guard.TAMPER, TAMPER_SAMPLES), (guard.SECRETS, SECRET_SAMPLES)]:
            for pattern, label in rules:
                with self.subTest(rule=label):
                    self.assertTrue(any(re.search(pattern, x) for x in samples),
                                    f"add a sample for {pattern!r} to the guard tests")
        for pattern in guard.INTERPRETERS:
            with self.subTest(interpreter=pattern):
                self.assertTrue(any(re.fullmatch(pattern, name) for name in INTERPRETER_SAMPLES)
                                or re.fullmatch(pattern, "awk"),
                                f"add a writer sample for {pattern!r} to INTERPRETER_SAMPLES")
        target = "src/a.test.ts"
        for x in TAMPER_SAMPLES + SECRET_SAMPLES:
            self.assertEqual(self.claude("Write", file_path=str(self.repo / target), content=x), 2, x)
            rule = "QA-4" if x in TAMPER_SAMPLES else "SEC-1"
            for cmd in every_writer(x, target):
                with self.subTest(cmd=cmd):
                    self.assertTrue((guard.bash_problem(cmd) or "").startswith(rule))
        for name in [".env", "apps/api/.env", ".env.local", ".envrc", "secrets.env"]:
            for cmd in every_writer("A=1", name):
                with self.subTest(cmd=cmd):
                    self.assertTrue((guard.bash_problem(cmd) or "").startswith("SEC-2"))
        # The same through the hook itself, for one writer of each kind.
        for cmd in ["echo 'it.skip(' >> src/a.test.ts", "echo \"open('.env','w').write('A=1')\" | python3"]:
            self.assertEqual(self.bash(cmd), 2, cmd)

    def test_LOG1_reads_and_exempt_writes_pass(self):
        """What the content rules must not stop: reading, prose, the harness, removing a skip."""
        for cmd in [
            "grep -rn 'eslint-disable' src",
            "grep -rn eslint-disable src 2>/dev/null | head",
            "grep -rn 'it.skip(' src > /tmp/keelokit-skips.txt",
            "grep -rn 'it.skip(' src > skips.txt",
            "echo 'never use it.skip(' >> docs/testing.md",
            "cat > .keelokit/harness/notes.toml <<'EOF'\nrule = \"no eslint-disable\"\nEOF",
            "cat .env.example",
            "cat .env",
            "cp .env.example .env",
            "python3 -c \"print(1)\"",
            "node -e \"console.log(process.env.HOME)\"",
            "perl -ne 'print if /eslint-disable/' src/a.ts",
            "python3 -c \"print('it.skip(' in open('src/a.test.ts').read())\"",
            "python3 -c \"print('// eslint-disable')\" >> docs/lint.md",
            "git commit -m \"$(cat <<'EOF'\nfix: drop the eslint-disable in a.ts\nEOF\n)\"",
            "pnpm test 2>&1 | tail -20",
            "ls | grep node",
            "awk '/eslint-disable/ {print FILENAME}' src/a.ts",
            # Reading .env from an interpreter writes nothing.
            "python3 -c \"print(open('.env').read())\"",
            "node -e \"require('dotenv').config({path: '.env.local'})\"",
            "node -e \"process.stdout.write(require('fs').readFileSync('.env', 'utf8'))\"",
            # Removing a skip or a suppression, however it is done.
            "sed -i 's/it.skip(/it(/' src/a.test.ts",
            "sed -i '/eslint-disable/d' src/a.ts",
            "sed -i '/it\\.skip(/d' src/a.test.ts",
            "sed -i '/it.skip(/d' src/a.test.ts",
            "sed -i -e '/@ts-ignore/d' -e 's/foo/bar/' src/a.ts",
            "sed -i '/eslint-disable/,/eslint-enable/d' src/a.ts",
            "sed -i '\\#// eslint-disable#d' src/a.ts",
            "sed '/it.skip(/d' src/a.test.ts > src/b.test.ts",
            "perl -ni -e 'print unless /eslint-disable/' src/a.ts",
            "grep -v 'eslint-disable' src/a.ts > src/a.ts.tmp && mv src/a.ts.tmp src/a.ts",
            "awk '!/eslint-disable/' src/a.ts > src/a.ts.tmp",
            "python3 - <<'PY'\nfrom pathlib import Path\np = Path('src/a.ts')\n"
            "p.write_text(p.read_text().replace('// eslint-disable-next-line\\n', ''))\nPY",
            "python3 -c \"import re; p='src/a.ts'; s=open(p).read(); open(p,'w').write(re.sub(r'.*eslint-disable.*\\n', '', s))\"",
            "python3 - <<'PY'\nls = open('src/a.ts').readlines()\n"
            "open('src/a.ts', 'w').writelines(l for l in ls if 'eslint-disable' not in l)\nPY",
            "node -e \"const fs=require('fs'); const s=fs.readFileSync('src/a.ts','utf8'); "
            "fs.writeFileSync('src/a.ts', s.replace(/\\/\\/ eslint-disable.*\\n/g, ''))\"",
            "node -e \"const fs=require('fs'); fs.writeFileSync('src/a.ts', fs.readFileSync('src/a.ts','utf8')"
            ".split('\\n').filter(l => !l.includes('@ts-ignore')).join('\\n'))\"",
        ]:
            with self.subTest(cmd=cmd):
                self.assertEqual(self.bash(cmd), 0)

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
