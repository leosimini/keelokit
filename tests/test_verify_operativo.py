"""The operational side of `pnpm verify`: run state, the green seal, --keep-going, --preflight, tools that must
exist, signals, a busy machine, --since and the routing of a change to the steps it needs. A fixture repo with
a bare origin and a stub pnpm; the real verify.sh and verify_tools.py. Run: python3 -m unittest discover -s tests"""
import json
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
case "$*" in *"ls --depth"*) [ -z "${LS_OUT:-}" ] || printf '%s\n' $LS_OUT; exit 0 ;; esac
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

    def history(self):
        return [json.loads(l) for l in (self.git_dir / "keelokit-verify.history").read_text().splitlines()]


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


class StepsTest(VerifyFixture):
    """HARN-005: `--steps` runs the named steps and nothing more, never seals, and refuses unknown names."""

    def test_HARN_005_S1_only_the_named_steps_run(self):
        self.commit_change()
        r = self.verify("--steps", "unit")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        calls = self.called()
        self.assertTrue(any("run test" in c for c in calls), calls)
        for other in ("lint", "run typecheck", "run build", "run e2e", "prettier", "doctor.py", "audit.py"):
            self.assertFalse(any(other in c for c in calls), f"{other} ran: {calls}")
        self.assertIn("Only these steps: unit", r.stdout)

    def test_HARN_005_S2_an_unknown_name_is_an_error_before_anything_runs(self):
        self.commit_change()
        r = self.verify("--steps", "unit,e2e-stak")
        self.assertEqual(r.returncode, 2)
        self.assertIn("unknown step(s) e2e-stak", r.stderr)
        self.assertEqual(self.called(), [])
        self.assertEqual(self.verify("--steps").returncode, 2)
        self.assertEqual(self.verify("--steps", "unit", "--preflight").returncode, 2)
        self.assertEqual(self.verify("--steps", "clock").returncode, 2, "clock without --all would run nothing")

    def test_HARN_005_S3_never_sealed_but_state_and_history_are_written(self):
        self.commit_change()
        self.assertEqual(self.verify("--steps", "unit,doctor").returncode, 0)
        self.assertFalse((self.git_dir / "keelokit-verify.seal").exists())
        self.assertEqual(self.state()["state"], "pass")
        entry = self.history()[-1]
        self.assertTrue(entry["partial"])
        self.assertEqual(entry["planned"], ["doctor", "unit"])
        self.assertIn("python3 .keelokit/bin/doctor.py --ci", self.called())
        # a sealed commit doesn't skip a partial run either
        self.assertEqual(self.verify().returncode, 0)
        self.assertNotIn("already passed", self.verify("--use-seal", "--steps", "unit").stdout)

    def test_HARN_005_S4_combines_with_since_all_and_keep_going(self):
        self.commit_change()
        first = sh(self.repo, "git", "rev-parse", "HEAD~1")
        self.assertEqual(self.verify("--steps", "unit", "--since", first).returncode, 0)
        self.assertTrue(any(f"...[{first}]" in c and "run test" in c for c in self.called()), self.called())
        self.calls.write_text("")
        self.assertEqual(self.verify("--steps", "unit", "--all", VERIFY_FORCE="1").returncode, 0)
        self.assertTrue(any(c.startswith("pnpm -r ") and "run test" in c for c in self.called()), self.called())
        r = self.verify("--steps", "lint,unit", "--keep-going", FAIL_ON="lint\\|run test")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(sorted(self.history()[-1]["failed_steps"]), ["lint", "unit"])


class RerunFailedTest(VerifyFixture):
    """HARN-006: `--rerun-failed` repeats what the last red run didn't pass, plus what new files call for."""

    def ran(self, *needles):
        calls = self.called()
        return {n: any(n in c for c in calls) for n in needles}

    def test_HARN_006_S1_repeats_the_red_step_and_what_never_ran(self):
        self.commit_change()
        self.assertEqual(self.verify(FAIL_ON="run build").returncode, 1)
        self.assertEqual(self.history()[-1]["failed_steps"], ["build"])
        self.calls.write_text("")
        r = self.verify("--rerun-failed")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Rerun of what failed or never ran", r.stdout)
        self.assertEqual(self.ran("run build", "run e2e", "audit.py", "lint", "run typecheck", "run test"),
                         {"run build": True, "run e2e": True, "audit.py": True,
                          "lint": False, "run typecheck": False, "run test": False})

    def seal(self):
        path = self.git_dir / "keelokit-verify.seal"
        return dict(l.split("=", 1) for l in path.read_text().splitlines()) if path.exists() else None

    def test_HARN_006_S8_a_rerun_that_completes_the_red_run_seals_the_commit(self):
        self.commit_change()
        red = sh(self.repo, "git", "rev-parse", "HEAD")
        self.assertEqual(self.verify(FAIL_ON="run build").returncode, 1)
        r = self.verify("--rerun-failed")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Composite seal", r.stdout)
        self.assertEqual(self.seal()["head"], red)
        self.assertEqual(self.seal()["level"], "changed")
        self.assertEqual(self.seal()["composite_of"], red)
        entry = self.history()[-1]
        self.assertEqual(entry["composite_of"], red)
        self.assertFalse(entry["partial"])
        self.assertIn("unit", entry["inherited"])
        self.calls.write_text("")
        self.assertIn("already passed", self.verify("--use-seal").stdout)
        self.assertEqual(self.called(), [])

    def test_HARN_006_S8_a_fix_routed_to_another_step_runs_it_and_still_seals(self):
        self.commit_change()
        red = sh(self.repo, "git", "rev-parse", "HEAD")
        self.assertEqual(self.verify(FAIL_ON="run build").returncode, 1)
        self.commit_change("docs/fix.md", "# the fix's notes\n")  # routed to format, which had passed
        fixed = sh(self.repo, "git", "rev-parse", "HEAD")
        self.calls.write_text("")
        r = self.verify("--rerun-failed")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        # format for the new file; lint, doctor and secrets read the whole repo; nothing per package (docs/ is in none)
        self.assertEqual(self.ran("prettier", "run build", "doctor.py", "lint", "audit.py", "run test", "run typecheck"),
                         {"prettier": True, "run build": True, "doctor.py": True, "lint": True, "audit.py": True,
                          "run test": False, "run typecheck": False})
        self.assertEqual((self.seal()["head"], self.seal()["composite_of"]), (fixed, red))
        self.assertNotIn("format", self.history()[-1]["inherited"])

    def test_HARN_006_S8_a_fix_inside_a_package_reruns_every_per_package_step(self):
        """A locale file routes to format, lint, typecheck and unit, but e2e asserts its texts: inside a package,
        every pass that runs per package is dropped and run again, so the seal covers what a verify would."""
        self.commit_change()
        self.assertEqual(self.verify("--keep-going", FAIL_ON="run test").returncode, 1)
        self.commit_change("apps/web/src/i18n/locales/en.json", '{"hi": "hello"}\n')
        self.calls.write_text("")
        r = self.verify("--rerun-failed")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.ran("run test", "run build", "run e2e", "run typecheck"),
                         {"run test": True, "run build": True, "run e2e": True, "run typecheck": True})
        self.assertIsNotNone(self.seal())
        # and a red e2e there is caught, not sealed over
        self.commit_change("apps/web/src/i18n/locales/en.json", '{"hi": "hola"}\n')
        self.assertEqual(self.verify("--rerun-failed", FAIL_ON="run e2e").returncode, 1)

    def test_HARN_006_S8_passes_that_depend_on_the_date_are_never_kept(self):
        self.commit_change()
        self.assertEqual(self.verify("--all", "--keep-going", FAIL_ON="run e2e", VERIFY_FORCE="1").returncode, 1)
        self.calls.write_text("")
        r = self.verify("--all", "--rerun-failed", VERIFY_FORCE="1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(self.ran("audit.py")["audit.py"], "the advisories may have changed since the red run")
        self.assertTrue(self.ran("doctor.py")["doctor.py"], "an exception may have expired since the red run")
        self.assertEqual(self.seal()["level"], "all")

    def test_HARN_006_S9_no_seal_when_the_red_run_covered_no_packages_and_now_some(self):
        """An empty package list is a list: it must not read as "this run kept nothing"."""
        self.commit_change()
        self.assertEqual(self.verify(FAIL_ON="run build").returncode, 1)  # the stub's ls: no packages
        r = self.verify("--rerun-failed", LS_OUT=str(self.repo / "apps/web"))
        self.assertIn("apps/web came into scope after the red run", r.stdout)
        self.assertIsNone(self.seal())
        self.assertEqual(self.history()[-1]["proven_packages"], [])

    def test_HARN_006_S9_no_seal_when_the_runs_do_not_cover_the_plan(self):
        """A red --steps run planned only its steps; a rerun of it proves those, not the commit."""
        self.commit_change()
        self.assertEqual(self.verify("--steps", "lint", FAIL_ON="lint").returncode, 1)
        r = self.verify("--rerun-failed")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("No seal: the steps", r.stdout)
        self.assertIsNone(self.seal())
        self.assertTrue(self.history()[-1]["partial"])
        self.assertIsNone(self.history()[-1]["composite_of"])

    def test_HARN_006_S9_no_seal_when_a_package_came_into_scope_after_the_red_run(self):
        self.commit_change()
        web, x = str(self.repo / "apps/web"), str(self.repo / "packages/x")
        self.assertEqual(self.verify(FAIL_ON="run build", LS_OUT=web).returncode, 1)
        r = self.verify("--rerun-failed", LS_OUT=f"{web} {x}")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("packages/x came into scope after the red run", r.stdout)
        self.assertIsNone(self.seal())

    def test_HARN_006_S9_no_seal_on_a_dirty_tree_or_with_since(self):
        self.commit_change()
        self.assertEqual(self.verify(FAIL_ON="run build").returncode, 1)
        (self.repo / "docs/scratch.md").write_text("u\n")
        self.verify("--rerun-failed")
        self.assertIsNone(self.seal())

    def test_HARN_006_S2_keep_going_reds_are_all_repeated(self):
        self.commit_change()
        self.assertEqual(self.verify("--keep-going", FAIL_ON="lint\\|run test").returncode, 1)
        self.calls.write_text("")
        self.assertEqual(self.verify("--rerun-failed").returncode, 0)
        self.assertEqual(self.ran("lint", "run test", "run typecheck", "run build"),
                         {"lint": True, "run test": True, "run typecheck": False, "run build": False})

    def test_HARN_006_S3_a_new_commit_adds_what_its_files_call_for(self):
        self.commit_change()
        self.assertEqual(self.verify(FAIL_ON="run build").returncode, 1)
        self.commit_change("docs/fix.md", "# fixed\n")  # routed to format only
        self.calls.write_text("")
        self.assertEqual(self.verify("--rerun-failed").returncode, 0)
        self.assertEqual(self.ran("run build", "prettier", "run test"), {"run build": True, "prettier": True, "run test": False})
        # code goes everywhere: no narrowing, and it says so
        self.assertEqual(self.verify(FAIL_ON="run build").returncode, 1)
        self.commit_change("apps/web/src/b.ts", "export const b = 1\n")
        self.calls.write_text("")
        r = self.verify("--rerun-failed")
        self.assertIn("can't narrow the run", r.stderr)
        self.assertTrue(self.ran("run test")["run test"])

    def test_HARN_006_S4_without_a_red_run_it_is_the_normal_verify_and_says_why(self):
        self.commit_change()
        r = self.verify("--rerun-failed")
        self.assertIn("no verify history", r.stderr)
        self.assertTrue(self.ran("run test", "lint")["run test"])
        self.assertTrue((self.git_dir / "keelokit-verify.seal").exists(), "a normal green verify seals")
        r = self.verify("--rerun-failed")
        self.assertIn("passed: nothing failed", r.stderr)

    def test_HARN_006_S5_an_all_run_is_only_narrowed_with_all(self):
        self.commit_change()
        self.assertEqual(self.verify("--all", FAIL_ON="run build", VERIFY_FORCE="1").returncode, 1)
        self.calls.write_text("")
        self.assertEqual(self.verify("--rerun-failed", "--all", FAIL_ON="run build", VERIFY_FORCE="1").returncode, 1)
        self.assertEqual(self.ran("run build", "run test"), {"run build": True, "run test": False})
        self.assertIn("rerun it with --all", self.verify("--rerun-failed").stderr)

    def test_HARN_006_S5_a_narrower_red_does_not_narrow_an_all_request(self):
        self.commit_change()
        self.assertEqual(self.verify(FAIL_ON="run build").returncode, 1)
        self.calls.write_text("")
        r = self.verify("--rerun-failed", "--all", VERIFY_FORCE="1")
        self.assertIn("its passes don't cover an --all request", r.stderr)
        self.assertTrue(self.ran("run test")["run test"])

    def test_HARN_006_S6_a_red_run_on_a_dirty_tree_is_not_narrowed(self):
        """The history keeps the commit, not the edits the run saw: reverting them must not leave a pass behind."""
        self.commit_change()
        (self.repo / "apps/web/src/a.ts").write_text("export const a = 'uncommitted fix'\n")
        self.assertEqual(self.verify(FAIL_ON="run build").returncode, 1)
        sh(self.repo, "git", "checkout", "--", "apps/web/src/a.ts")
        self.calls.write_text("")
        r = self.verify("--rerun-failed")
        self.assertIn("uncommitted or untracked changes", r.stderr)
        self.assertTrue(self.ran("run test")["run test"])

    def test_HARN_006_S7_a_step_that_ran_twice_and_failed_once_is_not_passed(self):
        """e2e-stack runs once per app under one name: web green, mobile red is a red e2e-stack."""
        self.commit_change()
        head = sh(self.repo, "git", "rev-parse", "HEAD")
        base = sh(self.repo, "git", "rev-parse", "origin/main")
        history = self.git_dir / "keelokit-verify.history"
        env = {**os.environ, "VERIFY_BASE": base, "VERIFY_CLEAN": "true",
               "VERIFY_PLANNED": "unit e2e-stack audit", "VERIFY_PASSED": "unit e2e-stack ",
               "VERIFY_FAILED_STEPS": " e2e-stack "}
        subprocess.run([sys.executable, ".keelokit/bin/verify_tools.py", "record", str(history), "fail", "1", head,
                        "changed", "", "", ""], cwd=self.repo, env=env, check=True)
        self.assertEqual(self.history()[-1]["passed"], ["unit"])
        out = subprocess.run([sys.executable, ".keelokit/bin/verify_tools.py", "rerun", str(history), "--head", head,
                              "--base", base, "--scope", "", "--level", "changed"],
                             cwd=self.repo, capture_output=True, text=True, check=True).stdout.strip().split("|")
        self.assertEqual(out[0].split(), ["e2e-stack", "audit"])
        self.assertEqual(out[1].split(), ["unit"], "the passes it keeps: not e2e-stack")


class PackagesAndHistoryTest(VerifyFixture):
    """HARN-007: an explicit package scope, and the packages each run covered in the history."""

    def test_HARN_007_S1_packages_and_their_dependents_instead_of_the_changed_ones(self):
        (self.repo / "packages/x").mkdir(parents=True)
        (self.repo / "packages/x/package.json").write_text('{"name":"x"}\n')
        (self.repo / "apps/web/package.json").write_text('{"name":"web"}\n')
        self.commit_change()
        r = self.verify("--packages", "./packages/x,apps/web/")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        tests = [c for c in self.called() if "run test" in c]
        self.assertEqual(len(tests), 1, self.called())
        self.assertIn("--filter ...{./packages/x} --filter ...{./apps/web}", tests[0])
        self.assertNotIn("...[origin/main]", tests[0])
        self.assertFalse((self.git_dir / "keelokit-verify.seal").exists())
        self.assertEqual(self.verify("--packages", "./nope").returncode, 2)

    def test_HARN_007_S2_a_filter_goes_to_pnpm_as_is_and_must_select_something(self):
        self.commit_change()
        r = self.verify("--filter", "@demo/web")
        self.assertEqual(r.returncode, 2)
        self.assertIn("--filter @demo/web selects no package", r.stderr)
        r = self.verify("--filter", "@demo/web", LS_OUT=str(self.repo / "apps/web"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(any("--filter @demo/web" in c and "run test" in c for c in self.called()), self.called())
        self.assertEqual(self.history()[-1]["scope"], "--filter @demo/web")

    def test_HARN_007_S3_the_history_says_which_packages_a_run_covered(self):
        self.commit_change()
        self.assertEqual(self.verify(LS_OUT=f"{self.repo / 'apps/web'} {self.repo / 'packages/shared'}").returncode, 0)
        entry = self.history()[-1]
        self.assertEqual(entry["packages"], ["apps/web", "packages/shared"])
        self.assertEqual(entry["step_packages"].get("lint"), ["."])
        self.assertEqual(len(entry["head"]), 40)
        self.assertEqual(entry["base"], sh(self.repo, "git", "rev-parse", "origin/main"))
        self.assertIn("unit", entry["passed"])


class SharedSealTest(VerifyFixture):
    """HARN-008: `--use-seal` also accepts a seal another machine pushed to git ([verify] shared_seals)."""

    SPEC = 'origin/harbor/log:harbor/seals/{head}.toml'

    def setUp(self):
        super().setUp()
        (self.repo / ".keelokit/state.toml").write_text(f'[verify]\nshared_seals = "{self.SPEC}"\n')
        self.commit_change()

    def publish(self, **fields):
        """Push a seal for HEAD to origin's harbor/log from another clone, as Harbor would."""
        head = sh(self.repo, "git", "rev-parse", "HEAD")
        seal = {"head": f'"{head}"', "base": f'"{sh(self.repo, "git", "rev-parse", "origin/main")}"',
                "exit": "0", "level": '"changed"', **fields}
        other = self.tmp / "harbor"
        if not other.exists():
            sh(self.tmp, "git", "clone", "-q", str(self.origin), str(other))
            sh(other, "git", "checkout", "-q", "--orphan", "harbor/log")
            sh(other, "git", "rm", "-rqf", ".")
        (other / "harbor/seals").mkdir(parents=True, exist_ok=True)
        (other / f"harbor/seals/{head}.toml").write_text("".join(f"{k} = {v}\n" for k, v in seal.items()))
        sh(other, "git", "add", "-A")
        sh(other, "git", "-c", "user.email=t@t", "-c", "user.name=T", "commit", "-qm", "seal", "--allow-empty")
        sh(other, "git", "push", "-qf", "origin", "HEAD:refs/heads/harbor/log")

    def test_HARN_008_S1_a_seal_from_another_machine_skips_the_run(self):
        self.publish()
        r = self.verify("--use-seal")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("already passed a changed verify", r.stdout)
        self.assertIn("whoever can push to that branch", r.stdout)
        self.assertEqual(self.called(), [])

    def test_HARN_008_S2_every_condition_is_checked_and_a_refusal_says_why(self):
        for fields, why, flags in [
            ({"head": '"' + "0" * 40 + '"'}, "its head is another commit", ()),
            ({"base": f'"{sh(self.repo, "git", "rev-parse", "HEAD")}"'}, "its base is not origin/main now", ()),
            ({"exit": "1"}, "its exit is not 0", ()),
            ({"exit": "0.0"}, "its exit is not 0", ()),
            ({"exit": "false"}, "its exit is not 0", ()),
            ({"level": '"changed"'}, "its level doesn't cover this request", ("--all",)),
        ]:
            with self.subTest(why=why):
                self.publish(**fields)
                (self.git_dir / "keelokit-verify.seal").unlink(missing_ok=True)  # only the shared one may apply
                self.calls.write_text("")
                r = self.verify("--use-seal", *flags, VERIFY_FORCE="1")
                self.assertIn(why, r.stdout)
                self.assertNotIn("already passed", r.stdout)
                self.assertTrue(any("run test" in c for c in self.called()))

    def test_HARN_008_S3_a_dirty_tree_a_missing_seal_or_no_seal_flag_runs(self):
        self.assertIn("can't fetch origin/harbor/log", self.verify("--use-seal").stdout)
        self.publish(head='"x"')
        sh(self.repo, "git", "commit", "-q", "--allow-empty", "-m", "another commit, no seal for it")
        self.assertIn("no seal for this commit there", self.verify("--use-seal").stdout)
        (self.git_dir / "keelokit-verify.seal").unlink(missing_ok=True)
        self.publish()
        (self.repo / "docs/notes.md").write_text("# edited\n")
        self.assertIn("the working tree has changes", self.verify("--use-seal").stdout)
        sh(self.repo, "git", "checkout", "--", "docs/notes.md")
        self.assertNotIn("already passed", self.verify("--use-seal", KEELOKIT_NO_SEAL="1").stdout)
        self.assertNotIn("already passed", self.verify("--use-seal", "--steps", "unit").stdout)

    def test_HARN_008_S4_without_the_key_nothing_changes(self):
        (self.repo / ".keelokit/state.toml").write_text("[gates]\n")
        sh(self.repo, "git", "commit", "-qam", "no shared seals")
        r = self.verify("--use-seal")
        self.assertNotIn("shared seal", r.stdout + r.stderr)
        self.assertTrue(any("run test" in c for c in self.called()))


class ConvoyBranchVerifyTest(VerifyFixture):
    """HARN-011: under convoy a session verifies its branch with a plain `pnpm verify`, which covers what
    `--since origin/main` does and seals, so the branch push (the hook's --use-seal) doesn't repeat it."""

    def on_a_branch(self):
        sh(self.repo, "git", "checkout", "-q", "-b", "auth-003")
        self.commit_change()

    def test_HARN_011_S1_a_plain_verify_has_the_scope_of_since_origin_main(self):
        self.on_a_branch()
        self.assertEqual(self.verify().returncode, 0)
        plain = self.called()
        self.calls.write_text("")
        (self.git_dir / "keelokit-audit-ok").unlink(missing_ok=True)  # a green audit is reused for 24 h
        self.assertEqual(self.verify("--since", "origin/main").returncode, 0)
        self.assertEqual(plain, self.called())
        self.assertTrue(any("...[origin/main]" in c for c in plain), plain)

    def test_HARN_011_S2_the_branch_push_does_not_run_it_again(self):
        self.on_a_branch()
        self.assertEqual(self.verify().returncode, 0)
        self.calls.write_text("")
        r = self.verify("--use-seal")  # what the pre-push hook runs on `git push origin HEAD:auth-003`
        self.assertIn("already passed", r.stdout)
        self.assertEqual(self.called(), [])
        # --since never seals: the push would run the whole verify again
        (self.git_dir / "keelokit-verify.seal").unlink()
        self.assertEqual(self.verify("--since", "origin/main").returncode, 0)
        self.calls.write_text("")
        self.assertNotIn("already passed", self.verify("--use-seal").stdout)
        self.assertTrue(self.called())


class StableTestsTest(VerifyFixture):
    """HARN-015: what most reds that weren't bugs taught, as defaults and known causes."""

    ROOT = T.parent

    def test_HARN_015_S1_verify_gives_node_a_bigger_heap_unless_one_is_chosen(self):
        (self.shims / "pnpm").write_text('#!/bin/sh\nprintf "NODE_OPTIONS=%s\\n" "$NODE_OPTIONS" >> "$CALLS"\nexit 0\n')
        self.commit_change()
        self.assertEqual(self.verify(NODE_OPTIONS="").returncode, 0)
        self.assertIn("NODE_OPTIONS=--max-old-space-size=4096", self.called())
        self.calls.write_text("")
        self.verify(NODE_OPTIONS="--use-openssl-ca")  # other options are kept
        self.assertIn("NODE_OPTIONS=--max-old-space-size=4096 --use-openssl-ca", self.called())
        self.calls.write_text("")
        self.verify(NODE_OPTIONS="--max-old-space-size=8192 --enable-source-maps")
        self.assertIn("NODE_OPTIONS=--max-old-space-size=8192 --enable-source-maps", self.called())
        self.assertNotIn("4096", " ".join(self.called()))

    def test_HARN_015_S2_the_reds_that_were_not_bugs_are_known_causes(self):
        logs = {
            "worker-exit": "A worker process has failed to exit gracefully and has been force exited",
            "hook-timeout": 'Error: Hook timed out in 10000ms.',
            "shared-rows": "Invalid `prisma.booking.create()` invocation: Unique constraint failed on the fields: (`slug`)",
            "unbuilt-package": "Error: Cannot find module '@demo/shared' from 'src/app.ts'",
            "unhandled": "Vitest caught 1 unhandled error during the test run. Unhandled Rejection",
            "db-exists": 'ERROR:  database "app_w1" already exists',
        }
        for cid, log in logs.items():
            with self.subTest(cause=cid):
                path = self.tmp / f"{cid}.log"
                path.write_text(f"some output\n{log}\nmore\n")
                out = subprocess.run([sys.executable, str(T / ".keelokit/bin/verify_tools.py"), "causes", str(path)],
                                     capture_output=True, text=True).stdout
                self.assertIn(f"[{cid}]", out)

    def test_HARN_015_S3_integration_files_run_one_at_a_time(self):
        config = (T / "apps/api/vitest.integration.config.ts").read_text()
        self.assertIn("fileParallelism: false", config)

    def test_HARN_015_S4_the_verifier_writes_tests_that_stay_green(self):
        verifier = (self.ROOT / "agents/verifier.md").read_text()
        for rule in ("only your own data", "global table", "never `sleep`", "fixed clock", "final state",
                     "teardown wins", "reaches every consumer"):
            self.assertIn(rule, verifier)
        self.assertIn("tests that stay green", (T / ".keelokit/harness/execution-protocol.md").read_text())


class ZonesTest(VerifyFixture):
    """HARN-018: the unit tests a change adds or edits run again at the clocks where date code breaks."""

    FAKETIME = """#!/bin/sh
printf 'faketime TZ=%s %s\\n' "$TZ" "$1" >> "$CALLS"
shift
exec "$@"
"""

    def setUp(self):
        super().setUp()
        (self.repo / "apps/web/package.json").write_text('{"name":"web","scripts":{"test":"vitest run"}}\n')
        (self.repo / "apps/mobile/src").mkdir(parents=True)
        (self.repo / "apps/mobile/package.json").write_text('{"name":"mobile","scripts":{"test":"jest --forceExit"}}\n')
        sh(self.repo, "git", "add", "-A")
        sh(self.repo, "git", "commit", "-qm", "packages")
        sh(self.repo, "git", "push", "-q", "origin", "HEAD:main")
        sh(self.repo, "git", "fetch", "-q", "origin")
        (self.shims / "faketime").write_text(self.FAKETIME)
        (self.shims / "faketime").chmod(0o755)

    def clocks(self):
        return [c for c in self.called() if c.startswith("faketime ")]

    def test_HARN_018_S1_a_changed_unit_test_runs_at_every_clock(self):
        self.commit_change("apps/web/src/a.test.ts", "it('a', () => {})\n")
        self.commit_change("apps/mobile/src/b.test.tsx", "it('b', () => {})\n")
        r = self.verify()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Changed tests at awkward clocks", r.stdout)
        clocks = self.clocks()
        self.assertEqual(len(clocks), 12, clocks)  # 6 scenarios x 2 packages
        self.assertIn("faketime TZ=America/New_York 2027-03-14 02:30:00", clocks)
        self.assertIn("faketime TZ=Europe/Berlin 2028-02-29 00:30:00", clocks)
        self.assertIn("pnpm exec vitest run src/a.test.ts", self.called())
        self.assertIn("pnpm exec jest src/b.test.tsx", self.called())

    def test_HARN_018_S2_only_changed_unit_tests_and_only_with_faketime(self):
        self.commit_change("apps/web/src/c.ts", "export const c = 1\n")  # code, no test
        self.commit_change("apps/api/src/d.integration.spec.ts", "it('d', () => {})\n")  # not a unit test
        r = self.verify()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.clocks(), [])
        self.commit_change("apps/web/src/a.test.ts", "it('a', () => {})\n")
        (self.shims / "faketime").unlink()
        r = self.verify()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("faketime not installed", r.stdout)

    def test_HARN_018_S3_the_project_names_its_own_clocks(self):
        (self.repo / ".keelokit/verify-clock.toml").write_text(
            '[[scenario]]\nname = "market-close"\nzone = "America/Sao_Paulo"\nat = "2027-11-30 23:59:00"\n')
        self.commit_change("apps/web/src/a.test.ts", "it('a', () => {})\n")
        self.assertEqual(self.verify().returncode, 0)
        self.assertEqual(self.clocks(), ["faketime TZ=America/Sao_Paulo 2027-11-30 23:59:00"])

    def test_HARN_018_S4_a_red_at_one_clock_is_a_red_verify(self):
        self.commit_change("apps/web/src/a.test.ts", "it('a', () => {})\n")
        r = self.verify(FAIL_ON="exec vitest")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.history()[-1]["failed_steps"], ["zones"])
        self.assertFalse((self.git_dir / "keelokit-verify.seal").exists())


class IntegrationResumeTest(VerifyFixture):
    """HARN-019: a red integration step reruns only the specs that failed and what the fix reaches."""

    # pnpm: logs its call; an integration run (whole or narrowed) writes the Vitest JSON report it was
    # asked for, with the specs named in INT_FAIL (relative to apps/api) failed, and then fails.
    PNPM = """#!{python}
import json, os, re, sys
args = sys.argv[1:]
open(os.environ["CALLS"], "a").write("pnpm " + " ".join(args) + "\\n")
if "ls" in args and "--depth" in args:
    print(os.environ.get("LS_OUT", "")); sys.exit(0)
out = next((a.split("=", 1)[1] for a in args if a.startswith("--outputFile.json=")), None)
fail = [f for f in os.environ.get("INT_FAIL", "").split(",") if f]
if out and os.environ.get("INT_UNHANDLED"):
    print("Vitest caught 1 unhandled error during the test run. Unhandled Errors")
if out:
    ran = [a for a in args if a.endswith(".integration.spec.ts")] or ["src/a.integration.spec.ts", "src/b.integration.spec.ts"]
    api = os.path.join(os.getcwd(), "apps/api")
    results = [{{"name": os.path.join(api, f), "status": "failed" if f in fail else "passed"}} for f in ran]
    json.dump({{"testResults": results}}, open(out, "w"))
    sys.exit(1 if any(r["status"] == "failed" for r in results) else 0)
sys.exit(0)
"""
    DOCKER = """#!/bin/sh
case "$1" in
  run) echo cid ;;
  port) echo 127.0.0.1:55432 ;;
esac
exit 0
"""

    def setUp(self):
        super().setUp()
        files = {"apps/api/package.json": '{"name":"api","scripts":{"test:integration":"vitest run --config vitest.integration.config.ts"}}\n',
                 "apps/api/src/svc.ts": "export const svc = 1\n",
                 "apps/api/src/a.integration.spec.ts": "it('a', () => {})\n",
                 "apps/api/src/b.integration.spec.ts": "it('b', () => {})\n",
                 "docker-compose.yml": "services:\n  postgres:\n    image: postgres:16\n"}
        for rel, text in files.items():
            (self.repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / rel).write_text(text)
        sh(self.repo, "git", "add", "-A")
        sh(self.repo, "git", "commit", "-qm", "an API")
        sh(self.repo, "git", "push", "-q", "origin", "HEAD:main")
        sh(self.repo, "git", "fetch", "-q", "origin")
        (self.shims / "pnpm").write_text(self.PNPM.format(python=sys.executable))
        (self.shims / "docker").write_text(self.DOCKER)
        for f in ("pnpm", "docker"):
            (self.shims / f).chmod(0o755)

    def run_verify(self, *flags, **extra):
        return self.verify(*flags, LS_OUT=str(self.repo / "apps/api"), **extra)

    def integration_calls(self):
        return [c for c in self.called() if "integration" in c and ("vitest" in c or "test:integration" in c)]

    def red_at_integration(self):
        self.reds = getattr(self, "reds", 0) + 1
        self.commit_change("apps/api/src/svc.ts", f"export const svc = {self.reds + 100}\n")
        r = self.run_verify(INT_FAIL="src/a.integration.spec.ts")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        entry = self.history()[-1]
        self.assertEqual(entry["failed_steps"], ["integration"])
        self.assertEqual(entry["failed_specs"], ["apps/api/src/a.integration.spec.ts"])
        self.assertTrue(entry["int_complete"])

    def test_HARN_019_S1_the_fix_reruns_the_failed_specs_and_what_it_reaches(self):
        self.red_at_integration()
        self.commit_change("apps/api/src/svc.ts", "export const svc = 3\n")  # the fix, in the API's sources
        self.calls.write_text("")
        r = self.run_verify("--rerun-failed")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        calls = self.integration_calls()
        self.assertTrue(any("exec vitest run --config vitest.integration.config.ts" in c
                            and c.endswith("src/a.integration.spec.ts") for c in calls), calls)
        self.assertTrue(any("exec vitest related --run" in c and c.endswith("src/svc.ts") for c in calls), calls)
        self.assertFalse(any("test:integration" in c for c in calls), "not the whole suite")
        self.assertTrue(any("run test" in c for c in self.called()), "code changed: every other step runs again")

    def test_HARN_019_S2_a_spec_the_fix_changed_runs_too(self):
        self.red_at_integration()
        self.commit_change("apps/api/src/b.integration.spec.ts", "it('b2', () => {})\n")
        self.calls.write_text("")
        self.assertEqual(self.run_verify("--rerun-failed").returncode, 0)
        narrowed = [c for c in self.integration_calls() if "exec vitest run" in c]
        self.assertTrue(narrowed and narrowed[0].endswith("src/a.integration.spec.ts src/b.integration.spec.ts"), narrowed)

    def test_HARN_019_S3_a_fix_that_reaches_every_spec_runs_the_whole_suite(self):
        for rel in ("apps/api/prisma/schema.prisma", "apps/api/src/testing/setup.ts", "packages/shared/src/x.ts",
                    "apps/api/vitest.integration.config.ts"):
            with self.subTest(fix=rel):
                self.red_at_integration()
                self.commit_change(rel, f"// {rel}\n")
                self.calls.write_text("")
                r = self.run_verify("--rerun-failed")
                self.assertIn("can't narrow the run", r.stderr)
                self.assertTrue(any("test:integration" in c for c in self.integration_calls()), self.called())

    def test_HARN_019_S4_without_a_complete_record_it_is_the_whole_suite(self):
        self.commit_change("apps/api/src/svc.ts", "export const svc = 2\n")
        self.run_verify(FAIL_ON="nothing")  # green: no failed specs on record
        self.assertNotIn("failed_specs", self.history()[-1])
        self.run_verify(INT_FAIL="src/a.integration.spec.ts")
        (self.git_dir / "keelokit-verify.history").write_text(
            self.history_text().replace('"int_complete": true', '"int_complete": false'))
        self.commit_change("apps/api/src/svc.ts", "export const svc = 3\n")
        self.calls.write_text("")
        self.run_verify("--rerun-failed")
        self.assertTrue(any("test:integration" in c for c in self.integration_calls()), self.called())

    def test_HARN_019_S4_an_error_outside_any_spec_makes_the_record_incomplete(self):
        """Vitest lists the spec whose timer threw as passed: the failed specs don't account for the red."""
        self.commit_change("apps/api/src/svc.ts", "export const svc = 2\n")
        self.run_verify(INT_FAIL="src/a.integration.spec.ts", INT_UNHANDLED="1")
        self.assertFalse(self.history()[-1]["int_complete"])
        self.commit_change("apps/api/src/svc.ts", "export const svc = 3\n")
        self.calls.write_text("")
        self.run_verify("--rerun-failed")
        self.assertTrue(any("test:integration" in c for c in self.integration_calls()), self.called())

    def test_HARN_019_S5_a_rerun_that_keeps_a_narrowed_integration_pass_stays_narrowed(self):
        """R2 passed integration on some specs and failed e2e; R3 reruns e2e only and keeps R2's integration
        pass: R3 must still be `narrowed`, or another checkout would trust it as a full run."""
        head = sh(self.repo, "git", "rev-parse", "HEAD")
        base = sh(self.repo, "git", "rev-parse", "origin/main")
        names = ["secrets", "format", "lint", "typecheck", "doctor", "unit", "integration", "build", "e2e"]
        entry = {"head": head, "base": base, "level": "changed", "result": "fail", "partial": True, "clean": True,
                 "since": False, "scope": "", "narrowed": True, "planned": names, "inherited": [],
                 "passed": [n for n in names if n != "e2e"], "failed_steps": ["e2e"], "packages": []}
        (self.git_dir / "keelokit-verify.history").write_text(json.dumps(entry) + "\n")
        out = subprocess.run([sys.executable, ".keelokit/bin/verify_tools.py", "rerun",
                              str(self.git_dir / "keelokit-verify.history"), "--head", head, "--base", base,
                              "--scope", "", "--level", "changed"], cwd=self.repo, capture_output=True, text=True)
        fields = out.stdout.strip().split("|")
        self.assertIn("integration", fields[1].split(), out.stderr)
        self.assertEqual(fields[6], "1")

    def test_HARN_019_S5_a_narrowed_green_completes_the_red_run_and_seals(self):
        self.red_at_integration()
        red = sh(self.repo, "git", "rev-parse", "HEAD")
        self.commit_change("apps/api/src/svc.ts", "export const svc = 3\n")
        r = self.run_verify("--rerun-failed")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        seal = dict(l.split("=", 1) for l in (self.git_dir / "keelokit-verify.seal").read_text().splitlines())
        self.assertEqual(seal["composite_of"], red)
        # it seals this clone's push, but another checkout's proof needs a run that wasn't cut down
        self.assertTrue(self.history()[-1]["narrowed"])
        green = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, '.keelokit/bin'); "
                                "import verify_tools; print(len(verify_tools.green_runs()))"],
                               cwd=self.repo, capture_output=True, text=True).stdout.strip()
        self.assertEqual(green, "0")

    def history_text(self):
        return (self.git_dir / "keelokit-verify.history").read_text()


class PrePushFixture(VerifyFixture):
    """The template's pre-push hook on, real pushes to the fixture's origin, a stub pnpm."""

    def setUp(self):
        super().setUp()
        (self.repo / ".githooks").mkdir()
        shutil.copy(T / ".githooks/pre-push", self.repo / ".githooks/pre-push")
        (self.repo / ".githooks/pre-push").chmod(0o755)
        sh(self.repo, "git", "config", "core.hooksPath", ".githooks")

    def state(self, text, push=True):
        """Commit state.toml and push main, where the hook reads the key from."""
        (self.repo / ".keelokit/state.toml").write_text(text)
        sh(self.repo, "git", "add", "-A")
        sh(self.repo, "git", "commit", "-qm", "state")
        if push:
            self.push("main")

    def push(self, *refs):
        self.calls.write_text("")
        self.last = subprocess.run(["git", "push", "-q", "origin", *refs], cwd=self.repo, capture_output=True,
                                   text=True, env=self.env(), timeout=60)
        return self.last

    def verified(self):
        return any(c.startswith("pnpm verify") for c in self.called())

    def gated(self):
        """The push went through the gate: verified, or refused because it isn't the checked-out commit
        (HARN-013). Anything but the shared-seals exception ends in one of the two."""
        return self.verified() or (self.last.returncode != 0 and "pre-push: refused" in self.last.stderr)


class PrePushTest(PrePushFixture):
    """HARN-010: the pre-push hook verifies every push but one that updates nothing but the [verify]
    shared_seals branch (as origin/main configures it) with commits holding only files under the seals'
    folder, each seal naming a commit that passed a full verify here: Harbor's logbook, no code."""

    SPEC = "origin/harbor/log:harbor/seals/{head}.toml"

    def setUp(self):
        super().setUp()
        self.state(f'[verify]\nshared_seals = "{self.SPEC}"\n')

    def logbook(self, *files, contents=None):
        """A commit on the harbor/log branch holding `files` (paths), as Harbor writes its logbook."""
        sh(self.repo, "git", "checkout", "-q", "--orphan", "harbor/log")
        sh(self.repo, "git", "rm", "-rqf", ".")
        for rel in files:
            (self.repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / rel).write_text((contents or {}).get(rel, "x\n"))
        sh(self.repo, "git", "add", "-A")
        sh(self.repo, "git", "commit", "-qm", "logbook")
        sh(self.repo, "git", "checkout", "-q", "-f", "main")

    def append_logbook(self, text):
        """A new logbook write on top of the last one, so a push has a ref to send."""
        sh(self.repo, "git", "checkout", "-q", "harbor/log")
        (self.repo / "harbor/seals/abc.toml").write_text(text)
        sh(self.repo, "git", "commit", "-qam", "logbook")
        sh(self.repo, "git", "checkout", "-q", "-f", "main")

    def test_HARN_010_S1_a_push_of_only_the_seal_branch_is_not_verified(self):
        self.logbook("harbor/seals/abc.toml")
        r = self.push("harbor/log")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(self.verified(), self.called())
        self.assertIn("nothing to verify", r.stdout + r.stderr)
        self.assertTrue(sh(self.repo, "git", "ls-remote", "origin", "refs/heads/harbor/log"))

    def test_HARN_010_S2_the_seal_branch_with_any_other_ref_is_verified(self):
        self.logbook("harbor/seals/abc.toml")
        self.commit_change()
        self.push("harbor/log", "main")
        self.assertTrue(self.gated(), "the exception covers only a push of nothing but the seal branch")
        self.commit_change(text="export const a = 3\n")  # something new, or git sends no ref and the check proves nothing
        r = self.push("main")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(self.verified(), "a push of main (the checked-out commit) alone is verified as before")

    def test_HARN_010_S3_code_on_the_seal_branch_is_verified(self):
        self.logbook("harbor/seals/abc.toml", "apps/web/src/b.ts")
        self.push("harbor/log")
        self.assertTrue(self.gated(), "a commit with a file outside harbor/ is code")

    def test_HARN_010_S3_code_in_a_parent_of_the_logbook_commit_is_verified(self):
        """The tip holds only harbor/, but the commit under it brings code: every new commit counts."""
        self.commit_change("apps/web/src/evil.ts", "export const evil = 1\n")
        sh(self.repo, "git", "checkout", "-q", "-b", "sneak")
        sh(self.repo, "git", "rm", "-rqf", ".")
        (self.repo / "harbor/seals").mkdir(parents=True)
        (self.repo / "harbor/seals/abc.toml").write_text("x\n")
        sh(self.repo, "git", "add", "-A")
        sh(self.repo, "git", "commit", "-qm", "only harbor/ at the tip")
        sh(self.repo, "git", "checkout", "-q", "-f", "main")
        self.push("sneak:harbor/log")
        self.assertTrue(self.gated())

    def test_HARN_010_S5_a_seal_for_a_commit_that_never_passed_here_is_verified(self):
        head = sh(self.repo, "git", "rev-parse", "HEAD")
        base = sh(self.repo, "git", "rev-parse", "origin/main")
        seal = f"harbor/seals/{head}.toml"
        text = {seal: f'head = "{head}"\nbase = "{base}"\nexit = 0\nlevel = "changed"\n'}
        self.logbook(seal, contents=text)
        self.push("harbor/log")
        self.assertTrue(self.gated(), "no green run of that commit in this clone: the seal is not taken on trust")
        self.assertEqual(self.verify().returncode, 0)  # now it passes here
        sh(self.repo, "git", "checkout", "-q", "harbor/log")  # the next logbook write, on top of the last one
        (self.repo / seal).write_text(text[seal] + "# written again after the green run\n")
        sh(self.repo, "git", "commit", "-qam", "logbook")
        sh(self.repo, "git", "checkout", "-q", "-f", "main")
        r = self.push("harbor/log")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(self.verified(), self.called())
        # and an "all" seal needs an --all pass, which this clone doesn't have
        sh(self.repo, "git", "checkout", "-q", "harbor/log")
        (self.repo / seal).write_text(text[seal].replace('"changed"', '"all"'))
        sh(self.repo, "git", "commit", "-qam", "logbook")
        sh(self.repo, "git", "checkout", "-q", "-f", "main")
        self.push("harbor/log")
        self.assertTrue(self.gated())

    def seal_on_logbook(self, head, base, how):
        """Append, on top of the pushed logbook, a seal for `head`, the way `how` says."""
        seal = f"harbor/seals/{head}.toml"
        sh(self.repo, "git", "checkout", "-q", "harbor/log")
        if how == "merge":  # a merge whose own tree brings the seal; its parents add nothing
            sh(self.repo, "git", "checkout", "-q", "-b", "side")
            sh(self.repo, "git", "commit", "-q", "--allow-empty", "-m", "side")
            sh(self.repo, "git", "checkout", "-q", "harbor/log")
            sh(self.repo, "git", "merge", "-q", "--no-commit", "--no-ff", "side")
        (self.repo / seal).parent.mkdir(parents=True, exist_ok=True)
        (self.repo / seal).unlink(missing_ok=True)
        if how == "symlink":
            (self.repo / seal).symlink_to("../../apps/web/src/a.ts")
        else:
            (self.repo / seal).write_text(f'head = "{head}"\nbase = "{base}"\nexit = 0\nlevel = "changed"\n')
        sh(self.repo, "git", "add", "-A")
        sh(self.repo, "git", "commit", "-qm", f"seal ({how})")
        sh(self.repo, "git", "checkout", "-q", "-f", "main")

    def test_HARN_010_S5_merges_symlinks_and_runs_that_prove_less_back_no_seal(self):
        self.logbook("harbor/notes.md")
        self.push("harbor/log")
        base = sh(self.repo, "git", "rev-parse", "origin/main")
        self.commit_change()  # a red commit nobody verified
        red = sh(self.repo, "git", "rev-parse", "HEAD")
        self.seal_on_logbook(red, base, "merge")
        self.push("harbor/log")
        self.assertTrue(self.gated(), "a merge's seal is checked like any other")
        # passes that prove less than a verify don't back a seal: --since, or an uncommitted change
        self.assertEqual(self.verify("--since", "HEAD").returncode, 0)
        (self.repo / "docs/notes.md").write_text("# edited\n")
        self.assertEqual(self.verify().returncode, 0)
        sh(self.repo, "git", "checkout", "--", "docs/notes.md")
        self.push("harbor/log")
        self.assertTrue(self.gated())
        self.seal_on_logbook(red, base, "symlink")
        self.push("harbor/log")
        self.assertTrue(self.gated(), "a symlink is not a seal")

    def test_HARN_010_S4_without_the_key_or_with_main_as_the_seal_branch_everything_is_verified(self):
        self.logbook("harbor/seals/abc.toml")
        self.state("[gates]\n")
        self.push("harbor/log")
        self.assertTrue(self.gated())
        # an uncommitted (or unpushed) edit doesn't count: the key is read from origin/main
        self.append_logbook("edited\n")
        (self.repo / ".keelokit/state.toml").write_text(f'[verify]\nshared_seals = "{self.SPEC}"\n')
        self.push("harbor/log")
        self.assertTrue(self.gated())
        sh(self.repo, "git", "checkout", "-q", "--", ".keelokit/state.toml")
        # nor does a remote-tracking ref moved by hand: the hook fetches main before reading the key
        self.state(f'[verify]\nshared_seals = "{self.SPEC}"\n', push=False)
        sh(self.repo, "git", "update-ref", "refs/remotes/origin/main", "HEAD")
        self.append_logbook("moved by hand\n")
        self.push("harbor/log")
        self.assertTrue(self.gated())
        self.state('[verify]\nshared_seals = "origin/main:harbor/seals/{head}.toml"\n')
        self.commit_change(text="export const a = 4\n")
        self.push("main")
        self.assertTrue(self.gated(), "main can't be the seal branch")


class WipBranchesTest(PrePushFixture):
    """HARN-017: wip/<topic> branches carry unfinished work between sessions, unverified, and never land."""

    def setUp(self):
        super().setUp()
        self.state('[verify]\nwip_branches = "wip/"\n')

    def unfinished(self):
        """Half-done work on a topic branch, then main checked out again."""
        sh(self.repo, "git", "switch", "-qc", "topic")
        self.commit_change("apps/web/src/half.ts", "export const half = (\n")
        tip = sh(self.repo, "git", "rev-parse", "HEAD")
        return tip

    def test_HARN_017_S1_a_wip_push_runs_no_verify_and_says_it_cannot_land(self):
        tip = self.unfinished()
        r = self.push("HEAD:wip/topic")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(self.verified())
        self.assertIn("not verified, and it can't land", r.stdout)
        self.assertEqual(sh(self.repo, "git", "ls-remote", "origin", "refs/heads/wip/topic").split()[0], tip)

    def test_HARN_017_S2_a_push_holding_wip_work_is_refused_even_after_the_branch_is_gone(self):
        self.unfinished()
        self.push("HEAD:wip/topic")
        self.commit_change("apps/web/src/half.ts", "export const half = 1\n")  # finished on top of the wip commit
        r = self.push("HEAD:main")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("unverified wip work", r.stderr)
        self.assertFalse(self.verified(), "refused before any verify")
        self.push(":wip/topic")  # deleting the branch doesn't hide it: this clone remembers the tip
        sh(self.repo, "git", "fetch", "-q", "--prune", "origin")
        self.assertNotEqual(self.push("HEAD:main").returncode, 0)
        r = self.push("HEAD:feature")  # nor a branch that would carry it on
        self.assertIn("unverified wip work", r.stderr)

    def test_HARN_017_S3_wip_work_that_passed_a_verify_here_no_longer_blocks(self):
        self.unfinished()
        (self.repo / "apps/web/src/half.ts").write_text("export const half = 1\n")
        sh(self.repo, "git", "commit", "-qam", "finished")
        self.push("HEAD:wip/topic")
        self.assertEqual(self.verify().returncode, 0)  # the same commit, verified green and clean
        r = self.push("HEAD:main")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(self.verified())

    def test_HARN_017_S3_a_verified_commit_that_holds_red_wip_work_goes_through(self):
        self.unfinished()  # red: half.ts doesn't parse
        self.push("HEAD:wip/topic")
        self.commit_change("apps/web/src/half.ts", "export const half = 1\n")  # finished on top
        self.assertNotEqual(self.push("HEAD:main").returncode, 0, "not verified yet")
        self.assertIn("run pnpm verify on this commit", self.last.stderr)
        self.assertEqual(self.verify().returncode, 0)
        r = self.push("HEAD:main")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_HARN_017_S4_a_tracking_ref_moved_by_hand_opens_nothing(self):
        """Even without a fetch refspec, the key is read from the remote's main as it is now."""
        self.state("[gates]\n")
        sh(self.repo, "git", "config", "--unset-all", "remote.origin.fetch")
        (self.repo / ".keelokit/state.toml").write_text('[verify]\nwip_branches = "feat/"\n')
        sh(self.repo, "git", "commit", "-qam", "a local key")
        sh(self.repo, "git", "update-ref", "refs/remotes/origin/main", "HEAD")
        self.unfinished()
        r = self.push("HEAD:feat/x")
        self.assertNotIn("not verified", r.stdout)
        self.assertTrue(self.verified(), r.stdout + r.stderr)

    def test_HARN_017_S4_a_fetch_url_other_than_the_push_url_opens_nothing(self):
        """The key is read from where the push goes (pushurl), not from wherever `url` points."""
        self.state("[gates]\n")
        decoy = self.tmp / "decoy.git"
        sh(self.tmp, "git", "clone", "-q", "--bare", str(self.origin), str(decoy))
        work = self.tmp / "decoy-work"
        sh(self.tmp, "git", "clone", "-q", str(decoy), str(work))
        (work / ".keelokit/state.toml").write_text('[verify]\nwip_branches = "feat/"\n')
        sh(work, "git", "-c", "user.email=t@t", "-c", "user.name=T", "commit", "-qam", "a key on the decoy")
        sh(work, "git", "push", "-q", "origin", "HEAD:main")
        sh(self.repo, "git", "config", "remote.origin.pushurl", str(self.origin))
        sh(self.repo, "git", "config", "remote.origin.url", str(decoy))
        self.unfinished()
        r = self.push("HEAD:feat/y")
        self.assertNotIn("not verified", r.stdout)
        self.assertTrue(self.verified(), r.stdout + r.stderr)
        # nor rewriting rules: pushInsteadOf sends the push to the real remote, insteadOf its fetch to the decoy
        sh(self.repo, "git", "config", "--unset", "remote.origin.pushurl")
        sh(self.repo, "git", "config", "remote.origin.url", "alias:real")
        sh(self.repo, "git", "config", f"url.{self.origin}.pushInsteadOf", "alias:real")
        sh(self.repo, "git", "config", f"url.{decoy}.insteadOf", str(self.origin))
        r = self.push("HEAD:feat/z")
        self.assertNotIn("not verified", r.stdout)
        self.assertTrue(self.gated(), r.stdout + r.stderr)

    def test_HARN_017_S4_without_the_key_a_wip_branch_is_an_ordinary_branch(self):
        self.state("[gates]\n")
        self.unfinished()
        r = self.push("HEAD:wip/topic")
        self.assertTrue(self.verified(), r.stdout + r.stderr)
        # an uncommitted (or unpushed) key opens nothing: it is read from origin/main
        (self.repo / ".keelokit/state.toml").write_text('[verify]\nwip_branches = "wip/"\n')
        self.commit_change("apps/web/src/half.ts", "export const half = 2\n")
        r = self.push("HEAD:wip/topic")
        self.assertTrue(self.verified(), r.stdout + r.stderr)


class PushWhatIsCheckedOutTest(VerifyFixture):
    """HARN-013: the template's pre-push hook verifies what it pushes. Real pushes to the bare origin through
    the hook; `pnpm verify` runs the real verify.sh, and a step goes red when the tree holds a file RED."""

    PNPM_VERIFY = """#!/bin/sh
printf '%s\\n' "pnpm $*" >> "$CALLS"
case "$1" in verify) shift; exec bash scripts/verify.sh "$@" ;; esac
case "$*" in *"ls --depth"*) exit 0 ;; esac
[ ! -f RED ] || { echo "RED is red"; exit 1; }
exit 0
"""

    def setUp(self):
        super().setUp()
        (self.shims / "pnpm").write_text(self.PNPM_VERIFY)
        hooks = self.tmp / "hooks"
        hooks.mkdir()
        shutil.copy(T / ".githooks/pre-push", hooks / "pre-push")
        sh(self.repo, "git", "config", "core.hooksPath", str(hooks))
        self.commit_change()
        self.assertEqual(self.verify().returncode, 0)  # HEAD is green and sealed
        self.green = sh(self.repo, "git", "rev-parse", "HEAD")
        sh(self.repo, "git", "switch", "-qc", "red")
        self.commit_change("RED", "red\n")
        self.red = sh(self.repo, "git", "rev-parse", "HEAD")
        sh(self.repo, "git", "switch", "-q", "main")
        self.calls.write_text("")

    def push(self, *args):
        return subprocess.run(["git", "push", "origin", *args], cwd=self.repo, capture_output=True, text=True,
                              env=self.env(), timeout=60)

    def remote(self, ref="main"):
        r = subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{ref}"], cwd=self.origin,
                           capture_output=True, text=True)
        return r.stdout.strip() or None

    def test_HARN_013_S1_a_commit_other_than_head_is_refused(self):
        before = self.remote()
        for args in [(f"{self.red}:main",), ("red:main",), ("red",), ("HEAD:main", "red")]:
            with self.subTest(push=args):
                r = self.push(*args)
                self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertIn(f"would get {self.red[:7]}", r.stderr)
                self.assertIn("check it out and push from there", r.stderr)
                self.assertEqual(self.remote(), before)
                self.assertIsNone(self.remote("red"))
                self.assertEqual(self.called(), [])  # refused before any verify, even HEAD's sealed one

    def proven_branch(self):
        """A branch whose tip passed a clean, full verify here, then main checked out again."""
        sh(self.repo, "git", "switch", "-qc", "topic")
        self.commit_change("apps/web/src/topic.ts", "export const topic = 1\n")
        self.assertEqual(self.verify().returncode, 0)
        tip = sh(self.repo, "git", "rev-parse", "HEAD")
        sh(self.repo, "git", "switch", "-q", "main")
        self.calls.write_text("")
        return tip

    def test_HARN_016_S1_a_proven_commit_reaches_a_branch_from_another_checkout(self):
        tip = self.proven_branch()
        r = self.push("topic")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("already passed a clean, full verify here", r.stdout)
        self.assertEqual(self.called(), [], "proven: nothing runs, HEAD's verify included")
        self.assertEqual(self.remote("topic"), tip)

    def test_HARN_016_S2_never_to_main_and_never_without_proof(self):
        before = self.remote()
        tip = self.proven_branch()
        r = self.push("topic:main")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("check it out and push from there", r.stderr)
        self.assertEqual(self.remote(), before)
        r = self.push("red")  # no green run of that commit
        self.assertNotEqual(r.returncode, 0)
        self.assertIsNone(self.remote("red"))
        # a run that proves less doesn't count: --since, or a dirty tree
        sh(self.repo, "git", "switch", "-q", "red")
        sh(self.repo, "git", "rm", "-q", "RED")
        sh(self.repo, "git", "commit", "-qm", "fixed")
        self.assertEqual(self.verify("--since", "origin/main").returncode, 0)
        fixed = sh(self.repo, "git", "rev-parse", "HEAD")
        sh(self.repo, "git", "switch", "-q", "main")
        self.assertNotEqual(self.push(f"{fixed}:refs/heads/fixed").returncode, 0)
        self.assertIsNone(self.remote("fixed"))
        self.assertTrue(tip)

    def test_HARN_016_S3_a_moved_main_voids_the_proof(self):
        self.proven_branch()
        other = self.tmp / "other"
        sh(self.tmp, "git", "clone", "-q", str(self.origin), str(other))
        (other / "docs/more.md").write_text("m\n")
        sh(other, "git", "add", "-A")
        sh(other, "git", "-c", "user.email=t@t", "-c", "user.name=T", "commit", "-qm", "main moved")
        sh(other, "git", "push", "-q", "origin", "HEAD:main")  # a fresh clone: no hooks
        r = self.push("topic")
        self.assertNotEqual(r.returncode, 0, "proven against a main that has moved since")
        self.assertIsNone(self.remote("topic"))

    def test_HARN_016_S4_the_verify_compares_with_main_where_the_push_goes(self):
        """A fetch url pointing at a decoy whose main is HEAD would make the plan empty; the push url decides."""
        decoy = self.tmp / "decoy.git"
        sh(self.tmp, "git", "clone", "-q", "--bare", str(self.repo), str(decoy))  # its main is HEAD
        sh(self.repo, "git", "config", "remote.origin.pushurl", str(self.origin))
        sh(self.repo, "git", "config", "remote.origin.url", str(decoy))
        self.commit_change("apps/web/src/new.ts", "export const n = 1\n")
        sh(self.tmp, "git", "--git-dir", str(decoy), "fetch", "-q", str(self.repo), "+HEAD:refs/heads/main")
        self.calls.write_text("")
        r = self.push("HEAD:main")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(any("run test" in c for c in self.called()), "the real main lacks the change: tests run")
        # rewriting rules: the push goes to the real remote (pushInsteadOf turns the alias into it) while a
        # fetch of that URL would be sent to the decoy (insteadOf): refused, never trusted
        before = self.remote()
        sh(self.repo, "git", "config", "--unset", "remote.origin.pushurl")
        sh(self.repo, "git", "config", "remote.origin.url", "alias:real")
        sh(self.repo, "git", "config", f"url.{self.origin}.pushInsteadOf", "alias:real")
        sh(self.repo, "git", "config", f"url.{decoy}.insteadOf", str(self.origin))
        self.commit_change("apps/web/src/new.ts", "export const n = 3\n")
        sh(self.tmp, "git", "--git-dir", str(decoy), "fetch", "-q", str(self.repo), "+HEAD:refs/heads/main")
        r = self.push("HEAD:main")
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("insteadOf", r.stdout + r.stderr)
        self.assertEqual(self.remote(), before)
        for key in (f"url.{decoy}.insteadOf", f"url.{self.origin}.pushInsteadOf"):
            sh(self.repo, "git", "config", "--unset", key)
        sh(self.repo, "git", "config", "remote.origin.url", str(decoy))
        sh(self.repo, "git", "config", "remote.origin.pushurl", str(self.tmp / "nowhere.git"))
        self.commit_change("apps/web/src/new.ts", "export const n = 2\n")
        r = self.push("HEAD:main")
        self.assertNotEqual(r.returncode, 0, "no base where the push goes: nothing pushed")

    def test_HARN_013_S2_a_push_of_head_runs_the_verify_as_before(self):
        r = self.push("HEAD:main")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("already passed", r.stdout)  # the seal skips the repeat
        self.assertEqual(self.called(), ["pnpm verify --use-seal"])
        self.assertEqual(self.remote(), self.green)
        sh(self.repo, "git", "tag", "-a", "-m", "v1", "v1")  # an annotated tag on HEAD pushes HEAD
        self.assertEqual(self.push("v1").returncode, 0)
        # Checked out, the red commit gets its verify, which stops it.
        sh(self.repo, "git", "switch", "-q", "red")
        self.calls.write_text("")
        r = self.push("HEAD:main")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("RED is red", r.stdout + r.stderr)
        self.assertNotIn("already passed", r.stdout)
        self.assertGreater(len(self.called()), 1)  # the verify ran its steps
        self.assertEqual(self.remote(), self.green)

    def test_HARN_013_S3_a_deletion_pushes_nothing_to_verify(self):
        self.assertEqual(self.push("HEAD:refs/heads/old").returncode, 0)
        (self.repo / "RED").write_text("red\n")  # a verify now would be red
        self.calls.write_text("")
        r = self.push(":old")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIsNone(self.remote("old"))
        self.assertEqual(self.called(), [])


if __name__ == "__main__":
    unittest.main()
