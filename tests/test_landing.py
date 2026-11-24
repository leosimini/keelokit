"""`[landing] policy` in .keelokit/state.toml: "direct" (absent = direct) or "convoy" (Harbor lands
batches of delivered branches). Run: python3 -m unittest discover -s tests

The promise these hold: a project without the key behaves exactly as before. With `convoy`,
status.py says which branches are delivered (already on origin) and the doctor adds one note."""
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STATUS = REPO / "template/.keelokit/bin/status.py"
DOCTOR = REPO / "template/.keelokit/bin/doctor.py"
PRE_PUSH = REPO / "template/.githooks/pre-push"
VERIFY_TOOLS = REPO / "template/.keelokit/bin/verify_tools.py"
NOTE = "verifies every push, Harbor's logbook writes included"
# The pre-push hook of 0.11.0, before it skipped a push of only the shared-seals branch.
OLD_PRE_PUSH = "#!/usr/bin/env sh\nexec pnpm verify --use-seal\n"
NOT_FINISHED = "not finished (commits not on main): "
DELIVERED = "delivered, waiting for a convoy: "


def run(cwd: Path, *cmd: str, env: dict | None = None) -> str:
    res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=env)
    if res.returncode != 0 and cmd[0] == "git":
        raise AssertionError(f"{' '.join(cmd)}: {res.stderr}")
    return res.stdout


class Project:
    """A clone of a bare origin with three worktree branches: `a` pushed, `b` never pushed, `c` pushed
    and then given one more local commit (its head is not on origin)."""

    def __init__(self, tmp: Path):
        origin, self.root = tmp / "origin.git", tmp / "repo"
        run(tmp, "git", "init", "-q", "--bare", "-b", "main", str(origin))
        run(tmp, "git", "clone", "-q", str(origin), str(self.root))
        for key, value in (("user.email", "t@example.com"), ("user.name", "T"), ("commit.gpgsign", "false")):
            run(self.root, "git", "config", key, value)
        self.write(".keelokit/bin/status.py", STATUS.read_text())
        self.write(".keelokit/bin/doctor.py", DOCTOR.read_text())
        self.write(".gitignore", ".keelokit/state.toml\n")  # each test writes its own: keep the tree clean
        self.commit("init")
        run(self.root, "git", "push", "-q", "origin", "HEAD:main")
        for branch, commits, push in (("a", 1, True), ("b", 1, False), ("c", 1, True)):
            tree = tmp / f"wt-{branch}"
            run(self.root, "git", "worktree", "add", "-q", str(tree), "-b", branch)
            for n in range(commits):
                run(tree, "git", "commit", "-q", "--allow-empty", "-m", f"{branch} {n}")
            if push:
                run(tree, "git", "push", "-q", "origin", f"HEAD:{branch}")
        run(tmp / "wt-c", "git", "commit", "-q", "--allow-empty", "-m", "c after the push")

    def write(self, rel: str, text: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def commit(self, message: str) -> None:
        run(self.root, "git", "add", "-A")
        run(self.root, "git", "commit", "-q", "--allow-empty", "-m", message)

    def status(self) -> list[str]:
        """status.py's own lines, up to the verify line: the doctor's summary after it is the doctor's."""
        env = {**os.environ, "KEELOKIT_STATUS_OFFLINE": "1"}
        lines = run(self.root, "python3", ".keelokit/bin/status.py", "--no-ci", env=env).splitlines()
        assert len(lines) <= 10, lines
        return lines[:next(i for i, l in enumerate(lines) if l.startswith("verify:")) + 1]

    @staticmethod
    def listed(lines: list[str], prefix: str) -> set[str] | None:
        found = [l.removeprefix(prefix) for l in lines if l.startswith(prefix)]
        return None if not found else (set() if found[0] == "none" else set(found[0].split(", ")))


class StatusTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.p = Project(cls.tmp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def tearDown(self):
        (self.p.root / ".keelokit/state.toml").unlink(missing_ok=True)

    def test_absent_policy_reads_as_before(self):
        lines = self.p.status()
        self.assertEqual(self.p.listed(lines, NOT_FINISHED), {"a (+1)", "b (+1)", "c (+2)"})
        self.assertIsNone(self.p.listed(lines, DELIVERED))

    def test_direct_and_unreadable_policies_change_nothing(self):
        before = self.p.status()
        for text in ('[landing]\npolicy = "direct"\n', '[landing]\npolicy = "convoi"\n', "[landing\nnot toml",
                     "landing = 3\n", '[gates]\nintake = "2026-10-01"\n', '[landing]\npolicy = ["convoy"]\n'):
            with self.subTest(text=text):
                self.p.write(".keelokit/state.toml", text)
                self.assertEqual(self.p.status(), before)

    def test_convoy_splits_delivered_from_not_finished(self):
        self.p.write(".keelokit/state.toml", '[landing]\npolicy = "convoy"\n')
        lines = self.p.status()
        self.assertEqual(self.p.listed(lines, DELIVERED), {"a (+1)"})
        # b was never pushed; c has a commit after its push: neither is delivered.
        self.assertEqual(self.p.listed(lines, NOT_FINISHED), {"b (+1)", "c (+2)"})


class DoctorFixture(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        files = {".keelokit/bin/doctor.py": DOCTOR.read_text(), "README.md": "# r\n",
                 ".githooks/pre-push": OLD_PRE_PUSH,
                 "docs/context/gaps.md": "| Id | File | Missing | Owner | Question | Blocking |\n|---|---|---|---|---|---|\n"}
        files |= {f"docs/context/{f}.md": f"# {f}\n" for f in ("product", "domain", "constraints", "environments")}
        for rel, text in files.items():
            self.write(rel, text)
        run(self.root, "git", "init", "-q", "-b", "main")

    def write(self, rel: str, text: str) -> None:
        (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
        (self.root / rel).write_text(text)

    def doctor(self, *args: str) -> str:
        return run(self.root, "python3", ".keelokit/bin/doctor.py", *args)


class DoctorLandingTest(DoctorFixture):
    def test_absent_policy_reads_as_before(self):
        absent = self.doctor(), self.doctor("--brief")
        self.assertNotIn(NOTE, absent[0])
        self.assertNotIn("landing", absent[0])
        self.write(".keelokit/state.toml", '[landing]\npolicy = "direct"\n')
        self.assertEqual((self.doctor(), self.doctor("--brief")), absent)

    def test_HARN_012_S1_convoy_with_a_hook_that_verifies_every_push_says_so(self):
        before = self.doctor()
        self.write(".keelokit/state.toml", '[landing]\npolicy = "convoy"\n')
        out = self.doctor()
        self.assertRegex(out, rf"(?m)^  warn  landing: policy is convoy, and .githooks/pre-push {NOTE} ")
        self.assertNotIn("ERROR", out)
        # The note is the only difference.
        self.assertEqual([l for l in out.splitlines() if NOTE not in l], before.splitlines())
        self.assertIn("harness-upgrade", out)
        self.assertNotIn("only what reaches main", out)
        self.assertEqual((self.root / ".githooks/pre-push").read_text(), OLD_PRE_PUSH, "the doctor never edits the hook")

    def test_HARN_012_S2_no_note_when_the_hook_skips_the_seal_branch_or_is_missing(self):
        self.write(".keelokit/state.toml", '[landing]\npolicy = "convoy"\n')
        self.write(".githooks/pre-push", "#!/usr/bin/env sh\npython3 .keelokit/bin/verify_tools.py seal-branch-only \"$1\"\n")
        self.assertNotIn(NOTE, self.doctor())
        self.write(".githooks/pre-push", PRE_PUSH.read_text())  # the template's own hook (HARN-010)
        self.assertNotIn(NOTE, self.doctor())
        (self.root / ".githooks/pre-push").unlink()
        self.assertNotIn(NOTE, self.doctor())

    def test_unknown_policy_is_an_error_that_names_the_file(self):
        self.write(".keelokit/state.toml", '[landing]\npolicy = "convoi"\n')
        self.assertRegex(self.doctor(), r'(?m)^  ERROR \.keelokit/state\.toml: \[landing\] policy is "direct" or "convoy"')


class DoctorSharedSealsTest(DoctorFixture):
    """HARN-008: the doctor checks the shape of [verify] shared_seals, which verify_tools.py reads."""

    def test_HARN_008_S5_the_doctor_checks_the_shared_seals_key(self):
        self.write(".keelokit/state.toml", '[verify]\nshared_seals = "origin/harbor/log:harbor/seals/{head}.toml"\n')
        self.assertNotIn("shared_seals", self.doctor())
        for bad in ('"harbor/seals/{head}.toml"', '"origin/harbor/log:seals.toml"', '"origin/../x:{head}"', "3",
                    '"origin/main:harbor/seals/{head}.toml"', '"origin/harbor/log:{head}.toml"'):
            with self.subTest(bad=bad):
                self.write(".keelokit/state.toml", f"[verify]\nshared_seals = {bad}\n")
                self.assertRegex(self.doctor(), r"(?m)^  ERROR \.keelokit/state\.toml: \[verify\] shared_seals is ")


class DoctorWipBranchesTest(DoctorFixture):
    """HARN-017: the doctor checks the shape of [verify] wip_branches, which verify_tools.py reads."""

    def test_HARN_017_S5_the_doctor_checks_the_wip_branches_key(self):
        self.write(".keelokit/state.toml", '[verify]\nwip_branches = "wip/"\n')
        self.assertNotIn("wip_branches", self.doctor())
        for bad in ('"wip"', '"/"', '"refs/heads/wip/"', '"Wip/"', "true"):
            with self.subTest(bad=bad):
                self.write(".keelokit/state.toml", f"[verify]\nwip_branches = {bad}\n")
                self.assertRegex(self.doctor(), r"(?m)^  ERROR \.keelokit/state\.toml: \[verify\] wip_branches is ")


class TextsTest(unittest.TestCase):
    """The pages agents read: the direct path stays word for word, the convoy path is there."""

    def read(self, rel: str) -> str:
        return (REPO / rel).read_text()

    def test_brief_keeps_direct_landing_and_adds_convoy_on_one_page(self):
        brief = self.read("template/.keelokit/harness/agent-brief.md")
        direct = re.search(r"(?s)## Landing — `direct` \(the default\)\n\n(.*?)\n\n## ", brief).group(1)
        self.assertEqual(direct, """\
1. `git fetch origin main && git rebase origin/main`. A conflict only in formatting: keep **your**
   content and run `pnpm format` (FMT-1). A real conflict: stop and say which files.
2. `pnpm verify` — never `--no-verify`. It takes the machine's verify lock, so two sessions on one
   laptop wait for each other instead of starving each other into fake timeouts.
3. `git push origin HEAD:main` (or the repo's way). If main moved, go back to 1.
4. `git log origin/main --oneline -1` shows your commit. That hash is the report.""")
        convoy = re.search(r"(?s)## Landing — `convoy`\n\n(.*?)\n\n## ", brief).group(1)
        for needle in ("never pushes to main", "`pnpm verify` green on the final commit", "it seals",
                       "branch + full hash + tier + verify result"):
            self.assertIn(needle, convoy)
        self.assertIn("absent = `direct`", brief)
        self.assertLessEqual(len(brief.splitlines()), 90, "the brief is one page")

    def test_models_table_and_agents_default_to_sonnet(self):
        brief = self.read("template/.keelokit/harness/agent-brief.md")
        models = re.search(r"(?s)## Models\n(.*?)\n## ", brief).group(1)
        for model in ("Haiku", "Sonnet", "Opus"):
            self.assertIn(model, models)
        for agent in sorted((REPO / "agents").glob("*.md")):
            with self.subTest(agent=agent.name):
                front = agent.read_text().split("---")[1]
                self.assertRegex(front, r"(?m)^model: sonnet$")
        self.assertIn("Opus in full tier", self.read("skills/build-story/SKILL.md"))

    def test_coordinate_and_protocol_branch_only_on_convoy(self):
        coordinate = self.read("skills/coordinate/SKILL.md")
        self.assertRegex(coordinate, r"absent = `direct`.*\n.*`/harbor:\*`")
        for section in ("## Start sessions", "## Every round", "## Report to the user"):
            self.assertIn(section, coordinate)
        protocol = self.read("template/.keelokit/harness/execution-protocol.md")
        done = re.search(r"(?s)## Done means\n(.*?)\n## ", protocol).group(1)
        self.assertIn('policy = "convoy"', done)


class UnverifiedPrefixesTest(unittest.TestCase):
    """LEDGER-008: the pre-push runs no verify for archive/ (ledger.py drop's abandoned attempts), as for the
    wip/ branches of [verify] wip_branches; verify_tools.py keeps the list of unverified prefixes."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.origin, self.root = self.tmp / "origin.git", self.tmp / "repo"
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        self.env.update(GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1", HOME=str(self.tmp))
        stubs = self.tmp / "stubs"
        stubs.mkdir()
        self.calls = self.tmp / "pnpm-calls"
        (stubs / "pnpm").write_text(f'#!/bin/sh\necho "pnpm $*" >> "{self.calls}"\nexit 1\n')
        (stubs / "pnpm").chmod(0o755)
        self.env["PATH"] = f"{stubs}:{self.env['PATH']}"
        self.git(self.tmp, "init", "-q", "--bare", "-b", "main", str(self.origin))
        self.git(self.tmp, "clone", "-q", str(self.origin), str(self.root))
        for key, value in (("user.email", "t@example.com"), ("user.name", "T"), ("commit.gpgsign", "false")):
            self.git(self.root, "config", key, value)
        for rel, src in ((".keelokit/bin/verify_tools.py", VERIFY_TOOLS), (".githooks/pre-push", PRE_PUSH)):
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, self.root / rel)
        (self.root / ".githooks/pre-push").chmod(0o755)

    def git(self, cwd: Path, *args: str) -> str:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env=self.env)
        if r.returncode:
            raise AssertionError(f"git {' '.join(args)}: {r.stderr}")
        return r.stdout

    def main_with(self, state: str | None) -> None:
        if state is not None:
            (self.root / ".keelokit/state.toml").write_text(state)
        self.git(self.root, "add", "-A")
        self.git(self.root, "commit", "-q", "--allow-empty", "-m", "init")
        self.git(self.root, "push", "-q", "origin", "HEAD:main")
        self.git(self.root, "config", "core.hooksPath", ".githooks")

    def prefixes(self) -> list[str]:
        r = subprocess.run(["python3", ".keelokit/bin/verify_tools.py", "unverified-prefixes", "origin"],
                           cwd=self.root, capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.split()

    def push(self, *refs: str) -> subprocess.CompletedProcess:
        self.calls.unlink(missing_ok=True)
        return subprocess.run(["git", "push", "-q", "origin", *refs], cwd=self.root, capture_output=True,
                              text=True, env=self.env, timeout=60)

    def verified(self) -> bool:
        return self.calls.exists() and "pnpm verify" in self.calls.read_text()

    def test_LEDGER_008_S4_the_unverified_prefixes_are_wip_branches_and_archive(self):
        self.main_with('[verify]\nwip_branches = "wip/"\n')
        self.assertEqual(self.prefixes(), ["wip/", "archive/"])

    def test_LEDGER_008_S4_archive_is_unverified_without_any_key(self):
        self.main_with(None)
        self.assertEqual(self.prefixes(), ["archive/"])

    def test_LEDGER_008_S4_wip_branches_set_to_archive_is_listed_once(self):
        self.main_with('[verify]\nwip_branches = "archive/"\n')
        self.assertEqual(self.prefixes(), ["archive/"])

    def test_LEDGER_008_S4_a_push_to_archive_runs_no_verify(self):
        self.main_with(None)
        self.git(self.root, "commit", "-q", "--allow-empty", "-m", "drop(AUTH-002): x\n\nDropped: AUTH-002")
        r = self.push("HEAD:refs/heads/archive/auth-002-20261124")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(self.verified(), "no verify for archive/")
        self.assertIn("is archive work: not verified", r.stdout)
        self.assertTrue(self.git(self.root, "ls-remote", "origin", "refs/heads/archive/auth-002-20261124").strip())

    def test_LEDGER_008_S4_a_push_to_any_other_branch_still_verifies(self):
        self.main_with('[verify]\nwip_branches = "wip/"\n')
        self.git(self.root, "commit", "-q", "--allow-empty", "-m", "work")
        r = self.push("HEAD:refs/heads/archived/x")  # a name that only starts like archive/
        self.assertNotEqual(r.returncode, 0, "the stub pnpm fails")
        self.assertTrue(self.verified())

    def test_LEDGER_008_S4_a_push_that_holds_an_archived_attempt_is_refused_before_a_verify(self):
        self.main_with(None)
        self.git(self.root, "commit", "-q", "--allow-empty", "-m", "drop(AUTH-002): x\n\nDropped: AUTH-002")
        self.assertEqual(self.push("HEAD:refs/heads/archive/auth-002-20261124").returncode, 0)
        self.git(self.root, "commit", "-q", "--allow-empty", "-m", "carried on from the abandoned attempt")
        r = self.push("HEAD:refs/heads/feature")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("unverified wip work", r.stderr)
        self.assertFalse(self.verified(), "refused before any verify")


if __name__ == "__main__":
    unittest.main()
