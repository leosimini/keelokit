"""The repository's shell scripts refuse a bad option before doing any work. Run:
python3 -m unittest discover -s tests

scripts/test-template.sh took `--update-from`'s tag with `${2:?}`, which only checks that some
word follows: `--update-from --postgis` took `--postgis` as the tag, left postgis off, and ran
`copier copy --vcs-ref --postgis`, which died three layers down in git's usage text without
naming the script or the option (DX-3). These cases find every option any tracked shell script
reads a value for (a `case` branch that reads `$2`) and run it with the value missing and with
another option in its place: the script must stop at once with exit 2 and a line naming the
option, before it runs anything on PATH. A value that is a real word must still be taken."""
import os
import json
import re
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# A `case` branch for an option (`--name)`, `-n|--name)`), on one line or spread over several.
BRANCH = re.compile(r"^(\s*)(-[\w-]+(?:\|-[\w-]+)*)\)")
READS_NEXT = re.compile(r"\$\{?2\b")
# Positional arguments each script needs before its options, so the options are what gets parsed.
LEADING = {"scripts/test-template.sh": ['["api"]']}
# Commands a script could reach once parsing is done; each shim logs its call and fails.
# Scripts outside scripts/ that find their own folder and can be run from anywhere.
SELF_CONTAINED = {"template/.keelokit/bin/run-local.sh", "template/scripts/verify.sh",
                  "template/.keelokit/bin/flaky.sh"}
SHIMS = ["uvx", "copier", "pnpm", "npm", "npx", "claude", "gh"]


def shell_scripts():
    listed = subprocess.run(["git", "-C", str(ROOT), "ls-files", "*.sh", "*.sh.jinja"],
                            capture_output=True, text=True, check=True).stdout.split()
    return listed


def value_options(path):
    """{option spelling: the other options the script knows}, for each option whose branch reads
    the next argument ($2) anywhere in its body, up to the next branch or `esac` at its indent."""
    lines = (ROOT / path).read_text().splitlines()
    branches = []
    for i, line in enumerate(lines):
        m = BRANCH.match(line)
        if not m:
            continue
        indent, body = len(m.group(1)), [line[m.end():]]
        for later in lines[i + 1:]:
            depth = len(later) - len(later.lstrip())
            if later.strip() and depth <= indent and (re.match(r"\s*(\S+\)|esac\b)", later)):
                break
            body.append(later)
        branches.append((m.group(2).split("|"), any(READS_NEXT.search(b) for b in body)))
    known = {opt for spellings, _ in branches for opt in spellings}
    return {opt: sorted(known - {opt}) for spellings, reads in branches if reads for opt in spellings}


class ValueOptionTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.bin = Path(tmp.name) / "bin"
        self.bin.mkdir()
        self.log = Path(tmp.name) / "calls.log"
        for name in SHIMS:
            shim = self.bin / name
            shim.write_text(f'#!/bin/sh\necho "{name} $*" >>"{self.log}"\nexit 1\n')
            shim.chmod(shim.stat().st_mode | stat.S_IXUSR)
        self.env = dict(os.environ, PATH=f"{self.bin}{os.pathsep}{os.environ['PATH']}")

    def run_script(self, path, *args):
        self.log.unlink(missing_ok=True)
        return subprocess.run(["bash", str(ROOT / path), *LEADING.get(path, []), *args],
                              capture_output=True, text=True, env=self.env, cwd=ROOT,
                              stdin=subprocess.DEVNULL, timeout=60)

    def calls(self):
        return self.log.read_text() if self.log.exists() else ""

    def test_DX_3_every_value_option_refuses_a_missing_value_or_another_option(self):
        scripts = {p: value_options(p) for p in shell_scripts()}
        scripts = {p: opts for p, opts in scripts.items() if opts}
        # Not vacuous: the option the bug was found in is still seen by the scan.
        self.assertIn("--update-from", scripts.get("scripts/test-template.sh", {}))
        for path, opts in scripts.items():
            self.assertTrue(path.startswith("scripts/") or path in SELF_CONTAINED,
                            f"{path} reads an option's value; add a way to run it to {Path(__file__).name}")
            for opt, others in opts.items():
                cases = [[opt], [opt, "-x"], [opt, "--"]] + [[opt, other] for other in others]
                for args in cases:
                    with self.subTest(script=path, args=args):
                        r = self.run_script(path, *args)
                        out = r.stdout + r.stderr
                        self.assertEqual(r.returncode, 2, f"{path} {args}: exit {r.returncode}\n{out[-2000:]}")
                        self.assertIn(opt, r.stderr, f"{path} {args}: the error doesn't name {opt}\n{out[-2000:]}")
                        self.assertNotIn("Traceback", out)
                        self.assertNotRegex(r.stderr, r"line \d+:", f"{path} {args}: a bare shell error\n{out}")
                        self.assertEqual(self.calls(), "", f"{path} {args}: ran something before refusing")

    def test_DX_3_update_from_still_takes_a_tag(self):
        r = self.run_script("scripts/test-template.sh", "--update-from", "v0.4.0", "--postgis")
        calls = self.calls()
        self.assertRegex(calls, r"--vcs-ref v0\.4\.0 ", r.stdout + r.stderr)
        self.assertIn("postgis=true", calls)


class ConcurrentRunsTest(unittest.TestCase):
    def test_PKG_3_browser_installs_take_turns_across_runs(self):
        """PKG-3: two template runs on one machine installed browsers at the same time: apt's lock
        failed one, and the shared pnpm store came out corrupted for the other. Every script step
        that installs browsers runs under a machine-wide flock where flock exists."""
        for path in sorted(ROOT.glob("scripts/*.sh")):
            lines = path.read_text().splitlines()
            for i, line in enumerate(lines):
                if re.search(r"e2e:install|playwright install", line) and not line.lstrip().startswith("#"):
                    with self.subTest(script=path.name, line=i + 1):
                        locked = line.lstrip().startswith("flock ")
                        fallback = i >= 2 and lines[i - 1].strip() == "else" and lines[i - 2].lstrip().startswith("flock ")
                        self.assertTrue(locked or fallback, line)


class AuditTest(unittest.TestCase):
    """SEC-3: a generated project's audit fails on a high or critical advisory with a fix, and only
    lists one with no fix yet (three of those, upstream, turned every new project red)."""
    AUDIT = ROOT / "template/.keelokit/bin/audit.py"

    def run_with(self, advisories):
        tmp = Path(tempfile.mkdtemp())
        shim = tmp / "pnpm"
        shim.write_text("#!/bin/sh\ncat " + str(tmp / "out.json") + "\n")
        shim.chmod(0o755)
        (tmp / "out.json").write_text(json.dumps({"advisories": advisories, "metadata": {}}))
        env = {**os.environ, "PATH": f"{tmp}:{os.environ['PATH']}"}
        return subprocess.run(["python3", str(self.AUDIT)], cwd=tmp, env=env, capture_output=True, text=True)

    def adv(self, name, severity, patched):
        return {"module_name": name, "severity": severity, "patched_versions": patched, "vulnerable_versions": "<=1",
                "title": "t", "github_advisory_id": f"GHSA-{name}", "findings": [{"paths": [f".>{name}"]}]}

    def test_SEC_3_blocks_what_has_a_fix_and_lists_what_doesnt(self):
        run = self.run_with({"1": self.adv("braces", "high", "<0.0.0"), "2": self.adv("low-one", "moderate", ">=2")})
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("no fix yet, not blocking: high braces", run.stdout)
        run = self.run_with({"1": self.adv("minimist", "critical", ">=1.2.6"), "2": self.adv("braces", "high", "<0.0.0")})
        self.assertEqual(run.returncode, 1)
        self.assertIn("minimist", run.stderr)

    def test_SEC_3_an_audit_that_cant_run_fails(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "pnpm").write_text("#!/bin/sh\necho '{\"error\": {\"code\": \"ERR_PNPM_AUDIT_BAD_RESPONSE\"}}'\n")
        (tmp / "pnpm").chmod(0o755)
        run = subprocess.run(["python3", str(self.AUDIT)], cwd=tmp, env={**os.environ, "PATH": f"{tmp}:{os.environ['PATH']}"},
                             capture_output=True, text=True)
        self.assertEqual(run.returncode, 1)

    def test_SEC_3_the_template_audits_only_through_it(self):
        for rel in ("template/scripts/verify.sh", "template/.github/workflows/ci.yml.jinja"):
            with self.subTest(rel):
                text = (ROOT / rel).read_text()
                self.assertIn("python3 .keelokit/bin/audit.py", text)
                self.assertNotIn("pnpm audit", text)


class StableTestsTest(unittest.TestCase):
    """FLEET-003: the stable-tests rules reach main, flaky.sh reproduces an intermittent red with
    its seed, zone and load, and the arch-specs ship to generated projects byte for byte."""
    FLAKY = ROOT / "template/.keelokit/bin/flaky.sh"
    FAILED = re.compile(r"^failed:.*\brun=(\d+) seed=(\d+) tz=(\S+) stress=(\d+) loadavg=([\d.]+|\?)", re.M)
    # Fails only where the local date differs from the UTC date at a fixed instant: 2026-11-23 12:30
    # UTC is already the 24th in Auckland (UTC+13), the same day in UTC.
    CLOCK_EDGE = ("import calendar, sys, time; t = calendar.timegm((2026, 11, 23, 12, 30, 0)); "
                  "sys.exit(time.strftime('%F', time.localtime(t)) != time.strftime('%F', time.gmtime(t)))")

    def flaky(self, *args):
        env = {**os.environ, "TZ": "UTC"}
        return subprocess.run(["bash", str(self.FLAKY), *args], capture_output=True, text=True,
                              env=env, cwd=ROOT, stdin=subprocess.DEVNULL, timeout=120)

    def test_FLEET_003_S1_the_rules_are_on_main_and_cited(self):
        """FLEET-003.S1: stable-tests.md numbers rules 1 to 11; 10 is deterministic test data,
        11 an absence asserted in one registry; the verifier, reviewer and build-story cite it."""
        text = (ROOT / "references/stable-tests.md").read_text()
        rules, current = {}, None
        for line in text.splitlines():
            m = re.match(r"^(\d+)\.\s+(.*)", line)
            if m:
                current = int(m.group(1))
                rules[current] = m.group(2)
            elif current is not None and line.startswith((" ", "\t")):
                rules[current] += " " + line.strip()
            elif line.strip() and not line.startswith((" ", "\t")):
                current = None
        self.assertEqual(sorted(rules), list(range(1, 12)), "rules are not numbered 1 to 11")
        self.assertRegex(rules[10].lower(), r"determinis")
        self.assertRegex(rules[11].lower(), r"absen")
        self.assertRegex(rules[11].lower(), r"registry|one place")
        for rel in ("agents/verifier.md", "agents/reviewer.md", "skills/build-story/SKILL.md"):
            with self.subTest(rel):
                self.assertIn("stable-tests.md", (ROOT / rel).read_text())

    def test_FLEET_003_S5_flaky_reports_the_runs_that_fail_at_a_clock_edge(self):
        """FLEET-003.S5: three runs each in the default zone, UTC and Auckland; only Auckland's fail,
        and each is reported with its run, seed, zone, stress and load; exit 1."""
        r = self.flaky("-n", "3", "--stress", "1", "--tz", "UTC Pacific/Auckland", "--",
                       "python3", "-c", self.CLOCK_EDGE)
        out = r.stdout + r.stderr
        self.assertEqual(r.returncode, 1, out)
        failed = self.FAILED.findall(out)
        self.assertEqual(len(failed), 3, out)
        self.assertEqual(len(re.findall(r"^failed:", out, re.M)), 3, out)
        for run, seed, tz, stress, _load in failed:
            self.assertEqual(tz, "Pacific/Auckland", out)
            self.assertEqual(stress, "1", out)
            self.assertEqual(int(seed), int(run), f"seed defaults to 1 + run - 1\n{out}")
        self.assertEqual(len({run for run, *_ in failed}), 3, out)

    def test_FLEET_003_S5_a_command_that_always_passes_exits_0(self):
        """FLEET-003.S5: no failing run, no `failed:` line, exit 0."""
        r = self.flaky("-n", "2", "--stress", "1", "--tz", "UTC Pacific/Auckland", "--", "true")
        out = r.stdout + r.stderr
        self.assertEqual(r.returncode, 0, out)
        self.assertNotRegex(out, r"(?m)^failed:")

    def test_FLEET_003_S5_each_run_gets_its_own_seed_and_seed_shifts_them(self):
        """FLEET-003.S5: FLAKY_SEED is S + run - 1 (S = 1 by default, --seed sets it), FLAKY_RUN the run."""
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "runs.log"
            cmd = ["sh", "-c", f'echo "$FLAKY_RUN $FLAKY_SEED" >>"{log}"']
            r = self.flaky("-n", "3", "--", *cmd)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(log.read_text().split("\n")[:-1], ["1 1", "2 2", "3 3"])
            log.unlink()
            r = self.flaky("-n", "3", "--seed", "100", "--", *cmd)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(log.read_text().split("\n")[:-1], ["1 100", "2 101", "3 102"])

    def test_FLEET_003_S5_a_usage_error_exits_2(self):
        """FLEET-003.S5: no command, or a count that is not a number, is a usage error."""
        for args in (["-n", "3"], ["-n", "3", "--"], ["-n", "abc", "--", "true"],
                     ["--stress", "x", "--", "true"], ["--seed", "x", "--", "true"]):
            with self.subTest(args=args):
                r = self.flaky(*args)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)

    def test_FLEET_003_S5_counts_and_seeds_are_decimal_never_octal(self):
        """FLEET-003.S5: bash reads 08 as octal and stops; -n 08, -n 010 and --seed 08 are 8, 10 and 8."""
        r = self.flaky("-n", "3", "--seed", "08", "--", "false")
        out = r.stdout + r.stderr
        self.assertEqual(r.returncode, 1, out)
        self.assertEqual([int(seed) for _, seed, *_ in self.FAILED.findall(out)], [8, 9, 10], out)
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "runs.log"
            cmd = ["sh", "-c", f'echo "$FLAKY_RUN" >>"{log}"']
            for count, runs in (("08", 8), ("010", 10)):
                with self.subTest(n=count):
                    log.unlink(missing_ok=True)
                    r = self.flaky("-n", count, "--", *cmd)
                    self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                    self.assertEqual(len(log.read_text().split()), runs)

    @unittest.skipUnless(Path("/usr/share/zoneinfo/UTC").exists(), "no zoneinfo to check a zone against")
    def test_FLEET_003_S5_an_unknown_zone_is_refused_before_any_run(self):
        """FLEET-003.S5: a misspelled zone runs under UTC and passes without testing the edge, and
        `*` must not be glob-expanded into file names (a file named UTC turns it into a real zone)."""
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "ran"
            (Path(tmp) / "UTC").write_text("")
            cmd = ["sh", "-c", f'touch "{marker}"']
            for zones, named in (("UTC Pacific/Aukland", "Pacific/Aukland"), ("*", "*")):
                with self.subTest(tz=zones):
                    r = subprocess.run(["bash", str(self.FLAKY), "-n", "1", "--tz", zones, "--", *cmd],
                                       capture_output=True, text=True, env={**os.environ, "TZ": "UTC"},
                                       cwd=tmp, stdin=subprocess.DEVNULL, timeout=60)
                    self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                    self.assertIn(named, r.stderr)
                    self.assertFalse(marker.exists(), f"--tz {zones!r}: a run started before refusing")

    def test_FLEET_003_S6_the_template_ships_the_arch_specs_byte_for_byte(self):
        """FLEET-003.S6: every file in references/arch-specs/ but README.md is in the template's
        packages/shared/src/arch/, identical, so a generated project's verify runs them."""
        src = ROOT / "references/arch-specs"
        dst = ROOT / "template/packages/shared/src/arch"
        names = sorted(f.name for f in src.iterdir() if f.is_file() and f.name != "README.md")
        for spec in ("no-literal-dates", "no-sleeps-in-specs", "no-random-test-data", "no-inherited-git-env"):
            self.assertIn(f"{spec}.arch.test.ts", names)
        self.assertIn("_walk.ts", names)
        for name in names:
            with self.subTest(name):
                self.assertTrue((dst / name).is_file(), f"{dst / name} is missing")
                self.assertEqual((dst / name).read_bytes(), (src / name).read_bytes(), f"{name} differs")


if __name__ == "__main__":
    unittest.main()


class CleanGitEnvTest(unittest.TestCase):
    """ESC-090: a git hook exports GIT_DIR (absolute in a linked worktree), GIT_INDEX_FILE and friends. The
    verify the pre-push hook runs passed them to every test, whose throwaway repos then committed to the real
    repository and pushed fixtures to origin's main. Both verify.sh scripts drop them before any git call."""

    VARS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY",
            "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_PREFIX", "GIT_NAMESPACE")
    SCRIPTS = ("scripts/verify.sh", "template/scripts/verify.sh")

    def unset_line(self, script):
        lines = (ROOT / script).read_text().splitlines()
        code = [(i, ln) for i, ln in enumerate(lines) if ln.strip() and not ln.lstrip().startswith("#")]
        unset = next(((i, ln) for i, ln in code if ln.startswith("unset GIT_DIR")), None)
        self.assertIsNotNone(unset, f"{script} has no `unset GIT_DIR …` line")
        first_git = next(i for i, ln in code if re.search(r"(^|[\s;&|(`$])git\s", ln))
        self.assertLess(unset[0], first_git, f"{script} calls git before it drops the inherited GIT_* variables")
        return unset[1]

    def test_ESC_090_both_verify_scripts_drop_every_inherited_git_variable_before_any_git_call(self):
        for script in self.SCRIPTS:
            with self.subTest(script=script):
                line = self.unset_line(script)
                env = {**os.environ, **{v: "/nowhere" for v in self.VARS}}
                out = subprocess.run(["bash", "-c", f"{line}\nenv"], env=env, capture_output=True, text=True,
                                     check=True).stdout
                left = [v for v in self.VARS if re.search(rf"(?m)^{v}=", out)]
                self.assertEqual(left, [], f"{script} keeps {left}")

    def test_ESC_090_a_test_repo_run_under_a_worktree_hook_env_no_longer_writes_to_the_real_repo(self):
        line = self.unset_line("scripts/verify.sh")
        with tempfile.TemporaryDirectory() as tmp:
            real, wt, scratch = Path(tmp, "real"), Path(tmp, "wt"), Path(tmp, "scratch")
            ident = ["-c", "user.name=T", "-c", "user.email=t@e.x"]
            clean = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
            run = lambda *a, cwd=None, env=clean: subprocess.run(a, cwd=cwd, env=env, capture_output=True,
                                                                  text=True, check=True).stdout.strip()
            run("git", "init", "-q", "-b", "main", str(real))
            run("git", *ident, "commit", "-q", "--allow-empty", "-m", "real", cwd=real)
            run("git", "worktree", "add", "-q", str(wt), "-b", "side", cwd=real)
            before = run("git", "rev-parse", "main", cwd=real)
            # What git exports to a hook in a linked worktree: an absolute GIT_DIR.
            hook_env = {**clean, "GIT_DIR": run("git", "rev-parse", "--absolute-git-dir", cwd=wt)}
            scratch.mkdir()
            fixture = (f"git init -q -b main . && git {' '.join(ident)} commit -q --allow-empty -m fixture "
                       f"&& git config user.name T")
            # Without the scrub the fixture lands in the real repo's worktree branch (the incident) …
            subprocess.run(["bash", "-c", fixture], cwd=scratch, env=hook_env, capture_output=True, text=True)
            self.assertNotEqual(run("git", "log", "-1", "--format=%s", "side", cwd=real), "real",
                                "the reproduction no longer reaches the real repo: the test proves nothing")
            run("git", "config", "--local", "--unset", "user.name", cwd=real)
            # … with it, the fixture stays in its own repo and the real one is untouched.
            run("git", "update-ref", "refs/heads/side", before, cwd=real)
            scratch2 = Path(tmp, "scratch2")
            scratch2.mkdir()
            subprocess.run(["bash", "-c", f"{line}\n{fixture}"], cwd=scratch2, env=hook_env, check=True,
                           capture_output=True, text=True)
            self.assertEqual(run("git", "rev-parse", "side", cwd=real), before)
            self.assertEqual(run("git", "rev-parse", "main", cwd=real), before)
            leaked = subprocess.run(["git", "config", "--local", "--get", "user.name"], cwd=real, env=clean,
                                    capture_output=True, text=True)
            self.assertNotEqual(leaked.returncode, 0, "the fixture's identity reached the real repo's config")
            self.assertEqual(run("git", "log", "-1", "--format=%s", cwd=scratch2), "fixture")


class UnitShardTest(unittest.TestCase):
    """CI runs the unit suite in shards (scripts/unit_shard.py): no test file may be left out or run twice."""

    def shard(self, *args):
        return subprocess.run(["python3", str(ROOT / "scripts/unit_shard.py"), *args], capture_output=True, text=True)

    def test_every_test_file_is_in_exactly_one_shard_and_the_split_is_stable(self):
        files = sorted(p.stem for p in (ROOT / "tests").glob("test_*.py"))
        for k in (1, 2, 3):
            with self.subTest(shards=k):
                got = [self.shard(str(n), str(k)).stdout.split() for n in range(1, k + 1)]
                flat = [m for s in got for m in s]
                self.assertEqual(sorted(flat), files)
                self.assertEqual(len(flat), len(set(flat)))
                self.assertEqual(got, [self.shard(str(n), str(k)).stdout.split() for n in range(1, k + 1)])

    def test_the_ci_workflow_runs_every_shard_it_asks_for(self):
        ci = (ROOT / ".github/workflows/ci.yml").read_text()
        m = re.search(r"shard: \[([\d, ]+)\]", ci)
        self.assertIsNotNone(m, "the unit job has no shard matrix")
        shards = [int(x) for x in m.group(1).split(",")]
        call = re.search(r"unit_shard\.py \$\{\{ matrix\.shard \}\} (\d+)", ci)
        self.assertIsNotNone(call)
        self.assertEqual(shards, list(range(1, int(call.group(1)) + 1)))

    def test_a_bad_shard_is_a_usage_error(self):
        for args in ([], ["0", "2"], ["3", "2"], ["x", "2"]):
            with self.subTest(args=args):
                r = self.shard(*args)
                self.assertEqual(r.returncode, 2)
                self.assertIn("usage", r.stderr)
