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
        "date", "git", "env", "perl", "seq", "mkdir", "tee", "sleep", "touch", "cp", "rm", "wc", "id", "python3", "du", "mv", "ln", "nohup", "mktemp", "mkfifo"]
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
        bad = PROFILE + LOCAL_OK.replace('"apps/api"', '"nope"').replace('"pnpm"', '"make"')
        _, r = self.check(pnpm_monorepo, bad)
        self.assertEqual(r.returncode, 1)
        self.assertIn('api_dir "nope" does not exist', r.stdout)
        self.assertIn('pm "make" is not pnpm, npm, yarn or bun', r.stdout)

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
        self.assertEqual(r.returncode, 3, "Xcode is missing: only a person can fix it")
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


def layout(d: Path, lock: str = "pnpm-lock.yaml", root_scripts: dict | None = None, api_scripts: dict | None = None,
           extra: dict | None = None, api_name: str = "@demo/api", mobile_deps: dict | None = None,
           api_pkg: dict | None = None, compose: str | None = None) -> None:
    """A monorepo with the package manager, root scripts and tools varied by the caller."""
    write(d, "package.json", json.dumps({"name": "demo", "scripts": root_scripts or {}, **(extra or {})}))
    write(d, lock, "")
    write(d, "apps/mobile/package.json", json.dumps({"dependencies": mobile_deps or {"expo": "~57.0.0", "react-native": "0.86.3"}}))
    write(d, "apps/mobile/app.json", json.dumps({"expo": {"android": {"package": "com.demo.app"}, "ios": {"bundleIdentifier": "com.demo.app"}, "scheme": "demo"}}))
    write(d, "apps/api/package.json", json.dumps({"name": api_name, "dependencies": {"@nestjs/core": "^12"},
          "scripts": api_scripts if api_scripts is not None else {"dev": "nest start --watch"}, **(api_pkg or {})}))
    if compose is not None:
        write(d, "docker-compose.yml", compose)


class DetectMoreTest(unittest.TestCase):
    def detect(self, build) -> dict:
        p = Project(self, build)
        r = p.run("detect")
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_yarn_classic_runs_in_a_folder_with_cwd(self):
        d = self.detect(lambda d: layout(d, "yarn.lock"))
        self.assertEqual((d["pm"], d["api_start"]), ("yarn", "yarn --cwd apps/api run dev"))

    def test_yarn_berry_runs_inside_the_folder(self):
        def berry(d):
            layout(d, "yarn.lock")
            write(d, ".yarnrc.yml", "nodeLinker: node-modules\n")
        d = self.detect(berry)
        self.assertEqual((d["pm"], d["api_start"]), ("yarn", "cd apps/api && yarn run dev"))

    def test_berry_is_read_from_package_manager_too(self):
        d = self.detect(lambda d: layout(d, "yarn.lock", extra={"packageManager": "yarn@4.1.0"}))
        self.assertEqual(d["api_start"], "cd apps/api && yarn run dev")

    def test_bun(self):
        d = self.detect(lambda d: layout(d, "bun.lockb"))
        self.assertEqual((d["pm"], d["api_start"]), ("bun", "bun --cwd apps/api run dev"))
        d = self.detect(lambda d: layout(d, "bun.lock"))
        self.assertEqual(d["pm"], "bun")

    def test_turborepo_filters_by_the_api_package(self):
        def turbo(d):
            layout(d)
            write(d, "turbo.json", "{}")
        d = self.detect(turbo)
        self.assertEqual((d["runner"], d["api_start"]), ("turbo", "pnpm exec turbo run dev --filter=@demo/api"))

    def test_lerna_scopes_to_the_api_package(self):
        def lerna(d):
            layout(d, "package-lock.json")
            write(d, "lerna.json", "{}")
        d = self.detect(lerna)
        self.assertEqual((d["runner"], d["api_start"]), ("lerna", "npx lerna run dev --scope @demo/api --stream"))

    def test_nx_is_a_guess_and_says_so(self):
        def nx(d):
            layout(d)
            write(d, "nx.json", "{}")
        d = self.detect(nx)
        self.assertEqual(d["runner"], "nx")
        self.assertIn("api_start", d["uncertain"])

    def test_a_root_dev_api_style_script_wins_over_the_runner(self):
        def both(d):
            layout(d, root_scripts={"api:dev": "turbo run dev --filter=@demo/api"})
            write(d, "turbo.json", "{}")
        self.assertEqual(self.detect(both)["api_start"], "pnpm run api:dev")

    def test_services_are_the_image_based_ones_besides_the_database(self):
        compose = ("services:\n  db:\n    image: postgres:16\n  redis:\n    image: redis:7\n  mailpit:\n    image: axllent/mailpit\n"
                   "  backend:\n    build: ./apps/api\n")
        d = self.detect(lambda d: layout(d, compose=compose))
        self.assertEqual((d["db_service"], d["services"]), ("db", ["redis", "mailpit"]))
        self.assertNotIn("services", d["uncertain"])

    def test_a_service_built_from_source_that_is_not_obviously_the_api_is_uncertain(self):
        compose = "services:\n  db:\n    image: postgres:16\n  worker:\n    build: ./worker\n"
        d = self.detect(lambda d: layout(d, compose=compose))
        self.assertEqual(d["services"], [])
        self.assertIn("services", d["uncertain"])

    def test_seed_scripts_are_found_in_order(self):
        d = self.detect(lambda d: layout(d, api_scripts={"dev": "x", "seed": "x", "db:seed": "x"}))
        self.assertEqual(d["api_seed"], "pnpm --dir apps/api run db:seed")
        d = self.detect(lambda d: layout(d, api_scripts={"dev": "x", "seed:demo": "x"}))
        self.assertEqual(d["api_seed"], "pnpm --dir apps/api run seed:demo")
        d = self.detect(lambda d: layout(d, api_pkg={"prisma": {"seed": "tsx prisma/seed.ts"}}))
        self.assertEqual(d["api_seed"], "cd apps/api && npx prisma db seed")
        self.assertEqual(self.detect(lambda d: layout(d))["api_seed"], "")

    def test_jdk_follows_react_native_then_the_expo_sdk(self):
        for deps, jdk in (({"expo": "~49.0.0", "react-native": "0.72.6"}, "11"), ({"expo": "~50.0.0", "react-native": "0.73.2"}, "17"),
                          ({"expo": "~57.0.0", "react-native": "^0.86.3"}, "17"), ({"expo": "~49.0.0"}, "11"), ({"expo": "~52.0.0"}, "17")):
            with self.subTest(deps=deps):
                self.assertEqual(self.detect(lambda d: layout(d, mobile_deps=deps))["jdk"], jdk)

    def test_node_comes_from_nvmrc_node_version_or_engines(self):
        def nvmrc(d):
            layout(d)
            write(d, ".nvmrc", "v20.11.0\n")
        self.assertEqual(self.detect(nvmrc)["node"], "20")
        def nv(d):
            layout(d)
            write(d, ".node-version", "22.3.0\n")
        self.assertEqual(self.detect(nv)["node"], "22")
        self.assertEqual(self.detect(lambda d: layout(d, extra={"engines": {"node": ">=18.17"}}))["node"], "18")
        self.assertEqual(self.detect(lambda d: layout(d))["node"], "")

    def test_scheme_and_bundle_id(self):
        d = self.detect(lambda d: layout(d))
        self.assertEqual((d["scheme"], d["ios_bundle"], d["android_package"]), ("demo", "com.demo.app", "com.demo.app"))


class Lib:
    """Sources the script with shims and runs a snippet: functions on their own."""

    def lib(self, p: Project, body: str, stdin: str = "", env: dict | None = None):
        e = {"PATH": str(p.bin), "HOME": str(p.home), "RUN_LOCAL_LIB": "1", **(env or {})}
        script = f'cd "{p.dir}"; . .keelokit/bin/run-local.sh; load_config; {body}'
        return subprocess.run(["bash", "-c", script], env=e, input=stdin, capture_output=True, text=True, timeout=90)


LOCAL_DEV = PROFILE + """
[local]
mobile_dir = "apps/mobile"
pm = "pnpm"
api_dir = "apps/api"
api_start = "true"
api_migrate = ""
db_service = "postgres"
client = "dev-client"
android_package = "com.demo.app"
ios_bundle = "com.demo.app"
scheme = "demo"
"""


class DecisionTableTest(Lib, unittest.TestCase):
    """A: relaunch without rebuilding."""

    def decide(self, installed, now, last, flags=""):
        p = Project(self, pnpm_monorepo, LOCAL_DEV)
        r = self.lib(p, f'{flags or ":"}; decide_build {installed} "{now}" "{last}"; echo "$BUILD_PATH"')
        return r.stdout.strip()

    def test_the_table(self):
        rows = [
            # installed, now, last, flags, expected
            (1, "files:a", "files:a", "", "fast"),
            (1, "files:a", "files:b", "", "build"),
            (1, "files:a", "", "", "build"),
            (1, "", "files:a", "", "build"),
            (0, "files:a", "files:a", "", "build"),
            (0, "files:a", "", "", "build"),
            (1, "files:a", "files:a", "REBUILD=1", "build"),
            (1, "files:a", "files:b", "NOBUILD=1", "fast"),
            (1, "", "", "NOBUILD=1", "fast"),
            (0, "files:a", "files:a", "NOBUILD=1", "fail"),
            (0, "files:a", "files:a", "REBUILD=1", "build"),
            (1, "expo:x", "files:x", "", "build"),
        ]
        for installed, now, last, flags, want in rows:
            with self.subTest(installed=installed, now=now, last=last, flags=flags):
                self.assertEqual(self.decide(installed, now, last, flags), want)

    def test_the_reason_is_said(self):
        p = Project(self, pnpm_monorepo, LOCAL_DEV)
        r = self.lib(p, 'decide_build 1 files:a files:b; echo "$BUILD_WHY"')
        self.assertIn("native inputs changed", r.stdout)
        r = self.lib(p, 'NOBUILD=1; decide_build 0 files:a files:a; echo "$BUILD_WHY"')
        self.assertIn("--no-build", r.stdout)

    def test_state_is_kept_per_target(self):
        p = Project(self, pnpm_monorepo, LOCAL_DEV)
        r = self.lib(p, 'state_set android S1 files:a 1.0; state_set ios U1 files:i 2.0; state_set android S1 files:b 1.1; '
                        'state_get android S1; state_get ios U1; state_get android S2; echo end', stdin="y\n")
        self.assertEqual(r.stdout.split(), ["files:b|1.1", "files:i|2.0", "end"])

    def native(self, launch_body: str, installed: int = 1):
        p = Project(self, pnpm_monorepo, LOCAL_DEV)
        script = (f'init_state; state_set android S1 files:old 0.9; fingerprint() {{ echo files:new; }}; app_version() {{ echo 1.0; }}; '
                  f'chk() {{ return {0 if installed else 1}; }}; launch() {{ {launch_body}; }}; native_build android S1 chk android true; echo rc=$?; state_get android S1')
        r = self.lib(p, script, stdin="y\n")
        return r.stdout.split()

    def test_a_failed_build_leaves_no_fingerprint(self):
        out = self.native("return 1")
        self.assertEqual(out, ["rc=1"], "the old fingerprint is gone and no new one was written")

    def test_an_interrupted_build_with_no_success_line_leaves_none(self):
        self.assertEqual(self.native("return 0"), ["rc=0"])

    def test_a_build_that_succeeded_but_installed_nothing_leaves_none(self):
        self.assertEqual(self.native('echo "BUILD SUCCESSFUL" >"$LOG/android.log"; return 0', installed=0), ["rc=0"])

    def test_a_successful_installed_build_records_the_fingerprint(self):
        self.assertEqual(self.native('echo "BUILD SUCCESSFUL in 4m" >"$LOG/android.log"; return 0'), ["rc=0", "files:new|1.0"])

    def test_fingerprint_changes_with_native_inputs_only(self):
        p = Project(self, pnpm_monorepo, LOCAL_DEV)
        def fp():
            return self.lib(p, "fingerprint").stdout.strip()
        base = fp()
        self.assertTrue(base.startswith("files:"))
        self.assertEqual(fp(), base)
        write(p.dir, "apps/mobile/src/App.tsx", "export default 1")  # JS only: Metro reloads it
        write(p.dir, "README.md", "x")
        self.assertEqual(fp(), base)
        changed = []
        pkg = p.dir / "apps/mobile/package.json"
        pkg.write_text(json.dumps({"dependencies": {"expo": "~57.0.0", "expo-camera": "1.0.0"}}))
        changed.append(fp())
        write(p.dir, "pnpm-lock.yaml", "lock: changed")
        changed.append(fp())
        write(p.dir, "apps/mobile/app.json", json.dumps({"expo": {"name": "x"}}))
        changed.append(fp())
        write(p.dir, "apps/mobile/ios/Podfile", "pod 'A'")
        subprocess.run(["git", "add", "-f", "apps/mobile/ios/Podfile"], cwd=p.dir, check=True)
        changed.append(fp())
        write(p.dir, "apps/mobile/ios/Podfile", "pod 'B'")
        changed.append(fp())
        self.assertEqual(len({base, *changed}), 6, "each native input changes it")

    def test_expo_fingerprint_is_preferred_when_the_project_has_it(self):
        p = Project(self, pnpm_monorepo, LOCAL_DEV)
        (p.dir / "apps/mobile/node_modules/@expo/fingerprint").mkdir(parents=True)
        p.shim("npx", 'echo \'{"sources": [], "hash": "abc123"}\'')
        self.assertEqual(self.lib(p, "fingerprint").stdout.strip(), "expo:abc123")
        p.shim("npx", "echo not json")  # a CLI that answers badly: back to the file hash
        self.assertTrue(self.lib(p, "fingerprint").stdout.strip().startswith("files:"))

    def test_the_fingerprint_is_tried_through_npx_even_when_the_package_is_not_hoisted(self):
        # pnpm keeps @expo/fingerprint out of the app's node_modules; npx still finds it
        p = Project(self, pnpm_monorepo, LOCAL_DEV)
        self.assertFalse((p.dir / "apps/mobile/node_modules").exists())
        p.shim("npx", 'echo \'{"sources": [], "hash": "abc123"}\'')
        self.assertEqual(self.lib(p, "fingerprint").stdout.strip(), "expo:abc123")
        self.assertIn("npx --no-install @expo/fingerprint .", p.called())
        p.shim("npx", "", code=1)  # the command fails: the file hash
        self.assertTrue(self.lib(p, "fingerprint").stdout.strip().startswith("files:"))
        p.shim("npx", 'echo \'{"sources": []}\'')  # JSON with no hash: the file hash
        self.assertTrue(self.lib(p, "fingerprint").stdout.strip().startswith("files:"))

    def test_a_project_without_expo_does_not_call_npx(self):
        def build(d):
            no_expo(d)
        p = Project(self, build, PROFILE)
        p.shim("npx", 'echo \'{"hash": "x"}\'')
        self.lib(p, "MOBILE_DIR=; fingerprint")
        self.assertEqual([c for c in p.called() if c.startswith("npx")], [])

    def test_a_hung_npx_cannot_freeze_a_launch(self):
        p = Project(self, pnpm_monorepo, LOCAL_DEV)
        p.shim("npx", "sleep 30")
        import time
        t = time.time()
        r = self.lib(p, "fingerprint", env={"FINGERPRINT_TIMEOUT": "1"})
        self.assertLess(time.time() - t, 15)
        self.assertTrue(r.stdout.strip().startswith("files:"))

    def test_installed_checks_use_pm_path_and_get_app_container(self):
        p = Project(self, pnpm_monorepo, LOCAL_DEV)
        p.shim("adb", 'case "$*" in *"pm path"*) echo package:/data/app/base.apk;; esac')
        p.shim("xcrun", 'case "$*" in *get_app_container*) echo /path;; *) exit 1;; esac')
        r = self.lib(p, 'A_SERIAL=S1; android_installed && echo a-yes; I_UDID=U1; ios_installed && echo i-yes')
        self.assertEqual(r.stdout.split(), ["a-yes", "i-yes"])
        self.assertIn("adb -s S1 shell pm path com.demo.app", p.called())
        self.assertIn("xcrun simctl get_app_container U1 com.demo.app", p.called())
        p.shim("adb", "")
        p.shim("xcrun", "", code=1)
        r = self.lib(p, 'A_SERIAL=S1; android_installed || echo a-no; I_UDID=U1; ios_installed || echo i-no')
        self.assertEqual(r.stdout.split(), ["a-no", "i-no"])

    def test_opening_the_app_uses_the_scheme_link_or_launches_it(self):
        p = Project(self, pnpm_monorepo, LOCAL_DEV)
        p.shim("adb")
        p.shim("xcrun")
        self.lib(p, "A_SERIAL=S1; open_app android; I_UDID=U1; open_app ios")
        link = "demo://expo-development-client/?url=http%3A%2F%2Flocalhost%3A8081"
        self.assertIn(f"adb -s S1 shell am start -a android.intent.action.VIEW -d {link}", p.called())
        self.assertIn(f"xcrun simctl openurl U1 {link}", p.called())
        self.lib(p, 'SCHEME=; A_SERIAL=S1; open_app android; I_UDID=U1; open_app ios')
        self.assertIn("adb -s S1 shell monkey -p com.demo.app -c android.intent.category.LAUNCHER 1", p.called())
        self.assertIn("xcrun simctl launch U1 com.demo.app", p.called())

    def run_target(self, p: Project, flags: str, state: str, installed: bool):
        """run_android with the machine parts stubbed: which path it takes and what it launches."""
        stubs = ("ensure() { return 0; }; start_backend() { return 0; }; free_port() { return 0; }; wait_metro() { return 0; }; "
                 "select_android_target() { A_SERIAL=S1; A_ID=S1; A_DEVNAME=Pixel; A_KIND=phone; }; fingerprint() { echo files:now; }; "
                 f"android_installed() {{ return {0 if installed else 1}; }}; launch() {{ echo \"LAUNCH $*\"; return 1; }}; ")
        return self.lib(p, f'{stubs}init_state; {state or ":; "}{flags or ":"}; run_android; echo rc=$?', stdin="y\n")

    def test_run_android_takes_the_fast_path_when_nothing_native_changed(self):
        p = Project(self, pnpm_monorepo, LOCAL_DEV)
        p.shim("adb")
        r = self.run_target(p, "", "state_set android S1 files:now 1.0; ", True)
        self.assertIn("no native build: installed, and the native inputs are the same", r.stdout)
        self.assertIn("start --dev-client", r.stdout)
        self.assertNotIn("run:android", r.stdout)
        self.assertIn("adb -s S1 reverse tcp:8081 tcp:8081", p.called())

    def test_run_android_builds_when_something_changed_or_is_missing(self):
        for state, installed, why in (("state_set android S1 files:old 1.0; ", True, "native inputs changed"), ("", True, "no record"),
                                      ("state_set android S1 files:now 1.0; ", False, "not installed")):
            with self.subTest(why=why):
                p = Project(self, pnpm_monorepo, LOCAL_DEV)
                p.shim("adb")
                r = self.run_target(p, "", state, installed)
                self.assertIn(why, r.stdout)
                self.assertIn("run:android --device Pixel", r.stdout)
                self.assertFalse(re.search(r"android\|S1\|files:now", (p.dir / ".local-dev/state").read_text() if (p.dir / ".local-dev/state").exists() else ""),
                                 "a build that did not finish leaves no fingerprint")

    def test_flags_force_the_path(self):
        p = Project(self, pnpm_monorepo, LOCAL_DEV)
        p.shim("adb")
        p.shim("xcrun")
        r = self.run_target(p, "REBUILD=1", "state_set android S1 files:now 1.0; ", True)
        self.assertIn("forced by --rebuild", r.stdout)
        self.assertIn("run:android", r.stdout)
        r = self.run_target(p, "NOBUILD=1", "state_set android S1 files:old 1.0; ", True)
        self.assertIn("forced by --no-build", r.stdout)
        self.assertNotIn("run:android", r.stdout)
        p2 = Project(self, pnpm_monorepo, LOCAL_DEV)
        p2.shim("adb")
        r = self.run_target(p2, "NOBUILD=1", "", False)
        self.assertIn("rc=1", r.stdout)
        self.assertIn("--no-build forbids building", r.stdout)
        self.assertNotIn("LAUNCH", r.stdout)

    def test_the_two_flags_exclude_each_other(self):
        p = Project(self, pnpm_monorepo, LOCAL_DEV)
        r = p.run("android", "--rebuild", "--no-build")
        self.assertEqual(r.returncode, 2)

    def test_metro_target_starts_only_metro_and_reverses_every_device(self):
        p = Project(self, pnpm_monorepo, LOCAL_DEV)
        p.shim("adb", 'case "$1" in devices) printf "List of devices attached\\nS1\\tdevice usb:1 model:Pixel\\nemulator-5554\\tdevice product:x\\n";; esac')
        stubs = "ensure() { return 0; }; start_backend() { return 0; }; free_port() { return 0; }; launch() { echo \"LAUNCH $*\"; }; "
        r = self.lib(p, f"{stubs}run_metro")
        self.assertIn("__expo start --dev-client", r.stdout)
        for s in ("S1", "emulator-5554"):
            self.assertIn(f"adb -s {s} reverse tcp:8081 tcp:8081", p.called())
            self.assertIn(f"adb -s {s} reverse tcp:3000 tcp:3000", p.called())
        self.assertNotIn("run:android", r.stdout)


class LaunchFailureTest(Lib, unittest.TestCase):
    """A launch that failed must not look like a Ctrl+C stop."""

    INSTALL_FAILED = (
        "Error: adb: failed to install /x/app-debug.apk: Failure [INSTALL_FAILED_INSUFFICIENT_STORAGE: Failed to override installation location]\n"
        "Error: /Users/me/Android/sdk/platform-tools/adb -s emulator-5554 install -r -d --user 0 /x/app-debug.apk exited with non-zero code: 1\n")

    def failed(self, rc, log):
        p = Project(self, pnpm_monorepo, LOCAL_DEV)
        (p.dir / "x.log").write_text(log)
        return self.lib(p, f'launch_failed {rc} x.log && echo failed || echo stopped').stdout.strip()

    def test_the_install_failure_from_the_emulator_is_a_failure_even_with_rc_0(self):
        self.assertEqual(self.failed(0, "BUILD SUCCESSFUL in 4m\n" + self.INSTALL_FAILED), "failed")
        self.assertEqual(self.failed(1, self.INSTALL_FAILED), "failed")

    def test_each_marker_counts_in_any_case(self):
        for text in ("INSTALL_FAILED_UPDATE_INCOMPATIBLE", "Error: boom", "ERROR: boom", "exited with non-zero code: 1",
                     "BUILD FAILED in 2s", "CommandError: x"):
            with self.subTest(text=text):
                self.assertEqual(self.failed(0, text + "\n"), "failed")

    def test_ctrl_c_and_a_clean_run_are_normal_stops(self):
        self.assertEqual(self.failed(130, self.INSTALL_FAILED), "stopped")
        self.assertEqual(self.failed(0, "Starting Metro\nLogs for your project will appear below.\n"), "stopped")
        self.assertEqual(self.failed(1, "nothing wrong in here\n"), "stopped")

    def test_a_marker_after_metro_was_ready_with_rc_0_is_still_a_stop(self):
        # the user used the app, a request failed ("Error: ..." in Metro's output), then Ctrl+C ended it with 0
        self.assertEqual(self.failed(0, "Logs for your project will appear below.\nError: Network request failed\n"), "stopped")

    def test_launch_reports_the_failure_and_records_it(self):
        p = Project(self, pnpm_monorepo, LOCAL_DEV)
        script = ('script() { shift; shift; printf "%s" "$FIXTURE" >"$LOG/android.log"; return 0; }; repair() { return 1; }; '
                  'launch android true; echo rc=$?')
        r = self.lib(p, "init_state; " + script, stdin="y\n", env={"FIXTURE": self.INSTALL_FAILED})
        self.assertIn("rc=1", r.stdout)
        self.assertIn("INSTALL_FAILED_INSUFFICIENT_STORAGE", (p.dir / ".local-dev/last-error.txt").read_text())
        self.assertNotIn("stopped", r.stdout)


class AndroidTargetTest(Lib, unittest.TestCase):
    """B: phones, wireless, several devices, the emulator."""

    DEVICES = "List of devices attached\\nS1\\tdevice usb:1 product:a model:Galaxy_S20 device:x\\n"

    def project(self, devices: str = "", avds: str = "", extra_shims: bool = True) -> Project:
        p = Project(self, pnpm_monorepo, LOCAL_DEV)
        p.shim("adb", f'case "$1" in devices) printf "{devices}";; esac\n'
                      'case "$*" in *"emu avd name"*) echo Pixel_7_API_34;; *getprop*) echo 1;; esac')
        p.shim("emulator", f'case "$1" in -list-avds) printf "{avds}";; *) exec sleep 5;; esac')
        p.shim("uname", 'case "$1" in -m) echo x86_64;; *) echo Darwin;; esac')
        return p

    def select(self, p, body="", stdin="", flags=""):
        stubs = "ensure() { return 0; }; "
        return self.lib(p, f'{stubs}{flags or ":"}; select_android_target; echo "rc=$? kind=$A_KIND serial=$A_SERIAL id=$A_ID name=$A_DEVNAME"; {body}', stdin=stdin)

    def test_the_plan_table(self):
        p = self.project()
        rows = [("auto", 1, 0, "phone"), ("auto", 2, 1, "phone"), ("auto", 0, 1, "emulator-running"), ("auto", 0, 0, "offer-emulator"),
                ("phone", 0, 1, "no-phone"), ("phone", 1, 1, "phone"), ("emulator", 1, 0, "emulator-start"), ("emulator", 1, 1, "emulator-running")]
        for target, phones, emus, want in rows:
            with self.subTest(target=target, phones=phones, emus=emus):
                self.assertEqual(self.lib(p, f"android_plan {target} {phones} {emus}").stdout.strip(), want)

    def test_one_phone_is_used_and_no_emulator_is_started(self):
        p = self.project(self.DEVICES, "Pixel_7_API_34\\n")
        r = self.select(p)
        self.assertIn("rc=0 kind=phone serial=S1 id=S1 name=Galaxy_S20", r.stdout)
        self.assertFalse([c for c in p.called() if c.startswith("emulator -avd")])

    def test_several_phones_ask_and_the_choice_is_remembered(self):
        devices = self.DEVICES + "R2\\tdevice usb:2 model:Pixel_8\\n"
        p = self.project(devices)
        r = self.select(p, stdin="2\ny\n")
        self.assertIn("serial=R2", r.stdout)
        self.assertEqual((p.dir / ".local-dev/android-device").read_text().strip(), "R2")
        r = self.select(p)  # no terminal: the remembered one is used without asking
        self.assertIn("rc=0 kind=phone serial=R2", r.stdout)
        r = self.select(p, flags="DEVICE=S1")  # --device wins
        self.assertIn("serial=S1", r.stdout)
        r = self.select(p, flags="DEVICE=Pixel_8")  # by model
        self.assertIn("serial=R2", r.stdout)
        r = self.select(p, flags="DEVICE=nope")
        self.assertIn("rc=1", r.stdout)
        self.assertIn('no connected phone is "nope"', r.stdout)

    def test_wireless_phones_are_phones(self):
        p = self.project("List of devices attached\\n192.168.1.5:41000\\tdevice product:a model:SM_G980F\\n")
        self.assertIn("kind=phone serial=192.168.1.5:41000", self.select(p).stdout)

    def test_no_phone_offers_the_emulator_and_a_no_keeps_waiting(self):
        p = self.project("List of devices attached\\n")
        r = self.select(p, stdin="n\n")
        self.assertIn("No phone in sight", r.stdout)
        self.assertIn("rc=1", r.stdout)  # no terminal left to retry
        self.assertFalse([c for c in p.called() if c.startswith("emulator")])
        self.assertIn("run-local.sh pair", r.stdout)

    def test_an_unauthorized_phone_is_explained(self):
        p = self.project("List of devices attached\\nS1\\tunauthorized usb:1\\n")
        self.assertIn("Allow USB debugging", self.select(p).stdout)

    def test_a_running_emulator_is_used_when_there_is_no_phone(self):
        p = self.project("List of devices attached\\nemulator-5554\\tdevice product:sdk model:sdk_gphone64\\n")
        r = self.select(p)
        self.assertIn("rc=0 kind=emulator serial=emulator-5554 id=avd:Pixel_7_API_34 name=Pixel_7_API_34", r.stdout)

    def test_the_emulator_flag_beats_a_connected_phone_and_leaves_it_alone(self):
        devices = self.DEVICES + "emulator-5554\\tdevice product:sdk\\n"
        p = self.project(devices)
        r = self.select(p, flags="EMULATOR_FLAG=1; load_config")
        self.assertIn("kind=emulator serial=emulator-5554", r.stdout)
        self.assertFalse([c for c in p.called() if " emu kill" in c])

    def test_a_phone_target_asks_before_shutting_a_running_emulator_down(self):
        devices = self.DEVICES + "emulator-5554\\tdevice product:sdk\\n"
        p = self.project(devices)
        self.select(p, stdin="n\n")
        self.assertFalse([c for c in p.called() if " emu kill" in c])
        self.select(p, stdin="y\n")
        self.assertIn("adb -s emulator-5554 emu kill", p.called())

    def test_an_existing_avd_boots_with_no_snapshot_save_and_is_remembered(self):
        p = self.project("List of devices attached\\nemulator-5554\\tdevice product:sdk\\n", "Pixel_7_API_34\\n")
        # not running yet: the adb shim lists it only after the emulator is started, so show it from the start and
        # check the command line the emulator got
        p2 = self.project("List of devices attached\\n", "Pixel_7_API_34\\n")
        p2.shim("adb", 'case "$1" in devices) if grep -q "emulator -avd" "' + str(p2.calls) + '"; then printf "List of devices attached\\nemulator-5554\\tdevice product:sdk\\n"; else printf "List of devices attached\\n"; fi;; esac\n'
                       'case "$*" in *getprop*) echo 1;; *"emu avd name"*) echo Pixel_7_API_34;; esac')
        r = self.select(p2, stdin="\ny\n", flags="EMULATOR_FLAG=1; load_config")
        self.assertIn("rc=0 kind=emulator serial=emulator-5554 id=avd:Pixel_7_API_34", r.stdout)
        self.assertIn("emulator -avd Pixel_7_API_34 -no-snapshot-save", p2.called())
        self.assertEqual((p2.dir / ".local-dev/avd").read_text().strip(), "Pixel_7_API_34")
        self.assertTrue((p2.dir / ".local-dev/logs").is_dir())

    def test_several_avds_ask_and_the_device_flag_names_one(self):
        p = self.project("List of devices attached\\n", "Pixel_7_API_34\\nTablet_API_33\\n")
        p.shim("adb", 'case "$1" in devices) if grep -q "emulator -avd" "' + str(p.calls) + '"; then printf "List of devices attached\\nemulator-5554\\tdevice product:sdk\\n"; else printf "List of devices attached\\n"; fi;; esac\n'
                      'case "$*" in *getprop*) echo 1;; esac')
        self.select(p, stdin="2\ny\n", flags="EMULATOR_FLAG=1; load_config")
        self.assertIn("emulator -avd Tablet_API_33 -no-snapshot-save", p.called())
        # --device names an AVD that is not a phone: it means the emulator, with a phone attached
        p3 = self.project(self.DEVICES, "Pixel_7_API_34\\nTablet_API_33\\n")
        p3.shim("adb", 'case "$1" in devices) if grep -q "emulator -avd" "' + str(p3.calls) + '"; then printf "List of devices attached\\nemulator-5554\\tdevice product:sdk\\n"; else printf "List of devices attached\\nS1\\tdevice usb:1 model:Galaxy_S20\\n"; fi;; esac\n'
                       'case "$*" in *getprop*) echo 1;; esac')
        self.select(p3, stdin="y\n", flags="DEVICE=Tablet_API_33")
        self.assertIn("emulator -avd Tablet_API_33 -no-snapshot-save", p3.called())

    def test_avd_creation_shows_the_size_and_downloads_only_after_a_yes(self):
        p = self.project("List of devices attached\\n", "")
        p.shim("sdkmanager", "")
        p.shim("avdmanager", "")
        r = self.select(p, stdin="n\n", flags="EMULATOR_FLAG=1; load_config")
        self.assertIn("1–2 GB", r.stdout)
        self.assertIn("system-images;android-34;google_apis_playstore;x86_64", r.stdout)
        self.assertFalse([c for c in p.called() if c.startswith(("sdkmanager --sdk_root", "avdmanager"))])
        self.assertIn("rc=1", r.stdout)

    def test_avd_creation_after_a_yes_installs_the_image_and_creates_the_device(self):
        p = self.project("List of devices attached\\n", "")
        p.shim("sdkmanager", "")
        p.shim("avdmanager", "")
        p.shim("adb", 'case "$1" in devices) if grep -q "emulator -avd" "' + str(p.calls) + '"; then printf "List of devices attached\\nemulator-5554\\tdevice product:sdk\\n"; else printf "List of devices attached\\n"; fi;; esac\n'
                      'case "$*" in *getprop*) echo 1;; esac')
        r = self.select(p, stdin="y\ny\n", flags="EMULATOR_FLAG=1; load_config")
        calls = p.called()
        self.assertTrue(any(c.startswith("sdkmanager --sdk_root=") and c.endswith("--install system-images;android-34;google_apis_playstore;x86_64") for c in calls), calls)
        self.assertIn('avdmanager create avd -n RunLocal_API_34 -k system-images;android-34;google_apis_playstore;x86_64 -d pixel', calls)
        self.assertIn("emulator -avd RunLocal_API_34 -no-snapshot-save", calls)
        self.assertIn("kind=emulator", r.stdout)

    def test_the_image_matches_the_machine_and_the_project(self):
        p = self.project()
        p.shim("uname", 'case "$1" in -m) echo arm64;; *) echo Darwin;; esac')
        self.assertEqual(self.lib(p, "avd_package").stdout.strip(), "system-images;android-34;google_apis_playstore;arm64-v8a")
        p = self.project()
        write(p.dir, "apps/mobile/android/build.gradle", "buildscript { ext { compileSdkVersion = 35 } }")
        self.assertEqual(self.lib(p, "avd_package").stdout.strip(), "system-images;android-35;google_apis_playstore;x86_64")
        self.assertEqual(self.lib(p, 'avd_create_cmd Pix "pkg;x"').stdout, 'echo no | avdmanager create avd -n "Pix" -k "pkg;x" -d pixel')

    def test_emulator_binary_is_found_under_android_home_when_not_on_path(self):
        p = Project(self, pnpm_monorepo, LOCAL_DEV)
        sdk = p.dir.parent / "sdk"
        write(sdk, "emulator/emulator", "#!/bin/bash\n")
        (sdk / "emulator/emulator").chmod(0o755)
        self.assertEqual(self.lib(p, "emulator_bin", env={"ANDROID_HOME": str(sdk)}).stdout.strip(), f"{sdk}/emulator/emulator")

    def test_stop_asks_before_shutting_an_emulator_down(self):
        p = self.project("List of devices attached\\nemulator-5554\\tdevice product:sdk\\n")
        self.lib(p, "stop_backend", stdin="n\n")
        self.assertFalse([c for c in p.called() if " emu kill" in c])
        self.lib(p, "stop_backend", stdin="n\ny\n")  # the API is not up: the questions are containers, then the emulator
        self.assertIn("adb -s emulator-5554 emu kill", p.called())

    def test_pair_asks_for_both_addresses_and_stores_nothing(self):
        p = self.project()
        r = self.lib(p, "pair_android", stdin="192.168.1.5:37000\n192.168.1.5:41000\n")
        self.assertIn("adb pair 192.168.1.5:37000", p.called())
        self.assertIn("adb connect 192.168.1.5:41000", p.called())
        self.assertNotIn("37000", "".join(f.read_text() for f in p.dir.rglob("*") if f.is_file() and ".git" not in f.parts and f.suffix != ".sh"))
        self.assertFalse((p.dir / ".local-dev").exists())
        p2 = self.project()
        r = self.lib(p2, "pair_android; echo rc=$?", stdin="$(rm -rf x)\n")
        self.assertIn("that is not an address", r.stdout)
        self.assertFalse([c for c in p2.called() if c.startswith("adb pair")])


class StorageRepairTest(Lib, unittest.TestCase):
    """INSTALL_FAILED_INSUFFICIENT_STORAGE: four ways out, each only with its own yes."""

    LOG = ("Error: adb: failed to install /x/app-debug.apk: Failure [INSTALL_FAILED_INSUFFICIENT_STORAGE: "
           "Failed to override installation location]\n")

    def project(self, avds="Pixel_7_API_34\n"):
        p = Project(self, pnpm_monorepo, LOCAL_DEV)
        (p.dir / ".gitignore").write_text(".local-dev/\n")
        (p.dir / ".local-dev/logs").mkdir(parents=True)
        (p.dir / "x.log").write_text(self.LOG)
        p.shim("adb", 'case "$1" in devices) if grep -q "wipe-data" "' + str(p.calls) + '"; then printf "List of devices attached\\nemulator-5554\\tdevice product:sdk\\n"; else printf "List of devices attached\\n"; fi;; esac\n'
                      'case "$*" in *getprop*) echo 1;; esac')
        p.shim("emulator", f'case "$1" in -list-avds) printf "{avds}";; *) exec sleep 5;; esac')
        p.shim("sdkmanager", 'case "$*" in *list_installed*) echo "system-images;android-34;google_apis_playstore;x86_64";; esac')
        p.shim("avdmanager", 'mkdir -p "$HOME/.android/avd/RunLocal_API_34.avd"; printf "hw.ramSize=2048\\ndisk.dataPartition.size=2G\\n" >"$HOME/.android/avd/RunLocal_API_34.avd/config.ini"')
        p.shim("uname", 'case "$1" in -m) echo x86_64;; *) echo Darwin;; esac')
        return p

    def repair(self, p, stdin="", pre="A_KIND=emulator; A_SERIAL=emulator-5554; AVD_NAME=Pixel_7_API_34"):
        return self.lib(p, f'{pre}; repair x.log; echo "rc=$? blocked=$BLOCKED"', stdin=stdin)

    def test_the_table_has_the_entry(self):
        self.assertIn("'INSTALL_FAILED_INSUFFICIENT_STORAGE => insufficient_storage'", SCRIPT.read_text())

    def test_with_yes_it_stops_listing_the_options_and_picks_none(self):
        p = self.project()
        r = self.repair(p, pre="YES=1; A_KIND=emulator; A_SERIAL=emulator-5554; AVD_NAME=Pixel_7_API_34")
        self.assertIn("rc=1 blocked=1", r.stdout)
        self.assertIn("none is picked for you", r.stdout)
        self.assertIn("--new-avd", r.stdout)
        self.assertIn("-wipe-data", r.stdout)
        self.assertEqual([c for c in p.called() if c.startswith(("adb -s", "avdmanager", "emulator -avd", "sdkmanager --sdk"))], [])

    def test_a_yes_to_uninstall_removes_the_app_and_retries(self):
        p = self.project()
        r = self.repair(p, "y\n")
        self.assertIn("rc=0 blocked=0", r.stdout)
        self.assertIn("adb -s emulator-5554 uninstall com.demo.app", p.called())
        self.assertFalse([c for c in p.called() if c.startswith("avdmanager")])

    def test_one_plain_sentence_says_why(self):
        p = self.project()
        r = self.repair(p, "n\nn\nn\n")
        self.assertIn("not enough free storage on emulator-5554", r.stdout)
        self.assertIn("pm trim-caches", r.stdout)  # only mentioned
        self.assertFalse([c for c in p.called() if "trim-caches" in c])
        self.assertIn("rc=1", r.stdout)

    def test_a_phone_is_only_offered_the_uninstall(self):
        p = self.project()
        r = self.repair(p, "n\ny\ny\n", pre="A_KIND=phone; A_SERIAL=S1")
        self.assertIn("rc=1", r.stdout)
        self.assertFalse([c for c in p.called() if c.startswith(("avdmanager", "emulator"))])
        self.assertNotIn("-wipe-data?", r.stdout)

    def test_a_new_avd_with_a_bigger_data_partition_reuses_the_installed_image(self):
        p = self.project()
        r = self.repair(p, "n\ny\ny\n")
        self.assertFalse([c for c in p.called() if c.startswith("sdkmanager --sdk_root")], "no download")
        self.assertIn("(the image is already installed: no download)", SCRIPT.read_text())
        cfg = (p.home / ".android/avd/RunLocal_API_34.avd/config.ini").read_text()
        self.assertEqual(cfg.count("disk.dataPartition.size"), 1)
        self.assertIn("disk.dataPartition.size=8G", cfg)
        self.assertEqual((p.dir / ".local-dev/avd").read_text().strip(), "RunLocal_API_34")
        self.assertIn("created RunLocal_API_34", r.stdout)
        self.assertIn("rc=1", r.stdout)
        self.assertFalse([c for c in p.called() if "-wipe-data" in c])

    def test_wipe_data_needs_its_own_yes_that_names_the_avd(self):
        p = self.project()
        r = self.repair(p, "n\nn\nn\n")
        self.assertIn('Cold boot $AVD_NAME with -wipe-data? This ERASES ALL its apps and data.', SCRIPT.read_text())  # names the AVD, warns
        self.assertFalse([c for c in p.called() if "-wipe-data" in c or "emu kill" in c])
        p = self.project()
        r = self.repair(p, "n\nn\ny\n")
        self.assertIn("adb -s emulator-5554 emu kill", p.called())
        self.assertIn("emulator -avd Pixel_7_API_34 -no-snapshot-save -wipe-data", p.called())
        self.assertIn("rc=0", r.stdout)
        self.assertEqual(self.lib(p, 'echo "[$EMU_EXTRA]"').stdout.strip(), "[]", "the flag is not left on for the next boot")

    def test_wipe_data_is_never_the_default_or_asked_with_yes(self):
        p = self.project()
        text = SCRIPT.read_text()
        d = text[text.index("repair_insufficient_storage()"):]
        d = d[:d.index("repair_no_acceleration()")]
        self.assertLess(d.index('if [ "$YES" = 1 ]'), d.index("-wipe-data"), "--yes returns before any option is reached")


class NewAvdTest(Lib, unittest.TestCase):
    LOG = StorageRepairTest.LOG

    def project(self, avds=""):
        p = StorageRepairTest.project(self, avds)
        p.shim("adb", 'case "$1" in devices) if grep -q "emulator -avd" "' + str(p.calls) + '"; then printf "List of devices attached\\nemulator-5554\\tdevice product:sdk\\n"; else printf "List of devices attached\\n"; fi;; esac\n'
                      'case "$*" in *getprop*) echo 1;; *"avd name"*) echo X;; esac')
        return p

    def select(self, p, stdin, flags):
        return self.lib(p, f'ensure() {{ return 0; }}; {flags}; select_android_target; echo "rc=$? kind=$A_KIND id=$A_ID"', stdin=stdin)

    def test_the_flag_creates_a_new_avd_even_when_others_exist(self):
        p = self.project("Pixel_7_API_34\n")
        r = self.select(p, "y\n", "NEWAVD_FLAG=1; EMULATOR_FLAG=1; load_config")
        self.assertIn("rc=0 kind=emulator id=avd:RunLocal_API_34", r.stdout)
        self.assertIn("emulator -avd RunLocal_API_34 -no-snapshot-save", p.called())
        self.assertIn("disk.dataPartition.size=8G", (p.home / ".android/avd/RunLocal_API_34.avd/config.ini").read_text())
        self.assertFalse([c for c in p.called() if c.startswith("sdkmanager --sdk_root")], "the image was installed: no download")

    def test_a_second_new_avd_gets_another_name(self):
        p = self.project("RunLocal_API_34\n")
        r = self.select(p, "y\n", "NEWAVD_FLAG=1; EMULATOR_FLAG=1; load_config")
        self.assertTrue(any("RunLocal_API_34_2" in c for c in p.called()) or "RunLocal_API_34_2" in r.stdout, r.stdout)

    def test_the_menu_offers_a_new_emulator_even_when_others_exist(self):
        p = self.project("Pixel_7_API_34\n")
        r = self.select(p, "n\ny\n", "EMULATOR_FLAG=1; load_config")
        self.assertIn("n) a NEW emulator (8 GB of storage)", r.stdout)
        self.assertIn("kind=emulator id=avd:RunLocal_API_34", r.stdout)
        p = self.project("Pixel_7_API_34\n")
        r = self.select(p, "1\ny\n", "EMULATOR_FLAG=1; load_config")
        self.assertIn("id=avd:Pixel_7_API_34", r.stdout)

    def test_with_yes_an_existing_emulator_is_used_and_none_is_created(self):
        p = self.project("Pixel_7_API_34\n")
        r = self.select(p, "", "YES=1; EMULATOR_FLAG=1; load_config")
        self.assertIn("id=avd:Pixel_7_API_34", r.stdout)
        self.assertFalse([c for c in p.called() if c.startswith("avdmanager")])

    def test_a_running_emulator_is_shut_down_for_a_new_one_only_with_a_yes(self):
        p = self.project("Pixel_7_API_34\n")
        p.shim("adb", 'case "$1" in devices) printf "List of devices attached\\nemulator-5554\\tdevice product:sdk\\n";; esac\ncase "$*" in *"avd name"*) echo Pixel_7_API_34;; esac')
        r = self.select(p, "n\n", "NEWAVD_FLAG=1; EMULATOR_FLAG=1; load_config")
        self.assertIn("rc=1", r.stdout)
        self.assertFalse([c for c in p.called() if "emu kill" in c])

    def test_the_flag_parses(self):
        p = Project(self, pnpm_monorepo, LOCAL_DEV)
        self.assertIn("--new-avd", p.run("android", "--help").stdout)


class RepairTableTest(Lib, unittest.TestCase):
    ACTIONS = "insufficient_storage uninstall_app free_metro_port gradle_memory pod_reinstall google_file free_emulator_port avd_lock no_acceleration"

    def which(self, log: str, setup: str = ""):
        p = Project(self, pnpm_monorepo, LOCAL_DEV)
        (p.dir / "x.log").write_text(log)
        stubs = "".join(f"repair_{a}() {{ echo {a}; return 0; }}; " for a in self.ACTIONS.split())
        r = self.lib(p, f'{stubs}{setup or ":"}; repair x.log; echo "rc=$?"')
        return r.stdout.split()

    def test_each_known_failure_runs_its_repair(self):
        cases = {"INSTALL_FAILED_UPDATE_INCOMPATIBLE: x": "uninstall_app", "listen EADDRINUSE :::8081": "free_metro_port",
                 "java.lang.OutOfMemoryError: Java heap space": "gradle_memory", "Unable to find a specification for 'X'": "pod_reinstall",
                 "File google-services.json is missing": "google_file", "port 5554 is already in use": "free_emulator_port",
                 "Running multiple emulators with the same AVD": "avd_lock", "emulator: ERROR: x86 emulation requires HVF": "no_acceleration"}
        for log, action in cases.items():
            with self.subTest(action=action):
                self.assertEqual(self.which(log, "ANDROID_PKG=a.b; A_SERIAL=S1"), [action, "rc=0"])

    def test_an_unknown_failure_stays_unrepaired(self):
        self.assertEqual(self.which("something nobody has seen"), ["rc=1"])

    def test_an_action_that_does_not_apply_lets_the_next_line_try(self):
        p = Project(self, pnpm_monorepo, LOCAL_DEV)
        (p.dir / "x.log").write_text("INSTALL_FAILED_UPDATE_INCOMPATIBLE and then EADDRINUSE")
        stubs = "free_metro_port() { echo metro; }; "
        r = self.lib(p, f'{stubs}ANDROID_PKG=; A_SERIAL=; repair_free_metro_port() {{ echo metro; return 0; }}; repair x.log; echo rc=$?')
        self.assertEqual(r.stdout.split(), ["metro", "rc=0"], "uninstalling needs a package and a phone; without them the port is next")

    def test_the_table_is_data_one_line_per_failure(self):
        text = SCRIPT.read_text()
        block = re.search(r"(?s)REPAIRS=\((.*?)\n\)", text).group(1)
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        self.assertGreaterEqual(len(lines), 8)
        for l in lines:
            m = re.fullmatch(r"'(.+) => (\w+)'", l)
            self.assertTrue(m, l)
            self.assertIn(f"repair_{m.group(2)}() ", text, f"{m.group(2)} has no function")

    def test_stale_avd_locks_are_deleted_only_with_a_yes(self):
        p = Project(self, pnpm_monorepo, LOCAL_DEV)
        lock = p.home / ".android/avd/Pix.avd/hardware-qemu.ini.lock"
        lock.parent.mkdir(parents=True)
        lock.write_text("")
        self.lib(p, "AVD_NAME=Pix; repair_avd_lock", stdin="n\n")
        self.assertTrue(lock.exists())
        self.lib(p, "AVD_NAME=Pix; repair_avd_lock", stdin="y\n")
        self.assertFalse(lock.exists())

    def test_a_busy_emulator_port_asks_before_closing_anything(self):
        p = Project(self, pnpm_monorepo, LOCAL_DEV)
        proc = subprocess.Popen(["sleep", "60"])
        self.addCleanup(lambda: (proc.kill(), proc.wait()))
        p.shim("lsof", f"echo {proc.pid}")
        p.shim("ps", "echo qemu")
        self.lib(p, "repair_free_emulator_port", stdin="n\n")
        self.assertIsNone(proc.poll())
        self.lib(p, "repair_free_emulator_port", stdin="y\n")
        proc.wait(timeout=10)


class ServicesAndSeedTest(Lib, unittest.TestCase):
    def project(self, extra: str = "", compose: str | None = None):
        def build(d):
            pnpm_monorepo(d)
            if compose:
                write(d, "docker-compose.yml", compose)
        return Project(self, build, LOCAL_DEV.replace('db_service = "postgres"', 'db_service = "postgres"\n' + extra))

    def test_services_are_read_from_the_block_or_detected(self):
        p = self.project('services = ["redis", "mailpit"]')
        self.assertEqual(self.lib(p, 'echo "$SERVICES"').stdout.strip(), "redis mailpit")
        p = self.project("", "services:\n  postgres:\n    image: postgres:16\n  redis:\n    image: redis:7\n")
        self.assertEqual(self.lib(p, 'echo "$SERVICES"').stdout.strip(), "redis")
        p = self.project("services = []", "services:\n  postgres:\n    image: postgres:16\n  redis:\n    image: redis:7\n")
        self.assertEqual(self.lib(p, 'echo "[$SERVICES]"').stdout.strip(), "[]", "an explicit empty list means none")

    def test_the_database_and_its_services_start_together_and_nothing_else(self):
        p = self.project('services = ["redis"]')
        p.shim("docker")
        self.lib(p, "setup_env; api_up() { return 0; }; API_MIGRATE=; start_backend", stdin="y\n")
        self.assertIn("docker compose up -d --wait postgres redis", p.called())

    def test_stop_stops_them_all_after_one_question(self):
        p = self.project('services = ["redis"]')
        p.shim("docker")
        self.lib(p, "stop_backend", stdin="n\n")
        self.assertFalse([c for c in p.called() if c.startswith("docker")])
        self.lib(p, "stop_backend", stdin="y\n")
        self.assertIn("docker compose stop postgres redis", p.called())

    def test_services_need_a_compose_file(self):
        p = Project(self, pnpm_monorepo, LOCAL_DEV.replace('db_service = "postgres"', 'services = ["redis"]'))
        (p.dir / "docker-compose.yml").unlink()
        p.shim("uname", "echo Linux")
        r = p.run("doctor", "--check")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no docker compose file", r.stdout)


class VersionsTest(Lib, unittest.TestCase):
    def nvm_home(self, p: Project, works: bool):
        nvm = p.home / ".nvm/nvm.sh"
        nvm.parent.mkdir(parents=True)
        nvm.write_text('nvm() { [ "$1" = use ] || return 0; ' + ('node() { echo v22.4.0; }; ' if works else '') + f'return {0 if works else 1}; }}\n')

    def test_a_matching_node_from_nvm_is_used_for_this_run_only(self):
        p = Project(self, pnpm_monorepo, LOCAL_DEV + 'node = "22"\n')
        p.shim("node", "echo v16.0.0")
        self.nvm_home(p, True)
        r = self.lib(p, 'setup_env; echo "major=$(node_major)"')
        self.assertIn("Node 22 from nvm, for this run only", r.stdout)
        self.assertIn("major=22", r.stdout)
        p2 = Project(self, pnpm_monorepo, LOCAL_DEV + 'node = "22"\n')
        p2.shim("node", "echo v16.0.0")
        r = self.lib(p2, 'setup_env; echo "major=$(node_major)"')
        self.assertIn("major=16", r.stdout, "without nvm nothing is switched")

    def test_an_old_node_with_nvm_offers_nvm_install_not_brew(self):
        p = Project(self, pnpm_monorepo, LOCAL_DEV + 'node = "22"\n')
        p.shim("node", "echo v16.0.0")
        self.nvm_home(p, False)
        r = self.lib(p, "setup_env; PLAN_D=(); PLAN_C=(); check_base; printf '%s\\n' \"${PLAN_C[@]}\"")
        self.assertIn("Node 22 (through nvm; your default Node is not changed)", r.stdout)
        self.assertIn('nvm install 22', r.stdout)
        self.assertNotIn("brew install node", r.stdout)

    def test_without_nvm_brew_is_offered_and_only_after_a_yes(self):
        p = Project(self, pnpm_monorepo, LOCAL_DEV + 'node = "22"\n')
        p.shim("brew")
        p.shim("uname", "echo Darwin")
        r = p.run("doctor", "--no-install")
        self.assertIn("Node 22", r.stdout)
        self.assertFalse([c for c in p.called() if c.startswith("brew install")])

    def test_the_node_version_comes_from_the_project(self):
        def build(d):
            pnpm_monorepo(d)
            write(d, ".nvmrc", "v20.1.0\n")
        p = Project(self, build, LOCAL_DEV)
        self.assertEqual(self.lib(p, "node_min").stdout.strip(), "20")

    def test_the_jdk_comes_from_local_then_the_detection(self):
        p = Project(self, pnpm_monorepo, LOCAL_DEV + 'jdk = 21\n')
        self.assertEqual(self.lib(p, "echo $JDK").stdout.strip(), "21")
        p = Project(self, lambda d: layout(d, mobile_deps={"expo": "~49.0.0", "react-native": "0.72.6"}), PROFILE)
        self.assertEqual(self.lib(p, "echo $JDK").stdout.strip(), "11")


class CommandsTest(Lib, unittest.TestCase):
    def mac(self, build=pnpm_monorepo, profile=LOCAL_DEV):
        p = Project(self, build, profile)
        p.shim("uname", "echo Darwin")
        return p

    def test_every_command_has_help(self):
        p = self.mac()
        for cmd in ("android", "ios", "metro", "backend", "seed", "pair", "doctor", "status", "logs", "clean", "stop", "detect"):
            with self.subTest(cmd=cmd):
                r = p.run(cmd, "--help")
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn(cmd, r.stdout.split("\n")[0])
                self.assertEqual(p.run("help", cmd).stdout, r.stdout)
        r = p.run("--help")
        self.assertIn("Exit codes", r.stdout)
        self.assertEqual(p.called(), [])

    def test_unknown_commands_and_options_are_usage_errors(self):
        p = self.mac()
        self.assertEqual(p.run("bogus").returncode, 2)
        self.assertEqual(p.run("android", "--nope").returncode, 2)

    def test_exit_codes(self):
        p = Project(self, pnpm_monorepo, LOCAL_DEV)
        r = self.lib(p, 'finish 0; echo $?; BLOCKED=1; finish 1; echo $?; BLOCKED=0; DECLINED=1; finish 1; echo $?; DECLINED=0; finish 1; echo $?')
        self.assertEqual(r.stdout.split(), ["0", "3", "4", "1"])
        r = self.lib(p, 'confirm "q?"; echo "$DECLINED"', stdin="n\n")
        self.assertEqual(r.stdout.strip(), "1")
        r = self.lib(p, 'confirm "q?"; echo "$DECLINED"')  # no terminal
        self.assertEqual(r.stdout.strip(), "1")

    def test_doctor_json_says_what_is_missing_and_what_only_a_person_can_fix(self):
        p = self.mac()
        r = p.run("doctor", "--json", env={"JAVA_HOME_BIN": "/nonexistent"})
        data = json.loads(r.stdout)
        self.assertEqual((data["command"], data["exit"], data["ok"], r.returncode), ("doctor", 3, False, 3))
        labels = [m["label"] for m in data["missing"]]
        for item in ("Node 18", "pnpm", "Docker Desktop", "JDK 17", "Android platform-tools (adb)"):
            self.assertIn(item, labels)
        self.assertTrue(all(m["command"] for m in data["missing"]))
        self.assertTrue(any("Xcode is not installed" in b for b in data["blockers"]))
        self.assertTrue(all(set(m) == {"level", "text"} for m in data["messages"]))
        self.assertNotIn("\x1b", r.stdout, "JSON mode prints nothing but the JSON")

    def test_doctor_json_when_everything_is_there(self):
        p = self.mac()
        for name, body in {"node": "echo v22.12.0", "pnpm": "echo 10.0.0", "docker": "", "adb": "", "pod": "",
                           "xcodebuild": '[ "$1" = -version ] && echo "Xcode 26.5"',
                           "xcrun": 'echo "    iPhone 17 Pro (11111111-2222-3333-4444-555555555555) (Shutdown)"'}.items():
            p.shim(name, body)
        java = p.dir.parent / "java_home"
        java.write_text("#!/bin/bash\necho /fake/jdk\n")
        java.chmod(0o755)
        sdk = p.dir.parent / "sdk"
        write(sdk, "licenses/android-sdk-license", "x")
        write(p.dir, "node_modules/.pnpm/x")
        os.utime(p.dir / "pnpm-lock.yaml", (1_700_000_000, 1_700_000_000))
        write(p.dir, "node_modules/.modules.yaml")
        write(p.dir, "apps/api/.env")
        r = p.run("doctor", "--json", env={"JAVA_HOME_BIN": str(java), "ANDROID_HOME": str(sdk)})
        data = json.loads(r.stdout)
        self.assertEqual((data["exit"], data["ok"], data["missing"], data["blockers"]), (0, True, [], []))

    def test_doctor_check_json(self):
        p = self.mac(profile=PROFILE)
        data = json.loads(p.run("doctor", "--check", "--json").stdout)
        self.assertEqual((data["exit"], data["ok"]), (1, False))
        self.assertTrue(any("no [local] block" in m["text"] for m in data["messages"] if m["level"] == "bad"))
        p = self.mac()
        self.assertEqual(json.loads(p.run("doctor", "--check", "--json").stdout)["exit"], 0)

    def test_doctor_json_on_another_system(self):
        p = Project(self, pnpm_monorepo, LOCAL_DEV)
        p.shim("uname", "echo Linux")
        data = json.loads(p.run("doctor", "--json").stdout)
        self.assertEqual((data["exit"], data["ok"]), (0, True))
        self.assertIn("macOS only", data["messages"][0]["text"])

    def test_status_json(self):
        p = self.mac()
        p.shim("lsof", "echo 4242")
        p.shim("ps", "echo /usr/bin/node")
        p.shim("curl", "echo 200")
        p.shim("docker", 'case "$*" in "info") ;; *"ps --status running --services"*) echo postgres;; esac')
        p.shim("adb", 'case "$1" in devices) printf "List of devices attached\\nS1\\tdevice usb:1 model:Galaxy_S20\\nemulator-5554\\tdevice product:sdk\\n";; esac')
        p.shim("xcrun", 'echo "    iPhone 17 Pro (11111111-2222-3333-4444-555555555555) (Booted)"')
        (p.dir / ".local-dev").mkdir()
        (p.dir / ".local-dev/android-device").write_text("S1\n")
        data = json.loads(p.run("status", "--json").stdout)
        self.assertEqual(set(data), {"api", "database", "metro", "android", "ios", "ports", "users"})
        self.assertEqual(data["api"], {"configured": True, "up": True, "port": 3000, "pid": 4242, "process": "node"})
        self.assertEqual(data["database"]["services"], {"postgres": "running"})
        self.assertEqual((data["metro"]["up"], data["metro"]["pid"]), (True, 4242))
        self.assertEqual(data["android"]["chosen"], "S1")
        self.assertEqual([(d["serial"], d["model"], d["kind"]) for d in data["android"]["devices"]],
                         [("S1", "Galaxy_S20", "phone"), ("emulator-5554", "", "emulator")])
        self.assertEqual(data["ios"]["booted"], [{"udid": "11111111-2222-3333-4444-555555555555", "name": "iPhone 17 Pro"}])
        self.assertIn("8081", data["ports"])
        self.assertEqual(data["ports"]["3000"], {"pid": 4242, "process": "node"})

    def test_status_when_nothing_runs_and_in_words(self):
        p = self.mac()
        data = json.loads(p.run("status", "--json").stdout)
        self.assertEqual((data["api"]["up"], data["metro"]["up"], data["ports"]), (False, False, {}))
        out = p.run("status").stdout
        self.assertIn("What is running", out)
        p.shim("lsof", "echo 77")
        p.shim("ps", "echo node")
        self.assertIn("Metro: up · node (pid 77)", p.run("status").stdout)

    def test_logs_newest_first_and_by_step(self):
        p = self.mac()
        self.assertEqual(p.run("logs").returncode, 1)
        logs = p.dir / ".local-dev/logs"
        logs.mkdir(parents=True)
        for i, name in enumerate(["db", "migrate", "android", "api"]):
            f = logs / f"{name}.log"
            f.write_text(f"line from {name}\n\x1b[31mred {name}\x1b[0m\n")
            os.utime(f, (1_700_000_000 + i * 100, 1_700_000_000 + i * 100))
        out = p.run("logs").stdout
        self.assertLess(out.index("api.log"), out.index("android.log"))
        self.assertLess(out.index("android.log"), out.index("migrate.log"))
        self.assertNotIn("db.log", out, "the three newest")
        self.assertNotIn("\x1b", out)
        one = p.run("logs", "db")
        self.assertEqual((one.returncode, "red db" in one.stdout), (0, True))
        missing = p.run("logs", "nope")
        self.assertEqual(missing.returncode, 1)
        self.assertIn("db", missing.stderr)

    def clean_project(self):
        p = self.mac()
        write(p.dir, "apps/mobile/android/.gradle/x.bin", "x" * 2000)
        write(p.dir, "apps/mobile/android/app/build/out.apk", "x" * 3000)
        write(p.dir, "apps/mobile/android/gradlew", "#!/bin/sh\n")
        write(p.dir, "apps/mobile/ios/Pods/P.txt", "x" * 1000)
        write(p.dir, "apps/mobile/ios/App.xcodeproj", "tracked")
        subprocess.run(["git", "add", "-f", "apps/mobile/ios/App.xcodeproj"], cwd=p.dir, check=True)
        write(p.dir, ".local-dev/logs/api.log", "log")
        write(p.dir, ".local-dev/last-error.txt", "err")
        write(p.dir, ".local-dev/ios-device", "keep me")
        outside = p.dir.parent / "outside"
        write(outside, "precious.txt", "do not touch")
        (p.dir / "apps/mobile/ios/build").symlink_to(outside)
        derived = p.home / "Library/Developer/Xcode/DerivedData"
        write(derived, "Mine-abc/info.plist", f"<string>{p.dir.resolve()}/apps/mobile/ios/Mine.xcworkspace</string>")
        write(derived, "Mine-abc/Build/x", "x" * 500)
        write(derived, "Other-def/info.plist", "<string>/Users/someone/else/Other.xcworkspace</string>")
        return p, outside, derived

    def test_clean_lists_with_sizes_and_deletes_nothing_without_a_yes(self):
        p, outside, derived = self.clean_project()
        r = p.run("clean", stdin="n\nn\nn\nn\n")
        self.assertIn("apps/mobile/android/.gradle", r.stdout)
        self.assertRegex(r.stdout, r"\d+(\.\d+)?[KMG]?\s+\./?apps/mobile/android/\.gradle|\d+[BKMG]?\s+apps/mobile/android/\.gradle")
        for rel in ("apps/mobile/android/.gradle/x.bin", "apps/mobile/android/app/build/out.apk", "apps/mobile/ios/Pods/P.txt",
                    ".local-dev/logs/api.log", ".local-dev/last-error.txt"):
            self.assertTrue((p.dir / rel).exists(), rel)
        self.assertTrue((derived / "Mine-abc").exists())
        self.assertEqual(r.returncode, 0)

    def test_clean_deletes_group_by_group_and_only_what_is_safe(self):
        p, outside, derived = self.clean_project()
        r = p.run("clean", "--yes")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse((p.dir / "apps/mobile/android").exists(), "untracked generated android/ goes")
        self.assertFalse((p.dir / "apps/mobile/ios/Pods").exists())
        self.assertTrue((p.dir / "apps/mobile/ios/App.xcodeproj").exists(), "what git tracks stays")
        self.assertTrue((p.dir / "apps/mobile/ios").is_dir())
        self.assertTrue((outside / "precious.txt").exists(), "a symlink out of the project is never followed")
        self.assertFalse((derived / "Mine-abc").exists(), "DerivedData of this project goes")
        self.assertTrue((derived / "Other-def").exists(), "another project's DerivedData stays")
        self.assertFalse((p.dir / ".local-dev/logs/api.log").exists())
        self.assertFalse((p.dir / ".local-dev/last-error.txt").exists())
        self.assertTrue((p.dir / ".local-dev/ios-device").exists(), "remembered choices are not logs")
        self.assertIn("git tracks it", r.stdout)

    def test_clean_asks_per_group(self):
        p, outside, derived = self.clean_project()
        # groups: build caches, DerivedData, generated native folders, logs. Say yes only to the logs.
        r = p.run("clean", stdin="n\nn\nn\ny\n")
        self.assertFalse((p.dir / ".local-dev/logs/api.log").exists())
        self.assertTrue((p.dir / "apps/mobile/android/.gradle").exists())
        self.assertTrue((derived / "Mine-abc").exists())

    def test_clean_in_a_folder_git_does_not_know_never_deletes_native_folders(self):
        p, outside, derived = self.clean_project()
        shutil.rmtree(p.dir / ".git")
        p.run("clean", "--yes")
        self.assertTrue((p.dir / "apps/mobile/android/.gradle").exists(), "it cannot tell what is tracked: it keeps it")




class LocalShapeTest(unittest.TestCase):
    """Every key the profile template documents for [local] is declared in the doctor's LOCAL_SHAPE
    (and the script reads it), and the doctor refuses a value of the wrong kind."""

    def declared(self):
        import ast
        tree = ast.parse((ROOT / "template/.keelokit/bin/doctor.py").read_text())
        for node in tree.body:
            if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "LOCAL_SHAPE":
                return ast.literal_eval(node.value)
        self.fail("LOCAL_SHAPE not found")

    def test_documented_keys_and_shapes_agree(self):
        text = (ROOT / "template/.keelokit/profile.toml.jinja").read_text()
        documented = set(re.findall(r"(?m)^#   (\w+)\s+=", text))
        self.assertEqual(documented, set(self.declared()))
        script = SCRIPT.read_text()
        for key in documented:
            self.assertRegex(script, rf"(cfg(_list)?|toml_get \"\$PROFILE\" local) {key}\b", f"the script never reads [local] {key}")

    def test_the_doctor_refuses_the_wrong_kind_of_value(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d)
        (d / ".keelokit/bin").mkdir(parents=True)
        shutil.copy(ROOT / "template/.keelokit/bin/doctor.py", d / ".keelokit/bin/doctor.py")
        (d / ".keelokit/profile.toml").write_text('kind = "mobile-app"\ntraits = ["mobile"]\n\n[local]\nservices = "redis"\napi_port = "3000"\njdk = 17\nnode = "22"\n')
        subprocess.run(["git", "init", "-q"], cwd=d, check=True)
        r = subprocess.run(["python3", ".keelokit/bin/doctor.py", "--ci"], cwd=d, capture_output=True, text=True)
        self.assertIn(".keelokit/profile.toml [local]: 'services' must be a list of text", r.stdout)
        self.assertIn("'api_port' must be a whole number", r.stdout)
        self.assertNotIn("'jdk'", r.stdout)
        self.assertNotIn("'node'", r.stdout)


class NeverWaitsTest(Lib, unittest.TestCase):
    """--yes never blocks on a menu, and with no terminal nothing blocks either: it gives up (exit 4)."""

    SIMS = ("-- iOS 26.0 --\n    iPhone 17 Pro (AAAAAAAA-0000-0000-0000-000000000001) (Shutdown)\n"
            "    iPhone 17 (BBBBBBBB-0000-0000-0000-000000000002) (Booted)\n"
            "    iPhone Air (CCCCCCCC-0000-0000-0000-000000000003) (Shutdown)\n")

    def project(self, sims=None):
        p = Project(self, pnpm_monorepo, LOCAL_DEV)
        self.xcrun(p, sims or self.SIMS)
        (p.dir / ".gitignore").write_text(".local-dev/\n")
        (p.dir / ".local-dev/logs").mkdir(parents=True)
        return p

    def xcrun(self, p, sims):
        (p.dir.parent / "sims.txt").write_text(sims)
        booted = "\n".join(l for l in sims.splitlines() if "(Booted)" in l)
        (p.dir.parent / "booted.txt").write_text(booted + "\n" if booted else "")
        p.shim("xcrun", f'case "$*" in *"list devices booted"*) cat "{p.dir.parent}/booted.txt";; *"list devices"*) cat "{p.dir.parent}/sims.txt";; esac')

    def held_open(self, p, body, env=None, timeout=60):
        """Runs `body` with stdin an open pipe nobody writes to; returns (stdout, seconds)."""
        import time
        e = {"PATH": str(p.bin), "HOME": str(p.home), "RUN_LOCAL_LIB": "1", "RUN_LOCAL_ASK_TIMEOUT": "1", **(env or {})}
        proc = subprocess.Popen(["bash", "-c", f'cd "{p.dir}"; . .keelokit/bin/run-local.sh; load_config; {body}'], env=e,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        t = time.time()
        try:
            out, err = proc.communicate(timeout=timeout)
        finally:
            proc.kill()
        return out, err, time.time() - t

    def test_yes_takes_the_booted_simulator_says_so_and_remembers(self):
        p = self.project()
        out, err, secs = self.held_open(p, 'YES=1; pick_ios; echo "rc=$? udid=$I_UDID name=$I_NAME"')
        self.assertIn("rc=0 udid=BBBBBBBB-0000-0000-0000-000000000002 name=iPhone 17", out)
        self.assertIn("--yes took the simulator iPhone 17", out)
        self.assertIn("--device", out)
        self.assertLess(secs, 20)
        self.assertEqual((p.dir / ".local-dev/ios-device").read_text().strip(), "BBBBBBBB-0000-0000-0000-000000000002")

    def test_yes_without_a_booted_one_takes_the_first(self):
        p = self.project(self.SIMS.replace("(Booted)", "(Shutdown)"))
        out, err, secs = self.held_open(p, 'YES=1; pick_ios; echo "rc=$? name=$I_NAME"')
        self.assertIn("rc=0 name=iPhone 17 Pro", out)

    def test_yes_prefers_the_remembered_simulator(self):
        p = self.project()
        (p.dir / ".local-dev/ios-device").write_text("CCCCCCCC-0000-0000-0000-000000000003\n")
        out, err, secs = self.held_open(p, 'YES=1; pick_ios; echo "rc=$? name=$I_NAME"')
        self.assertIn("rc=0 name=iPhone Air", out)

    def test_without_yes_and_stdin_held_open_it_gives_up_with_exit_4(self):
        p = self.project()
        out, err, secs = self.held_open(p, 'pick_ios; rc=$?; echo "rc=$rc declined=$DECLINED"; finish $rc; echo "exit=$?"')
        self.assertIn("rc=1 declined=1", out)
        self.assertIn("exit=4", out)
        self.assertIn("No answer and no terminal", out + err)
        self.assertIn("1) iPhone 17 Pro", out, "the menu is shown")
        self.assertLess(secs, 20)
        self.assertFalse((p.dir / ".local-dev/ios-device").exists(), "nothing was chosen for the user")

    def test_without_yes_and_stdin_from_dev_null_it_gives_up_at_once(self):
        p = self.project()
        e = {"PATH": str(p.bin), "HOME": str(p.home), "RUN_LOCAL_LIB": "1"}
        r = subprocess.run(["bash", "-c", f'cd "{p.dir}"; . .keelokit/bin/run-local.sh; load_config; pick_ios; rc=$?; echo "rc=$rc declined=$DECLINED"; finish $rc; echo "exit=$?"'],
                           env=e, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)
        self.assertIn("rc=1 declined=1", r.stdout)
        self.assertIn("exit=4", r.stdout)

    def test_a_piped_answer_still_works(self):
        p = self.project()
        r = self.lib(p, 'pick_ios; echo "rc=$? name=$I_NAME"', stdin="3\ny\n")
        self.assertIn("rc=0 name=iPhone Air", r.stdout)

    def phones(self, p):
        p.shim("adb", 'case "$1" in devices) printf "List of devices attached\\nS1\\tdevice usb:1 model:Galaxy_S20\\nR2\\tdevice usb:2 model:Pixel_8\\n";; esac')

    def test_several_phones_with_yes_take_the_remembered_one_else_the_first(self):
        p = self.project()
        self.phones(p)
        phones = "S1|Galaxy_S20|device|phone\nR2|Pixel_8|device|phone"
        out, err, secs = self.held_open(p, f'YES=1; pick_phone "{phones}"; echo "rc=$? serial=$A_SERIAL"')
        self.assertIn("rc=0 serial=S1", out)
        self.assertIn("--yes took the first (S1)", out)
        (p.dir / ".local-dev/android-device").write_text("R2\n")
        out, err, secs = self.held_open(p, f'YES=1; pick_phone "{phones}"; echo "rc=$? serial=$A_SERIAL"')
        self.assertIn("rc=0 serial=R2", out)
        out, err, secs = self.held_open(p, f'DEVICE=; rm .local-dev/android-device; pick_phone "{phones}"; echo "rc=$? declined=$DECLINED"')
        self.assertIn("rc=1 declined=1", out)

    def test_avd_choice_with_yes_takes_the_remembered_or_the_first_and_never_creates(self):
        p = self.project()
        p.shim("emulator", 'case "$1" in -list-avds) printf "Pixel_7_API_34\\nTablet_API_33\\n";; *) exec sleep 5;; esac')
        p.shim("adb", 'case "$1" in devices) if grep -q "emulator -avd" "' + str(p.calls) + '"; then printf "List of devices attached\\nemulator-5554\\tdevice product:sdk\\n"; else printf "List of devices attached\\n"; fi;; esac\ncase "$*" in *getprop*) echo 1;; esac')
        p.shim("avdmanager")
        out, err, secs = self.held_open(p, 'YES=1; EMULATOR_FLAG=1; load_config; ensure() { return 0; }; select_android_target; echo "rc=$? id=$A_ID"')
        self.assertIn("rc=0 id=avd:Pixel_7_API_34", out)
        self.assertIn("--yes took the emulator Pixel_7_API_34", out)
        self.assertFalse([c for c in p.called() if c.startswith("avdmanager")])

    def test_no_phone_with_yes_does_not_wait_for_one(self):
        p = self.project()
        p.shim("adb", 'case "$1" in devices) printf "List of devices attached\\n";; esac')
        out, err, secs = self.held_open(p, 'YES=1; ANDROID_TARGET=phone; ensure() { return 0; }; select_android_target; rc=$?; echo "rc=$rc blocked=$BLOCKED"; finish $rc; echo "exit=$?"')
        self.assertIn("rc=1 blocked=1", out)
        self.assertIn("exit=3", out)
        self.assertLess(secs, 20)

    def test_the_menu_gives_up_with_exit_4_when_nobody_answers(self):
        p = self.project()
        p.shim("uname", "echo Darwin")
        e = {"PATH": str(p.bin), "HOME": str(p.home), "RUN_LOCAL_ASK_TIMEOUT": "1"}
        proc = subprocess.Popen(["bash", ".keelokit/bin/run-local.sh"], cwd=p.dir, env=e, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            proc.communicate(timeout=30)
        finally:
            proc.kill()
        self.assertEqual(proc.returncode, 4)


class IosFastPathTest(Lib, unittest.TestCase):
    """iOS always asks "Open in <app>?" for a link. The script says so and opens the link."""

    def run_fast(self, profile=LOCAL_DEV):
        p = Project(self, pnpm_monorepo, profile)
        p.shim("xcrun")
        script = "wait_metro() { return 0; }; init_state; I_UDID=U1; launch() { sleep 2; return 0; }; fast_launch ios ios-metro; wait; echo done"
        return p, self.lib(p, script, stdin="y\n")

    def test_the_message_is_printed_on_the_ios_fast_path(self):
        p, r = self.run_fast()
        self.assertIn('iOS asks "Open in <your app>?": tap Open.', r.stdout)

    def test_the_link_is_opened_and_the_app_is_not_launched_first(self):
        p, r = self.run_fast()
        calls = [c for c in p.called() if c.startswith("xcrun simctl")]
        self.assertEqual(len(calls), 1, calls)
        self.assertTrue(calls[0].startswith("xcrun simctl openurl U1 demo://expo-development-client/"), calls)

    def test_without_a_scheme_the_app_is_launched(self):
        p, r = self.run_fast(LOCAL_DEV.replace('scheme = "demo"\n', ""))
        calls = [c for c in p.called() if c.startswith("xcrun simctl")]
        self.assertEqual(calls, ["xcrun simctl launch U1 com.demo.app"])

    def test_the_wait_and_log_polling_are_gone(self):
        text = SCRIPT.read_text()
        self.assertNotIn("OPEN_WAIT", text)
        self.assertNotIn("open_ios_app", text)

    def test_android_keeps_its_link_and_prints_no_ios_message(self):
        p = Project(self, pnpm_monorepo, LOCAL_DEV)
        p.shim("adb")
        r = self.lib(p, "wait_metro() { return 0; }; init_state; A_SERIAL=S1; launch() { sleep 2; return 0; }; fast_launch android android-metro; wait", stdin="y\n")
        self.assertNotIn("Open in", r.stdout)
        self.assertTrue(any("adb -s S1 shell am start -a android.intent.action.VIEW" in c for c in p.called()))


class ExpoGoPromptTest(Lib, unittest.TestCase):
    PROMPT = ("Expo Go 57.0.9 is recommended for SDK 57.0.0 (iPhone 17 Pro is using 2.32.18).\n"
              "? Install the recommended Expo Go version? \u203a (Y/n)\nPrompt cancelled.\n")

    def project(self, script_body: str):
        p = Project(self, pnpm_monorepo, LOCAL_DEV.replace('client = "dev-client"', 'client = "expo-go"'))
        (p.dir / ".gitignore").write_text(".local-dev/\n")
        (p.dir / ".local-dev/logs").mkdir(parents=True)
        p.shim("script", script_body)
        return p

    def test_a_cancelled_prompt_is_a_failure_that_only_a_person_can_resolve(self):
        p = self.project(f'printf %s "{self.PROMPT}" >"$2"')
        r = self.lib(p, 'launch ios true; rc=$?; echo "rc=$rc"; finish $rc; echo "exit=$?"')
        self.assertIn("rc=1", r.stdout)
        self.assertIn("exit=3", r.stdout)
        self.assertIn("Expo asked to install or update Expo Go and nobody could answer", r.stdout)
        self.assertNotIn("stopped", r.stdout)
        self.assertIn("Install the recommended Expo Go", (p.dir / ".local-dev/last-error.txt").read_text())

    def test_the_prompt_followed_by_a_running_metro_is_a_normal_stop(self):
        p = self.project(f'printf "%s" "{self.PROMPT}Logs for your project will appear below.\\n" >"$2"')
        r = self.lib(p, 'launch ios true; echo "rc=$?"')
        self.assertIn("rc=0", r.stdout)

    def test_with_yes_one_y_reaches_the_command_and_stdin_stays_open(self):
        p = self.project("true")
        p.shim("script", 'read -r a; echo "got:$a" >>"' + str(p.calls) + '"; if read -r -t 1 b; then echo "second:$b" >>"' + str(p.calls) + '"; else echo "still-open" >>"' + str(p.calls) + '"; fi; echo "Logs for your project" >"$2"')
        import time
        e = {"PATH": str(p.bin), "HOME": str(p.home), "RUN_LOCAL_LIB": "1"}
        proc = subprocess.Popen(["bash", "-c", f'cd "{p.dir}"; . .keelokit/bin/run-local.sh; load_config; YES=1; expo_go_yes; launch ios true; echo "rc=$?"'],
                                env=e, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        t = time.time()
        try:
            out, _ = proc.communicate(timeout=30)
        finally:
            proc.kill()
        self.assertLess(time.time() - t, 20, "the feeder is stopped with the command")
        self.assertIn("rc=0", out)
        self.assertIn("--yes accepts installing or updating it", out)
        self.assertIn("downloads the app from Expo", out)
        calls = p.called()
        self.assertIn("got:y", calls)
        self.assertIn("still-open", calls, "stdin was not closed after the y")

    def test_without_yes_nothing_is_fed(self):
        p = self.project("true")
        p.shim("script", 'if read -r -t 1 a; then echo "got:$a" >>"' + str(p.calls) + '"; else echo none >>"' + str(p.calls) + '"; fi; echo "Logs for your project" >"$2"')
        r = self.lib(p, "launch ios true; echo rc=$?", stdin="")
        self.assertNotIn("got:y", p.called())
        self.assertNotIn("--yes accepts", r.stdout)

    def test_only_the_expo_go_launches_ask_for_it(self):
        text = SCRIPT.read_text()
        self.assertEqual(len(re.findall(r"expo_go_yes\n\s+launch (ios|android)", text)), 2)

    def test_the_flag_is_used_up_by_one_launch(self):
        p = self.project('echo "Logs for your project" >"$2"')
        self.lib(p, 'YES=1; expo_go_yes; launch ios true; echo "[$FEED_Y]"')
        r = self.lib(p, 'YES=1; expo_go_yes; launch ios true; echo "[$FEED_Y]"')
        self.assertIn("[0]", r.stdout)


class SeedQuestionTest(Lib, unittest.TestCase):
    """Before launching: "Load the seed data?" with a recommendation; always its own yes."""

    def project(self, state_out=None, extra_local=""):
        p = Project(self, pnpm_monorepo, LOCAL_DEV.replace('db_service = "postgres"', 'db_service = "postgres"\napi_seed = "echo seeded >seed.out"' + extra_local))
        (p.dir / ".gitignore").write_text(".local-dev/\n")
        (p.dir / ".local-dev/logs").mkdir(parents=True)
        body = "" if state_out is None else f'echo "{state_out}"'
        p.shim("docker", body)
        return p

    def step(self, p, stdin="", pre="", tty=True):
        env = {"RUN_LOCAL_TTY": "1"} if tty else {}
        return self.lib(p, f'{pre or ":"}; seed_step; echo "rc=$?"', stdin=stdin, env=env)

    def test_an_empty_database_is_recommended_and_a_yes_runs_the_seed(self):
        p = self.project("0")
        r = self.step(p, "\n")  # Enter takes the default: yes when it looks empty
        self.assertIn("The database looks empty: loading the seed data is recommended.", r.stdout)
        self.assertTrue((p.dir / "seed.out").exists())
        self.assertEqual((p.dir / ".local-dev/seed_default").read_text().strip(), "yes")
        self.assertTrue(any("psql" in c or "exec -T postgres" in c for c in p.called()), p.called())

    def test_a_database_with_data_is_not_recommended_and_enter_means_no(self):
        p = self.project("42")
        r = self.step(p, "\n")
        self.assertIn("already has data", r.stdout)
        self.assertFalse((p.dir / "seed.out").exists())
        self.assertEqual((p.dir / ".local-dev/seed_default").read_text().strip(), "no")

    def test_when_it_cannot_tell_it_says_so(self):
        p = self.project("not a number")
        r = self.step(p, "n\n")
        self.assertIn("can't tell if the database already has data", r.stdout)
        self.assertFalse((p.dir / "seed.out").exists())

    def test_the_remembered_answer_is_the_next_default(self):
        p = self.project("42")
        (p.dir / ".local-dev/seed_default").write_text("yes\n")
        self.step(p, "\n")
        self.assertTrue((p.dir / "seed.out").exists(), "a database with data, but last time said yes: Enter is yes")
        p = self.project("0")
        (p.dir / ".local-dev/seed_default").write_text("no\n")
        self.step(p, "\n")
        self.assertFalse((p.dir / "seed.out").exists())

    def test_never_silent_yes_alone_and_no_terminal_do_not_seed(self):
        p = self.project("0")
        r = self.step(p, pre="YES=1")
        self.assertFalse((p.dir / "seed.out").exists())
        self.assertIn("seed not run", r.stdout)
        p = self.project("0")
        r = self.step(p, tty=False)
        self.assertFalse((p.dir / "seed.out").exists())
        self.assertIn("needs a yes at a terminal", r.stdout)

    def test_the_flags(self):
        p = self.project("42")
        self.step(p, pre="SEED_FLAG=1; YES=1")
        self.assertTrue((p.dir / "seed.out").exists(), "--seed is the yes, even with --yes")
        p = self.project("0")
        r = self.step(p, pre="NOSEED_FLAG=1")
        self.assertFalse((p.dir / "seed.out").exists())
        self.assertIn("seed skipped (--no-seed)", r.stdout)
        self.assertEqual(p.run("android", "--seed", "--no-seed").returncode, 2)

    def test_the_seed_command_asks_unless_yes_and_then_shows_the_users(self):
        p = self.project()
        write(p.dir, "docs/test-users.md", "| Role | Email | Password |\n|---|---|---|\n| admin | admin@demo.test | demo1234 |\n")
        r = self.lib(p, "run_seed 1", stdin="n\n", env={"RUN_LOCAL_TTY": "1"})
        self.assertFalse((p.dir / "seed.out").exists())
        r = self.lib(p, "run_seed 1", stdin="y\n")
        self.assertTrue((p.dir / "seed.out").exists())
        self.assertIn("admin@demo.test", r.stdout)
        self.assertIn("Test users", r.stdout)


class TargetQuestionTest(Lib, unittest.TestCase):
    DEVICES = "List of devices attached\\nS1\\tdevice usb:1 model:Galaxy_S20\\n"

    def project(self, avds="Pixel_7_API_34\\n", extra_local=""):
        p = Project(self, pnpm_monorepo, LOCAL_DEV + extra_local)
        (p.dir / ".gitignore").write_text(".local-dev/\n")
        (p.dir / ".local-dev/logs").mkdir(parents=True)
        p.shim("adb", 'case "$1" in devices) if grep -q "emulator -avd" "' + str(p.calls) + '"; then printf "' + self.DEVICES + 'emulator-5554\\tdevice product:sdk\\n"; else printf "' + self.DEVICES + '"; fi;; esac\n'
                      'case "$*" in *getprop*) echo 1;; esac')
        p.shim("emulator", f'case "$1" in -list-avds) printf "{avds}";; *) exec sleep 5;; esac')
        p.shim("uname", 'case "$1" in -m) echo x86_64;; *) echo Darwin;; esac')
        return p

    def select(self, p, stdin="", flags=":", tty=True):
        env = {"RUN_LOCAL_TTY": "1"} if tty else {}
        return self.lib(p, f'ensure() {{ return 0; }}; {flags}; select_android_target; echo "rc=$? kind=$A_KIND"', stdin=stdin, env=env)

    def test_with_a_phone_and_an_emulator_it_asks_and_the_default_is_the_last_choice(self):
        p = self.project()
        r = self.select(p, "2\ny\n")
        self.assertIn("kind=emulator", r.stdout)
        self.assertEqual((p.dir / ".local-dev/android_target_last").read_text().strip(), "emulator")
        p = self.project()
        r = self.select(p, "\n")
        self.assertIn("kind=phone", r.stdout)
        self.assertEqual((p.dir / ".local-dev/android_target_last").read_text().strip(), "phone")
        (p.dir / ".local-dev/android_target_last").write_text("emulator\n")
        r = self.select(p, "\ny\n")  # Enter: last time's choice
        self.assertIn("kind=emulator", r.stdout)

    def test_with_yes_or_no_terminal_it_never_blocks_and_says_how_to_change_it(self):
        p = self.project()
        r = self.select(p, flags="YES=1")
        self.assertIn("kind=phone", r.stdout)
        self.assertIn("--phone | --emulator, or android_target in [local]", r.stdout)
        (p.dir / ".local-dev/android_target_last").write_text("emulator\n")
        r = self.select(p, flags="YES=1")
        self.assertIn("kind=emulator", r.stdout)
        p = self.project()
        r = self.select(p, tty=False)
        self.assertIn("kind=phone", r.stdout)

    def test_no_question_when_there_is_no_real_choice(self):
        p = Project(self, pnpm_monorepo, LOCAL_DEV)
        p.shim("adb", 'case "$1" in devices) printf "' + self.DEVICES + '";; esac')  # no emulator tool at all
        p.shim("uname", "echo Darwin")
        r = self.select(p, "")
        self.assertIn("kind=phone", r.stdout)
        self.assertNotIn("a phone and an emulator are both possible", r.stdout)

    def test_the_flags_and_the_setting_override(self):
        p = self.project()
        self.assertIn("kind=phone", self.select(p, "", "PHONE_FLAG=1; load_config").stdout)
        self.assertIn("kind=emulator", self.select(self.project(), "y\n", "EMULATOR_FLAG=1; load_config").stdout)
        self.assertIn("kind=emulator", self.select(self.project(extra_local='android_target = "emulator"\n'), "y\n").stdout)
        self.assertIn("kind=phone", self.select(self.project(extra_local='android_target = "phone"\n')).stdout)

    def test_auto_keeps_the_phone_when_one_is_connected(self):
        p = self.project(extra_local='android_target = "auto"\n')
        r = self.select(p, "2\n")  # an answer nobody asked for stays unread
        self.assertIn("kind=phone", r.stdout)
        self.assertNotIn("both possible", r.stdout)

    def test_ask_is_the_default_and_the_flags_exclude_each_other(self):
        p = self.project()
        self.assertEqual(self.lib(p, "echo $ANDROID_TARGET").stdout.strip(), "ask")
        self.assertEqual(p.run("android", "--phone", "--emulator").returncode, 2)
        self.assertEqual(self.lib(self.project(extra_local='android_target = "sometimes"\n'), "check_config; echo rc=$?").stdout.count("rc=1"), 1)

    def test_a_device_naming_an_avd_means_the_emulator_without_asking(self):
        p = self.project()
        r = self.select(p, "y\n", "DEVICE=Pixel_7_API_34")
        self.assertIn("kind=emulator", r.stdout)
        self.assertNotIn("both possible", r.stdout)


class UsersTest(Lib, unittest.TestCase):
    ACCOUNTS = "| Role | Email | Password |\n|---|---|---|\n| admin | admin@demo.test | demo1234 |\n| athlete | ana@demo.test | demo1234 |\n"

    def users(self, p, *args):
        r = p.run("users", "--json", *args)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def project(self, files=None, local_extra=""):
        def build(d):
            pnpm_monorepo(d)
            for rel, text in (files or {}).items():
                write(d, rel, text)
        p = Project(self, build, LOCAL_DEV + local_extra)
        p.shim("uname", "echo Linux")  # `users` reads project files only: any OS
        return p

    def test_users_file_wins_and_lines_are_raw(self):
        p = self.project({"notes/accounts.txt": "ana@demo.test / secret\n", "docs/test-users.md": self.ACCOUNTS}, 'users_file = "notes/accounts.txt"\n')
        d = self.users(p)
        self.assertEqual(d, {"source": "notes/accounts.txt", "accounts": [{"line": "ana@demo.test / secret"}]})

    def test_the_fallbacks_in_order(self):
        p = self.project({"docs/test-users.md": self.ACCOUNTS, "docs/local-testing.md": "x@y.test pw\n"})
        d = self.users(p)
        self.assertEqual(d["source"], "docs/test-users.md")
        self.assertEqual(len(d["accounts"]), 4)
        p = self.project({"docs/local-testing.md": "Intro line\nlogin as boss@demo.test\nnothing here\npassword: abc\n"})
        d = self.users(p)
        self.assertEqual((d["source"], [a["line"] for a in d["accounts"]]), ("docs/local-testing.md (a guess)", ["login as boss@demo.test", "password: abc"]))
        p = self.project({"docs/local-android-testing.md": "owner@demo.test\nadmin@demo.test\n"})
        self.assertEqual(self.users(p)["source"], "docs/local-android-testing.md")

    def test_a_readme_section(self):
        readme = "# App\n\nIntro\n\n## Usuarios de prueba\n\n| Rol | Email |\n|---|---|\n| admin | a@demo.test |\n| ana | ana@demo.test |\n\n## Next\n\nnot a user line\n"
        d = self.users(self.project({"README.md": readme}))
        self.assertEqual(d["source"], "README.md (Usuarios de prueba)")
        self.assertEqual(len(d["accounts"]), 4)
        self.assertFalse(any("Next" in a["line"] or "not a user" in a["line"] for a in d["accounts"]))
        for title in ("Test users", "Demo accounts", "Cuentas de prueba", "Demo users"):
            with self.subTest(title=title):
                self.assertEqual(self.users(self.project({"README.md": f"# A\n\n### {title}\n- ana@demo.test\n"}))["source"], f"README.md ({title})")

    def test_the_seed_log_is_the_last_resort_and_only_credential_lines(self):
        p = self.project({".local-dev/logs/seed.log": "\x1b[32mseeding\x1b[0m\nCreated ana@demo.test\nPassword for all: demo1234\nunrelated noise\n"})
        d = self.users(p)
        self.assertEqual(d["source"], ".local-dev/logs/seed.log (a guess)")
        self.assertEqual([a["line"] for a in d["accounts"]], ["Created ana@demo.test", "Password for all: demo1234"])

    def test_nothing_found_says_how_to_add_users_file(self):
        p = self.project()
        self.assertEqual(self.users(p), {"source": None, "accounts": []})
        r = p.run("users")
        self.assertEqual(r.returncode, 0)
        self.assertIn('users_file = "docs/test-users.md"', r.stdout)

    def test_it_never_reads_env_files_or_anything_outside_the_project(self):
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, outside)
        (outside / "secret.md").write_text("root@evil.test password\n")
        p = self.project({".env": "ADMIN=a@demo.test password\n", "apps/api/.env.local": "x@y.test password\n"})
        (p.dir / "link.md").symlink_to(outside / "secret.md")
        for bad in (".env", "apps/api/.env.local", "../secret.md", str(outside / "secret.md"), "link.md", "docs/../../x"):
            with self.subTest(users_file=bad):
                q = self.project({".env": "ADMIN=a@demo.test password\n"}, f'users_file = "{bad}"\n')
                if bad == "link.md":
                    (q.dir / "link.md").symlink_to(outside / "secret.md")
                self.assertEqual(self.users(q)["accounts"], [])

    def test_nothing_is_written(self):
        p = self.project({"docs/test-users.md": self.ACCOUNTS})
        before = sorted(str(f.relative_to(p.dir)) for f in p.dir.rglob("*") if f.is_file() and ".git" not in f.parts)
        p.run("users")
        p.run("users", "--json")
        after = sorted(str(f.relative_to(p.dir)) for f in p.dir.rglob("*") if f.is_file() and ".git" not in f.parts)
        self.assertEqual(before, after)

    def test_the_human_output_names_the_source(self):
        p = self.project({"docs/test-users.md": self.ACCOUNTS})
        out = p.run("users").stdout
        self.assertIn("Test users (from docs/test-users.md)", out)
        self.assertIn("admin@demo.test", out)

    def test_status_json_carries_the_users(self):
        p = self.project({"docs/test-users.md": self.ACCOUNTS})
        p.shim("uname", "echo Darwin")
        data = json.loads(p.run("status", "--json").stdout)
        self.assertEqual(data["users"]["source"], "docs/test-users.md")
        self.assertEqual(data["users"]["accounts"][0], {"line": "| Role | Email | Password |"})

    def test_detect_suggests_the_users_file(self):
        p = self.project({"docs/test-users.md": self.ACCOUNTS})
        self.assertEqual(json.loads(p.run("detect").stdout)["users_file"], "docs/test-users.md")

    def test_the_block_is_short_and_shown_once_when_a_launch_starts(self):
        many = "\n".join(f"user{i}@demo.test pw" for i in range(30)) + "\n"
        p = self.project({"docs/test-users.md": many})
        (p.dir / ".gitignore").write_text(".local-dev/\n")
        (p.dir / ".local-dev/logs").mkdir(parents=True)
        p.shim("script", 'echo "Logs for your project" >"$2"')
        r = self.lib(p, "launch metro true; launch metro true")
        self.assertEqual(r.stdout.count("Test users"), 1)
        self.assertEqual(len([l for l in r.stdout.splitlines() if "@demo.test" in l]), 15)
        self.assertIn("15 more: bash .keelokit/bin/run-local.sh users", r.stdout)

    def test_no_users_is_one_line_with_the_hint(self):
        p = self.project()
        (p.dir / ".gitignore").write_text(".local-dev/\n")
        (p.dir / ".local-dev/logs").mkdir(parents=True)
        p.shim("script", 'echo "Logs for your project" >"$2"')
        r = self.lib(p, "launch metro true")
        self.assertIn("Test users: none found", r.stdout)
        self.assertIn("run-local.sh users", r.stdout)

    def test_users_has_help_and_the_shape(self):
        p = self.project()
        self.assertIn("users_file", p.run("users", "--help").stdout)


NOISY_GUIDE = """# Local Android testing

Install the tools first:

| Tool | Command |
|---|---|
| Node | `pnpm install` |
| Mail | `docker compose up -d mailpit` |

Mailpit catches every email at http://localhost:8025 (sender noreply@jouna.app).

## 4. The API

Create `apps/api/.env` with:

```
SMTP_PASSWORD=local
ADMIN_EMAIL=root@jouna.app
DATABASE_URL=postgresql://app:app@localhost:5432/app
```

docker compose up -d --wait postgres
Never reuse these passwords outside your machine: contact security@jouna.app if you do.
[Read the full security guide](https://example.com/security)

## 7. Demo accounts

Every account's password is `demo1234`:

| Role | Email |
|---|---|
| owner | owner@demo.jouna.app |
| admin | admin@demo.jouna.app |
| staff | staff@demo.jouna.app |
| coach | coach@demo.jouna.app |
| athlete | ana@demo.jouna.app |
| athlete | ben@demo.jouna.app |
| athlete | cris@demo.jouna.app |
| athlete | dana@demo.jouna.app |

> Note: change the password before sharing a build.
Something unrelated after, with a mail to help@jouna.app.

## 8. Troubleshooting

Run `pnpm dev` again.
"""


class NoisyGuideTest(Lib, unittest.TestCase):
    users = UsersTest.users
    project = UsersTest.project

    def test_only_the_accounts_table_and_the_password_sentence_come_out(self):
        d = self.users(self.project({"docs/local-android-testing.md": NOISY_GUIDE}))
        lines = [a["line"] for a in d["accounts"]]
        self.assertEqual(d["source"], "docs/local-android-testing.md")
        self.assertEqual(lines[0], "Every account's password is `demo1234`:")
        self.assertEqual(lines[1:4], ["| Role | Email |", "|---|---|", "| owner | owner@demo.jouna.app |"])
        self.assertEqual(sum("@demo.jouna.app" in l for l in lines), 8)
        self.assertEqual(lines[-1], "> Note: change the password before sharing a build.")
        self.assertEqual(len(lines), 12)
        for noise in ("SMTP_PASSWORD", "ADMIN_EMAIL", "pnpm install", "docker compose", "Never reuse", "Mailpit", "noreply@", "help@", "Read the full"):
            self.assertFalse(any(noise in l for l in lines), noise)

    def test_a_long_table_is_cut_at_15_and_names_its_heading(self):
        rows = "".join(f"| user{i} | user{i}@demo.test |\n" for i in range(20))
        guide = f"# G\n\n## 7. Demo accounts\n\nThe password is demo1234:\n\n| Role | Email |\n|---|---|\n{rows}"
        d = self.users(self.project({"docs/local-testing.md": guide}))
        lines = [a["line"] for a in d["accounts"]]
        self.assertEqual(len(lines), 16)
        self.assertEqual(lines[-1], "(more in docs/local-testing.md §7. Demo accounts)")
        self.assertEqual(sum("@demo.test" in l for l in lines), 12, "15 lines: the sentence, the header, the rule and 12 rows")

    def test_the_largest_cluster_wins_and_a_blank_line_between_rows_is_allowed(self):
        guide = ("x one@a.test\ny two@a.test\n\nPassword: p\n| A | B |\n|---|---|\n| 1 | a1@d.test |\n\n| 2 | a2@d.test |\n| 3 | a3@d.test |\n")
        d = self.users(self.project({"docs/local-testing.md": guide}))
        lines = [a["line"] for a in d["accounts"]]
        self.assertEqual([l for l in lines if "@d.test" in l], ["| 1 | a1@d.test |", "| 2 | a2@d.test |", "| 3 | a3@d.test |"])
        self.assertIn("Password: p", lines)
        self.assertFalse(any("a.test" in l for l in lines))

    def test_a_tie_goes_to_the_first_cluster(self):
        guide = "first1@a.test\nfirst2@a.test\n\n\n\nsecond1@b.test\nsecond2@b.test\nPassword: x\n"
        lines = [a["line"] for a in self.users(self.project({"docs/local-testing.md": guide}))["accounts"]]
        self.assertEqual(lines, ["first1@a.test", "first2@a.test"])

    def test_lines_above_only_count_when_they_speak_of_passwords(self):
        guide = "Some prose about the team.\nThe login is in the table:\n\n| a@x.test |\n| b@x.test |\n"
        lines = [a["line"] for a in self.users(self.project({"docs/local-testing.md": guide}))["accounts"]]
        self.assertEqual(lines, ["The login is in the table:", "| a@x.test |", "| b@x.test |"])

    def test_no_emails_falls_back_to_a_guess_and_says_so(self):
        guide = ("# Guide\n\nRun things.\nLog in with the username admin.\nThe password is hunter2.\nnoise\nmore noise\n"
                 "Another username: boss\n\n\n\n\nunrelated\n")
        d = self.users(self.project({"docs/local-testing.md": guide}))
        self.assertEqual(d["source"], "docs/local-testing.md (a guess)")
        lines = [a["line"] for a in d["accounts"]]
        self.assertIn("Log in with the username admin.", lines)
        self.assertIn("The password is hunter2.", lines)
        self.assertLessEqual(len(lines), 5)
        self.assertFalse(any("noise" in l or "unrelated" in l for l in lines))

    def test_a_guide_with_neither_emails_nor_passwords_finds_nothing(self):
        guide = "# Guide\n\nRun `pnpm dev`.\nOpen the app.\nDATABASE_URL=postgresql://x\n"
        d = self.users(self.project({"docs/local-testing.md": guide}))
        self.assertEqual(d, {"source": None, "accounts": []})

    def test_one_stray_email_is_not_an_accounts_table(self):
        guide = "# G\n\nSend feedback to me@x.test whenever.\nNothing else.\n"
        self.assertEqual(self.users(self.project({"docs/local-testing.md": guide}))["accounts"], [])

    def test_the_same_logic_applies_to_readme_sections_and_the_seed_log(self):
        readme = "# App\n\n## Test users\n\nPassword for all: demo1234\n\n| Email |\n|---|\n| a@d.test |\n| b@d.test |\n\nSee SMTP_PASSWORD=local\nrun `docker compose up`\n\n## Next\n"
        d = self.users(self.project({"README.md": readme}))
        self.assertEqual(d["source"], "README.md (Test users)")
        self.assertEqual([a["line"] for a in d["accounts"]], ["Password for all: demo1234", "| Email |", "|---|", "| a@d.test |", "| b@d.test |"])
        log = "\x1b[32mseeded\x1b[0m\nDATABASE_URL=postgres://x\nana@d.test  demo1234\nben@d.test  demo1234\ndone\n"
        d = self.users(self.project({".local-dev/logs/seed.log": log}))
        self.assertEqual(d["source"], ".local-dev/logs/seed.log")
        self.assertEqual([a["line"] for a in d["accounts"]], ["ana@d.test  demo1234", "ben@d.test  demo1234"])

    def test_the_shape_is_unchanged(self):
        d = self.users(self.project({"docs/local-android-testing.md": NOISY_GUIDE}))
        self.assertEqual(set(d), {"source", "accounts"})
        self.assertTrue(all(set(a) == {"line"} for a in d["accounts"]))


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
