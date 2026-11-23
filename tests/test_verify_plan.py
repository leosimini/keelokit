"""The routing of a change to the verify steps it needs (verify_tools.py plan). The guards that keep the map
honest: unknown goes up, --all is every step, a plan never shrinks when a file is added, every route names real
steps, and each file the template ships is classified the way it is written down here independently.
Run: python3 -m unittest discover -s tests"""
import json
import os
import runpy
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
TOOLS = runpy.run_path(str(REPO / "template/.keelokit/bin/verify_tools.py"), run_name="tools")
ROUTING = tomllib.loads((REPO / "template/.keelokit/verify-routing.toml").read_text())
STEPS = set(TOOLS["STEPS"])


def plan(files, everything=False):
    always = ROUTING.get("always", [])
    routes = [([TOOLS["glob_re"](p) for p in r["paths"]], r["steps"]) for r in ROUTING["route"]]
    return TOOLS["plan_for"](files, (always, routes), everything)


def template_files():
    listed = subprocess.run(["git", "ls-files", "template"], cwd=REPO, capture_output=True, text=True, check=True).stdout.split()
    return [f[len("template/"):].removesuffix(".jinja") for f in listed]


class PlanGuardsTest(unittest.TestCase):
    def test_every_route_names_real_steps(self):
        for r in ROUTING["route"]:
            self.assertTrue(set(r["steps"]) <= STEPS | {"all"}, r)

    def test_all_is_every_step_and_any_plan_is_inside_it(self):
        self.assertEqual(plan(["docs/a.md"], everything=True)[0], ["all"])
        for f in template_files():
            steps, _ = plan([f])
            self.assertTrue(steps == ["all"] or set(steps) <= STEPS, (f, steps))

    def test_a_file_no_route_knows_runs_everything(self):
        steps, unknown = plan(["docs/a.md", "tools/mystery.xyz"])
        self.assertEqual((steps, unknown), (["all"], ["tools/mystery.xyz"]))

    def test_adding_a_file_never_removes_a_step(self):
        files = template_files()
        base = {"docs/guide.md"}
        for f in files[::7]:
            before, _ = plan(sorted(base))
            after, _ = plan(sorted(base | {f}))
            self.assertTrue(after == ["all"] or (before != ["all"] and set(before) <= set(after)), (f, before, after))

    def test_what_each_kind_of_file_must_get_written_independently_of_the_table(self):
        expect = {
            "docs/guide.md": ({"format"}, {"unit", "build", "e2e", "integration", "typecheck", "lint"}),
            "README.md": ({"format"}, {"unit", "build", "e2e"}),
            "backlog/stories/A-1-x.md": ({"format"}, {"unit"}),
            "apps/web/src/i18n/locales/es.json": ({"unit", "lint", "typecheck", "format"}, {"build", "e2e", "integration"}),
        }
        for f, (must, must_not) in expect.items():
            steps, _ = plan([f])
            self.assertNotEqual(steps, ["all"], f)
            self.assertTrue(must <= set(steps), (f, steps))
            self.assertFalse(must_not & set(steps), (f, steps))
        for f in ("apps/api/src/billing/charge.ts", "packages/shared/src/index.ts", "package.json", "pnpm-lock.yaml",
                  ".keelokit/harness/rules.toml", ".github/workflows/ci.yml.jinja", "scripts/verify.sh", ".githooks/pre-push",
                  "apps/web/e2e/home.spec.ts", "tsconfig.base.json"):
            self.assertEqual(plan([f])[0], ["all"], f)

    def test_every_file_the_template_ships_is_classified_or_runs_everything(self):
        """Not a place to add routes, a place to see what is unclassified: a new kind of file is `all` until
        someone decides, and this lists them so the decision is visible in review."""
        unknown = sorted({Path(f).suffix or Path(f).name for f in template_files() if plan([f])[1]})
        self.assertLessEqual(len(unknown), 40, unknown)

    def test_globs(self):
        g = TOOLS["glob_re"]
        self.assertTrue(g("**/*.md").match("a.md") and g("**/*.md").match("a/b/c.md"))
        self.assertTrue(g("docs/**").match("docs/a/b.md") and not g("docs/**").match("xdocs/a.md"))
        self.assertTrue(g("apps/*/src/**").match("apps/web/src/a/b.ts") and not g("apps/*/src/**").match("apps/web/x/src/a.ts"))
        self.assertFalse(g("*.md").match("docs/a.md"))


class CausesTest(unittest.TestCase):
    def test_builtin_causes_are_found_in_a_log(self):
        found = dict(TOOLS["causes_in"]("..\nFATAL ERROR: Reached heap limit Allocation failed - JavaScript heap out of memory\n"))
        self.assertIn("heap", found)
        self.assertNotIn("disk", found)
        self.assertIn("disk", dict(TOOLS["causes_in"]("write failed: ENOSPC: no space left on device")))
        self.assertEqual(TOOLS["causes_in"]("all green"), [])


# FLEET-001: the verify fits its test workers to the memory the machine has, and records what each step used.
# Interfaces from the story's done-contract: own_cgroup_dir, memory_available_mb, workers_for, per_worker_peaks,
# memory_override, memory_plan, peak_from_rusage, the `workers` and `measure` CLIs, and cmd_record's peak fields.
# Nothing here reads the real machine's memory, cores or cgroup: every figure comes from a temp file.
TOOLS_PY = REPO / "template/.keelokit/bin/verify_tools.py"
GB6 = 6 * 1024 * 1024  # kB in MemAvailable for 6 GB
GB1_5 = 1536 * 1024  # kB for 1.5 GB


def fn(name):
    """A function of verify_tools.py by name: a missing one fails the test that needs it, not the module."""
    if name not in TOOLS:
        raise AssertionError(f"verify_tools.py has no {name}()")
    return TOOLS[name]


class MemoryFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp)

    def meminfo(self, kb=GB6):
        p = self.tmp / "meminfo"
        p.write_text(f"MemTotal:       16384000 kB\nMemFree:          512000 kB\nMemAvailable:   {kb} kB\n")
        return p

    def cgroup(self, max_="max", current=0, name="cg"):
        d = self.tmp / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "memory.max").write_text(f"{max_}\n")
        (d / "memory.current").write_text(f"{current}\n")
        return d


class CgroupAndMemAvailableTest(MemoryFixture):
    def test_FLEET_001_S6_own_cgroup_dir_from_proc_self_cgroup(self):
        """FLEET-001.S6: the v2 line `0::/path` names the own cgroup under the cgroup root."""
        root = self.tmp / "sys/fs/cgroup"
        (root / "user.slice/session-1.scope").mkdir(parents=True)
        proc = self.tmp / "self_cgroup"
        proc.write_text("0::/user.slice/session-1.scope\n")
        self.assertEqual(fn("own_cgroup_dir")(proc, root), root / "user.slice/session-1.scope")
        proc.write_text("12:memory:/docker/abc\n11:cpu:/docker/abc\n")  # v1 only
        self.assertIsNone(fn("own_cgroup_dir")(proc, root))
        proc.write_text("0::/not/there\n")
        self.assertIsNone(fn("own_cgroup_dir")(proc, root))

    def test_FLEET_001_S6_memavailable_alone(self):
        self.assertEqual(fn("memory_available_mb")(self.meminfo(GB6), None), (6144, "MemAvailable"))
        self.assertEqual(fn("memory_available_mb")(self.meminfo(GB6), self.cgroup("max", 10 * 2**30)), (6144, "MemAvailable"))

    def test_FLEET_001_S6_a_cgroup_limit_lower_than_memavailable_wins(self):
        """FLEET-001.S6: a container whose memory.max is below the host's MemAvailable plans with the cgroup's figure."""
        cg = self.cgroup(4 * 2**30, 1 * 2**30)  # 3 GB left in the cgroup, 6 GB on the host
        self.assertEqual(fn("memory_available_mb")(self.meminfo(GB6), cg), (3072, "cgroup memory.max"))
        # and the host wins when it is the lower one
        cg = self.cgroup(16 * 2**30, 0, name="big")
        self.assertEqual(fn("memory_available_mb")(self.meminfo(GB6), cg), (6144, "MemAvailable"))

    def test_FLEET_001_S6_one_source_or_none(self):
        missing = self.tmp / "no-meminfo"
        self.assertEqual(fn("memory_available_mb")(missing, self.cgroup(2 * 2**30, 0)), (2048, "cgroup memory.max"))
        self.assertIsNone(fn("memory_available_mb")(missing, None))
        self.assertIsNone(fn("memory_available_mb")(missing, self.cgroup("max", 0, name="nolimit")))
        # over its limit: floored at 0, never negative
        self.assertEqual(fn("memory_available_mb")(missing, self.cgroup(2**30, 2 * 2**30, name="over")), (0, "cgroup memory.max"))


class WorkersFormulaTest(unittest.TestCase):
    def test_FLEET_001_S2_six_gb_and_2_3_gb_per_worker_on_8_cores_is_2(self):
        self.assertEqual(fn("workers_for")(6144, 2355, 8), 2)

    def test_FLEET_001_formula_floors_keeps_at_least_one_and_caps_at_cores(self):
        w = fn("workers_for")
        self.assertEqual(w(6144, 2000, 8), 2)  # 2.46 floors to 2
        self.assertEqual(w(1000, 2355, 8), 1)  # 0.34 → at least 1
        self.assertEqual(w(100000, 100, 4), 4)  # 800 → capped at the cores
        self.assertEqual(w(10000, 1000, 16), 8)  # 10000 × 0.8 / 1000


class PerWorkerPeaksTest(unittest.TestCase):
    def line(self, peak, source, workers=None, result="pass"):
        e = {"t": 1, "head": "h", "result": result, "peak_mb": peak, "peak_source": source}
        if workers is not None:
            e["workers"] = workers
        return json.dumps(e)

    def test_FLEET_001_S2_rss_is_one_worker_and_cgroup_is_divided_by_the_workers(self):
        peaks = fn("per_worker_peaks")([self.line({"unit": 900, "integration": 4600}, {"unit": "rss", "integration": "cgroup"},
                                                  {"integration": 2})], 8)
        self.assertEqual(peaks, {"unit": 900, "integration": 2300})

    def test_FLEET_001_S2_cgroup_without_workers_uses_the_runners_default(self):
        peaks = fn("per_worker_peaks")([self.line({"unit": 7000}, {"unit": "cgroup"})], 8)
        self.assertEqual(peaks, {"unit": 1000})  # 8 cores − 1
        self.assertEqual(fn("per_worker_peaks")([self.line({"unit": 700}, {"unit": "cgroup"})], 1), {"unit": 700})

    def test_FLEET_001_S2_the_max_of_the_last_10_entries_that_measured_the_step_wins(self):
        """FLEET-001.S2: a small run after a big one (a narrowed rerun, a --packages run, an early red) must not erase the
        real peak: the figure is the max over the last 10 entries that measured the step, any result."""
        lines = [self.line({"unit": 2355, "integration": 1000}, {"unit": "rss", "integration": "rss"}),
                 self.line({"unit": 310}, {"unit": "rss"}, result="fail"),
                 self.line({}, {})]
        self.assertEqual(fn("per_worker_peaks")(lines, 8), {"unit": 2355, "integration": 1000})
        # beyond the last 10 that measured it, an old peak no longer counts; entries that didn't measure it don't count
        old = [self.line({"unit": 9000}, {"unit": "rss"})]
        recent = [self.line({"unit": 300}, {"unit": "rss"}) if i % 2 == 0 else self.line({"lint": 50}, {"lint": "rss"})
                  for i in range(20)]
        self.assertEqual(fn("per_worker_peaks")(old + recent, 8)["unit"], 300)
        self.assertEqual(fn("per_worker_peaks")(old + recent[:18], 8)["unit"], 9000)  # 9 measured since: still inside

    def test_FLEET_001_malformed_history_is_skipped(self):
        lines = [self.line({"unit": 600}, {"unit": "rss"}),
                 "not json at all", "", "[1, 2]",
                 json.dumps({"peak_mb": "lots", "peak_source": {}}),
                 json.dumps({"peak_mb": {"unit": "x"}, "peak_source": {"unit": "rss"}}),
                 json.dumps({"peak_mb": {"integration": 900}}),
                 json.dumps({"peak_mb": {"e2e": 700}, "peak_source": {"e2e": "rss"}, "workers": "two"})]
        peaks = fn("per_worker_peaks")(lines, 8)
        self.assertEqual(peaks.get("unit"), 600)
        self.assertTrue(set(peaks) <= {"unit", "integration", "e2e"}, peaks)


class MemoryOverrideTest(MemoryFixture):
    def state(self, text):
        p = self.tmp / "state.toml"
        p.write_text(text)
        return p

    def test_FLEET_001_S5_the_override_as_a_number_or_a_table(self):
        self.assertEqual(fn("memory_override")(self.state("[verify]\nmemory_per_worker_mb = 1500\n")), 1500)
        self.assertEqual(fn("memory_override")(self.state("[verify.memory_per_worker_mb]\nintegration = 1500\nunit = 800\n")),
                         {"integration": 1500, "unit": 800})

    def test_FLEET_001_S5_anything_else_is_no_override(self):
        for text in ("", "[verify]\nshared_seals = []\n", "[verify]\nmemory_per_worker_mb = 0\n",
                     "[verify]\nmemory_per_worker_mb = -5\n", "[verify]\nmemory_per_worker_mb = \"1500\"\n", "not = [toml"):
            self.assertIsNone(fn("memory_override")(self.state(text)), text)
        self.assertIsNone(fn("memory_override")(self.tmp / "absent.toml"))


class MemoryPlanTest(unittest.TestCase):
    STEPS = ["format", "lint", "unit", "integration", "build", "e2e"]

    def test_FLEET_001_S2_workers_fit_the_memory_and_the_plan_says_so(self):
        """FLEET-001.S2: 6 GB available, integration peaked at 2.3 GB per worker, 8 cores → 2 workers and the line."""
        workers, lines, refusal = fn("memory_plan")(self.STEPS, (6144, "MemAvailable"), {"integration": 2355}, None, 8)
        self.assertEqual(workers, {"integration": 2})
        self.assertEqual(lines, ["integration: 2 workers, 6.0 GB free, 2.3 GB each last time"])
        self.assertIsNone(refusal)

    def test_FLEET_001_S3_one_worker_that_does_not_fit_is_a_refusal_with_both_numbers(self):
        """FLEET-001.S3: 1.5 GB available and 2.3 GB for one worker → a refusal naming the step, both GB and the way out."""
        _, _, refusal = fn("memory_plan")(self.STEPS, (1536, "MemAvailable"), {"integration": 2355}, None, 8)
        self.assertIsNotNone(refusal)
        for part in ("integration", "2.3 GB", "1.5 GB", "MemAvailable", "VERIFY_FORCE=1"):
            self.assertIn(part, refusal)

    def test_FLEET_001_the_refusal_threshold_is_more_than_available_not_80_percent(self):
        workers, _, refusal = fn("memory_plan")(self.STEPS, (2400, "MemAvailable"), {"integration": 2355}, None, 8)
        self.assertIsNone(refusal)
        self.assertEqual(workers, {"integration": 1})
        _, _, refusal = fn("memory_plan")(self.STEPS, (2355, "MemAvailable"), {"integration": 2355}, None, 8)
        self.assertIsNone(refusal, "exactly what one worker needs is not a refusal")
        _, _, refusal = fn("memory_plan")(self.STEPS, (2354, "cgroup memory.max"), {"integration": 2355}, None, 8)
        self.assertIn("cgroup memory.max", refusal)

    def test_FLEET_001_S4_no_peak_and_no_override_plans_nothing(self):
        """FLEET-001.S4: no recorded peak, no override → today's workers: nothing planned, no line."""
        self.assertEqual(fn("memory_plan")(self.STEPS, (6144, "MemAvailable"), {}, None, 8), ({}, [], None))

    def test_FLEET_001_S4_no_memory_measure_plans_nothing_and_refuses_nothing(self):
        self.assertEqual(fn("memory_plan")(self.STEPS, None, {"integration": 99999}, 1500, 8), ({}, [], None))

    def test_FLEET_001_only_worker_steps_in_the_run_are_planned(self):
        workers, lines, refusal = fn("memory_plan")(["unit", "build"], (6144, "MemAvailable"),
                                                    {"build": 9000, "integration": 9000, "unit": 1000}, None, 8)
        self.assertEqual(set(workers), {"unit"})
        self.assertIsNone(refusal)
        self.assertEqual(len(lines), 1)

    def test_FLEET_001_S5_the_override_wins_over_the_measure(self):
        """FLEET-001.S5: [verify] memory_per_worker_mb = 1500 is used instead of the 2.3 GB measured."""
        workers, lines, refusal = fn("memory_plan")(self.STEPS, (6144, "MemAvailable"), {"integration": 2355}, 1500, 8)
        self.assertEqual(workers["integration"], 3)  # 6144 × 0.8 / 1500 = 3.3
        self.assertIn("integration: 3 workers, 6.0 GB free, 1.5 GB each ([verify] memory_per_worker_mb)", lines)
        self.assertIsNone(refusal)
        self.assertEqual(workers.get("unit"), 3, "a number applies to every worker step, measured or not")

    def test_FLEET_001_S5_the_override_table_names_its_steps(self):
        workers, lines, _ = fn("memory_plan")(self.STEPS, (6144, "MemAvailable"), {"integration": 2355}, {"unit": 1500}, 8)
        self.assertEqual(workers, {"unit": 3, "integration": 2})
        self.assertIn("unit: 3 workers, 6.0 GB free, 1.5 GB each ([verify] memory_per_worker_mb)", lines)
        self.assertIn("integration: 2 workers, 6.0 GB free, 2.3 GB each last time", lines)


class WorkersCliTest(MemoryFixture):
    """`verify_tools.py workers HISTORY --steps … [--cores N] [--force]`, in a copy so ROOT/.keelokit/state.toml is ours."""

    def setUp(self):
        super().setUp()
        (self.tmp / ".keelokit/bin").mkdir(parents=True)
        shutil.copy(TOOLS_PY, self.tmp / ".keelokit/bin/verify_tools.py")
        self.history = self.tmp / "history"
        self.history.write_text(json.dumps({"t": 1, "head": "h", "result": "pass", "peak_mb": {"integration": 2355},
                                            "peak_source": {"integration": "rss"}}) + "\n")

    def workers(self, *args, meminfo_kb=GB6, cgroup=""):
        env = {**os.environ, "KEELOKIT_MEMINFO": str(self.meminfo(meminfo_kb)), "KEELOKIT_CGROUP_DIR": str(cgroup)}
        return subprocess.run([sys.executable, str(self.tmp / ".keelokit/bin/verify_tools.py"), "workers", str(self.history),
                               "--steps", "unit integration build", "--cores", "8", *args],
                              capture_output=True, text=True, env=env, timeout=30)

    def test_FLEET_001_S2_the_cli_prints_the_pairs_then_the_lines(self):
        r = self.workers()
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout.splitlines()
        self.assertEqual(out[0].split(), ["integration=2"])
        self.assertIn("integration: 2 workers, 6.0 GB free, 2.3 GB each last time", out[1:])

    def test_FLEET_001_S3_the_cli_refuses_with_exit_3_and_force_gives_one_worker(self):
        r = self.workers(meminfo_kb=GB1_5)
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        for part in ("integration", "2.3 GB", "1.5 GB", "VERIFY_FORCE=1"):
            self.assertIn(part, r.stderr)
        forced = self.workers("--force", meminfo_kb=GB1_5)
        self.assertEqual(forced.returncode, 0, forced.stderr)
        self.assertEqual(forced.stdout.splitlines()[0].split(), ["integration=1"])
        self.assertTrue(any(l.startswith("integration:") for l in forced.stdout.splitlines()[1:]), forced.stdout)

    def test_FLEET_001_S4_no_peak_prints_an_empty_plan(self):
        self.history.write_text("")
        r = self.workers()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "")

    def test_FLEET_001_S5_the_cli_reads_the_override_from_state_toml(self):
        (self.tmp / ".keelokit/state.toml").write_text("[verify]\nmemory_per_worker_mb = 1500\n")
        r = self.workers()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(sorted(r.stdout.splitlines()[0].split()), ["integration=3", "unit=3"])
        self.assertIn("integration: 3 workers, 6.0 GB free, 1.5 GB each ([verify] memory_per_worker_mb)", r.stdout)

    def test_FLEET_001_S6_the_cli_takes_the_cgroup_when_it_is_lower(self):
        r = self.workers(cgroup=self.cgroup(3 * 2**30, 0))  # 3 GB in the cgroup vs 6 GB on the host → 1 worker
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.splitlines()[0].split(), ["integration=1"])
        self.assertRegex(r.stdout, r"integration: 1 workers?, 3\.0 GB free, 2\.3 GB each last time")


class PeakRecordingTest(MemoryFixture):
    def test_FLEET_001_S1_peak_from_rusage_kb_on_linux_bytes_on_macos(self):
        self.assertEqual(fn("peak_from_rusage")(2355 * 1024, "linux"), 2355)
        self.assertEqual(fn("peak_from_rusage")(2355 * 1024 * 1024, "darwin"), 2355)

    def measure(self, out, *cmd):
        return subprocess.run([sys.executable, str(TOOLS_PY), "measure", str(out), "unit", "--", *cmd],
                              capture_output=True, text=True, timeout=30)

    def test_FLEET_001_S1_measure_passes_the_exit_code_and_appends_the_peak(self):
        out = self.tmp / "peaks"
        r = self.measure(out, sys.executable, "-c", "b = bytearray(30 * 2**20); raise SystemExit(5)")
        self.assertEqual(r.returncode, 5, r.stderr)
        step, mb, source = out.read_text().splitlines()[-1].split("\t")
        self.assertEqual(step, "unit")
        self.assertIn(source, {"rss", "cgroup"})
        self.assertGreaterEqual(int(mb), 1)

    def test_FLEET_001_S1_a_child_killed_by_a_signal_is_128_plus_n(self):
        r = self.measure(self.tmp / "peaks", "sh", "-c", "kill -9 $$")
        self.assertEqual(r.returncode, 137)

    def test_FLEET_001_a_measuring_failure_never_fails_the_step(self):
        r = self.measure(self.tmp / "no/such/dir/peaks", "true")
        self.assertEqual(r.returncode, 0, r.stderr)


class RecordPeaksTest(MemoryFixture):
    def record(self, **env):
        history = self.tmp / "history"
        clean = {k: v for k, v in os.environ.items() if not k.startswith("VERIFY_")}
        with mock.patch.dict(os.environ, {**clean, **env}, clear=True):
            fn("cmd_record")([str(history), "pass", "0", "abc", "changed", "3|Unit tests\n", "", str(self.tmp / "no.log")])
        return json.loads(history.read_text().splitlines()[-1])

    def test_FLEET_001_S1_peaks_are_recorded_per_step_with_their_source(self):
        """FLEET-001.S1: the history line has each measured step's peak (the max of its commands) and its source."""
        peaks = self.tmp / "peaks"
        peaks.write_text("unit\t100\trss\nunit\t300\trss\ndoctor\t50\tcgroup\nunit\t200\tcgroup\n")
        e = self.record(VERIFY_PEAKS=str(peaks))
        self.assertEqual(e["peak_mb"], {"unit": 300, "doctor": 50})
        self.assertEqual(e["peak_source"], {"unit": "rss", "doctor": "cgroup"})

    def test_FLEET_001_S1_nothing_measured_is_omitted(self):
        """FLEET-001.S1: a machine that can't measure leaves the step out: both keys empty."""
        e = self.record()
        self.assertEqual((e["peak_mb"], e["peak_source"]), ({}, {}))
        (self.tmp / "empty").write_text("")
        e = self.record(VERIFY_PEAKS=str(self.tmp / "empty"))
        self.assertEqual((e["peak_mb"], e["peak_source"]), ({}, {}))

    def test_FLEET_001_S2_the_workers_and_why_are_recorded(self):
        e = self.record(VERIFY_WORKERS="unit=2 integration=3",
                        VERIFY_WORKERS_WHY="unit: 2 workers, 6.0 GB free, 2.3 GB each last time")
        self.assertEqual(e["workers"], {"unit": 2, "integration": 3})
        self.assertEqual(e["workers_why"], "unit: 2 workers, 6.0 GB free, 2.3 GB each last time")
        e = self.record()
        self.assertEqual((e["workers"], e["workers_why"]), ({}, ""))


class StatusWorkersLineTest(MemoryFixture):
    """status.py says the workers chosen and why, after the verify line (dx)."""

    def status(self, entries):
        repo = self.tmp / "repo"
        shutil.copytree(REPO / "template/.keelokit/bin", repo / ".keelokit/bin")
        g = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run([*g, "init", "-q", "-b", "main", str(repo)], check=True)
        subprocess.run([*g, "commit", "-q", "--allow-empty", "-m", "init"], cwd=repo, check=True)
        (repo / ".git/keelokit-verify.state").write_text("state=pass\nrc=0\nhead=abcdef0\nlevel=changed\nsince=0\n")
        (repo / ".git/keelokit-verify.history").write_text("".join(json.dumps(e) + "\n" for e in entries))
        env = {**os.environ, "KEELOKIT_STATUS_OFFLINE": "1"}
        r = subprocess.run([sys.executable, ".keelokit/bin/status.py", "--no-ci"], cwd=repo, capture_output=True,
                           text=True, env=env, timeout=60)
        return r.stdout.splitlines()

    def test_FLEET_001_S2_status_shows_the_last_workers_why(self):
        old = "integration: 3 workers, 9.0 GB free, 2.3 GB each last time"
        why = "integration: 2 workers, 6.0 GB free, 2.3 GB each last time"
        out = self.status([{"t": 1, "result": "pass", "workers_why": old}, {"t": 2, "result": "pass", "workers_why": why}])
        at = next(i for i, l in enumerate(out) if l.startswith("verify:"))
        self.assertEqual(out[at + 1], f"verify workers: {why}", out)

    def test_FLEET_001_S4_status_says_nothing_without_a_why(self):
        out = self.status([{"t": 1, "result": "pass"}])
        self.assertFalse(any(l.startswith("verify workers:") for l in out), out)


if __name__ == "__main__":
    unittest.main()
