"""ledger.py history: the SessionStart hook completes the trunk's history (LEDGER-002);
ledger.py and ledger.py --json: every story's state from git (LEDGER-003, the classes after LedgerHistoryTest).
Run: python3 -m unittest discover -s tests

Everything runs against real git with local remotes (file:// and a refused http port), never the
network. The slow server is git's own `remote.origin.uploadpack` (a `sleep` in front of
git-upload-pack); the server that rejects --filter is a `git` wrapper first on PATH that logs its
argv. Each git call runs with a clean environment: no proxy, no global or system config."""
import http.server
import json
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import threading
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
        # Every commit changes churn.txt: a commits-only (blob:none) fetch really leaves old blobs out.
        self.n_commits = getattr(self, "n_commits", 0) + 1
        self.write("churn.txt", f"version {self.n_commits}: {message.splitlines()[0]}\n")
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
        --filter fails the way a server without filter support makes it fail, after writing the
        promisor config first, as real git does before it contacts the server."""
        bindir = self.tmp / "wrap-bin"
        bindir.mkdir(exist_ok=True)
        log = self.tmp / "git-argv.log"
        log.touch()
        real = shutil.which("git", path=self.env["PATH"])
        reject = ('case " $* " in *" --filter"*)\n'
                  f'  "{real}" config remote.origin.promisor true\n'
                  f'  "{real}" config remote.origin.partialclonefilter blob:none\n'
                  '  echo "fatal: filtering not supported by server" >&2; exit 128;;\nesac\n'
                  if reject_filter else "")
        script = bindir / "git"
        script.write_text(f'#!/bin/sh\nprintf \'%s\\n\' "$*" >> "{log}"\n{reject}exec "{real}" "$@"\n')
        script.chmod(0o755)
        return f"{bindir}{os.pathsep}{self.env['PATH']}", log

    @staticmethod
    def fetches(log: Path) -> list[str]:
        return [line for line in log.read_text().splitlines() if re.search(r"(^|\s)fetch(\s|$)", line)]

    FILTER_KEYS = ("remote.origin.promisor", "remote.origin.partialclonefilter", "extensions.partialclone")

    def filter_config(self, clone: Path) -> dict:
        """The partial-clone config of the clone, key -> value, only the keys that are set."""
        out = {}
        for key in self.FILTER_KEYS:
            value = self.git(clone, "config", "--local", "--get", key, check=False).strip()
            if value:
                out[key] = value
        return out

    def assert_filter_config_as_before(self, clone: Path, before: dict, when: str) -> None:
        """The class check (ESC, LEDGER-002 round 2): after any --ensure that does not end as a
        complete fetch whose filter the server honoured, the filter config is what it was before
        the run: a failed, cut, ignored or rejected filter leaves nothing behind."""
        self.assertEqual(self.filter_config(clone), before, f"filter config changed {when}")

    def ledger(self, clone: Path, *args: str, path: str | None = None, timeout: float = 45,
               extra_env: dict | None = None) -> tuple[subprocess.CompletedProcess, float]:
        script = clone / ".keelokit/bin/ledger.py"
        self.assertTrue(script.exists(), "template/.keelokit/bin/ledger.py does not exist yet")
        env = clean_env(self.tmp, path or self.env["PATH"])
        env.update(extra_env or {})
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
        self.assert_filter_config_as_before(clone, {}, "after the plain fallback")
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

    # ── round 2: what review and the breaker found (each reproduced before the fix) ──
    def assert_partial_clone_sound(self, clone: Path) -> None:
        """Old blobs are missing on purpose, and git can still read every commit: the promisor
        config that lets it fetch them on demand is there."""
        self.assertEqual(self.git(clone, "config", "--get", "remote.origin.promisor", check=False).strip(), "true",
                         "the promisor config of a working partial clone was removed")
        self.assertEqual(self.git(clone, "config", "--get", "remote.origin.partialclonefilter", check=False).strip(),
                         "blob:none")
        oldest = self.git(clone, "rev-list", "--max-parents=0", "HEAD").split()[0]
        show = subprocess.run(["git", "show", f"{oldest}:churn.txt"], cwd=clone, env=self.env,
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(show.returncode, 0, show.stderr)
        self.assertIn("version 1:", show.stdout)
        for args in (["log", "-p"], ["fsck"]):
            r = subprocess.run(["git", *args], cwd=clone, env=self.env, capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, f"git {' '.join(args)}: {r.stderr[-500:]}")
            self.assertNotRegex(r.stderr, r"(?m)^(fatal|error|missing)", f"git {' '.join(args)}")

    def test_LEDGER_002_S1_a_filtered_fetch_that_worked_keeps_the_partial_clone_readable(self):
        """Review: the cleanup meant for an IGNORED filter also ran after a filter the server
        honoured (GitHub's case): promisor config gone, old blobs missing, `git log -p` fatal."""
        self.git(self.origin, "config", "uploadpack.allowFilter", "true")
        clone = self.clone(3)
        r, _ = self.ledger(clone, "history", "--ensure")
        self.assertIn("history completed", self.one_line(r))
        self.assertFalse(self.shallow(clone))
        self.assert_partial_clone_sound(clone)

    def test_LEDGER_002_S1_a_clone_that_was_already_partial_keeps_its_config(self):
        self.git(self.origin, "config", "uploadpack.allowFilter", "true")
        clone = self.tmp / "partial"
        self.git(self.tmp, "clone", "-q", "--depth=3", "--filter=blob:none", f"file://{self.origin}", str(clone))
        self.assertTrue(self.shallow(clone), "fixture")
        r, _ = self.ledger(clone, "history", "--ensure")
        self.assertIn("history completed", self.one_line(r))
        self.assertFalse(self.shallow(clone))
        self.assert_partial_clone_sound(clone)

    def test_LEDGER_002_S1_a_single_branch_clone_of_another_branch_gets_the_trunk(self):
        """Breaker: `clone --depth 1 -b side --single-branch` never created origin/main, and the line
        gave HEAD's count as main's, so the doctor still could not count."""
        self.git(self.origin, "branch", "side", "main~2")  # before AUTH-004: HEAD's history alone says 3/6
        clone = self.tmp / "side"
        self.git(self.tmp, "clone", "-q", "--depth=1", "-b", "side", "--single-branch", f"file://{self.origin}", str(clone))
        self.assertTrue(self.shallow(clone), "fixture")
        r, _ = self.ledger(clone, "history", "--ensure")
        line = self.one_line(r)
        main_count = self.git(self.origin, "rev-list", "--count", "main").strip()
        self.assertIn(f"history completed ({main_count} commits of main)", line)
        self.assertEqual(self.git(clone, "rev-parse", "--verify", "-q", "refs/remotes/origin/main", check=False).strip(),
                         self.git(self.origin, "rev-parse", "main").strip(), "origin/main is where the doctor counts")
        self.assertIn("Context gaps: 0 (0 blocking) · Backlog: 4/6 done", self.doctor_brief(clone).splitlines())

    def test_LEDGER_002_S1_nfr_a_server_asking_for_credentials_never_prompts(self):
        """Breaker: GIT_TERMINAL_PROMPT=0 does not stop GIT_ASKPASS, SSH_ASKPASS or core.askPass; a
        hook that runs a credential helper may block or leak. An http origin answering 401."""
        class Unauthorized(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                self.send_response(401)
                self.send_header("WWW-Authenticate", 'Basic realm="x"')
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Unauthorized)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        clone = self.clone(3)
        self.git(clone, "remote", "set-url", "origin", f"http://127.0.0.1:{server.server_port}/x.git")
        asked = self.tmp / "askpass.log"
        askpass = self.tmp / "askpass.sh"
        askpass.write_text(f'#!/bin/sh\necho "$*" >> "{asked}"\necho secret\n')
        askpass.chmod(0o755)
        self.git(clone, "config", "core.askPass", str(askpass))
        r, elapsed = self.ledger(clone, "history", "--ensure",
                                 extra_env={"GIT_ASKPASS": str(askpass), "SSH_ASKPASS": str(askpass),
                                            "SSH_ASKPASS_REQUIRE": "force", "DISPLAY": ":0"})
        line = self.one_line(r)
        self.assertFalse(asked.exists(), f"a credential prompt ran: {asked.read_text() if asked.exists() else ''}")
        self.assertIn("fetch failed: history incomplete", line, "an auth error is not 'offline'")
        self.assertNotIn("offline", line)
        self.assertLess(elapsed, 15)
        self.assertTrue(self.shallow(clone))

    def test_LEDGER_002_S2_a_failure_that_is_not_the_network_is_not_called_offline(self):
        """Review: every failed fetch said 'offline', a stale .git/shallow.lock too."""
        clone = self.clone(3)
        (clone / ".git/shallow.lock").write_text("")
        r, _ = self.ledger(clone, "history", "--ensure")
        line = self.one_line(r)
        self.assertIn("fetch failed: history incomplete (", line)
        self.assertIn("shallow.lock", line, "git's reason is in the line")
        self.assertNotIn("offline", line)
        self.assertIn("git fetch --unshallow origin main", line)
        self.assertTrue(self.shallow(clone))

    def test_LEDGER_002_S4_dx_an_infinite_or_nan_cap_is_the_default_and_the_trunk_is_named(self):
        """Breaker: TOML accepts inf and nan; int(inf) crashed into the catch-all, whose message
        always said `main` whatever the trunk."""
        self.git(self.origin, "branch", "develop", "main")
        for value in ("inf", "+inf", "nan", "-inf"):
            with self.subTest(value=value):
                clone = self.clone(3, f"clone-{value.replace('+', 'p').replace('-', 'm')}")
                self.state(clone, f'[ledger]\ntrunk = "develop"\nhistory_seconds = {value}\n')
                r, _ = self.ledger(clone, "history", "--ensure")
                line = self.one_line(r)
                self.assertNotIn("origin main", line, "the configured trunk is develop")
                self.assertRegex(line, r"^Keelokit: history completed \(\d+ commits of develop\)")
                self.assertFalse(self.shallow(clone))

    def test_LEDGER_002_S2_a_failed_filtered_fetch_leaves_no_promisor_config(self):
        """Breaker: git writes the promisor config before it contacts the server, so a filtered
        fetch that fails (here: the trunk is not on origin) left it, and the user's later
        `git fetch --unshallow origin` came back blob:none with blobs missing."""
        for allow in ("true", "false"):
            with self.subTest(allowFilter=allow):
                self.git(self.origin, "config", "uploadpack.allowFilter", allow)
                clone = self.clone(3, f"clone-{allow}")
                self.state(clone, '[ledger]\ntrunk = "develop"\n')
                before = self.filter_config(clone)
                r, _ = self.ledger(clone, "history", "--ensure")
                line = self.one_line(r)
                self.assertIn("fetch failed: history incomplete", line)
                self.assertTrue(self.shallow(clone))
                self.assert_filter_config_as_before(clone, before, "after a failed fetch")

    def test_LEDGER_002_S4_a_cut_leaves_no_promisor_config_and_the_rerun_does_not_keep_it(self):
        """Breaker and review: a cut left the config; the next run that completed took it as the
        user's own and kept it, so every later `git fetch origin` warned 'filtering not recognized'."""
        self.git(self.origin, "config", "uploadpack.allowFilter", "false")
        clone = self.clone(3)
        before = self.filter_config(clone)
        self.state(clone, "[ledger]\nhistory_seconds = 2\n")
        self.slow_origin(clone, 30)
        r, _ = self.ledger(clone, "history", "--ensure", timeout=25)
        self.assertIn("cut at 2s", self.one_line(r))
        self.assert_filter_config_as_before(clone, before, "after the cut")
        self.git(clone, "config", "--unset", "remote.origin.uploadpack")
        r, _ = self.ledger(clone, "history", "--ensure")
        self.assertIn("history completed", self.one_line(r))
        self.assertFalse(self.shallow(clone))
        self.assert_filter_config_as_before(clone, before, "after the rerun that completed")
        later = subprocess.run(["git", "fetch", "origin"], cwd=clone, env=self.env, capture_output=True,
                               text=True, timeout=60)
        self.assertEqual(later.returncode, 0, later.stderr)
        self.assertNotIn("filtering not recognized", later.stderr)

    def test_LEDGER_002_nfr_the_two_copies_are_identical(self):
        self.assertTrue(LEDGER.exists(), "template/.keelokit/bin/ledger.py does not exist yet")
        self.assertEqual((REPO / ".keelokit/bin/ledger.py").read_text(), LEDGER.read_text())


# ─────────────────────────────── LEDGER-003: states from git ───────────────────────────────
# Each fixture is a work repo with a bare file:// origin (or a clone of it); ledger.py is copied
# into the repo's .keelokit/bin/ (ROOT comes from the script's path) and kept out of commits.
# Commits get fixed dates (an hour apart from 2026-01-01T00:00:00Z unless a test names one).

EPOCH = 1767225600  # 2026-01-01T00:00:00Z
STORY_KEYS = {"id", "title", "epic", "wave", "state", "since", "since_exact", "commit", "convoy", "version",
              "candidate", "environments", "reconstructed", "reverted", "branches", "attempts", "swarm",
              "signals", "reason", "path"}
TOP_KEYS = {"schema", "trunk", "trunk_sha", "history", "stories", "unattributed", "diffs"}


def story_md(sid: str, depends_on: tuple = (), wave: int = 1, title: str | None = None) -> str:
    deps = ", ".join(f'"{d}"' for d in depends_on)
    title = title or f"Title of {sid}"
    return (f'+++\nid = "{sid}"\nepic = "{sid.split("-")[0]}"\ntitle = "{title}"\nwave = {wave}\n'
            f'depends_on = [{deps}]\n+++\n# {title}\n\n```gherkin\nScenario: [S1] works\n```\n')


class GitRepo:
    """A work repo with a bare origin, built with real git and fixed dates."""

    def __init__(self, tmp: Path, name: str = "work", trunk: str = "main", remote: bool = True,
                 existing: Path | None = None):
        self.tmp = tmp
        self.env = clean_env(tmp)
        self.tick = 0
        self.changes = 0
        self.trunk = trunk
        if existing is not None:
            self.path = existing
        else:
            self.path = tmp / name
            self.path.mkdir(parents=True)
            self.git("init", "-q", "-b", trunk)
            if remote:
                self.bare = tmp / f"{name}-origin.git"
                self.run(["git", "init", "-q", "--bare", "-b", trunk, str(self.bare)], tmp)
                self.git("remote", "add", "origin", f"file://{self.bare}")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "T")
        self.git("config", "commit.gpgsign", "false")
        self.git("config", "tag.gpgsign", "false")
        script = self.path / ".keelokit/bin/ledger.py"
        script.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(LEDGER, script)
        with (self.path / ".git/info/exclude").open("a") as f:
            f.write("/.keelokit/\n")

    def run(self, argv: list[str], cwd: Path, env: dict | None = None, check: bool = True) -> str:
        r = subprocess.run(argv, cwd=cwd, env=env or self.env, capture_output=True, text=True, timeout=180)
        if check and r.returncode:
            raise AssertionError(f"fixture: {' '.join(argv)} failed\n{r.stderr}")
        return r.stdout

    def git(self, *args: str, when: str | None = None, check: bool = True) -> str:
        env = {**self.env, "GIT_COMMITTER_DATE": when, "GIT_AUTHOR_DATE": when} if when else None
        return self.run(["git", *args], self.path, env, check)

    def next_date(self) -> str:
        self.tick += 1
        return f"@{EPOCH + 3600 * self.tick} +0000"

    def write(self, rel: str, text: str) -> None:
        path = self.path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def sha(self, ref: str = "HEAD") -> str:
        return self.git("rev-parse", "--verify", "-q", f"{ref}^{{commit}}").strip()

    def commit(self, message: str, files: dict | None = None, when: str | None = None) -> str:
        # Each commit adds its own file, so any commit can be reverted without a conflict.
        self.changes += 1
        self.write(f"changes/{self.changes}.txt", message + "\n")
        for rel, text in (files or {}).items():
            self.write(rel, text)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message, when=when or self.next_date())
        return self.sha()

    def plan(self, *ids: str, deps: dict | None = None, when: str | None = None) -> str:
        deps = deps or {}
        files = {f"backlog/stories/{sid}-s.md": story_md(sid, tuple(deps.get(sid, ()))) for sid in ids}
        return self.commit("docs: plan\n\nNo-story: docs", files, when)

    def revert(self, sha: str, when: str | None = None) -> str:
        self.git("revert", "--no-edit", sha, when=when or self.next_date())
        return self.sha()

    def on_branch(self, branch: str, *messages: str, when: str | None = None, keep: bool = False,
                  push: bool = True) -> list[str]:
        current = self.git("symbolic-ref", "--short", "HEAD").strip()
        self.git("checkout", "-q", "-b", branch)
        shas = [self.commit(m, when=when) for m in messages]
        if push:
            self.git("push", "-q", "origin", branch)
        self.git("checkout", "-q", current)
        if not keep:
            self.git("branch", "-q", "-D", branch)
        return shas

    def merge(self, branch: str, message: str, when: str | None = None) -> str:
        self.git("merge", "-q", "--no-ff", "-m", message, branch, when=when or self.next_date())
        return self.sha()

    def tag(self, name: str, ref: str = "HEAD", when: str | None = None) -> None:
        self.git("tag", "-a", "-m", name, name, ref, when=when or self.next_date())

    def deploy(self, env_name: str, sha: str) -> None:
        self.git("push", "-q", "-f", "origin", f"{sha}:refs/heads/deploy/{env_name}")
        self.git("fetch", "-q", "--prune", "origin")

    def publish(self, *refs: str) -> None:
        self.git("push", "-q", "origin", *(refs or (self.trunk,)))
        self.git("fetch", "-q", "--prune", "origin")

    def state(self, text: str) -> None:
        self.write(".keelokit/state.toml", textwrap.dedent(text))

    def clone(self, name: str, depth: int | None = None) -> "GitRepo":
        dest = self.tmp / name
        self.run(["git", "clone", "-q", *([f"--depth={depth}"] if depth else []), f"file://{self.bare}",
                  str(dest)], self.tmp)
        return GitRepo(self.tmp, existing=dest)

    def ledger(self, *args: str, extra_env: dict | None = None, path: str | None = None,
               timeout: float = 60) -> subprocess.CompletedProcess:
        env = clean_env(self.tmp, path)
        env.update(extra_env or {})
        return subprocess.run(["python3", ".keelokit/bin/ledger.py", *args], cwd=self.path, env=env,
                              stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout)


def read_json(test: unittest.TestCase, repo: GitRepo, extra_env: dict | None = None) -> dict:
    """`ledger.py --json`: schema 1 on stdout, exit 1 iff diffs is not empty, else 0."""
    r = repo.ledger("--json", extra_env=extra_env)
    test.assertNotIn("Traceback", r.stderr)
    test.assertIn(r.returncode, (0, 1), f"ledger.py --json exited {r.returncode}\nstderr: {r.stderr}")
    try:
        data = json.loads(r.stdout)
    except ValueError:
        test.fail(f"ledger.py --json did not print JSON:\n{r.stdout[:2000]}")
    test.assertEqual(r.returncode, 1 if data.get("diffs") else 0, f"exit vs diffs: {data.get('diffs')}")
    return data


def by_id(data: dict) -> dict:
    return {s["id"]: s for s in data["stories"]}


class LedgerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    @classmethod
    def class_tmp(cls) -> Path:
        tmp = Path(tempfile.mkdtemp())
        cls.addClassCleanup(shutil.rmtree, tmp, True)
        return tmp

    def stories(self, repo: GitRepo, extra_env: dict | None = None) -> dict:
        return by_id(read_json(self, repo, extra_env))

    def shared(self) -> dict:
        """One `--json` read of the class's fixture (cls.repo), shared by its tests."""
        cls = type(self)
        if "_shared" not in cls.__dict__:
            cls._shared = read_json(self, cls.repo)
        return cls._shared


class LedgerOnTrunkTest(LedgerCase):
    """S1: a Story: commit on the trunk, straight or through a merge; the JSON schema 1."""

    @classmethod
    def setUpClass(cls):
        repo = cls.repo = GitRepo(cls.class_tmp())
        repo.plan("AUTH-001", "AUTH-002", "AUTH-003", when="2026-03-01T00:00:00+00:00")
        cls.s1 = repo.commit("feat: AUTH-001\n\nWhat was decided.\n\nStory: AUTH-001",
                             when="2026-03-04T05:06:07+00:00")
        repo.commit("chore: between\n\nNo-story: docs", when="2026-03-05T00:00:00+00:00")
        cls.s2 = repo.on_branch("feat/two", "feat: AUTH-002\n\nWhy.\n\nStory: AUTH-002",
                                when="2026-03-02T00:00:00+00:00", keep=True)[0]
        repo.commit("chore: the trunk moves\n\nNo-story: docs", when="2026-03-06T00:00:00+00:00")
        cls.merge = repo.merge("feat/two", "Merge feat/two\n\nNo-story: release", when="2026-03-10T12:00:00+03:00")
        repo.publish()
        assert repo.git("log", "-1", "--format=%cI", cls.merge).strip() == "2026-03-10T12:00:00+03:00"

    def test_LEDGER_003_S1_a_story_commit_on_the_trunk_is_on_trunk_with_its_hash_and_an_approximate_date(self):
        s = by_id(self.shared())["AUTH-001"]
        self.assertEqual(s["state"], "on-trunk")
        self.assertEqual(s["commit"], self.s1)
        self.assertEqual(s["since"], "2026-03-04T05:06:07Z")
        self.assertIs(s["since_exact"], False)
        self.assertIs(s["reverted"], False)
        self.assertIsNone(s["version"])

    def test_LEDGER_003_S1_logic_a_merged_story_arrives_at_the_merges_committer_date_in_utc(self):
        s = by_id(self.shared())["AUTH-002"]
        self.assertEqual(s["state"], "on-trunk")
        self.assertEqual(s["commit"], self.s2, "commit is the Story: commit, not the merge")
        self.assertEqual(s["since"], "2026-03-10T09:00:00Z", "since = the merge's committer date, in UTC")
        self.assertIs(s["since_exact"], False)

    def test_LEDGER_003_S1_logic_a_story_with_no_commit_is_ready_with_no_date(self):
        s = by_id(self.shared())["AUTH-003"]
        self.assertEqual(s["state"], "ready")
        self.assertIsNone(s["since"])

    def test_LEDGER_003_data_json_schema_1_keys(self):
        d = self.shared()
        self.assertLessEqual(TOP_KEYS, set(d), f"missing top-level keys: {TOP_KEYS - set(d)}")
        self.assertEqual(d["schema"], 1)
        self.assertEqual(d["trunk"], "main")
        self.assertEqual(d["trunk_sha"], self.repo.sha("refs/remotes/origin/main"))
        self.assertEqual(d["history"], "complete")
        self.assertEqual(d["diffs"], [])
        self.assertLessEqual({"since", "commits", "ratio"}, set(d["unattributed"]))
        self.assertEqual([s["id"] for s in d["stories"]], ["AUTH-001", "AUTH-002", "AUTH-003"], "sorted by id")
        for s in d["stories"]:
            self.assertLessEqual(STORY_KEYS, set(s), f"{s['id']} misses {STORY_KEYS - set(s)}")
            self.assertEqual(s["title"], f"Title of {s['id']}")
            self.assertEqual(s["epic"], "AUTH")
            self.assertEqual(s["wave"], 1)
            self.assertIsNone(s["convoy"])
            self.assertIs(s["reconstructed"], False)
            self.assertEqual(s["attempts"], [])
            self.assertEqual(s["swarm"], [])
            self.assertEqual(s["signals"], [])
            self.assertIsNone(s["reason"], "reason is null unless the state is unknown")
            self.assertIsNone(s["candidate"])
            self.assertEqual(s["environments"], {"staging": None, "production": None})
            self.assertEqual(s["path"], f"backlog/stories/{s['id']}-s.md")
        self.assertEqual(by_id(d)["AUTH-002"]["branches"], [], "a branch with only a Story: commit is no Part-of")


class LedgerVersionTest(LedgerCase):
    """S2: v* tags in version order; -rc.N is a candidate; other tags are ignored."""

    @property
    def s(self) -> dict:
        return by_id(self.shared())

    @classmethod
    def setUpClass(cls):
        repo = cls.repo = GitRepo(cls.class_tmp())
        repo.plan("AUTH-001", "AUTH-002", "AUTH-003")
        s1 = repo.commit("feat: AUTH-001\n\nWhy.\n\nStory: AUTH-001")
        repo.tag("v0.9.0-beta")  # not v<N>(.<N>)*[-rc.<N>]: ignored
        repo.git("tag", "release-1")  # not v*: ignored
        repo.git("tag", "v1.1.0", f"{s1}~1")  # before the commit: does not contain it
        repo.commit("chore: a\n\nNo-story: docs")
        repo.tag("v1.2.0")
        repo.commit("chore: b\n\nNo-story: docs")
        repo.git("tag", "v1.10.0")  # lightweight; after v1.2.0 in version order (not in string order)
        repo.commit("feat: AUTH-003\n\nWhy.\n\nStory: AUTH-003")
        repo.tag("v2.0.0-rc.1")
        repo.commit("chore: c\n\nNo-story: docs")
        repo.tag("v2.0.0")
        repo.commit("feat: AUTH-002\n\nWhy.\n\nStory: AUTH-002")
        repo.tag("v2.1.0-rc.1")
        repo.commit("chore: d\n\nNo-story: docs")
        repo.tag("v2.1.0-rc.2")
        repo.publish()

    def test_LEDGER_003_S2_a_tag_that_contains_the_commit_makes_it_in_version(self):
        self.assertEqual(self.s["AUTH-001"]["state"], "in-version")
        self.assertEqual(self.s["AUTH-001"]["version"], "v1.2.0", "the first v* tag in version order containing it")

    def test_LEDGER_003_S2_logic_the_first_final_tag_wins_over_its_release_candidate(self):
        self.assertEqual(self.s["AUTH-003"]["state"], "in-version")
        self.assertEqual(self.s["AUTH-003"]["version"], "v2.0.0")

    def test_LEDGER_003_S2_logic_an_rc_tag_is_a_candidate_not_a_version(self):
        s = self.s["AUTH-002"]
        self.assertEqual(s["state"], "on-trunk")
        self.assertIsNone(s["version"])
        self.assertEqual(s["candidate"], "v2.1.0-rc.1")


class LedgerProgressTest(LedgerCase):
    """S3: Part-of: on any origin branch not on the trunk; stale after stale_days."""

    @classmethod
    def setUpClass(cls):
        repo = cls.repo = GitRepo(cls.class_tmp())
        repo.plan(*(f"AUTH-00{n}" for n in range(1, 8)))
        repo.commit("feat: AUTH-001\n\nWhy.\n\nStory: AUTH-001")
        repo.publish()
        recent = f"@{int(time.time()) - 86400} +0000"
        repo.on_branch("claude/xyz", "wip: AUTH-002\n\nPart-of: AUTH-002", when=recent)
        repo.on_branch("feature/multi", "wip: two stories\n\nPart-of: AUTH-003, AUTH-004", when=recent)
        repo.on_branch("agent/two", "wip: AUTH-003 again\n\nPart-of: AUTH-003", when=recent)
        repo.on_branch("old/thing", "wip: AUTH-005\n\nPart-of: AUTH-005", when="2020-01-01T00:00:00+00:00")
        repo.on_branch("fix/a", "fix: AUTH-001 follow-up\n\nPart-of: AUTH-001", when=recent)
        repo.on_branch("done/b", "feat: AUTH-006 part\n\nPart-of: AUTH-006", keep=True)
        repo.merge("done/b", "Merge done/b\n\nNo-story: release")
        repo.on_branch("local/only", "wip: AUTH-007\n\nPart-of: AUTH-007", push=False)
        repo.publish()

    def test_LEDGER_003_S3_a_part_of_commit_on_an_origin_branch_is_in_progress_with_that_branch(self):
        s = self.stories(self.repo)
        self.assertEqual(s["AUTH-002"]["state"], "in-progress")
        self.assertEqual(s["AUTH-002"]["branches"], ["claude/xyz"])
        self.assertEqual(s["AUTH-002"]["signals"], [])

    def test_LEDGER_003_S3_logic_part_of_with_two_ids_and_two_branches(self):
        s = self.stories(self.repo)
        self.assertEqual(s["AUTH-003"]["state"], "in-progress")
        self.assertEqual(s["AUTH-003"]["branches"], ["agent/two", "feature/multi"], "sorted, without refs/remotes/origin/")
        self.assertEqual(s["AUTH-004"]["state"], "in-progress")
        self.assertEqual(s["AUTH-004"]["branches"], ["feature/multi"])

    def test_LEDGER_003_S3_logic_precedence_on_trunk_beats_in_progress_but_branches_are_listed(self):
        s = self.stories(self.repo)["AUTH-001"]
        self.assertEqual(s["state"], "on-trunk")
        self.assertEqual(s["branches"], ["fix/a"])
        self.assertNotIn("stale", s["signals"])

    def test_LEDGER_003_S3_logic_part_of_already_on_the_trunk_or_only_local_is_not_in_progress(self):
        s = self.stories(self.repo)
        self.assertEqual(s["AUTH-006"]["state"], "ready", "its Part-of commit is on the trunk")
        self.assertEqual(s["AUTH-006"]["branches"], [])
        self.assertEqual(s["AUTH-007"]["state"], "ready", "a local branch is not on origin")
        self.assertEqual(s["AUTH-007"]["branches"], [])

    def test_LEDGER_003_S3_logic_stale_after_stale_days_and_the_config_moves_it(self):
        self.repo.state("")
        self.assertEqual(self.stories(self.repo)["AUTH-005"]["signals"], ["stale"])
        self.assertEqual(self.stories(self.repo)["AUTH-005"]["state"], "in-progress", "stale is a signal, not a state")
        self.repo.state('[ledger]\nstale_days = "seven"\n')  # a wrong type falls back to 7
        self.assertEqual(self.stories(self.repo)["AUTH-005"]["signals"], ["stale"])
        self.repo.state("[ledger]\nstale_days = 100000\n")
        try:
            self.assertEqual(self.stories(self.repo)["AUTH-005"]["signals"], [])
        finally:
            self.repo.state("")


class LedgerRevertTest(LedgerCase):
    """S4 and INV-005: on the trunk iff a Story: commit is reachable from it and no revert of it is."""

    @property
    def s(self) -> dict:
        return by_id(self.shared())

    @classmethod
    def setUpClass(cls):
        repo = cls.repo = GitRepo(cls.class_tmp())
        repo.plan("AUTH-001", "AUTH-002", "AUTH-003", "AUTH-004", "AUTH-005", "AUTH-006", "AUTH-007", "AUTH-008",
                  deps={"AUTH-006": ["AUTH-007"]})
        c = cls.c = {}
        c["s1"] = repo.commit("feat: AUTH-001\n\nWhy.\n\nStory: AUTH-001")
        c["r1"] = repo.revert(c["s1"])
        c["s2"] = repo.commit("feat: AUTH-002\n\nWhy.\n\nStory: AUTH-002")
        c["r2"] = repo.revert(c["s2"])
        repo.revert(c["r2"])  # the revert of the revert: AUTH-002 is back
        c["s3a"] = repo.commit("feat: AUTH-003\n\nWhy.\n\nStory: AUTH-003")
        repo.revert(c["s3a"])
        c["s3b"] = repo.commit("feat: AUTH-003 again\n\nWhy.\n\nStory: AUTH-003")
        c["s4a"] = repo.commit("feat: AUTH-004\n\nWhy.\n\nStory: AUTH-004")
        c["s4b"] = repo.commit("feat: AUTH-004 more\n\nWhy.\n\nStory: AUTH-004")
        repo.revert(c["s4a"])
        c["s5"] = repo.commit("feat: AUTH-005\n\nWhy.\n\nStory: AUTH-005")
        c["s6"] = repo.commit("feat: AUTH-006\n\nWhy.\n\nStory: AUTH-006")
        repo.revert(c["s6"])
        c["s8"] = repo.commit("feat: AUTH-008\n\nWhy.\n\nStory: AUTH-008")
        repo.revert(c["s8"])
        repo.publish()
        repo.git("checkout", "-q", "-b", "claude/r")
        repo.revert(c["s5"])  # a revert that is not on the trunk does not count
        repo.git("push", "-q", "origin", "claude/r")
        repo.git("checkout", "-q", "main")
        repo.on_branch("claude/again", "wip: AUTH-008 redo\n\nPart-of: AUTH-008")
        repo.publish()

    def test_LEDGER_003_S4_INV_005_a_reverted_story_commit_is_ready_marked_reverted(self):
        s = self.s["AUTH-001"]
        self.assertEqual(s["state"], "ready")
        self.assertIs(s["reverted"], True)
        self.assertIsNone(s["since"])

    def test_LEDGER_003_S4_INV_005_the_revert_of_a_revert_puts_it_back_on_the_trunk(self):
        s = self.s["AUTH-002"]
        self.assertEqual(s["state"], "on-trunk")
        self.assertEqual(s["commit"], self.c["s2"])
        self.assertIs(s["reverted"], False)

    def test_LEDGER_003_S4_INV_005_the_oldest_story_commit_not_reverted_is_the_commit(self):
        self.assertEqual(self.s["AUTH-003"]["state"], "on-trunk")
        self.assertEqual(self.s["AUTH-003"]["commit"], self.c["s3b"])
        self.assertEqual(self.s["AUTH-004"]["state"], "on-trunk")
        self.assertEqual(self.s["AUTH-004"]["commit"], self.c["s4b"])
        self.assertIs(self.s["AUTH-004"]["reverted"], False)

    def test_LEDGER_003_S4_INV_005_a_revert_off_the_trunk_does_not_count(self):
        self.assertEqual(self.s["AUTH-005"]["state"], "on-trunk")
        self.assertEqual(self.s["AUTH-005"]["commit"], self.c["s5"])
        self.assertIs(self.s["AUTH-005"]["reverted"], False)

    def test_LEDGER_003_S4_INV_005_reverted_falls_to_its_base_state(self):
        self.assertEqual(self.s["AUTH-006"]["state"], "defined", "its dependency AUTH-007 is not on the trunk")
        self.assertIs(self.s["AUTH-006"]["reverted"], True)
        self.assertEqual(self.s["AUTH-008"]["state"], "in-progress")
        self.assertEqual(self.s["AUTH-008"]["branches"], ["claude/again"])
        self.assertIs(self.s["AUTH-008"]["reverted"], True)


class LedgerDependencyTest(LedgerCase):
    """S5: ready iff every depends_on is on-trunk or later; an id that is no story is not ready."""

    def test_LEDGER_003_S5_defined_while_the_dependency_is_not_on_trunk_and_ready_once_it_is(self):
        repo = GitRepo(self.tmp)
        repo.plan("AUTH-003", "AUTH-004", "AUTH-005", "AUTH-006",
                  deps={"AUTH-003": ["AUTH-004"], "AUTH-005": ["AUTH-004", "AUTH-006"]})
        repo.publish()
        s = self.stories(repo)
        self.assertEqual(s["AUTH-003"]["state"], "defined")
        self.assertEqual(s["AUTH-004"]["state"], "ready")
        repo.commit("feat: AUTH-004\n\nWhy.\n\nStory: AUTH-004")
        repo.tag("v1.0.0")  # in-version is "on-trunk or later"
        repo.publish()
        s = self.stories(repo)
        self.assertEqual(s["AUTH-004"]["state"], "in-version")
        self.assertEqual(s["AUTH-003"]["state"], "ready")
        self.assertEqual(s["AUTH-005"]["state"], "defined", "AUTH-006 is still not on the trunk")

    def test_LEDGER_003_S5_logic_an_unknown_dependency_id_is_not_ready(self):
        repo = GitRepo(self.tmp)
        repo.plan("AUTH-001", deps={"AUTH-001": ["NOPE-1"]})
        repo.publish()
        self.assertEqual(self.stories(repo)["AUTH-001"]["state"], "defined")


class LedgerIncompleteHistoryTest(LedgerCase):
    """S6: a shallow clone fails closed: unknown with the reason, never a lower state."""

    @classmethod
    def setUpClass(cls):
        repo = GitRepo(cls.class_tmp())
        repo.plan("AUTH-001", "AUTH-002", "AUTH-003")
        repo.commit("feat: AUTH-001\n\nWhy.\n\nStory: AUTH-001")
        for n in range(4):
            repo.commit(f"chore: {n}\n\nNo-story: docs")
        repo.publish()
        cls.shallow = repo.clone("shallow", depth=2)
        assert cls.shallow.git("rev-parse", "--is-shallow-repository").strip() == "true"
        cls.full = repo.clone("full")

    def test_LEDGER_003_S6_a_shallow_clone_makes_every_state_unknown_with_the_reason(self):
        d = read_json(self, self.shallow)
        self.assertEqual(d["history"], "incomplete")
        self.assertEqual(len(d["stories"]), 3, "the stories are still listed")
        for s in d["stories"]:
            self.assertEqual(s["state"], "unknown", s["id"])
            self.assertIsInstance(s["reason"], str)
            self.assertIn("history --ensure", s["reason"], "the reason names the fix")
        codes = [x for x in d["diffs"] if x.get("code") == "HISTORY_INCOMPLETE"]
        self.assertEqual(len(codes), 1, d["diffs"])
        self.assertEqual(codes[0]["level"], "warning", "a warning in a session")

    def test_LEDGER_003_S6_logic_history_incomplete_is_an_error_under_ci(self):
        d = read_json(self, self.shallow, extra_env={"CI": "true"})
        codes = [x for x in d["diffs"] if x.get("code") == "HISTORY_INCOMPLETE"]
        self.assertEqual([x["level"] for x in codes], ["error"])

    def test_LEDGER_003_S6_dx_the_summary_says_the_history_is_incomplete(self):
        r = self.shallow.ledger()
        self.assertNotIn("Traceback", r.stderr)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        lines = r.stdout.splitlines()
        self.assertLessEqual(len(lines), 10, r.stdout)
        self.assertIn("incomplete", "\n".join(lines[:2]).lower(), "the first lines say so")

    def test_LEDGER_003_S6_logic_the_same_origin_cloned_whole_is_complete(self):
        d = read_json(self, self.full)
        self.assertEqual(d["history"], "complete")
        self.assertEqual(by_id(d)["AUTH-001"]["state"], "on-trunk")
        self.assertEqual(by_id(d)["AUTH-002"]["state"], "ready")


class LedgerStoryFilesTest(LedgerCase):
    """S7 and the stories config: id from the file name or the front matter, read from the trunk's tree."""

    def test_LEDGER_003_S7_ids_from_file_names_with_the_title_from_the_first_heading(self):
        repo = GitRepo(self.tmp)
        repo.state('[ledger]\nid_from = "filename"\nstories = "roadmap/stories/*.md"\n')
        repo.commit("docs: roadmap\n\nNo-story: docs", {
            "roadmap/stories/UXC-113-something.md": "Some intro.\n\n# Make the thing\n\nText.\n\n# Second heading\n",
            "roadmap/stories/UXC-114-bare.md": "No heading at all.\n",
            "roadmap/stories/UXC-115-deps.md": '+++\nwave = 2\ndepends_on = ["UXC-113"]\n+++\n# Uses the thing\n',
            "roadmap/stories/notes.md": "# Notes\n",
            "roadmap/stories/old/UXC-200-nested.md": "# Nested: `*` does not cross /\n",
        })
        repo.commit("feat: UXC-113\n\nWhy.\n\nStory: UXC-113")
        repo.publish()
        s = self.stories(repo)
        self.assertEqual(set(s), {"UXC-113", "UXC-114", "UXC-115"})
        u = s["UXC-113"]
        self.assertEqual((u["title"], u["epic"], u["wave"]), ("Make the thing", "UXC", None))
        self.assertEqual(u["path"], "roadmap/stories/UXC-113-something.md")
        self.assertEqual(u["state"], "on-trunk")
        self.assertEqual(s["UXC-114"]["title"], "UXC-114", "no heading: the id")
        self.assertEqual(s["UXC-114"]["state"], "ready")
        self.assertEqual((s["UXC-115"]["title"], s["UXC-115"]["wave"]), ("Uses the thing", 2))
        self.assertEqual(s["UXC-115"]["state"], "ready", "depends_on from front matter; UXC-113 is on the trunk")

    def test_LEDGER_003_S7_logic_front_matter_ids_and_files_without_it_are_not_stories(self):
        repo = GitRepo(self.tmp)
        repo.commit("docs: stories\n\nNo-story: docs", {
            "backlog/stories/README.md": "# Stories\n",
            "backlog/stories/whatever.md": '+++\nid = "AUTH-009"\ntitle = "Named in front matter"\n+++\n',
            "backlog/stories/AUTH-001-a.md": story_md("AUTH-001", title="First of two"),
            "backlog/stories/AUTH-001-b.md": story_md("AUTH-001", title="Second of two"),
        })
        repo.publish()
        repo.commit("docs: local only\n\nNo-story: docs", {"backlog/stories/AUTH-011-l.md": story_md("AUTH-011")})
        repo.write("backlog/stories/AUTH-012-wt.md", story_md("AUTH-012"))  # only in the working tree
        s = self.stories(repo)
        self.assertEqual(set(s), {"AUTH-001", "AUTH-009"}, "only files on origin/main with front matter")
        self.assertEqual(s["AUTH-009"]["epic"], "AUTH", "epic defaults to the id's prefix")
        self.assertIsNone(s["AUTH-009"]["wave"])
        self.assertEqual(s["AUTH-009"]["path"], "backlog/stories/whatever.md")
        self.assertEqual(s["AUTH-001"]["path"], "backlog/stories/AUTH-001-a.md", "a duplicate id: the first path wins")
        self.assertEqual(s["AUTH-001"]["title"], "First of two")

    def test_LEDGER_003_S7_logic_a_double_star_glob_crosses_directories_and_a_wrong_type_is_the_default(self):
        repo = GitRepo(self.tmp)
        repo.commit("docs: plan\n\nNo-story: docs", {
            "plan/a/X-1-one.md": "# One\n", "plan/b/c/X-2-two.md": "# Two\n",
            "backlog/stories/AUTH-001-s.md": story_md("AUTH-001"),
        })
        repo.publish()
        repo.state('[ledger]\nid_from = "filename"\nstories = "plan/**/*.md"\n')
        self.assertEqual(set(self.stories(repo)), {"X-1", "X-2"})
        repo.state("[ledger]\nid_from = 5\nstories = 3\n")
        self.assertEqual(set(self.stories(repo)), {"AUTH-001"})


class LedgerTrunkTest(LedgerCase):
    """S8: the states are measured against the configured trunk: origin/<trunk>, else the local branch."""

    def develop_repo(self) -> GitRepo:
        repo = GitRepo(self.tmp)
        repo.plan("AUTH-001", "AUTH-002")
        repo.publish()
        repo.git("checkout", "-q", "-b", "develop")
        repo.commit("feat: AUTH-001\n\nWhy.\n\nStory: AUTH-001")
        repo.publish("develop")
        return repo  # HEAD is develop

    def test_LEDGER_003_S8_harbor_trunk_develop_measures_against_develop(self):
        repo = self.develop_repo()
        repo.state('[harbor]\ntrunk = "develop"\n')
        d = read_json(self, repo)
        self.assertEqual(d["trunk"], "develop")
        self.assertEqual(d["trunk_sha"], repo.sha("refs/remotes/origin/develop"))
        self.assertEqual(by_id(d)["AUTH-001"]["state"], "on-trunk")

    def test_LEDGER_003_S8_logic_ledger_trunk_wins_over_harbor_trunk_and_head_is_never_the_trunk(self):
        repo = self.develop_repo()
        repo.state('[ledger]\ntrunk = "main"\n\n[harbor]\ntrunk = "develop"\n')
        d = read_json(self, repo)
        self.assertEqual(d["trunk"], "main")
        self.assertEqual(by_id(d)["AUTH-001"]["state"], "ready", "the Story: commit is on HEAD (develop), not main")

    def test_LEDGER_003_S8_logic_origin_trunk_first_then_the_local_branch(self):
        repo = GitRepo(self.tmp)
        repo.plan("AUTH-001")
        repo.publish()
        repo.commit("feat: AUTH-001\n\nWhy.\n\nStory: AUTH-001")  # not pushed: origin/main does not have it
        self.assertEqual(self.stories(repo)["AUTH-001"]["state"], "ready")
        local = GitRepo(self.tmp, name="local", remote=False)
        local.plan("AUTH-001")
        local.commit("feat: AUTH-001\n\nWhy.\n\nStory: AUTH-001")
        d = read_json(self, local)
        self.assertEqual(d["trunk_sha"], local.sha("refs/heads/main"))
        self.assertEqual(by_id(d)["AUTH-001"]["state"], "on-trunk")


class LedgerDeployTest(LedgerCase):
    """S9: origin/deploy/staging and origin/deploy/production."""

    def test_LEDGER_003_S9_a_deploy_branch_that_contains_the_commit(self):
        repo = GitRepo(self.tmp)
        repo.plan("AUTH-001", "AUTH-002", "AUTH-003")
        s1 = repo.commit("feat: AUTH-001\n\nWhy.\n\nStory: AUTH-001")
        s2 = repo.commit("feat: AUTH-002\n\nWhy.\n\nStory: AUTH-002")
        repo.commit("feat: AUTH-003\n\nWhy.\n\nStory: AUTH-003")
        repo.tag("v1.0.0")
        repo.publish()
        repo.deploy("production", s1)
        repo.deploy("staging", s2)
        s = self.stories(repo)
        self.assertEqual(s["AUTH-001"]["state"], "in-production")
        self.assertEqual(s["AUTH-001"]["version"], "v1.0.0")
        self.assertEqual(s["AUTH-001"]["environments"], {"staging": s2, "production": s1})
        self.assertEqual(s["AUTH-002"]["state"], "in-staging")
        self.assertEqual(s["AUTH-002"]["environments"], {"staging": s2, "production": None})
        self.assertEqual(s["AUTH-003"]["state"], "in-version")
        self.assertEqual(s["AUTH-003"]["environments"], {"staging": None, "production": None})


class LedgerUnattributedTest(LedgerCase):
    """unattributed: trunk commits after [ledger] since with no Story:/Part-of:/No-story:, nor a merge carrying one."""

    @classmethod
    def setUpClass(cls):
        repo = cls.repo = GitRepo(cls.class_tmp())
        repo.plan("AUTH-001", "AUTH-002")
        repo.commit("chore: before since, not counted")
        cls.since = repo.commit("chore: adopt\n\nNo-story: harness")
        repo.commit("feat: AUTH-001\n\nWhy.\n\nStory: AUTH-001")
        repo.commit("docs: x\n\nNo-story: docs")
        repo.commit("chore: oops")  # 1: unattributed
        repo.commit("wip: AUTH-002\n\nPart-of: AUTH-002")
        repo.on_branch("feat/f", "chore: inside an attributed merge", keep=True)
        repo.commit("ci: y\n\nNo-story: ci")
        repo.merge("feat/f", "Merge feat/f\n\nWhy.\n\nStory: AUTH-002")
        repo.on_branch("feat/g", "chore: inside a plain merge", keep=True)  # 2
        repo.commit("docs: z\n\nNo-story: docs")
        repo.merge("feat/g", "Merge branch feat/g")  # 3
        repo.publish()

    def test_LEDGER_003_data_unattributed_counts_since_the_since_commit(self):
        self.repo.state(f'[ledger]\nsince = "{self.since}"\n')
        u = read_json(self, self.repo)["unattributed"]
        self.assertEqual(u["since"], self.since)
        self.assertEqual(u["commits"], 3)
        self.assertAlmostEqual(u["ratio"], 3 / 10, places=3)  # 10 commits after since

    def test_LEDGER_003_data_unattributed_without_since_or_with_an_unknown_since_is_zero(self):
        self.repo.state("")
        self.assertEqual(read_json(self, self.repo)["unattributed"], {"since": None, "commits": 0, "ratio": 0.0})
        ghost = "0123456789abcdef0123456789abcdef01234567"
        self.repo.state(f'[ledger]\nsince = "{ghost}"\n')
        self.assertEqual(read_json(self, self.repo)["unattributed"], {"since": ghost, "commits": 0, "ratio": 0.0})


class LedgerCliTest(LedgerCase):
    """The summary, the exit codes and the history subcommand."""

    def test_LEDGER_003_dx_the_summary_is_at_most_10_lines_and_names_what_matters(self):
        repo = GitRepo(self.tmp)
        ids = [f"AUTH-{n:03}" for n in range(1, 31)]
        repo.plan(*ids)
        repo.commit("feat: AUTH-001\n\nWhy.\n\nStory: AUTH-001")
        r1 = repo.commit("feat: AUTH-030\n\nWhy.\n\nStory: AUTH-030")
        repo.revert(r1)
        repo.publish()
        repo.on_branch("claude/xyz", "wip: AUTH-002\n\nPart-of: AUTH-002")
        repo.publish()
        for lang in ("", '[dashboard]\nlang = "es"\n'):
            repo.state(lang)
            r = repo.ledger()
            self.assertNotIn("Traceback", r.stderr)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertLessEqual(len(r.stdout.splitlines()), 10, r.stdout)
            self.assertIn("main", r.stdout)
            self.assertIn(repo.sha("refs/remotes/origin/main")[:7], r.stdout)
            self.assertIn("AUTH-002", r.stdout, "in progress, with its branch")
            self.assertIn("claude/xyz", r.stdout)
            self.assertIn("AUTH-030", r.stdout, "reverted")

    def test_LEDGER_003_dx_exit_2_outside_git_for_a_trunk_that_does_not_resolve_and_for_bad_arguments(self):
        plain = self.tmp / "plain/.keelokit/bin"
        plain.mkdir(parents=True)
        shutil.copyfile(LEDGER, plain / "ledger.py")
        r = subprocess.run(["python3", ".keelokit/bin/ledger.py", "--json"], cwd=self.tmp / "plain",
                           env=clean_env(self.tmp), capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        repo = GitRepo(self.tmp)
        repo.plan("AUTH-001")
        repo.publish()
        repo.state('[ledger]\ntrunk = "nope"\n')
        r = repo.ledger("--json")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertEqual(len(r.stderr.strip().splitlines()), 1, r.stderr)
        self.assertIn("nope", r.stderr, "the line says which trunk")
        repo.state("")
        for bad in (["--bogus"], ["--json", "extra"], ["show"]):
            r = repo.ledger(*bad)
            self.assertEqual(r.returncode, 2, f"{bad}: {r.stdout}{r.stderr}")
            self.assertTrue(r.stderr.strip(), f"{bad}: the usage goes to stderr")

    def test_LEDGER_003_dx_history_still_works(self):
        repo = GitRepo(self.tmp)
        repo.plan("AUTH-001")
        repo.publish()
        r = repo.ledger("history")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = repo.ledger("history", "--ensure")
        self.assertEqual((r.returncode, r.stdout.strip()), (0, ""), r.stderr)
        self.assertEqual(read_json(self, repo)["history"], "complete")


class LedgerBudgetTest(LedgerCase):
    """S10: 10 000 commits and 700 stories (built with git fast-import): under 2 s, git calls fixed."""

    N_COMMITS = 10_000
    N_STORIES = 700

    @classmethod
    def setUpClass(cls):
        tmp = cls.tmp_class = cls.class_tmp()
        repo = cls.repo = GitRepo(tmp)
        out = []

        def data(text: str) -> None:
            out.append(f"data {len(text.encode())}\n{text}\n")

        def committer(k: int) -> str:
            return f"committer T <t@example.com> {EPOCH + 60 * k} +0000\n"

        out.append(f"commit refs/heads/main\nmark :1\n{committer(1)}")
        data("docs: plan\n\nNo-story: docs\n")
        for i in range(cls.N_STORIES):
            out.append(f"M 100644 inline backlog/stories/PERF-{1000 + i}-s.md\n")
            data(story_md(f"PERF-{1000 + i}", depends_on=(f"PERF-{999 + i}",) if i else ()))
        for i in range(1, 8):
            out.append(f"M 100644 inline few/FEW-{i}-s.md\n")
            data(story_md(f"FEW-{i}"))
        story = 0
        for k in range(2, cls.N_COMMITS + 1):
            if k % 14 == 0 and story < cls.N_STORIES:
                sid = f"PERF-{1000 + story}"
                msg = f"feat: {sid}\n\nWhy.\n\nStory: {sid}\n"
                story += 1
            elif k % 5 == 0:
                msg = f"docs: {k}\n\nNo-story: docs\n"
            else:
                msg = f"chore: {k}\n"
            out.append(f"commit refs/heads/main\nmark :{k}\n{committer(k)}")
            data(msg)
            out.append(f"from :{k - 1}\nM 100644 inline churn.txt\n")
            data(f"{k}\n")
        for k, tag in ((5000, "v1.0.0"), (9000, "v2.0.0"), (9500, "v2.1.0-rc.1")):
            out.append(f"reset refs/tags/{tag}\nfrom :{k}\n\n")
        for n in range(5):  # work in progress on origin
            out.append(f"commit refs/heads/wip/{n}\nmark :{cls.N_COMMITS + 1 + n}\n{committer(cls.N_COMMITS + 1 + n)}")
            data(f"wip\n\nPart-of: PERF-{1695 + n}\n")
            out.append(f"from :{cls.N_COMMITS}\nM 100644 inline wip{n}.txt\n")
            data("x\n")
        out.append(f"reset refs/heads/deploy/production\nfrom :3000\n\n")
        r = subprocess.run(["git", "fast-import", "--quiet"], cwd=repo.path, env=repo.env, input="".join(out),
                           capture_output=True, text=True, timeout=300)
        assert r.returncode == 0, r.stderr
        repo.git("push", "-q", "origin", "main", "deploy/production", *(f"wip/{n}" for n in range(5)))
        repo.git("fetch", "-q", "--prune", "origin")
        assert int(repo.git("rev-list", "--count", "refs/remotes/origin/main").strip()) == cls.N_COMMITS

    def counted_run(self, state: str) -> tuple[int, dict]:
        """The number of git invocations of one `--json` run, from a `git` first on PATH that logs argv."""
        bindir = self.tmp / "shim"
        bindir.mkdir(exist_ok=True)
        log = self.tmp / f"argv-{uuid.uuid4().hex}.log"
        log.touch()
        real = shutil.which("git", path=clean_env(self.tmp)["PATH"])
        shim = bindir / "git"
        shim.write_text(f'#!/bin/sh\nprintf \'%s\\n\' "$*" >> "{log}"\nexec "{real}" "$@"\n')
        shim.chmod(0o755)
        self.repo.state(state)
        try:
            r = self.repo.ledger("--json", path=f"{bindir}{os.pathsep}{clean_env(self.tmp)['PATH']}")
        finally:
            self.repo.state("")
        self.assertIn(r.returncode, (0, 1), r.stderr)
        return len(log.read_text().splitlines()), json.loads(r.stdout)

    def test_LEDGER_003_S10_the_number_of_git_calls_does_not_grow_with_the_stories(self):
        few_calls, few = self.counted_run('[ledger]\nstories = "few/*.md"\n')
        many_calls, many = self.counted_run("")
        self.assertEqual(len(few["stories"]), 7)
        self.assertEqual(len(many["stories"]), self.N_STORIES)
        self.assertGreater(few_calls, 0, "the shim logged no git call: ledger.py must run `git` from PATH")
        self.assertEqual(many_calls, few_calls, "7 and 700 stories make the same number of git calls")
        self.assertLessEqual(many_calls, 30, "a fixed handful of git calls, not one per commit, tag or branch")

    def test_LEDGER_003_S10_nfr_json_takes_under_2_seconds_on_10000_commits_and_700_stories(self):
        self.repo.state("")
        best = None
        for _ in range(2):  # the better of two runs: a cold page cache is not the ledger's cost
            start = time.monotonic()
            r = self.repo.ledger("--json")
            took = time.monotonic() - start
            self.assertIn(r.returncode, (0, 1), r.stderr)
            best = took if best is None else min(best, took)
        self.assertLess(best, 2.0, f"ledger.py --json took {best:.2f}s")
        s = by_id(json.loads(r.stdout))
        self.assertEqual(len(s), self.N_STORIES)
        self.assertEqual(s["PERF-1000"]["state"], "in-production", "Story: at commit 14, deploy/production at 3000")
        self.assertEqual(s["PERF-1000"]["version"], "v1.0.0")
        self.assertEqual(s["PERF-1400"]["state"], "in-version")  # Story: at commit 5614
        self.assertEqual(s["PERF-1400"]["version"], "v2.0.0")
        self.assertEqual(s["PERF-1650"]["state"], "on-trunk")  # commit 9114: only v2.1.0-rc.1 (9500) contains it
        self.assertEqual(s["PERF-1650"]["candidate"], "v2.1.0-rc.1")
        self.assertEqual(s["PERF-1699"]["state"], "on-trunk")
        self.assertEqual(s["PERF-1699"]["branches"], ["wip/4"])


if __name__ == "__main__":
    unittest.main()
