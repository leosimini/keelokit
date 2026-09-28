"""Doctor behaviour on a tiny project. Run: python3 -m unittest discover -s tests"""
import ast
import contextlib
import io
import json
import re
import runpy
import shutil
import subprocess
import sys
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

    def test_INT_2_a_hand_edited_state_or_exception_is_an_error_not_a_traceback(self):
        """INT-2 (and LOG-2): an invalid state.toml or an exception whose `expires` isn't a date
        crashed every mode, even the SessionStart `--brief`. Each is an ERROR like any other."""
        self.rules(self.rule("R-HOOK", "git-hook:pre-commit"))
        for rel, text, error in [
            (".keelokit/state.toml", "[gates\nthis is not valid toml", ".keelokit/state.toml: invalid TOML"),
            (".keelokit/exceptions.toml",
             '[[exception]]\nrule = "R-HOOK"\nreason = "r"\napprover = "Leo"\nexpires = "not-a-date"\n',
             "exception for R-HOOK: 'expires' is not a date (YYYY-MM-DD) or 'permanent' ('not-a-date')"),
        ]:
            with self.subTest(rel):
                self.write(rel, text)
                brief = subprocess.run(["python3", ".keelokit/bin/doctor.py", "--brief"], cwd=self.root, capture_output=True, text=True)
                self.assertEqual((brief.returncode, brief.stderr), (0, ""))
                self.assertIn("Harness errors:", brief.stdout)
                ci = subprocess.run(["python3", ".keelokit/bin/doctor.py", "--ci"], cwd=self.root, capture_output=True, text=True)
                self.assertEqual((ci.returncode, ci.stderr), (1, ""))  # INV-006
                self.assertIn(f"ERROR {error}", ci.stdout)
                (self.root / rel).unlink()

    def test_INT_2_bytes_directories_and_paths_outside_the_repo_are_errors_not_tracebacks(self):
        """INT-2, the rest of the class: a hand-edited file saved as Latin-1 (a Spanish user's
        state.toml or story), a directory where an enforcer reads a file (`test:apps/web`,
        `file:apps#x`), an absolute glob and a critical area outside the repo each crashed the doctor."""
        (self.root / "apps/web").mkdir(parents=True)
        self.write("backlog/stories/AUTH-002-b.md", STORY.format(id="AUTH-002", wave=1, touches='"apps/api/"'))
        self.commit("init")
        cases = [
            (".keelokit/state.toml", b'[gates]\nintake = "raz\xf3n"\n', ".keelokit/state.toml: not UTF-8 (byte 0xf3"),
            ("backlog/stories/AUTH-001-a.md",
             STORY.format(id="AUTH-001", wave=1, touches='"apps/api/"').replace('title = "t"', 'title = "Autenticaci\xf3n"').encode("latin-1"),
             "backlog/stories/AUTH-001-a.md: not UTF-8 (byte 0xf3"),
            (".keelokit/rules.local.toml", self.rule("L-1", "test:apps/web").encode(), "rule L-1: 'apps/web' is a directory"),
            (".keelokit/rules.local.toml", self.rule("L-1", "file:apps#x").encode(), "rule L-1: apps: is a directory"),
            (".keelokit/rules.local.toml", self.rule("L-1", "test:/tmp/*").encode(), "rule L-1: '/tmp/*' must be a path relative to the repo root"),
            (".keelokit/critical.toml", b'[[area]]\nname = "etc"\nwhy = "w"\npaths = ["/etc/hostname"]\n',
             ".keelokit/critical.toml: area 'etc' path '/etc/hostname' must be a path relative to the repo root"),
        ]
        for rel, data, error in cases:
            with self.subTest(error):
                (self.root / rel).write_bytes(data)
                for args, code in ([["--brief"], 0], [["--ci"], 1], [["--critical", "--changed"], None], [["--scope", "AUTH-001"], None]):
                    run = subprocess.run(["python3", ".keelokit/bin/doctor.py", *args], cwd=self.root, capture_output=True, text=True)
                    self.assertNotIn("Traceback", run.stdout + run.stderr, args)
                    self.assertIn(run.returncode, (code,) if code is not None else (0, 1, 2), (args, run.stdout, run.stderr))
                ci = self.doctor("--ci")
                self.assertIn(f"ERROR {error}", ci)
                (self.root / rel).unlink()
        # A done story whose invariant isn't a plain id (it went into a regex unescaped).
        self.write("backlog/stories/AUTH-003-c.md", STORY.format(id="AUTH-003", wave=2, touches='"apps/c/"')
                   .replace('dimensions = ["api"]', 'dimensions = ["integrity"]\ninvariants = ["INV-(1"]'))
        self.commit("feat: c\n\nStory: AUTH-003")
        run = subprocess.run(["python3", ".keelokit/bin/doctor.py", "--ci"], cwd=self.root, capture_output=True, text=True)
        self.assertEqual((run.returncode, run.stderr), (1, ""))
        self.assertIn("no active test title cites invariant INV-(1", run.stdout)

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

    def assert_remedies_run_here(self, out: str) -> list[str]:
        """Every command the output tells you to run exists in this repo: the doctor by its own path,
        git, or a package manager whose install step or script the repo's package.json has."""
        pkg = json.loads((self.root / "package.json").read_text()) if (self.root / "package.json").exists() else None
        remedies = re.findall(r"\bruns? `([^`]+)`", out)
        for cmd in remedies:
            words = cmd.split()
            if words[0] == "python3":
                self.assertTrue((self.root / words[1]).is_file(), cmd)
            elif words[0] == "git":
                continue
            else:
                self.assertIn(words[0], ("pnpm", "npm", "yarn", "bun"), f"unknown command: {cmd}")
                self.assertIsNotNone(pkg, f"`{cmd}` in a repo without package.json")
                if words[1] != "install":
                    self.assertEqual(words[1], "run", f"`{cmd}`: say `run`, a built-in may shadow the script")
                    self.assertIn(words[2], pkg.get("scripts", {}), cmd)
        if pkg is None:
            self.assertNotRegex(out, r"\b(pnpm|npm|yarn)\b", "a package manager named in a repo without package.json")
        return remedies

    def test_CPY_1_fix_it_text_names_only_commands_the_repo_has(self):
        """The doctor told every repo to run pnpm's `doctor` (pnpm's own command, which never runs
        the script) and `pnpm install`, even one with no package.json (an adopted repo, this one)."""
        self.rules(self.rule("R-HOOK", "git-hook:pre-commit"), self.rule("R-PUSH", "git-hook:pre-push"))
        self.write(".keelokit/bin/guard.py", "")
        cases = {
            "no package.json, no hooks": ({}, "add a 'pre-commit' hook that runs `python3 .keelokit/bin/guard.py git-pre-commit`"),
            "the hooks ship in .githooks": ({".githooks/pre-commit": "#!/bin/sh\n", ".githooks/pre-push": "#!/bin/sh\n"},
                                            "a human runs `git config core.hooksPath .githooks`"),
            "generated project": ({"package.json": json.dumps({"packageManager": "pnpm@10.33.0", "scripts": {
                "prepare": "git config core.hooksPath .githooks || true", "doctor": "python3 .keelokit/bin/doctor.py"}}),
                ".githooks/pre-commit": "#!/bin/sh\n"}, "run `pnpm install`"),
            "husky with npm": ({"package.json": json.dumps({"scripts": {"prepare": "husky"}}), "package-lock.json": "{}"},
                               "run `npm install`"),
            "yarn lockfile": ({"package.json": json.dumps({"scripts": {"postinstall": "husky install"}}), "yarn.lock": ""},
                              "run `yarn install`"),
            "package.json without an install step": ({"package.json": json.dumps({"scripts": {"doctor": "x"}})},
                                                     "add a 'pre-push' hook, or map or except"),
            "package.json that isn't JSON": ({"package.json": "{not json"}, "add a 'pre-commit' hook"),
        }
        for name, (files, hint) in cases.items():
            with self.subTest(name):
                for f in ("package.json", "package-lock.json", "yarn.lock"):
                    (self.root / f).unlink(missing_ok=True)
                shutil.rmtree(self.root / ".githooks", ignore_errors=True)
                for f, text in files.items():
                    self.write(f, text)
                out, brief = self.doctor(), self.doctor("--brief")
                self.assertIn(hint, out)
                self.assertNotIn("Traceback", out + brief)
                self.assertIn("Harness errors:", brief)
                if name != "package.json that isn't JSON":
                    self.assertTrue(self.assert_remedies_run_here(out), out)
                    self.assertTrue(self.assert_remedies_run_here(brief), brief)

    def test_CPY_1_no_doc_runs_a_script_that_a_pnpm_command_shadows(self):
        """The class: a package script named like a pnpm command (`doctor`) only runs as `pnpm run
        <name>`; `pnpm <name>` runs pnpm's own command and says nothing about the harness."""
        repo = Path(__file__).resolve().parents[1]
        scripts = set(re.findall(r'^\s*"([\w:-]+)":', (repo / "template/package.json.jinja").read_text().split('"scripts"', 1)[1]
                                 .split("\n  }", 1)[0], re.M))
        shadowed = scripts & PNPM_COMMANDS
        self.assertIn("doctor", shadowed)
        tracked = subprocess.run(["git", "ls-files"], cwd=repo, capture_output=True, text=True, check=True).stdout.split()
        found = []
        for rel in tracked:
            if rel == "CHANGELOG.md" or rel.startswith("docs/bugbash/") or rel.endswith((".png", ".svg", ".ico", ".zip")):
                continue
            try:
                text = (repo / rel).read_text(encoding="utf-8")
            except (UnicodeDecodeError, IsADirectoryError, FileNotFoundError):
                continue
            for m in re.finditer(rf"\bpnpm\s+({'|'.join(map(re.escape, shadowed))})\b", text):
                found.append(f"{rel}:{text[:m.start()].count(chr(10)) + 1}: {m.group(0)}")
        self.assertEqual(found, [], "say `pnpm run <script>` or `python3 .keelokit/bin/doctor.py`")

    def test_CPY_1_every_failing_check_names_only_commands_the_repo_has(self):
        """The class, dynamically: a failing enforcer of every kind the doctor knows (found in its
        source, so a new kind needs a case here), and the other checks that report an ERROR, in a
        repo without package.json, a generated project and a package.json without scripts: every
        command any line tells you to run must exist in that repo."""
        source = DOCTOR.read_text()
        body = source.split("def enforcer_problem", 1)[1].split("\ndef ", 1)[0]
        kinds = {k for m in re.finditer(r"kind (?:==|in) ([^:]+):", body) for k in re.findall(r'"([a-z-]+)"', m.group(1))}
        failing = {  # kind → enforcers that fail it, one per way it can fail
            "ci": ["ci:missing", "ci:soft", "ci:empty"],
            "git-hook": ["git-hook:pre-commit", "git-hook:pre-push", "git-hook:../x"],
            "claude-hook": ["claude-hook:nothere.py"],
            "test": ["test:missing.test.ts", "test:somedir", "test:b.test.ts", "test:*/none.test.ts", "test:/abs.test.ts"],
            "lint": ["lint:no-console", "lint:not-enabled"],
            "script": ["script:scripts/verify.sh"],
            "file": ["file:nope.json", 'file:tsconfig.json#"strict": true', "file:somedir#x"],
            "review": ["review:"],
            "unknown": ["bogus:x"],
        }
        self.assertEqual(kinds - failing.keys(), set(), "add a failing enforcer for each new kind")
        refs = [r for rs in failing.values() for r in rs]
        self.rules(*(self.rule(f"R-{i}", ref) for i, ref in enumerate(refs)),
                   '[[rule]]\nid = "R-NONE"\nlevel = "MUST"\nrule = "r"\nwhy = "w"\nenforced_by = []\n')
        self.write(".keelokit/bin/guard.py", "")
        self.write("b.test.ts", "it('works', () => {})\n")
        self.write("somedir/x.test.ts", "")
        self.write("tsconfig.json", '{"strict": false}')
        self.write(".keelokit/exceptions.toml", '[[exception]]\nrule = "R-0"\nreason = "r"\napprover = "a"\nexpires = 2000-01-01\n'
                   '[[exception]]\nrule = "R-GONE"\n')
        self.write(".keelokit/profile.toml", 'kind = "unknown"\ntraits = ["nope"]\n')
        self.write(".keelokit/critical.toml", 'mutation_break = 700\n[[area]]\nname = "a"\nwhy = "w"\npaths = ["gone/"]\n')
        self.write("docs/context/product.md", "# product\nIt should be robust. See [GAP-009].\n")
        self.write("docs/context/domain.md", "- [INV-001] no class\n")
        self.write("docs/escapes.md", "| ESC-001 | | | | | |\n")
        self.write("backlog/stories/AUTH-001-x.md", "+++\nid = \"AUTH-001\"\nstatus = \"done\"\ndepends_on = [\"X-1\"]\n+++\n")
        self.write("backlog/stories/bad.md", "no front matter\n")
        shapes = {
            "no package.json": {},
            "generated project": {"package.json": json.dumps({"packageManager": "pnpm@10.33.0", "scripts": {
                "prepare": "git config core.hooksPath .githooks || true", "doctor": "python3 .keelokit/bin/doctor.py"}})},
            "package.json without scripts": {"package.json": "{}"},
        }
        for name, files in shapes.items():
            with self.subTest(name):
                (self.root / "package.json").unlink(missing_ok=True)
                for f, text in files.items():
                    self.write(f, text)
                out = self.doctor()
                for i, ref in enumerate(refs):
                    self.assertIn(f"ERROR rule R-{i}:", out, f"{ref} should fail in this fixture")
                self.assertGreaterEqual(out.count("ERROR"), len(refs) + 10, out)
                for text in (out, self.doctor("--ci"), self.doctor("--brief"), self.doctor("--scope", "AUTH-001")):
                    self.assertNotIn("Traceback", text)
                    self.assert_remedies_run_here(text)

    def test_CPY_1_no_doctor_message_names_a_package_manager(self):
        """The class, statically: every string the doctor can print, in both copies. Only
        hook_remedy may name a package manager (the one the repo's package.json installs with, which
        the dynamic cases check); any other remedy is the doctor by its path, a script under
        .keelokit/bin, git, or a /keelokit: skill, which every repo with the harness has."""
        repo = Path(__file__).resolve().parents[1]
        for copy in (DOCTOR, repo / ".keelokit/bin/doctor.py"):
            tree = ast.parse(copy.read_text())
            skip = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name == "hook_remedy":
                    skip |= {id(n) for n in ast.walk(node)}
                if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "LOCKFILES" for t in node.targets):
                    skip |= {id(n) for n in ast.walk(node)}
                if isinstance(node, (ast.Module, ast.FunctionDef)) and ast.get_docstring(node, clean=False) is not None:
                    skip.add(id(node.body[0].value))
            texts = [ast.unparse(n) if isinstance(n, ast.JoinedStr) else n.value for n in ast.walk(tree)
                     if id(n) not in skip and (isinstance(n, ast.JoinedStr)
                                               or isinstance(n, ast.Constant) and isinstance(n.value, str))]
            self.assertGreater(len(texts), 100, copy)
            for text in texts:
                with self.subTest(copy=str(copy.relative_to(repo)), text=text[:80]):
                    self.assertNotRegex(text, r"\b(pnpm|pnpx|npm|npx|yarn|bun|bunx)\b",
                                        "a package manager in a doctor message: an adopted repo may have none")
                    for cmd in re.findall(r"\bruns? `([^`]+)`", text):
                        self.assertRegex(cmd, r"^(\{DOCTOR_CMD\}|python3 \.keelokit/bin/\w+\.py\b|git )", cmd)


# pnpm 10's own commands (`pnpm help --all`), minus start and test, which run the package script.
PNPM_COMMANDS = {
    "add", "dedupe", "fetch", "import", "i", "install", "it", "install-test", "ln", "link", "prune", "rb", "rebuild",
    "rm", "remove", "unlink", "up", "update", "patch", "patch-commit", "patch-remove", "audit", "licenses", "ls", "list",
    "outdated", "why", "approve-builds", "create", "dlx", "exec", "ignored-builds", "run", "bin", "c", "config", "deploy",
    "doctor", "init", "pack", "publish", "root", "self-update", "env", "cat-file", "cat-index", "find-hash", "store",
    "cache", "setup", "server",
}


# Every kind of TOML value, and the kinds of doctor's SHAPES each one is (none: always wrong).
LITERALS = {
    '"x"': {"text"}, '"2030-01-01"': {"text"}, "7": {"whole"}, "1.5": set(), "true": set(),
    "2030-01-01T00:00:00Z": set(), "2030-01-01T00:00:00": set(), "2030-01-01": {"date"}, "07:00:00": set(),
    '["x"]': {"texts"}, "[]": {"texts", "tables"}, "[1]": set(), '["x", 1]': set(),
    "{a = 1}": {"table"}, "[{a = 1}]": {"tables"},
}
# Path content for every key the doctor looks up on disk: → outside (the repo), dir, file, missing or glob.
PATH_VALUES = {
    "": "outside", "  ": "outside", "/etc/hostname": "outside", "/tmp/*": "outside", "..": "outside",
    "../x": "outside", "src/../../x": "outside", "C:\\x": "outside", "\\\\srv\\x": "outside", "x\0y": "outside",
    "src": "dir", "src/": "dir", "src/pay/a.ts": "file", "missing.ts": "missing",
    "src/*": "glob", "*": "glob", "**": "glob", "src/**/*.ts": "glob", "a/**b": "glob", "[": "glob",
}
# A healthy project holding every file the doctor reads: top-level keys, then [[entries]].
HEALTHY = {
    ".keelokit/harness/rules.toml": ({}, {"rule": [{"id": '"R-1"', "level": '"MUST"', "rule": '"r"', "why": '"w"',
                                                     "enforced_by": '["file:README.md"]', "when": '"README.md"', "needs": "[]"}]}),
    ".keelokit/rules.local.toml": ({}, {"rule": [{"id": '"L-1"', "level": '"MUST"', "rule": '"r"', "why": '"w"',
                                                   "enforced_by": '["file:README.md"]', "when": '["README.md"]', "needs": "[]"}]}),
    ".keelokit/exceptions.toml": ({}, {"exception": [{"rule": '"R-1"', "reason": '"r"', "approver": '"Leo"', "expires": '"permanent"'}]}),
    ".keelokit/profile.toml": ({"kind": '"plugin"', "traits": '["developer-facing"]'}, {}),
    ".keelokit/critical.toml": ({"mutation_break": "70"}, {"area": [{"name": '"money"', "why": '"w"', "paths": '["src/pay"]'}]}),
    ".keelokit/state.toml": ({"gates": '{intake = "2026-09-27"}'}, {}),
    "backlog/stories/*.md": ({"id": '"AUTH-001"', "epic": '"AUTH"', "title": '"t"', "wave": "1", "depends_on": "[]",
                              "touches": '["apps/a/"]', "dimensions": '["api"]', "invariants": "[]", "origin": '"x"'}, {}),
}
# Keys the docs define in these files that the doctor never reads (the dashboard does).
NOT_READ = {".keelokit/profile.toml": {"detected"}, ".keelokit/state.toml": {"dashboard", "run"}}


def documented_keys(text: str) -> tuple[set[str], dict[str, set[str]]]:
    """Top-level keys and [[entry]] keys a documented example sets, commented out or not."""
    top: set[str] = set()
    entries: dict[str, set[str]] = {}
    section = None
    for line in text.splitlines():
        if m := re.match(r"\s*#?\s*\[\[(\w+)\]\]\s*$", line):
            section = entries.setdefault(m.group(1), set())
            top.add(m.group(1))
        elif m := re.match(r"\s*#?\s*\[(\w+)\]\s*$", line):
            top.add(m.group(1))
            section = set()  # a table's own keys: the doctor reads the table whole
        elif m := re.match(r"\s*#?\s*(\w+)\s*=\s*\S", line):
            (top if section is None else section).add(m.group(1))
    return top, entries


class DoctorInputContractTest(unittest.TestCase):
    """The class behind INT-2: people and agents edit the files the doctor reads by hand, and a
    value it doesn't expect (bad TOML, a date that isn't one, a number where a list goes) crashed
    every mode, the SessionStart `--brief` included. For every file and key the doctor reads and
    every kind of TOML value: never a traceback, `--brief` exits 0, and a kind its SHAPES don't
    allow is an ERROR that names the file, so `--ci` exits 1 (INV-006)."""

    @classmethod
    def setUpClass(cls):
        cls.api = runpy.run_path(str(DOCTOR), run_name="doctor")
        cls.code = compile(DOCTOR.read_text(), str(DOCTOR), "exec")
        cls.repo = Path(__file__).resolve().parents[1]

    def test_every_toml_the_doctor_reads_goes_through_its_shapes(self):
        source = DOCTOR.read_text()
        loaders = {m.group(1) for m in re.finditer(r"(?ms)^def (\w+)\(.*?(?=^def |\Z)", source)
                   if "tomllib.loads(" in m.group(0)}
        self.assertEqual(loaders, {"read_toml", "read_story"}, "parse TOML only through read_toml (or read_story)")
        self.assertIn('misshapen(meta, SHAPES["backlog/stories/*.md"][0])', source)
        for rel in re.findall(r'(?:read_toml|load_toml)\(ROOT / "([^"]+)"', source):
            self.assertIn(rel, self.api["SHAPES"], f"{rel} is read but has no shape")
        self.assertEqual(set(HEALTHY), set(self.api["SHAPES"]), "give HEALTHY a valid example of every shaped file")

    def test_every_documented_key_has_a_shape(self):
        docs = {
            ".keelokit/harness/rules.toml": ["template/.keelokit/harness/rules.toml"],
            ".keelokit/rules.local.toml": ["template/.keelokit/rules.local.toml"],
            ".keelokit/exceptions.toml": ["template/.keelokit/exceptions.toml"],
            ".keelokit/profile.toml": ["template/.keelokit/profile.toml.jinja"],
            ".keelokit/critical.toml": ["template/.keelokit/critical.toml.jinja"],
            "backlog/stories/*.md": [],
        }
        texts = {rel: "\n".join((self.repo / f).read_text() for f in files) for rel, files in docs.items()}
        readme = (self.repo / "template/backlog/README.md").read_text()
        texts["backlog/stories/*.md"] = re.search(r"(?s)```\n\+\+\+\n(.*?)\+\+\+", readme).group(1)
        # state.toml has no template: the skills name its tables (`[gates]` in `.keelokit/state.toml`).
        skills = "\n".join(p.read_text() for p in self.repo.glob("skills/*/SKILL.md"))
        near = r"`\[(\w+)\][^`\n]*`[^\n]*`\.keelokit/state\.toml`|`\.keelokit/state\.toml`[^\n]*?`\[(\w+)\]"
        tables = {t for pair in re.findall(near, skills) for t in pair if t}
        self.assertIn("gates", tables)
        texts[".keelokit/state.toml"] = "\n".join(f"[{t}]" for t in sorted(tables))
        self.assertEqual(set(texts), set(self.api["SHAPES"]))
        for rel, text in texts.items():
            top, entries = documented_keys(text)
            shape_top, shape_entries = self.api["SHAPES"][rel]
            self.assertTrue(top, rel)
            self.assertEqual(top - set(shape_top) - NOT_READ.get(rel, set()), set(), f"{rel}: give these keys a shape")
            for key, keys in entries.items():
                self.assertEqual(keys - set(shape_entries.get(key, {})), set(), f"{rel} [[{key}]]: give these keys a shape")

    def run_doctor(self, root: Path, *args: str) -> tuple[int, str]:
        """`python3 .keelokit/bin/doctor.py <args>` in `root`, in this process (compiled once: it's fast)."""
        out, argv = io.StringIO(), sys.argv
        sys.argv = ["doctor.py", *args]
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                exec(self.code, {"__name__": "__main__", "__file__": str(root / ".keelokit/bin/doctor.py")})
            code = 0
        except SystemExit as e:
            code = e.code
        finally:
            sys.argv = argv
        return code, out.getvalue()

    @staticmethod
    def render(rel: str, top: dict, entries: dict) -> str:
        lines = [f"{k} = {v}" for k, v in top.items()]
        for key, items in entries.items():
            for item in items:
                lines += [f"[[{key}]]", *(f"{k} = {v}" for k, v in item.items())]
        text = "\n".join(lines) + "\n"
        return f"+++\n{text}+++\nScenario: [S1] works\n" if rel.endswith(".md") else text

    def fixture(self, rel: str) -> Path:
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root)
        files = {".keelokit/bin/doctor.py": DOCTOR.read_text(), "README.md": "# r\n", "src/pay/a.ts": "export {}\n",
                 "docs/context/gaps.md": "| Id | File | Missing | Owner | Question | Blocking |\n|---|---|---|---|---|---|\n"}
        files |= {f"docs/context/{f}.md": f"# {f}\n" for f in ("product", "domain", "constraints", "environments")}
        files[".keelokit/harness/rules.toml"] = self.render(".keelokit/harness/rules.toml", *HEALTHY[".keelokit/harness/rules.toml"])
        if rel == "backlog/stories/*.md":
            second = {**HEALTHY[rel][0], "id": '"AUTH-002"', "touches": '["apps/b/"]'}
            files["backlog/stories/AUTH-002-b.md"] = self.render(rel, second, {})
        for f, text in files.items():
            (root / f).parent.mkdir(parents=True, exist_ok=True)
            (root / f).write_text(text)
        for cmd in (["init", "-q", "-b", "main"], ["-c", "user.email=t@t", "-c", "user.name=T", "commit", "-qm", "init", "--allow-empty"]):
            subprocess.run(["git", *cmd], cwd=root, check=True, capture_output=True)
        return root

    def check(self, root: Path, rel: str, text: str, wrong: bool, why: str) -> None:
        path = root / (rel.replace("*", "AUTH-001-a"))
        path.write_text(text)
        name = path.relative_to(root).as_posix()
        with self.subTest(why):
            code, out = self.run_doctor(root, "--brief")
            self.assertEqual(code, 0, out)
            code, out = self.run_doctor(root, "--ci")
            self.assertIn(code, (1,) if wrong else (0, 1), out)
            if wrong:
                self.assertRegex(out, rf"(?m)^  ERROR {re.escape(name)}: ", out)
            else:
                self.assertNotRegex(out, rf"(?m)^  ERROR {re.escape(name)}: .*must be", out)
            if rel == ".keelokit/critical.toml":
                self.assertIn(self.run_doctor(root, "--critical", "--changed")[0], (0, 1))
            if rel.endswith(".md"):
                self.assertIn(self.run_doctor(root, "--scope", "AUTH-001")[0], (0, 1, 2))

    def test_no_value_in_any_file_crashes_the_doctor(self):
        for rel, (top, entries) in HEALTHY.items():
            root = self.fixture(rel)
            self.check(root, rel, self.render(rel, top, entries), False, f"{rel} healthy")
            code, out = self.run_doctor(root, "--ci")
            self.assertEqual(code, 0, out)
            broken = "[oops\nnot = toml = at all\n"
            self.check(root, rel, f"+++\n{broken}+++\n" if rel.endswith(".md") else broken, True, f"{rel} invalid TOML")
            shape_top, shape_entries = self.api["SHAPES"][rel]
            for literal, kinds in LITERALS.items():
                for key, allowed in shape_top.items():
                    wrong = not kinds & set(allowed.split("|"))
                    t, e = {**top, key: literal}, {k: v for k, v in entries.items() if k != key}
                    self.check(root, rel, self.render(rel, t, e), wrong, f"{rel} {key} = {literal}")
                for key, entry_shape in shape_entries.items():
                    for field, allowed in entry_shape.items():
                        wrong = not kinds & set(allowed.split("|"))
                        e = {**entries, key: [{**entries[key][0], field: literal}]}
                        self.check(root, rel, self.render(rel, top, e), wrong, f"{rel} [[{key}]] {field} = {literal}")
                if rel == ".keelokit/state.toml":  # a gate's value is only read as set or not
                    self.check(root, rel, self.render(rel, {"gates": f"{{intake = {literal}}}"}, {}), False, f"gate = {literal}")

    def test_every_file_and_glob_goes_through_a_guarded_reader(self):
        """The class: a file or glob the doctor reads straight (`read_text`, `open`, `glob` of a
        hand-edited pattern) crashes on bytes, a directory or a path it doesn't expect."""
        source = DOCTOR.read_text()
        funcs = {m.group(1): m.group(0) for m in re.finditer(r"(?ms)^def (\w+)\(.*?(?=^def |^if __name__|\Z)", source)}
        readers = {name for name, body in funcs.items() if re.search(r"\.read_text\(|\.read_bytes\(|(?<![\w.])open\(", body)}
        self.assertEqual(readers, {"read_file"}, "read files only through read_file/read")
        globs = {name for name, body in funcs.items() for arg in re.findall(r"\.r?glob\(([^)]*)\)", body)
                 if not re.fullmatch(r'"[^"{}]*"', arg.strip())}
        # load_profile globs TRAIT_EVIDENCE, a constant; any pattern from a file goes through repo_glob.
        self.assertEqual(globs, {"repo_glob", "load_profile"}, "glob a pattern from a file only through repo_glob")

    def full_fixture(self) -> tuple[Path, dict[str, bool]]:
        """A healthy project where the doctor reads every kind of file it reads; → file → lenient."""
        root = self.fixture(".keelokit/profile.toml")
        render = lambda rel, top=None, entries=None: self.render(rel, *(HEALTHY[rel] if top is None else (top, entries)))
        rules = {"rule": [{**HEALTHY[".keelokit/harness/rules.toml"][1]["rule"][0],
                           "enforced_by": '["file:src/pay/a.ts#export", "test:apps/a/x.test.ts", "ci:checks", "lint:no-console"]'}]}
        exceptions = {"exception": [{**HEALTHY[".keelokit/exceptions.toml"][1]["exception"][0], "rule": '"L-1"'}]}
        story = "backlog/stories/AUTH-001-a.md"
        files = {
            ".keelokit/harness/rules.toml": render(".keelokit/harness/rules.toml", {}, rules),
            ".keelokit/exceptions.toml": render(".keelokit/exceptions.toml", {}, exceptions),
            **{rel: render(rel) for rel in (".keelokit/rules.local.toml", ".keelokit/profile.toml",
                                            ".keelokit/critical.toml", ".keelokit/state.toml")},
            story: self.render("backlog/stories/*.md", *HEALTHY["backlog/stories/*.md"]),
            ".keelokit/answers.yml": "mode: project\n",
            ".github/workflows/ci.yml": CI,
            "eslint.config.mjs": "rules: { 'no-console': 'error' }\n",
            "apps/a/x.test.ts": "// R-1\ntest('AUTH-001.S1 works', () => {})\n",
            "docs/escapes.md": "# Escapes\n",
        }
        for f, text in files.items():
            (root / f).parent.mkdir(parents=True, exist_ok=True)
            (root / f).write_text(text)
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=T", "commit", "-qm", "x\n\nStory: AUTH-001"],
                       cwd=root, check=True, capture_output=True)
        reads = {f: f == "apps/a/x.test.ts" for f in files}
        reads |= {f"docs/context/{f}": False for f in ("product.md", "domain.md", "constraints.md", "environments.md", "gaps.md")}
        reads["src/pay/a.ts"] = False  # file:src/pay/a.ts#export
        return root, reads

    def survives(self, root: Path) -> tuple[int, str]:
        """Every mode runs to the end (no exception escapes); → --ci's exit code and output."""
        self.assertEqual(self.run_doctor(root, "--brief")[0], 0)
        self.assertIn(self.run_doctor(root, "--critical", "--changed")[0], (0, 1))
        self.assertIn(self.run_doctor(root, "--scope", "AUTH-001")[0], (0, 1, 2))
        return self.run_doctor(root, "--ci")

    def test_no_file_saved_in_another_encoding_or_turned_directory_crashes_the_doctor(self):
        """Every file the doctor reads, saved as Latin-1 or replaced by a directory: an ERROR that
        names it (a test file it only scans for titles may hold any bytes), never a traceback."""
        root, reads = self.full_fixture()
        code, out = self.run_doctor(root, "--ci")
        self.assertEqual(code, 0, out)
        self.assertIn("Backlog: 1/1 done", out)
        for f, lenient in reads.items():
            path = root / f
            original = path.read_bytes()
            with self.subTest(f"{f} in Latin-1"):
                path.write_bytes(original + b"\n# raz\xf3n\n")
                code, out = self.survives(root)
                if lenient:
                    self.assertEqual(code, 0, out)
                else:
                    self.assertEqual(code, 1, out)
                    self.assertIn(f"{f}: not UTF-8 (byte 0xf3", out)
            with self.subTest(f"{f} is a directory"):
                path.unlink()
                (path / "x").mkdir(parents=True)
                try:
                    code, out = self.survives(root)
                    self.assertEqual(code, 1, out)
                    self.assertRegex(out, rf"ERROR .*{re.escape(f)}'?:? is a directory")
                finally:
                    shutil.rmtree(path)
            path.write_bytes(original)
        self.assertEqual(self.run_doctor(root, "--ci")[0], 0)

    def test_no_path_in_any_file_crashes_the_doctor_or_reads_outside_the_repo(self):
        """Every key whose value the doctor looks up on disk (an enforcer's path or glob, `when`, a
        critical area) with every kind of path content: one outside the repo (absolute, `..`,
        empty, a NUL) is an ERROR, a directory where it reads a file is an ERROR, and none crashes.
        `touches` is only compared as text, so it just must not crash."""
        root, _ = self.full_fixture()
        outside = r"(is empty|contains a NUL character|must be a path relative to the repo root|must stay inside the repo)"
        rules_rel, critical_rel, story_rel = ".keelokit/harness/rules.toml", ".keelokit/critical.toml", "backlog/stories/AUTH-001-a.md"
        healthy = {f: (root / f).read_text() for f in (rules_rel, critical_rel, story_rel)}
        for value, what in PATH_VALUES.items():
            lit = json.dumps(value)
            cases = []
            for kind, suffix in [("test", ""), ("file", ""), ("file", "#export"), ("script", ""), ("claude-hook", ""), ("git-hook", "")]:
                ref = json.dumps(f"{kind}:{value}{suffix}")
                text = re.sub(r"(?m)^enforced_by = .*$", lambda _: f"enforced_by = [{ref}]", healthy[rules_rel])
                expect = outside if what == "outside" else "is a directory" if what == "dir" and (kind == "test" or suffix) else None
                cases.append((rules_rel, text, rf"rule R-1: .*{expect}" if expect else None, f"{kind}:{value!r}{suffix}"))
            for when in (lit, f"[{lit}]"):
                text = re.sub(r"(?m)^when = .*$", lambda _: f"when = {when}", healthy[rules_rel])
                cases.append((rules_rel, text, rf"rule R-1: when .*{outside}" if what == "outside" else None, f"when = {when}"))
            text = re.sub(r"(?m)^paths = .*$", lambda _: f"paths = [{lit}]", healthy[critical_rel])
            cases.append((critical_rel, text, rf"{critical_rel}: area 'money' path .*{outside}" if what == "outside" else None, f"paths {value!r}"))
            text = re.sub(r"(?m)^touches = .*$", lambda _: f"touches = [{lit}]", healthy[story_rel])
            cases.append((story_rel, text, None, f"touches {value!r}"))
            for rel, text, error, why in cases:
                with self.subTest(why):
                    (root / rel).write_text(text)
                    try:
                        code, out = self.survives(root)
                        self.assertNotIn("invalid TOML", out)
                        if error:
                            self.assertEqual(code, 1, out)
                            self.assertRegex(out, rf"(?m)^  ERROR {error}")
                    finally:
                        (root / rel).write_text(healthy[rel])


if __name__ == "__main__":
    unittest.main()
