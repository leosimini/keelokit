"""ledger.py history: the SessionStart hook completes the trunk's history (LEDGER-002);
ledger.py and ledger.py --json: every story's state from git (LEDGER-003, the classes after LedgerHistoryTest).
LEDGER-004 (corrections) and LEDGER-015 (delegated review of corrections) follow, from CORR onwards.
Run: python3 -m unittest discover -s tests

Everything runs against real git with local remotes (file:// and a refused http port), never the
network. The slow server is git's own `remote.origin.uploadpack` (a `sleep` in front of
git-upload-pack); the server that rejects --filter is a `git` wrapper first on PATH that logs its
argv. Each git call runs with a clean environment: no proxy, no global or system config."""
import hashlib
import http.server
import json
import os
import re
import select
import shutil
import subprocess
import tempfile
import textwrap
import threading
import time
import tomllib
import unittest
import uuid
from datetime import datetime, timezone
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


    # LEDGER-005: docs/ledger.md, "Performance and trust": show, next, check and --release make a fixed number of
    # git calls whatever the number of stories, and stay under the budget.
    def counted(self, state: str, *args: str) -> tuple[int, subprocess.CompletedProcess]:
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
            r = self.repo.ledger(*args, path=f"{bindir}{os.pathsep}{clean_env(self.tmp)['PATH']}")
        finally:
            self.repo.state("")
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn(r.returncode, (0, 1), r.stdout + r.stderr)
        return len(log.read_text().splitlines()), r

    def test_LEDGER_005_nfr_show_next_check_and_release_make_a_fixed_number_of_git_calls(self):
        few_state = '[ledger]\nstories = "few/*.md"\n'
        for args, few_args in ((("show", "PERF-1699"), ("show", "FEW-3")), (("next",), ("next",)),
                               (("check",), ("check",)), (("--release", "v2.0.0"), ("--release", "v2.0.0"))):
            with self.subTest(args):
                few, _ = self.counted(few_state, *few_args)
                many, r = self.counted("", *args)
                self.assertEqual(many, few, f"{args}: 7 and 700 stories make the same number of git calls")
                self.assertLessEqual(many, 32, args)

    def test_LEDGER_005_nfr_show_takes_under_2_seconds_on_10000_commits_and_700_stories(self):
        self.repo.state("")
        best = None
        for _ in range(2):
            start = time.monotonic()
            r = self.repo.ledger("show", "PERF-1699")
            took = time.monotonic() - start
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            best = took if best is None else min(best, took)
        self.assertLess(best, 2.0, f"ledger.py show took {best:.2f}s")
        self.assertIn("wip/4", r.stdout)
        r = self.repo.ledger("--release", "v2.0.0")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("PERF-1400", r.stdout)
        self.assertNotIn("PERF-1000", r.stdout, "v1.0.0 already had it")


    def test_LEDGER_005_nfr_ESC_122_the_read_does_not_grow_as_stories_times_commits(self):
        """The 700-story read costs about what the 7-story read of the same 10 000 commits costs (a scan of the
        trunk log per story made it five times slower)."""
        def best(state: str) -> float:
            self.repo.state(state)
            try:
                times = []
                for _ in range(3):
                    start = time.monotonic()
                    r = self.repo.ledger("next")
                    times.append(time.monotonic() - start)
                    self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                return min(times)
            finally:
                self.repo.state("")
        few, many = best('[ledger]\nstories = "few/*.md"\n'), best("")
        self.assertLess(many, 2.5 * few + 0.3, f"700 stories took {many:.2f}s, 7 stories {few:.2f}s")

# ─────────────── LEDGER-003 round 1: review and breaker findings (ESC-063..065, 080, 081) ───────────────


def drop_object(repo: GitRepo, sha: str) -> None:
    """Make one loose object unreadable: the tree still names it, the object store no longer has it."""
    path = repo.path / ".git/objects" / sha[:2] / sha[2:]
    assert path.exists(), f"fixture: {sha} is not a loose object"
    path.chmod(0o644)
    path.unlink()
    assert subprocess.run(["git", "cat-file", "-e", sha], cwd=repo.path, env=repo.env).returncode != 0


class LedgerUnreadableStoryTest(LedgerCase):
    """ESC-063 (review): a story whose file cannot be read is unknown, and so is everything that depends on
    it, through any chain and whatever the order of the ids; a missing blob is never fetched lazily."""

    def test_LEDGER_003_S5_an_unreadable_dependency_makes_its_dependents_unknown_whatever_the_id_order(self):
        repo = GitRepo(self.tmp)
        repo.state('[ledger]\nid_from = "filename"\n')

        def fm(*deps: str) -> str:
            return "+++\ndepends_on = [" + ", ".join(f'"{d}"' for d in deps) + "]\n+++\n"

        repo.commit("docs: plan\n\nNo-story: docs", {
            "backlog/stories/AA-2-missing.md": "# The one that will be missing (AA-2)\n",
            "backlog/stories/AA-1-before.md": fm("AA-2") + "# Sorts before its dependency\n",
            "backlog/stories/AB-1-after.md": fm("AA-2") + "# Sorts after its dependency\n",
            "backlog/stories/AA-0-chain.md": fm("AA-1") + "# Depends on a dependent, sorts first\n",
            "backlog/stories/ZZ-1-chain.md": fm("AB-1") + "# Depends on a dependent, sorts last\n",
            "backlog/stories/BB-1-free.md": "# Depends on nothing\n",
        })
        repo.publish()
        drop_object(repo, repo.git("rev-parse", "HEAD:backlog/stories/AA-2-missing.md").strip())
        s = self.stories(repo)
        self.assertEqual(s["BB-1"]["state"], "ready", "a story that depends on nothing unknown keeps its state")
        for sid in ("AA-2", "AA-1", "AB-1", "AA-0", "ZZ-1"):
            self.assertEqual(s[sid]["state"], "unknown", sid)
            self.assertTrue(isinstance(s[sid]["reason"], str) and s[sid]["reason"].strip(), f"{sid} has a reason")

    def test_LEDGER_003_S7_front_matter_mode_lists_an_unreadable_story_by_its_file_name(self):
        repo = GitRepo(self.tmp)
        repo.plan("AUTH-001", "AUTH-002", "AUTH-003", deps={"AUTH-003": ["AUTH-002"]})
        repo.publish()
        drop_object(repo, repo.git("rev-parse", "HEAD:backlog/stories/AUTH-002-s.md").strip())
        s = self.stories(repo)
        self.assertEqual(s["AUTH-001"]["state"], "ready")
        self.assertEqual(s["AUTH-002"]["state"], "unknown", "the id comes from the EPIC-NNN prefix of the name")
        self.assertTrue(s["AUTH-002"]["reason"])
        self.assertEqual(s["AUTH-003"]["state"], "unknown", "its dependency is unknown")

    def test_LEDGER_003_S7_front_matter_mode_an_unreadable_file_without_an_id_in_its_name_exits_2(self):
        repo = GitRepo(self.tmp)
        repo.commit("docs: plan\n\nNo-story: docs", {"backlog/stories/whatever.md": story_md("AUTH-001")})
        repo.publish()
        drop_object(repo, repo.git("rev-parse", "HEAD:backlog/stories/whatever.md").strip())
        r = repo.ledger("--json")
        self.assertNotIn("Traceback", r.stderr)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("whatever.md", r.stderr, "the line names the file it could not read")

    def test_LEDGER_003_S6_a_blob_none_clone_never_fetches_a_missing_story_lazily(self):
        repo = GitRepo(self.tmp)
        repo.plan("AUTH-001", "AUTH-002")
        repo.commit("feat: AUTH-001\n\nWhy.\n\nStory: AUTH-001")
        repo.publish()
        repo.run(["git", "config", "uploadpack.allowFilter", "true"], repo.bare)
        dest = self.tmp / "partial"
        repo.run(["git", "clone", "-q", "--filter=blob:none", "--no-checkout", f"file://{repo.bare}", str(dest)],
                 self.tmp)
        clone = GitRepo(self.tmp, existing=dest)
        log = self.tmp / "upload-pack.log"
        log.touch()
        server = self.tmp / "logging-upload-pack"
        server.write_text(f'#!/bin/sh\necho called >> "{log}"\nexec git-upload-pack "$@"\n')
        server.chmod(0o755)
        clone.git("config", "remote.origin.uploadpack", str(server))
        s = self.stories(clone)
        self.assertEqual(log.read_text(), "", "ledger.py fetched from origin: a missing blob must not be fetched")
        self.assertEqual(set(s), {"AUTH-001", "AUTH-002"}, "listed by the EPIC-NNN prefix of their names")
        for sid in s:
            self.assertEqual(s[sid]["state"], "unknown", sid)
            self.assertTrue(s[sid]["reason"])


class LedgerMergeRevertTest(LedgerCase):
    """ESC-064 (breaker): `git revert -m 1` of a merge writes "This reverts commit <sha>, reversing changes
    made to <sha>." and reverting the merge that brought a Story: commit reverts that story."""

    @classmethod
    def setUpClass(cls):
        repo = cls.repo = GitRepo(cls.class_tmp())
        repo.plan("AUTH-001", "AUTH-002", "AUTH-003")
        repo.on_branch("feat/one", "feat: AUTH-001 work\n\nNo-story: docs", keep=True)
        repo.commit("chore: trunk moves\n\nNo-story: docs")
        merge1 = repo.merge("feat/one", "Merge feat/one\n\nWhy.\n\nStory: AUTH-001")
        repo.git("revert", "--no-edit", "-m", "1", merge1, when=repo.next_date())
        cls.revert_msg = repo.git("log", "-1", "--format=%B")
        repo.on_branch("feat/two", "feat: AUTH-002\n\nWhy.\n\nStory: AUTH-002", keep=True)
        repo.commit("chore: trunk moves again\n\nNo-story: docs")
        merge2 = repo.merge("feat/two", "Merge feat/two")
        repo.git("revert", "--no-edit", "-m", "1", merge2, when=repo.next_date())
        repo.on_branch("feat/three", "feat: AUTH-003\n\nWhy.\n\nStory: AUTH-003", keep=True)
        repo.commit("chore: trunk moves a third time\n\nNo-story: docs")
        repo.merge("feat/three", "Merge feat/three")  # not reverted: stays on the trunk
        repo.publish()

    def test_LEDGER_003_S4_INV_005_reverting_the_story_merge_with_m1_is_a_revert(self):
        self.assertIn("reversing", self.revert_msg, "fixture: git wrote the -m 1 form")
        s = by_id(self.shared())["AUTH-001"]
        self.assertEqual(s["state"], "ready")
        self.assertIs(s["reverted"], True)

    def test_LEDGER_003_S4_INV_005_reverting_the_arrival_merge_reverts_its_story(self):
        s = by_id(self.shared())
        self.assertEqual(s["AUTH-002"]["state"], "ready")
        self.assertIs(s["AUTH-002"]["reverted"], True)
        self.assertEqual(s["AUTH-003"]["state"], "on-trunk", "a merge that is not reverted keeps its story")
        self.assertIs(s["AUTH-003"]["reverted"], False)


class LedgerIncompleteHistoryEdgesTest(LedgerCase):
    """ESC-065: the cut check covers every ref the ledger reads (remote branches too), and a shallow file
    git cannot read stops the ledger instead of letting it answer from a cut history."""

    def test_LEDGER_003_S6_a_shallow_fetch_of_a_remote_branch_makes_the_history_incomplete(self):
        repo = GitRepo(self.tmp)
        repo.plan("AUTH-001", "AUTH-002")
        repo.commit("feat: AUTH-001\n\nWhy.\n\nStory: AUTH-001")
        repo.publish()
        clone = repo.clone("full")
        repo.on_branch("claude/xyz", "wip: AUTH-002 one\n\nPart-of: AUTH-002", "wip: AUTH-002 two\n\nPart-of: AUTH-002")
        clone.git("fetch", "-q", "--depth", "1", "origin", "claude/xyz")
        self.assertEqual(clone.git("rev-parse", "--is-shallow-repository").strip(), "true", "fixture: shallow now")
        self.assertTrue(clone.git("rev-parse", "-q", "--verify", "refs/remotes/origin/claude/xyz").strip())
        d = read_json(self, clone)
        self.assertEqual(d["history"], "incomplete", "the first Part-of commit of claude/xyz was cut")
        for s in d["stories"]:
            self.assertEqual(s["state"], "unknown", s["id"])
        self.assertIn("HISTORY_INCOMPLETE", [x.get("code") for x in d["diffs"]])

    def shallow_clone(self) -> GitRepo:
        repo = GitRepo(self.tmp)
        repo.plan("AUTH-001")
        repo.commit("feat: AUTH-001\n\nWhy.\n\nStory: AUTH-001")
        for n in range(3):
            repo.commit(f"chore: {n}\n\nNo-story: docs")
        repo.publish()
        return repo.clone("shallow", depth=2)

    def test_LEDGER_003_S6_a_shallow_file_git_cannot_read_exits_2(self):
        # As root a file cannot be made unreadable by its mode; a shallow file git refuses is the closest case.
        clone = self.shallow_clone()
        (clone.path / ".git/shallow").write_bytes(b"\xff\xfe not a sha\n")
        for args in (["--json"], []):
            r = clone.ledger(*args)
            self.assertNotIn("Traceback", r.stderr)
            self.assertEqual(r.returncode, 2, f"{args}: {r.stdout}{r.stderr}")
            self.assertEqual(r.stdout.strip(), "", f"{args}: no partial answer")

    def test_LEDGER_003_S6_a_shallow_file_replaced_by_a_directory_exits_2(self):
        # git then says "not shallow" while the history is still cut: never an answer from it.
        clone = self.shallow_clone()
        shallow = clone.path / ".git/shallow"
        shallow.unlink()
        shallow.mkdir()
        r = clone.ledger("--json")
        self.assertNotIn("Traceback", r.stderr)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertEqual(r.stdout.strip(), "")


class LedgerRefFactsTest(LedgerCase):
    """ESC-080 (breaker, review): every ref keeps its facts: a nested annotated tag is peeled to its commit,
    and a commit on several origin branches is on each of them."""

    def test_LEDGER_003_S2_a_v_tag_on_a_nested_annotated_tag_is_peeled_to_the_commit(self):
        repo = GitRepo(self.tmp)
        repo.plan("AUTH-001")
        repo.commit("feat: AUTH-001\n\nWhy.\n\nStory: AUTH-001")
        repo.tag("inner")
        repo.tag("v1.0.0", "inner")  # an annotated tag of an annotated tag
        repo.publish()
        self.assertEqual(repo.git("cat-file", "-t", "v1.0.0^{}").strip(), "commit")
        self.assertEqual(repo.git("cat-file", "-p", "v1.0.0").splitlines()[1], "type tag", "fixture: nested")
        s = self.stories(repo)["AUTH-001"]
        self.assertEqual(s["state"], "in-version")
        self.assertEqual(s["version"], "v1.0.0")

    def test_LEDGER_003_S3_one_part_of_commit_on_two_origin_branches_lists_both(self):
        repo = GitRepo(self.tmp)
        repo.plan("AUTH-001")
        repo.publish()
        sha = repo.on_branch("claude/b", "wip: AUTH-001\n\nPart-of: AUTH-001")[0]
        repo.git("push", "-q", "origin", f"{sha}:refs/heads/claude/a")
        repo.publish()
        s = self.stories(repo)["AUTH-001"]
        self.assertEqual(s["state"], "in-progress")
        self.assertEqual(s["branches"], ["claude/a", "claude/b"])


class LedgerSpanishSummaryTest(LedgerCase):
    """ESC-081 (review): with [dashboard] lang = "es" the state names are Spanish too."""

    ENGLISH = ("defined", "ready", "in-progress", "on-trunk", "in-version", "in-staging", "in-production", "unknown")

    def assert_spanish(self, out: str) -> None:
        for word in self.ENGLISH:
            self.assertIsNone(re.search(rf"(?<![\w-]){re.escape(word)}(?![\w-])", out, re.I),
                              f"English state name {word!r} in the Spanish summary:\n{out}")

    def test_LEDGER_003_dx_the_spanish_summary_names_the_states_in_spanish(self):
        repo = GitRepo(self.tmp)
        repo.plan("AUTH-001", "AUTH-002", "AUTH-003", "AUTH-004", "AUTH-005", "AUTH-006",
                  deps={"AUTH-005": ["AUTH-006"]})
        s1 = repo.commit("feat: AUTH-001\n\nWhy.\n\nStory: AUTH-001")
        repo.tag("v1.0.0")
        repo.commit("feat: AUTH-002\n\nWhy.\n\nStory: AUTH-002")
        repo.publish()
        repo.deploy("staging", s1)
        repo.on_branch("claude/xyz", "wip: AUTH-003\n\nPart-of: AUTH-003")
        repo.publish()
        repo.state('[dashboard]\nlang = "es"\n')
        r = repo.ledger()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assert_spanish(r.stdout)
        self.assertIn("en curso", r.stdout.lower())

    def test_LEDGER_003_S6_the_spanish_summary_says_desconocido_not_unknown(self):
        repo = GitRepo(self.tmp)
        repo.plan("AUTH-001")
        for n in range(3):
            repo.commit(f"chore: {n}\n\nNo-story: docs")
        repo.publish()
        clone = repo.clone("shallow", depth=2)
        clone.state('[dashboard]\nlang = "es"\n')
        r = clone.ledger()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assert_spanish(r.stdout)
        self.assertIn("desconocid", r.stdout.lower())


# ─────────────── LEDGER-003 round 2: breaker findings (ESC-082..084) ───────────────


class LedgerNestedMergeRevertTest(LedgerCase):
    """ESC-082: reverting a merge reverts every commit reachable from it and not from its first parent,
    wherever the merge sits (here: off the trunk's first-parent chain)."""

    def test_LEDGER_003_S4_INV_005_reverting_a_merge_off_the_first_parent_chain_reverts_its_story(self):
        repo = GitRepo(self.tmp)
        repo.plan("AUTH-001", "AUTH-002")
        repo.git("checkout", "-q", "-b", "feat")
        repo.git("checkout", "-q", "-b", "sub")
        repo.commit("feat: AUTH-001\n\nWhy.\n\nStory: AUTH-001")
        repo.git("checkout", "-q", "feat")
        repo.commit("feat: AUTH-002\n\nWhy.\n\nStory: AUTH-002")
        inner = repo.merge("sub", "Merge sub into feat\n\nNo-story: release")
        repo.git("checkout", "-q", "main")
        repo.commit("chore: trunk moves\n\nNo-story: docs")
        outer = repo.merge("feat", "Merge feat\n\nNo-story: release")
        self.assertNotIn(inner, repo.git("rev-list", "--first-parent", "main").split(), "fixture: off the chain")
        repo.git("revert", "--no-edit", "-m", "1", inner, when=repo.next_date())
        repo.publish()
        self.assertTrue(outer)
        s = self.stories(repo)
        self.assertEqual(s["AUTH-001"]["state"], "ready")
        self.assertIs(s["AUTH-001"]["reverted"], True)
        self.assertEqual(s["AUTH-002"]["state"], "on-trunk", "reachable from the merge's first parent: not reverted")
        self.assertIs(s["AUTH-002"]["reverted"], False)


class LedgerUnreadableIdTest(LedgerCase):
    """ESC-083: with a story file unreadable, an id it might carry is unknown, not unmet; and a readable
    file wins the duplicate-id tie over an unreadable one."""

    def test_LEDGER_003_S5_a_dependency_hidden_in_an_unreadable_file_named_with_another_id_is_unknown(self):
        repo = GitRepo(self.tmp)
        repo.plan("AUTH-001")
        repo.publish()
        repo.run(["git", "config", "uploadpack.allowFilter", "true"], repo.bare)
        dest = self.tmp / "partial"
        repo.run(["git", "clone", "-q", "--filter=blob:none", f"file://{repo.bare}", str(dest)], self.tmp)
        clone = GitRepo(self.tmp, existing=dest)
        repo.commit("docs: more stories\n\nNo-story: docs", {
            "backlog/stories/A-9-wrongname.md": story_md("E-5"),
            "backlog/stories/F-6.md": story_md("F-6", depends_on=("E-5",)),
        })
        repo.publish()
        clone.git("fetch", "-q", "origin")
        clone.git("cat-file", "blob", "refs/remotes/origin/main:backlog/stories/F-6.md")  # only F-6's blob comes
        clone.git("config", "remote.origin.url", OFFLINE)  # nothing else can come
        s = self.stories(clone)
        self.assertEqual(s["AUTH-001"]["state"], "ready")
        self.assertEqual(s["A-9"]["state"], "unknown", "listed by its file name")
        self.assertEqual(s["F-6"]["title"], "Title of F-6", "fixture: F-6 is readable")
        self.assertEqual(s["F-6"]["state"], "unknown", "E-5 may be the unreadable file: unknown, not unmet")
        self.assertTrue(s["F-6"]["reason"])

    def test_LEDGER_003_S7_a_readable_story_wins_the_duplicate_id_over_an_unreadable_file(self):
        repo = GitRepo(self.tmp)
        repo.commit("docs: plan\n\nNo-story: docs", {
            "backlog/stories/AUTH-001-old.md": story_md("AUTH-001", title="The old one, unreadable"),
            "backlog/stories/AUTH-001-x.md": story_md("AUTH-001", title="The readable one"),
        })
        repo.commit("feat: AUTH-001\n\nWhy.\n\nStory: AUTH-001")
        repo.publish()
        drop_object(repo, repo.git("rev-parse", "HEAD:backlog/stories/AUTH-001-old.md").strip())
        s = self.stories(repo)["AUTH-001"]
        self.assertEqual(s["title"], "The readable one")
        self.assertEqual(s["path"], "backlog/stories/AUTH-001-x.md")
        self.assertEqual(s["state"], "on-trunk")


class LedgerBranchBudgetTest(LedgerCase):
    """ESC-084: the branch walk does not grow as branches × off-trunk commits: 2000 origin branches along
    a 10 000-commit chain off the trunk (refs written by fast-import, only the refs are read). A walk per
    branch visits ~10 million commits here (about 5 s); one walk over the off-trunk graph stays well under 2 s.
    (1000 branches on 3000 commits, the breaker's size, ran in 0.6 s on the quadratic walk: too small.)"""

    CHAIN = 10_000
    BRANCHES = 2000

    @classmethod
    def setUpClass(cls):
        repo = cls.repo = GitRepo(cls.class_tmp(), remote=False)
        out = []

        def data(text: str) -> None:
            out.append(f"data {len(text.encode())}\n{text}\n")

        def committer(k: int) -> str:
            return f"committer T <t@example.com> {EPOCH + 60 * k} +0000\n"

        out.append(f"commit refs/heads/main\nmark :1\n{committer(1)}")
        data("docs: plan\n\nNo-story: docs\n")
        for i in range(10):
            out.append(f"M 100644 inline backlog/stories/P-{i}-s.md\n")
            data(story_md(f"P-{i}"))
        out.append("reset refs/remotes/origin/main\nfrom :1\n\n")
        for k in range(2, cls.CHAIN + 2):
            out.append(f"commit refs/heads/chain\nmark :{k}\n{committer(k)}")
            data(f"wip {k}\n\nPart-of: P-{k % 10}\n")
            out.append(f"from :{k - 1}\nM 100644 inline chain.txt\n")
            data(f"{k}\n")
        step = cls.CHAIN // cls.BRANCHES
        for n in range(cls.BRANCHES):
            out.append(f"reset refs/remotes/origin/wip/{n:04}\nfrom :{2 + step * n + step - 1}\n\n")
        r = subprocess.run(["git", "fast-import", "--quiet"], cwd=repo.path, env=repo.env, input="".join(out),
                           capture_output=True, text=True, timeout=300)
        assert r.returncode == 0, r.stderr
        repo.git("branch", "-q", "-D", "chain")
        assert len(repo.git("for-each-ref", "refs/remotes/origin/wip").splitlines()) == cls.BRANCHES

    def test_LEDGER_003_S10_nfr_2000_branches_along_a_10000_commit_chain_take_under_2_seconds(self):
        best = None
        for _ in range(2):  # the better of two runs
            start = time.monotonic()
            r = self.repo.ledger("--json", timeout=120)
            took = time.monotonic() - start
            self.assertIn(r.returncode, (0, 1), r.stderr)
            best = took if best is None else min(best, took)
        self.assertLess(best, 2.0, f"ledger.py --json took {best:.2f}s")
        s = by_id(json.loads(r.stdout))
        self.assertEqual(s["P-0"]["state"], "in-progress")
        step = self.CHAIN // self.BRANCHES
        expected = [f"wip/{n:04}" for n in range(self.BRANCHES) if 2 + step * n + step - 1 >= 10]  # P-0 first at :10
        self.assertEqual(s["P-0"]["branches"], expected, "every branch holding a Part-of: P-0 commit")


# ── LEDGER-004: approved corrections (backlog/ledger-corrections.toml) and a backfill for the history
# that has no trailers. The file is read from the trunk's tree like the stories; an active row makes a
# story without a live Story: commit on-trunk, `reconstructed` (INV-005); no row on the trunk may change
# or disappear (INV-008). ──

CORR = "backlog/ledger-corrections.toml"
PROPOSED = ".keelokit/ledger-corrections.proposed.toml"
CORR_HEADER = "# Ledger corrections: append-only and the human's (QA-4). Format: docs/ledger.md.\n"
ROW_KEYS = {"story", "commit", "kind", "evidence", "approver", "date"}
FULL_SHA = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")


def toml_row(**fields) -> str:
    """One [[row]] table. Values are Python values written as TOML (json.dumps fits strings and ints);
    None leaves the key out. Defaults: a valid backfill row for UXC-113 approved by Leo (commit is required)."""
    row = {"story": "UXC-113", "commit": None, "kind": "backfill", "evidence": "train sheet 18; BOARD.md row T18",
           "approver": "Leo", "date": "2026-11-25", **fields}
    return "\n[[row]]\n" + "".join(f"{k} = {json.dumps(v)}\n" for k, v in row.items() if v is not None)


def corrections(*rows: str) -> str:
    return CORR_HEADER + "".join(rows)


def arrival(repo: GitRepo, sha: str) -> str:
    """The trunk arrival of a commit made straight on the trunk: its committer date, in UTC."""
    ts = int(repo.git("log", "-1", "--format=%ct", sha).strip())
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def proposed_rows(repo: GitRepo) -> list[dict]:
    return tomllib.loads((repo.path / PROPOSED).read_text()).get("row", [])


def corrections_rows(repo: GitRepo) -> list[dict]:
    return tomllib.loads((repo.path / CORR).read_text()).get("row", [])


def ledger_check(test: unittest.TestCase, repo: GitRepo) -> dict:
    """`ledger.py check --json`: {"schema": 1, "diffs": [...]}, exit 1 iff an error-level diff, else 0."""
    r = repo.ledger("check", "--json")
    test.assertNotIn("Traceback", r.stderr)
    test.assertIn(r.returncode, (0, 1), f"ledger.py check --json exited {r.returncode}\n{r.stdout}{r.stderr}")
    try:
        data = json.loads(r.stdout)
    except ValueError:
        test.fail(f"ledger.py check --json did not print JSON:\n{r.stdout[:2000]}")
    test.assertEqual(data.get("schema"), 1)
    errors = [d for d in data["diffs"] if d["level"] == "error"]
    test.assertEqual(r.returncode, 1 if errors else 0, f"exit vs error diffs: {data['diffs']}")
    return data


def codes(data: dict, level: str | None = None) -> list[str]:
    return [d["code"] for d in data["diffs"] if level is None or d["level"] == level]


def details(data: dict, code: str) -> str:
    return "\n".join(str(d.get("detail", "")) for d in data["diffs"] if d["code"] == code)


def propose(test: unittest.TestCase, repo: GitRepo, *args: str) -> tuple[subprocess.CompletedProcess, list[dict]]:
    r = repo.ledger("backfill", "--propose", *args)
    test.assertNotIn("Traceback", r.stderr)
    test.assertEqual(r.returncode, 0, r.stdout + r.stderr)
    test.assertTrue((repo.path / PROPOSED).is_file(), "backfill --propose writes the proposed file")
    return r, proposed_rows(repo)


def person_env(tmp: Path, extra_env: dict | None = None) -> dict:
    """A person's shell: the clean environment without CLAUDECODE (the suite may run inside a Claude session,
    and `backfill --accept` refuses Claude Code's own shell, ESC-092)."""
    env = clean_env(tmp)
    env.pop("CLAUDECODE", None)
    env.update(extra_env or {})
    return env


def run_in_pty(repo: GitRepo, *args: str, answer: str | None = None,
               timeout: float = 60, extra_env: dict | None = None) -> tuple[int, str]:
    """ledger.py with stdin, stdout and stderr on a real pseudo-terminal, as a person in their terminal.
    `answer` is typed once the `[y/N]` question appears; the output is read until the program exits."""
    master, slave = os.openpty()
    p = subprocess.Popen(["python3", ".keelokit/bin/ledger.py", *args], cwd=repo.path,
                         env=person_env(repo.tmp, extra_env),
                         stdin=slave, stdout=slave, stderr=slave, close_fds=True)
    os.close(slave)
    out, sent = b"", False
    deadline = time.monotonic() + timeout
    try:
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                p.kill()
                raise AssertionError(f"ledger.py {' '.join(args)} did not finish:\n{out.decode(errors='replace')}")
            ready, _, _ = select.select([master], [], [], left)
            if not ready:
                continue
            try:
                chunk = os.read(master, 4096)
            except OSError:  # EIO: the program exited and closed the terminal
                break
            if not chunk:
                break
            out += chunk
            if answer is not None and not sent and b"[y/N]" in out:
                os.write(master, answer.encode())
                sent = True
    finally:
        os.close(master)
    return p.wait(timeout=timeout), out.decode(errors="replace")


def today_dates() -> set[str]:
    now = time.time()
    return {time.strftime("%Y-%m-%d", time.localtime(now)), time.strftime("%Y-%m-%d", time.gmtime(now))}


class LedgerCorrectionsProposeTest(LedgerCase):
    """S1: `backfill --propose` finds candidates in trunk commits that name the id and in merges of branches
    named with it; it leaves out what is no evidence and never touches the corrections file."""

    @classmethod
    def setUpClass(cls):
        repo = cls.repo = GitRepo(cls.class_tmp())
        repo.plan("UXC-110", "UXC-112", "UXC-113", "UXC-115", "UXC-116", "UXC-117", "UXC-118", "UXC-119", "UXC-121")
        c = cls.c = {}
        c["added114"] = repo.commit("docs: add UXC-114", {"backlog/stories/UXC-114-s.md": story_md("UXC-114")})
        c["s110"] = repo.commit("feat: UXC-110 done\n\nWhy.\n\nStory: UXC-110")
        c["m110"] = repo.commit("fix: UXC-110 follow-up")
        c["low113"] = repo.commit("chore: tidy the form\n\nA follow-up of UXC-113.")
        c["med113"] = repo.commit("feat: login form for UXC-113")
        c["low112"] = repo.commit("refactor: split helpers\n\nPrepares UXC-112.")
        c["ns115"] = repo.commit("docs: notes on UXC-115\n\nNo-story: docs")
        c["rev116"] = repo.commit("feat: UXC-116 first try")
        repo.revert(c["rev116"])
        c["zzz"] = repo.commit("feat: ZZZ-999 is not a story")
        c["lower121"] = repo.commit("chore: rename the uxc-121 folder")
        c["near113"] = repo.commit("feat: UXC-1130 is another id")
        repo.on_branch("uxc-117-login", "wip: the form", keep=True)
        c["m117"] = repo.merge("uxc-117-login", "Merge branch 'uxc-117-login'")
        repo.on_branch("feat/uxc-118-export", "wip: export")  # pushed: origin/feat/uxc-118-export
        c["m118"] = repo.merge("origin/feat/uxc-118-export",
                               "Merge remote-tracking branch 'origin/feat/uxc-118-export'")
        repo.on_branch("uxc-119-search", "wip: search", keep=True)
        c["m119"] = repo.merge("uxc-119-search", "Merge pull request #12 from acme/uxc-119-search\n\nSearch")
        repo.publish()

    def proposal(self) -> tuple[subprocess.CompletedProcess, list[dict], dict]:
        cls = type(self)
        if "_proposal" not in cls.__dict__:
            r, rows = propose(self, cls.repo)
            cls._proposal = (r, rows, {row["story"]: row for row in rows})
        return cls._proposal

    def test_LEDGER_004_S1_a_subject_naming_the_id_is_a_medium_candidate_with_its_evidence(self):
        row = self.proposal()[2]["UXC-113"]
        self.assertEqual(row["commit"], self.c["med113"])
        self.assertEqual(row["kind"], "backfill")
        self.assertEqual(row["confidence"], "medium")
        self.assertTrue(isinstance(row["evidence"], str) and row["evidence"].strip())
        self.assertIn(self.c["low113"][:7], row["evidence"], "the evidence also names the other candidates")

    def test_LEDGER_004_S1_logic_a_body_only_mention_is_a_low_candidate(self):
        row = self.proposal()[2]["UXC-112"]
        self.assertEqual(row["commit"], self.c["low112"])
        self.assertEqual(row["confidence"], "low")

    def test_LEDGER_004_S1_data_one_row_per_story_with_a_full_sha_and_only_stories_that_exist(self):
        rows = self.proposal()[1]
        stories = [row["story"] for row in rows]
        self.assertEqual(len(stories), len(set(stories)), f"one row per story: {stories}")
        self.assertNotIn("ZZZ-999", stories, "an id that is no story gets no row")
        for row in rows:
            with self.subTest(story=row["story"]):
                self.assertLessEqual({"story", "commit", "kind", "confidence", "evidence"}, set(row))
                self.assertRegex(row["commit"], rf"^{FULL_SHA.pattern}$")
                self.assertEqual(row["kind"], "backfill")
                self.assertIn(row["confidence"], ("high", "medium", "low"))
                self.assertTrue(row["evidence"].strip())

    def test_LEDGER_004_S1_INV_005_a_story_already_on_trunk_gets_no_row(self):
        self.assertNotIn("UXC-110", self.proposal()[2], "UXC-110 has a live Story: commit")

    def test_LEDGER_004_S1_logic_the_commit_that_added_the_story_file_is_no_candidate(self):
        self.assertNotIn("UXC-114", self.proposal()[2])

    def test_LEDGER_004_S1_logic_no_story_and_reverted_commits_are_no_candidates(self):
        rows = self.proposal()[2]
        self.assertNotIn("UXC-115", rows, "named only by a No-story: commit")
        self.assertNotEqual(rows.get("UXC-116", {}).get("commit"), self.c["rev116"], "a reverted commit")

    def test_LEDGER_004_S1_logic_ids_are_exact_uppercase_tokens(self):
        rows = self.proposal()[2]
        self.assertNotIn("UXC-121", rows, "a lowercase id in a subject that is no merge is not the id")
        self.assertNotIn(self.c["near113"][:7], rows["UXC-113"]["evidence"], "UXC-1130 is not UXC-113")

    def test_LEDGER_004_S1_logic_a_merge_of_a_branch_named_with_the_id_is_a_medium_candidate(self):
        rows = self.proposal()[2]
        for sid, key in [("UXC-117", "m117"), ("UXC-118", "m118"), ("UXC-119", "m119")]:
            with self.subTest(sid):
                self.assertIn(sid, rows)
                self.assertEqual(rows[sid]["commit"], self.c[key], "the merge commit")
                self.assertEqual(rows[sid]["confidence"], "medium")

    def test_LEDGER_004_S1_dx_propose_prints_count_and_path_overwrites_and_never_touches_the_corrections_file(self):
        r, rows, _ = self.proposal()
        self.assertIn(PROPOSED, r.stdout)
        self.assertIn(str(len(rows)), r.stdout)
        self.assertFalse((self.repo.path / CORR).exists(), "propose never writes backlog/ledger-corrections.toml")
        _, again = propose(self, self.repo)
        self.assertEqual(again, rows, "a second run overwrites the proposed file, it does not append")


class LedgerCorrectionsNoEvidenceTest(LedgerCase):
    def test_LEDGER_004_S1_logic_twenty_commits_with_no_id_by_another_author_propose_nothing(self):
        repo = GitRepo(self.tmp)
        repo.plan("UXC-113", "UXC-114")
        repo.git("config", "user.name", "Other")
        repo.git("config", "user.email", "other@example.com")
        for n in range(20):
            repo.commit(f"update the docs ({n})\n\nMore words, version 2-{n}.")
        repo.publish()
        r, rows = propose(self, repo)
        self.assertEqual(rows, [], f"no id, no candidate:\n{(repo.path / PROPOSED).read_text()}")
        self.assertRegex(r.stdout, r"\b0\b")


class LedgerCorrectionsEvidenceFileTest(LedgerCase):
    """S2: `--from FILE` lines that name ids and a sha (high) or a train (the trunk commit of that train)."""

    @classmethod
    def setUpClass(cls):
        tmp = cls.class_tmp()
        repo = cls.repo = GitRepo(tmp)
        repo.plan("UXC-110", "UXC-111", "UXC-112", "UXC-113", "UXC-114", "UXC-115")
        c = cls.c = {}
        c["t18"] = repo.commit("feat: train 18 (#40)")
        c["sha112"] = repo.commit("feat: the search box")
        c["c19a"] = repo.commit("feat: convoy work\n\nConvoy: 19")
        c["c19b"] = repo.commit("fix: Tren #19 follow-up")
        repo.on_branch("convoy/20", "wip: the export", keep=True)
        c["t20"] = repo.merge("convoy/20", "Merge branch 'convoy/20'")
        c["sha114"] = repo.commit("feat: something older")
        c["med114"] = repo.commit("feat: UXC-114 named in a newer subject")
        repo.publish()
        cls.sheet = tmp / "trains.md"
        cls.sheet.write_text("# Trains\n\n| Train | Stories | Date |\n|---|---|---|\n"
                             "| 18 | UXC-110, UXC-111 | 2026-03-01 |\n")  # line 5
        cls.board = tmp / "BOARD.md"
        cls.board.write_text(f"UXC-112 shipped in {c['sha112'][:9]}\n"
                             "T19: UXC-113\n"
                             "train 20 UXC-115\n"
                             f"UXC-114 {c['sha114']}\n")

    def rows(self) -> dict:
        cls = type(self)
        if "_rows" not in cls.__dict__:
            _, rows = propose(self, cls.repo, "--from", str(cls.sheet), "--from", str(cls.board))
            cls._rows = {row["story"]: row for row in rows}
        return cls._rows

    def test_LEDGER_004_S2_both_stories_of_train_18_point_at_its_squash_commit(self):
        for sid in ("UXC-110", "UXC-111"):
            with self.subTest(sid):
                row = self.rows()[sid]
                self.assertEqual(row["commit"], self.c["t18"])
                self.assertEqual(row["confidence"], "medium", "one commit for the train")
                self.assertIn("trains.md", row["evidence"])
                self.assertRegex(row["evidence"], r"\b5\b", "the evidence names the line number")

    def test_LEDGER_004_S2_logic_a_line_with_a_sha_prefix_is_high(self):
        row = self.rows()["UXC-112"]
        self.assertEqual(row["commit"], self.c["sha112"], "the prefix resolves to the full sha")
        self.assertEqual(row["confidence"], "high")
        self.assertIn("BOARD.md", row["evidence"])

    def test_LEDGER_004_S2_logic_a_train_with_several_commits_is_the_newest_low(self):
        row = self.rows()["UXC-113"]
        self.assertEqual(row["commit"], self.c["c19b"], "Convoy: 19 trailer and 'Tren #19': the newest")
        self.assertEqual(row["confidence"], "low")

    def test_LEDGER_004_S2_logic_a_train_found_by_its_convoy_branch_merge(self):
        row = self.rows()["UXC-115"]
        self.assertEqual(row["commit"], self.c["t20"])
        self.assertEqual(row["confidence"], "medium")

    def test_LEDGER_004_S2_logic_the_highest_confidence_wins_over_the_newest(self):
        row = self.rows()["UXC-114"]
        self.assertEqual(row["commit"], self.c["sha114"], "high (sha line) beats a newer medium (subject)")
        self.assertEqual(row["confidence"], "high")

    def test_LEDGER_004_S2_dx_an_evidence_file_that_cannot_be_read_exits_2(self):
        r = self.repo.ledger("backfill", "--propose", "--from", str(self.sheet.parent / "missing.md"))
        self.assertNotIn("Traceback", r.stderr)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)


class LedgerCorrectionsReconstructTest(LedgerCase):
    """S4 and INV-005: an active row makes a story with no live Story: commit on-trunk (or later), marked
    reconstructed, with the row as its `correction`; it satisfies depends_on like any on-trunk story."""

    @property
    def s(self) -> dict:
        return by_id(self.shared())

    @classmethod
    def setUpClass(cls):
        repo = cls.repo = GitRepo(cls.class_tmp())
        repo.plan("UXC-113", "UXC-114", "UXC-115", "UXC-116", "UXC-117", deps={"UXC-114": ["UXC-113"]})
        c = cls.c = {}
        c["login"] = repo.commit("feat: the login form")
        repo.tag("v1.0.0")
        c["s115"] = repo.commit("feat: UXC-115\n\nWhy.\n\nStory: UXC-115")
        c["old116"] = repo.commit("feat: search, first part")
        c["new116"] = repo.commit("feat: search, second part")
        c["r117"] = repo.commit("feat: export")
        repo.revert(c["r117"])
        repo.commit("chore: corrections\n\nNo-story: ledger", {CORR: corrections(
            toml_row(commit=c["login"]),
            toml_row(story="UXC-115", commit=c["login"], evidence="also on BOARD.md"),
            toml_row(story="UXC-116", commit=c["new116"], kind="late", evidence="slipped through"),
            toml_row(story="UXC-116", commit=c["old116"], evidence="train 3"),
            toml_row(story="UXC-117", commit=c["r117"], evidence="reverted later"))})
        repo.publish()
        repo.deploy("staging", c["login"])

    def test_LEDGER_004_S4_an_accepted_row_reconstructs_the_story_with_its_evidence(self):
        s = self.s["UXC-113"]
        self.assertEqual(s["state"], "in-staging", "version and deploys from the row's commit, as a Story: commit")
        self.assertEqual(s["version"], "v1.0.0")
        self.assertEqual(s["environments"]["staging"], self.c["login"])
        self.assertIs(s["reconstructed"], True)
        self.assertEqual(s["commit"], self.c["login"])
        self.assertEqual(s["since"], arrival(self.repo, self.c["login"]))
        self.assertEqual(s["correction"], {"kind": "backfill", "commit": self.c["login"],
                                           "evidence": "train sheet 18; BOARD.md row T18", "approver": "Leo",
                                           "date": "2026-11-25"})

    def test_LEDGER_004_S4_INV_005_a_reconstructed_story_satisfies_depends_on(self):
        self.assertEqual(self.s["UXC-114"]["state"], "ready")

    def test_LEDGER_004_S4_INV_005_a_live_story_commit_ignores_rows(self):
        s = self.s["UXC-115"]
        self.assertEqual(s["state"], "on-trunk")
        self.assertEqual(s["commit"], self.c["s115"])
        self.assertIs(s["reconstructed"], False)
        self.assertIsNone(s["correction"])

    def test_LEDGER_004_S4_logic_several_active_rows_the_oldest_by_trunk_arrival(self):
        s = self.s["UXC-116"]
        self.assertEqual(s["state"], "on-trunk")
        self.assertEqual(s["commit"], self.c["old116"])
        self.assertEqual(s["since"], arrival(self.repo, self.c["old116"]))
        self.assertEqual(s["correction"]["evidence"], "train 3")
        self.assertEqual(s["correction"]["kind"], "backfill")

    def test_LEDGER_004_S4_INV_005_a_row_whose_commit_is_reverted_reconstructs_nothing(self):
        s = self.s["UXC-117"]
        self.assertEqual(s["state"], "ready")
        self.assertIs(s["reconstructed"], False)
        self.assertIsNone(s["correction"])

    def test_LEDGER_004_S4_data_every_story_has_a_correction_key_null_unless_reconstructed(self):
        for s in self.shared()["stories"]:
            with self.subTest(s["id"]):
                self.assertIn("correction", s)
                if not s["reconstructed"]:
                    self.assertIsNone(s["correction"])

    def test_LEDGER_004_S4_dx_check_passes_valid_rows(self):
        data = ledger_check(self, self.repo)
        self.assertEqual([c for c in codes(data) if c.startswith("CORRECTION")], [], data["diffs"])


class LedgerCorrectionsInvalidTest(LedgerCase):
    """S6: an invalid row is CORRECTION_INVALID (an error) and is ignored; the valid rows still count."""

    @classmethod
    def setUpClass(cls):
        repo = cls.repo = GitRepo(cls.class_tmp())
        repo.plan("UXC-113", "UXC-114")
        cls.login = repo.commit("feat: the login form")
        cls.search = repo.commit("feat: search")
        cls.side = repo.on_branch("side", "feat: never merged")[0]
        repo.publish()
        cls.base = repo.sha()

    def trunk_file(self, text: str) -> None:
        """The trunk is the base plus one commit of the corrections file holding `text` (and nothing earlier)."""
        repo = self.repo
        repo.git("reset", "-q", "--hard", self.base)
        repo.commit("chore: corrections\n\nNo-story: ledger", {CORR: text})
        repo.git("push", "-q", "-f", "origin", "main")
        repo.git("fetch", "-q", "--prune", "origin")

    def test_LEDGER_004_S6_each_invalid_row_is_correction_invalid_and_ignored(self):
        login = self.login
        variants = {
            "commit not reachable from the trunk": toml_row(commit=self.side),
            "story that does not exist": toml_row(story="NOPE-9", commit=login),
            "empty approver": toml_row(commit=login, approver=""),
            "no approver": toml_row(commit=login, approver=None),
            "delegated approver": toml_row(commit=login, approver="delegated:run-7"),
            "unknown kind": toml_row(commit=login, kind="fix"),
            "date not YYYY-MM-DD": toml_row(commit=login, date="25/11/2026"),
            "date without padding": toml_row(commit=login, date="2026-11-5"),
            "short sha": toml_row(commit=login[:7]),
            "uppercase sha": toml_row(commit=login.upper()),
            "no evidence": toml_row(commit=login, evidence=None),
            "evidence not a string": toml_row(commit=login, evidence=3),
            "empty story": toml_row(story="", commit=login),
            "retract with no earlier row": toml_row(commit=login, kind="retract"),
        }
        for why, bad in variants.items():
            with self.subTest(why):
                self.trunk_file(corrections(bad, toml_row(story="UXC-114", commit=self.search)))
                data = ledger_check(self, self.repo)
                self.assertIn("CORRECTION_INVALID", codes(data, "error"), data["diffs"])
                s = self.stories(self.repo)
                self.assertEqual(s["UXC-113"]["state"], "ready", "the invalid row is ignored")
                self.assertIs(s["UXC-113"]["reconstructed"], False)
                self.assertIs(s["UXC-114"]["reconstructed"], True, "a valid row next to it still counts")

    def test_LEDGER_004_S6_a_file_that_is_not_toml_is_one_correction_invalid_and_no_row_counts(self):
        self.trunk_file(CORR_HEADER + "[[row]\nstory = \n" + toml_row(story="UXC-114", commit=self.search))
        data = ledger_check(self, self.repo)
        self.assertEqual(codes(data), ["CORRECTION_INVALID"], data["diffs"])
        s = self.stories(self.repo)
        self.assertIs(s["UXC-114"]["reconstructed"], False)

    def test_LEDGER_004_S6_dx_check_text_is_one_line_per_diff(self):
        self.trunk_file(corrections(toml_row(story="NOPE-9", commit=self.login)))
        r = self.repo.ledger("check")
        self.assertNotIn("Traceback", r.stderr)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertRegex(r.stdout, r"(?m)^error CORRECTION_INVALID \S")

    def test_LEDGER_004_S6_dx_json_lists_the_same_diff(self):
        self.trunk_file(corrections(toml_row(commit=self.login, approver="")))
        self.assertIn("CORRECTION_INVALID", codes(read_json(self, self.repo), "error"))


class LedgerCorrectionsRetractTest(LedgerCase):
    """S7: a retract deactivates the earlier active rows of the same story and commit (INV-005)."""

    def repo_with(self, *rows_of) -> tuple[GitRepo, dict]:
        repo = GitRepo(self.tmp)
        repo.plan("UXC-113")
        c = {"a": repo.commit("feat: the login form"), "b": repo.commit("feat: the login form, part 2")}
        repo.commit("chore: corrections\n\nNo-story: ledger", {CORR: corrections(*(f(c) for f in rows_of))})
        repo.publish()
        return repo, c

    def test_LEDGER_004_S7_INV_005_a_retract_cancels_the_row(self):
        repo, _ = self.repo_with(lambda c: toml_row(commit=c["a"]),
                                 lambda c: toml_row(commit=c["a"], kind="retract", evidence="wrong commit"))
        s = self.stories(repo)["UXC-113"]
        self.assertEqual(s["state"], "ready")
        self.assertIs(s["reconstructed"], False)
        self.assertIsNone(s["correction"])
        self.assertEqual(ledger_check(self, repo)["diffs"], [])

    def test_LEDGER_004_S7_logic_a_retract_appended_later_cancels_and_is_no_edit(self):
        repo, c = self.repo_with(lambda c: toml_row(commit=c["a"]))
        self.assertIs(self.stories(repo)["UXC-113"]["reconstructed"], True)
        text = (repo.path / CORR).read_text() + toml_row(commit=c["a"], kind="retract", evidence="wrong commit")
        repo.commit("chore: retract\n\nNo-story: ledger", {CORR: text})
        repo.publish()
        self.assertIs(self.stories(repo)["UXC-113"]["reconstructed"], False)
        self.assertEqual(ledger_check(self, repo)["diffs"], [])

    def test_LEDGER_004_S7_logic_a_retract_leaves_the_rows_of_another_commit(self):
        repo, c = self.repo_with(lambda c: toml_row(commit=c["a"]), lambda c: toml_row(commit=c["b"]),
                                 lambda c: toml_row(commit=c["a"], kind="retract", evidence="wrong commit"))
        s = self.stories(repo)["UXC-113"]
        self.assertIs(s["reconstructed"], True)
        self.assertEqual(s["commit"], c["b"])

    def test_LEDGER_004_S7_logic_a_row_after_the_retract_is_active_again(self):
        repo, c = self.repo_with(lambda c: toml_row(commit=c["a"]),
                                 lambda c: toml_row(commit=c["a"], kind="retract", evidence="wrong"),
                                 lambda c: toml_row(commit=c["a"], kind="late", evidence="right after all"))
        s = self.stories(repo)["UXC-113"]
        self.assertIs(s["reconstructed"], True)
        self.assertEqual(s["correction"]["kind"], "late")


class LedgerCorrectionsAppendOnlyTest(LedgerCase):
    """S5 and INV-008: every row of every earlier version of the file on the trunk's first-parent chain must
    still be in the tip's version (compared as a whole table), else CORRECTION_EDITED naming story and commit."""

    @classmethod
    def setUpClass(cls):
        repo = cls.repo = GitRepo(cls.class_tmp())
        repo.plan("UXC-113", "UXC-114")
        cls.login = repo.commit("feat: the login form")
        cls.search = repo.commit("feat: search")
        cls.v1 = corrections(toml_row(commit=cls.login))
        repo.commit("chore: corrections\n\nNo-story: ledger", {CORR: cls.v1})
        repo.publish()
        cls.base = repo.sha()

    def later(self, text: str | None) -> dict:
        """A later trunk commit writes `text` to the file (None: removes it); returns `check --json`."""
        repo = self.repo
        repo.git("reset", "-q", "--hard", self.base)
        if text is None:
            repo.git("rm", "-q", CORR)
            repo.git("commit", "-q", "-m", "chore: drop corrections\n\nNo-story: ledger", when=repo.next_date())
        else:
            repo.commit("chore: corrections again\n\nNo-story: ledger", {CORR: text})
        repo.git("push", "-q", "-f", "origin", "main")
        repo.git("fetch", "-q", "--prune", "origin")
        return ledger_check(self, repo)

    def assert_edited(self, data: dict) -> None:
        self.assertIn("CORRECTION_EDITED", codes(data, "error"), data["diffs"])
        detail = details(data, "CORRECTION_EDITED")
        self.assertIn("UXC-113", detail)
        self.assertIn(self.login[:7], detail)

    def test_LEDGER_004_S5_INV_008_editing_a_row_on_the_trunk_is_correction_edited(self):
        self.assert_edited(self.later(corrections(toml_row(commit=self.login, evidence="something else"))))

    def test_LEDGER_004_S5_INV_008_removing_a_row_is_correction_edited(self):
        self.assert_edited(self.later(CORR_HEADER))

    def test_LEDGER_004_S5_INV_008_removing_the_whole_file_is_correction_edited(self):
        self.assert_edited(self.later(None))

    def test_LEDGER_004_S5_INV_008_appending_a_row_is_no_edit(self):
        data = self.later(self.v1 + toml_row(story="UXC-114", commit=self.search))
        self.assertNotIn("CORRECTION_EDITED", codes(data), data["diffs"])
        self.assertIs(self.stories(self.repo)["UXC-114"]["reconstructed"], True)

    def test_LEDGER_004_S5_logic_the_same_table_rewritten_is_no_edit(self):
        same = (CORR_HEADER + "# reordered and respaced\n[[row]]\n"
                f'date="2026-11-25"\napprover = "Leo"\nevidence =    "train sheet 18; BOARD.md row T18"\n'
                f"kind = 'backfill'\ncommit = \"{self.login}\"\nstory = \"UXC-113\"\n")
        data = self.later(same)
        self.assertNotIn("CORRECTION_EDITED", codes(data), data["diffs"])


class LedgerCorrectionsPartialCloneTest(LedgerCase):
    def test_LEDGER_004_S5_a_partial_clone_without_an_earlier_version_warns_and_never_fetches(self):
        repo = GitRepo(self.tmp)
        repo.plan("UXC-113", "UXC-114")
        login = repo.commit("feat: the login form")
        search = repo.commit("feat: search")
        v1 = repo.commit("chore: corrections\n\nNo-story: ledger", {CORR: corrections(toml_row(commit=login))})
        repo.commit("chore: more corrections\n\nNo-story: ledger",
                    {CORR: corrections(toml_row(commit=login), toml_row(story="UXC-114", commit=search))})
        repo.publish()
        old_blob = repo.git("rev-parse", f"{v1}:{CORR}").strip()
        repo.run(["git", "config", "uploadpack.allowFilter", "true"], repo.bare)
        dest = self.tmp / "partial"
        repo.run(["git", "clone", "-q", "--filter=blob:none", f"file://{repo.bare}", str(dest)], self.tmp)
        clone = GitRepo(self.tmp, existing=dest)
        missing = clone.git("rev-list", "--objects", "--all", "--missing=print")
        self.assertIn(f"?{old_blob}", missing.split(), "fixture: the first version's blob is not in the clone")
        log = self.tmp / "upload-pack.log"
        log.touch()
        server = self.tmp / "logging-upload-pack"
        server.write_text(f'#!/bin/sh\necho called >> "{log}"\nexec git-upload-pack "$@"\n')
        server.chmod(0o755)
        clone.git("config", "remote.origin.uploadpack", str(server))
        data = ledger_check(self, clone)
        self.assertEqual(log.read_text(), "", "ledger.py check fetched from origin: a missing blob is never fetched")
        self.assertIn("CORRECTION_UNCHECKED", codes(data, "warning"), data["diffs"])
        self.assertNotIn("CORRECTION_EDITED", codes(data))


class LedgerCorrectionsAcceptTest(LedgerCase):
    """`backfill --accept`: a person in their terminal (S3: never without one) appends the proposed rows with
    approver = git config user.name and today's date, never rewriting the bytes already there."""

    def repo(self) -> tuple[GitRepo, str]:
        repo = GitRepo(self.tmp)
        repo.plan("UXC-113", "UXC-114")
        c = repo.commit("feat: login form for UXC-113")
        repo.publish()
        return repo, c

    @staticmethod
    def write_proposed(repo: GitRepo, *rows: str) -> None:
        repo.write(PROPOSED, "".join(rows))

    def test_LEDGER_004_S3_accept_refuses_when_stdin_is_not_a_terminal(self):
        repo, _ = self.repo()
        propose(self, repo)
        r = repo.ledger("backfill", "--accept")  # stdin /dev/null, stdout a pipe: an agent
        self.assertNotIn("Traceback", r.stderr)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertFalse((repo.path / CORR).exists(), "nothing written")
        self.assertTrue((repo.path / PROPOSED).exists(), "the proposal is kept")

    def test_LEDGER_004_S3_accept_refuses_when_stdout_is_not_a_terminal(self):
        repo, _ = self.repo()
        propose(self, repo)
        master, slave = os.openpty()
        try:
            os.write(master, b"y\n")
            r = subprocess.run(["python3", ".keelokit/bin/ledger.py", "backfill", "--accept"], cwd=repo.path,
                               env=person_env(repo.tmp), stdin=slave, capture_output=True, text=True, timeout=60)
        finally:
            os.close(slave)
            os.close(master)
        self.assertNotIn("Traceback", r.stderr)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertFalse((repo.path / CORR).exists(), "nothing written")

    def test_LEDGER_004_S4_a_person_accepts_in_a_terminal_and_the_story_is_reconstructed(self):
        repo, c = self.repo()
        _, rows = propose(self, repo)
        self.assertEqual([(r["story"], r["commit"]) for r in rows], [("UXC-113", c)], "fixture")
        before = today_dates()
        code, out = run_in_pty(repo, "backfill", "--accept", answer="y\n")
        dates = before | today_dates()
        self.assertNotIn("Traceback", out)
        self.assertEqual(code, 0, out)
        self.assertIn("Accept 1", out)
        self.assertIn("[y/N]", out)
        self.assertIn("git -c keelokit.allowTamper=true commit", out, "it prints the commit command")
        text = (repo.path / CORR).read_text()
        self.assertTrue(text.startswith("#"), "a new file starts with its header")
        [row] = corrections_rows(repo)
        self.assertEqual(set(row), ROW_KEYS, "confidence is dropped")
        self.assertEqual((row["story"], row["commit"], row["kind"]), ("UXC-113", c, "backfill"))
        self.assertEqual(row["evidence"], rows[0]["evidence"])
        self.assertEqual(row["approver"], "T", "git config user.name")
        self.assertIn(row["date"], dates)
        self.assertFalse((repo.path / PROPOSED).exists(), "the proposed file is removed")
        repo.git("add", CORR)
        repo.git("-c", "keelokit.allowTamper=true", "commit", "-q", "-m", "chore: corrections\n\nNo-story: ledger")
        repo.publish()
        s = self.stories(repo)["UXC-113"]
        self.assertIs(s["reconstructed"], True)
        self.assertEqual(s["commit"], c)
        self.assertEqual(s["correction"]["approver"], "T")
        self.assertEqual(ledger_check(self, repo)["diffs"], [])

    def test_LEDGER_004_logic_accept_sets_approver_and_date_itself(self):
        repo, c = self.repo()
        self.write_proposed(repo, toml_row(commit=c, approver="Mallory", date="2020-01-01", confidence="high"))
        before = today_dates()
        code, out = run_in_pty(repo, "backfill", "--accept", answer="y\n")
        self.assertEqual(code, 0, out)
        [row] = corrections_rows(repo)
        self.assertEqual(row["approver"], "T", "an approver in the proposed row is ignored")
        self.assertIn(row["date"], before | today_dates(), "a date in the proposed row is ignored")
        self.assertNotIn("confidence", row)

    def test_LEDGER_004_INV_008_accept_appends_without_rewriting_and_skips_an_active_row(self):
        repo, c = self.repo()
        old = (corrections(toml_row(commit=c)) + "# a person's note, kept byte for byte  \n").encode()
        repo.commit("chore: corrections\n\nNo-story: ledger", {CORR: old.decode()})
        repo.publish()
        self.write_proposed(repo, toml_row(commit=c, approver=None, date=None, confidence="medium"),
                            toml_row(story="UXC-114", commit=c, kind="late", evidence="slipped through",
                                     approver=None, date=None))
        code, out = run_in_pty(repo, "backfill", "--accept", answer="y\n")
        self.assertEqual(code, 0, out)
        new = (repo.path / CORR).read_bytes()
        self.assertTrue(new.startswith(old), "the bytes already there are never rewritten")
        rows = corrections_rows(repo)
        self.assertEqual(sum((r["story"], r["commit"], r["kind"]) == ("UXC-113", c, "backfill") for r in rows), 1,
                         "a row identical to an active one is skipped")
        [late] = [r for r in rows if r["story"] == "UXC-114"]
        self.assertEqual((late["kind"], late["approver"], late["evidence"]), ("late", "T", "slipped through"))

    def test_LEDGER_004_logic_only_y_or_yes_writes(self):
        repo, c = self.repo()
        for answer in ("n\n", "\n", "sure\n"):
            with self.subTest(answer=answer):
                self.write_proposed(repo, toml_row(commit=c, approver=None, date=None, confidence="medium"))
                code, out = run_in_pty(repo, "backfill", "--accept", answer=answer)
                self.assertNotIn("Traceback", out)
                self.assertFalse((repo.path / CORR).exists(), out)
        self.write_proposed(repo, toml_row(commit=c, approver=None, date=None, confidence="medium"))
        code, out = run_in_pty(repo, "backfill", "--accept", answer="yes\n")
        self.assertEqual(code, 0, out)
        self.assertEqual(len(corrections_rows(repo)), 1)

    def test_LEDGER_004_dx_accept_refuses_without_a_git_user_name(self):
        repo, c = self.repo()
        for how in (("config", "user.name", ""), ("config", "--unset", "user.name")):
            with self.subTest(how=how):
                repo.git(*how)
                self.write_proposed(repo, toml_row(commit=c, approver=None, date=None, confidence="medium"))
                code, out = run_in_pty(repo, "backfill", "--accept", answer="y\n")
                self.assertNotIn("Traceback", out)
                self.assertEqual(code, 1, out)
                self.assertFalse((repo.path / CORR).exists())

    def test_LEDGER_004_dx_accept_refuses_a_missing_or_empty_proposal(self):
        repo, _ = self.repo()
        for text in (None, "", "# nothing proposed\n"):
            with self.subTest(text=text):
                (repo.path / PROPOSED).unlink(missing_ok=True)
                if text is not None:
                    repo.write(PROPOSED, text)
                code, out = run_in_pty(repo, "backfill", "--accept", answer="y\n")
                self.assertNotIn("Traceback", out)
                self.assertEqual(code, 1, out)
                self.assertFalse((repo.path / CORR).exists())

    def test_LEDGER_004_S6_accept_refuses_an_invalid_proposed_row(self):
        repo, c = self.repo()
        side = repo.on_branch("side", "feat: never merged")[0]
        for why, bad in {"unknown story": toml_row(story="NOPE-9", commit=c),
                         "unreachable commit": toml_row(commit=side),
                         "short sha": toml_row(commit=c[:7]),
                         "unknown kind": toml_row(commit=c, kind="fix")}.items():
            with self.subTest(why):
                self.write_proposed(repo, toml_row(story="UXC-114", commit=c), bad)
                code, out = run_in_pty(repo, "backfill", "--accept", answer="y\n")
                self.assertNotIn("Traceback", out)
                self.assertEqual(code, 1, out)
                self.assertFalse((repo.path / CORR).exists(), "nothing written, not even the valid row")


class LedgerCorrectionsCorrectTest(LedgerCase):
    """`correct <commit> --story <ID> --evidence "…"` proposes one late row for a commit that slipped through."""

    def repo(self) -> tuple[GitRepo, dict]:
        repo = GitRepo(self.tmp)
        repo.plan("UXC-113", "UXC-114")
        c = {"fix": repo.commit("fix: the login button"), "other": repo.commit("feat: UXC-114 search")}
        c["side"] = repo.on_branch("side", "feat: never merged")[0]
        repo.publish()
        return repo, c

    def correct(self, repo: GitRepo, *args: str) -> subprocess.CompletedProcess:
        r = repo.ledger("correct", *args)
        self.assertNotIn("Traceback", r.stderr)
        return r

    def test_LEDGER_004_logic_correct_appends_a_late_row_with_the_full_sha(self):
        repo, c = self.repo()
        r = self.correct(repo, "HEAD~1", "--story", "UXC-113", "--evidence", "slipped through without a trailer")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        [row] = proposed_rows(repo)
        self.assertEqual((row["story"], row["commit"], row["kind"]), ("UXC-113", c["fix"], "late"))
        self.assertEqual(row["evidence"], "slipped through without a trailer")
        self.assertIn(row.get("confidence", "high"), ("high",))
        self.assertFalse((repo.path / CORR).exists())

    def test_LEDGER_004_logic_correct_keeps_the_rows_already_proposed(self):
        repo, c = self.repo()
        _, rows = propose(self, repo)
        self.assertEqual([r["story"] for r in rows], ["UXC-114"], "fixture")
        r = self.correct(repo, c["fix"][:10], "--story", "UXC-113", "--evidence", "the PR says so")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        rows = proposed_rows(repo)
        self.assertEqual([(r["story"], r["kind"]) for r in rows], [("UXC-114", "backfill"), ("UXC-113", "late")])

    def test_LEDGER_004_S6_correct_refuses_an_unreachable_commit_an_unknown_story_or_no_evidence(self):
        repo, c = self.repo()
        for why, args in {"unreachable": (c["side"], "--story", "UXC-113", "--evidence", "x"),
                          "unknown story": (c["fix"], "--story", "NOPE-9", "--evidence", "x"),
                          "empty evidence": (c["fix"], "--story", "UXC-113", "--evidence", "")}.items():
            with self.subTest(why):
                r = self.correct(repo, *args)
                self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                self.assertFalse((repo.path / PROPOSED).exists() and proposed_rows(repo), "nothing proposed")

    def test_LEDGER_004_S4_a_late_row_accepted_reconstructs_the_story(self):
        repo, c = self.repo()
        self.assertEqual(self.correct(repo, c["fix"], "--story", "UXC-113", "--evidence", "slipped").returncode, 0)
        code, out = run_in_pty(repo, "backfill", "--accept", answer="y\n")
        self.assertEqual(code, 0, out)
        repo.git("add", CORR)
        repo.git("-c", "keelokit.allowTamper=true", "commit", "-q", "-m", "chore: late row\n\nNo-story: ledger")
        repo.publish()
        s = self.stories(repo)["UXC-113"]
        self.assertIs(s["reconstructed"], True)
        self.assertEqual(s["correction"]["kind"], "late")


class LedgerCorrectionsUsageTest(LedgerCase):
    def test_LEDGER_004_dx_other_spellings_print_the_usage_and_exit_2(self):
        repo = GitRepo(self.tmp)
        repo.plan("UXC-113")
        repo.publish()
        for args in (["backfill"], ["backfill", "--nope"], ["backfill", "--propose", "--from"], ["correct"],
                     ["correct", "HEAD"], ["check", "--nope"], ["checks"]):
            with self.subTest(args=args):
                r = repo.ledger(*args)
                self.assertNotIn("Traceback", r.stderr)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)



# ── LEDGER-004, review round 1: what got past the first tests (ESC-092..095) ──


class LedgerCorrectionsReviewAcceptTest(LedgerCase):
    def test_LEDGER_004_S3_accept_refuses_claude_codes_own_shell_even_under_a_pty(self):
        """ESC-092: an agent can give the accept a terminal (`script`, `unbuffer`, tmux); Claude Code's shell
        sets CLAUDECODE, and there `backfill --accept` refuses: exit 1, nothing written."""
        repo = GitRepo(self.tmp)
        repo.plan("UXC-113")
        c = repo.commit("feat: login form for UXC-113")
        repo.publish()
        repo.write(PROPOSED, toml_row(commit=c, approver=None, date=None, confidence="medium"))
        code, out = run_in_pty(repo, "backfill", "--accept", answer="y\n", extra_env={"CLAUDECODE": "1"})
        self.assertNotIn("Traceback", out)
        self.assertEqual(code, 1, out)
        self.assertIn("terminal", out.lower(), "it says a person's terminal is needed")
        self.assertFalse((repo.path / CORR).exists(), "nothing written")
        self.assertTrue((repo.path / PROPOSED).exists(), "the proposal is kept")


class LedgerCorrectionsReviewProposeTest(LedgerCase):
    """ESC-093: a revert commit is no evidence that a story shipped, and a commit's own Part-of: trailer is
    work in progress, not a candidate."""

    @classmethod
    def setUpClass(cls):
        repo = cls.repo = GitRepo(cls.class_tmp())
        repo.plan("UXC-113", "UXC-114", "UXC-115")
        c = cls.c = {}
        c["s113"] = repo.commit("feat: UXC-113 login")
        c["r113"] = repo.revert(c["s113"])  # 'Revert "feat: UXC-113 login"' names the id in its subject
        c["other"] = repo.commit("feat: unrelated")
        c["r115"] = repo.commit(f"fix: undo the UXC-115 tweak\n\nThis reverts commit {c['other']}.")
        c["p114"] = repo.commit("wip: the search box\n\nPart-of: UXC-114")
        repo.publish()

    def rows(self) -> dict:
        cls = type(self)
        if "_rows" not in cls.__dict__:
            _, rows = propose(self, cls.repo)
            cls._rows = {row["story"]: row for row in rows}
        return cls._rows

    def test_LEDGER_004_S1_ESC_093_a_revert_commit_is_never_a_candidate(self):
        self.assertNotIn("UXC-113", self.rows(), f"the revert {self.c['r113'][:7]} is no evidence")
        self.assertNotIn("UXC-115", self.rows(), "a body with 'This reverts commit <sha>.' is a revert")

    def test_LEDGER_004_S1_ESC_093_ids_in_a_commits_own_part_of_trailer_are_no_candidates(self):
        self.assertNotIn("UXC-114", self.rows())


class LedgerCorrectionsReviewAppendOnlyTest(LedgerCase):
    """ESC-094 and ESC-095 (INV-008): a row removed or rewritten through a merge that is fast-forwarded onto
    the trunk (a foxtrot merge) is CORRECTION_EDITED, and so is a reordering; a normal PR merge is not."""

    def setUp(self):
        super().setUp()
        repo = self.repo = GitRepo(self.tmp)
        repo.plan("UXC-113", "UXC-114", "UXC-115")
        self.login = repo.commit("feat: the login form")
        self.search = repo.commit("feat: search")
        self.export = repo.commit("feat: export")
        repo.publish()

    def corr(self, message: str, *rows: str) -> str:
        return self.repo.commit(f"{message}\n\nNo-story: ledger", {CORR: corrections(*rows)})

    def foxtrot(self, merged_text: str | None) -> dict:
        """main accepts a row; feat (from before it) merges main with --no-commit, changes the file to
        `merged_text` (None: removes it) and commits; main is fast-forwarded to feat."""
        repo = self.repo
        before = repo.sha()
        self.corr("chore: accept row", toml_row(commit=self.login))
        repo.publish()
        repo.git("checkout", "-q", "-b", "feat", before)
        repo.commit("feat: work on feat")
        repo.git("merge", "-q", "--no-ff", "--no-commit", "main", check=False)
        if merged_text is None:
            repo.git("rm", "-q", "-f", CORR)
        else:
            repo.write(CORR, merged_text)
            repo.git("add", CORR)
        repo.git("commit", "-q", "-m", "Merge main into feat\n\nNo-story: release", when=repo.next_date())
        repo.git("checkout", "-q", "main")
        repo.git("merge", "-q", "--ff-only", "feat")
        repo.publish()
        return ledger_check(self, repo)

    def test_LEDGER_004_S5_ESC_094_a_row_deleted_through_a_foxtrot_merge_is_correction_edited(self):
        data = self.foxtrot(None)
        self.assertIn("CORRECTION_EDITED", codes(data, "error"), data["diffs"])

    def test_LEDGER_004_S5_ESC_094_a_row_rewritten_through_a_foxtrot_merge_is_correction_edited(self):
        data = self.foxtrot(corrections(toml_row(commit=self.login, evidence="rewritten on feat")))
        self.assertIn("CORRECTION_EDITED", codes(data, "error"), data["diffs"])

    def test_LEDGER_004_S5_logic_a_pr_that_edits_its_own_new_row_before_merging_is_no_edit(self):
        repo = self.repo
        self.corr("chore: row A", toml_row(commit=self.login))
        repo.publish()
        repo.git("checkout", "-q", "-b", "feat")
        self.corr("chore: row B", toml_row(commit=self.login), toml_row(story="UXC-114", commit=self.search))
        self.corr("chore: row B, fixed", toml_row(commit=self.login),
                  toml_row(story="UXC-114", commit=self.search, evidence="fixed before review"))
        repo.git("checkout", "-q", "main")
        repo.merge("feat", "Merge feat\n\nNo-story: release")
        repo.publish()
        data = ledger_check(self, repo)
        self.assertNotIn("CORRECTION_EDITED", codes(data), data["diffs"])

    def test_LEDGER_004_S5_logic_a_row_that_arrived_through_a_merge_is_checked(self):
        repo = self.repo
        repo.git("checkout", "-q", "-b", "feat")
        self.corr("chore: row A", toml_row(commit=self.login))
        repo.git("checkout", "-q", "main")
        repo.merge("feat", "Merge feat\n\nNo-story: release")
        self.corr("chore: rewrite", toml_row(commit=self.login, evidence="rewritten on main"))
        repo.publish()
        data = ledger_check(self, repo)
        self.assertIn("CORRECTION_EDITED", codes(data, "error"), data["diffs"])

    def test_LEDGER_004_S5_ESC_095_reordering_rows_is_correction_edited(self):
        backfill = toml_row(commit=self.login)
        retract = toml_row(commit=self.login, kind="retract", evidence="wrong commit")
        self.corr("chore: v1", backfill)
        self.corr("chore: v2", backfill, retract)
        self.corr("chore: v3 reordered", retract, backfill)  # now the backfill is active again
        self.repo.publish()
        data = ledger_check(self, self.repo)
        self.assertIn("CORRECTION_EDITED", codes(data, "error"), data["diffs"])

    def test_LEDGER_004_S5_logic_two_branches_appending_different_rows_merged_is_no_edit(self):
        repo = self.repo
        a = toml_row(commit=self.login)
        b = toml_row(story="UXC-114", commit=self.search)
        c = toml_row(story="UXC-115", commit=self.export)
        self.corr("chore: row A", a)
        base = repo.sha()
        repo.git("checkout", "-q", "-b", "b1")
        self.corr("chore: row B", a, b)
        repo.git("checkout", "-q", "-b", "b2", base)
        self.corr("chore: row C", a, c)
        repo.git("checkout", "-q", "main")
        repo.merge("b1", "Merge b1\n\nNo-story: release")
        repo.git("merge", "-q", "--no-ff", "--no-commit", "b2", check=False)  # both appended: a conflict
        repo.write(CORR, corrections(a, b, c))
        repo.git("add", "-A")
        repo.git("commit", "-q", "-m", "Merge b2\n\nNo-story: release", when=repo.next_date())
        repo.publish()
        data = ledger_check(self, repo)
        self.assertNotIn("CORRECTION_EDITED", codes(data), data["diffs"])
        self.assertEqual(codes(data), [], data["diffs"])

    def test_LEDGER_004_S5_ESC_095_a_tip_that_is_not_toml_is_invalid_and_edited(self):
        for why, tip in {"not TOML": "[[row]\nstory = \n", "row is not a list": 'row = "x"\n'}.items():
            with self.subTest(why):
                self.repo.git("reset", "-q", "--hard", "origin/main")
                self.corr("chore: row A", toml_row(commit=self.login))
                self.repo.commit("chore: broken\n\nNo-story: ledger", {CORR: CORR_HEADER + tip})
                self.repo.git("push", "-q", "-f", "origin", "main")
                self.repo.git("fetch", "-q", "--prune", "origin")
                data = ledger_check(self, self.repo)
                self.assertIn("CORRECTION_INVALID", codes(data, "error"), data["diffs"])
                self.assertIn("CORRECTION_EDITED", codes(data, "error"), data["diffs"])
                self.repo.git("reset", "-q", "--hard", f"origin/main~2")
                self.repo.git("push", "-q", "-f", "origin", "main")
                self.repo.git("fetch", "-q", "--prune", "origin")

    def test_LEDGER_004_S6_a_date_that_is_no_calendar_date_is_correction_invalid(self):
        self.corr("chore: row", toml_row(commit=self.login, date="2026-99-99"))
        self.repo.publish()
        data = ledger_check(self, self.repo)
        self.assertIn("CORRECTION_INVALID", codes(data, "error"), data["diffs"])
        self.assertIs(self.stories(self.repo)["UXC-113"]["reconstructed"], False)


class LedgerCorrectionsBudgetTest(LedgerCase):
    """A fixed number of git calls (docs/ledger.md, "Performance and trust"): the corrections file's history,
    merges included, never costs one call per version."""

    def counted(self, repo: GitRepo) -> int:
        bindir = repo.tmp / f"shim-{repo.path.name}"
        bindir.mkdir()
        log = repo.tmp / f"argv-{repo.path.name}.log"
        log.touch()
        real = shutil.which("git", path=clean_env(repo.tmp)["PATH"])
        (bindir / "git").write_text(f'#!/bin/sh\nprintf \'%s\\n\' "$*" >> "{log}"\nexec "{real}" "$@"\n')
        (bindir / "git").chmod(0o755)
        r = repo.ledger("--json", path=f"{bindir}{os.pathsep}{clean_env(repo.tmp)['PATH']}")
        self.assertIn(r.returncode, (0, 1), r.stderr)
        self.assertNotIn("CORRECTION_EDITED", r.stdout)
        self.calls = getattr(self, "calls", []) + [log.read_text()]
        return len(log.read_text().splitlines())

    def build(self, name: str, versions: int) -> GitRepo:
        repo = GitRepo(self.tmp, name=name)
        repo.plan("UXC-113")
        shas = [repo.commit(f"feat: part {n}") for n in range(versions)]
        rows: list[str] = []
        for n, sha in enumerate(shas):
            rows.append(toml_row(commit=sha, evidence=f"part {n}"))
            if n % 3 == 2:  # every third version arrives through a --no-ff merge
                repo.git("checkout", "-q", "-b", f"rows-{n}")
                repo.commit(f"chore: row {n}\n\nNo-story: ledger", {CORR: corrections(*rows)})
                repo.git("checkout", "-q", "main")
                repo.merge(f"rows-{n}", f"Merge rows-{n}\n\nNo-story: release")
            else:
                repo.commit(f"chore: row {n}\n\nNo-story: ledger", {CORR: corrections(*rows)})
        repo.git("checkout", "-q", "-b", "side")  # both repos hold a merge that does not touch the file
        repo.commit("feat: side work")
        repo.git("checkout", "-q", "main")
        repo.merge("side", "Merge side\n\nNo-story: release")
        repo.publish()
        return repo

    def test_LEDGER_004_nfr_git_calls_do_not_grow_with_the_versions_of_the_corrections_file(self):
        one = self.counted(self.build("one", 1))
        thirty = self.counted(self.build("thirty", 30))
        self.assertEqual(thirty, one, "30 versions (some through merges) cost the git calls of 1\n"
                         + "\n---\n".join(self.calls))



class LedgerCorrectionsNestedFoxtrotTest(LedgerCase):
    def test_LEDGER_004_S5_ESC_098_INV_008_a_row_removed_through_a_nested_foxtrot_merge_is_correction_edited(self):
        """ESC-098 (fixture n1b): the removal happens in a merge on feat2, feat merges feat2 with --no-ff and
        main is fast-forwarded to feat: the merge that dropped the row is not a direct parent of a
        first-parent merge, yet no row on the trunk may disappear."""
        repo = GitRepo(self.tmp)
        repo.plan("UXC-113")
        login = repo.commit("feat: the login form")
        repo.publish()
        before = repo.sha()
        repo.commit("chore: accept row\n\nNo-story: ledger", {CORR: corrections(toml_row(commit=login))})
        repo.publish()
        repo.git("branch", "feat", before)
        repo.git("checkout", "-q", "-b", "feat2", before)
        repo.commit("feat: work on feat2")
        repo.git("merge", "-q", "--no-ff", "--no-commit", "main", check=False)
        repo.git("rm", "-q", "-f", CORR)
        repo.git("commit", "-q", "-m", "Merge main into feat2\n\nNo-story: release", when=repo.next_date())
        repo.git("checkout", "-q", "feat")
        repo.commit("feat: work on feat")
        repo.merge("feat2", "Merge feat2\n\nNo-story: release")
        repo.git("checkout", "-q", "main")
        repo.git("merge", "-q", "--ff-only", "feat")
        repo.publish()
        self.assertFalse(repo.git("ls-tree", "origin/main", "--", CORR).strip(), "fixture: the row is gone from main")
        data = ledger_check(self, repo)
        self.assertIn("CORRECTION_EDITED", codes(data, "error"), data["diffs"])

# ── LEDGER-015: corrections approved by agents, with an adversarial review, when the person delegates it ──
# The approval mode is read from the trunk's committed .keelokit/state.toml (D1); GitRepo excludes /.keelokit/,
# so the harness files are committed with `git add -f` (commit_harness).

STATE = ".keelokit/state.toml"
CRITICAL = ".keelokit/critical.toml"
REVIEWS = ".keelokit/ledger-reviews"
RUN_ID = re.compile(r"r[0-9a-f]{12}")
CRITICAL_TOML = '[[area]]\nname = "payments"\nwhy = "money moves"\npaths = ["apps/api/pay/charge.ts"]\n'
# The stories of the delegated fixtures: id -> (touches, dimensions). UXC-303 touches a critical area,
# UXC-304 declares integrity.
DELEGATED_STORIES = {"UXC-301": ("apps/api/login/", "logic"), "UXC-302": ("apps/api/search/", "logic"),
                     "UXC-303": ("apps/api/pay/", "logic"), "UXC-304": ("apps/api/ledger/", "integrity"),
                     "UXC-305": ("apps/api/export/", "logic"), "UXC-306": ("apps/api/misc/", "logic")}


def story15(sid: str, touches: tuple = (), dimensions: tuple = ("logic",)) -> str:
    """A story with `touches` and `dimensions` in its front matter (the filter and the critical flag read them)."""
    t = ", ".join(json.dumps(p) for p in touches)
    d = ", ".join(json.dumps(x) for x in dimensions)
    return (f'+++\nid = "{sid}"\nepic = "{sid.split("-")[0]}"\ntitle = "Title of {sid}"\nwave = 1\n'
            f'depends_on = []\ntouches = [{t}]\ndimensions = [{d}]\n+++\n# Title of {sid}\n\n'
            '```gherkin\nScenario: [S1] works\n```\n')


def approval(mode: str | None = None, human_for: list | None = None, sample: float | None = None) -> str:
    """state.toml text: a [ledger] table, and [ledger.approval] when a mode is given."""
    text = '[ledger]\ntrunk = "main"\n'
    if mode is not None:
        text += f"\n[ledger.approval]\nmode = {json.dumps(mode)}\n"
        if human_for is not None:
            text += f"human_for = {json.dumps(human_for)}\n"
        if sample is not None:
            text += f"sample = {sample!r}\n"
    return text


def commit_harness(repo: GitRepo, message: str, files: dict) -> str:
    """A trunk commit of `files`, harness files included (`git add -f`: /.keelokit/ is excluded in GitRepo)."""
    for rel, text in files.items():
        repo.write(rel, text)
    repo.git("add", "-A")
    repo.git("add", "-f", *files)
    repo.git("commit", "-q", "-m", message, when=repo.next_date())
    return repo.sha()


def verdicts(a: str = "yes", b: str = "yes", refuted: bool | None = False, model: str | None = None) -> dict:
    """judge_a, judge_b and skeptic of one review row; refuted None leaves the skeptic out (null)."""
    m = {"model": model} if model else {}
    return {"judge_a": {"verdict": a, "reason": "S1 is proven by apps/api/x.ts", **m},
            "judge_b": {"verdict": b, "reason": "the diff implements S1", **m},
            "skeptic": None if refuted is None else {"refuted": refuted, "reason": "tried the revert and the scope",
                                                     **m}}


def review_row(story: str, commit: str, evidence: str = "EV", decision: str | None = "approved", **v) -> dict:
    row = {"story": story, "commit": commit, "kind": "backfill", "evidence": evidence, "confidence": "medium",
           "critical": False, "title": f"Title of {story}", "path": f"backlog/stories/{story}-s.md", **verdicts(**v)}
    if decision is not None:
        row["decision"] = decision
    return row


def review_text(run: str, rows: list[dict], mode: str | None = "delegated") -> str:
    """A review file; `mode` is the recorded mode (round 1, ESC-114: a delegated row counts only when its review
    recorded delegated or mixed), None leaves it out."""
    data = {"schema": 1, "run": run, **({"mode": mode} if mode is not None else {}), "rows": rows, "dropped": []}
    if mode == "mixed":
        data["human_for"] = ["critical", "disagreement", "low-confidence"]
    return json.dumps(data, indent=1) + "\n"


def delegated_row(story: str, commit: str, run: str, evidence: str = "EV") -> str:
    return toml_row(story=story, commit=commit, evidence=evidence, approver=f"delegated:{run}", date="2026-11-25")


def proposed_row(story: str, commit: str, confidence: str = "medium", evidence: str | None = None,
                 kind: str = "backfill") -> str:
    return toml_row(story=story, commit=commit, kind=kind, confidence=confidence, approver=None, date=None,
                    evidence=f"{story}: diff of {commit[:7]}" if evidence is None else evidence)


def review_filter(test: unittest.TestCase, repo: GitRepo) -> dict:
    """`ledger.py review --filter`: JSON on stdout, exit 0 (D3)."""
    r = repo.ledger("review", "--filter")
    test.assertNotIn("Traceback", r.stderr)
    test.assertEqual(r.returncode, 0, f"ledger.py review --filter exited {r.returncode}\n{r.stdout}{r.stderr}")
    try:
        return json.loads(r.stdout)
    except ValueError:
        test.fail(f"ledger.py review --filter did not print JSON:\n{r.stdout[:2000]}")


def build_delegated(tmp: Path, state: str | None) -> tuple[GitRepo, dict]:
    """Six stories with touches, one commit on the trunk touching each story's path, critical.toml and (unless
    state is None) state.toml committed on the trunk, published."""
    repo = GitRepo(tmp)
    repo.commit("docs: plan\n\nNo-story: docs", {f"backlog/stories/{sid}-s.md": story15(sid, (path,), (dim,))
                                                 for sid, (path, dim) in DELEGATED_STORIES.items()})
    c = {sid: repo.commit(f"feat: work under {path}", {f"{path}x.ts": f"export const v = '{sid}'\n"})
         for sid, (path, _) in DELEGATED_STORIES.items()}
    files = {CRITICAL: CRITICAL_TOML}
    if state is not None:
        files[STATE] = state
    commit_harness(repo, "chore: harness\n\nNo-story: harness", files)
    repo.publish()
    return repo, c


def agent_env() -> dict:
    return {"CLAUDECODE": "1"}


class LedgerDelegatedFilterTest(LedgerCase):
    """S2 and D3: `review --filter` drops, with a reason and with no model, every row it can prove wrong; it keeps
    the rest with their critical flag, names a deterministic run, and writes nothing."""

    @classmethod
    def setUpClass(cls):
        repo = cls.repo = GitRepo(cls.class_tmp())
        stories = {"UXC-201": (("apps/api/login/",), ("logic",)), "UXC-202": (("apps/api/search/",), ("logic",)),
                   "UXC-203": ((), ("logic",)), "UXC-204": (("apps/api/pay/",), ("logic",)),
                   "UXC-205": ((), ("integrity",)), "UXC-206": (("apps/api/a6/",), ("logic",)),
                   "UXC-207": (("apps/api/login/",), ("logic",)), "UXC-208": (("apps/api/login/",), ("logic",))}
        repo.commit("docs: plan\n\nNo-story: docs",
                    {f"backlog/stories/{sid}-s.md": story15(sid, *tv) for sid, tv in stories.items()})
        c = cls.c = {}
        c["login"] = repo.commit("feat: the login form", {"apps/api/login/form.ts": "export {}\n"})
        c["elsewhere"] = repo.commit("docs: notes", {"docs/notes.md": "notes\n"})
        c["pay"] = repo.commit("feat: charge", {"apps/api/pay/charge.ts": "export {}\n"})
        c["s206"] = repo.commit("feat: UXC-206\n\nWhy.\n\nStory: UXC-206", {"apps/api/a6/x.ts": "export {}\n"})
        repo.git("checkout", "-q", "-b", "feat/search")
        repo.commit("feat: search", {"apps/api/search/q.ts": "export {}\n"})
        repo.git("checkout", "-q", "main")
        repo.commit("chore: the trunk moves", {"docs/other.md": "x\n"})
        c["merge"] = repo.merge("feat/search", "Merge branch 'feat/search'")
        c["side"] = repo.on_branch("side", "feat: never merged")[0]
        commit_harness(repo, "chore: harness\n\nNo-story: harness",
                       {STATE: approval("mixed"), CRITICAL: CRITICAL_TOML})
        repo.publish()
        cls.proposed = "".join([
            proposed_row("UXC-201", c["login"]),                        # kept: touches its path
            proposed_row("UXC-202", c["elsewhere"]),                    # dropped: diff outside touches
            proposed_row("UXC-201", c["side"]),                         # dropped: not on the trunk
            proposed_row("NOPE-9", c["login"]),                         # dropped: no such story
            proposed_row("UXC-201", c["login"], evidence="again"),      # dropped: duplicate (story, commit)
            proposed_row("UXC-206", c["login"]),                        # dropped: already on the trunk
            proposed_row("UXC-207", c["login"], evidence=""),           # dropped: empty evidence
            proposed_row("UXC-208", c["login"], kind="retract"),        # dropped: kind is not backfill|late
            proposed_row("UXC-203", c["elsewhere"]),                    # kept: the story has no touches
            proposed_row("UXC-204", c["pay"]),                          # kept, critical (critical.toml)
            proposed_row("UXC-205", c["elsewhere"], confidence="low"),  # kept, critical (integrity)
            proposed_row("UXC-202", c["merge"]),                        # kept: a merge, diffed to its first parent
        ])
        repo.write(PROPOSED, cls.proposed)

    def result(self) -> dict:
        cls = type(self)
        if "_result" not in cls.__dict__:
            cls._result = review_filter(self, cls.repo)
        return cls._result

    def kept(self) -> dict:
        return {(r["story"], r["commit"]): r for r in self.result()["rows"]}

    def test_LEDGER_015_S2_the_filter_keeps_rows_whose_commit_touches_the_story(self):
        c = self.c
        self.assertEqual(set(self.kept()), {("UXC-201", c["login"]), ("UXC-203", c["elsewhere"]),
                                            ("UXC-204", c["pay"]), ("UXC-205", c["elsewhere"]),
                                            ("UXC-202", c["merge"])}, self.result())

    def test_LEDGER_015_S2_the_filter_drops_what_it_can_prove_wrong_with_a_reason(self):
        c = self.c
        dropped = {(d["story"], d["commit"], d["kind"]): d for d in self.result()["dropped"]}
        for why, key in {"diff outside the story's touches": ("UXC-202", c["elsewhere"], "backfill"),
                         "commit not on the trunk": ("UXC-201", c["side"], "backfill"),
                         "unknown story": ("NOPE-9", c["login"], "backfill"),
                         "story already on the trunk": ("UXC-206", c["login"], "backfill"),
                         "empty evidence": ("UXC-207", c["login"], "backfill"),
                         "retract kind": ("UXC-208", c["login"], "retract")}.items():
            with self.subTest(why):
                self.assertIn(key, dropped, self.result()["dropped"])
                self.assertTrue(str(dropped[key].get("reason", "")).strip(), "each dropped row says why")
        self.assertEqual(sum(1 for d in self.result()["dropped"] if (d["story"], d["commit"]) == ("UXC-201", c["login"])),
                         1, "the duplicate of a kept row is dropped once, the first one is kept")
        self.assertEqual([r["evidence"] for r in self.result()["rows"] if r["story"] == "UXC-201"],
                         [f"UXC-201: diff of {c['login'][:7]}"], "the first of two identical rows is the one kept")

    def test_LEDGER_015_S2_the_filter_flags_critical_stories(self):
        flags = {k[0]: r["critical"] for k, r in self.kept().items()}
        self.assertEqual(flags, {"UXC-201": False, "UXC-203": False, "UXC-204": True, "UXC-205": True,
                                 "UXC-202": False}, "critical: touches a critical.toml area, or the integrity dimension")

    def test_LEDGER_015_S2_dx_the_filter_output_schema(self):
        d = self.result()
        self.assertEqual(d["schema"], 1)
        self.assertEqual(d["mode"], "mixed")
        self.assertEqual(d["human_for"], ["critical", "disagreement", "low-confidence"], "the default of mixed")
        self.assertEqual(d["sample"], 0.05, "the default sample")
        self.assertRegex(d["run"], RUN_ID.pattern)
        for row in d["rows"]:
            with self.subTest(row["story"]):
                self.assertLessEqual({"story", "commit", "kind", "evidence", "confidence", "critical", "title", "path"},
                                     set(row))
                self.assertEqual(row["path"], f"backlog/stories/{row['story']}-s.md")
                self.assertEqual(row["title"], f"Title of {row['story']}")
        self.assertEqual(self.kept()[("UXC-205", self.c["elsewhere"])]["confidence"], "low")

    def test_LEDGER_015_S2_the_run_id_is_deterministic_and_the_filter_writes_nothing(self):
        repo = self.repo
        first = self.result()["run"]
        again = review_filter(self, repo)
        self.assertEqual(again["run"], first, "no clock, no randomness: the same trunk and rows give the same run")
        self.assertEqual((repo.path / PROPOSED).read_text(), self.proposed, "the proposed file is untouched")
        self.assertFalse((repo.path / CORR).exists(), "nothing is approved")
        self.assertFalse((repo.path / REVIEWS).exists(), "the filter writes no review file")

    def test_LEDGER_015_dx_review_spellings_print_the_usage_and_exit_2(self):
        for args in (["review"], ["review", "--filter", "x"], ["review", "--reject-sample"], ["review", "--nope"],
                     ["backfill", "--accept", "--delegated"], ["backfill", "--accept", "--delegated", "r1", "x"],
                     ["backfill", "--delegated", "r1"]):
            with self.subTest(args=args):
                r = self.repo.ledger(*args, extra_env=agent_env())
                self.assertNotIn("Traceback", r.stderr)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)


class LedgerDelegatedAcceptCase(LedgerCase):
    """A fresh delegated fixture per test: propose rows, run the filter, write the review file with the judges'
    verdicts, then `backfill --accept --delegated <run>` as an agent (CLAUDECODE set, no terminal)."""

    def build(self, state: str | None) -> tuple[GitRepo, dict]:
        return build_delegated(self.tmp, state)

    def review(self, repo: GitRepo, rows: dict, extra: list[dict] = (), override: dict | None = None) -> str:
        """Propose `rows` (story -> commit), run the filter and write its rows to the review file with the verdicts
        of `override` (story -> verdicts kwargs, default all yes); `extra` rows are added as they are."""
        repo.write(PROPOSED, "".join(proposed_row(s, c) for s, c in rows.items()))
        d = review_filter(self, repo)
        run = d["run"]
        out = [{**r, **verdicts(**(override or {}).get(r["story"], {}))} for r in d["rows"]]
        repo.write(f"{REVIEWS}/{run}.json", review_text(run, out + list(extra)))
        return run

    def accept(self, repo: GitRepo, run: str) -> subprocess.CompletedProcess:
        r = repo.ledger("backfill", "--accept", "--delegated", run, extra_env=agent_env())
        self.assertNotIn("Traceback", r.stderr)
        return r

    def file(self, repo: GitRepo, run: str) -> dict:
        return json.loads((repo.path / REVIEWS / f"{run}.json").read_text())

    def decisions(self, repo: GitRepo, run: str) -> dict:
        return {r["story"]: r.get("decision") for r in self.file(repo, run)["rows"]}

    def land(self, repo: GitRepo, run: str) -> None:
        """Commit the rows and the review file to the trunk and publish (the workflow's Decide step)."""
        files = [f"{REVIEWS}/{run}.json"] + ([CORR] if (repo.path / CORR).exists() else [])
        repo.git("add", "-f", *files)
        repo.git("commit", "-q", "-m", f"chore: delegated review {run}\n\nNo-story: ledger", when=repo.next_date())
        repo.publish()

    def corr(self, repo: GitRepo) -> list[dict]:
        return corrections_rows(repo) if (repo.path / CORR).exists() else []

    def pending(self, repo: GitRepo) -> list[dict]:
        data = ledger_check(self, repo)
        self.assertEqual(codes(data, "error"), [], data["diffs"])
        return [d for d in data["diffs"] if d["code"] == "PENDING_REVIEW"]


class LedgerDelegatedDecisionTest(LedgerDelegatedAcceptCase):
    """S3–S6 and the decision table of D5: ledger.py computes each row's decision from the verdicts, the mode and
    the trunk (never from the file); only an approved row is written, as delegated:<run>."""

    def test_LEDGER_015_S3_INV_005_agreement_and_a_failed_refutation_approve_as_delegated(self):
        repo, c = self.build(approval("delegated"))
        run = self.review(repo, {"UXC-301": c["UXC-301"]})
        before = today_dates()
        r = self.accept(repo, run)
        dates = before | today_dates()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((repo.path / CORR).read_text().startswith("#"), "a new file starts with its header")
        [row] = corrections_rows(repo)
        self.assertEqual(set(row), ROW_KEYS)
        self.assertEqual((row["story"], row["commit"], row["kind"]), ("UXC-301", c["UXC-301"], "backfill"))
        self.assertEqual(row["approver"], f"delegated:{run}")
        self.assertIn(row["date"], dates)
        self.assertEqual(row["evidence"], f"UXC-301: diff of {c['UXC-301'][:7]}")
        f = self.file(repo, run)
        [rr] = f["rows"]
        self.assertEqual(rr["decision"], "approved")
        self.assertEqual((rr["judge_a"]["verdict"], rr["judge_b"]["verdict"], rr["skeptic"]["refuted"]),
                         ("yes", "yes", False), "the verdicts stay in the review file")
        self.assertEqual(f["mode"], "delegated")
        self.assertEqual(f["sample"], [{"story": "UXC-301", "commit": c["UXC-301"]}], "ceil(0.05 × 1) = 1 row")
        self.assertEqual(proposed_rows(repo) if (repo.path / PROPOSED).exists() else [], [],
                         "an approved row leaves the proposed file")
        self.land(repo, run)
        s = self.stories(repo)["UXC-301"]
        self.assertEqual(s["state"], "on-trunk")
        self.assertIs(s["reconstructed"], True)
        self.assertEqual(s["reconstructed_by"], "delegated")
        self.assertEqual(self.pending(repo), [])
        self.assertEqual(ledger_check(self, repo)["diffs"], [])

    def test_LEDGER_015_S3_INV_008_the_delegated_accept_appends_without_rewriting_and_skips_an_active_row(self):
        repo, c = self.build(approval("delegated"))
        old = corrections(toml_row(story="UXC-302", commit=c["UXC-302"])) + "# a person's note  \n"
        repo.commit("chore: corrections\n\nNo-story: ledger", {CORR: old})
        repo.publish()
        run = self.review(repo, {"UXC-301": c["UXC-301"]},
                          extra=[review_row("UXC-302", c["UXC-302"], decision=None)])
        r = self.accept(repo, run)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        new = (repo.path / CORR).read_text()
        self.assertTrue(new.startswith(old), "the bytes already there are never rewritten")
        rows = corrections_rows(repo)
        self.assertEqual([(x["story"], x["approver"]) for x in rows], [("UXC-302", "Leo"), ("UXC-301", f"delegated:{run}")],
                         "UXC-302 is already on the trunk: dropped or skipped, never written twice")

    def test_LEDGER_015_S4_disagreement_goes_to_the_persons_queue_in_mixed(self):
        repo, c = self.build(approval("mixed"))
        run = self.review(repo, {"UXC-301": c["UXC-301"]}, override={"UXC-301": {"a": "yes", "b": "no", "refuted": None}})
        r = self.accept(repo, run)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("UXC-301", r.stdout, "the person's queue is printed")
        self.assertEqual(self.corr(repo), [], "nothing is written")
        self.assertEqual(self.decisions(repo, run), {"UXC-301": "person"})
        self.assertEqual([(x["story"], x["commit"]) for x in proposed_rows(repo)], [("UXC-301", c["UXC-301"])],
                         "the row stays in the proposed file, for the person")
        self.land(repo, run)
        s = self.stories(repo)["UXC-301"]
        self.assertEqual(s["state"], "ready", "INV-005: the story is not on the trunk")
        self.assertIs(s["reconstructed"], False)
        pending = self.pending(repo)
        self.assertEqual(len(pending), 1, pending)
        self.assertEqual(pending[0]["level"], "warning")
        self.assertIn("UXC-301", pending[0]["detail"])

    def test_LEDGER_015_S5_a_refutation_stays_pending_in_delegated(self):
        repo, c = self.build(approval("delegated"))
        run = self.review(repo, {"UXC-301": c["UXC-301"], "UXC-302": c["UXC-302"]},
                          override={"UXC-301": {"refuted": True}, "UXC-302": {"a": "no", "b": "yes", "refuted": None}})
        r = self.accept(repo, run)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.corr(repo), [], "a refuted or disputed row is not written")
        self.assertEqual(self.decisions(repo, run), {"UXC-301": "pending", "UXC-302": "pending"})
        self.land(repo, run)
        s = self.stories(repo)
        self.assertEqual((s["UXC-301"]["state"], s["UXC-302"]["state"]), ("ready", "ready"))
        pending = self.pending(repo)
        self.assertEqual(sorted(sid for sid in ("UXC-301", "UXC-302") for d in pending if sid in d["detail"]),
                         ["UXC-301", "UXC-302"], pending)
        self.assertEqual(len(pending), 2, "one PENDING_REVIEW per story")
        self.assertTrue(all(d["level"] == "warning" for d in pending))

    def test_LEDGER_015_S6_a_critical_story_goes_to_the_person_in_mixed_whatever_the_judges_say(self):
        repo, c = self.build(approval("mixed"))
        run = self.review(repo, {"UXC-303": c["UXC-303"], "UXC-304": c["UXC-304"]},
                          override={s: {"model": "opus"} for s in ("UXC-303", "UXC-304")})
        f = self.file(repo, run)  # the review file says not critical: ledger.py reads the trunk, never the file
        for row in f["rows"]:
            row["critical"] = False
        repo.write(f"{REVIEWS}/{run}.json", json.dumps(f))
        r = self.accept(repo, run)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.decisions(repo, run), {"UXC-303": "person", "UXC-304": "person"},
                         "critical.toml area and the integrity dimension")
        self.assertEqual(self.corr(repo), [])

    def test_LEDGER_015_S6_a_critical_story_in_delegated_needs_opus_verdicts(self):
        repo, c = self.build(approval("delegated"))
        run = self.review(repo, {"UXC-303": c["UXC-303"], "UXC-304": c["UXC-304"]},
                          override={"UXC-303": {"model": "sonnet"}, "UXC-304": {"model": "opus"}})
        r = self.accept(repo, run)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.decisions(repo, run), {"UXC-303": "pending", "UXC-304": "approved"})
        self.assertEqual([x["story"] for x in self.corr(repo)], ["UXC-304"])

    def test_LEDGER_015_S2_a_row_the_filter_drops_is_never_approved_whatever_the_judges_say(self):
        repo, c = self.build(approval("delegated"))
        # UXC-302's touches are apps/api/search/; UXC-301's commit touches apps/api/login/ only.
        run = self.review(repo, {"UXC-301": c["UXC-301"]}, extra=[review_row("UXC-302", c["UXC-301"], decision=None)])
        repo.write(PROPOSED, proposed_row("UXC-301", c["UXC-301"]) + proposed_row("UXC-302", c["UXC-301"]))
        r = self.accept(repo, run)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual([x["story"] for x in self.corr(repo)], ["UXC-301"])
        self.assertEqual(self.decisions(repo, run)["UXC-302"], "dropped")
        left = proposed_rows(repo) if (repo.path / PROPOSED).exists() else []
        self.assertEqual(left, [], "approved and dropped rows leave the proposed file")

    def test_LEDGER_015_logic_mixed_low_confidence_and_human_for(self):
        """D5's mixed rows: low confidence goes to the person only when listed; a disagreement not listed is pending;
        an empty human_for lets agreeing judges approve a critical story."""
        cases = [(["critical", "disagreement", "low-confidence"], "UXC-301", {}, "low", "person"),
                 (["critical"], "UXC-301", {}, "low", "approved"),
                 (["critical"], "UXC-302", {"a": "no", "b": "yes", "refuted": None}, "medium", "pending"),
                 ([], "UXC-303", {}, "medium", "approved")]
        for human_for, story, v, confidence, expected in cases:
            with self.subTest(human_for=human_for, story=story, expected=expected):
                self.tmp = Path(tempfile.mkdtemp())
                self.addCleanup(shutil.rmtree, self.tmp, True)
                repo, c = self.build(approval("mixed", human_for=human_for))
                repo.write(PROPOSED, proposed_row(story, c[story], confidence=confidence))
                d = review_filter(self, repo)
                self.assertEqual(d["human_for"], human_for)
                run = d["run"]
                repo.write(f"{REVIEWS}/{run}.json", review_text(run, [{**x, **verdicts(**v)} for x in d["rows"]]))
                r = self.accept(repo, run)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertEqual(self.decisions(repo, run), {story: expected})
                self.assertEqual([x["story"] for x in self.corr(repo)], [story] if expected == "approved" else [])

    def test_LEDGER_015_logic_the_sample_is_the_first_rows_by_hash_of_the_run(self):
        repo, c = self.build(approval("delegated", sample=0.5))
        rows = {s: c[s] for s in ("UXC-301", "UXC-302", "UXC-305")}
        run = self.review(repo, rows)
        r = self.accept(repo, run)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        order = sorted(rows.items(), key=lambda sc: hashlib.sha256((run + sc[0] + sc[1]).encode()).hexdigest())
        self.assertEqual(self.file(repo, run)["sample"], [{"story": s, "commit": x} for s, x in order[:2]],
                         "ceil(0.5 × 3) = 2, ordered by sha256(run + story + commit)")

    def test_LEDGER_015_logic_a_malformed_review_is_refused_and_nothing_is_written(self):
        repo, c = self.build(approval("delegated"))
        run = self.review(repo, {"UXC-301": c["UXC-301"]})
        good = (repo.path / REVIEWS / f"{run}.json").read_text()
        proposed = (repo.path / PROPOSED).read_text()
        d = json.loads(good)
        no_b = json.loads(good)
        del no_b["rows"][0]["judge_b"]
        no_skeptic = json.loads(good)
        no_skeptic["rows"][0]["skeptic"] = None
        other_run = {**d, "run": "rother"}
        for why, text in {"not JSON": "{", "another run": json.dumps(other_run), "no judge_b": json.dumps(no_b),
                          "both yes and no skeptic": json.dumps(no_skeptic), "missing": None}.items():
            with self.subTest(why):
                path = repo.path / REVIEWS / f"{run}.json"
                if text is None:
                    path.unlink()
                else:
                    path.write_text(text)
                r = self.accept(repo, run)
                self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                self.assertFalse((repo.path / CORR).exists(), "nothing written")
                self.assertEqual((repo.path / PROPOSED).read_text(), proposed, "the proposal is kept")
        for bad in ("../evil", "a/b", ".hidden", "x" * 65):
            with self.subTest(run=bad):
                r = self.accept(repo, bad)
                self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                self.assertFalse((repo.path / CORR).exists())

    def test_LEDGER_015_D1_an_approval_only_in_the_work_tree_enables_nothing(self):
        repo, c = self.build(approval())
        repo.state(approval("delegated"))  # the agent's uncommitted edit
        run = self.review(repo, {"UXC-301": c["UXC-301"]})
        self.assertEqual(review_filter(self, repo)["mode"], "human", "the mode is the trunk's")
        r = self.accept(repo, run)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertFalse((repo.path / CORR).exists())

    def test_LEDGER_015_D1_an_invalid_mode_or_state_file_is_human(self):
        repo, c = self.build(approval("yolo"))
        run = self.review(repo, {"UXC-301": c["UXC-301"]})
        for why, text in {"unknown mode": None, "invalid TOML": "[ledger.approval\nmode = 'delegated'\n"}.items():
            with self.subTest(why):
                if text is not None:
                    commit_harness(repo, "chore: state\n\nNo-story: harness", {STATE: text})
                    repo.publish()
                self.assertEqual(review_filter(self, repo)["mode"], "human")
                r = self.accept(repo, run)
                self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                self.assertFalse((repo.path / CORR).exists())


class LedgerDelegatedHumanModeTest(LedgerDelegatedAcceptCase):
    """S9: without a [ledger.approval] table nothing changes: only a person accepts rows (LEDGER-004)."""

    def test_LEDGER_015_S9_without_delegation_the_delegated_accept_is_refused(self):
        repo, c = self.build(approval())
        run = self.review(repo, {"UXC-301": c["UXC-301"]})
        self.assertEqual(review_filter(self, repo)["mode"], "human")
        r = self.accept(repo, run)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("human", (r.stdout + r.stderr).lower(), "it says the project approves by a person")
        self.assertFalse((repo.path / CORR).exists())
        r = repo.ledger("backfill", "--accept", extra_env=agent_env())
        self.assertEqual(r.returncode, 1, "the person's accept still needs a person's terminal")
        self.assertFalse((repo.path / CORR).exists())

    def test_LEDGER_015_S9_a_delegated_row_without_its_review_file_is_correction_invalid(self):
        repo, c = self.build(None)
        repo.commit("chore: corrections\n\nNo-story: ledger", {CORR: corrections(delegated_row("UXC-301", c["UXC-301"], "rgone"))})
        repo.publish()
        data = ledger_check(self, repo)
        self.assertIn("CORRECTION_INVALID", codes(data, "error"), data["diffs"])
        self.assertIn("rgone", details(data, "CORRECTION_INVALID"))
        self.assertIs(self.stories(repo)["UXC-301"]["reconstructed"], False)


class LedgerDelegatedRecordTest(LedgerCase):
    """S7 and D6: who approved shows in the summary and the JSON; a delegated row counts only when its committed
    review file approves it (CORRECTION_INVALID otherwise, naming the run)."""

    @classmethod
    def setUpClass(cls):
        repo, c = cls.repo, cls.c = build_delegated(cls.class_tmp(), approval("delegated"))
        reviews = {"rok": [review_row("UXC-302", c["UXC-302"])],
                   "rnob": [review_row("UXC-305", c["UXC-305"], b="no", refuted=None)],
                   "rperson": [review_row("UXC-306", c["UXC-306"], decision="person")]}
        files = {f"{REVIEWS}/{run}.json": review_text(run, rows) for run, rows in reviews.items()}
        files[CORR] = corrections(toml_row(story="UXC-301", commit=c["UXC-301"]),
                                  delegated_row("UXC-302", c["UXC-302"], "rok"),
                                  delegated_row("UXC-304", c["UXC-304"], "rmissing"),
                                  delegated_row("UXC-305", c["UXC-305"], "rnob"),
                                  delegated_row("UXC-306", c["UXC-306"], "rperson"))
        commit_harness(repo, "chore: corrections\n\nNo-story: ledger", files)
        repo.publish()

    def test_LEDGER_015_S7_INV_005_the_json_says_who_approved(self):
        s = self.stories(self.repo)
        self.assertEqual((s["UXC-301"]["reconstructed"], s["UXC-301"]["reconstructed_by"]), (True, "person"))
        self.assertEqual((s["UXC-302"]["reconstructed"], s["UXC-302"]["reconstructed_by"]), (True, "delegated"))
        self.assertEqual(s["UXC-302"]["correction"]["approver"], "delegated:rok")
        self.assertIsNone(s["UXC-303"]["reconstructed_by"], "null unless reconstructed")

    def test_LEDGER_015_S7_the_summary_says_reconstructed_person_or_delegated(self):
        r = self.repo.ledger()
        self.assertNotIn("Traceback", r.stderr)
        lines = r.stdout.splitlines()
        person = [x for x in lines if x.startswith("reconstructed (person):")]
        delegated = [x for x in lines if x.startswith("reconstructed (delegated):")]
        self.assertEqual(len(person), 1, r.stdout)
        self.assertEqual(len(delegated), 1, r.stdout)
        self.assertIn("UXC-301", person[0])
        self.assertNotIn("UXC-302", person[0])
        self.assertIn("UXC-302", delegated[0])
        self.assertNotIn("UXC-301", delegated[0])

    def test_LEDGER_015_S7_dx_the_spanish_summary(self):
        self.repo.state(approval("delegated") + '\n[dashboard]\nlang = "es"\n')
        self.addCleanup(self.repo.state, approval("delegated"))
        out = self.repo.ledger().stdout
        self.assertRegex(out, r"(?m)^reconstruidas \(persona\): .*UXC-301")
        self.assertRegex(out, r"(?m)^reconstruidas \(delegada\): .*UXC-302")

    def test_LEDGER_015_D6_a_delegated_row_counts_only_when_its_review_file_approves_it(self):
        data = ledger_check(self, self.repo)
        invalid = [d["detail"] for d in data["diffs"] if d["code"] == "CORRECTION_INVALID"]
        for run in ("rmissing", "rnob", "rperson"):
            with self.subTest(run):
                self.assertEqual(sum(run in d for d in invalid), 1, invalid)
        self.assertFalse(any("rok" in d for d in invalid), invalid)
        s = self.stories(self.repo)
        for sid in ("UXC-304", "UXC-305", "UXC-306"):
            self.assertIs(s[sid]["reconstructed"], False, sid)
        self.assertIs(s["UXC-302"]["reconstructed"], True)


class LedgerDelegatedRejectSampleTest(LedgerCase):
    """S8 and D9: `review --reject-sample <run>`, a person in their terminal, retracts every row of that run
    (append-only, INV-008) and sends them back to the proposed file; other runs and the person's rows stay."""

    def build(self) -> tuple[GitRepo, dict]:
        repo, c = build_delegated(self.tmp, approval("delegated"))
        files = {f"{REVIEWS}/rs.json": review_text("rs", [review_row("UXC-301", c["UXC-301"], evidence="E1"),
                                                          review_row("UXC-302", c["UXC-302"], evidence="E2")]),
                 f"{REVIEWS}/rt.json": review_text("rt", [review_row("UXC-306", c["UXC-306"])]),
                 CORR: corrections(delegated_row("UXC-301", c["UXC-301"], "rs", evidence="E1"),
                                   delegated_row("UXC-302", c["UXC-302"], "rs", evidence="E2"),
                                   toml_row(story="UXC-305", commit=c["UXC-305"]),
                                   delegated_row("UXC-306", c["UXC-306"], "rt"))}
        commit_harness(repo, "chore: corrections\n\nNo-story: ledger", files)
        repo.publish()
        s = self.stories(repo)
        self.assertTrue(all(s[x]["reconstructed"] for x in ("UXC-301", "UXC-302", "UXC-305", "UXC-306")),
                        "D6: delegated rows backed by their committed review file count")
        return repo, c

    def test_LEDGER_015_S8_INV_008_a_rejected_sample_retracts_every_row_of_the_run(self):
        repo, c = self.build()
        old = (repo.path / CORR).read_text()
        before = today_dates()
        code, out = run_in_pty(repo, "review", "--reject-sample", "rs", answer="y\n")
        dates = before | today_dates()
        self.assertNotIn("Traceback", out)
        self.assertEqual(code, 0, out)
        self.assertIn("[y/N]", out)
        new = (repo.path / CORR).read_text()
        self.assertTrue(new.startswith(old), "rows are only added")
        added = corrections_rows(repo)[4:]
        self.assertEqual([(r["story"], r["commit"], r["kind"]) for r in added],
                         [("UXC-301", c["UXC-301"], "retract"), ("UXC-302", c["UXC-302"], "retract")])
        for r in added:
            self.assertEqual(r["approver"], "T")
            self.assertIn(r["date"], dates)
            self.assertEqual(r["evidence"], "sample of delegated run rs rejected")
        back = [(r["story"], r["commit"], r["kind"], r["evidence"]) for r in proposed_rows(repo)]
        self.assertEqual(back, [("UXC-301", c["UXC-301"], "backfill", "E1"), ("UXC-302", c["UXC-302"], "backfill", "E2")],
                         "the rows go back to review")
        repo.git("add", CORR)
        repo.git("commit", "-q", "-m", "chore: reject sample rs\n\nNo-story: ledger", when=repo.next_date())
        repo.publish()
        s = self.stories(repo)
        for sid in ("UXC-301", "UXC-302"):
            self.assertEqual((s[sid]["state"], s[sid]["reconstructed"]), ("ready", False), sid)
        for sid in ("UXC-305", "UXC-306"):
            self.assertIs(s[sid]["reconstructed"], True, f"{sid}: another run and the person's rows stay")
        self.assertEqual(codes(ledger_check(self, repo), "error"), [])

    def test_LEDGER_015_S8_reject_sample_is_a_persons_and_needs_rows_to_retract(self):
        repo, _ = self.build()
        old = (repo.path / CORR).read_text()
        r = repo.ledger("review", "--reject-sample", "rs")
        self.assertNotIn("Traceback", r.stderr)
        self.assertEqual(r.returncode, 1, "no terminal: an agent")
        code, out = run_in_pty(repo, "review", "--reject-sample", "rs", answer="y\n", extra_env=agent_env())
        self.assertEqual(code, 1, "Claude Code's shell, even under a pty")
        code, out = run_in_pty(repo, "review", "--reject-sample", "rnone", answer="y\n")
        self.assertNotIn("Traceback", out)
        self.assertEqual(code, 1, "nothing to retract")
        self.assertEqual((repo.path / CORR).read_text(), old, "nothing written")
        self.assertFalse((repo.path / PROPOSED).exists())


# ── LEDGER-015, review round 1: what got past the first tests (ESC-114, ESC-116, ESC-117) ──


class LedgerDelegatedRowValidityTest(LedgerCase):
    """ESC-114 (F5): a delegated row counts only when its review recorded delegated or mixed, its kind is backfill or
    late, ledger.py re-decides it approved (recorded mode, human_for, confidence and models, with `critical`
    recomputed from the trunk now) and its commit touches the story's paths. A hand-written "approved" is not enough.
    The valid control (a critical row judged by Opus while the trunk delegates) is LedgerDelegatedTrunkModeTest's: this
    class's trunk is mixed, where such a review is G2's forgery (ESC-120)."""

    @classmethod
    def setUpClass(cls):
        repo, c = cls.repo, cls.c = build_delegated(cls.class_tmp(), approval("mixed"))
        reviews = {
            "rcrit": (review_text("rcrit", [review_row("UXC-303", c["UXC-303"])], mode="mixed")),
            "rout": (review_text("rout", [review_row("UXC-301", c["UXC-302"])])),
            "rnomode": (review_text("rnomode", [review_row("UXC-305", c["UXC-305"])], mode=None)),
            "rhuman": (review_text("rhuman", [review_row("UXC-306", c["UXC-306"])], mode="human")),
            "rret": (review_text("rret", [{**review_row("UXC-302", c["UXC-302"]), "kind": "retract"}])),
        }
        files = {f"{REVIEWS}/{run}.json": text for run, text in reviews.items()}
        files[CORR] = corrections(
            delegated_row("UXC-303", c["UXC-303"], "rcrit"),
            delegated_row("UXC-301", c["UXC-302"], "rout"),
            delegated_row("UXC-305", c["UXC-305"], "rnomode"),
            delegated_row("UXC-306", c["UXC-306"], "rhuman"),
            toml_row(story="UXC-302", commit=c["UXC-302"]),
            toml_row(story="UXC-302", commit=c["UXC-302"], kind="retract", approver="delegated:rret"))
        commit_harness(repo, "chore: corrections\n\nNo-story: ledger", files)
        repo.publish()

    def invalid(self) -> list[str]:
        cls = type(self)
        if "_invalid" not in cls.__dict__:
            data = ledger_check(self, cls.repo)
            cls._invalid = [d["detail"] for d in data["diffs"] if d["code"] == "CORRECTION_INVALID"]
        return cls._invalid

    def assert_invalid(self, run: str, story: str) -> None:
        self.assertEqual(sum(run in d for d in self.invalid()), 1, self.invalid())
        self.assertIs(self.stories(self.repo)[story]["reconstructed"], False, story)

    def test_LEDGER_015_D6_ESC_114_INV_005_an_approved_critical_story_in_mixed_does_not_count(self):
        self.assert_invalid("rcrit", "UXC-303")

    def test_LEDGER_015_D6_ESC_114_INV_005_a_commit_outside_the_storys_paths_does_not_count(self):
        self.assert_invalid("rout", "UXC-301")

    def test_LEDGER_015_D6_ESC_114_a_review_with_no_recorded_mode_or_mode_human_does_not_count(self):
        self.assert_invalid("rnomode", "UXC-305")
        self.assert_invalid("rhuman", "UXC-306")

    def test_LEDGER_015_D6_ESC_114_INV_005_a_delegated_retract_does_not_count(self):
        self.assertEqual(sum("rret" in d for d in self.invalid()), 1, self.invalid())
        self.assertIs(self.stories(self.repo)["UXC-302"]["reconstructed"], True, "the person's row stays active")



class LedgerDelegatedHumanReviewTest(LedgerCase):
    def test_LEDGER_015_S9_ESC_114_without_delegation_a_review_recorded_human_or_without_mode_backs_nothing(self):
        """F10: a project whose trunk has no [ledger.approval]; the delegated rows' review files say approved."""
        repo, c = build_delegated(self.tmp, approval())
        files = {f"{REVIEWS}/rh.json": review_text("rh", [review_row("UXC-301", c["UXC-301"])], mode="human"),
                 f"{REVIEWS}/rn.json": review_text("rn", [review_row("UXC-302", c["UXC-302"])], mode=None),
                 CORR: corrections(delegated_row("UXC-301", c["UXC-301"], "rh"),
                                   delegated_row("UXC-302", c["UXC-302"], "rn"))}
        commit_harness(repo, "chore: corrections\n\nNo-story: ledger", files)
        repo.publish()
        data = ledger_check(self, repo)
        invalid = details(data, "CORRECTION_INVALID")
        self.assertIn("rh", invalid)
        self.assertIn("rn", invalid)
        s = self.stories(repo)
        self.assertEqual((s["UXC-301"]["reconstructed"], s["UXC-302"]["reconstructed"]), (False, False))


class LedgerDelegatedLaunderTest(LedgerDelegatedAcceptCase):
    """ESC-116 (F7): a row a review left to the person or pending (on the trunk or in the work tree) is dropped by the
    filter and by the delegated accept: judging it again cannot launder a disagreement."""

    def test_LEDGER_015_S4_ESC_116_a_row_left_to_the_person_or_pending_is_dropped_by_the_filter_and_the_accept(self):
        repo, c = self.build(approval("mixed"))
        commit_harness(repo, "chore: delegated review\n\nNo-story: ledger", {
            f"{REVIEWS}/rp.json": review_text("rp", [review_row("UXC-301", c["UXC-301"], decision="person",
                                                                b="no", refuted=None)], mode="mixed"),
            f"{REVIEWS}/rq.json": review_text("rq", [review_row("UXC-302", c["UXC-302"], decision="pending",
                                                                refuted=True)], mode="mixed")})
        repo.publish()
        repo.write(f"{REVIEWS}/rw.json", review_text("rw", [review_row("UXC-305", c["UXC-305"], decision="pending",
                                                                       refuted=True)], mode="mixed"))
        repo.write(PROPOSED, "".join(proposed_row(s, c[s]) for s in ("UXC-301", "UXC-302", "UXC-305", "UXC-306")))
        d = review_filter(self, repo)
        self.assertEqual([r["story"] for r in d["rows"]], ["UXC-306"], d)
        reasons = {x["story"]: x["reason"] for x in d["dropped"]}
        self.assertIn("left to the person by run rp", reasons.get("UXC-301", ""))
        self.assertIn("pending after run rq", reasons.get("UXC-302", ""))
        self.assertIn("pending after run rw", reasons.get("UXC-305", ""), "a review in the work tree counts too")
        repo.write(f"{REVIEWS}/rnew.json", review_text("rnew", [review_row("UXC-301", c["UXC-301"], decision=None),
                                                                review_row("UXC-306", c["UXC-306"], decision=None)],
                                                       mode=None))
        r = self.accept(repo, "rnew")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.decisions(repo, "rnew"), {"UXC-301": "dropped", "UXC-306": "approved"})
        self.assertEqual([x["story"] for x in self.corr(repo)], ["UXC-306"])


class LedgerDelegatedResumeTest(LedgerDelegatedAcceptCase):
    def test_LEDGER_015_S3_ESC_117_INV_008_a_resumed_accept_of_the_same_run_appends_nothing_twice(self):
        """ESC-117 (F8): a resumed workflow puts back the undecided review file and runs the accept again; with
        rows of delegated:<run> already in the work tree's corrections file it refuses."""
        repo, c = self.build(approval("delegated"))
        run = self.review(repo, {"UXC-301": c["UXC-301"]})
        undecided = (repo.path / REVIEWS / f"{run}.json").read_text()
        r = self.accept(repo, run)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        written = (repo.path / CORR).read_text()
        repo.write(f"{REVIEWS}/{run}.json", undecided)
        r = self.accept(repo, run)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual((repo.path / CORR).read_text(), written, "no second copy")
        self.assertEqual(len(corrections_rows(repo)), 1)


# ── LEDGER-015, review round 2 (ESC-120: delegated rows re-decided against the right approval and trunk) ──


class LedgerDelegatedTrunkModeTest(LedgerCase):
    """ESC-120 (G2): a delegated row counts only when it is approved under its review's recorded approval and, when
    the trunk's current mode is mixed, under the trunk's current approval too: a review that records "delegated"
    cannot take a critical story past a project that keeps critical stories for the person."""

    def forged(self, trunk_mode: str) -> GitRepo:
        repo, c = build_delegated(self.tmp, approval(trunk_mode))
        commit_harness(repo, "chore: corrections\n\nNo-story: ledger", {
            f"{REVIEWS}/rforge.json": review_text("rforge", [review_row("UXC-303", c["UXC-303"], model="claude-opus-4")],
                                                  mode="delegated"),
            CORR: corrections(delegated_row("UXC-303", c["UXC-303"], "rforge"))})
        repo.publish()
        return repo

    def test_LEDGER_015_D6_ESC_120_INV_005_a_review_recorded_delegated_does_not_pass_a_critical_story_in_a_mixed_project(self):
        repo = self.forged("mixed")
        data = ledger_check(self, repo)
        self.assertIn("rforge", details(data, "CORRECTION_INVALID"), data["diffs"])
        self.assertIs(self.stories(repo)["UXC-303"]["reconstructed"], False)

    def test_LEDGER_015_D6_ESC_120_the_same_review_counts_while_the_trunk_delegates(self):
        repo = self.forged("delegated")
        data = ledger_check(self, repo)
        self.assertNotIn("rforge", details(data, "CORRECTION_INVALID"), data["diffs"])
        s = self.stories(repo)["UXC-303"]
        self.assertEqual((s["reconstructed"], s["reconstructed_by"]), (True, "delegated"))


class LedgerDelegatedAsOfArrivalTest(LedgerCase):
    """ESC-120 (G4): a delegated row's `critical` flag and its story's `touches` are read from the trunk as it was at
    the first-parent commit where the row first appeared, not from the tip: a later critical area or a later change
    of the story's paths does not void an honest approval (the forgery, a row committed while the story was already
    critical, stays invalid: LedgerDelegatedRowValidityTest's rcrit)."""

    def test_LEDGER_015_D6_ESC_120_INV_005_a_later_critical_area_or_touches_change_keeps_an_approved_row(self):
        repo, c = build_delegated(self.tmp, approval("mixed"))
        commit_harness(repo, "chore: delegated review r1\n\nNo-story: ledger", {
            f"{REVIEWS}/r1.json": review_text("r1", [review_row("UXC-301", c["UXC-301"])], mode="mixed"),
            CORR: corrections(delegated_row("UXC-301", c["UXC-301"], "r1"))})
        repo.publish()
        later = {"a critical area now covers its paths":
                 {CRITICAL: CRITICAL_TOML + '\n[[area]]\nname = "login"\nwhy = "w"\npaths = ["apps/api/login/"]\n'},
                 "its touches moved elsewhere":
                 {"backlog/stories/UXC-301-s.md": story15("UXC-301", ("apps/api/elsewhere/",))}}
        for why, files in later.items():
            with self.subTest(why):
                commit_harness(repo, f"chore: {why}\n\nNo-story: docs", files)
                repo.publish()
                data = ledger_check(self, repo)
                self.assertNotIn("r1", details(data, "CORRECTION_INVALID"), data["diffs"])
                s = self.stories(repo)["UXC-301"]
                self.assertEqual((s["reconstructed"], s["reconstructed_by"]), (True, "delegated"))



# ─────────────── LEDGER-005: show, next, check and --release ───────────────


def story_file(sid: str, extra: str = "", wave: int = 1, depends_on: tuple = ()) -> str:
    """A story file with optional text after it (an addendum)."""
    return story_md(sid, depends_on, wave) + extra


def show(test: unittest.TestCase, repo: GitRepo, *args: str, code: int = 0) -> str:
    r = repo.ledger("show", *args)
    test.assertNotIn("Traceback", r.stderr)
    test.assertEqual(r.returncode, code, f"ledger.py show {' '.join(args)} exited {r.returncode}\n{r.stdout}{r.stderr}")
    return r.stdout


def check_text(test: unittest.TestCase, repo: GitRepo, *args: str) -> subprocess.CompletedProcess:
    r = repo.ledger("check", *args)
    test.assertNotIn("Traceback", r.stderr)
    test.assertIn(r.returncode, (0, 1), r.stdout + r.stderr)
    return r


ADDENDUM = "\n## Addendum — 2026-11-20\n\nDecided: the smallest option.\n"


class LedgerShowTest(LedgerCase):
    """S1..S3: show gathers the why from where it already lives: commit bodies, the addendum, escape rows,
    bug-bash findings (by id or through Finding:), abandoned attempts on origin branches, corrections."""

    @classmethod
    def setUpClass(cls):
        repo = cls.repo = GitRepo(cls.class_tmp())
        repo.commit("docs: plan\n\nNo-story: docs", {
            "backlog/stories/SHOW-001-s.md": story_file("SHOW-001", ADDENDUM),
            "backlog/stories/SHOW-002-s.md": story_file("SHOW-002"),
            "backlog/stories/SHOW-003-s.md": story_file("SHOW-003"),
            "backlog/stories/SHOW-004-s.md": story_file("SHOW-004"),
            "backlog/stories/SHOW-010-s.md": story_file("SHOW-010"),
            "docs/escapes.md": "# Escapes\n\n| Id | Date | Found by | What escaped | Class | Check added |\n"
                               "|---|---|---|---|---|---|\n"
                               "| ESC-001 | 2026-11-20 | SHOW-001 breaker | the cache kept a stale row | consistency | t1 |\n"
                               "| ESC-002 | 2026-11-20 | OTHER-1 reviewer | SHOW-0010 and XSHOW-001 differ | logic | t2 |\n"
                               "| ESC-003 | 2026-11-21 | bug bash | LOG-303: the retry doubled the charge | money | t3 |\n",
            "docs/bugbash/2026-11-21/logic.md": "# logic\n\n### LOG-302 · Unrelated\n- text\n\n"
                                                "### LOG-303 · The retry doubles the charge (P1)\n- **Where:** api\n",
        })
        cls.part = repo.commit("feat: SHOW-001 first half\n\nThe parser goes first because the cache needs it.\n\n"
                               "Part-of: SHOW-001\nClaude-Session: https://claude.ai/code/session_aaa")
        cls.story = repo.commit("feat: SHOW-001 the cache\n\nKept the cache in memory: a file lock was too slow.\n"
                                "Left out: eviction.\n\nStory: SHOW-001\nClaude-Session: https://claude.ai/code/session_bbb")
        cls.fix = repo.commit("fix: the retry\n\nOne retry, never two.\n\nStory: SHOW-003\nFinding: LOG-303")
        repo.publish()
        repo.on_branch("try/show-2", "wip: SHOW-002 with a queue\n\nPart-of: SHOW-002",
                       "drop: SHOW-002\n\nA queue cannot keep the order the export needs.\n\nDropped: SHOW-002")
        repo.publish()

    def test_LEDGER_005_S1_show_gathers_the_body_the_addendum_and_the_escape_row_with_their_paths(self):
        out = show(self, self.repo, "SHOW-001")
        self.assertIn("SHOW-001", out.splitlines()[0])
        self.assertIn("on-trunk", out)
        self.assertIn("Kept the cache in memory: a file lock was too slow.", out, "the Story: commit's body")
        self.assertIn("The parser goes first because the cache needs it.", out, "the Part-of: commit's body")
        self.assertIn(self.story[:7], out)
        self.assertIn("feat: SHOW-001 the cache", out, "the subject")
        self.assertIn("session_bbb", out, "Claude-Session:")
        self.assertIn("backlog/stories/SHOW-001-s.md", out, "the story file's path")
        addendum = [line for line in out.splitlines() if "## Addendum — 2026-11-20" in line]
        self.assertTrue(addendum, out)
        self.assertIn("backlog/stories/SHOW-001-s.md", addendum[0], "the addendum heading with its path")
        rows = [line for line in out.splitlines() if "ESC-001" in line]
        self.assertTrue(rows, out)
        self.assertIn("docs/escapes.md", rows[0], "the escape row with its path")
        self.assertNotIn("ESC-002", out, "SHOW-0010 and XSHOW-001 do not name SHOW-001")
        self.assertNotIn("Decided: the smallest option.", out, "headings, not the addendum's contents")

    def test_LEDGER_005_S2_show_lists_an_abandoned_attempt_with_its_reason_and_branch(self):
        out = show(self, self.repo, "SHOW-002")
        lines = [line for line in out.splitlines() if "try/show-2" in line]
        self.assertTrue(lines, out)
        self.assertIn("A queue cannot keep the order the export needs.", out)
        attempts = self.stories(self.repo)["SHOW-002"]["attempts"]
        self.assertEqual(len(attempts), 1, attempts)
        self.assertEqual(attempts[0]["branches"], ["try/show-2"])
        self.assertIn("A queue cannot keep the order", attempts[0]["reason"])
        self.assertEqual(attempts[0]["commit"], self.repo.sha("refs/remotes/origin/try/show-2"))

    def test_LEDGER_005_S3_show_finds_a_finding_through_the_finding_trailer(self):
        out = show(self, self.repo, "SHOW-003")
        lines = [line for line in out.splitlines() if "LOG-303" in line and "docs/bugbash/2026-11-21/logic.md" in line]
        self.assertTrue(lines, out)
        self.assertNotIn("LOG-302", out)
        self.assertIn("ESC-003", out, "an escape row naming the finding arrives through Finding: too")

    def test_LEDGER_005_dx_show_of_an_unknown_id_exits_1_and_without_an_id_is_usage(self):
        r = self.repo.ledger("show", "NOPE-001")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("NOPE-001", r.stdout + r.stderr)
        for bad in (["show"], ["show", "a", "b"], ["show", "SHOW-001", "--bogus"], ["next", "x"], ["--release"],
                    ["check", "--bogus"]):
            r = self.repo.ledger(*bad)
            self.assertEqual(r.returncode, 2, f"{bad}: {r.stdout}{r.stderr}")
            self.assertNotIn("Traceback", r.stderr)

    def test_LEDGER_005_dx_show_of_a_story_with_nothing_yet_says_so_briefly(self):
        out = show(self, self.repo, "SHOW-010")
        self.assertIn("ready", out)
        self.assertLessEqual(len(out.splitlines()), 10, out)

    def test_LEDGER_005_i18n_show_speaks_the_dashboard_language(self):
        self.repo.state('[dashboard]\nlang = "es"\n')
        try:
            out = show(self, self.repo, "SHOW-001")
        finally:
            self.repo.state("")
        self.assertIn("en trunk", out)
        self.assertIn("Kept the cache in memory", out, "the facts stay as written")


class LedgerShowCorrectionTest(LedgerCase):
    """show lists a story's corrections: the row that reconstructs it, with its evidence and approver."""

    def test_LEDGER_005_logic_show_lists_the_correction_rows_of_a_reconstructed_story(self):
        repo = GitRepo(self.tmp)
        repo.plan("UXC-113")
        old = repo.commit("feat: the old export\n\nNo-story: docs")
        repo.commit("chore: corrections\n\nNo-story: docs", {CORR: corrections(toml_row(commit=old))})
        repo.publish()
        out = show(self, repo, "UXC-113")
        self.assertIn("reconstructed (person)", out)
        lines = [line for line in out.splitlines() if old[:7] in line and "backfill" in line]
        self.assertTrue(lines, out)
        self.assertIn("train sheet 18", out)
        self.assertIn("Leo", out)


class LedgerShowBoundTest(LedgerCase):
    """S8: at most 60 lines, and how to see the rest."""

    def test_LEDGER_005_S8_show_prints_at_most_60_lines_and_says_how_to_see_the_rest(self):
        repo = GitRepo(self.tmp)
        repo.plan("BIG-001")
        for n in range(40):
            repo.commit(f"feat: BIG-001 step {n}\n\nStep {n} because of reason {n}.\nAnd a second line {n}.\n\n"
                        f"Part-of: BIG-001")
        repo.commit("feat: BIG-001 done\n\nThe last word.\n\nStory: BIG-001")
        repo.publish()
        out = show(self, repo, "BIG-001")
        lines = out.splitlines()
        self.assertLessEqual(len(lines), 60, out)
        self.assertIn("--full", lines[-1], "the last line says how to see the rest")
        full = show(self, repo, "BIG-001", "--full")
        self.assertGreater(len(full.splitlines()), 60)
        for n in range(40):
            self.assertIn(f"Step {n} because of reason {n}.", full)
        self.assertIn("The last word.", full)
        self.assertNotIn("--full", full.splitlines()[-1])
        self.assertTrue(all(len(line) <= 200 for line in lines), "paths, not long contents")


class LedgerNextTest(LedgerCase):
    """S4: next lists the ready stories that are not in progress, by wave and id."""

    def test_LEDGER_005_S4_next_excludes_work_in_progress(self):
        repo = GitRepo(self.tmp)
        repo.commit("docs: plan\n\nNo-story: docs", {
            "backlog/stories/NX-1-s.md": story_file("NX-1"),
            "backlog/stories/NX-2-s.md": story_file("NX-2"),
            "backlog/stories/NX-3-s.md": story_file("NX-3", depends_on=("NX-9",)),
            "backlog/stories/NX-9-s.md": story_file("NX-9", wave=5),
            "backlog/stories/NX-10-s.md": story_file("NX-10"),
            "backlog/stories/NX-4-s.md": story_file("NX-4", wave=0),
            "backlog/stories/NX-5-s.md": story_file("NX-5")})
        repo.commit("feat: NX-5\n\nWhy.\n\nStory: NX-5")
        repo.publish()
        repo.on_branch("claude/nx-1", "wip: NX-1\n\nPart-of: NX-1")
        repo.publish()
        r = repo.ledger("next")
        self.assertNotIn("Traceback", r.stderr)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        ids = [m.group(0) for m in (re.match(r"NX-[0-9]+", line) for line in r.stdout.splitlines()) if m]
        self.assertEqual(ids, ["NX-4", "NX-2", "NX-10", "NX-9"],
                         "ready only (not NX-1 in progress, NX-3 waiting, NX-5 done), by wave then id\n" + r.stdout)

    def test_LEDGER_005_S4_dx_next_with_nothing_ready_says_so_and_exits_0(self):
        repo = GitRepo(self.tmp)
        repo.plan("NX-1")
        repo.commit("feat: NX-1\n\nWhy.\n\nStory: NX-1")
        repo.publish()
        r = repo.ledger("next")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(r.stdout.strip(), "one line saying nothing is ready")
        self.assertNotIn("NX-1", r.stdout)


class LedgerCheckCodesTest(LedgerCase):
    """S5, S6: check gives every difference of docs/ledger.md with its level; exit 1 on an error, 0 on warnings."""

    def test_LEDGER_005_S5_check_finds_an_unknown_id_and_exits_1(self):
        repo = GitRepo(self.tmp)
        repo.plan("AUTH-001")
        bad = repo.commit("feat: something\n\nWhy.\n\nStory: NOPE-001")
        repo.publish()
        data = ledger_check(self, repo)
        self.assertIn("UNKNOWN_STORY", codes(data, "error"))
        self.assertIn("NOPE-001", details(data, "UNKNOWN_STORY"))
        self.assertIn(bad[:7], details(data, "UNKNOWN_STORY"))
        r = check_text(self, repo)
        self.assertEqual(r.returncode, 1)
        self.assertIn("error UNKNOWN_STORY", r.stdout)

    def test_LEDGER_005_S5_logic_a_part_of_naming_an_unknown_id_is_unknown_too_and_a_known_one_is_not(self):
        repo = GitRepo(self.tmp)
        repo.plan("AUTH-001")
        repo.commit("feat: a\n\nWhy.\n\nPart-of: AUTH-001, GHOST-7")
        repo.commit("feat: b\n\nWhy.\n\nStory: AUTH-001")
        repo.publish()
        data = ledger_check(self, repo)
        self.assertEqual(codes(data), ["UNKNOWN_STORY"], data["diffs"])
        self.assertIn("GHOST-7", details(data, "UNKNOWN_STORY"))
        self.assertNotIn("AUTH-001", details(data, "UNKNOWN_STORY"))

    def test_LEDGER_005_S6_check_warns_about_a_stale_branch_and_exits_0(self):
        repo = GitRepo(self.tmp)
        repo.plan("AUTH-001", "AUTH-002")
        repo.publish()
        repo.on_branch("old/auth-1", "wip: AUTH-001\n\nPart-of: AUTH-001", when="2020-01-01T00:00:00+00:00")
        recent = f"@{int(time.time()) - 3600} +0000"
        repo.on_branch("new/auth-2", "wip: AUTH-002\n\nPart-of: AUTH-002", when=recent)
        repo.publish()
        data = ledger_check(self, repo)
        self.assertEqual(codes(data), ["STALE_BRANCH"], data["diffs"])
        self.assertEqual(codes(data, "warning"), ["STALE_BRANCH"])
        self.assertIn("AUTH-001", details(data, "STALE_BRANCH"))
        self.assertIn("old/auth-1", details(data, "STALE_BRANCH"))
        self.assertNotIn("AUTH-002", details(data, "STALE_BRANCH"))
        r = check_text(self, repo)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("warning STALE_BRANCH", r.stdout)
        repo.state("[ledger]\nstale_days = 100000\n")
        self.assertEqual(codes(ledger_check(self, repo)), [])

    def test_LEDGER_005_S5_logic_attribution_codes_after_since(self):
        """UNATTRIBUTED, BAD_CATEGORY, STORY_NO_BODY and SQUASH_LOST_TRAILERS: errors, only after `since`."""
        repo = GitRepo(self.tmp)
        repo.plan("AUTH-001", "AUTH-002", "AUTH-003")
        repo.commit("chore: old and loose")
        repo.commit("feat: old\n\nStory: AUTH-003")  # before since: no body is not checked
        since = repo.commit("chore: adopt\n\nNo-story: harness")
        loose = repo.commit("chore: loose")
        cat = repo.commit("chore: x\n\nNo-story: lunch — nothing")
        nobody = repo.commit("feat: AUTH-001\n\nStory: AUTH-001")
        squash = repo.commit("feat: AUTH-002 (#7)\n\n* wip: AUTH-002\n\nPart-of: AUTH-002\n\n* more\n\n"
                             "Co-authored-by: A <a@example.com>")
        repo.commit("docs: fine\n\nNo-story: docs — a typo")
        repo.publish()
        repo.state(f'[ledger]\nsince = "{since}"\n')
        data = ledger_check(self, repo)
        self.assertEqual(sorted(codes(data, "error")),
                         ["BAD_CATEGORY", "SQUASH_LOST_TRAILERS", "STORY_NO_BODY", "UNATTRIBUTED"], data["diffs"])
        self.assertIn(loose[:7], details(data, "UNATTRIBUTED"))
        self.assertNotIn(squash[:7], details(data, "UNATTRIBUTED"), "a lost squash is its own code")
        self.assertIn(squash[:7], details(data, "SQUASH_LOST_TRAILERS"))
        self.assertIn(cat[:7], details(data, "BAD_CATEGORY"))
        self.assertIn("lunch", details(data, "BAD_CATEGORY"))
        self.assertIn(nobody[:7], details(data, "STORY_NO_BODY"))
        repo.state(f'[ledger]\nsince = "{since}"\nno_story = ["lunch", "docs", "harness"]\n')
        self.assertNotIn("BAD_CATEGORY", codes(ledger_check(self, repo)))
        repo.state(f'[ledger]\nsince = "{since}"\nenforce = "warn"\n')
        data = ledger_check(self, repo)
        self.assertEqual(codes(data, "error"), [], "enforce = warn: the attribution codes are warnings")
        self.assertIn("UNATTRIBUTED", codes(data, "warning"))
        repo.state("")
        self.assertEqual(codes(ledger_check(self, repo)), [], "no since: attribution is not required")

    def test_LEDGER_005_S5_logic_a_merge_attributes_what_it_brings(self):
        repo = GitRepo(self.tmp)
        repo.plan("AUTH-001")
        since = repo.commit("chore: adopt\n\nNo-story: harness")
        repo.on_branch("feat/x", "wip one", "wip two", keep=True, push=False)
        repo.merge("feat/x", "Merge feat/x\n\nThe export, in two steps.\n\nStory: AUTH-001")
        repo.publish()
        repo.state(f'[ledger]\nsince = "{since}"\n')
        self.assertEqual(codes(ledger_check(self, repo)), [])

    def test_LEDGER_005_S6_logic_done_twice_is_a_warning(self):
        repo = GitRepo(self.tmp)
        repo.plan("AUTH-001")
        first = repo.commit("feat: AUTH-001\n\nWhy.\n\nStory: AUTH-001")
        second = repo.commit("feat: AUTH-001 again\n\nWhy again.\n\nStory: AUTH-001")
        repo.publish()
        data = ledger_check(self, repo)
        self.assertEqual(codes(data), ["DONE_TWICE"], data["diffs"])
        self.assertEqual(codes(data, "warning"), ["DONE_TWICE"])
        self.assertIn(first[:7], details(data, "DONE_TWICE"))
        self.assertIn(second[:7], details(data, "DONE_TWICE"))
        repo.revert(second)
        repo.publish()
        self.assertEqual(codes(ledger_check(self, repo)), [], "a reverted one does not count")

    def test_LEDGER_005_S6_logic_snapshot_behind_is_a_warning(self):
        repo = GitRepo(self.tmp)
        repo.plan("AUTH-001")
        old = repo.sha()
        repo.publish()
        self.assertEqual(codes(ledger_check(self, repo)), [], "no snapshot branch: nothing to compare")
        current = repo.git("symbolic-ref", "--short", "HEAD").strip()
        repo.git("checkout", "-q", "--orphan", "keelokit/ledger")
        repo.git("rm", "-rq", "--cached", ".")
        repo.write("ledger.json", json.dumps({"schema": 1, "trunk": "main", "trunk_sha": old}))
        repo.git("add", "ledger.json")
        repo.git("commit", "-q", "-m", "snapshot", when=repo.next_date())
        repo.git("push", "-q", "origin", "keelokit/ledger")
        repo.git("checkout", "-q", "-f", current)
        self.assertEqual(codes(ledger_check(self, repo)), [], "the snapshot is at the trunk")
        repo.commit("docs: more\n\nNo-story: docs")
        repo.publish()
        data = ledger_check(self, repo)
        self.assertEqual(codes(data), ["SNAPSHOT_BEHIND"], data["diffs"])
        self.assertEqual(codes(data, "warning"), ["SNAPSHOT_BEHIND"])
        repo.state('[ledger]\nsnapshot = ""\n')
        self.assertEqual(codes(ledger_check(self, repo)), [], "snapshot = \"\" turns it off")

    def test_LEDGER_005_S5_logic_ci_makes_an_incomplete_history_an_error(self):
        repo = GitRepo(self.tmp)
        repo.plan("AUTH-001")
        for n in range(5):
            repo.commit(f"docs: {n}\n\nNo-story: docs")
        repo.publish()
        clone = repo.clone("shallow", depth=2)
        r = clone.ledger("check", "--json")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(codes(json.loads(r.stdout), "warning"), ["HISTORY_INCOMPLETE"])
        r = clone.ledger("check", "--ci", "--json")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(codes(json.loads(r.stdout), "error"), ["HISTORY_INCOMPLETE"])
        r = clone.ledger("check", "--ci")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("error HISTORY_INCOMPLETE", r.stdout)


class LedgerReleaseTest(LedgerCase):
    """S7: --release vX.Y.Z lists the stories whose commits are between the previous version tag and it."""

    def test_LEDGER_005_S7_release_lists_exactly_the_stories_between_the_two_tags(self):
        repo = GitRepo(self.tmp)
        repo.plan("REL-1", "REL-2", "REL-3", "REL-4")
        repo.commit("feat: REL-1\n\nWhy.\n\nStory: REL-1")
        repo.tag("v1.0.0")
        repo.commit("feat: REL-2\n\nWhy.\n\nStory: REL-2")
        repo.commit("docs: between\n\nNo-story: docs")
        repo.commit("feat: REL-3\n\nWhy.\n\nStory: REL-3")
        repo.tag("v1.1.0-rc.1")
        repo.tag("v1.1.0")
        repo.commit("feat: REL-4\n\nWhy.\n\nStory: REL-4")
        repo.publish()
        repo.git("push", "-q", "origin", "--tags")
        r = repo.ledger("--release", "v1.1.0")
        self.assertNotIn("Traceback", r.stderr)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        listed_ids = sorted(set(re.findall(r"REL-[0-9]+", r.stdout)))
        self.assertEqual(listed_ids, ["REL-2", "REL-3"], r.stdout)
        r = repo.ledger("--release", "v1.0.0")
        self.assertEqual(sorted(set(re.findall(r"REL-[0-9]+", r.stdout))), ["REL-1"], "the first tag: from the start")
        r = repo.ledger("--release", "v9.9.9")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("v9.9.9", r.stdout + r.stderr)
        self.assertNotIn("Traceback", r.stderr)



class LedgerRound1Test(LedgerCase):
    """LEDGER-005 round 1: the review's and the breaker's findings (ESC-121..127), each first as a failing test."""

    def test_LEDGER_005_S8_ESC_121_a_value_with_newlines_does_not_escape_the_60_line_bound(self):
        repo = GitRepo(self.tmp)
        repo.plan("UXC-113")
        old = repo.commit("feat: the old export\n\nNo-story: docs")
        repo.commit("chore: corrections\n\nNo-story: docs", {CORR: corrections(toml_row(commit=old, evidence="x\n" * 100))})
        repo.publish()
        lines = show(self, repo, "UXC-113").splitlines()
        self.assertLessEqual(len(lines), 60, "\n".join(lines))

    def test_LEDGER_005_S4_ESC_126_next_fails_closed_when_a_story_is_unknown(self):
        repo = GitRepo(self.tmp)
        repo.plan("A-1", "A-2")
        repo.publish()
        clone = self.tmp / "partial"
        repo.run(["git", "-C", str(repo.bare), "config", "uploadpack.allowfilter", "true"], self.tmp)
        repo.run(["git", "clone", "-q", "--filter=blob:none", "--no-checkout", f"file://{repo.bare}", str(clone)], self.tmp)
        part = GitRepo(self.tmp, existing=clone)
        r = part.ledger("next")
        self.assertNotIn("Traceback", r.stderr)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("A-1", r.stdout + r.stderr, "the unknown stories are named, never silently left out")

    def test_LEDGER_005_S5_ESC_123_a_trailer_value_that_is_not_an_id_is_unknown_story(self):
        repo = GitRepo(self.tmp)
        repo.plan("A-1")
        since = repo.commit("chore: adopt\n\nNo-story: harness")
        lower = repo.commit("x\n\nbody\n\nStory: a-1")
        tbd = repo.commit("y\n\nbody\n\nPart-of: TBD")
        repo.publish()
        repo.state(f'[ledger]\nsince = "{since}"\n')
        data = ledger_check(self, repo)
        self.assertIn(lower[:7], details(data, "UNKNOWN_STORY"))
        self.assertIn(tbd[:7], details(data, "UNKNOWN_STORY"))
        self.assertIn("UNKNOWN_STORY", codes(data, "error"))

    def test_LEDGER_005_S7_ESC_124_release_lists_a_story_that_entered_and_was_reverted_later(self):
        repo = GitRepo(self.tmp)
        repo.plan("A-1")
        done = repo.commit("feat: A-1\n\nWhy.\n\nStory: A-1")
        repo.tag("v1.0.0")
        repo.revert(done)
        repo.publish()
        repo.git("push", "-q", "origin", "--tags")
        r = repo.ledger("--release", "v1.0.0")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("A-1", r.stdout)
        self.assertIn("1 story", r.stdout, "singular")

    def test_LEDGER_005_S5_ESC_125_a_squash_that_lost_its_story_line_behind_a_part_of_is_reported(self):
        repo = GitRepo(self.tmp)
        repo.plan("A-1")
        since = repo.commit("chore: adopt\n\nNo-story: harness")
        squash = repo.commit("Add login (#12)\n\n* land login\n\ndecided X\n\nStory: A-1\n\n* fix typo\n\nPart-of: A-1")
        repo.publish()
        repo.state(f'[ledger]\nsince = "{since}"\n')
        data = ledger_check(self, repo)
        self.assertIn(squash[:7], details(data, "SQUASH_LOST_TRAILERS"))

    def github_merges(self, *messages: str) -> tuple[GitRepo, str, list[str], list[str]]:
        """A branch with `messages`, the trunk moving on meanwhile, the trunk synced into the branch with a
        trailerless merge, and the branch merged with GitHub's trailerless "Merge pull request" commit."""
        repo = GitRepo(self.tmp)
        repo.plan("A-1", "A-2")
        since = repo.commit("chore: adopt\n\nNo-story: harness")
        work = repo.on_branch("a-1", *messages, keep=True)
        repo.commit("feat: A-2\n\nWhy.\n\nStory: A-2")
        repo.git("checkout", "-q", "a-1")
        sync = repo.merge("main", "Merge remote-tracking branch 'origin/main' into a-1")
        repo.git("checkout", "-q", "main")
        pr = repo.merge("a-1", "Merge pull request #13 from someone/a-1")
        repo.publish()
        repo.state(f'[ledger]\nsince = "{since}"\n')
        return repo, since, work, [sync, pr]

    def test_ESC_130_ESC_134_a_trailerless_merge_of_attributed_commits_is_attributed(self):
        repo, _, _, (sync, pr) = self.github_merges("wip\n\nPart-of: A-1", "feat: A-1\n\nWhy.\n\nStory: A-1")
        data = ledger_check(self, repo)
        self.assertNotIn("UNATTRIBUTED", codes(data), data["diffs"])
        self.assertEqual(read_json(self, repo)["unattributed"]["commits"], 0, "the facts agree")

    def test_ESC_131_a_merge_that_brings_an_unattributed_commit_still_reports_it(self):
        repo, _, (good, loose), (sync, pr) = self.github_merges("wip\n\nPart-of: A-1", "chore: loose")
        data = ledger_check(self, repo)
        found = details(data, "UNATTRIBUTED")
        self.assertIn(loose[:7], found)
        self.assertIn(pr[:7], found, "the merge brings an unattributed commit")
        self.assertNotIn(good[:7], found)
        self.assertNotIn(sync[:7], found, "the sync brings only the trunk's attributed commit")

    def test_ESC_132_a_merge_bringing_nothing_new_is_attributed(self):
        repo = GitRepo(self.tmp)
        repo.plan("A-1")
        since = repo.commit("chore: adopt\n\nNo-story: harness")
        repo.git("checkout", "-q", "-b", "a-1")
        repo.commit("wip\n\nPart-of: A-1")
        repo.git("checkout", "-q", "main")
        repo.git("merge", "-q", "--no-ff", "-s", "ours", "-m", "Merge branch 'a-1'", "a-1",
                 when=repo.next_date())
        repo.git("checkout", "-q", "a-1")
        sync = repo.merge("main", "Merge branch 'main' into a-1")
        repo.git("checkout", "-q", "main")
        repo.git("merge", "-q", "--ff-only", "a-1")
        repo.publish()
        repo.state(f'[ledger]\nsince = "{since}"\n')
        data = ledger_check(self, repo)
        self.assertNotIn(sync[:7], details(data, "UNATTRIBUTED"), data["diffs"])

    def test_ESC_133_a_trailer_outside_the_last_paragraph_says_where_it_must_go(self):
        repo = GitRepo(self.tmp)
        repo.plan("A-1")
        since = repo.commit("chore: adopt\n\nNo-story: harness")
        apart = repo.commit("fix: x\n\nWhy.\n\nPart-of: A-1\n\nCo-Authored-By: C <c@example.com>")
        repo.publish()
        repo.state(f'[ledger]\nsince = "{since}"\n')
        found = details(ledger_check(self, repo), "SQUASH_LOST_TRAILERS")
        self.assertIn(apart[:7], found)
        self.assertIn("last paragraph", found)
        self.assertIn("same final paragraph", found)

    def test_LEDGER_005_S1_ESC_127_show_prints_no_terminal_control_characters(self):
        repo = GitRepo(self.tmp)
        repo.plan("A-1")
        repo.commit("evil \x1b]0;PWNED\x07 subj\n\nbody \x1b[2J here\n\nStory: A-1")
        repo.publish()
        out = show(self, repo, "A-1")
        self.assertFalse(re.search(r"[\x00-\x08\x0b-\x1f\x7f]", out), repr(out))
        self.assertIn("subj", out)

    def test_LEDGER_005_logic_round_1_minor_findings(self):
        """A plain hyphen ends a No-story category; an empty No-story is only UNATTRIBUTED; a multi-line subject and
        git's own trailer-block lines are not a body."""
        repo = GitRepo(self.tmp)
        repo.plan("A-1", "A-2")
        since = repo.commit("chore: adopt\n\nNo-story: harness")
        repo.commit("docs: typo\n\nNo-story: docs-typo")
        empty = repo.commit("chore: x\n\nNo-story:")
        picked = repo.commit("feat: A-1\n\nStory: A-1\n(cherry picked from commit " + "a" * 40 + ")")
        two = repo.commit("feat: A-2\nsecond subject line\n\nStory: A-2")
        repo.publish()
        repo.state(f'[ledger]\nsince = "{since}"\n')
        data = ledger_check(self, repo)
        self.assertEqual(codes(data, "error").count("BAD_CATEGORY"), 0, data["diffs"])
        self.assertIn(empty[:7], details(data, "UNATTRIBUTED"))
        self.assertIn(picked[:7], details(data, "STORY_NO_BODY"))
        self.assertIn(two[:7], details(data, "STORY_NO_BODY"))

    def test_LEDGER_005_dx_show_names_a_candidate_only_without_a_version(self):
        repo = GitRepo(self.tmp)
        repo.plan("A-1")
        repo.commit("feat: A-1\n\nWhy.\n\nStory: A-1")
        repo.tag("v1.0.0")
        repo.commit("docs: x\n\nNo-story: docs")
        repo.tag("v1.1.0-rc.1")
        repo.publish()
        repo.git("push", "-q", "origin", "--tags")
        out = show(self, repo, "A-1")
        self.assertIn("v1.0.0", out)
        self.assertNotIn("v1.1.0-rc.1", out)


ARCHIVE = re.compile(r"refs/heads/archive/auth-002-[0-9]{8}(-[0-9]+)?")
TEMPLATE_PRE_PUSH = REPO / "template/.githooks/pre-push"
VERIFY_TOOLS = REPO / "template/.keelokit/bin/verify_tools.py"


class LedgerTakeDropCase(LedgerCase):
    """LEDGER-008: take (the story this worktree works on, in its own config) and drop (an abandoned attempt
    pushed to archive/<id>-<YYYYMMDD>, or to the current branch when archive/ is refused)."""

    def project(self) -> GitRepo:
        repo = GitRepo(self.tmp)
        repo.plan("AUTH-001", "AUTH-002", "AUTH-003")
        repo.commit("feat: AUTH-001\n\nStory: AUTH-001")
        repo.publish()
        repo.git("checkout", "-q", "-b", "claude/session-x")
        return repo

    def story_of(self, cwd: Path) -> str | None:
        r = subprocess.run(["git", "config", "--get", "keelokit.story"], cwd=cwd, env=clean_env(self.tmp),
                           capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else None

    def archived(self, repo: GitRepo) -> list[tuple[str, str]]:
        """(sha, ref) of every archive/ branch of AUTH-002 on origin."""
        out = repo.git("ls-remote", "origin", "refs/heads/archive/*")
        return [(line.split()[0], line.split()[1]) for line in out.splitlines() if line.split()]

    def message(self, repo: GitRepo, sha: str) -> str:
        return repo.git("log", "-1", "--format=%B", sha)


class LedgerTakeTest(LedgerTakeDropCase):
    def test_LEDGER_008_S1_take_is_per_worktree(self):
        repo = self.project()
        second = self.tmp / "trees" / "second"  # both worktrees live in this test's temp dir
        repo.git("worktree", "add", "-q", "-b", "other", str(second))
        r = repo.ledger("take", "AUTH-002")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.story_of(repo.path), "AUTH-002")
        self.assertIsNone(self.story_of(second), "the second worktree has no story")
        self.assertEqual(repo.git("config", "--get", "extensions.worktreeConfig").strip(), "true")
        self.assertNotIn("keelokit", repo.git("config", "--local", "--list"), "never in the clone's shared config")

    def test_LEDGER_008_S1_take_clear_removes_it_and_is_quiet_when_nothing_is_set(self):
        repo = self.project()
        self.assertEqual(repo.ledger("take", "AUTH-002").returncode, 0)
        r = repo.ledger("take", "--clear")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIsNone(self.story_of(repo.path))
        self.assertEqual(repo.ledger("take", "--clear").returncode, 0, "clearing twice is fine")

    def test_LEDGER_008_S2_take_refuses_a_story_already_on_the_trunk(self):
        repo = self.project()
        r = repo.ledger("take", "AUTH-001")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("AUTH-001", r.stdout + r.stderr)
        self.assertIn("on-trunk", r.stdout + r.stderr)
        self.assertIsNone(self.story_of(repo.path))

    def test_LEDGER_008_S2_take_refuses_an_id_that_is_no_story(self):
        repo = self.project()
        r = repo.ledger("take", "NOPE-001")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("NOPE-001", r.stdout + r.stderr)
        self.assertIsNone(self.story_of(repo.path))
        for bad in (["take"], ["take", "AUTH-002", "AUTH-003"], ["take", "--bogus"], ["take", "AUTH-002", "--clear"]):
            with self.subTest(bad=bad):
                self.assertEqual(repo.ledger(*bad).returncode, 2)

    def test_LEDGER_008_S3_take_warns_about_another_branch_and_still_sets_it(self):
        repo = self.project()
        repo.git("checkout", "-q", "main")
        repo.on_branch("claude/other-session", "feat: half of AUTH-002\n\nPart-of: AUTH-002")
        repo.git("fetch", "-q", "origin")
        repo.git("checkout", "-q", "claude/session-x")
        r = repo.ledger("take", "AUTH-002")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("claude/other-session", r.stdout + r.stderr)
        self.assertEqual(self.story_of(repo.path), "AUTH-002")
        quiet = repo.ledger("take", "AUTH-003")
        self.assertNotIn("claude/other-session", quiet.stdout + quiet.stderr, "no warning for a story nobody has")

    def test_LEDGER_008_S3_its_own_branch_is_not_another_branch(self):
        repo = self.project()
        repo.commit("feat: half of AUTH-002\n\nPart-of: AUTH-002")
        repo.git("push", "-q", "origin", "claude/session-x")
        r = repo.ledger("take", "AUTH-002")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("claude/session-x", r.stdout + r.stderr)


class LedgerDropTest(LedgerTakeDropCase):
    REASON = "the API it needs is not there yet"

    def hooks(self, repo: GitRepo) -> Path:
        """The template's pre-push on, and a pnpm that records every call (and fails, so a verify shows)."""
        (repo.path / ".githooks").mkdir()
        shutil.copyfile(TEMPLATE_PRE_PUSH, repo.path / ".githooks/pre-push")
        (repo.path / ".githooks/pre-push").chmod(0o755)
        shutil.copyfile(VERIFY_TOOLS, repo.path / ".keelokit/bin/verify_tools.py")
        with (repo.path / ".git/info/exclude").open("a") as f:
            f.write("/.githooks/\n")
        repo.git("config", "core.hooksPath", ".githooks")
        stubs = self.tmp / "stubs"
        stubs.mkdir()
        self.calls = self.tmp / "pnpm-calls"
        (stubs / "pnpm").write_text(f'#!/bin/sh\necho "pnpm $*" >> "{self.calls}"\nexit 1\n')
        (stubs / "pnpm").chmod(0o755)
        return stubs

    def test_LEDGER_008_S4_drop_pushes_to_archive_without_verify(self):
        repo = self.project()
        repo.commit("feat: a first try at AUTH-002\n\nPart-of: AUTH-002")
        stubs = self.hooks(repo)
        self.assertEqual(repo.ledger("take", "AUTH-002").returncode, 0)
        r = repo.ledger("drop", "AUTH-002", "--motivo", self.REASON, path=f"{stubs}:{os.environ['PATH']}")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(self.calls.exists() and self.calls.read_text().strip(), "the pre-push ran no verify")
        archived = self.archived(repo)
        self.assertEqual(len(archived), 1, archived)
        sha, ref = archived[0]
        self.assertRegex(ref, ARCHIVE)
        message = self.message(repo, sha)
        self.assertTrue(message.startswith("drop(AUTH-002): "), message)
        self.assertIn(self.REASON, message)
        self.assertEqual(repo.git("log", "-1", "--format=%(trailers:key=Dropped,valueonly)", sha).strip(), "AUTH-002")
        self.assertEqual(repo.git("diff-tree", "--no-commit-id", "-r", sha).strip(), "", "an empty commit")
        show = repo.ledger("show", "AUTH-002")
        self.assertEqual(show.returncode, 0, show.stderr)
        self.assertIn(self.REASON, show.stdout)
        self.assertIn(ref.removeprefix("refs/heads/"), show.stdout)
        attempts = self.stories(repo)["AUTH-002"]["attempts"]
        self.assertEqual([a["commit"] for a in attempts], [sha])
        self.assertIn(self.REASON, attempts[0]["reason"])

    def test_LEDGER_008_S4_a_second_drop_the_same_day_gets_its_own_archive_branch(self):
        repo = self.project()
        for n in (1, 2):
            r = repo.ledger("drop", "AUTH-002", "--motivo", f"try {n} failed")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        refs = [ref for _, ref in self.archived(repo)]
        self.assertEqual(len(set(refs)), 2, refs)
        self.assertEqual(len(self.stories(repo)["AUTH-002"]["attempts"]), 2)

    def test_LEDGER_008_S4_drop_refuses_an_unknown_story_or_an_empty_reason(self):
        repo = self.project()
        before = repo.sha()
        for args in (["drop", "NOPE-001", "--motivo", "x"], ["drop", "AUTH-002", "--motivo", "  "]):
            with self.subTest(args=args):
                r = repo.ledger(*args)
                self.assertNotEqual(r.returncode, 0, r.stdout)
        for bad in (["drop", "AUTH-002"], ["drop", "--motivo", "x"], ["drop", "AUTH-002", "--reason", "x"]):
            with self.subTest(bad=bad):
                self.assertEqual(repo.ledger(*bad).returncode, 2)
        self.assertEqual(repo.sha(), before, "no commit")
        self.assertEqual(self.archived(repo), [])

    def test_LEDGER_008_S4_drop_leaves_staged_work_out_of_its_commit(self):
        repo = self.project()
        repo.write("staged.txt", "half\n")
        repo.git("add", "staged.txt")
        r = repo.ledger("drop", "AUTH-002", "--motivo", self.REASON)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(repo.git("diff-tree", "--no-commit-id", "-r", self.archived(repo)[0][0]).strip(), "")
        self.assertIn("staged.txt", repo.git("diff", "--cached", "--name-only"), "still staged, not committed")

    def test_LEDGER_008_S5_drop_falls_back_to_the_current_branch_when_archive_is_refused(self):
        repo = self.project()
        hook = repo.bare / "hooks/pre-receive"
        hook.write_text('#!/bin/sh\nwhile read old new ref; do case $ref in refs/heads/archive/*) '
                        'echo "archive/ is not yours" >&2; exit 1;; esac; done\n')
        hook.chmod(0o755)
        self.assertEqual(repo.ledger("take", "AUTH-002").returncode, 0)
        r = repo.ledger("drop", "AUTH-002", "--motivo", self.REASON)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.archived(repo), [])
        tip = repo.git("ls-remote", "origin", "refs/heads/claude/session-x").split()[0]
        self.assertIn(self.REASON, self.message(repo, tip))
        self.assertIn("claude/session-x", r.stdout + r.stderr, "it says where the commit went")
        attempts = self.stories(repo)["AUTH-002"]["attempts"]
        self.assertEqual([a["commit"] for a in attempts], [tip])
        self.assertEqual(attempts[0]["branches"], ["claude/session-x"])
        self.assertIsNone(self.story_of(repo.path))

    def test_LEDGER_008_S5_drop_never_falls_back_to_the_trunk(self):
        repo = self.project()
        repo.git("checkout", "-q", "main")
        hook = repo.bare / "hooks/pre-receive"
        hook.write_text('#!/bin/sh\nwhile read old new ref; do case $ref in refs/heads/archive/*) exit 1;; esac; done\n')
        hook.chmod(0o755)
        trunk = repo.git("ls-remote", "origin", "refs/heads/main").split()[0]
        r = repo.ledger("drop", "AUTH-002", "--motivo", self.REASON)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(repo.git("ls-remote", "origin", "refs/heads/main").split()[0], trunk)

    def test_LEDGER_008_S6_drop_and_landing_clear_the_story(self):
        repo = self.project()
        self.assertEqual(repo.ledger("take", "AUTH-002").returncode, 0)
        self.assertEqual(repo.ledger("drop", "AUTH-002", "--motivo", self.REASON).returncode, 0)
        self.assertIsNone(self.story_of(repo.path), "drop clears it")
        # Landing: build-story runs `take --clear` once the story is on the trunk, and says so.
        self.assertEqual(repo.ledger("take", "AUTH-003").returncode, 0)
        self.assertEqual(repo.ledger("take", "--clear").returncode, 0)
        self.assertIsNone(self.story_of(repo.path), "take --clear clears it")
        skill = (REPO / "skills/build-story/SKILL.md").read_text()
        land = skill[skill.index("## 7. Land"):skill.index("## Report")]
        self.assertIn("ledger.py take --clear", land)
        self.assertIn("ledger.py take <ID>", skill[skill.index("## 1. Pick"):skill.index("## 2. Contract")])
        self.assertIn("ledger.py drop <ID>", skill)
        brief = (REPO / "template/.keelokit/harness/agent-brief.md").read_text()
        for command in ("ledger.py take <ID>", "ledger.py drop <ID>", "ledger.py take --clear"):
            self.assertIn(command, brief)


if __name__ == "__main__":
    unittest.main()
