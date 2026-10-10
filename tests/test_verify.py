"""What `pnpm verify` counts as changed. Run: python3 -m unittest discover -s tests

template/scripts/verify.sh runs typecheck, tests, build and E2E only for the packages changed since
origin/main (and their dependents), and everything when a root manifest changed. A change can be
in any git state when it runs: committed on the branch, staged, only in the working tree, a new
file git doesn't track yet, a deleted one, one taken out of the index or ignored. `git diff` and
pnpm's `[origin/main]` filter see tracked files only, so each check that decides "changed since
main" is run here across every state, against the real pnpm that decides the scope. The doctor's
`--critical --changed` (what `pnpm mutation` mutates) gets the same matrix."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PNPM = shutil.which("pnpm")
MANIFESTS = ["package.json", "pnpm-lock.yaml", "pnpm-workspace.yaml", "tsconfig.base.json"]
ALL = {".", "packages/a", "packages/b", "packages/c"}

# The pnpm the script calls: `run typecheck` is where verify.sh hands its scope to pnpm, so that
# call asks the real pnpm which packages the scope selects; every other call succeeds silently.
PNPM_STUB = """#!{python}
import subprocess, sys
args = sys.argv[1:]
if args[-3:] == ["--if-present", "run", "typecheck"]:
    out = subprocess.run([{pnpm!r}, *args[:-3], "ls", "--depth", "-1", "--parseable"],
                         capture_output=True, text=True, check=True).stdout
    open({log!r}, "w").write(out)
"""


def sh(cwd, *argv):
    r = subprocess.run(argv, cwd=cwd, capture_output=True, text=True)
    if r.returncode:
        raise AssertionError(f"{argv}: {r.stdout}{r.stderr}")
    return r.stdout


def git(cwd, *argv):
    return sh(cwd, "git", "-c", "user.name=t", "-c", "user.email=t@t", *argv)


class GitStates:
    """Every git state a change since origin/main can be in, applied to one path of a fixture:
    a workspace (root; a; b, which depends on a; c on its own) pushed to a bare origin, with the
    work on a branch."""

    STATES = ["committed", "staged", "unstaged", "untracked", "new-untracked", "untracked-rm-cached",
              "deleted", "ignored"]

    def fixture(self):
        tmp = Path(tempfile.mkdtemp()).resolve()  # macOS: /var is /private/var, as git reports it
        self.addCleanup(shutil.rmtree, tmp)
        root = tmp / "repo"
        files = {
            "package.json": '{"name": "root", "private": true}\n',
            "pnpm-workspace.yaml": "packages:\n  - 'packages/*'\n",
            "pnpm-lock.yaml": "lockfileVersion: '9.0'\n",
            "tsconfig.base.json": "{}\n",
            "packages/a/package.json": '{"name": "a", "version": "1.0.0"}\n',
            "packages/a/src/index.ts": "export const a = 1;\n",
            "packages/b/package.json": '{"name": "b", "version": "1.0.0", "dependencies": {"a": "workspace:*"}}\n',
            "packages/b/src/index.ts": "export const b = 1;\n",
            "packages/c/package.json": '{"name": "c", "version": "1.0.0"}\n',
            "packages/c/src/index.ts": "export const c = 1;\n",
            "docs/notes.md": "# Notes\n",
            "scripts/verify.sh": (ROOT / "template/scripts/verify.sh").read_text(),
            ".gitignore": "node_modules\n",
        }
        for rel, text in files.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(text)
        shutil.copytree(ROOT / "template/.keelokit/bin", root / ".keelokit/bin")
        (root / ".keelokit/critical.toml").write_text(
            '[[area]]\nname = "core"\nwhy = "w"\npaths = ["packages/a/src/", "packages/c/src/"]\n')
        git(tmp, "init", "-q", "-b", "main", str(root))
        git(root, "add", "-A")
        git(root, "commit", "-qm", "init")
        git(tmp, "clone", "-q", "--bare", str(root), str(tmp / "origin.git"))
        git(root, "remote", "add", "origin", str(tmp / "origin.git"))
        git(root, "fetch", "-q", "origin")
        git(root, "branch", "-q", "--set-upstream-to=origin/main")
        return tmp, root

    def apply(self, root, rel, state):
        """Put `rel` in `state` relative to origin/main. False when the state can't apply to it."""
        p = root / rel
        new = rel.replace("index.ts", "new.ts") if rel.endswith("index.ts") else rel
        if state == "new-untracked":
            if new == rel:  # a manifest: take it off main, keep it on disk (LOG-302)
                git(root, "rm", "-q", "--cached", rel)
                git(root, "commit", "-qm", f"drop {rel}")
                git(root, "push", "-q", "origin", "main")
            else:
                (root / new).write_text("export const n = 1;\n")
            return True
        if state == "untracked-rm-cached":
            git(root, "rm", "-q", "--cached", rel)
            return True
        if state == "ignored":
            if new != rel:
                return False  # an ignored source file isn't source
            git(root, "rm", "-q", "--cached", rel)
            with open(root / ".gitignore", "a") as f:
                f.write(rel + "\n")
            git(root, "add", ".gitignore")
            git(root, "commit", "-qm", "ignore")
            git(root, "push", "-q", "origin", "main")
            return True
        if state == "deleted":
            if rel in ("package.json", "pnpm-workspace.yaml"):
                return False  # no workspace left to scope
            p.unlink()
            return True
        with open(p, "a") as f:
            f.write("\n" if rel.endswith((".json", ".yaml")) else "export const x = 2;\n")
        if state == "untracked":  # modified and also dropped from the index
            git(root, "rm", "-q", "--cached", rel)
        if state in ("committed", "staged"):
            git(root, "add", "-A")
        if state == "committed":
            git(root, "commit", "-qm", "change")
        return True

    def branch(self, root):
        git(root, "checkout", "-q", "-b", "work")


@unittest.skipUnless(PNPM or os.environ.get("CI"), "pnpm not installed (CI installs it)")
class VerifyScopeTest(GitStates, unittest.TestCase):
    """LOG-302: which packages `pnpm verify` checks, for a change in every git state."""

    def verify(self, tmp, root):
        self.assertTrue(PNPM, "pnpm is needed to know what `pnpm verify` selects (CI sets it up)")
        bin_dir = tmp / "bin"
        bin_dir.mkdir(exist_ok=True)
        log = tmp / "scope.txt"
        log.unlink(missing_ok=True)
        stubs = {"pnpm": PNPM_STUB.format(python=sys.executable, pnpm=PNPM, log=str(log)),
                 "gitleaks": "#!/bin/sh\nexit 0\n", "docker": "#!/bin/sh\nexit 1\n",
                 "python3": "#!/bin/sh\nexit 0\n"}  # the doctor step; the doctor has its own tests
        for name, text in stubs.items():
            (bin_dir / name).write_text(text)
            (bin_dir / name).chmod(0o755)
        env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
        r = subprocess.run(["bash", "scripts/verify.sh"], cwd=root, env=env, capture_output=True, text=True,
                           timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(log.exists(), "verify.sh never ran typecheck\n" + r.stdout + r.stderr)
        picked = {os.path.relpath(line, root) for line in log.read_text().split()}
        return picked, r.stdout + r.stderr

    def check(self, rel, state, expected, says=None):
        tmp, root = self.fixture()
        if state != "new-untracked":  # that one changes main first, then branches
            self.branch(root)
        if not self.apply(root, rel, state):
            return
        if state == "new-untracked":
            self.branch(root)
        picked, out = self.verify(tmp, root)
        self.assertEqual(picked, expected, f"{rel} {state}: verify checked {sorted(picked)}\n{out}")
        if says:
            self.assertIn(says, out, f"{rel} {state}")

    def test_LOG_302_a_root_manifest_in_any_git_state_means_everything(self):
        for rel in MANIFESTS:
            for state in self.STATES:
                with self.subTest(rel=rel, state=state):
                    untracked = state in ("new-untracked", "untracked", "untracked-rm-cached", "ignored")
                    self.check(rel, state, ALL, f"{rel} is not tracked by git" if untracked else None)

    def test_LOG_302_a_package_file_in_any_git_state_means_its_package_and_dependents(self):
        for state in self.STATES:
            with self.subTest(state=state):
                self.check("packages/a/src/index.ts", state, {"packages/a", "packages/b"})
            with self.subTest(package="c", state=state):
                self.check("packages/c/src/index.ts", state, {"packages/c"})

    def test_LOG_302_nothing_changed_or_docs_only_means_no_package(self):
        tmp, root = self.fixture()
        self.branch(root)
        self.assertEqual(self.verify(tmp, root)[0], set())
        for state in ("committed", "unstaged", "new-untracked"):
            with self.subTest(state=state):
                tmp, root = self.fixture()
                self.branch(root)
                self.apply(root, "docs/notes.md", "committed" if state == "committed" else "unstaged")
                if state == "new-untracked":
                    (root / "docs/new.md").write_text("# New\n")
                self.assertEqual(self.verify(tmp, root)[0], set(), state)


class VerifyUntrackedCostTest(GitStates, unittest.TestCase):
    """LOG-302: counting untracked files into the scope must not start a process per file.

    verify.sh runs on every push (the pre-push hook), and a repo can hold thousands of untracked
    files (a `.venv`, generated code, assets not added yet). The script runs twice, with a few
    untracked files and with thousands in the same places (so the scope is the same), in a closed
    world: every command on PATH is a shim that logs its run, and xtrace prints each line with
    `$BASHPID`, so a command substitution or a pipeline shows up as a new subshell. Both counts must
    not grow with the number of files, and the traced lines per file stay a small constant (a walk
    up the tree for every file, even without forks, fails it)."""

    @staticmethod
    def bash_with_bashpid():
        """The tracer prints $BASHPID, which bash 3.2 (macOS's /bin/bash) does not have."""
        for cand in (shutil.which("bash"), "/opt/homebrew/bin/bash", "/usr/local/bin/bash"):
            if cand and os.access(cand, os.X_OK):
                out = subprocess.run([cand, "-c", "echo ${BASHPID:-}"], capture_output=True, text=True).stdout
                if out.strip().isdigit():
                    return cand
        return None

    def run_counted(self, tmp, root):
        bash = self.bash_with_bashpid()
        if bash is None:
            self.skipTest("needs a bash with $BASHPID (4+): brew install bash")
        shims = tmp / "shims"
        shutil.rmtree(shims, ignore_errors=True)
        shims.mkdir()
        execs, trace, args = tmp / "execs.txt", tmp / "trace.txt", tmp / "pnpm-args.txt"
        for f in (execs, trace, args):
            f.unlink(missing_ok=True)
        own = {  # the doctor, the secret scan and Docker have their own tests; pnpm only logs
            "pnpm": f"#!/bin/sh\nprintf '%s\\n' pnpm >> '{execs}'\n"
                    f"case \"$*\" in *'run typecheck') printf '%s\\n' \"$@\" > '{args}' ;; esac\n",
            "gitleaks": f"#!/bin/sh\nprintf '%s\\n' gitleaks >> '{execs}'\n",
            "python3": f"#!/bin/sh\nprintf '%s\\n' python3 >> '{execs}'\n",
            "docker": f"#!/bin/sh\nprintf '%s\\n' docker >> '{execs}'\nexit 1\n",
        }
        for d in os.environ["PATH"].split(os.pathsep):
            if not os.path.isdir(d):
                continue
            for name in os.listdir(d):
                real = os.path.join(d, name)
                if name in own or (shims / name).exists() or not os.access(real, os.X_OK) \
                        or os.path.isdir(real) or "'" in name:
                    continue
                own[name] = f"#!/bin/sh\nprintf '%s\\n' '{name}' >> '{execs}'\nexec '{real}' \"$@\"\n"
                (shims / name).write_text(own[name])
                (shims / name).chmod(0o755)
        for name in ("pnpm", "gitleaks", "python3", "docker"):
            (shims / name).write_text(own[name])
            (shims / name).chmod(0o755)
        env = {**os.environ, "PATH": str(shims)}
        script = 'exec 9>"$0"; BASH_XTRACEFD=9; PS4=\'+${BASHPID}| \'; set -x; . scripts/verify.sh'
        r = subprocess.run([bash, "-c", script, str(trace)], cwd=root, env=env,
                           capture_output=True, text=True, timeout=300)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        lines = [line for line in trace.read_text(errors="replace").splitlines() if line.startswith("+")]
        pids = {line.lstrip("+").split("|", 1)[0] for line in lines}
        ran = execs.read_text().split() if execs.exists() else []
        return {"processes": len(ran), "subshells": len(pids), "lines": len(lines),
                "scope": args.read_text() if args.exists() else None, "ran": ran}

    def untracked(self, root, many):
        """Untracked files at the root, in a venv-like tree with many directories and no package,
        deep inside package a, and in many directories of package a."""
        n = 1 if not many else None
        spots = {
            "root": [f"loose{i}.txt" for i in range(n or 300)],
            "venv": [f".venv/lib/p{i}/m{j}.py" for i in range(n or 100) for j in range(n or 10)],
            "deep": [f"packages/a/src/gen/x/y/z/f{i}.ts" for i in range(n or 1000)],
            "dirs": [f"packages/a/src/gen/d{i}/g.ts" for i in range(n or 100)],
        }
        paths = [p for group in spots.values() for p in group]
        for rel in paths:
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text("x\n")
        return len(paths)

    def test_LOG_302_untracked_files_cost_no_process_each(self):
        runs = {}
        for many in (False, True):
            tmp, root = self.fixture()
            self.branch(root)
            files = self.untracked(root, many)
            runs[many] = (files, self.run_counted(tmp, root))
        (few, small), (lots, large) = runs[False], runs[True]
        self.assertIn("...{./packages/a}", small["scope"] or "", small)
        self.assertEqual(large["scope"], small["scope"], "the same places, the same scope")
        self.assertEqual(large["processes"], small["processes"],
                         f"commands run: {few} untracked files {sorted(small['ran'])}, "
                         f"{lots} files {len(large['ran'])} runs")
        self.assertEqual(large["subshells"], small["subshells"],
                         f"subshells: {few} untracked files -> {small['subshells']}, "
                         f"{lots} -> {large['subshells']}")
        per_file = (large["lines"] - small["lines"]) / (lots - few)
        # A file in a directory already walked costs 6 traced lines; walking a deep file's 6 levels
        # again for every file costs about 20.
        self.assertLessEqual(per_file, 10, f"{per_file:.1f} traced lines per untracked file")


class FormatAndAuditShortcutsTest(GitStates, unittest.TestCase):
    """What `pnpm verify` formats and audits outside `--all`: only the changed files, and a green
    audit of the same lockfile is reused for 24 h. `--all` (CI) always runs both in full."""

    def run_verify(self, tmp, root, *flags):
        shims = tmp / "shims"
        shims.mkdir(exist_ok=True)
        log = tmp / "calls.txt"
        log.unlink(missing_ok=True)
        for name in ("pnpm", "python3"):
            (shims / name).write_text(f"#!/bin/sh\nprintf '%s\\n' \"{name} $*\" >> '{log}'\n")
            (shims / name).chmod(0o755)
        env = {**os.environ, "PATH": f"{shims}{os.pathsep}{os.environ['PATH']}"}
        r = subprocess.run(["bash", "scripts/verify.sh", *flags], cwd=root, env=env,
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return log.read_text().splitlines() if log.exists() else []

    def edit(self, root, rel, text="\nmore\n"):
        with open(root / rel, "a") as f:
            f.write(text)

    def prettier(self, calls):
        return [c for c in calls if "prettier" in c or "format:check" in c]

    def test_only_the_changed_files_are_format_checked_and_lint_is_cached(self):
        tmp, root = self.fixture()
        self.branch(root)
        self.edit(root, "docs/notes.md")
        (root / "docs/new.md").write_text("# New\n")
        calls = self.run_verify(tmp, root)
        self.assertEqual(self.prettier(calls), ["pnpm exec prettier --check --cache --ignore-unknown "
                                                "docs/new.md docs/notes.md"])
        self.assertIn("pnpm lint --cache", calls)

    def test_nothing_changed_checks_no_file(self):
        tmp, root = self.fixture()
        self.branch(root)
        self.assertEqual(self.prettier(self.run_verify(tmp, root)), [])

    def test_a_formatter_or_linter_config_change_checks_every_file(self):
        for config in (".prettierrc", "eslint.config.mjs", ".editorconfig", "prettier.config.js"):
            with self.subTest(config=config):
                tmp, root = self.fixture()
                self.branch(root)
                (root / config).write_text("{}\n")
                self.assertEqual(self.prettier(self.run_verify(tmp, root)), ["pnpm format:check"])

    def test_all_checks_every_file(self):
        tmp, root = self.fixture()
        self.branch(root)
        self.edit(root, "docs/notes.md")
        self.assertEqual(self.prettier(self.run_verify(tmp, root, "--all")), ["pnpm format:check"])

    def audits(self, calls):
        return [c for c in calls if "audit.py" in c]

    def test_a_green_audit_of_the_same_lockfile_is_reused_for_24_hours(self):
        tmp, root = self.fixture()
        self.branch(root)
        self.assertEqual(len(self.audits(self.run_verify(tmp, root))), 1)
        stamp = root / ".git/keelokit-audit-ok"
        self.assertTrue(stamp.exists())
        self.assertEqual(self.audits(self.run_verify(tmp, root)), [], "same lockfile: reused")
        self.assertEqual(len(self.audits(self.run_verify(tmp, root, "--all"))), 1, "--all always audits")
        old = stamp.stat().st_mtime - 25 * 3600
        os.utime(stamp, (old, old))
        self.assertEqual(len(self.audits(self.run_verify(tmp, root))), 1, "older than 24 h: audited again")

    def test_a_changed_lockfile_is_audited_again(self):
        tmp, root = self.fixture()
        self.branch(root)
        self.run_verify(tmp, root)
        self.edit(root, "pnpm-lock.yaml", "# bump\n")
        self.assertEqual(len(self.audits(self.run_verify(tmp, root))), 1)


class CriticalChangedTest(GitStates, unittest.TestCase):
    """The same matrix for `doctor.py --critical --changed`, the files `pnpm mutation` mutates."""

    def test_LOG_302_a_critical_file_in_any_git_state_counts_as_changed(self):
        for state in self.STATES:
            with self.subTest(state=state):
                tmp, root = self.fixture()
                self.branch(root)
                if not self.apply(root, "packages/a/src/index.ts", state):
                    continue
                out = sh(root, sys.executable, ".keelokit/bin/doctor.py", "--critical", "--changed").split()
                want = {"new-untracked": ["packages/a/src/new.ts"], "deleted": []}.get(state, ["packages/a/src/index.ts"])
                self.assertEqual(out, want, state)


if __name__ == "__main__":
    unittest.main()
