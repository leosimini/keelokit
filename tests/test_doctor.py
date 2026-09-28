"""Doctor behaviour on a tiny project. Run: python3 -m unittest discover -s tests"""
import re
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


    def integrity_story(self, sid: str, wave: int, touches: str, dims: str, invariants: str = "") -> None:
        text = STORY.format(id=sid, wave=wave, touches=touches).replace('dimensions = ["api"]', f"dimensions = [{dims}]")
        if invariants:
            text = text.replace("+++\n```", f"invariants = [{invariants}]\n+++\n```", 1)
        self.write(f"backlog/stories/{sid}-x.md", text)

    def test_invariants_need_a_class_and_a_test_once_their_story_is_done(self):
        self.rules()
        self.write("docs/context/domain.md", """\
            # Domain
            - [INV-001] [MUST] Charged equals refunded plus held plus fee — class: conservation (S1)
            - [INV-002] [MUST] A reminder is sent at most once — class: someday (S1)
            - [INV-003] [MUST] A slot never takes more bookings than its capacity (S1)
            <!-- - [INV-009] commented out — class: nope -->
            """)
        self.integrity_story("PAY-001", 1, '"apps/api/src/pay/"', '"api", "integrity"', '"INV-001", "INV-404"')
        self.integrity_story("PAY-002", 1, '"apps/api/src/other/"', '"api", "integrity"')
        self.integrity_story("PAY-003", 2, '"apps/api/src/third/"', '"api"', '"INV-002"')
        out = self.doctor()
        self.assertIn("INV-002 needs 'class:", out)
        self.assertIn("INV-003 needs 'class:", out)
        self.assertNotIn("INV-009", out)
        self.assertIn("PAY-001: invariants INV-404 are not defined", out)
        self.assertIn("PAY-002: declares 'integrity' — list the invariants", out)
        self.assertIn("PAY-003: lists invariants — declare the 'integrity' dimension", out)
        self.assertIn("warn  invariant INV-003", out)

        self.write("docs/context/domain.md", "- [INV-001] [MUST] Conserved — class: conservation (S1)\n")
        for sid in ("PAY-002", "PAY-003"):
            (self.root / f"backlog/stories/{sid}-x.md").unlink()
        self.integrity_story("PAY-001", 1, '"apps/api/src/pay/"', '"api", "integrity"', '"INV-001"')
        self.write("apps/api/pay.test.ts", "it('PAY-001.S1 ok', () => {})\nit('PAY-001.S10 ok', () => {})\nit.skip('INV-001 conserved', () => {})\n")
        self.commit("feat: pay\n\nStory: PAY-001")
        self.assertIn("no active test title cites invariant INV-001 (INV-1)", self.doctor())
        self.write("apps/api/pay.test.ts", "it('PAY-001.S1 ok', () => {})\nit('PAY-001.S10 ok', () => {})\nit('INV-001 conserved for any split', () => {})\n")
        self.assertIn("harness healthy", self.doctor())

    def test_critical_areas_force_integrity_and_go_one_story_at_a_time(self):
        self.rules()
        self.write("docs/context/domain.md", "- [INV-001] [MUST] Conserved — class: conservation (S1)\n")
        self.write("apps/api/src/pay/charge.ts", "export const charge = 1;\n")
        self.write("apps/api/src/pay/charge.spec.ts", "it('x', () => {})\n")
        self.write("packages/shared/src/allocate.ts", "export const a = 1;\n")
        self.write(".keelokit/critical.toml", """\
            mutation_break = 70
            [[area]]
            name = "money"
            why = "charges and refunds"
            paths = ["apps/api/src/pay/", "packages/shared/src/allocate.ts"]
            [[area]]
            name = "ghost"
            why = "gone"
            paths = ["apps/api/src/nope/"]
            """)
        self.integrity_story("PAY-001", 1, '"apps/api/src/pay/"', '"api"')
        self.integrity_story("PAY-002", 1, '"packages/shared/"', '"logic", "integrity"', '"INV-001"')
        self.integrity_story("PAY-003", 1, '"apps/web/"', '"ux"')
        self.commit("init")
        out = self.doctor()
        self.assertIn("area 'ghost' points at 'apps/api/src/nope/', which does not exist", out)
        self.assertIn("PAY-001: touches critical area money — declare 'integrity'", out)
        self.assertIn("stories PAY-001 and PAY-002 share wave 1 and critical area money", out)
        self.assertNotIn("PAY-003 share", out)
        self.assertNotIn("PAY-003: touches", out)

        self.write(".keelokit/critical.toml", '[[area]]\nname = "money"\nwhy = "w"\npaths = ["apps/api/src/pay/", "packages/shared/src/allocate.ts"]\n')
        self.assertEqual(
            self.doctor("--critical").split(),
            ["apps/api/src/pay/charge.ts", "packages/shared/src/allocate.ts"],
        )
        self.commit("areas")
        sh(self.root, "git", "checkout", "-q", "-b", "pay")
        self.assertEqual(self.doctor("--critical", "--changed").split(), [])
        self.write("packages/shared/src/allocate.ts", "export const a = 2;\n")
        self.assertEqual(self.doctor("--critical", "--changed").split(), ["packages/shared/src/allocate.ts"])

    def test_scope_catches_undeclared_critical_work_and_edited_acceptance_tests(self):
        self.rules()
        self.write("apps/api/src/pay/charge.ts", "export const charge = 1;\n")
        self.write(".keelokit/critical.toml", '[[area]]\nname = "money"\nwhy = "w"\npaths = ["apps/api/src/pay/"]\n')
        self.integrity_story("AUTH-001", 1, '"apps/api/"', '"api"')
        self.commit("init")
        sh(self.root, "git", "checkout", "-q", "-b", "auth-001")
        self.write("apps/api/src/auth.spec.ts", "it('AUTH-001.S1', () => {})\n")
        self.commit("test(AUTH-001): acceptance tests")
        self.write("apps/api/src/auth.ts", "export {}\n")
        self.commit("feat: auth")
        self.assertIn("all 2 changed files are within its touches", self.doctor("--scope", "AUTH-001"))
        self.write("apps/api/src/auth.spec.ts", "it('AUTH-001.S1', () => { expect(1) })\n")
        self.commit("test(AUTH-001): the scenario asked for 401, not 403")
        self.assertIn("within its touches", self.doctor("--scope", "AUTH-001"))
        self.write("apps/api/src/auth.spec.ts", "it.skip('AUTH-001.S1', () => {})\n")
        self.write("apps/api/src/pay/charge.ts", "export const charge = 2;\n")
        self.commit("feat: make it pass")
        out = self.doctor("--scope", "AUTH-001")
        self.assertIn("acceptance tests changed outside a 'test(AUTH-001): …' commit", out)
        self.assertIn("apps/api/src/auth.spec.ts", out)
        self.assertIn("changed critical area money but does not declare 'integrity'", out)

    def test_INT_1_without_main_nothing_counts_as_done_and_diffs_fail_safe(self):
        """INV-005: a PR checked out without main (actions/checkout's default depth, a detached
        HEAD) must not count its own `Story:` trailers as done, nor diff HEAD against itself."""
        self.rules()
        self.write("apps/api/src/pay/charge.ts", "export const charge = 1;\n")
        self.write("apps/api/src/pay/refund.ts", "export const refund = 1;\n")
        self.write(".keelokit/critical.toml", '[[area]]\nname = "money"\nwhy = "w"\npaths = ["apps/api/src/pay/"]\n')
        self.write("backlog/stories/AUTH-001-a.md", STORY.format(id="AUTH-001", wave=1, touches='"apps/api/src/auth/"'))
        self.write("apps/api/a.test.ts", "it('AUTH-001.S1 ok', () => {})\nit('AUTH-001.S10 ok', () => {})\n")
        self.commit("init")
        sh(self.root, "git", "checkout", "-q", "--detach")
        sh(self.root, "git", "branch", "-q", "-D", "main")
        self.write("apps/api/src/pay/charge.ts", "export const charge = 2;\n")
        self.commit("feat: sign up\n\nStory: AUTH-001")
        for ref in ("main", "origin/main"):
            self.assertEqual(sh(self.root, "git", "rev-parse", "--verify", "--quiet", ref), "")

        out = self.doctor()
        self.assertIn("Backlog: 0/1 done", out)
        self.assertIn("ERROR no main or origin/main to count done stories from", out)
        self.assertNotIn("harness healthy", out)
        ci = subprocess.run(["python3", ".keelokit/bin/doctor.py", "--ci"], cwd=self.root, capture_output=True, text=True)
        self.assertNotEqual(ci.returncode, 0)  # INV-006

        scope = subprocess.run(["python3", ".keelokit/bin/doctor.py", "--scope", "AUTH-001"],
                               cwd=self.root, capture_output=True, text=True)
        self.assertEqual(scope.returncode, 2)
        self.assertIn("no main or origin/main", scope.stdout)
        self.assertNotIn("within its touches", scope.stdout)

        # Unknown base → every critical file counts as changed, like `pnpm verify` with no origin/main.
        self.assertEqual(self.doctor("--critical", "--changed").split(),
                         ["apps/api/src/pay/charge.ts", "apps/api/src/pay/refund.ts"])

        # Fetching main (CI: fetch-depth: 0) brings the real answer back.
        sh(self.root, "git", "branch", "-q", "main", "HEAD~1")
        self.assertIn("Backlog: 0/1 done", self.doctor())
        self.assertNotIn("no main or origin/main", self.doctor())
        self.assertEqual(self.doctor("--critical", "--changed").split(), ["apps/api/src/pay/charge.ts"])

    def test_INT_1_ci_jobs_that_read_history_against_main_fetch_it(self):
        """The class behind INT-1: a CI job that compares against main (doctor, mutation, a
        gitleaks history scan, verify) on a shallow checkout sees no main at all."""
        repo = Path(__file__).resolve().parents[1]
        reads_main = re.compile(r"doctor\.py|pnpm (mutation|verify)|scripts/(verify|mutation)\.sh|gitleaks[^\n]*\bgit\b")
        paths = sorted([*(repo / "template/.github/workflows").glob("*.y*ml*"), *(repo / ".github/workflows").glob("*.y*ml")])
        self.assertTrue(paths)
        checked = 0
        for path in paths:
            for m in re.finditer(r"(?ms)^  ([\w-]+):\s*\n(.*?)(?=^  \S|\Z)", path.read_text().split("\njobs:", 1)[-1]):
                job, body = m.groups()
                if not reads_main.search(body):
                    continue
                checked += 1
                self.assertRegex(body, r"uses: actions/checkout@[^\n]*\n\s+with:\n(\s+[\w-]+:[^\n]*\n)*?\s+fetch-depth: 0",
                                 f"{path.relative_to(repo)}: job '{job}' reads history against main but its "
                                 "checkout is shallow; add `fetch-depth: 0`")
        self.assertGreaterEqual(checked, 3)  # secrets, checks, mutation in the template

    def test_profile_decides_which_rules_apply_and_warns_on_drift(self):
        self.rules(
            self.rule("R-UI", "test:missing.test.ts") + 'needs = ["ui"]\n',
            self.rule("R-ALL", "test:missing.test.ts"),
        )
        self.write(".keelokit/profile.toml", 'kind = "plugin"\ntraits = ["developer-facing"]\n')
        out = self.doctor()
        self.assertNotIn("rule R-UI:", out)  # a plugin without UI isn't held to UI rules
        self.assertIn("rule R-ALL:", out)
        self.assertIn("not applicable: R-UI", out)
        # The repo grows a database the profile doesn't know about: the doctor says so.
        self.write("prisma/schema.prisma", "// schema\n")
        self.assertIn("profile: the repo shows `database` (prisma/schema.prisma)", self.doctor())
        # And the other way round: a structural trait nothing backs.
        self.write(".keelokit/profile.toml", 'kind = "plugin"\ntraits = ["developer-facing", "database", "mobile"]\n')
        out = self.doctor("--brief")
        self.assertIn("Profile drift: the profile lists `mobile` but nothing in the repo shows it yet", out)
        self.assertNotIn("`database` but nothing", out)

    def test_profile_must_be_diagnosed(self):
        self.write(".keelokit/profile.toml", 'kind = "unknown"\ntraits = ["ui", "blockchain"]\n')
        out = self.doctor()
        self.assertIn("the project's kind isn't diagnosed yet", out)
        self.assertIn("unknown traits blockchain", out)

    def test_escape_log_names_the_check_left_behind(self):
        self.rules()
        self.write("docs/escapes.md", """\
            | Id | Date | Found by | What escaped | Class | Check added |
            |---|---|---|---|---|---|
            | ESC-001 | 2026-09-01 | breaker | Two taps booked the last seat twice | limit | race test on POST /bookings |
            | ESC-002 | 2026-09-02 | bugbash | Reminder sent twice | once |  |
            """)
        out = self.doctor()
        self.assertIn("Escapes logged: 2", out)
        self.assertIn("ESC-002 needs", out)
        self.assertNotIn("ESC-001 needs", out)


if __name__ == "__main__":
    unittest.main()
