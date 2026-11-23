"""ledger.py history: the SessionStart hook completes the trunk's history (LEDGER-002).
Run: python3 -m unittest discover -s tests

Everything runs against real git with local remotes (file:// and a refused http port), never the
network. The slow server is git's own `remote.origin.uploadpack` (a `sleep` in front of
git-upload-pack); the server that rejects --filter is a `git` wrapper first on PATH that logs its
argv. Each git call runs with a clean environment: no proxy, no global or system config."""
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import time
import unittest
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DOCTOR = REPO / "template/.keelokit/bin/doctor.py"
LEDGER = REPO / "template/.keelokit/bin/ledger.py"
OFFLINE = "http://127.0.0.1:9/x.git"  # discard port: refused at once
PROXY_VARS = {"http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "all_proxy",
              "no_proxy", "NO_PROXY", "GIT_PROXY_COMMAND", "GIT_SSL_CAINFO"}

STORY = """\
+++
id = "{id}"
epic = "AUTH"
title = "t"
wave = {wave}
depends_on = []
touches = ["{path}"]
dimensions = ["api"]
+++
```gherkin
Scenario: [S1] works
Scenario: [S10] also works
```
"""


def clean_env(home: Path, path: str | None = None) -> dict:
    env = {k: v for k, v in os.environ.items()
           if k not in PROXY_VARS and not k.startswith("GIT_") and k not in ("CI", "GITHUB_ACTIONS")}
    env.update(GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1", HOME=str(home), LC_ALL="C",
               GIT_TERMINAL_PROMPT="0")
    if path is not None:
        env["PATH"] = path
    return env


class LedgerHistoryTest(unittest.TestCase):
    """An origin with six stories, four done (AUTH-001..004), as in LEDGER-001's fixture, with the
    doctor and ledger.py committed; clones of it, shallow or not."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.env = clean_env(self.tmp)
        self.origin = self.tmp / "origin"
        self.make_origin()

    # ── fixtures ──
    def git(self, cwd: Path, *args: str, check: bool = True, env: dict | None = None) -> str:
        r = subprocess.run(["git", *args], cwd=cwd, env=env or self.env, capture_output=True, text=True,
                           timeout=60)
        if check and r.returncode:
            raise AssertionError(f"fixture: git {' '.join(args)} failed\n{r.stderr}")
        return r.stdout

    def write(self, rel: str, text: str) -> None:
        path = self.origin / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text))

    def commit(self, message: str) -> None:
        self.git(self.origin, "add", "-A")
        self.git(self.origin, "commit", "-qm", message, "--allow-empty")

    def make_origin(self) -> None:
        self.origin.mkdir()
        self.git(self.origin, "init", "-q", "-b", "main")
        self.git(self.origin, "config", "user.email", "t@example.com")
        self.git(self.origin, "config", "user.name", "T")
        self.write(".keelokit/bin/doctor.py", DOCTOR.read_text())
        if LEDGER.exists():
            self.write(".keelokit/bin/ledger.py", LEDGER.read_text())
        self.write(".keelokit/harness/rules.toml", "")
        self.write(".github/workflows/ci.yml",
                   "name: CI\njobs:\n  checks:\n    runs-on: ubuntu-latest\n    steps:\n"
                   "      - uses: actions/checkout@v4\n      - run: pnpm lint\n")
        self.write("eslint.config.mjs", "rules: { 'no-explicit-any': 'error', 'no-console': 'off' }")
        for f in ("product", "domain", "constraints", "environments"):
            self.write(f"docs/context/{f}.md", f"# {f}\n")
        self.write("docs/context/gaps.md",
                   "| Id | File | Missing | Owner | Question | Blocking |\n|---|---|---|---|---|---|\n")
        layout = {"AUTH-001": (1, "apps/api/a1/"), "AUTH-002": (1, "apps/api/a2/"), "AUTH-003": (2, "apps/api/a3/"),
                  "AUTH-004": (2, "apps/api/a4/"), "AUTH-005": (3, "apps/api/a5/"), "AUTH-006": (3, "apps/api/a6/")}
        for sid, (wave, path) in layout.items():
            self.write(f"backlog/stories/{sid}-a.md", STORY.format(id=sid, wave=wave, path=path))
            self.write(f"{path}x.ts", "export {}\n")
        cites = [f"    def test_AUTH_00{n}_S{s}_works(self):\n        pass\n" for n in range(1, 5) for s in (1, 10)]
        self.write("tests/test_auth.py", "import unittest\n\n\nclass T(unittest.TestCase):\n" + "\n".join(cites))
        self.commit("docs: plan AUTH")
        for sid in ("AUTH-001", "AUTH-002", "AUTH-003"):
            self.commit(f"feat: {sid}\n\nStory: {sid}")
        self.commit("chore: x")
        self.commit("feat: AUTH-004\n\nStory: AUTH-004")
        self.commit("chore: y")

    def clone(self, depth: int | None = 3, name: str = "clone") -> Path:
        clone = self.tmp / name
        self.git(self.tmp, "clone", "-q", *([f"--depth={depth}"] if depth else []), f"file://{self.origin}", str(clone))
        self.assertEqual(self.shallow(clone), bool(depth), "fixture: the clone is (not) shallow as intended")
        return clone

    def shallow(self, clone: Path) -> bool:
        return self.git(clone, "rev-parse", "--is-shallow-repository").strip() == "true"

    @staticmethod
    def state(clone: Path, text: str) -> None:
        (clone / ".keelokit/state.toml").write_text(textwrap.dedent(text))

    def wrapper(self, reject_filter: bool = False) -> tuple[str, Path]:
        """A `git` first on PATH that logs each argv as one line; with reject_filter, a fetch with
        --filter fails the way a server without filter support makes it fail."""
        bindir = self.tmp / "wrap-bin"
        bindir.mkdir(exist_ok=True)
        log = self.tmp / "git-argv.log"
        log.touch()
        real = shutil.which("git", path=self.env["PATH"])
        reject = ('case " $* " in *" --filter"*) echo "fatal: filtering not supported by server" >&2; exit 128;; esac\n'
                  if reject_filter else "")
        script = bindir / "git"
        script.write_text(f'#!/bin/sh\nprintf \'%s\\n\' "$*" >> "{log}"\n{reject}exec "{real}" "$@"\n')
        script.chmod(0o755)
        return f"{bindir}{os.pathsep}{self.env['PATH']}", log

    @staticmethod
    def fetches(log: Path) -> list[str]:
        return [line for line in log.read_text().splitlines() if re.search(r"(^|\s)fetch(\s|$)", line)]

    def ledger(self, clone: Path, *args: str, path: str | None = None, timeout: float = 45) -> tuple[subprocess.CompletedProcess, float]:
        script = clone / ".keelokit/bin/ledger.py"
        self.assertTrue(script.exists(), "template/.keelokit/bin/ledger.py does not exist yet")
        env = clean_env(self.tmp, path or self.env["PATH"])
        start = time.monotonic()
        try:
            r = subprocess.run(["python3", ".keelokit/bin/ledger.py", *args], cwd=clone, env=env,
                               stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            self.fail(f"ledger.py {' '.join(args)} still running after {timeout}s (or something it started holds its output)")
        return r, time.monotonic() - start

    def doctor_brief(self, clone: Path) -> str:
        r = subprocess.run(["python3", ".keelokit/bin/doctor.py", "--brief"], cwd=clone, env=self.env,
                           capture_output=True, text=True, timeout=60)
        return r.stdout

    @staticmethod
    def backlog_line(out: str) -> str:
        return next((line for line in out.splitlines() if "Backlog" in line), "")

    def one_line(self, r: subprocess.CompletedProcess) -> str:
        """DX: every outcome is one line, starting `Keelokit:`, and nothing else (git's own output included)."""
        out = r.stdout + r.stderr
        self.assertNotIn("Traceback", out)
        lines = [line for line in out.splitlines() if line.strip()]
        self.assertEqual(len(lines), 1, f"exactly one line expected:\n{out}")
        self.assertTrue(lines[0].startswith("Keelokit:"), lines[0])
        self.assertEqual(r.returncode, 0, out)
        return lines[0]

    def slow_origin(self, clone: Path, seconds: int = 30) -> str:
        """Every fetch from this clone waits `seconds` before the server answers. Returns a pattern
        that matches the waiting processes (and nothing else on the machine)."""
        tag = f"{seconds}.{uuid.uuid4().int % 10**8:08d}"
        self.git(clone, "config", "remote.origin.uploadpack", f"sleep {tag}; git-upload-pack")
        pattern = f"sleep {re.escape(tag)}"
        self.addCleanup(subprocess.run, ["pkill", "-9", "-f", pattern], capture_output=True)
        return pattern

    def left_over(self, pattern: str) -> str:
        return subprocess.run(["pgrep", "-af", pattern], capture_output=True, text=True).stdout.strip()

    # ── S1 ──
    def test_LEDGER_002_S1_a_shallow_clone_with_network_is_completed_and_the_doctor_counts(self):
        self.git(self.origin, "config", "uploadpack.allowFilter", "true")  # a server like GitHub's
        clone = self.clone(3)
        self.assertIn("unknown", self.backlog_line(self.doctor_brief(clone)).lower(), "fixture: unknown before")
        r, _ = self.ledger(clone, "history", "--ensure")
        line = self.one_line(r)
        self.assertRegex(line, r"^Keelokit: history completed \(\d+ commits of main\) in \d+(\.\d+)?s$")
        self.assertFalse(self.shallow(clone))
        self.assertIn("Context gaps: 0 (0 blocking) · Backlog: 4/6 done", self.doctor_brief(clone).splitlines())

    def test_LEDGER_002_S1_the_fetch_asks_for_commits_only(self):
        """--filter=blob:none, so a large repo does not pay for every old file."""
        self.git(self.origin, "config", "uploadpack.allowFilter", "true")
        clone = self.clone(3)
        path, log = self.wrapper()
        r, _ = self.ledger(clone, "history", "--ensure", path=path)
        self.one_line(r)
        fetches = self.fetches(log)
        self.assertTrue(fetches, "no fetch ran")
        first = fetches[0].split()
        for arg in ("--filter=blob:none", "--unshallow", "origin", "main"):
            self.assertIn(arg, first, fetches[0])
        self.assertFalse(self.shallow(clone))

    # ── S2 ──
    def test_LEDGER_002_S2_offline_is_one_line_exit_0_and_the_doctor_says_unknown(self):
        clone = self.clone(3)
        self.git(clone, "remote", "set-url", "origin", OFFLINE)
        r, elapsed = self.ledger(clone, "history", "--ensure")
        line = self.one_line(r)
        self.assertIn("offline: history incomplete", line)
        self.assertIn("git fetch --unshallow origin main", line)
        self.assertLess(elapsed, 15, "a refused connection is not a reason to wait for the cap")
        self.assertTrue(self.shallow(clone))
        self.assertIn("unknown", self.backlog_line(self.doctor_brief(clone)).lower())

    # ── S3 ──
    def test_LEDGER_002_S3_a_server_that_ignores_the_filter_gives_a_complete_history(self):
        """A file:// remote: git warns 'filtering not recognized by server, ignoring' and fetches
        everything. No promisor config is left behind, so later fetches don't warn forever."""
        self.git(self.origin, "config", "uploadpack.allowFilter", "false")
        clone = self.clone(3)
        r, _ = self.ledger(clone, "history", "--ensure")
        line = self.one_line(r)
        self.assertIn("history completed", line)
        self.assertNotIn("filtering", line)
        self.assertFalse(self.shallow(clone))
        missing = [l for l in self.git(clone, "rev-list", "--objects", "--missing=print", "--all").splitlines()
                   if l.startswith("?")]
        self.assertEqual(missing, [], "every object of the history is there")
        for key in ("remote.origin.promisor", "remote.origin.partialclonefilter"):
            self.assertEqual(self.git(clone, "config", "--get", key, check=False).strip(), "", key)
        self.assertIn("Context gaps: 0 (0 blocking) · Backlog: 4/6 done", self.doctor_brief(clone).splitlines())

    def test_LEDGER_002_S3_a_server_that_rejects_the_filter_gets_a_plain_unshallow(self):
        clone = self.clone(3)
        path, log = self.wrapper(reject_filter=True)
        r, _ = self.ledger(clone, "history", "--ensure", path=path)
        line = self.one_line(r)
        self.assertIn("history completed", line)
        fetches = self.fetches(log)
        self.assertTrue(any("--filter" in f for f in fetches), f"the filtered fetch is tried first: {fetches}")
        first_filtered = next(i for i, f in enumerate(fetches) if "--filter" in f)
        plain = [f.split() for f in fetches[first_filtered + 1:] if "--filter" not in f]
        self.assertTrue(plain, f"no plain fetch after the rejected filter: {fetches}")
        self.assertTrue(all(a in plain[-1] for a in ("--unshallow", "origin", "main")), fetches)
        self.assertFalse(self.shallow(clone))
        missing = [l for l in self.git(clone, "rev-list", "--objects", "--missing=print", "--all").splitlines()
                   if l.startswith("?")]
        self.assertEqual(missing, [])

    # ── S4 ──
    def test_LEDGER_002_S4_the_cap_cuts_a_slow_fetch_and_leaves_nothing_behind(self):
        clone = self.clone(3)
        self.state(clone, "[ledger]\nhistory_seconds = 2\n")
        pattern = self.slow_origin(clone, 30)
        r, elapsed = self.ledger(clone, "history", "--ensure", timeout=25)
        line = self.one_line(r)
        self.assertIn("cut at 2s: history incomplete", line)
        self.assertIn("git fetch --unshallow origin main", line)
        self.assertGreaterEqual(elapsed, 1.5, "it waited for the cap, not less")
        self.assertLess(elapsed, 8, "stops at the cap (plus a short grace), not at the fetch's length")
        self.assertEqual(self.left_over(pattern), "", "the fetch's process group outlived the cap")
        self.assertFalse((clone / ".git/shallow.lock").exists(), "git was stopped without removing its lock")
        self.assertFalse(list((clone / ".git").glob("*.lock")), "a lock file left behind")
        self.assertTrue(self.shallow(clone))
        self.assertIn("unknown", self.backlog_line(self.doctor_brief(clone)).lower())

    def test_LEDGER_002_S4_nfr_a_cap_above_20_is_clamped_to_20(self):
        """The hook's timeout is fixed at 30 s and the doctor must still run after it."""
        clone = self.clone(3)
        self.state(clone, "[ledger]\nhistory_seconds = 60\n")
        pattern = self.slow_origin(clone, 40)
        r, elapsed = self.ledger(clone, "history", "--ensure", timeout=35)
        line = self.one_line(r)
        self.assertIn("cut at 20s", line)
        self.assertGreaterEqual(elapsed, 18)
        self.assertLess(elapsed, 26, "the hook's 30 s must leave room for the doctor")
        self.assertEqual(self.left_over(pattern), "")

    # ── S5 ──
    def test_LEDGER_002_S5_a_complete_history_fetches_nothing_and_prints_nothing(self):
        clone = self.clone(None)
        self.git(clone, "remote", "set-url", "origin", OFFLINE)
        path, log = self.wrapper()
        r, _ = self.ledger(clone, "history", "--ensure", path=path)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
        self.assertEqual(self.fetches(log), [], "no fetch on a complete history")

    # ── dx / logic: report-only mode, trunk, config ──
    def test_LEDGER_002_dx_history_without_ensure_reports_and_never_fetches(self):
        path, log = self.wrapper()
        shallow = self.clone(3)
        r, _ = self.ledger(shallow, "history", path=path)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertTrue(self.shallow(shallow))
        full = self.clone(None, "full")
        r, _ = self.ledger(full, "history", path=path)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.fetches(log), [], "`history` without --ensure only reads")

    def test_LEDGER_002_dx_history_outside_a_git_repo_exits_2(self):
        where = self.tmp / "nogit"
        (where / ".keelokit/bin").mkdir(parents=True)
        if LEDGER.exists():
            shutil.copy(LEDGER, where / ".keelokit/bin/ledger.py")
        r, _ = self.ledger(where, "history")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        r, _ = self.ledger(where, "history", "--ensure")
        self.assertEqual(r.returncode, 0, "--ensure never fails the session")
        self.assertNotIn("Traceback", r.stdout + r.stderr)

    def trunk_case(self, state: str) -> None:
        self.git(self.origin, "branch", "develop", "main")
        clone = self.clone(3)
        self.state(clone, state)
        path, log = self.wrapper()
        r, _ = self.ledger(clone, "history", "--ensure", path=path)
        line = self.one_line(r)
        self.assertIn("of develop)", line)
        fetches = self.fetches(log)
        self.assertTrue(fetches and all("origin develop" in f for f in fetches), fetches)
        self.assertFalse(self.shallow(clone))

    def test_LEDGER_002_logic_the_trunk_comes_from_ledger_trunk(self):
        self.trunk_case('[ledger]\ntrunk = "develop"\n\n[harbor]\ntrunk = "main"\n')

    def test_LEDGER_002_logic_the_trunk_falls_back_to_harbor_trunk(self):
        self.trunk_case('[harbor]\ntrunk = "develop"\n')

    def test_LEDGER_002_nfr_a_trunk_that_looks_like_an_option_is_never_passed_to_git(self):
        clone = self.clone(3)
        pwned = self.tmp / "PWNED"
        self.state(clone, f'[ledger]\ntrunk = "--upload-pack=touch {pwned}"\n')
        path, log = self.wrapper()
        r, _ = self.ledger(clone, "history", "--ensure", path=path)
        out = r.stdout + r.stderr
        self.assertEqual(r.returncode, 0, out)
        self.assertNotIn("Traceback", out)
        self.assertLessEqual(len([l for l in out.splitlines() if l.strip()]), 1, out)
        self.assertFalse(pwned.exists())
        self.assertFalse([f for f in self.fetches(log) if "--upload-pack" in f], log.read_text())

    def test_LEDGER_002_nfr_a_broken_state_toml_does_not_crash(self):
        clone = self.clone(3)
        self.state(clone, "[ledger\nhistory_seconds = \n")
        r, _ = self.ledger(clone, "history", "--ensure")
        out = r.stdout + r.stderr
        self.assertEqual(r.returncode, 0, out)
        self.assertNotIn("Traceback", out)
        lines = [l for l in out.splitlines() if l.strip()]
        self.assertLessEqual(len(lines), 1, out)
        self.assertTrue(all(l.startswith("Keelokit:") for l in lines), out)

    def test_LEDGER_002_nfr_a_non_positive_or_non_number_cap_falls_back_to_the_default(self):
        """0, -5 or "abc" would cut at once if taken literally: the default (20) applies."""
        for value in ("0", "-5", '"abc"'):
            with self.subTest(value=value):
                clone = self.clone(3, f"clone-{abs(hash(value))}")
                self.state(clone, f"[ledger]\nhistory_seconds = {value}\n")
                r, _ = self.ledger(clone, "history", "--ensure")
                self.assertIn("history completed", self.one_line(r))
                self.assertFalse(self.shallow(clone))

    def test_LEDGER_002_dx_no_origin_remote_is_one_line(self):
        clone = self.clone(3)
        self.git(clone, "remote", "remove", "origin")
        r, _ = self.ledger(clone, "history", "--ensure")
        self.assertIn("no origin: history incomplete", self.one_line(r))

    def test_LEDGER_002_nfr_the_two_copies_are_identical(self):
        self.assertTrue(LEDGER.exists(), "template/.keelokit/bin/ledger.py does not exist yet")
        self.assertEqual((REPO / ".keelokit/bin/ledger.py").read_text(), LEDGER.read_text())


if __name__ == "__main__":
    unittest.main()
