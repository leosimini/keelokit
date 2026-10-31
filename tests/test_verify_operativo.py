"""The operational side of `pnpm verify`: run state, the green seal, --keep-going, --preflight, tools that must
exist, signals, a busy machine, --since and the routing of a change to the steps it needs. A fixture repo with
a bare origin and a stub pnpm; the real verify.sh and verify_tools.py. Run: python3 -m unittest discover -s tests"""
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

T = Path(__file__).resolve().parents[1] / "template"

PNPM = """#!/bin/sh
printf '%s\\n' "pnpm $*" >> "$CALLS"
case "$*" in *"ls --depth"*) exit 0 ;; esac
if [ -n "${SLEEP_ON:-}" ] && printf '%s' "$*" | grep -q -- "$SLEEP_ON"; then sleep 30; fi
if [ -n "${FAIL_ON:-}" ] && printf '%s' "$*" | grep -q -- "$FAIL_ON"; then echo "${FAIL_MSG:-boom}"; exit 1; fi
exit 0
"""
PY = """#!/bin/sh
case "$1" in .keelokit/bin/doctor.py|.keelokit/bin/audit.py) printf '%s\\n' "python3 $*" >> "$CALLS"; exit 0 ;; esac
exec {real} "$@"
"""


def sh(cwd, *cmd):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if r.returncode:
        raise AssertionError(f"{cmd}: {r.stdout}{r.stderr}")
    return r.stdout.strip()


class VerifyFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.origin = self.tmp / "origin.git"
        sh(self.tmp, "git", "init", "-q", "--bare", "-b", "main", str(self.origin))
        self.repo = self.tmp / "repo"
        sh(self.tmp, "git", "clone", "-q", str(self.origin), str(self.repo))
        sh(self.repo, "git", "config", "user.email", "t@t")
        sh(self.repo, "git", "config", "user.name", "T")
        for rel, text in {"package.json": '{"name":"root","private":true}\n', "pnpm-lock.yaml": "x\n", "docs/notes.md": "# n\n",
                          "apps/web/src/a.ts": "export {}\n", ".gitignore": "calls.txt\n"}.items():
            (self.repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / rel).write_text(text)
        (self.repo / "scripts").mkdir()
        shutil.copy(T / "scripts/verify.sh", self.repo / "scripts/verify.sh")
        (self.repo / ".keelokit/bin").mkdir(parents=True)
        shutil.copy(T / ".keelokit/bin/verify_tools.py", self.repo / ".keelokit/bin/verify_tools.py")
        shutil.copy(T / ".keelokit/verify-routing.toml", self.repo / ".keelokit/verify-routing.toml")
        sh(self.repo, "git", "add", "-A")
        sh(self.repo, "git", "commit", "-qm", "init")
        sh(self.repo, "git", "push", "-q", "origin", "HEAD:main")
        sh(self.repo, "git", "branch", "-q", "--set-upstream-to=origin/main")
        sh(self.repo, "git", "fetch", "-q", "origin")
        self.shims = self.tmp / "shims"
        self.shims.mkdir()
        (self.shims / "pnpm").write_text(PNPM)
        (self.shims / "python3").write_text(PY.format(real=sys.executable))
        for f in self.shims.iterdir():
            f.chmod(0o755)
        self.calls = self.tmp / "calls.txt"
        self.git_dir = self.repo / ".git"

    def commit_change(self, rel="apps/web/src/a.ts", text="export const a = 1\n"):
        (self.repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (self.repo / rel).write_text(text)
        sh(self.repo, "git", "add", "-A")
        sh(self.repo, "git", "commit", "-qm", f"change {rel}")

    def env(self, **extra):
        path = f"{self.shims}{os.pathsep}/usr/bin{os.pathsep}/bin"
        return {**{k: v for k, v in os.environ.items() if k not in ("KEELOKIT_ALLOW_MISSING", "VERIFY_FORCE")},
                "PATH": path, "CALLS": str(self.calls), "KEELOKIT_ALLOW_MISSING": "gitleaks semgrep", **extra}

    def verify(self, *flags, **extra):
        self.calls.write_text("") if not self.calls.exists() else None
        return subprocess.run(["bash", "scripts/verify.sh", *flags], cwd=self.repo, capture_output=True, text=True,
                              env=self.env(**extra), timeout=60)

    def called(self):
        return self.calls.read_text().splitlines() if self.calls.exists() else []

    def state(self):
        return dict(l.split("=", 1) for l in (self.git_dir / "keelokit-verify.state").read_text().splitlines())


class StateAndSealTest(VerifyFixture):
    def test_a_green_run_leaves_state_seal_and_history(self):
        self.commit_change()
        r = self.verify()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.state()["state"], "pass")
        self.assertTrue((self.git_dir / "keelokit-verify.seal").exists())
        self.assertIn('"result": "pass"', (self.git_dir / "keelokit-verify.history").read_text())
        self.assertIn("Time per step", r.stdout)

    def test_the_seal_skips_the_identical_rerun_and_only_that(self):
        self.commit_change()
        self.assertEqual(self.verify().returncode, 0)
        self.calls.write_text("")
        again = self.verify("--use-seal")
        self.assertIn("already passed", again.stdout)
        self.assertEqual(self.called(), [], "the sealed commit must not run anything again")
        # a new commit invalidates it
        self.commit_change(text="export const a = 2\n")
        self.assertNotIn("already passed", self.verify("--use-seal").stdout)
        # an edit in the working tree invalidates it too
        (self.repo / "docs/notes.md").write_text("# edited\n")
        self.assertNotIn("already passed", self.verify("--use-seal").stdout)

    def test_a_base_that_moved_invalidates_the_seal(self):
        self.commit_change()
        self.assertEqual(self.verify().returncode, 0)
        other = self.tmp / "other"
        sh(self.tmp, "git", "clone", "-q", str(self.origin), str(other))
        (other / "docs/more.md").write_text("m\n")
        sh(other, "git", "add", "-A")
        sh(other, "git", "-c", "user.email=t@t", "-c", "user.name=T", "commit", "-qm", "main moved")
        sh(other, "git", "push", "-q", "origin", "HEAD:main")
        sh(self.repo, "git", "rebase", "-q", "origin/main") if False else None
        r = self.verify("--use-seal")
        self.assertNotIn("already passed", r.stdout)  # and the run itself refuses: this branch lacks origin/main
        self.assertEqual(r.returncode, 1)
        self.assertIn("origin/main has commits this branch lacks", r.stdout)

    def test_the_seal_of_a_changed_scope_does_not_cover_all(self):
        self.commit_change()
        self.assertEqual(self.verify().returncode, 0)
        r = self.verify("--use-seal", "--all", VERIFY_FORCE="1")
        self.assertNotIn("already passed", r.stdout)

    def test_a_failed_run_leaves_no_seal_and_names_the_known_cause(self):
        self.commit_change()
        r = self.verify(FAIL_ON="run test", FAIL_MSG="FATAL ERROR: JavaScript heap out of memory")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.state()["state"], "fail")
        self.assertFalse((self.git_dir / "keelokit-verify.seal").exists())
        self.assertIn("Known causes seen in this log", r.stdout)
        self.assertIn("[heap]", r.stdout)

    def test_no_seal_without_a_clean_tree_or_with_since(self):
        self.commit_change()
        (self.repo / "docs/untracked.md").write_text("u\n")
        self.assertEqual(self.verify().returncode, 0)
        self.assertFalse((self.git_dir / "keelokit-verify.seal").exists())
        (self.repo / "docs/untracked.md").unlink()
        self.assertEqual(self.verify("--since", "origin/main").returncode, 0)
        self.assertFalse((self.git_dir / "keelokit-verify.seal").exists())


class KeepGoingAndPreflightTest(VerifyFixture):
    def test_without_keep_going_the_first_red_stops_the_run(self):
        self.commit_change()
        r = self.verify(FAIL_ON="lint")
        self.assertEqual(r.returncode, 1)
        self.assertFalse(any("run test" in c for c in self.called()), "tests must not run after a red lint")

    def test_keep_going_runs_the_independent_steps_and_lists_every_red(self):
        self.commit_change()
        r = self.verify("--keep-going", FAIL_ON="lint\\|run test")
        self.assertEqual(r.returncode, 1)
        self.assertIn("verify found reds in:", r.stdout)
        self.assertIn("Lint", r.stdout.split("verify found reds in:")[1])
        self.assertIn("Unit tests", r.stdout.split("verify found reds in:")[1])
        self.assertTrue(any("run build" in c for c in self.called()), "later independent steps still ran")
        self.assertFalse((self.git_dir / "keelokit-verify.seal").exists())

    def test_preflight_runs_the_cheap_checks_and_not_the_tests(self):
        self.commit_change()
        r = self.verify("--preflight")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("preflight passed", r.stdout)
        calls = self.called()
        self.assertTrue(any("lint" in c for c in calls))
        self.assertFalse(any("run test" in c or "run build" in c or "run e2e" in c for c in calls))
        self.assertFalse((self.git_dir / "keelokit-verify.seal").exists())
        self.assertFalse((self.git_dir / "keelokit-verify.lock").exists())

    def test_preflight_fails_on_a_red(self):
        self.commit_change()
        self.assertEqual(self.verify("--preflight", FAIL_ON="typecheck").returncode, 1)


class ToolsSignalsAndMachineTest(VerifyFixture):
    def test_a_missing_required_tool_fails_the_run(self):
        self.commit_change()
        r = subprocess.run(["bash", "scripts/verify.sh"], cwd=self.repo, capture_output=True, text=True, timeout=60,
                           env={**self.env(), "KEELOKIT_ALLOW_MISSING": ""})
        self.assertEqual(r.returncode, 4, r.stdout + r.stderr)
        self.assertIn("gitleaks is not installed, and the CI runs it", r.stderr)
        self.assertIn("KEELOKIT_ALLOW_MISSING=gitleaks", r.stderr)

    def test_an_allowed_missing_tool_is_a_note_not_a_failure(self):
        self.commit_change()
        r = self.verify()
        self.assertEqual(r.returncode, 0)
        self.assertIn("gitleaks not installed; skipped on purpose", r.stdout)

    def test_a_killed_verify_exits_non_zero_says_so_and_stops_its_children(self):
        self.commit_change()
        p = subprocess.Popen(["bash", "scripts/verify.sh"], cwd=self.repo, env=self.env(SLEEP_ON="run test"),
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                if "Unit tests" in self.state().get("step", "") and any("run test" in c for c in self.called()):
                    break
            except (OSError, ValueError):
                pass
            time.sleep(0.2)
        else:
            p.kill()
            self.fail("verify never reached the unit tests")
        p.send_signal(signal.SIGTERM)
        out, err = p.communicate(timeout=20)
        self.assertEqual(p.returncode, 143, out + err)
        self.assertIn("stopped by signal TERM at step 'Unit tests'", err)
        self.assertEqual(self.state()["state"], "fail")
        self.assertEqual(self.state()["rc"], "143")
        self.assertFalse((self.git_dir / "keelokit-verify.seal").exists())
        for _ in range(20):  # the group is told to stop as verify exits; give the child a moment to go
            if subprocess.run(["pgrep", "-f", "^sleep 30"], capture_output=True).returncode == 1:
                break
            time.sleep(0.1)
        else:
            self.fail("the stub's sleep outlived the killed verify")

    def test_all_will_not_start_on_a_busy_machine_and_force_overrides(self):
        self.commit_change()
        r = self.verify("--all", VERIFY_MAX_LOAD_FACTOR="0")
        self.assertEqual(r.returncode, 3)
        self.assertIn("will not start", r.stderr)
        self.assertEqual(self.called(), [])
        self.assertEqual(self.verify("--all", VERIFY_MAX_LOAD_FACTOR="0", VERIFY_FORCE="1").returncode, 0)

    def test_since_compares_with_the_ref_it_is_given(self):
        self.commit_change()
        first = sh(self.repo, "git", "rev-parse", "HEAD~1")
        r = self.verify("--since", first)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(any(f"...[{first}]" in c for c in self.called()), self.called())
        self.assertEqual(subprocess.run(["bash", "scripts/verify.sh", "--since"], cwd=self.repo, capture_output=True, text=True).returncode, 2)


class RoutingTest(VerifyFixture):
    def test_a_docs_only_change_runs_no_tests_build_or_e2e(self):
        self.commit_change("docs/guide.md", "# guide\n")
        r = self.verify()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Plan for this change: format", r.stdout)
        calls = self.called()
        self.assertFalse(any(("run test" in c or "run build" in c or "run e2e" in c or "run typecheck" in c or " lint" in c) for c in calls), calls)
        self.assertIn("not needed for this change", r.stdout)

    def test_code_runs_everything(self):
        self.commit_change()
        r = self.verify()
        self.assertTrue(any("run test" in c for c in self.called()))
        self.assertNotIn("Plan for this change", r.stdout)

    def test_an_unknown_file_runs_everything_and_says_why(self):
        self.commit_change("tools/thing.xyz", "?\n")
        r = self.verify()
        self.assertIn("match no route", r.stderr + r.stdout)
        self.assertTrue(any("run test" in c for c in self.called()))

    def test_all_is_every_step_even_for_docs(self):
        self.commit_change("docs/guide.md", "# guide\n")
        self.verify("--all", VERIFY_FORCE="1")
        self.assertTrue(any("run test" in c for c in self.called()))


if __name__ == "__main__":
    unittest.main()
