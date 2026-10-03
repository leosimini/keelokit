"""RUN-1: template/.keelokit/bin/run-local.sh finds the Expo app and its backend in repos of different
shapes, checks that [local] is coherent, diagnoses the Mac without installing, and never kills, stops
or edits anything it was not allowed to. Run: python3 -m unittest discover -s tests

Nothing here touches the machine: each case builds a throwaway project, and the commands the script
reaches (node, docker, adb, xcodebuild, kill...) are shims on a PATH that holds only core utilities,
so the answer never depends on what the machine running the tests has installed."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "template/.keelokit/bin/run-local.sh"
CORE = ["bash", "awk", "sed", "grep", "sort", "tr", "cat", "ls", "head", "tail", "cut", "basename", "dirname",
        "date", "git", "env", "perl", "seq", "mkdir", "tee", "sleep", "touch", "cp", "rm", "wc", "id", "python3"]
PROFILE = 'kind = "mobile-app"\ntraits = ["mobile"]\n'
LOCAL_OK = """
[local]
mobile_dir = "apps/mobile"
pm = "pnpm"
api_dir = "apps/api"
api_start = "pnpm run dev:api"
db_service = "postgres"
"""


def write(base: Path, rel: str, text: str = "") -> None:
    p = base / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def pnpm_monorepo(d: Path) -> None:
    write(d, "package.json", json.dumps({"name": "demo", "scripts": {"dev:api": "pnpm --filter ./apps/api dev"}}))
    write(d, "pnpm-lock.yaml")
    write(d, "apps/mobile/package.json", json.dumps({"dependencies": {"expo": "~57.0.25", "react-native-screens": "~4.26.0"}}))
    write(d, "apps/mobile/app.json", json.dumps({"expo": {"android": {"package": "com.demo.app"}}}))
    write(d, "apps/mobile/.env.example", "EXPO_PUBLIC_API_URL=http://localhost:3000\n")
    write(d, "apps/api/package.json", json.dumps({"dependencies": {"@nestjs/core": "^12", "prisma": "^7"},
          "scripts": {"dev": "nest start --watch", "prisma:generate": "prisma generate", "prisma:migrate:deploy": "prisma migrate deploy"}}))
    write(d, "apps/api/prisma/schema.prisma")
    write(d, "apps/api/.env.example", "PORT=3000\n")
    write(d, "apps/api/src/health.controller.ts", "@Controller('health') class H {}")
    write(d, "docker-compose.yml", "services:\n  postgres:\n    image: postgres:16\n    ports:\n      - '${POSTGRES_PORT:-5432}:5432'\n")


def npm_backend(d: Path) -> None:
    """A project that is nobody's template: npm, the API in backend/, the db service named db, the
    compose file also running the backend, the API url in eas.json with a /api/v1 prefix."""
    write(d, "package.json", json.dumps({"name": "gc", "workspaces": ["apps/*", "backend"]}))
    write(d, "package-lock.json")
    write(d, "apps/mobile/package.json", json.dumps({"dependencies": {"expo": "~52.0.0", "expo-dev-client": "~5.0.0"}}))
    write(d, "apps/mobile/app.config.ts", "export default { android: { package: 'app.gc.mobile' } };")
    write(d, "apps/mobile/eas.json", json.dumps({"build": {"development": {"env": {"EXPO_PUBLIC_API_BASE_URL": "http://localhost:3000/api/v1"}}}}))
    write(d, "backend/package.json", json.dumps({"dependencies": {"express": "^4", "@prisma/client": "^6"}, "scripts": {"dev": "tsx watch src/index.ts"}}))
    write(d, "backend/prisma/schema.prisma")
    write(d, "docker-compose.yml",
          "services:\n  db:\n    image: postgres:16\n    ports:\n      - '5432:5432'\n  backend:\n    build: ./backend\n    ports:\n      - '3000:3000'\n")


def no_expo(d: Path) -> None:
    write(d, "package.json", json.dumps({"name": "api-only", "dependencies": {"express": "^4"}}))
    write(d, "package-lock.json")
    write(d, "src/index.ts", "// no app here")


class Project:
    """A throwaway git repo with the script installed where an adopted or generated project has it."""

    def __init__(self, test: unittest.TestCase, build, profile: str = PROFILE, lang: str | None = None):
        tmp = tempfile.TemporaryDirectory()
        test.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name) / "proj"
        self.dir.mkdir()
        build(self.dir)
        write(self.dir, ".keelokit/profile.toml", profile)
        if lang:
            write(self.dir, ".keelokit/state.toml", f'[dashboard]\nlang = "{lang}"\n')
        (self.dir / ".keelokit/bin").mkdir(parents=True, exist_ok=True)
        shutil.copy(SCRIPT, self.dir / ".keelokit/bin/run-local.sh")
        self.bin = Path(tmp.name) / "bin"
        self.bin.mkdir()
        self.calls = Path(tmp.name) / "calls.log"
        self.calls.touch()
        for name in CORE:
            real = sys.executable if name == "python3" else shutil.which(name)
            if real:
                (self.bin / name).symlink_to(real)
        subprocess.run(["git", "init", "-q"], cwd=self.dir, check=True)
        self.home = Path(tmp.name) / "home"
        self.home.mkdir()

    def shim(self, name: str, body: str = "", code: int = 0) -> None:
        """A command that logs its call; `body` runs before it exits with `code`."""
        f = self.bin / name
        f.write_text(f'#!/bin/bash\necho "{name} $*" >>"{self.calls}"\n{body}\nexit {code}\n')
        f.chmod(0o755)

    def run(self, *args: str, stdin: str = "", env: dict | None = None):
        e = {"PATH": str(self.bin), "HOME": str(self.home), "LANG": "en_US.UTF-8", **(env or {})}
        return subprocess.run(["bash", ".keelokit/bin/run-local.sh", *args], cwd=self.dir, env=e, input=stdin,
                              capture_output=True, text=True, timeout=60)

    def called(self) -> list[str]:
        return self.calls.read_text().splitlines()


class DetectTest(unittest.TestCase):
    def detect(self, build) -> dict:
        p = Project(self, build)
        r = p.run("detect")
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_pnpm_monorepo_with_a_nest_api(self):
        d = self.detect(pnpm_monorepo)
        self.assertEqual(
            {k: d[k] for k in ("mobile_dir", "pm", "android_package", "api_dir", "db_service", "api_url_env", "api_url_suffix", "api_port")},
            {"mobile_dir": "apps/mobile", "pm": "pnpm", "android_package": "com.demo.app", "api_dir": "apps/api",
             "db_service": "postgres", "api_url_env": "EXPO_PUBLIC_API_URL", "api_url_suffix": "", "api_port": "3000"})
        self.assertEqual(d["api_start"], "pnpm run dev:api")
        self.assertEqual(d["api_migrate"], "pnpm --dir apps/api run prisma:generate && pnpm --dir apps/api run prisma:migrate:deploy")
        self.assertEqual(d["api_ready_url"], "http://localhost:3000/health")
        self.assertEqual(d["uncertain"], [])

    def test_npm_project_with_its_own_names(self):
        d = self.detect(npm_backend)
        self.assertEqual(
            {k: d[k] for k in ("mobile_dir", "pm", "android_package", "api_dir", "db_service", "api_url_env", "api_url_suffix")},
            {"mobile_dir": "apps/mobile", "pm": "npm", "android_package": "app.gc.mobile", "api_dir": "backend",
             "db_service": "db", "api_url_env": "EXPO_PUBLIC_API_BASE_URL", "api_url_suffix": "/api/v1"})
        self.assertEqual(d["api_start"], "npm --prefix backend run dev")
        self.assertEqual(d["api_migrate"], "cd backend && npx prisma generate && npx prisma migrate deploy")
        self.assertEqual(d["api_ready_url"], "")  # no health route to be found: it waits for the port instead

    def test_no_expo_app(self):
        d = self.detect(no_expo)
        self.assertEqual((d["mobile_dirs"], d["mobile_dir"]), ([], ""))

    def test_two_expo_apps_are_uncertain(self):
        def two(d: Path):
            pnpm_monorepo(d)
            write(d, "apps/other/package.json", json.dumps({"dependencies": {"expo": "~57.0.0"}}))
            write(d, "apps/other/app.json", json.dumps({"expo": {}}))
        d = self.detect(two)
        self.assertEqual(sorted(d["mobile_dirs"]), ["apps/mobile", "apps/other"])
        self.assertIn("mobile_dir", d["uncertain"])


class CheckTest(unittest.TestCase):
    """`doctor --check`: what RUN-1 runs. Any OS, nothing installed, nothing asked."""

    def check(self, build, profile=PROFILE, lang=None, os_name="Linux"):
        p = Project(self, build, profile, lang)
        p.shim("uname", f'echo {os_name}')
        r = p.run("doctor", "--check")
        return p, r

    def test_valid_local_block_passes(self):
        _, r = self.check(pnpm_monorepo, PROFILE + LOCAL_OK)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("[local] is coherent", r.stdout)

    def test_missing_block_fails_and_names_the_fix(self):
        _, r = self.check(pnpm_monorepo)
        self.assertEqual(r.returncode, 1)
        self.assertIn("no [local] block", r.stdout)
        self.assertIn("run-local.sh doctor", r.stdout)

    def test_expo_app_not_where_local_says_fails(self):
        _, r = self.check(pnpm_monorepo, PROFILE + LOCAL_OK.replace("apps/mobile", "apps/phone"))
        self.assertEqual(r.returncode, 1)
        self.assertIn('mobile_dir "apps/phone" has no Expo app', r.stdout)

    def test_backend_folder_and_package_manager_must_exist(self):
        bad = PROFILE + LOCAL_OK.replace('"apps/api"', '"nope"').replace('"pnpm"', '"bun"')
        _, r = self.check(pnpm_monorepo, bad)
        self.assertEqual(r.returncode, 1)
        self.assertIn('api_dir "nope" does not exist', r.stdout)
        self.assertIn('pm "bun" is not pnpm, npm or yarn', r.stdout)

    def test_a_repo_without_expo_is_clean(self):
        _, r = self.check(no_expo)
        self.assertEqual(r.returncode, 0)
        self.assertIn("no Expo app here", r.stdout)

    def test_messages_follow_the_project_language(self):
        _, r = self.check(no_expo, lang="es")
        self.assertIn("no hay app Expo", r.stdout)
        _, r = self.check(no_expo, lang="en")
        self.assertIn("no Expo app here", r.stdout)

    def test_check_writes_nothing(self):
        p, r = self.check(pnpm_monorepo, PROFILE + LOCAL_OK)
        self.assertFalse((p.dir / ".local-dev").exists())
        self.assertEqual(p.called(), [])


class MacTest(unittest.TestCase):
    def mac(self, build=pnpm_monorepo, profile=PROFILE + LOCAL_OK):
        p = Project(self, build, profile)
        p.shim("uname", "echo Darwin")
        return p

    def test_other_systems_exit_clean_without_trying_anything(self):
        p = Project(self, pnpm_monorepo, PROFILE + LOCAL_OK)
        p.shim("uname", "echo Linux")
        r = p.run("doctor")
        self.assertEqual(r.returncode, 0)
        self.assertIn("macOS only", r.stdout)
        self.assertEqual(p.called(), ["uname -s"])

    def test_diagnosis_lists_everything_missing_at_once_and_installs_nothing(self):
        p = self.mac()
        p.shim("brew")
        r = p.run("doctor", "--no-install", env={"JAVA_HOME_BIN": "/nonexistent"})
        self.assertEqual(r.returncode, 1)
        for item in ("Node 18", "pnpm", "Docker Desktop", "dependencies (pnpm install)", "apps/api/.env", "JDK 17",
                     "Android platform-tools (adb)", "Xcode is not installed"):
            self.assertIn(item, r.stdout)
        self.assertEqual([c for c in p.called() if not c.startswith(("uname", "brew --prefix"))], [], "nothing is installed or started")

    def test_everything_present_passes(self):
        p = self.mac()
        for name, body in {
            "node": 'echo v22.12.0', "pnpm": 'echo 10.0.0', "docker": "", "adb": "", "pod": "",
            "xcodebuild": '[ "$1" = -version ] && echo "Xcode 26.5"',
            "xcrun": 'echo "    iPhone 17 Pro (11111111-2222-3333-4444-555555555555) (Shutdown)"',
        }.items():
            p.shim(name, body)
        java = p.dir.parent / "java_home"
        java.write_text("#!/bin/bash\necho /fake/jdk\n")
        java.chmod(0o755)
        sdk = p.dir.parent / "sdk"
        write(sdk, "licenses/android-sdk-license", "x")
        write(p.dir, "node_modules/.pnpm/x")
        time = 1_700_000_000
        os.utime(p.dir / "pnpm-lock.yaml", (time, time))
        write(p.dir, "node_modules/.modules.yaml")
        write(p.dir, "apps/api/.env")
        r = p.run("doctor", "--no-install", env={"JAVA_HOME_BIN": str(java), "ANDROID_HOME": str(sdk)})
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_missing_block_is_detected_shown_and_saved_only_after_a_yes(self):
        p = self.mac(profile=PROFILE)
        r = p.run("doctor", "--no-install", stdin="n\n")
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("[local]", (p.dir / ".keelokit/profile.toml").read_text())
        self.assertIn("apps/mobile", r.stdout)
        r = p.run("doctor", "--no-install", "--yes")
        saved = (p.dir / ".keelokit/profile.toml").read_text()
        self.assertIn('[local]\nmobile_dir = "apps/mobile"', saved)
        self.assertIn('db_service = "postgres"', saved)
        self.assertIn("api_port = 3000", saved)
        self.assertEqual(p.run("doctor", "--check").returncode, 0)


class SourcedTest(unittest.TestCase):
    """Functions run on their own with shims: the script's promises about what it never does."""

    def lib(self, p: Project, body: str, stdin: str = "", env: dict | None = None):
        e = {"PATH": str(p.bin), "HOME": str(p.home), "RUN_LOCAL_LIB": "1", **(env or {})}
        script = f'cd "{p.dir}"; . .keelokit/bin/run-local.sh; load_config; {body}'
        return subprocess.run(["bash", "-c", script], env=e, input=stdin, capture_output=True, text=True, timeout=60)

    def test_the_state_folder_and_gitignore_are_written_only_after_a_yes(self):
        p = Project(self, pnpm_monorepo, PROFILE + LOCAL_OK)
        r = self.lib(p, "init_state; echo rc=$?", stdin="n\n")
        self.assertIn("rc=1", r.stdout)
        self.assertFalse((p.dir / ".gitignore").exists() or (p.dir / ".local-dev").exists())
        r = self.lib(p, "init_state; echo rc=$?", stdin="y\n")
        self.assertIn("rc=0", r.stdout)
        self.assertIn(".local-dev/", (p.dir / ".gitignore").read_text())
        self.assertTrue((p.dir / ".local-dev/logs").is_dir())

    def test_a_state_folder_without_logs_still_gets_them(self):
        # .local-dev/ can exist (a worktree, an earlier tool) without logs/: every step writes there.
        p = Project(self, pnpm_monorepo, PROFILE + LOCAL_OK)
        (p.dir / ".gitignore").write_text(".local-dev/\n")
        (p.dir / ".local-dev").mkdir()
        r = self.lib(p, "init_state; echo rc=$?")
        self.assertIn("rc=0", r.stdout)
        self.assertTrue((p.dir / ".local-dev/logs").is_dir())

    def sleeper(self, p: Project):
        """A real process that a `lsof` shim reports as the port's owner, so a kill can be seen."""
        proc = subprocess.Popen(["sleep", "60"])
        self.addCleanup(lambda: (proc.kill(), proc.wait()))
        p.shim("lsof", f"echo {proc.pid}")
        p.shim("ps", "echo node")
        return proc

    def test_a_busy_port_is_never_freed_without_a_yes(self):
        p = Project(self, pnpm_monorepo, PROFILE + LOCAL_OK)
        proc = self.sleeper(p)
        r = self.lib(p, "free_port 8081; echo rc=$?", stdin="n\n")
        self.assertIn("rc=1", r.stdout)
        self.assertIsNone(proc.poll(), "declined: the process lives")
        r = self.lib(p, "free_port 8081; echo rc=$?", stdin="y\n")
        self.assertIn("rc=0", r.stdout)
        proc.wait(timeout=10)

    def test_stop_asks_before_stopping_the_api_and_the_container(self):
        p = Project(self, pnpm_monorepo, PROFILE + LOCAL_OK)
        proc = self.sleeper(p)
        p.shim("docker")
        self.lib(p, "stop_backend", stdin="n\nn\n")
        self.assertIsNone(proc.poll())
        self.assertFalse([c for c in p.called() if c.startswith("docker")])

    def entitlements(self, tracked: bool, answer: str):
        p = Project(self, pnpm_monorepo, PROFILE + LOCAL_OK)
        ent = "apps/mobile/ios/Demo/Demo.entitlements"
        write(p.dir, ent, "com.apple.developer.applesignin\ncom.apple.developer.associated-domains\ncom.apple.security.app-sandbox\n")
        if tracked:
            subprocess.run(["git", "add", "-f", ent], cwd=p.dir, check=True)
        plist = p.dir.parent / "PlistBuddy"
        plist.write_text(f'''#!/bin/bash
echo "PlistBuddy $*" >>"{p.calls}"
key=${{2#*:}}
case "$2" in
  Print*) grep -qx "$key" "$3" ;;
  Delete*) sed -i.bak "/^$key$/d" "$3" ;;
esac
''')
        plist.chmod(0o755)
        r = self.lib(p, "strip_entitlements; echo rc=$?", stdin=answer, env={"PLISTBUDDY": str(plist)})
        return p, r, (p.dir / ent).read_text()

    def test_simulator_strip_shows_the_list_asks_once_and_removes_only_those(self):
        p, r, text = self.entitlements(tracked=False, answer="y\ny\n")
        self.assertIn("com.apple.developer.applesignin", r.stdout)
        self.assertIn("com.apple.developer.associated-domains", r.stdout)
        self.assertNotIn("applesignin", text)
        self.assertIn("com.apple.security.app-sandbox", text)
        self.assertTrue((p.dir / ".local-dev/entitlements-ok").exists())

    def test_declined_strip_changes_nothing_and_stops(self):
        _, r, text = self.entitlements(tracked=False, answer="n\n")
        self.assertIn("rc=1", r.stdout)
        self.assertIn("applesignin", text)

    def test_ios_tracked_by_git_is_never_edited(self):
        p, r, text = self.entitlements(tracked=True, answer="y\n")
        self.assertIn("is tracked by git", r.stdout)
        self.assertIn("applesignin", text)
        self.assertFalse([c for c in p.called() if "Delete" in c])


class StaticTest(unittest.TestCase):
    def test_bash_3_2_compatible(self):
        """macOS ships bash 3.2: no mapfile, associative arrays, case conversion or negative indexes."""
        text = "\n".join(l for l in SCRIPT.read_text().splitlines() if not l.lstrip().startswith("#"))
        for pat in (r"\bmapfile\b", r"\breadarray\b", r"declare -A", r"\$\{[A-Za-z_]+(,,|\^\^)", r"\[-\d+\]", r"&>>", r"\|&"):
            self.assertIsNone(re.search(pat, text), pat)
        r = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_simulator_is_launched_by_name_never_by_udid(self):
        text = SCRIPT.read_text()
        self.assertIn('run:ios --device "$I_NAME"', text)
        self.assertNotIn('--device "$I_UDID"', text)

    def test_never_removes_ios_or_android_folders(self):
        self.assertIsNone(re.search(r"rm -rf?[^\n]*(ios|android)", SCRIPT.read_text()))


if __name__ == "__main__":
    unittest.main()
