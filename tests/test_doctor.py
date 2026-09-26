"""Doctor behaviour on a tiny project. Run: python3 -m unittest discover -s tests"""
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

DOCTOR = Path(__file__).resolve().parents[1] / "template/.keelokit/bin/doctor.py"

CI = """\
name: CI
jobs:
  checks:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pnpm lint
  soft:
    runs-on: ubuntu-latest
    continue-on-error: true
    steps:
      - run: pnpm test
  empty:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: 'true'
"""

STORY = """\
+++
id = "{id}"
epic = "AUTH"
title = "t"
wave = {wave}
depends_on = []
touches = [{touches}]
dimensions = ["api"]
+++
```gherkin
Scenario: [S1] works
Scenario: [S10] also works
```
"""


def sh(cwd: Path, *cmd: str) -> str:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True).stdout


class DoctorTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.write(".keelokit/bin/doctor.py", DOCTOR.read_text())
        self.write(".github/workflows/ci.yml", CI)
        self.write("eslint.config.mjs", "rules: { 'no-explicit-any': 'error', 'no-console': 'off' }")
        for f in ("product", "domain", "constraints", "environments"):
            self.write(f"docs/context/{f}.md", f"# {f}\n")
        self.write("docs/context/gaps.md", "| Id | File | Missing | Owner | Question | Blocking |\n|---|---|---|---|---|---|\n")
        sh(self.root, "git", "init", "-q", "-b", "main")
        sh(self.root, "git", "config", "user.email", "t@example.com")
        sh(self.root, "git", "config", "user.name", "T")

    def tearDown(self):
        shutil.rmtree(self.root)

    def write(self, rel: str, text: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text))

    def rules(self, *entries: str) -> None:
        self.write(".keelokit/harness/rules.toml", "\n".join(entries))

    def commit(self, message: str) -> None:
        sh(self.root, "git", "add", "-A")
        sh(self.root, "git", "commit", "-qm", message, "--allow-empty")

    def doctor(self, *args: str) -> str:
        return sh(self.root, "python3", ".keelokit/bin/doctor.py", *args)

    @staticmethod
    def rule(rid: str, enforcer: str) -> str:
        return f"[[rule]]\nid = \"{rid}\"\nlevel = \"MUST\"\nrule = \"r\"\nwhy = \"w\"\nenforced_by = ['{enforcer}']\n"

    def test_enforcers_must_look_alive(self):
        self.write("a.test.ts", "// R-TEST\nit.each(Object.entries({a: 1}))('works %s', () => {})\n")
        self.write("b.test.ts", "it('works', () => {})\n")
        self.write("c.test.ts", "// R-SKIP\nit.skip('x', () => {})\n")
        self.write("tsconfig.json", '{"strict": false}')
        self.rules(
            self.rule("R-TEST", "test:a.test.ts"),
            self.rule("R-NOCITE", "test:b.test.ts"),
            self.rule("R-SKIP", "test:c.test.ts"),
            self.rule("R-LINT", "lint:no-explicit-any"),
            self.rule("R-OFF", "lint:no-console"),
            self.rule("R-CI", "ci:checks"),
            self.rule("R-SOFT", "ci:soft"),
            self.rule("R-EMPTY", "ci:empty"),
            self.rule("R-HOOK", "git-hook:pre-commit"),
            self.rule("R-FILE", 'file:tsconfig.json#"strict": true'),
        )
        out = self.doctor()
        for ok in ("R-TEST:", "R-LINT:", "R-CI:"):
            self.assertNotIn(f"rule {ok}", out)
        for bad, why in [
            ("R-NOCITE", "no active test that names R-NOCITE"),
            ("R-SKIP", "no active test that names R-SKIP"),
            ("R-OFF", "turned off"),
            ("R-SOFT", "continue-on-error"),
            ("R-EMPTY", "no real step"),
            ("R-HOOK", "not installed"),
            ("R-FILE", "does not contain"),
        ]:
            self.assertIn(f"rule {bad}: ", out)
            self.assertIn(why, out)

    def test_exception_turns_error_into_warning(self):
        self.rules(self.rule("R-HOOK", "git-hook:pre-commit"))
        self.write(".keelokit/exceptions.toml", '[[exception]]\nrule = "R-HOOK"\nreason = "r"\napprover = "Leo"\nexpires = "2999-01-01"\n')
        out = self.doctor()
        self.assertIn("warn  rule R-HOOK", out)
        self.assertIn("harness healthy", out)

    def test_status_comes_only_from_story_trailers_on_main(self):
        self.rules()
        self.write("backlog/stories/AUTH-001-a.md", STORY.format(id="AUTH-001", wave=1, touches='"apps/api/"'))
        self.write("apps/api/a.test.ts", "it('AUTH-001.S1 ok', () => {})\nit('AUTH-001.S10 ok', () => {})\n")
        self.commit("docs: plan AUTH-001 and friends")
        self.assertIn("Backlog: 0/1 done", self.doctor())
        self.commit("feat: sign up\n\nStory: AUTH-001")
        out = self.doctor()
        self.assertIn("Backlog: 1/1 done", out)
        self.assertIn("harness healthy", out)

    def test_trace_needs_active_titles(self):
        self.rules()
        self.write("backlog/stories/AUTH-001-a.md", STORY.format(id="AUTH-001", wave=1, touches='"apps/api/"'))
        self.write("apps/api/a.test.ts", "// AUTH-001.S1\nit.skip('AUTH-001.S1', () => {})\nit('AUTH-001.S10 ok', () => {})\n")
        self.commit("feat: x\n\nStory: AUTH-001")
        out = self.doctor()
        self.assertIn("no active test title cites AUTH-001.S1", out)
        self.assertNotIn("AUTH-001.S10,", out)

    def test_wave_collisions_and_scope(self):
        self.rules()
        self.write("backlog/stories/AUTH-001-a.md", STORY.format(id="AUTH-001", wave=1, touches='"apps/api/src/auth/"'))
        self.write("backlog/stories/AUTH-002-b.md", STORY.format(id="AUTH-002", wave=1, touches='"apps/api/src/auth/login.ts"'))
        self.commit("init")
        self.assertIn("share wave 1 but both touch apps/api/src/auth/", self.doctor())
        sh(self.root, "git", "checkout", "-q", "-b", "auth-001")
        self.write("apps/api/src/auth/signup.ts", "export {}\n")
        self.write("apps/web/src/App.tsx", "export {}\n")
        self.commit("wip")
        out = self.doctor("--scope", "AUTH-001")
        self.assertIn("apps/web/src/App.tsx", out)
        self.assertNotIn("signup.ts", out)


if __name__ == "__main__":
    unittest.main()
