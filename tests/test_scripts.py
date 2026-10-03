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
SELF_CONTAINED = {"template/.keelokit/bin/run-local.sh"}
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


if __name__ == "__main__":
    unittest.main()
