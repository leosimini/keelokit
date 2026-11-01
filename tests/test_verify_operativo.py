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
        self.assertFalse((self.git_dir / "keelokit-verify.seal").exists())

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
        history = self.git_dir / "keelokit-verify.history"
        env = {**os.environ, "VERIFY_BASE": sh(self.repo, "git", "rev-parse", "origin/main"), "VERIFY_CLEAN": "true",
               "VERIFY_PLANNED": "unit e2e-stack audit", "VERIFY_PASSED": "unit e2e-stack ",
               "VERIFY_FAILED_STEPS": " e2e-stack "}
        subprocess.run([sys.executable, ".keelokit/bin/verify_tools.py", "record", str(history), "fail", "1", head,
                        "changed", "", "", ""], cwd=self.repo, env=env, check=True)
        self.assertEqual(self.history()[-1]["passed"], ["unit"])
        out = subprocess.run([sys.executable, ".keelokit/bin/verify_tools.py", "rerun", str(history), "--head", head,
                              "--base", env["VERIFY_BASE"], "--scope", "", "--level", "changed"],
                             cwd=self.repo, capture_output=True, text=True, check=True).stdout.split()
        self.assertEqual(out, ["e2e-stack", "audit"])


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


if __name__ == "__main__":
    unittest.main()
