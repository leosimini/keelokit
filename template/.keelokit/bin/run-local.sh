#!/usr/bin/env bash
# Runs the product's Expo app and its API on this Mac, in one command, on ONE target at a time: an
# Android phone (USB or wireless debugging), an Android emulator or an iOS Simulator. It checks what
# the Mac is missing, shows it all at once and, after one yes, installs it; then starts the database
# and the API, and launches the app. It runs without Claude and without the plugin, like
# scripts/verify.sh.
#
#   bash .keelokit/bin/run-local.sh                  menu
#   bash .keelokit/bin/run-local.sh <command> [options]       (`<command> --help` says more)
#
#   android   the app on a phone, or on an emulator (--emulator)
#   ios       the app on an iOS simulator
#   metro     only Metro (and adb reverse): you open the app by hand
#   backend   only the database, its services and the API
#   seed      run the project's seed script (asks first: it writes to the database), then show the test users
#   users     the test accounts the project's own docs or seed list (--json)
#   pair      pair and connect a phone over Wi-Fi (wireless debugging)
#   doctor    what this Mac is missing (--json, --check, --no-install)
#   status    what is running: API, database, Metro, devices, who holds each port (--json)
#   logs      the tail of the step logs in .local-dev/logs, newest first (logs <step>)
#   clean     delete generated native folders, build caches and logs, group by group, after asking
#   stop      stop the API, the containers and an emulator, each after asking
#   detect    what the repo shows, as JSON (what [local] would hold)
#
# Options: --yes (answer yes to every question), --check, --no-install, --json, --seed, --no-seed,
#   --rebuild (always build the native app), --no-build (never build it: fail if it is not installed),
#   --phone / --emulator (Android target), --new-avd (create a new emulator with an 8 GB data partition), --device <serial|model|name|udid>, --help.
#
# Questions: with --yes nothing is asked, and a menu takes the remembered choice, else the first one
#   (and says so). Without --yes and without a terminal an unanswered question gives up after 20 s
#   (RUN_LOCAL_ASK_TIMEOUT) as declined: exit 4, never a hang.
# Exit codes: 0 done · 1 failed, or something is missing · 2 usage · 3 stopped on something only a
#   person can do (Xcode, no phone, no emulator image) · 4 a question was declined, or there was
#   no terminal to answer it.
#
# JSON (stdout; nothing else is printed in that mode):
#   doctor --json / doctor --check --json
#     {"command":"doctor","exit":0,"ok":true,
#      "messages":[{"level":"ok|warn|bad|say","text":"..."}],
#      "missing":[{"label":"...","command":"..."}],      installs it would offer
#      "blockers":["..."]}                                only a person can fix these
#   status --json
#     {"api":{"configured":true,"up":true,"port":3000,"pid":123,"process":"node"},
#      "database":{"services":{"db":"running|stopped|unknown"}},
#      "metro":{"up":false,"port":8081,"pid":null,"process":null},
#      "android":{"devices":[{"serial":"...","model":"...","state":"device","kind":"phone|emulator"}],"chosen":null},
#      "ios":{"booted":[{"udid":"...","name":"..."}],"chosen":null},
#      "ports":{"3000":{"pid":123,"process":"node"}}}
#   detect: the keys of [local], plus "uncertain" (keys it is not sure of), "mobile_dirs" and "runner".
#
# Settings live in the [local] block of .keelokit/profile.toml; whatever it leaves out is detected
# from the repo. Messages follow the project's language ([dashboard] lang in .keelokit/state.toml,
# else $LANG; English or Spanish); --help is English.
# Every step logs to .local-dev/logs/. When one fails, the tail of its log goes to
# .local-dev/last-error.txt (hand that file to Claude), a few known causes (REPAIRS, below) are
# repaired and the step runs again once. Nothing is killed, stopped or deleted without asking.
#
# A second `android` or `ios` does not rebuild: when the app is installed on the target and nothing
# native changed since the last successful install, only Metro starts and the app opens.
#
# macOS only. Launched an app on the iOS simulator and on a Samsung Galaxy S20 over USB, on Intel
# with Xcode 26. UNTESTED: Apple Silicon, wireless debugging, Expo Go, the Android emulator, the
# fingerprint through @expo/fingerprint. macOS ships bash 3.2: no mapfile, no associative arrays.
set -o pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.." || exit 1

SELF=$PWD/.keelokit/bin/run-local.sh
PROFILE=.keelokit/profile.toml
STATE=.local-dev
LOG=$STATE/logs
YES=0 CHECK=0 NOINSTALL=0 JSONMODE=0 SEED_FLAG=0 NOSEED_FLAG=0 REBUILD=0 NOBUILD=0 EMULATOR_FLAG=0 PHONE_FLAG=0 NEWAVD_FLAG=0 USERS_SHOWN=0 EMU_EXTRA= DEVICE= CMD= ARG2=
PLAN_D=() PLAN_C=() BLOCKERS=() MSGS=() MISSING=() BLOCKED_MSGS=()
QUIET=0 DETECTED=0 HAS_LOCAL=0 DECLINED=0 BLOCKED=0
PLISTBUDDY=${PLISTBUDDY:-/usr/libexec/PlistBuddy} # the overridable tools are test hooks (tests/test_run_local.py)

# ---------- known failures and what repairs them ----------
# One line each: <extended regex found in the log> => <action>. The first line that matches runs
# `repair_<action>`; an action returns 0 when it changed something (the step runs again), 1 when
# the failure stays, 2 when it does not apply here (the next line is tried).
REPAIRS=(
  'INSTALL_FAILED_INSUFFICIENT_STORAGE => insufficient_storage'
  'INSTALL_FAILED_UPDATE_INCOMPATIBLE|signatures do not match => uninstall_app'
  'EADDRINUSE|[Pp]ort 8081 .*(in use|already) => free_metro_port'
  'OutOfMemoryError|Java heap space|Gradle daemon.*(disappeared|stopped)|Daemon will be stopped => gradle_memory'
  'pod install|CocoaPods could not find compatible|Unable to find a specification => pod_reinstall'
  'google-services.json|GoogleService-Info.plist => google_file'
  '5554.*(in use|busy|already)|(in use|busy|already).*5554 => free_emulator_port'
  'multiple emulators with the same AVD|\.lock => avd_lock'
  'HAXM|HVF|[Hh]ypervisor|KVM|acceleration => no_acceleration'
)

# ---------- language and output ----------

LNG=$(awk '/^[ \t]*\[/{s=$0;gsub(/^[ \t]*\[|\][ \t]*(#.*)?$/,"",s);i=(s=="dashboard");next} i&&/^[ \t]*lang[ \t]*=/{v=$0;sub(/^[^=]*=[ \t]*"?/,"",v);sub(/".*$/,"",v);print v;exit}' .keelokit/state.toml 2>/dev/null)
if [ -z "$LNG" ]; then case "${LANG:-}" in es*) LNG=es ;; *) LNG=en ;; esac; fi
L() { if [ "$LNG" = es ]; then printf '%s' "$2"; else printf '%s' "$1"; fi; } # L <english> <spanish>

emit() { MSGS+=("$1"$'\t'"$2"); } # every message is kept for --json, and printed unless that is on
say() { emit say "$*"; [ "$JSONMODE" = 1 ] || printf '\n\033[1m▶ %s\033[0m\n' "$*"; }
ok() { [ "$QUIET" = 1 ] && return 0; emit ok "$*"; [ "$JSONMODE" = 1 ] || printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { emit warn "$*"; [ "$JSONMODE" = 1 ] || printf '  \033[33m!\033[0m %s\n' "$*"; }
bad() { emit bad "$*"; [ "$JSONMODE" = 1 ] || printf '  \033[31m✗\033[0m %s\n' "$*"; }
# Reads an answer into <var>. At a terminal it waits as long as it takes. Without one (a pipe, a
# script, stdin held open by a tool) it waits RUN_LOCAL_ASK_TIMEOUT seconds (20) and then gives up:
# the question counts as declined (exit 4) and the script says so, instead of blocking forever.
interactive() { [ -t 0 ] || [ "${RUN_LOCAL_TTY:-}" = 1 ]; } # a person can answer (RUN_LOCAL_TTY=1 is a test hook)

ask() { # <var> <prompt>
  local to=()
  [ -t 0 ] || to=(-t "${RUN_LOCAL_ASK_TIMEOUT:-20}")
  read -r "${to[@]}" -p "$2" "$1" && return 0
  DECLINED=1
  printf '\n' >&2
  bad "$(L 'No answer and no terminal to ask on: nothing was chosen for you. Run it in a terminal, or add --yes to take the defaults.' 'Sin respuesta y sin terminal para preguntar: no elegí nada por vos. Corrélo en una terminal, o agregá --yes para tomar lo predeterminado.')" >&2
  return 1
}
confirm() {
  [ "$YES" = 1 ] && return 0
  local a
  ask a "  $1 $(L '[Y/n]' '[S/n]') " || return 1
  [[ -z $a || $a =~ ^[sSyY] ]] && return 0
  DECLINED=1
  return 1
}
need() { # <what> <command>: "?what" = optional
  PLAN_D+=("$1"); PLAN_C+=("$2"); MISSING+=("${1#\?}"$'\t'"$2")
  bad "$(L 'missing:' 'falta:') ${1#\?}"
}
block() { BLOCKERS+=("$1"); BLOCKED=1; bad "$1"; } # only a person can fix it

usage() { echo "usage: bash .keelokit/bin/run-local.sh [android|ios|metro|backend|seed|users|pair|doctor|status|logs|clean|stop|detect] [options]  (--help)" >&2; }

help_text() { # <command>
  case "$1" in
    android) cat <<'EOF'
android — the app on an Android phone, or an emulator
  Checks the Mac, starts the database and the API, picks the target, and launches the app.
  If the app is already installed there and nothing native changed since the last successful
  install, it only starts Metro and opens the app (no build); it says which path it took and why.
  --rebuild      build the native app even so
  --no-build     never build: fail if the app is not installed
  --phone        use the phone; --emulator the emulator ([local] android_target: phone | emulator | auto | ask)
                 With a phone connected and an emulator available it asks "phone or emulator?" at a terminal
                 (default: last time's choice, kept in .local-dev/android_target_last). With --yes or no
                 terminal it takes that choice, says so and goes on. "auto": the phone when one is connected.
  --new-avd      create a new emulator (8 GB of storage; no download if its image is installed) and use it
  --device X     the phone by serial or model, or the emulator by AVD name
  --yes          answer yes to every question
  One phone connected: it is used. Several: you choose, and the choice is remembered in
  .local-dev/android-device. None: it offers the emulator (an AVD is created only after you
  see the download size and say yes). UNTESTED: the emulator, wireless debugging, Expo Go.
EOF
      ;;
    ios) cat <<'EOF'
ios — the app on an iOS simulator
  --rebuild      build the native app even if it is installed and nothing native changed
  --no-build     never build: fail if the app is not installed
  --device X     the simulator by name or UDID (otherwise the one you chose last time, or a menu)
  A simulator build removes capabilities a simulator cannot run (Sign in with Apple, push) from
  a generated ios/, showing the list and asking once. A git-tracked ios/ is never edited.
EOF
      ;;
    metro) echo "metro — only Metro, plus adb reverse (API and Metro ports) to every connected Android device; no device actions. For people who open the app by hand." ;;
    backend) echo "backend — the database and its [local] services (docker compose), the migration, and the API. The seed is offered, never run silently (see: seed)." ;;
    seed) cat <<'EOF'
seed — runs [local] api_seed (detected: db:seed, seed, seed:demo, prisma db seed) and then shows the test users.
  It writes to your local database, so it asks first (--yes answers it). android/ios/backend ask "Load the
  seed data?" at a terminal, recommending it when the database looks empty (docker compose exec <db> psql,
  best effort); the answer becomes the next default (.local-dev/seed_default). They never seed with
  --yes alone: --seed does it, --no-seed skips the question.
EOF
      ;;
    users) echo "users — the test accounts the project lists: [local] users_file, else docs/test-users.md, docs/local-testing.md, docs/local-android-testing.md, a README section (Test users, Demo accounts, Usuarios de prueba...), else lines of the last seed's log. Prints the raw lines and where they come from; --json for {\"source\",\"accounts\":[{\"line\"}]}. It reads only files of this project (never .env) and writes nothing. It is shown too when a launch starts and after the seed." ;;
    pair) echo "pair — wireless debugging. On the phone: Developer options → Wireless debugging → Pair device with pairing code. It asks for the pairing address, lets adb ask you for the code, then asks for the connect address. Nothing is stored. UNTESTED." ;;
    doctor) cat <<'EOF'
doctor — what this Mac is missing, all at once
  --check        only check that [local] is coherent and the Expo app is where it says (any OS)
  --no-install   diagnose, install nothing, exit 1 if something is missing
  --json         the same as JSON (see the header of this script)
  Without --check or --no-install it offers to install what is missing, after one yes.
EOF
      ;;
    status) echo "status — what is running: the API, the database services, Metro, Android devices and emulators, booted simulators, and who holds ports 3000, 8081, 5554 and the database's. --json for a machine-readable answer." ;;
    logs) echo "logs [step] — the tail of the logs in .local-dev/logs, newest first; with a step name (db, migrate, android, ios, api, emulator...) its last 100 lines." ;;
    clean) cat <<'EOF'
clean — frees disk, group by group, listing exactly what goes and its size
  1. build caches: Gradle (android/.gradle, build, .cxx), iOS (Pods, build)
  2. Xcode DerivedData of this project (only folders whose info.plist names this folder)
  3. the generated android/ and ios/ folders, only when git does not track them
  4. the logs in .local-dev/
  Each group is asked separately (--yes answers yes to each). Tracked files, symlinks and anything
  outside this project are never touched. The next build regenerates what it needs (10–20 min).
EOF
      ;;
    stop) echo "stop — asks before stopping the API, the containers (the data stays) and an Android emulator." ;;
    detect) echo "detect — prints what the repo shows as JSON: the keys of [local], the ones it is not sure of (\"uncertain\"), the Expo apps found." ;;
    *) usage ;;
  esac
}

# ---------- configuration: [local] in profile.toml, else what the repo shows ----------

toml_get() { # <file> <section> <key>: prints "=<value>" when the key is there (even empty), nothing when not
  awk -v sec="$2" -v key="$3" '
    /^[ \t]*\[/ { s=$0; gsub(/^[ \t]*\[|\][ \t]*(#.*)?$/,"",s); insec=(s==sec); next }
    insec && $0 ~ "^[ \t]*" key "[ \t]*=" {
      v=$0; sub(/^[^=]*=[ \t]*/,"",v)
      if (v ~ /^"/) { sub(/^"/,"",v); sub(/".*$/,"",v) }
      else if (v ~ /^\047/) { sub(/^\047/,"",v); sub(/\047.*$/,"",v) }
      else sub(/[ \t]*(#.*)?$/,"",v)
      print "=" v; exit }' "$1" 2>/dev/null
}

# The detection, in Python (stdlib only). `kv`: key=value lines; `json`: the same for people and
# skills; `client`: Expo Go or a dev client, and why; `fingerprint`: a hash of what a native build
# depends on (the fallback when @expo/fingerprint is not there); `json_doctor` / `json_status`:
# JSON from the tab-separated lines on stdin.
# (The program is kept in a variable, not fed through stdin, so the JSON modes can read stdin.)
IFS= read -r -d '' DETECT_PY <<'PY'
import hashlib, json, os, re, subprocess, sys
root, mode = sys.argv[1], sys.argv[2]
SKIP = {"node_modules", "ios", "android", "dist", "build", "Pods", "coverage"}

def readj(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def reads(p):
    try:
        with open(p, encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return ""

def walk(depth=4):
    for cur, ds, fs in os.walk(root):
        rel = os.path.relpath(cur, root)
        d = 0 if rel == "." else rel.count(os.sep) + 1
        ds[:] = [x for x in ds if x not in SKIP and not x.startswith(".")] if d < depth else []
        yield cur, ("" if rel == "." else rel), fs

def deps(pkg):
    return {**pkg.get("devDependencies", {}), **pkg.get("dependencies", {})}

def berry():
    pmf = readj(os.path.join(root, "package.json")).get("packageManager", "")
    m = re.match(r"yarn@(\d+)", pmf)
    return os.path.exists(os.path.join(root, ".yarnrc.yml")) or bool(m and int(m.group(1)) >= 2)

def pm_run(pm, d, script):
    if pm == "pnpm":
        return f"pnpm --dir {d} run {script}"
    if pm == "yarn":
        return f"cd {d} && yarn run {script}" if berry() else f"yarn --cwd {d} run {script}"
    if pm == "bun":
        return f"bun --cwd {d} run {script}"
    return f"npm --prefix {d} run {script}"

def pm_root_run(pm, script):
    return {"pnpm": "pnpm run ", "yarn": "yarn run ", "bun": "bun run "}.get(pm, "npm run ") + script

def pm_exec(pm):
    return {"pnpm": "pnpm exec", "yarn": "yarn", "bun": "bunx"}.get(pm, "npx")

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PASSWORDISH = re.compile(r"password|contrase|passwd", re.I)
USER_TITLES = re.compile(r"^(#{1,6})\s*(test users|demo accounts|usuarios de prueba|cuentas de prueba|demo users)\b", re.I)
USER_FILES = ("docs/test-users.md", "docs/local-testing.md", "docs/local-android-testing.md")
ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\r")

def inside(rel):
    """A file of this project: relative, no .., not an .env, symlinks resolved (nothing outside the project)."""
    if not rel or os.path.isabs(rel) or ".." in rel.replace("\\", "/").split("/") or os.path.basename(rel).startswith(".env"):
        return None
    p = os.path.realpath(os.path.join(root, rel))
    return p if p.startswith(os.path.realpath(root) + os.sep) and os.path.isfile(p) else None

PASSWORD_WORDS = re.compile(r"password|passwd|contrase|clave|login|credential", re.I)
ENV_LINE = re.compile(r"^\s*(export\s+)?[A-Z][A-Z0-9_]*=")
SHELL_LINE = re.compile(r"^\s*(\$\s*)?(docker|pnpm|npm|yarn|adb|curl|git|cd|brew|npx|sudo)\b")
LINK_ONLY = re.compile(r"^\s*(\[[^\]]*\]\([^)]*\)|<https?://\S+>|https?://\S+)\s*$")
INSTALL_ROW = re.compile(r"^\s*\|.*`\s*(pnpm|npm|yarn|brew|docker|adb|npx|sdkmanager)\b")
NOTE_START = re.compile(r"^\s*(>|\*|note\b|nota\b|\*\*note|\*\*nota)", re.I)
IDENT = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+|\b(user|username|usuario|login|admin|email)\b", re.I)
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
MAX_LINES = 15

def noise(l):
    """A line that is not an account: an env assignment, a shell command, a link, an install table row."""
    return bool(ENV_LINE.match(l) or SHELL_LINE.match(l) or LINK_ONLY.match(l) or INSTALL_ROW.match(l))

def clean(text):
    return [ANSI.sub("", l).rstrip() for l in text.splitlines()]

def heading_above(lines, i, fallback=""):
    for j in range(i, -1, -1):
        m = HEADING.match(lines[j])
        if m:
            return m.group(2)
    return fallback

def extract(text, fallback_heading="", section=False):
    """The accounts in a text, raw lines, cluster first: the largest run of consecutive lines that carry
    an email (at most one blank line between rows), with its table header, the one or two lines above
    that speak of passwords and a password note right after; otherwise a guess from lines that pair an
    identifier with a password. Returns (lines, how) where how is "" or "guess"; the last line says
    where the rest is when it was cut."""
    lines = clean(text)
    emails = [i for i, l in enumerate(lines) if EMAIL.search(l) and not noise(l)]
    clusters, cur = [], []
    for i in emails:
        if cur and (i == cur[-1] + 1 or (i == cur[-1] + 2 and not lines[cur[-1] + 1].strip())):
            cur.append(i)
        else:
            if cur:
                clusters.append(cur)
            cur = [i]
    if cur:
        clusters.append(cur)
    best = max(clusters, key=len, default=[])  # max keeps the first of equals
    if len(best) >= 2:
        lo, hi = best[0], best[-1]
        while lo > 0 and lines[lo - 1].lstrip().startswith("|") and not noise(lines[lo - 1]):  # the table's header and rule
            lo -= 1
        top, j, above = lo, lo - 1, []
        while j >= 0 and len(above) < 2:
            if not lines[j].strip():
                j -= 1
                continue
            if PASSWORD_WORDS.search(lines[j]) and not noise(lines[j]) and not HEADING.match(lines[j]):
                above.insert(0, j)
                j -= 1
            else:
                break
        chosen = [i for i in range(above[0] if above else lo, hi + 1) if lines[i].strip() and not noise(lines[i])]
        k = hi + 1
        while k < len(lines) and not lines[k].strip() and k <= hi + 1:
            k += 1
        if k < len(lines) and NOTE_START.match(lines[k]) and PASSWORD_WORDS.search(lines[k]) and not noise(lines[k]):
            chosen.append(k)
        out = [lines[i] for i in chosen]
        if len(out) > MAX_LINES:
            out = out[:MAX_LINES] + [f"(more in {{file}} §{heading_above(lines, best[0], fallback_heading)})"]
        return out, ""
    # no cluster of two accounts: lines that pair an identifier with a password, close together
    picks = []
    for i, l in enumerate(lines):
        if noise(l) or not l.strip() or not PASSWORD_WORDS.search(l) or not re.search(r"password|passwd|contrase", l, re.I):
            continue
        for j in range(max(0, i - 3), min(len(lines), i + 4)):
            if IDENT.search(lines[j]) and not noise(lines[j]) and lines[j].strip():
                for x in sorted({i, j}):
                    if x not in picks:
                        picks.append(x)
    picks = sorted(picks)[:5]
    if picks:
        return [lines[i] for i in picks], "guess"
    if section:  # a section titled like test users: a lone account is still the answer
        one = [l for l in lines if EMAIL.search(l) and not noise(l)][:5]
        if one:
            return one, ""
    return [], ""

def raw_lines(text):
    return [l for l in clean(text) if l.strip()][:40]

def users_result(source, lines, how):
    if not lines:
        return None
    src = source + (" (a guess)" if how else "")
    return {"source": src, "accounts": [{"line": l.replace("{file}", source)} for l in lines]}

def from_file(rel, text, raw_ok=True):
    """A whole file: the same extraction as anywhere (a saved users_file may point at a long guide).
    Its own lines are the answer only for a file made for this (raw_ok) and short; a long one, or a
    general guide, with no accounts gives nothing."""
    ls, how = extract(text, rel)
    if ls:
        return users_result(rel, ls, how)
    raw = raw_lines(text)
    return users_result(rel, raw, "") if raw_ok and len([l for l in clean(text) if l.strip()]) <= 40 else None

def find_users(users_file=""):
    """The test accounts the project lists, as raw lines: [local] users_file, then docs the project
    commonly writes them in, a README section, the last seed's log. Never an .env, nothing outside."""
    p = inside(users_file) if users_file else None
    if p and (r := from_file(users_file, reads(p))):
        return r
    for rel in USER_FILES:
        p = inside(rel)
        if p and (r := from_file(rel, reads(p), raw_ok=rel == USER_FILES[0])):
            return r
    p = inside("README.md")
    if p:
        text, level, body, title = reads(p).splitlines(), 0, [], ""
        for l in text:
            m = re.match(r"^(#{1,6})\s", l)
            if level and m and len(m.group(1)) <= level:
                break
            if level:
                body.append(l)
            elif (t := USER_TITLES.match(l)):
                level, title = len(t.group(1)), l.lstrip("# ").strip()
        if body:
            ls, how = extract("\n".join(body), title, section=True)
            if (r := users_result(f"README.md ({title})", ls, how)):
                return r
    p = inside(".local-dev/logs/seed.log")
    if p:
        ls, how = extract(reads(p), "seed.log")
        if (r := users_result(".local-dev/logs/seed.log", ls, how)):
            return r
    return {"source": None, "accounts": []}

def tsv_lines():
    return [l.rstrip("\n").split("\t") for l in sys.stdin if l.strip()]

if mode == "json_doctor":
    rows = tsv_lines()
    rc = next((int(r[1]) for r in rows if r[0] == "exit"), 1)
    print(json.dumps({
        "command": "doctor", "exit": rc, "ok": rc == 0,
        "messages": [{"level": r[1], "text": r[2] if len(r) > 2 else ""} for r in rows if r[0] == "msg"],
        "missing": [{"label": r[1], "command": r[2] if len(r) > 2 else ""} for r in rows if r[0] == "missing"],
        "blockers": [r[1] for r in rows if r[0] == "blocker"]}, indent=2))
    sys.exit()

if mode == "users":
    print(json.dumps(find_users(sys.argv[3] if len(sys.argv) > 3 else ""), indent=2))
    sys.exit()

if mode == "json_status":
    out = {"api": {"configured": False, "up": False, "port": None, "pid": None, "process": None},
           "database": {"services": {}}, "metro": {"up": False, "port": 8081, "pid": None, "process": None},
           "android": {"devices": [], "chosen": None}, "ios": {"booted": [], "chosen": None}, "ports": {},
           "users": find_users(sys.argv[3] if len(sys.argv) > 3 else "")}
    for r in tsv_lines():
        k = r[0]
        if k == "api":
            out["api"] = {"configured": True, "up": r[1] == "up", "port": int(r[2]),
                          "pid": int(r[3]) if r[3] else None, "process": r[4] or None}
        elif k == "db":
            out["database"]["services"][r[1]] = r[2]
        elif k == "metro":
            out["metro"].update(up=r[1] == "up", pid=int(r[2]) if r[2] else None, process=r[3] or None)
        elif k == "android":
            out["android"]["devices"].append({"serial": r[1], "model": r[2], "state": r[3], "kind": r[4]})
        elif k == "android_chosen":
            out["android"]["chosen"] = r[1] or None
        elif k == "ios":
            out["ios"]["booted"].append({"udid": r[1], "name": r[2]})
        elif k == "ios_chosen":
            out["ios"]["chosen"] = r[1] or None
        elif k == "port":
            out["ports"][r[1]] = {"pid": int(r[2]) if r[2] else None, "process": r[3] or None}
    print(json.dumps(out, indent=2))
    sys.exit()

if mode == "stamp":
    # cheap: path, mtime and size of every input the fingerprint reads (no contents)
    d = sys.argv[3] if len(sys.argv) > 3 else "."
    app = os.path.join(root, d)
    files = []
    for base in (root, app):
        for f in ("package.json", "pnpm-lock.yaml", "yarn.lock", "package-lock.json", "bun.lockb", "bun.lock"):
            files.append(os.path.join(base, f))
    if os.path.isdir(app):
        files += [os.path.join(app, f) for f in sorted(os.listdir(app)) if f == "app.json" or f.startswith("app.config.")]
    try:
        files += [os.path.join(root, t.decode()) for t in subprocess.run(
            ["git", "ls-files", "-z", "--", os.path.join(d, "ios"), os.path.join(d, "android")], cwd=root, capture_output=True).stdout.split(b"\0") if t]
    except Exception:
        pass
    h = hashlib.sha256()
    for f in files:
        try:
            st = os.stat(f)
            h.update(f"{f}|{st.st_mtime_ns}|{st.st_size}\n".encode())
        except OSError:
            h.update(f"{f}|-\n".encode())
    print(h.hexdigest()[:24])
    sys.exit()

if mode == "fingerprint":
    # what a native build depends on: dependencies, lockfiles, app config, tracked native folders
    d = sys.argv[3] if len(sys.argv) > 3 else "."
    app = os.path.join(root, d)
    h = hashlib.sha256()
    for base in (root, app):
        pkg = readj(os.path.join(base, "package.json"))
        h.update(json.dumps(deps(pkg), sort_keys=True).encode())
        for lock in ("pnpm-lock.yaml", "yarn.lock", "package-lock.json", "bun.lockb", "bun.lock"):
            h.update(reads(os.path.join(base, lock)).encode() if lock != "bun.lockb" and os.path.exists(os.path.join(base, lock)) else b"")
            if lock == "bun.lockb" and os.path.exists(os.path.join(base, lock)):
                with open(os.path.join(base, lock), "rb") as f:
                    h.update(f.read())
    if os.path.isdir(app):
        for f in sorted(os.listdir(app)):
            if f == "app.json" or f.startswith("app.config."):
                h.update(f.encode() + reads(os.path.join(app, f)).encode())
    try:
        tracked = subprocess.run(["git", "ls-files", "-z", "--", os.path.join(d, "ios"), os.path.join(d, "android")],
                                 cwd=root, capture_output=True).stdout.split(b"\0")
    except Exception:
        tracked = []
    for t in sorted(x for x in tracked if x):
        h.update(t)
        try:
            with open(os.path.join(root, t.decode()), "rb") as f:
                h.update(f.read())
        except Exception:
            pass
    print(h.hexdigest()[:24])
    sys.exit()

if mode == "client":
    d = sys.argv[3]
    pkg = readj(os.path.join(root, d, "package.json"))
    dd = deps(pkg)
    if "expo-dev-client" in dd:
        print("client=dev-client\nreason=expo-dev-client is a dependency")
        sys.exit()
    bundled = None
    for base in (os.path.join(root, d), root):
        b = os.path.join(base, "node_modules", "expo", "bundledNativeModules.json")
        if os.path.exists(b):
            bundled = readj(b)
            break
    if bundled is None:
        print("client=expo-go\nreason=no expo-dev-client, and the dependencies are not installed to compare with Expo Go's modules")
        sys.exit()
    # ponytail: a name pattern, not a native scan; `client = "dev-client"` in [local] forces it
    native = [n for n in dd if re.match(r"^(react-native-|@react-native-|expo-)", n)
              and n not in bundled and n not in ("react-native-web", "expo-dev-client")]
    if native:
        print("client=dev-client\nreason=" + ", ".join(sorted(native)[:3]) + " is native code Expo Go does not include")
    else:
        print("client=expo-go\nreason=every native module is one Expo Go ships")
    sys.exit()

found = []  # Expo apps
for cur, rel, fs in walk():
    pkg = readj(os.path.join(cur, "package.json")) if "package.json" in fs else {}
    cfg = any(f == "app.json" and "expo" in readj(os.path.join(cur, f)) or f.startswith("app.config.") for f in fs)
    if "expo" in deps(pkg) or cfg:
        found.append((rel, cfg))
found.sort(key=lambda x: (not x[1], x[0].count(os.sep), x[0]))
dirs = [r or "." for r, _ in found]
out = {"mobile_dirs": dirs, "uncertain": []}
unc = out["uncertain"]
if not dirs:
    mobile = ""
else:
    mobile = dirs[0]
    if len(dirs) > 1:
        unc.append("mobile_dir")
out["mobile_dir"] = mobile
md = "" if mobile in ("", ".") else mobile

# package manager: the lockfile
pm = ""
for base in ("", md):
    for lock, name in (("pnpm-lock.yaml", "pnpm"), ("bun.lockb", "bun"), ("bun.lock", "bun"), ("yarn.lock", "yarn"), ("package-lock.json", "npm")):
        if not pm and os.path.exists(os.path.join(root, base, lock)):
            pm = name
if not pm:
    pm = (readj(os.path.join(root, "package.json")).get("packageManager", "npm").split("@")[0]) or "npm"
    unc.append("pm")
out["pm"] = pm
out["runner"] = next((r for r, f in (("turbo", "turbo.json"), ("nx", "nx.json"), ("lerna", "lerna.json")) if os.path.exists(os.path.join(root, f))), "")

# the app's identity: android package, iOS bundle id, URL scheme, JDK, Node
pkgname, bundle, scheme = "", "", ""
app = os.path.join(root, md)
mpkg = readj(os.path.join(app, "package.json")) if mobile else {}
if mobile:
    aj = readj(os.path.join(app, "app.json")).get("expo", {})
    pkgname = aj.get("android", {}).get("package", "")
    bundle = aj.get("ios", {}).get("bundleIdentifier", "")
    sc = aj.get("scheme", "")
    scheme = sc if isinstance(sc, str) else (sc[0] if sc else "")
    for f in sorted(os.listdir(app)):
        if f.startswith("app.config."):
            t = reads(os.path.join(app, f))
            if not pkgname:
                m = re.search(r"android\s*:\s*\{[^}]*?package\s*:\s*['\"]([\w.]+)['\"]", t, re.S) or re.search(r"package\s*:\s*['\"]([\w.]+)['\"]", t)
                pkgname = m.group(1) if m else ""
            if not bundle:
                m = re.search(r"bundleIdentifier\s*:\s*['\"]([\w.]+)['\"]", t)
                bundle = m.group(1) if m else ""
            if not scheme:
                m = re.search(r"\bscheme\s*:\s*['\"]([\w.+-]+)['\"]", t)
                scheme = m.group(1) if m else ""
    if not pkgname:
        unc.append("android_package")
out["android_package"] = pkgname
out["ios_bundle"] = bundle
out["scheme"] = scheme

# JDK by React Native (then Expo SDK): RN 0.73 and later need 17; 0.71 and 0.72 run on 11
jdk = "17"
rn = re.search(r"(\d+)\.(\d+)", str(deps(mpkg).get("react-native", "")))
sdk = re.search(r"(\d+)", str(deps(mpkg).get("expo", "")))
if rn:
    jdk = "17" if (int(rn.group(1)), int(rn.group(2))) >= (0, 73) else "11"
elif sdk:
    jdk = "17" if int(sdk.group(1)) >= 50 else "11"
out["jdk"] = jdk

# Node: .nvmrc, .node-version, then engines.node (its first number)
node = ""
for f in (".nvmrc", ".node-version"):
    m = re.match(r"v?(\d+)", reads(os.path.join(root, f)).strip())
    if m and not node:
        node = m.group(1)
if not node:
    for p in (os.path.join(root, "package.json"), os.path.join(app, "package.json")):
        m = re.search(r"(\d+)", str(readj(p).get("engines", {}).get("node", "")))
        if m and not node:
            node = m.group(1)
out["node"] = node

# the database service (postgres) and the other services of the compose file
db, services = "", []
for f in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"):
    p = os.path.join(root, f)
    if not os.path.exists(p):
        continue
    svc, cur, ins = {}, None, False
    for line in reads(p).splitlines():
        if re.match(r"^services:\s*$", line):
            ins = True
            continue
        if re.match(r"^\S", line) and not line.startswith("#"):
            ins = False
        m = re.match(r"^  ([\w.-]+):\s*$", line) if ins else None
        if m:
            cur = m.group(1)
            svc[cur] = []
        elif cur and ins:
            svc[cur].append(line)
    for name, body in svc.items():
        if re.search(r"image:\s*\S*(postgres|postgis)", "\n".join(body)):
            db = name
            break
    db = db or next((n for n in svc if n in ("db", "postgres", "database")), "")
    # what else the app needs running: the services that are an image, not the project's own build
    for name, body in svc.items():
        if name == db:
            continue
        if re.search(r"(?m)^\s+build:", "\n".join(body)):
            if name not in ("api", "backend", "server", "web", "app"):
                unc.append("services")
            continue
        services.append(name)
    break
out["db_service"] = db
out["services"] = services

# the backend: a folder whose package.json is a Nest/Express/Fastify server, with prisma if possible
cands = []
for cur, rel, fs in walk():
    if "package.json" not in fs or not rel:
        continue
    dd = deps(readj(os.path.join(cur, "package.json")))
    if rel in dirs or "expo" in dd:
        continue
    if any(k in dd for k in ("@nestjs/core", "express", "fastify")):
        cands.append((("prisma" not in dd and not os.path.isdir(os.path.join(cur, "prisma"))), rel.count(os.sep), rel))
cands.sort()
api = cands[0][2] if cands else ""
if len(cands) > 1 and cands[0][0] == cands[1][0]:
    unc.append("api_dir")
out["api_dir"] = api
out["api_port"] = "3000"
out["api_start"] = out["api_ready_url"] = out["api_migrate"] = out["api_seed"] = ""
if api:
    ap = os.path.join(root, api)
    apkg = readj(os.path.join(ap, "package.json"))
    scripts = apkg.get("scripts", {})
    rs = readj(os.path.join(root, "package.json")).get("scripts", {})
    aname = apkg.get("name", "")
    root_script = next((s for s in ("dev:api", "api:dev", "start:api", "dev:backend", "dev:server") if s in rs), "")
    own = next((k for k in ("dev", "start:dev", "start") if k in scripts), "")
    runner = out["runner"]
    if root_script:
        out["api_start"] = pm_root_run(pm, root_script)
    elif runner == "turbo" and aname:
        out["api_start"] = f"{pm_exec(pm)} turbo run {own or 'dev'} --filter={aname}"
    elif runner == "lerna" and aname:
        out["api_start"] = f"{pm_exec(pm)} lerna run {own or 'dev'} --scope {aname} --stream"
    elif runner == "nx" and aname:
        out["api_start"] = f"{pm_exec(pm)} nx run {aname}:{own or 'serve'}"
        unc.append("api_start")
    elif own:
        out["api_start"] = pm_run(pm, api, own)
    else:
        unc.append("api_start")
    # a fresh checkout has no Prisma client: the API does not compile until it is generated
    if "prisma:migrate:deploy" in scripts:
        gen = pm_run(pm, api, "prisma:generate") + " && " if "prisma:generate" in scripts else f"cd {api} && npx prisma generate && "
        out["api_migrate"] = gen + pm_run(pm, api, "prisma:migrate:deploy")
    elif os.path.isdir(os.path.join(ap, "prisma")):
        out["api_migrate"] = f"cd {api} && npx prisma generate && npx prisma migrate deploy"
    # a seed script: offered, never run silently
    seed = next((s for s in ("db:seed", "seed", "seed:demo", "prisma:seed") if s in scripts), "")
    if seed:
        out["api_seed"] = pm_run(pm, api, seed)
    elif apkg.get("prisma", {}).get("seed") or any(os.path.exists(os.path.join(ap, "prisma", "seed" + e)) for e in (".ts", ".js", ".mjs")):
        out["api_seed"] = f"cd {api} && npx prisma db seed"
    m = re.search(r"(?m)^PORT=(\d+)", reads(os.path.join(ap, ".env.example")))
    if m:
        out["api_port"] = m.group(1)

# the app's API url: the EXPO_PUBLIC_*URL variable the app reads, and the path its default carries
name, suffix = "", ""
if mobile:
    texts = []
    for cur, ds, fs in os.walk(app):
        ds[:] = [x for x in ds if x not in SKIP and not x.startswith(".")]
        for f in fs:
            if f.endswith((".ts", ".tsx", ".js", ".jsx", ".json", ".example", ".mjs")) or f == ".env":
                p = os.path.join(cur, f)
                if os.path.getsize(p) < 500000:
                    texts.append(reads(p))
    allt = "\n".join(texts)
    counts = {}
    for n in re.findall(r"EXPO_PUBLIC_[A-Z0-9_]*URL", allt):
        counts[n] = counts.get(n, 0) + 1
    if counts:
        name = max(sorted(counts), key=lambda k: counts[k])
        m = re.search(name + r"[\"']?\s*[:=]\s*[\"']?https?://[^/\s\"']+(/[^\s\"'\\]*)", allt)
        suffix = m.group(1).rstrip("/") if m else ""
    else:
        name = "EXPO_PUBLIC_API_URL"
        unc.append("api_url_env")
out["api_url_env"] = name
out["api_url_suffix"] = suffix
if api and out["api_port"]:
    health = any(re.search(r"health", reads(os.path.join(c, f)), re.I)
                 for c, _, fs in os.walk(os.path.join(root, api, "src")) for f in fs if f.endswith((".ts", ".js")))
    if health:
        out["api_ready_url"] = f"http://localhost:{out['api_port']}/health"
        if suffix:
            unc.append("api_ready_url")
out["client"] = "auto"
out["android_target"] = "ask"
out["users_file"] = USER_FILES[0] if inside(USER_FILES[0]) else ""  # only a file made for it: guides stay search fallbacks, never saved

if mode == "json":
    print(json.dumps(out, indent=2))
else:
    for k, v in out.items():
        print(f"{k}={','.join(v) if isinstance(v, list) else v}")
PY

detect_py() { python3 -c "$DETECT_PY" "$PWD" "$@"; } # <kv|json|client|fingerprint|stamp|users|json_doctor|json_status> [mobile_dir]

load_detect() {
  [ "$DETECTED" = 1 ] && return
  DETECTED=1
  command -v python3 >/dev/null || return
  local k v
  while IFS='=' read -r k v; do eval "DET_$k=\$v"; done < <(detect_py kv 2>/dev/null)
}

cfg() { # <key>: [local]'s value (even empty), else the detected one
  local r
  r=$(toml_get "$PROFILE" local "$1")
  if [ -n "$r" ]; then printf '%s' "${r#=}"; else eval "printf '%s' \"\${DET_$1:-}\""; fi
}

cfg_list() { cfg "$1" | tr -d '[]"'"'" | tr ',' ' ' | tr -s ' '; } # ["a", "b"] or a,b → a b

load_config() {
  grep -q '^\[local\]' "$PROFILE" 2>/dev/null && HAS_LOCAL=1
  load_detect
  MOBILE_DIR=$(cfg mobile_dir)
  [ "$MOBILE_DIR" = . ] && MOBILE_DIR=
  PM=$(cfg pm)
  ANDROID_PKG=$(cfg android_package)
  IOS_BUNDLE=$(cfg ios_bundle)
  SCHEME=$(cfg scheme)
  API_DIR=$(cfg api_dir)
  API_START=$(cfg api_start)
  API_READY=$(cfg api_ready_url)
  API_MIGRATE=$(cfg api_migrate)
  API_SEED=$(cfg api_seed)
  DB_SERVICE=$(cfg db_service)
  SERVICES=$(cfg_list services)
  API_PORT=$(cfg api_port)
  API_URL_ENV=$(cfg api_url_env)
  API_URL_SUFFIX=$(cfg api_url_suffix)
  CLIENT=$(cfg client)
  JDK=$(cfg jdk)
  NODE_WANT=$(cfg node | tr -cd '0-9' | cut -c1-3)
  ANDROID_TARGET=$(cfg android_target)
  AVD_CFG=$(cfg avd)
  [ -n "$API_PORT" ] || API_PORT=3000
  [ -n "$CLIENT" ] || CLIENT=auto
  [ -n "$JDK" ] || JDK=17
  [ -n "$ANDROID_TARGET" ] || ANDROID_TARGET=ask
  USERS_FILE=$(toml_get "$PROFILE" local users_file) # only what the project wrote: the detected suggestion is searched in order, filtered
  USERS_FILE=${USERS_FILE#=}
  [ "$EMULATOR_FLAG" = 1 ] && ANDROID_TARGET=emulator
  [ "$PHONE_FLAG" = 1 ] && ANDROID_TARGET=phone
  return 0
}

has_expo_app() { # the folder holds an Expo app
  local d=${MOBILE_DIR:-.}
  [ -f "$d/app.json" ] || ls "$d"/app.config.* >/dev/null 2>&1 || grep -q '"expo"' "$d/package.json" 2>/dev/null
}

compose_file() { ls docker-compose.yml docker-compose.yaml compose.yml compose.yaml 2>/dev/null | head -1; }

# Coherence of [local], on any OS: what RUN-1 asks of the project. Prints problems, returns 1 on any.
check_config() {
  local n=0
  if [ "$HAS_LOCAL" = 0 ]; then
    if [ -z "${DET_mobile_dir:-}" ] && ! has_expo_app; then
      ok "$(L 'no Expo app here: nothing to run' 'no hay app Expo: no hay nada que lanzar')"
      return 0
    fi
    bad "$(L "an Expo app is in ${DET_mobile_dir:-.} but .keelokit/profile.toml has no [local] block: run /keelokit:run-local, or: bash .keelokit/bin/run-local.sh doctor" "hay una app Expo en ${DET_mobile_dir:-.} pero .keelokit/profile.toml no tiene el bloque [local]: corré /keelokit:run-local, o: bash .keelokit/bin/run-local.sh doctor")"
    return 1
  fi
  has_expo_app || { bad "$(L "mobile_dir \"$MOBILE_DIR\" has no Expo app (app.json, app.config.* or expo in package.json)" "mobile_dir \"$MOBILE_DIR\" no tiene una app Expo (app.json, app.config.* o expo en package.json)")"; n=1; }
  case "$PM" in pnpm | npm | yarn | bun) ;; *) bad "$(L "pm \"$PM\" is not pnpm, npm, yarn or bun" "pm \"$PM\" no es pnpm, npm, yarn ni bun")"; n=1 ;; esac
  case "$ANDROID_TARGET" in auto | phone | emulator | ask) ;; *) bad "$(L "android_target \"$ANDROID_TARGET\" is not auto, phone, emulator or ask" "android_target \"$ANDROID_TARGET\" no es auto, phone, emulator ni ask")"; n=1 ;; esac
  case "$CLIENT" in auto | expo-go | dev-client) ;; *) bad "$(L "client \"$CLIENT\" is not auto, expo-go or dev-client" "client \"$CLIENT\" no es auto, expo-go ni dev-client")"; n=1 ;; esac
  if [ -n "$API_DIR" ] && [ ! -d "$API_DIR" ]; then bad "$(L "api_dir \"$API_DIR\" does not exist" "api_dir \"$API_DIR\" no existe")"; n=1; fi
  if [ -n "$DB_SERVICE$SERVICES" ] && [ -z "$(compose_file)" ]; then
    bad "$(L "db_service/services are set but there is no docker compose file" "db_service/services están puestos pero no hay un archivo de docker compose")"; n=1
  fi
  if [ -n "$API_DIR" ] && [ -z "$API_START" ]; then bad "$(L 'api_dir is set but api_start is empty' 'api_dir está puesto pero api_start está vacío')"; n=1; fi
  [ "$n" = 0 ] && ok "$(L "[local] is coherent (Expo app in ${MOBILE_DIR:-.}, $PM)" "[local] es coherente (app Expo en ${MOBILE_DIR:-.}, $PM)")"
  return "$n"
}

# [local] is missing: show what the repo says, ask about what is not certain, save once.
setup_local() {
  load_detect
  command -v python3 >/dev/null || { bad "$(L 'python3 is needed to look for the Expo app' 'hace falta python3 para buscar la app Expo')"; return 1; }
  local dirs k cur ans d i
  dirs=${DET_mobile_dirs:-}
  if [ -z "$dirs" ]; then
    ok "$(L 'no Expo app found: nothing to run here' 'no encontré una app Expo: no hay nada que lanzar acá')"
    return 2
  fi
  say "$(L 'Settings found in the repo (not saved yet)' 'Lo que encontré en el repo (todavía sin guardar)')"
  if [ "${DET_mobile_dirs#*,}" != "$DET_mobile_dirs" ]; then
    warn "$(L 'More than one Expo app:' 'Hay más de una app Expo:')"
    i=0
    for d in $(tr ',' ' ' <<<"$dirs"); do i=$((i + 1)); printf '  %d) %s\n' "$i" "$d"; done
    if [ "$YES" = 0 ]; then
      ask ans "  $(L 'Which one? [1] ' '¿Cuál? [1] ') " || return 1
      DET_mobile_dir=$(tr ',' '\n' <<<"$dirs" | sed -n "${ans:-1}p")
      [ -n "$DET_mobile_dir" ] || return 1
    fi
  fi
  for k in mobile_dir pm android_package api_dir api_start api_ready_url api_migrate api_seed db_service services api_port api_url_env api_url_suffix jdk node; do
    eval "cur=\${DET_$k:-}"
    printf '  %-16s %s\n' "$k" "${cur:-—}"
  done
  for k in $(tr ',' ' ' <<<"${DET_uncertain:-}"); do
    [ "$k" = mobile_dir ] && continue
    eval "cur=\${DET_$k:-}"
    warn "$(L "not certain: $k" "no estoy seguro: $k")"
    if [ "$YES" = 0 ]; then
      ask ans "  $k [$cur]: " || return 1
      [ -n "$ans" ] && eval "DET_$k=\$ans"
    fi
  done
  confirm "$(L 'Save this as [local] in .keelokit/profile.toml?' '¿Guardo esto como [local] en .keelokit/profile.toml?')" || return 1
  [ -f "$PROFILE" ] || { bad "$(L 'there is no .keelokit/profile.toml' 'no existe .keelokit/profile.toml')"; return 1; }
  {
    [ -n "$(tail -c1 "$PROFILE")" ] && echo
    echo
    echo '[local]'
    for k in mobile_dir android_package ios_bundle scheme pm api_dir api_start api_ready_url api_migrate api_seed db_service services api_port api_url_env api_url_suffix client android_target users_file jdk node; do
      eval "cur=\${DET_$k:-}"
      case $k in
        api_port) [ -n "$cur" ] || cur=3000 ;;
        client) cur=auto ;;
        android_target) cur=ask ;;
        ios_bundle | scheme | node | users_file) [ -n "$cur" ] || continue ;;
      esac
      if [ "$k" = api_port ] || [ "$k" = jdk ]; then printf '%s = %s\n' "$k" "$cur"
      elif [ "$k" = services ]; then
        printf 'services = ['
        d=""
        for i in $(tr ',' ' ' <<<"$cur"); do printf '%s"%s"' "$d" "$i"; d=", "; done
        printf ']\n'
      elif [[ $cur == *\"* ]]; then printf "%s = '%s'\n" "$k" "$cur"
      else printf '%s = "%s"\n' "$k" "$cur"; fi
    done
  } >>"$PROFILE"
  HAS_LOCAL=1
  ok "$(L '[local] saved. Correct by hand whatever is wrong.' '[local] guardado. Corregí a mano lo que esté mal.')"
  load_config
}

# ---------- environment ----------

# Node: the version the project wants. A matching one from nvm is used for this run only; the
# shell and the default Node are never switched. Installing one (nvm or brew) is a question in the
# diagnosis.
node_min() { echo "${NODE_WANT:-18}"; }
node_major() { node -v 2>/dev/null | sed -n 's/^v\([0-9][0-9]*\).*/\1/p'; }

use_nvm_node() {
  local want have
  want=$(node_min)
  have=$(node_major)
  [ -s "$HOME/.nvm/nvm.sh" ] || return 0
  if [ -z "$have" ] || [ "$have" -lt "$want" ] 2>/dev/null; then
    # shellcheck disable=SC1091
    . "$HOME/.nvm/nvm.sh" >/dev/null 2>&1
    if command -v nvm >/dev/null 2>&1 && nvm use "$want" >/dev/null 2>&1; then
      ok "$(L "Node $want from nvm, for this run only (your shell keeps its own)" "Node $want de nvm, solo para esta corrida (tu shell conserva el suyo)")"
    fi
  fi
}

setup_env() {
  export LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 # CocoaPods dies on a non-UTF-8 locale
  # Every worktree uses the main checkout's compose project, so they share the database you already have.
  MAIN=$PWD
  if git rev-parse --git-common-dir >/dev/null 2>&1; then MAIN=$(cd "$(git rev-parse --git-common-dir)/.." && pwd); fi
  export COMPOSE_PROJECT_NAME
  COMPOSE_PROJECT_NAME=$(basename "$MAIN" | tr 'A-Z' 'a-z' | tr -cd 'a-z0-9_-')
  export ANDROID_HOME="${ANDROID_HOME:-$HOME/Library/Android/sdk}" ANDROID_SDK_ROOT="$ANDROID_HOME"
  local jh brewtools
  jh=$("${JAVA_HOME_BIN:-/usr/libexec/java_home}" -v "$JDK" 2>/dev/null) && export JAVA_HOME=$jh
  brewtools="$(brew --prefix 2>/dev/null)/share/android-commandlinetools/cmdline-tools/latest/bin"
  PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$ANDROID_HOME/cmdline-tools/latest/bin:$brewtools:$PATH"
  use_nvm_node
}

# The first write into .local-dev/: asks once when git would otherwise see it.
init_state() {
  [ -d "$LOG" ] && return 0
  if [ ! -d "$STATE" ] && git rev-parse --git-dir >/dev/null 2>&1 && ! git check-ignore -q "$STATE/x"; then
    confirm "$(L "Create $STATE/ (logs, last-error.txt) and add it to .gitignore?" "¿Creo $STATE/ (logs, last-error.txt) y lo agrego a .gitignore?")" || return 1
    { [ -f .gitignore ] && [ -n "$(tail -c1 .gitignore)" ] && echo; echo "$STATE/"; } >>.gitignore
  fi
  mkdir -p "$LOG"
}

# .local-dev/state: one line per target, "<android|ios>|<device id>|<fingerprint>|<app version>".
state_get() { awk -F'|' -v t="$1" -v i="$2" '$1==t && $2==i {print $3 "|" $4; exit}' "$STATE/state" 2>/dev/null; }
state_clear() {
  [ -f "$STATE/state" ] || return 0
  awk -F'|' -v t="$1" -v i="$2" '!($1==t && $2==i)' "$STATE/state" >"$STATE/state.tmp" && mv "$STATE/state.tmp" "$STATE/state"
}
state_set() { # <target> <id> <fingerprint> <version>
  init_state || return 1
  state_clear "$1" "$2"
  echo "$1|$2|$3|$4" >>"$STATE/state"
}

# ---------- running things, logging, repairs ----------

record_error() { # <step> <exit code> <log>
  init_state >/dev/null 2>&1
  {
    echo "step: $1   exit: $2   $(date '+%F %T')"
    echo "branch: $(git branch --show-current 2>/dev/null)   node: $(node -v 2>&1)   java: $(java -version 2>&1 | head -1)"
    echo "---- last 60 lines of $3 ----"
    perl -pe 's/\e\[[0-9;?]*[a-zA-Z]//g; s/\r//g' "$3" | tail -60
  } >"$STATE/last-error.txt"
  bad "$(L "step «$1» failed (code $2). Log: $3" "falló «$1» (código $2). Log: $3")"
  bad "$(L "Summary to hand to Claude: $STATE/last-error.txt" "Resumen para pasarle a Claude: $STATE/last-error.txt")"
}

run() { # <step> <command...>: logged, output still shown
  local step=$1 rc
  shift
  init_state || return 1
  "$@" 2>&1 | tee "$LOG/$step.log"
  rc=${PIPESTATUS[0]}
  [ "$rc" = 0 ] || record_error "$step" "$rc" "$LOG/$step.log"
  return "$rc"
}

free_port() { # <port>: never kills anything without asking
  local pids
  pids=$(lsof -ti "tcp:$1" -sTCP:LISTEN 2>/dev/null) || return 0
  warn "$(L "port $1 is used by: $(ps -o comm= -p "${pids%%$'\n'*}")" "el puerto $1 lo usa: $(ps -o comm= -p "${pids%%$'\n'*}")")"
  confirm "$(L 'Close it?' '¿Lo cierro?')" || return 1
  # shellcheck disable=SC2086
  kill $pids 2>/dev/null
  sleep 1
}

repair_uninstall_app() {
  [ -n "$ANDROID_PKG" ] && [ -n "$A_SERIAL" ] || return 2
  warn "$(L 'the installed app is signed differently' 'la app instalada está firmada distinto')"
  confirm "$(L "Uninstall $ANDROID_PKG from the phone?" "¿Desinstalo $ANDROID_PKG del teléfono?")" || return 1
  adb -s "$A_SERIAL" uninstall "$ANDROID_PKG" >/dev/null
}
repair_free_metro_port() { free_port 8081; }
repair_gradle_memory() {
  local props=${MOBILE_DIR:-.}/android/gradle.properties
  warn "$(L 'Gradle ran out of memory: 4 GB for it, and its daemon restarts' 'Gradle se quedó sin memoria: le doy 4 GB y reinicio su daemon')"
  [ -f "$props" ] && sed -i '' 's/^org.gradle.jvmargs=.*/org.gradle.jvmargs=-Xmx4096m -XX:MaxMetaspaceSize=1g/' "$props"
  (cd "${MOBILE_DIR:-.}/android" && ./gradlew --stop >/dev/null 2>&1)
  return 0
}
repair_pod_reinstall() {
  warn "$(L 'CocoaPods: updating its index and reinstalling the pods' 'CocoaPods: actualizo su índice y reinstalo los pods')"
  (cd "${MOBILE_DIR:-.}/ios" && pod install --repo-update)
}
repair_google_file() {
  warn "$(L 'a Google services file the app points to is missing: it is a secret of the project, put it where app.json says' 'falta un archivo de servicios de Google al que apunta la app: es un secreto del proyecto, ponelo donde dice app.json')"
  return 1
}
repair_free_emulator_port() { free_port 5554; }
repair_avd_lock() { # stale lock files of the AVD: removed only with a yes
  local locks="" f
  for f in "$HOME/.android/avd/${AVD_NAME:-}".avd/*.lock; do [ -e "$f" ] && locks="$locks $f"; done
  [ -n "$locks" ] || return 2
  warn "$(L "the emulator left lock files:$locks" "el emulador dejó archivos de bloqueo:$locks")"
  confirm "$(L 'Delete them? (make sure no emulator is using this AVD)' '¿Los borro? (fijate que ningún emulador use este AVD)')" || return 1
  for f in $locks; do rm -rf -- "$f"; done
}
# The app does not fit: an install needs several times the size of the APK. Four ways out, each
# only with its own yes; with --yes none is picked and the script stops (exit 3) listing them.
repair_insufficient_storage() {
  warn "$(L "there is not enough free storage on ${A_SERIAL:-the target} to install the app (an install needs several times the size of the APK)." "no hay espacio libre suficiente en ${A_SERIAL:-el target} para instalar la app (instalar necesita varias veces el tamaño del APK).")"
  if [ "$YES" = 1 ]; then
    BLOCKED=1
    warn "$(L 'Options (none is picked for you): uninstall the app and retry · create a new emulator with a bigger data partition: run-local.sh android --new-avd · cold boot this emulator with -wipe-data (ERASES all its apps and data): run it without --yes.' 'Opciones (no elijo ninguna por vos): desinstalar la app y reintentar · crear un emulador nuevo con una partición de datos más grande: run-local.sh android --new-avd · arranque en frío de este emulador con -wipe-data (BORRA todas sus apps y datos): corrélo sin --yes.')"
    return 1
  fi
  if [ -n "$ANDROID_PKG" ] && [ -n "$A_SERIAL" ] &&
    confirm "$(L "Uninstall $ANDROID_PKG from ${A_SERIAL} and try again? (it frees some space; it may not be enough)" "¿Desinstalo $ANDROID_PKG de ${A_SERIAL} y reintento? (libera algo de espacio; puede no alcanzar)")"; then
    adb -s "$A_SERIAL" uninstall "$ANDROID_PKG" >/dev/null
    return 0
  fi
  warn "$(L '`pm trim-caches` usually frees nothing here, so it is not offered.' '`pm trim-caches` casi nunca libera nada acá, así que no lo ofrezco.')"
  if [ "${A_KIND:-}" = emulator ]; then
    if confirm "$(L 'Create a NEW emulator with an 8 GB data partition? (an image that is already installed is reused: no download)' '¿Creo un emulador NUEVO con una partición de datos de 8 GB? (una imagen ya instalada se reutiliza: sin descarga)')" && create_avd; then
      remember avd "$AVD_NAME"
      ok "$(L "created $AVD_NAME. Stop the running emulator (run-local.sh stop) and run android --emulator again." "creado $AVD_NAME. Detené el emulador que corre (run-local.sh stop) y corré android --emulator de nuevo.")"
      return 1
    fi
    if [ -n "${AVD_NAME:-}" ] && confirm "$(L "Cold boot $AVD_NAME with -wipe-data? This ERASES ALL its apps and data." "¿Arranque en frío de $AVD_NAME con -wipe-data? Esto BORRA TODAS sus apps y datos.")"; then
      adb -s "$A_SERIAL" emu kill >/dev/null 2>&1
      sleep 5
      EMU_EXTRA=-wipe-data
      boot_emulator "$AVD_NAME"
      local rc=$?
      EMU_EXTRA=
      return "$rc"
    fi
  fi
  return 1
}
repair_no_acceleration() {
  warn "$(L 'the emulator has no hardware acceleration (HVF on macOS needs a supported CPU and no other hypervisor holding it). Close other virtual machines, or use a phone.' 'el emulador no tiene aceleración por hardware (HVF en macOS necesita una CPU compatible y ningún otro hipervisor que la use). Cerrá otras máquinas virtuales, o usá un teléfono.')"
  return 1
}

# Known causes of a failed build, repaired in place. Returns 0 when it changed something, so the
# step is worth running again; 1 when the failure is unknown (it stays in last-error.txt).
repair() { # <log>
  local entry rc
  for entry in "${REPAIRS[@]}"; do
    grep -qE "${entry%% => *}" "$1" || continue
    "repair_${entry##* => }" "$1"
    rc=$?
    [ "$rc" = 2 ] && continue
    return "$rc"
  done
  return 1
}

# An interactive step (Metro keeps running in it): `script` keeps the terminal live and logs it.
# Ctrl+C is a normal stop, not a failure.
# Did a launch fail? Ctrl+C (130) is a normal stop. A failure marker in the log counts when the exit
# code is not 0, and also with 0 when Metro never said it was ready (`script` can hide the code of
# what ran inside it: an install that failed after the build looked like a stop).
LAUNCH_MARKERS='BUILD FAILED|FAILURE:|error:|CommandError|INSTALL_FAILED_[A-Z_]+|exited with non-zero code'
launch_failed() { # <rc> <log>
  [ "$1" = 130 ] && return 1
  grep -qiE "$LAUNCH_MARKERS" "$2" || return 1
  [ "$1" != 0 ] && return 0
  ! grep -qE 'Logs for your project|Metro waiting on|Waiting on http' "$2"
}

# Expo asks "Install the recommended Expo Go?" when the one on the simulator or phone is not the SDK's.
# With no terminal that prompt is cancelled and Expo exits: a failure that only a person can resolve.
expo_go_prompt_cancelled() { # <log>
  grep -q 'Install the recommended Expo Go' "$1" && ! grep -q 'Logs for your project' "$1"
}

# Runs the command under `script` (the terminal stays live and the output is logged). When stdin is
# not a terminal (Claude, CI, a background run) Expo reads EOF and shuts Metro down, so the command
# gets a stdin that never ends: a fifo held open by a sleeping writer, with the one `y` for Expo Go's
# prompt first when feed is 1. The writer is stopped when the command ends, and on TERM or HUP.
FEEDER_PIDFILE=
stop_feeder() {
  local pid
  if [ -n "$FEEDER_PIDFILE" ]; then
    pid=$(cat "$FEEDER_PIDFILE" 2>/dev/null)
    # killed from another shell so this one prints no "Terminated" job report
    [ -n "$pid" ] && sh -c 'kill "$1"' _ "$pid" 2>/dev/null
    rm -f "$FEEDER_PIDFILE"
  fi
  FEEDER_PIDFILE=
  return 0
}
trap 'stop_feeder' EXIT
trap 'stop_feeder; exit 143' TERM HUP

# A pipe, not a FIFO: BSD `script` on macOS fails with "tcgetattr/ioctl: Operation not supported" when
# its stdin is a FIFO. The writer keeps the pipe open and records its pid so it can be stopped. It is
# a process substitution, not a `|`: a pipeline would make this shell wait for the writer too.
script_run() { # <log> <feed y: 1|0> <command...>
  local log=$1 feed=$2 rc
  shift 2
  if [ -t 0 ] && [ "$feed" != 1 ]; then
    script -q "$log" "$@"
    return $?
  fi
  FEEDER_PIDFILE=$(mktemp "${TMPDIR:-/tmp}/run-local.XXXXXX") || return 1
  script -q "$log" "$@" < <(sh -c 'echo $$ >"$1"; [ "$2" = 1 ] && printf "y\n"; exec sleep 2147483647' _ "$FEEDER_PIDFILE" "$feed")
  rc=$?
  stop_feeder
  return "$rc"
}

# Metro that ended by itself: nobody pressed Ctrl+C (130) and there was no terminal to do it on. Expo
# says "Stopping server" when it is shut down from outside (an EOF on stdin, a signal).
metro_exited_on_its_own() { # <rc> <log> <seconds it ran>
  [ -t 0 ] && return 1
  [ "$1" = 130 ] && return 1
  grep -qE 'Stopping server|Stopped server' "$2" && return 0
  [ "$3" -lt "${RUN_LOCAL_QUICK:-10}" ]
}

launch() { # <step> <command...>
  local step=$1 attempt=1 rc feed=${FEED_Y:-0} started
  FEED_Y=0
  shift
  init_state || return 1
  show_users
  while :; do
    : >"$LOG/$step.log"
    started=$SECONDS
    script_run "$LOG/$step.log" "$feed" "$@"
    rc=$?
    if [ "$rc" != 130 ] && expo_go_prompt_cancelled "$LOG/$step.log"; then
      record_error "$step" "$rc" "$LOG/$step.log"
      bad "$(L 'Expo asked to install or update Expo Go and nobody could answer. Run it in a terminal and answer Y, or add --yes (it downloads Expo Go from Expo and installs it on the target).' 'Expo preguntó si instalar o actualizar Expo Go y nadie pudo responder. Corrélo en una terminal y respondé Y, o agregá --yes (descarga Expo Go de Expo y lo instala en el target).')"
      BLOCKED=1
      return 1
    fi
    if ! launch_failed "$rc" "$LOG/$step.log"; then
      if metro_exited_on_its_own "$rc" "$LOG/$step.log" $((SECONDS - started)); then
        bad "$(L "Metro exited on its own (nobody pressed Ctrl+C, and there was no terminal). The app is installed but has no Metro. Log: $LOG/$step.log" "Metro terminó solo (nadie apretó Ctrl+C y no había terminal). La app quedó instalada pero sin Metro. Log: $LOG/$step.log")"
        return 1
      fi
      ok "$(L 'stopped' 'detenido')"
      return 0
    fi
    record_error "$step" "$rc" "$LOG/$step.log"
    [ "$attempt" -ge 2 ] && return 1
    repair "$LOG/$step.log" || return 1
    attempt=$((attempt + 1))
    warn "$(L 'repaired; launching again' 'reparado; lo lanzo de nuevo')"
  done
}

in_dir() { bash -c 'cd "$1" && shift && exec "$@"' _ "$@"; } # in_dir <dir> <command...>

expo() { # runs the project's expo CLI inside the app folder
  case "$PM" in
    pnpm) in_dir "${MOBILE_DIR:-.}" pnpm exec expo "$@" ;;
    yarn) in_dir "${MOBILE_DIR:-.}" yarn expo "$@" ;;
    bun) in_dir "${MOBILE_DIR:-.}" bunx expo "$@" ;;
    *) in_dir "${MOBILE_DIR:-.}" npx expo "$@" ;;
  esac
}

# ---------- diagnosis ----------

is_berry() { [ -f .yarnrc.yml ] || grep -q '"packageManager"[ ]*:[ ]*"yarn@[2-9]' package.json 2>/dev/null; }

deps_fresh() {
  case "$PM" in
    pnpm) [ -d node_modules/.pnpm ] && [ node_modules/.modules.yaml -nt pnpm-lock.yaml ] ;;
    yarn)
      if is_berry; then [ -f .yarn/install-state.gz ] && [ .yarn/install-state.gz -nt yarn.lock ]
      else [ -f node_modules/.yarn-integrity ] && [ node_modules/.yarn-integrity -nt yarn.lock ]; fi ;;
    bun) [ -d node_modules ] && { [ node_modules -nt bun.lockb ] || [ node_modules -nt bun.lock ]; } ;;
    *) [ -f node_modules/.package-lock.json ] && [ node_modules/.package-lock.json -nt package-lock.json ] ;;
  esac
}

check_base() {
  local min have
  min=$(node_min)
  have=$(node_major)
  if [ -n "$have" ] && [ "$have" -ge "$min" ]; then
    ok "Node v$(node -v | sed 's/^v//')"
  elif [ -s "$HOME/.nvm/nvm.sh" ]; then
    need "Node $min $(L '(through nvm; your default Node is not changed)' '(con nvm; tu Node por defecto no cambia)')" '. "$HOME/.nvm/nvm.sh" && nvm install '"$min"
  else need "Node $min" "brew install node@$min && brew link --overwrite --force node@$min"; fi
  if command -v python3 >/dev/null; then ok "Python $(python3 -V 2>&1 | cut -d' ' -f2)"; else need "Python 3" "brew install python"; fi
  case "$PM" in
    pnpm) if command -v pnpm >/dev/null; then ok "pnpm $(pnpm -v)"; else need "pnpm" "corepack enable"; fi ;;
    yarn) if command -v yarn >/dev/null; then ok "yarn $(yarn -v)"; else need "yarn" "corepack enable"; fi ;;
    bun) if command -v bun >/dev/null; then ok "bun $(bun -v)"; else need "bun" "brew install oven-sh/bun/bun"; fi ;;
    *) command -v npm >/dev/null && ok "npm $(npm -v)" ;;
  esac
  if [ -n "$DB_SERVICE$SERVICES" ]; then
    if command -v docker >/dev/null; then ok "$(L 'Docker installed' 'Docker instalado')"
    else need "Docker Desktop" "brew install --cask docker"; fi
    if docker info >/dev/null 2>&1; then ok "$(L 'Docker running' 'Docker corriendo')"
    else need "$(L 'Docker Desktop open' 'Docker Desktop abierto')" "start_docker"; fi
  fi
  if deps_fresh; then ok "$(L 'dependencies' 'dependencias')"
  else
    case "$PM" in
      pnpm) need "$(L 'dependencies (pnpm install)' 'dependencias (pnpm install)')" "pnpm install --frozen-lockfile" ;;
      yarn) if is_berry; then need "$(L 'dependencies (yarn install)' 'dependencias (yarn install)')" "yarn install --immutable"
        else need "$(L 'dependencies (yarn install)' 'dependencias (yarn install)')" "yarn install --frozen-lockfile"; fi ;;
      bun) need "$(L 'dependencies (bun install)' 'dependencias (bun install)')" "bun install --frozen-lockfile" ;;
      *) need "$(L 'dependencies (npm ci)' 'dependencias (npm ci)')" "npm ci" ;;
    esac
  fi
  if [ -n "$API_DIR" ]; then
    if [ -f "$API_DIR/.env" ]; then ok "$API_DIR/.env"
    else need "$API_DIR/.env $(L 'with local values' 'con valores locales')" "write_api_env"; fi
  fi
}

# JDK: [local] jdk, else from React Native (0.73 and later: 17; 0.71–0.72: 11) or the Expo SDK (50 and later: 17).
check_android() {
  if [ -n "$JAVA_HOME" ]; then ok "JDK $JDK"; else need "JDK $JDK" "brew install --cask zulu@$JDK"; fi
  if command -v adb >/dev/null; then ok "adb"
  else
    command -v sdkmanager >/dev/null || need "Android command-line tools" "brew install --cask android-commandlinetools"
    need "Android platform-tools (adb)" 'setup_env; yes | sdkmanager --sdk_root="$ANDROID_HOME" platform-tools'
  fi
  # Gradle downloads the platform, build-tools and NDK itself once the licences are accepted.
  if [ -f "$ANDROID_HOME/licenses/android-sdk-license" ]; then ok "$(L 'Android SDK licences' 'licencias del SDK de Android')"
  else need "$(L 'Android SDK licences' 'licencias del SDK de Android')" 'setup_env; yes | sdkmanager --sdk_root="$ANDROID_HOME" --licenses'; fi
}

check_emulator() {
  if [ -n "$(emulator_bin)" ]; then ok "$(L 'Android emulator' 'emulador de Android')"
  else need "$(L 'Android emulator (about 400 MB)' 'emulador de Android (unos 400 MB)')" 'setup_env; sdkmanager --sdk_root="$ANDROID_HOME" emulator'; fi
}

check_ios() {
  if ! xcodebuild -version >/dev/null 2>&1; then
    block "$(L 'Xcode is not installed: get it from the App Store and open it once' 'Xcode no está instalado: instalalo desde la App Store y abrilo una vez')"
    return
  fi
  ok "$(xcodebuild -version | head -1)"
  xcodebuild -checkFirstLaunchStatus >/dev/null 2>&1 || need "$(L 'finish the Xcode setup (asks for your password)' 'terminar la configuración de Xcode (pide tu contraseña)')" "sudo xcodebuild -runFirstLaunch"
  xcrun simctl list devices available | grep -q iPhone || block "$(L 'Xcode has no iPhone simulator: Xcode → Settings → Components' 'Xcode no tiene un simulador de iPhone: Xcode → Settings → Components')"
  if command -v pod >/dev/null; then ok "CocoaPods"; else need "CocoaPods" "brew install cocoapods"; fi
}

# Diagnose, show everything missing at once, install after one yes, then diagnose again.
ensure() { # <check_x...>
  local pass i t
  for pass in 1 2; do
    PLAN_D=() PLAN_C=() BLOCKERS=() MISSING=()
    QUIET=$((pass - 1))
    setup_env
    [ "$pass" = 1 ] && say "$(L 'Diagnosis' 'Diagnóstico')"
    for t in "$@"; do
      declare -F "check_$t" >/dev/null || { bad "ensure: there is no function check_$t (a bug in run-local.sh)"; return 1; }
    done
    for t in "$@"; do "check_$t"; done
    if [ ${#BLOCKERS[@]} -gt 0 ]; then bad "$(L 'I cannot install that; fix it and run again.' 'Eso no lo puedo instalar yo; resolvelo y volvé a correr.')"; return 1; fi
    [ ${#PLAN_C[@]} -eq 0 ] && return 0
    if [ "$NOINSTALL" = 1 ]; then return 1; fi
    if [ "$pass" = 2 ]; then
      for i in "${!PLAN_D[@]}"; do [[ ${PLAN_D[$i]} == \?* ]] || { bad "$(L 'still missing:' 'sigue faltando:') ${PLAN_D[$i]}"; return 1; }; done
      return 0
    fi
    say "$(L 'I am going to install/configure:' 'Voy a instalar/configurar:')"
    for i in "${!PLAN_D[@]}"; do printf '  • %s\n' "${PLAN_D[$i]#\?}"; done
    if printf '%s ' "${PLAN_C[@]}" | grep -q 'brew ' && ! command -v brew >/dev/null; then
      bad "$(L 'Homebrew is missing: https://brew.sh' 'Falta Homebrew: https://brew.sh')"
      return 1
    fi
    confirm "$(L 'Go on?' '¿Sigo?')" || return 1
    for i in "${!PLAN_D[@]}"; do
      say "${PLAN_D[$i]#\?}"
      run "fix-$i" eval "${PLAN_C[$i]}" || [[ ${PLAN_D[$i]} == \?* ]] || return 1
    done
  done
}

start_docker() {
  open -a Docker
  local _
  for _ in $(seq 60); do docker info >/dev/null 2>&1 && return 0; sleep 3; done
  return 1
}

# The API's .env: a main checkout's own one wins when this is a worktree (your keys, your DB port);
# otherwise a copy of .env.example. Without either, you are asked to make it.
write_api_env() {
  if [ "$MAIN" != "$PWD" ] && [ -f "$MAIN/$API_DIR/.env" ]; then cp "$MAIN/$API_DIR/.env" "$API_DIR/.env"; return; fi
  if [ -f "$API_DIR/.env.example" ]; then
    cp "$API_DIR/.env.example" "$API_DIR/.env"
    git check-ignore -q "$API_DIR/.env" 2>/dev/null || warn "$(L "$API_DIR/.env is not in .gitignore: add it before committing" "$API_DIR/.env no está en .gitignore: agregalo antes de commitear")"
    return
  fi
  echo "$(L "no $API_DIR/.env.example to copy: create $API_DIR/.env with the API's local values" "no hay $API_DIR/.env.example para copiar: creá $API_DIR/.env con los valores locales de la API")" >&2
  return 1
}

# ---------- backend ----------

compose_args() { COMPOSE_ENV=(); [ -f "$MAIN/.env" ] && COMPOSE_ENV=(--env-file "$MAIN/.env"); [ -f "$STATE/compose.env" ] && COMPOSE_ENV=(--env-file "$STATE/compose.env"); return 0; }

api_up() { # the API answers (below 500) at its ready url, or listens on its port
  local code
  if [ -n "$API_READY" ]; then
    code=$(curl -s -o /dev/null -w '%{http_code}' "$API_READY" 2>/dev/null)
    [ -n "$code" ] && [ "$code" != 000 ] && [ "$code" -lt 500 ]
  else
    lsof -ti "tcp:$API_PORT" -sTCP:LISTEN >/dev/null 2>&1
  fi
}

# Another database on the port this one needs: ask before moving to a free one.
db_port() { # <env-file args...>
  local port pids new
  port=$(sed -n 's/^POSTGRES_PORT=//p' "$STATE/compose.env" "$MAIN/.env" 2>/dev/null | head -1)
  port=${POSTGRES_PORT:-${port:-5432}}
  pids=$(lsof -ti "tcp:$port" -sTCP:LISTEN 2>/dev/null) || return 0
  [ -n "$pids" ] || return 0
  docker compose "$@" ps --status running -q "$DB_SERVICE" 2>/dev/null | grep -q . && return 0
  warn "$(L "port $port is used by $(ps -o comm= -p "${pids%%$'\n'*}"), not by this project's database" "el puerto $port lo usa $(ps -o comm= -p "${pids%%$'\n'*}"), no la base de este proyecto")"
  if ! grep -qs POSTGRES_PORT docker-compose.y*ml compose.y*ml; then
    bad "$(L 'the compose file does not read POSTGRES_PORT: free the port, or make it configurable' 'el compose no lee POSTGRES_PORT: liberá el puerto, o hacelo configurable')"
    return 1
  fi
  confirm "$(L 'Use another port for this database?' '¿Uso otro puerto para esta base?')" || return 1
  new=$((port + 1))
  while lsof -ti "tcp:$new" -sTCP:LISTEN >/dev/null 2>&1; do new=$((new + 1)); done
  init_state || return 1
  echo "POSTGRES_PORT=$new" >"$STATE/compose.env"
  [ -f "$API_DIR/.env" ] && sed -i '' "s#@localhost:$port/#@localhost:$new/#" "$API_DIR/.env"
  ok "$(L "database on port $new" "base en el puerto $new")"
}

# Is the database empty? Best effort, through the compose service's own psql (estimated live rows in
# the app's tables, the migrations table left out). Prints empty, data or unknown.
db_state() {
  local n sql="select coalesce(sum(n_live_tup),0)::bigint from pg_stat_user_tables where relname <> '_prisma_migrations'"
  [ -n "$DB_SERVICE" ] && command -v docker >/dev/null || { echo unknown; return; }
  compose_args
  n=$(docker compose "${COMPOSE_ENV[@]}" exec -T "$DB_SERVICE" sh -c 'psql -U "$POSTGRES_USER" -d "${POSTGRES_DB:-$POSTGRES_USER}" -tAc "$1"' _ "$sql" 2>/dev/null | tr -d ' \r\n')
  case "$n" in '' | *[!0-9]*) echo unknown ;; 0) echo empty ;; *) echo data ;; esac
}

# The seed writes to the database: it needs its own yes, every time, and never happens silently.
# `--seed` (or the `seed` command, which asks unless --yes) is the yes; --yes alone never seeds.
run_seed() { # <forced: 1 when asked for by name>
  [ -n "$API_SEED" ] || { warn "$(L 'no seed in [local] (api_seed is empty)' 'no hay seed en [local] (api_seed está vacío)')"; return 0; }
  if [ "$SEED_FLAG" != 1 ]; then
    confirm "$(L "Run the seed ($API_SEED)? It writes to your local database." "¿Corro el seed ($API_SEED)? Escribe en tu base local.")" || return 0
  fi
  run seed bash -c "$API_SEED" || return 1
  USERS_SHOWN=0
  show_users
}

# Before launching: "Load the seed data?" at a terminal, recommending it when the database looks empty.
# The answer is the next default (.local-dev/seed_default: yes or no). Without a terminal, or with
# --yes alone, it is not run: the script says how.
seed_step() {
  [ -n "$API_SEED" ] || return 0
  if [ "$NOSEED_FLAG" = 1 ]; then ok "$(L 'seed skipped (--no-seed)' 'seed omitido (--no-seed)')"; return 0; fi
  if [ "$SEED_FLAG" = 1 ]; then run_seed 1; return; fi
  if [ "$YES" = 1 ] || ! interactive; then
    warn "$(L "seed not run: it writes to the database, so it needs a yes at a terminal. To load it: --seed, or: run-local.sh seed" "seed no corrido: escribe en la base, así que necesita un sí en una terminal. Para cargarlo: --seed, o: run-local.sh seed")"
    return 0
  fi
  local state def last ans
  state=$(db_state)
  case "$state" in
    empty) say "$(L 'The database looks empty: loading the seed data is recommended.' 'La base parece vacía: se recomienda cargar el seed.')"; def=y ;;
    data) warn "$(L 'The database already has data: you probably do not need the seed.' 'La base ya tiene datos: probablemente no necesitás el seed.')"; def=n ;;
    *) warn "$(L "I can't tell if the database already has data." 'No puedo saber si la base ya tiene datos.')"; def=n ;;
  esac
  last=$(cat "$STATE/seed_default" 2>/dev/null)
  case "$last" in yes) def=y ;; no) def=n ;; esac
  if [ "$def" = y ]; then ask ans "  $(L 'Load the seed data? [Y/n] ' '¿Cargo el seed? [S/n] ')" || return 1
  else ask ans "  $(L 'Load the seed data? [y/N] ' '¿Cargo el seed? [s/N] ')" || return 1; fi
  if [ -z "$ans" ]; then ans=$def; fi
  if [[ $ans =~ ^[sSyY] ]]; then
    remember seed_default yes
    SEED_FLAG=1
    run_seed 1
    return
  fi
  remember seed_default no
  return 0
}

start_backend() {
  [ -n "$API_DIR" ] || { warn "$(L 'no backend in [local] (api_dir is empty)' 'no hay backend en [local] (api_dir está vacío)')"; return 0; }
  say "$(L 'Database and API' 'Base de datos y API')"
  init_state || return 1
  local _
  compose_args
  if [ -n "$DB_SERVICE$SERVICES" ]; then
    [ -n "$DB_SERVICE" ] && { db_port "${COMPOSE_ENV[@]}" || return 1; }
    compose_args
    # only what [local] names: a compose file may also define the API itself
    # shellcheck disable=SC2086
    run db docker compose "${COMPOSE_ENV[@]}" up -d --wait $DB_SERVICE $SERVICES || return 1
  fi
  [ -n "$API_MIGRATE" ] && { run migrate bash -c "$API_MIGRATE" || return 1; }
  seed_step || return 1
  if api_up; then ok "$(L "API already running on port $API_PORT" "API ya corriendo en el puerto $API_PORT")"; return 0; fi
  init_state || return 1
  nohup bash -c "$API_START" >"$LOG/api.log" 2>&1 &
  for _ in $(seq 90); do # the first build takes a while
    api_up && { ok "$(L "API on port $API_PORT (log: $LOG/api.log)" "API en el puerto $API_PORT (log: $LOG/api.log)")"; return 0; }
    sleep 2
  done
  record_error api 1 "$LOG/api.log"
  return 1
}

stop_backend() {
  say "$(L 'Stop the API, the containers and the emulator' 'Detener API, contenedores y emulador')"
  setup_env
  # a watcher respawns its child: stop the listener's parents (pnpm, nest...) first
  local pid chain p serial
  pid=$(lsof -ti "tcp:$API_PORT" -sTCP:LISTEN 2>/dev/null | head -1)
  if [ -n "$pid" ]; then
    warn "$(L "port $API_PORT is used by: $(ps -o comm= -p "$pid")" "el puerto $API_PORT lo usa: $(ps -o comm= -p "$pid")")"
    if confirm "$(L 'Stop it?' '¿La detengo?')"; then
      chain=$pid
      p=$pid
      while p=$(ps -o ppid= -p "$p" | tr -d ' ') && ps -o command= -p "$p" | grep -qE 'node|pnpm|npm|yarn|bun|nest|tsx'; do chain="$p $chain"; done
      # shellcheck disable=SC2086
      kill $chain 2>/dev/null && ok "$(L 'API stopped' 'API detenida')"
    fi
  fi
  if [ -n "$DB_SERVICE$SERVICES" ] && confirm "$(L "Stop the containers ($DB_SERVICE $SERVICES)? (the data stays)" "¿Detengo los contenedores ($DB_SERVICE $SERVICES)? (los datos se conservan)")"; then
    compose_args
    # shellcheck disable=SC2086
    docker compose "${COMPOSE_ENV[@]}" stop $DB_SERVICE $SERVICES >/dev/null 2>&1 && ok "$(L "stopped (the data stays)" "detenidos (los datos se conservan)")"
  fi
  serial=$(adb_list 2>/dev/null | awk -F'|' '$4=="emulator" {print $1; exit}')
  if [ -n "$serial" ] && confirm "$(L "Shut the emulator down ($serial)?" "¿Apago el emulador ($serial)?")"; then
    adb -s "$serial" emu kill >/dev/null 2>&1 && ok "$(L 'emulator stopped' 'emulador apagado')"
  fi
}

# ---------- status, logs, clean ----------

owner() { # <port>: "pid<TAB>process" of whoever listens on it, or two empty fields
  local pid
  pid=$(lsof -ti "tcp:$1" -sTCP:LISTEN 2>/dev/null | head -1)
  if [ -n "$pid" ]; then printf '%s\t%s' "$pid" "$(ps -o comm= -p "$pid" 2>/dev/null | sed 's#.*/##')"; else printf '\t'; fi
}

status_facts() { # tab-separated lines (see json_status in detect_py)
  local pid proc svc up p running dbp o
  if [ -n "$API_DIR" ]; then
    o=$(owner "$API_PORT")
    if api_up; then up=up; else up=down; fi
    printf 'api\t%s\t%s\t%s\n' "$up" "$API_PORT" "$o"
  fi
  if [ -n "$DB_SERVICE$SERVICES" ]; then
    compose_args
    running=$(docker compose "${COMPOSE_ENV[@]}" ps --status running --services 2>/dev/null)
    for svc in $DB_SERVICE $SERVICES; do
      if ! command -v docker >/dev/null || ! docker info >/dev/null 2>&1; then printf 'db\t%s\tunknown\n' "$svc"
      elif grep -qx "$svc" <<<"$running"; then printf 'db\t%s\trunning\n' "$svc"
      else printf 'db\t%s\tstopped\n' "$svc"; fi
    done
  fi
  o=$(owner 8081)
  if [ "$o" != $'\t' ]; then printf 'metro\tup\t%s\n' "$o"; else printf 'metro\tdown\t\t\n'; fi
  if command -v adb >/dev/null; then
    adb_list | while IFS='|' read -r s m st k; do printf 'android\t%s\t%s\t%s\t%s\n' "$s" "$m" "$st" "$k"; done
  fi
  printf 'android_chosen\t%s\n' "$(cat "$STATE/android-device" 2>/dev/null)"
  if command -v xcrun >/dev/null; then
    xcrun simctl list devices booted 2>/dev/null | sed -nE 's/^ +(.*[^ (]) \(([0-9A-F-]{36})\) \(Booted\).*/\2|\1/p' | while IFS='|' read -r u n; do printf 'ios\t%s\t%s\n' "$u" "$n"; done
  fi
  printf 'ios_chosen\t%s\n' "$(cat "$STATE/ios-device" 2>/dev/null)"
  dbp=$(sed -n 's/^POSTGRES_PORT=//p' "$STATE/compose.env" "$MAIN/.env" 2>/dev/null | head -1)
  for p in "$API_PORT" 8081 5554 "${POSTGRES_PORT:-${dbp:-5432}}"; do
    o=$(owner "$p")
    [ "$o" != $'\t' ] && printf 'port\t%s\t%s\n' "$p" "$o"
  done
  return 0
}

cmd_status() {
  setup_env
  local facts
  facts=$(status_facts)
  if [ "$JSONMODE" = 1 ]; then printf '%s\n' "$facts" | detect_py json_status "$USERS_FILE"; return 0; fi
  say "$(L 'What is running' 'Qué está corriendo')"
  local k a b c d e
  while IFS=$'\037' read -r k a b c d e; do
    case "$k" in
      api) ok "API: $a (port $b)${d:+ · $d (pid $c)}" ;;
      db) ok "$(L 'container' 'contenedor') $a: $b" ;;
      metro) ok "Metro: $a${c:+ · $c (pid $b)}" ;;
      android) ok "Android: $a ($b) $c · $d" ;;
      ios) ok "iOS: $b ($a) booted" ;;
      port) ok "$(L 'port' 'puerto') $a: $c (pid $b)" ;;
    esac
  done < <(tr '\t' '\037' <<<"$facts")
  return 0
}

# The test accounts the project's own docs or seed list. Printed, never stored.
cmd_users() {
  command -v python3 >/dev/null || { echo "python3 is needed" >&2; return 1; }
  if [ "$JSONMODE" = 1 ]; then detect_py users "$USERS_FILE"; return 0; fi
  local out src
  out=$(detect_py users "$USERS_FILE")
  src=$(printf '%s' "$out" | python3 -c 'import json,sys; print(json.load(sys.stdin)["source"] or "")')
  if [ -z "$src" ]; then
    say "$(L 'Test users' 'Usuarios de prueba')"
    [ -n "$USERS_FILE" ] && warn "$(L "no accounts found in $USERS_FILE" "no encontré cuentas en $USERS_FILE")"
    warn "$(L 'No test users found. Put them in a file of the project (a markdown or text list) and name it: users_file = "docs/test-users.md" in [local]. I also look in docs/test-users.md, docs/local-testing.md, a README section called Test users, and the last seed log.' 'No encontré usuarios de prueba. Ponelos en un archivo del proyecto (una lista en markdown o texto) y nombralo: users_file = "docs/test-users.md" en [local]. También miro docs/test-users.md, docs/local-testing.md, una sección del README llamada Usuarios de prueba y el log del último seed.')"
    return 0
  fi
  say "$(L "Test users (from $src)" "Usuarios de prueba (de $src)")"
  printf '%s' "$out" | python3 -c 'import json,sys; [print("  " + a["line"]) for a in json.load(sys.stdin)["accounts"]]'
}

# A short block when a launch starts and after the seed: up to 15 lines, or one line pointing at `users`.
show_users() {
  [ "$USERS_SHOWN" = 1 ] && return 0
  USERS_SHOWN=1
  [ "$JSONMODE" = 1 ] && return 0
  command -v python3 >/dev/null || return 0
  local out n
  out=$(detect_py users "$USERS_FILE" 2>/dev/null)
  n=$(printf '%s' "$out" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["accounts"]))' 2>/dev/null)
  if [ "${n:-0}" = 0 ]; then
    ok "$(L 'Test users: none found. See them, or how to add them: bash .keelokit/bin/run-local.sh users' 'Usuarios de prueba: no encontré. Verlos, o cómo agregarlos: bash .keelokit/bin/run-local.sh users')"
    return 0
  fi
  say "$(L 'Test users' 'Usuarios de prueba') ($(printf '%s' "$out" | python3 -c 'import json,sys; print(json.load(sys.stdin)["source"])'))"
  printf '%s' "$out" | python3 -c 'import json,sys; [print("  " + a["line"]) for a in json.load(sys.stdin)["accounts"][:16]]'
  [ "$n" -gt 16 ] && echo "  … $(L "$((n - 16)) more: bash .keelokit/bin/run-local.sh users" "$((n - 16)) más: bash .keelokit/bin/run-local.sh users")"
  return 0
}

cmd_logs() { # [step]
  [ -d "$LOG" ] || { echo "$(L "no logs yet ($LOG)" "todavía no hay logs ($LOG)")" >&2; return 1; }
  local f n=0
  if [ -n "$ARG2" ]; then
    f=$LOG/$ARG2.log
    [ -f "$f" ] || { echo "$(L "no log for \"$ARG2\" in $LOG: $(ls "$LOG" | sed 's/\.log$//' | tr '\n' ' ')" "no hay log de \"$ARG2\" en $LOG: $(ls "$LOG" | sed 's/\.log$//' | tr '\n' ' ')")" >&2; return 1; }
    perl -pe 's/\e\[[0-9;?]*[a-zA-Z]//g; s/\r//g' "$f" | tail -100
    return 0
  fi
  for f in $(ls -t "$LOG"/*.log 2>/dev/null); do
    n=$((n + 1))
    [ "$n" -gt 3 ] && break
    printf '\n==> %s (%s)\n' "$f" "$(date -r "$f" '+%F %T' 2>/dev/null)"
    perl -pe 's/\e\[[0-9;?]*[a-zA-Z]//g; s/\r//g' "$f" | tail -15
  done
  [ "$n" -gt 0 ] || { echo "$(L 'no logs yet' 'todavía no hay logs')" >&2; return 1; }
  return 0
}

tracked_by_git() { # a path git tracks (or a folder that is not a repo: it cannot be told, so it counts as tracked)
  git rev-parse --git-dir >/dev/null 2>&1 || return 0
  [ -n "$(git ls-files -- "$1" 2>/dev/null | head -1)" ]
}

inside_project() { # the path, symlinks resolved, is under this folder
  local d
  d=$(cd "$(dirname "$1")" 2>/dev/null && pwd -P) || return 1
  case "$d/" in "$(pwd -P)"/*) return 0 ;; *) return 1 ;; esac
}

clean_group() { # <label> <paths...>: lists what goes and its size, asks, deletes the safe ones
  local label=$1 p list=""
  shift
  for p in "$@"; do
    [ -e "$p" ] || continue
    [ -L "$p" ] && continue
    if tracked_by_git "$p"; then warn "$(L "kept, git tracks it: $p" "se queda, git lo versiona: $p")"; continue; fi
    list="$list$p"$'\n'
  done
  [ -n "$list" ] || return 0
  say "$label"
  while IFS= read -r p; do [ -n "$p" ] && printf '  %8s  %s\n' "$(du -sh "$p" 2>/dev/null | cut -f1)" "$p"; done <<<"$list"
  confirm "$(L 'Delete these?' '¿Los borro?')" || { warn "$(L 'kept' 'se quedan')"; return 0; }
  while IFS= read -r p; do
    [ -n "$p" ] || continue
    inside_project "$p" && rm -rf -- "$p" && ok "$(L "deleted: $p" "borrado: $p")"
  done <<<"$list"
}

cmd_clean() {
  local m=${MOBILE_DIR:-.} d name list="" w
  clean_group "$(L 'Build caches (Gradle, Pods, build outputs)' 'Cachés de compilación (Gradle, Pods, salidas de build)')" \
    "$m/android/.gradle" "$m/android/build" "$m/android/app/build" "$m/android/app/.cxx" "$m/ios/Pods" "$m/ios/build"
  # Xcode DerivedData of this project: only folders whose info.plist names this folder
  for d in "$HOME"/Library/Developer/Xcode/DerivedData/*/; do
    [ -f "${d}info.plist" ] && grep -qF "$(pwd -P)/" "${d}info.plist" && list="$list${d%/}"$'\n'
  done
  if [ -n "$list" ]; then
    say "$(L 'Xcode DerivedData of this project' 'DerivedData de Xcode de este proyecto')"
    while IFS= read -r d; do [ -n "$d" ] && printf '  %8s  %s\n' "$(du -sh "$d" 2>/dev/null | cut -f1)" "$d"; done <<<"$list"
    if confirm "$(L 'Delete these?' '¿Los borro?')"; then
      while IFS= read -r d; do
        # outside the project by nature: only a folder under DerivedData whose plist matched
        case "$d" in "$HOME"/Library/Developer/Xcode/DerivedData/?*) [ -L "$d" ] || rm -rf -- "$d" ;; esac
      done <<<"$list"
      ok "$(L 'DerivedData deleted' 'DerivedData borrado')"
    fi
  fi
  clean_group "$(L 'Generated native folders (the next build regenerates them: 10–20 min)' 'Carpetas nativas generadas (el próximo build las regenera: 10–20 min)')" "$m/android" "$m/ios"
  if [ -d "$LOG" ]; then
    list=""
    for w in "$LOG"/*.log "$STATE/last-error.txt"; do [ -f "$w" ] && list="$list$w"$'\n'; done
    if [ -n "$list" ]; then
      say "$(L 'Logs in .local-dev' 'Logs en .local-dev')"
      while IFS= read -r w; do [ -n "$w" ] && printf '  %8s  %s\n' "$(du -sh "$w" | cut -f1)" "$w"; done <<<"$list"
      if confirm "$(L 'Delete these?' '¿Los borro?')"; then
        while IFS= read -r w; do [ -n "$w" ] && inside_project "$w" && rm -f -- "$w"; done <<<"$list"
        ok "$(L 'logs deleted' 'logs borrados')"
      fi
    fi
  fi
  return 0
}

# ---------- targets ----------

api_url() { # the API address the app is built with: localhost, which adb reverse carries to the phone
  local v=${!API_URL_ENV:-}
  echo "${v:-http://localhost:$API_PORT$API_URL_SUFFIX}"
}

choose_client() { # sets USE_CLIENT: expo-go or dev-client, and says why
  local out reason
  USE_CLIENT=$CLIENT
  if [ "$CLIENT" = auto ]; then
    out=$(detect_py client "${MOBILE_DIR:-.}")
    USE_CLIENT=$(sed -n 's/^client=//p' <<<"$out")
    reason=$(sed -n 's/^reason=//p' <<<"$out")
    ok "$(L "app client: $USE_CLIENT ($reason; to force one: client = in [local])" "cliente de la app: $USE_CLIENT ($reason; para forzar uno: client = en [local])")"
  else
    ok "$(L "app client: $USE_CLIENT (set in [local])" "cliente de la app: $USE_CLIENT (fijado en [local])")"
  fi
}

# ----- Android devices: phones (USB or Wi-Fi) and emulators -----

adb_list() { # "serial|model|state|kind" for every attached device; kind is phone or emulator
  adb devices -l 2>/dev/null | awk '
    $2 ~ /^(device|unauthorized|offline)$/ {
      model=""; for (i = 3; i <= NF; i++) if ($i ~ /^model:/) model = substr($i, 7)
      print $1 "|" model "|" $2 "|" (($1 ~ /^emulator-/) ? "emulator" : "phone") }'
}

# Which kind of target to use, from what is attached. One target at a time, and an emulator is
# never booted while a phone is there to use.
android_plan() { # <auto|phone|emulator> <phones ready> <emulators ready>
  case "$1" in
    emulator) if [ "$3" -gt 0 ]; then echo emulator-running; else echo emulator-start; fi ;;
    phone) if [ "$2" -gt 0 ]; then echo phone; else echo no-phone; fi ;;
    *) if [ "$2" -ge 1 ]; then echo phone; elif [ "$3" -ge 1 ]; then echo emulator-running; else echo offer-emulator; fi ;;
  esac
}

pair_android() {
  setup_env
  command -v adb >/dev/null || { bad "$(L 'adb is missing: run `doctor` first' 'falta adb: corré `doctor` primero')"; BLOCKED=1; return 1; }
  say "$(L 'Wireless debugging' 'Depuración inalámbrica')"
  echo "  $(L 'On the phone (same Wi-Fi as this Mac): Settings → Developer options → Wireless debugging → on,' 'En el teléfono (misma Wi-Fi que esta Mac): Ajustes → Opciones de desarrollador → Depuración inalámbrica → activada,')"
  echo "  $(L 'then "Pair device with pairing code": it shows an address and a code.' 'luego «Vincular dispositivo con código»: muestra una dirección y un código.')"
  local addr conn
  ask addr "  $(L 'Pairing address (ip:port): ' 'Dirección de vinculación (ip:puerto): ')" || return 1
  [[ $addr =~ ^[A-Za-z0-9._:-]+$ ]] || { bad "$(L 'that is not an address' 'eso no es una dirección')"; return 1; }
  echo "  $(L 'adb will ask you for the code; it is not kept anywhere.' 'adb te va a pedir el código; no se guarda en ningún lado.')"
  adb pair "$addr" || { bad "$(L 'pairing failed' 'falló la vinculación')"; return 1; }
  ask conn "  $(L 'Connect address (ip:port on the main Wireless debugging screen, not the pairing one): ' 'Dirección de conexión (ip:puerto de la pantalla principal de Depuración inalámbrica, no la de vinculación): ')" || return 1
  [[ $conn =~ ^[A-Za-z0-9._:-]+$ ]] || { bad "$(L 'that is not an address' 'eso no es una dirección')"; return 1; }
  adb connect "$conn" || return 1
  adb devices -l
}

remember() { # <file in .local-dev> <value>
  init_state && echo "$2" >"$STATE/$1"
}

pick_phone() { # <phones: "serial|model|state|kind" lines>; sets A_SERIAL, A_MODEL, A_ID, A_DEVNAME
  local phones=$1 n i choice l last="" line=""
  n=$(grep -c . <<<"$phones")
  if [ -n "$DEVICE" ]; then
    line=$(awk -F'|' -v d="$DEVICE" '$1==d || $2==d {print; exit}' <<<"$phones")
    [ -n "$line" ] || { block "$(L "no connected phone is \"$DEVICE\" (serial or model)" "ningún teléfono conectado es \"$DEVICE\" (serial o modelo)")"; return 1; }
  elif [ "$n" -eq 1 ]; then
    line=$phones
  else
    [ -f "$STATE/android-device" ] && last=$(cat "$STATE/android-device")
    [ -n "$last" ] && line=$(awk -F'|' -v d="$last" '$1==d {print; exit}' <<<"$phones")
    if [ -n "$line" ]; then
      ok "$(L "phone from last time (to change it: --device, or rm $STATE/android-device)" "teléfono de la vez pasada (para cambiarlo: --device, o rm $STATE/android-device)")"
    elif [ "$YES" = 1 ]; then # never waits: the first one, and it says so
      line=$(sed -n 1p <<<"$phones")
      warn "$(L "several phones; --yes took the first (${line%%|*}). To choose: --device <serial|model>" "hay varios teléfonos; --yes tomó el primero (${line%%|*}). Para elegir: --device <serial|modelo>")"
    else
      i=0
      while read -r l; do i=$((i + 1)); printf '  %d) %s\n' "$i" "${l//|/  }"; done <<<"$phones"
      ask choice "  $(L 'Which one? [1] ' '¿Cuál? [1] ')" || return 1
      [[ ${choice:-1} =~ ^[0-9]+$ ]] || choice=1
      line=$(sed -n "${choice:-1}p" <<<"$phones")
      [ -n "$line" ] || line=$(sed -n 1p <<<"$phones")
      remember android-device "${line%%|*}"
    fi
  fi
  A_SERIAL=${line%%|*}
  A_MODEL=$(awk -F'|' '{print $2}' <<<"$line")
  A_ID=$A_SERIAL
  A_DEVNAME=$A_MODEL
  ok "$(L "phone: $A_MODEL ($A_SERIAL)" "teléfono: $A_MODEL ($A_SERIAL)")"
}

# ----- the emulator -----

emulator_bin() {
  if command -v emulator >/dev/null 2>&1; then command -v emulator
  elif [ -x "$ANDROID_HOME/emulator/emulator" ]; then echo "$ANDROID_HOME/emulator/emulator"; fi
}

avd_abi() { # Intel: x86_64. Apple Silicon: arm64-v8a (an x86 shell under Rosetta reports x86_64: use a native one)
  case "$(uname -m)" in arm64 | aarch64) echo arm64-v8a ;; *) echo x86_64 ;; esac
}

avd_api() { # compileSdk of the generated android/ (build.gradle), else 34
  local g=${MOBILE_DIR:-.}/android/build.gradle v=""
  [ -f "$g" ] && v=$(sed -n 's/.*compileSdk\(Version\)\{0,1\}[ =]*\([0-9][0-9]*\).*/\2/p' "$g" | head -1)
  echo "${v:-34}"
}

avd_package() { echo "system-images;android-$(avd_api);google_apis_playstore;$(avd_abi)"; } # a Google Play image

avd_create_cmd() { # <name> <package>: how the AVD is created ("no" answers the hardware-profile question)
  printf 'echo no | avdmanager create avd -n "%s" -k "%s" -d pixel' "$1" "$2"
}

avd_list() { emulator_bin >/dev/null || return 0; "$(emulator_bin)" -list-avds 2>/dev/null | grep -E '^[A-Za-z0-9_.-]+$'; }

# Shuts down the emulator that runs another AVD (one target at a time), only with a yes.
emulator_running_name() { # <serial>
  adb -s "$1" emu avd name 2>/dev/null | head -1 | tr -d '\r'
}

avd_set_data_size() { # <avd> <size>: disk.dataPartition.size in the AVD's config.ini (an install needs room)
  local f="$HOME/.android/avd/$1.avd/config.ini"
  [ -f "$f" ] || return 0
  awk -v v="disk.dataPartition.size=$2" 'BEGIN{d=0} /^disk\.dataPartition\.size[ ]*=/ {print v; d=1; next} {print} END{if(!d) print v}' "$f" >"$f.tmp" && mv "$f.tmp" "$f"
}

create_avd() { # downloads a system image (1–2 GB) only after showing it and getting a yes; sets AVD_NAME
  local pkg name base n=1
  pkg=$(avd_package)
  base="RunLocal_API_$(avd_api)"
  name=$base
  while avd_list | grep -qx "$name"; do n=$((n + 1)); name="${base}_$n"; done
  if ! sdkmanager --list_installed 2>/dev/null | grep -qF "$pkg"; then
    warn "$(L "I can create the emulator \"$name\" with the Google Play image $pkg." "Puedo crear el emulador \"$name\" con la imagen de Google Play $pkg.")"
    warn "$(L 'The system image is a download of about 1–2 GB.' 'La imagen del sistema es una descarga de 1–2 GB.')"
    confirm "$(L 'Download it and create the emulator?' '¿La descargo y creo el emulador?')" || return 1
    run avd-image sdkmanager --sdk_root="$ANDROID_HOME" --install "$pkg" || return 1
  else
    confirm "$(L "Create the emulator \"$name\" (the image is already installed: no download)?" "¿Creo el emulador \"$name\" (la imagen ya está instalada: sin descarga)?")" || return 1
  fi
  run avd-create bash -c "$(avd_create_cmd "$name" "$pkg")" || return 1
  avd_set_data_size "$name" 8G
  AVD_NAME=$name
}

boot_emulator() { # <avd> → sets A_SERIAL; waits for sys.boot_completed
  local avd=$1 attempt=1 pid i s
  AVD_NAME=$avd
  init_state || return 1
  while :; do
    ok "$(L "booting $avd in the background (log: $LOG/emulator.log)" "arrancando $avd en segundo plano (log: $LOG/emulator.log)")"
    nohup "$(emulator_bin)" -avd "$avd" -no-snapshot-save $EMU_EXTRA >"$LOG/emulator.log" 2>&1 &
    pid=$!
    for i in $(seq 90); do
      if ! kill -0 "$pid" 2>/dev/null; then break; fi
      s=$(adb_list | awk -F'|' '$4=="emulator" && $3=="device" {print $1; exit}')
      if [ -n "$s" ] && [ "$(adb -s "$s" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = 1 ]; then
        A_SERIAL=$s
        return 0
      fi
      sleep 2
    done
    kill -0 "$pid" 2>/dev/null && { bad "$(L 'the emulator did not finish booting in 3 minutes' 'el emulador no terminó de arrancar en 3 minutos')"; return 1; }
    record_error emulator 1 "$LOG/emulator.log"
    [ "$attempt" -ge 2 ] && return 1
    repair "$LOG/emulator.log" || return 1
    attempt=$((attempt + 1))
    warn "$(L 'repaired; booting again' 'reparado; arranco de nuevo')"
  done
}

use_emulator() { # <emulators: "serial|model|state|kind" lines>; sets A_SERIAL, A_ID, A_DEVNAME, AVD_NAME
  local emus=$1 s name avds n i choice l chosen=""
  s=$(awk -F'|' '$3=="device" {print $1; exit}' <<<"$emus")
  if [ -n "$s" ] && [ "$NEWAVD_FLAG" = 1 ]; then # a new emulator: the one running (one target at a time) goes first, with a yes
    confirm "$(L "An emulator is running ($s). Shut it down to create a new one?" "Hay un emulador corriendo ($s). ¿Lo apago para crear uno nuevo?")" || return 1
    adb -s "$s" emu kill >/dev/null 2>&1
    sleep 3
    s=""
  fi
  if [ -n "$s" ]; then
    name=$(emulator_running_name "$s")
    A_SERIAL=$s
    AVD_NAME=${name:-$s}
    ok "$(L "emulator already running: $AVD_NAME ($s)" "emulador ya corriendo: $AVD_NAME ($s)")"
  else
    emulator_bin >/dev/null || { block "$(L 'the Android emulator is not installed' 'el emulador de Android no está instalado')"; return 1; }
    [ -n "$DEVICE" ] && chosen=$DEVICE
    [ -z "$chosen" ] && chosen=$AVD_CFG
    [ -z "$chosen" ] && [ -f "$STATE/avd" ] && chosen=$(cat "$STATE/avd")
    avds=$(avd_list)
    if [ "$NEWAVD_FLAG" = 1 ]; then
      create_avd || return 1
      chosen=$AVD_NAME
    elif [ -n "$chosen" ] && grep -qx "$chosen" <<<"$avds"; then :
    elif [ -z "$avds" ]; then
      create_avd || return 1
      chosen=$AVD_NAME
    else
      n=$(grep -c . <<<"$avds")
      if [ "$YES" = 1 ]; then # --yes never waits and never creates one: the first
        chosen=$(sed -n 1p <<<"$avds")
        warn "$(L "--yes took the emulator $chosen. To choose: --device <AVD name>, or android --new-avd" "--yes tomó el emulador $chosen. Para elegir: --device <nombre del AVD>, o android --new-avd")"
      else
        i=0
        while read -r l; do i=$((i + 1)); printf '  %d) %s\n' "$i" "$l"; done <<<"$avds"
        printf '  n) %s\n' "$(L 'a NEW emulator (8 GB of storage)' 'un emulador NUEVO (8 GB de almacenamiento)')"
        ask choice "  $(L 'Which emulator? [1] ' '¿Cuál emulador? [1] ')" || return 1
        if [[ $choice == [nN] ]]; then create_avd || return 1; chosen=$AVD_NAME
        else
          [[ ${choice:-1} =~ ^[0-9]+$ ]] || choice=1
          chosen=$(sed -n "${choice:-1}p" <<<"$avds")
          [ -n "$chosen" ] || chosen=$(sed -n 1p <<<"$avds")
        fi
      fi
    fi
    remember avd "$chosen"
    boot_emulator "$chosen" || return 1
  fi
  A_ID="avd:$AVD_NAME"
  A_DEVNAME=$AVD_NAME
  A_MODEL=$AVD_NAME
}

# Chooses the Android target: a phone when one is connected, else an emulator (offered, never
# forced). Sets A_SERIAL, A_ID, A_DEVNAME and A_KIND. The "no phone" wait loop keeps the old behavior.
# Is an emulator an option? One is running, or the SDK has the emulator and an AVD (or can make one).
emulator_possible() { # <emulators running>
  [ "$1" -gt 0 ] && return 0
  [ -n "$(emulator_bin)" ] || return 1
  [ -n "$(avd_list)" ] || command -v sdkmanager >/dev/null
}

# android_target "ask" (the default): with a phone connected AND an emulator possible, asks which one
# at a terminal (default: last time's, kept in .local-dev/android_target_last). With --yes or no
# terminal it never blocks: it takes the last choice, else the phone, and says how to change it.
# Sets TGT: phone, emulator or auto (no real choice: the usual rules).
resolve_target_question() { # <phones> <emulators> <phone lines>
  TGT=$ANDROID_TARGET
  [ "$TGT" = ask ] || return 0
  if [ "$1" -lt 1 ] || ! emulator_possible "$2"; then TGT=auto; return 0; fi
  local last choice def=1
  last=$(cat "$STATE/android_target_last" 2>/dev/null)
  [ "$last" = emulator ] && def=2
  if [ "$YES" = 1 ] || ! interactive; then
    TGT=${last:-phone}
    warn "$(L "a phone and an emulator are both possible: --yes/no terminal took the $TGT (last time's choice, else the phone). To choose: --phone | --emulator, or android_target in [local]" "hay un teléfono y un emulador posibles: --yes/sin terminal tomó $TGT (la elección de la vez pasada, si no el teléfono). Para elegir: --phone | --emulator, o android_target en [local]")"
    return 0
  fi
  printf '  1) %s\n  2) %s\n' "$(L "phone: $(awk -F'|' 'NR==1{print $2}' <<<"$3")" "teléfono: $(awk -F'|' 'NR==1{print $2}' <<<"$3")")" "$(L 'emulator' 'emulador')"
  ask choice "  $(L "Phone or emulator? [$def] " "¿Teléfono o emulador? [$def] ")" || return 1
  case "${choice:-$def}" in 2 | e* | E*) TGT=emulator ;; *) TGT=phone ;; esac
  remember android_target_last "$TGT"
}

select_android_target() {
  local devs phones emus np ne plan choice running tgt
  while :; do
    devs=$(adb_list)
    phones=$(awk -F'|' '$4=="phone" && $3=="device"' <<<"$devs")
    emus=$(awk -F'|' '$4=="emulator" && $3=="device"' <<<"$devs")
    np=$(grep -c . <<<"$phones")
    ne=$(grep -c . <<<"$emus")
    # --device names an AVD, not one of the phones: it means the emulator, and there is nothing to ask
    if { [ "$ANDROID_TARGET" = auto ] || [ "$ANDROID_TARGET" = ask ]; } && [ -n "$DEVICE" ] &&
      ! awk -F'|' -v d="$DEVICE" '$1==d || $2==d {f=1} END{exit !f}' <<<"$phones" && avd_list | grep -qx "$DEVICE"; then
      tgt=emulator
    else
      resolve_target_question "$np" "$ne" "$phones" || return 1
      tgt=$TGT
    fi
    plan=$(android_plan "$tgt" "$np" "$ne")
    case "$plan" in
      phone)
        pick_phone "$phones" || return 1
        A_KIND=phone
        # one target at a time: an emulator left running is shut down only with a yes
        running=$(awk -F'|' '{print $1; exit}' <<<"$emus")
        if [ -n "$running" ] && confirm "$(L "An emulator is running ($running) and the phone is the target. Shut the emulator down?" "Hay un emulador corriendo ($running) y el target es el teléfono. ¿Apago el emulador?")"; then
          adb -s "$running" emu kill >/dev/null 2>&1
        fi
        return 0 ;;
      emulator-running | emulator-start)
        ensure emulator || return 1
        use_emulator "$emus" || return 1
        A_KIND=emulator
        return 0 ;;
      offer-emulator)
        warn "$(L 'No phone in sight.' 'No veo ningún teléfono.')"
        if confirm "$(L 'Use an Android emulator instead?' '¿Uso un emulador de Android?')"; then
          ensure emulator || return 1
          use_emulator "" || return 1
          A_KIND=emulator
          return 0
        fi ;;
    esac
    if awk -F'|' '$3=="unauthorized"{f=1} END{exit !f}' <<<"$devs"; then
      warn "$(L 'The phone asks for permission: unlock it and accept «Allow USB debugging».' 'El teléfono pide permiso: desbloquealo y aceptá «Permitir depuración USB».')"
    else
      warn "$(L 'No phone in sight. Connect it by USB with USB debugging on, or over Wi-Fi: bash .keelokit/bin/run-local.sh pair' 'No veo ningún teléfono. Conectalo por USB con «Depuración USB» activada, o por Wi-Fi: bash .keelokit/bin/run-local.sh pair')"
    fi
    BLOCKED=1
    [ "$YES" = 1 ] && return 1 # nobody to plug the phone in while it waits
    ask choice "  $(L 'Enter to retry, q to quit: ' 'Enter para reintentar, q para salir: ')" || return 1
    [ "$choice" = q ] && return 1
    BLOCKED=0
  done
}

# ----- relaunching without rebuilding -----

# A fingerprint of what a native build depends on. @expo/fingerprint when the project has it
# (UNTESTED against the real CLI), else a hash of dependencies, lockfiles, app config and tracked
# native folders. The prefix keeps the two apart: a switch of method is a rebuild, never a false match.
# Runs a command for at most <seconds>; its whole process group is stopped after that (macOS has no `timeout`).
with_timeout() { # <seconds> <command...>
  perl -e '$s = shift; $pid = fork; if (!$pid) { setpgrp(0, 0); exec @ARGV or exit 127 }
           $SIG{ALRM} = sub { kill "TERM", -$pid; exit 124 }; alarm $s; waitpid $pid, 0; exit($? >> 8)' "$@"
}

fingerprint() {
  local d=${MOBILE_DIR:-.} stamp cached
  stamp=$(detect_py stamp "$d" 2>/dev/null)
  # npx takes 15–25 s: an unchanged project (same paths, mtimes and sizes) does not pay twice.
  cached=$(awk -F'|' -v s="$stamp" '$1==s {print $2; exit}' "$STATE/fingerprint-cache" 2>/dev/null)
  if [ -n "$stamp" ] && [ -n "$cached" ]; then echo "$cached"; return; fi
  cached=$(fingerprint_compute)
  # only the slow answer is kept: a fallback hash is cheap, and a failed npx must not stick
  [ -n "$stamp" ] && [[ $cached == expo:* ]] && [ -d "$STATE" ] && echo "$stamp|$cached" >"$STATE/fingerprint-cache"
  echo "$cached"
}

fingerprint_compute() {
  local d=${MOBILE_DIR:-.} out h=""
  # Any project that depends on expo: pnpm does not hoist @expo/fingerprint, but npx finds it. At
  # most FINGERPRINT_TIMEOUT seconds (60): a hung npx must not freeze a launch.
  if [ -d "$d/node_modules/expo" ] || [ -d node_modules/expo ] || grep -q '"expo"' "$d/package.json" 2>/dev/null; then
    out=$(with_timeout "${FINGERPRINT_TIMEOUT:-60}" bash -c 'cd "$1" && exec npx --no-install @expo/fingerprint .' _ "$d" 2>/dev/null)
    h=$(printf '%s' "$out" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("hash",""))' 2>/dev/null)
    [ -n "$h" ] && { echo "expo:$h"; return; }
  fi
  h=$(detect_py fingerprint "${MOBILE_DIR:-.}" 2>/dev/null)
  [ -n "$h" ] && echo "files:$h"
}

app_version() { sed -n 's/.*"version"[ ]*:[ ]*"\([^"]*\)".*/\1/p' "${MOBILE_DIR:-.}/app.json" 2>/dev/null | head -1; }

android_installed() { # `pm path`, not `pm list`: a Samsung secure folder makes the list fail
  [ -n "$ANDROID_PKG" ] && adb -s "$A_SERIAL" shell pm path "$ANDROID_PKG" 2>/dev/null | grep -q '^package:'
}
ios_installed() { [ -n "$IOS_BUNDLE" ] && xcrun simctl get_app_container "$I_UDID" "$IOS_BUNDLE" >/dev/null 2>&1; }

# Build or not. Sets BUILD_PATH (build|fast|fail) and BUILD_WHY.
decide_build() { # <installed 1|0> <fingerprint now> <fingerprint last built>
  BUILD_PATH=build
  if [ "$REBUILD" = 1 ]; then BUILD_WHY=$(L 'forced by --rebuild' 'forzado por --rebuild')
  elif [ "$NOBUILD" = 1 ] && [ "$1" != 1 ]; then BUILD_PATH=fail; BUILD_WHY=$(L 'the app is not installed on this target and --no-build forbids building it' 'la app no está instalada en este target y --no-build prohíbe compilarla')
  elif [ "$NOBUILD" = 1 ]; then BUILD_PATH=fast; BUILD_WHY=$(L 'forced by --no-build' 'forzado por --no-build')
  elif [ "$1" != 1 ]; then BUILD_WHY=$(L 'the app is not installed on this target' 'la app no está instalada en este target')
  elif [ -z "$3" ]; then BUILD_WHY=$(L 'no record of a previous build here' 'no hay registro de un build anterior acá')
  elif [ -z "$2" ]; then BUILD_WHY=$(L 'the native inputs could not be fingerprinted' 'no se pudieron huellar las entradas nativas')
  elif [ "$2" != "$3" ]; then BUILD_WHY=$(L 'the native inputs changed since the last build' 'las entradas nativas cambiaron desde el último build')
  else BUILD_PATH=fast; BUILD_WHY=$(L 'installed, and the native inputs are the same as in the last build' 'instalada, y las entradas nativas son las mismas del último build')
  fi
}

build_ok_in_log() { # <target> <log>
  case "$1" in
    android) grep -qE 'BUILD SUCCESSFUL' "$2" ;;
    *) grep -qE 'Build Succeeded|\*\* BUILD SUCCEEDED' "$2" ;;
  esac
}

# The native build. The saved fingerprint is dropped first and written only after the build
# succeeded and the app is installed, so a failed or interrupted build never leaves a stale one.
native_build() { # <target> <id> <installed-check function> <step> <command...>
  local target=$1 id=$2 check=$3 step=$4 fp ver rc watcher
  shift 4
  fp=$(fingerprint)
  ver=$(app_version)
  init_state || return 1
  state_clear "$target" "$id"
  (
    for _ in $(seq 2000); do
      sleep 5
      if [ -f "$LOG/$step.log" ] && build_ok_in_log "$target" "$LOG/$step.log" && "$check" && [ -n "$fp" ]; then
        state_set "$target" "$id" "$fp" "$ver"
        exit 0
      fi
    done
  ) &
  watcher=$!
  launch "$step" "$@"
  rc=$?
  kill "$watcher" 2>/dev/null
  wait "$watcher" 2>/dev/null
  if [ "$rc" = 0 ] && [ -n "$fp" ] && build_ok_in_log "$target" "$LOG/$step.log" && "$check"; then
    state_set "$target" "$id" "$fp" "$ver"
  fi
  return "$rc"
}

deep_link() { # the dev client opens Metro's address
  echo "$SCHEME://expo-development-client/?url=http%3A%2F%2Flocalhost%3A8081"
}

open_app() { # <android|ios>: open the installed app on the target (the dev client, pointed at Metro)
  if [ "$1" = android ]; then
    if [ -n "$SCHEME" ]; then adb -s "$A_SERIAL" shell am start -a android.intent.action.VIEW -d "$(deep_link)" >/dev/null
    else adb -s "$A_SERIAL" shell monkey -p "$ANDROID_PKG" -c android.intent.category.LAUNCHER 1 >/dev/null; fi
  else
    if [ -n "$SCHEME" ]; then xcrun simctl openurl "$I_UDID" "$(deep_link)"
    else xcrun simctl launch "$I_UDID" "$IOS_BUNDLE" >/dev/null; fi
  fi
}

wait_metro() { local _; for _ in $(seq 180); do curl -s http://localhost:8081/status 2>/dev/null | grep -q running && return 0; sleep 1; done; return 1; }

# The fast path: Metro, and the installed dev client opened on it. No native build.
fast_launch() { # <android|ios> <step>
  [ -n "$SCHEME" ] || warn "$(L 'no URL scheme in the app config: the app is launched, and you pick Metro in it' 'la config de la app no tiene scheme: se abre la app y elegís Metro en ella')"
  # iOS always asks the simulator's user to confirm a custom-scheme link (Open in "<app>"?). Launching
  # the app first was tried on hardware: the dev launcher opens but does not reconnect by itself, so
  # the link is the way. Android has no such prompt.
  [ "$1" = ios ] && warn "$(L 'iOS asks "Open in <your app>?": tap Open.' 'iOS pregunta «¿Abrir en <tu app>?»: tocá Abrir.')"
  ( wait_metro && open_app "$1" ) &
  launch "$2" env "$API_URL_ENV=$(api_url)" bash "$SELF" __expo start --dev-client
}

# With --yes, the Expo Go install/update prompt is answered (Y) for the Expo Go launches only; without
# --yes at a terminal nothing changes and Expo asks by itself.
expo_go_yes() {
  FEED_Y=0
  [ "$YES" = 1 ] || return 0
  FEED_Y=1
  warn "$(L 'Expo Go: --yes accepts installing or updating it on the target if Expo asks (it downloads the app from Expo).' 'Expo Go: --yes acepta instalarlo o actualizarlo en el target si Expo pregunta (descarga la app de Expo).')"
}

# Prints which path was taken and why. Returns 1 when --no-build forbids the only way forward.
choose_build_path() { # <target> <id> <installed function>
  local last fp
  last=$(state_get "$1" "$2")
  fp=$(fingerprint)
  if "$3"; then decide_build 1 "$fp" "${last%%|*}"; else decide_build 0 "$fp" "${last%%|*}"; fi
  case "$BUILD_PATH" in
    fast) ok "$(L "no native build: $BUILD_WHY" "sin build nativo: $BUILD_WHY")" ;;
    build) ok "$(L "native build: $BUILD_WHY" "build nativo: $BUILD_WHY")" ;;
    fail) bad "$BUILD_WHY"; return 1 ;;
  esac
}

run_android() {
  ensure base android || return 1
  start_backend || return 1
  select_android_target || return 1
  adb -s "$A_SERIAL" reverse tcp:8081 tcp:8081 || { bad "adb reverse failed"; return 1; }
  if [ -n "$API_DIR" ]; then
    adb -s "$A_SERIAL" reverse "tcp:$API_PORT" "tcp:$API_PORT" || { bad "adb reverse failed"; return 1; }
  fi
  free_port 8081 || return 1
  choose_client
  if [ "$USE_CLIENT" = dev-client ]; then
    choose_build_path android "$A_ID" android_installed || return 1
    if [ "$BUILD_PATH" = fast ]; then
      say "$(L 'Starting Metro and opening the app. Ctrl+C stops Metro.' 'Arrancando Metro y abriendo la app. Ctrl+C detiene Metro.')"
      fast_launch android android-metro
    else
      say "$(L 'Building and installing (first time: 10–20 min; after that, fast). Ctrl+C stops Metro.' 'Compilando e instalando (la primera vez: 10–20 min; después, rápido). Ctrl+C detiene Metro.')"
      native_build android "$A_ID" android_installed android env "$API_URL_ENV=$(api_url)" bash "$SELF" __expo run:android --device "$A_DEVNAME"
    fi
  else
    # UNTESTED: Expo Go on a real Android phone. Expo Go must come from the store; it is never installed from here.
    if ! adb -s "$A_SERIAL" shell pm list packages 2>/dev/null | grep -q host.exp.exponent; then
      bad "$(L 'Expo Go is not on the phone: install it from the Play Store and run again.' 'Expo Go no está en el teléfono: instalalo desde Play Store y volvé a correr.')"
      return 1
    fi
    say "$(L 'Opening in Expo Go. Ctrl+C stops Metro.' 'Abriendo en Expo Go. Ctrl+C detiene Metro.')"
    expo_go_yes
    launch android env "$API_URL_ENV=$(api_url)" bash "$SELF" __expo start --android
  fi
}

pick_ios() { # sets I_UDID and I_NAME: --device, the simulator you chose last time, or a menu; the others get shut down
  local last="" sims i=0 choice l
  [ -f $STATE/ios-device ] && last=$(cat $STATE/ios-device)
  sims=$(xcrun simctl list devices available | sed -nE 's/^ +(iPhone[^()]*[^ (]) \(([0-9A-F-]{36})\) \((Booted|Shutdown)\).*/\2 \1 (\3)/p')
  if [ -n "$DEVICE" ]; then
    I_UDID=$(awk -v d="$DEVICE" '{u=$1; n=$0; sub(/^[^ ]+ /,"",n); sub(/ \((Booted|Shutdown)\)$/,"",n); if (u==d || n==d) {print u; exit}}' <<<"$sims")
    [ -n "$I_UDID" ] || { block "$(L "no simulator is \"$DEVICE\" (name or UDID)" "ningún simulador es \"$DEVICE\" (nombre o UDID)")"; return 1; }
  elif [ -n "$last" ] && grep -q "^$last" <<<"$sims"; then
    I_UDID=$last
    ok "$(L "simulator: $(grep "^$last" <<<"$sims" | cut -d' ' -f2-) (to change it: --device, or rm $STATE/ios-device)" "simulador: $(grep "^$last" <<<"$sims" | cut -d' ' -f2-) (para cambiarlo: --device, o rm $STATE/ios-device)")"
  elif [ "$YES" = 1 ]; then # never waits: a booted iPhone, else the first; remembered, and said
    I_UDID=$(grep '(Booted)$' <<<"$sims" | head -1 | cut -d' ' -f1)
    [ -n "$I_UDID" ] || I_UDID=$(sed -n 1p <<<"$sims" | cut -d' ' -f1)
    [ -n "$I_UDID" ] || { block "$(L 'there is no iPhone simulator' 'no hay un simulador de iPhone')"; return 1; }
    warn "$(L "--yes took the simulator $(grep "^$I_UDID" <<<"$sims" | cut -d' ' -f2- | sed 's/ ([A-Za-z]*)$//'). To choose: --device <name|UDID>, or rm $STATE/ios-device" "--yes tomó el simulador $(grep "^$I_UDID" <<<"$sims" | cut -d' ' -f2- | sed 's/ ([A-Za-z]*)$//'). Para elegir: --device <nombre|UDID>, o rm $STATE/ios-device")"
    init_state && echo "$I_UDID" >$STATE/ios-device
  else
    while read -r l; do i=$((i + 1)); printf '  %d) %s\n' "$i" "${l#* }"; done <<<"$sims"
    ask choice "  $(L 'Which simulator? [1] ' '¿Qué simulador? [1] ')" || return 1
    [[ ${choice:-1} =~ ^[0-9]+$ ]] || choice=1
    I_UDID=$(sed -n "${choice:-1}p" <<<"$sims" | cut -d' ' -f1)
    [ -n "$I_UDID" ] || return 1
    init_state || return 1
    echo "$I_UDID" >$STATE/ios-device
  fi
  # expo reads a UDID as a physical device (and asks for code signing): it wants the simulator's NAME
  I_NAME=$(grep "^$I_UDID" <<<"$sims" | cut -d' ' -f2- | sed 's/ ([A-Za-z]*)$//')
  # one simulator at a time
  xcrun simctl list devices booted | sed -nE 's/.*\(([0-9A-F-]{36})\) \(Booted\).*/\1/p' | while read -r u; do
    [ "$u" = "$I_UDID" ] || xcrun simctl shutdown "$u"
  done
}

# `expo run:ios` asks for an Apple developer certificate, even for the simulator, when the project
# declares capabilities such as Sign in with Apple. A simulator build runs without them (those
# features just do not work there), so the generated ios/ project loses them. Only the simulator,
# only an ios/ that git does not track, only after showing the list and asking once. A phone never
# gets this: a build for a device needs the real certificate, and the script says so instead.
ENTITLEMENTS="com.apple.developer.applesignin com.apple.developer.associated-domains aps-environment com.apple.developer.healthkit"
strip_entitlements() {
  local ios=${MOBILE_DIR:-.}/ios f key found=""
  if [ ! -d "$ios" ]; then
    ok "$(L 'no ios/ yet: expo creates it' 'todavía no hay ios/: lo crea expo')"
    run prebuild-ios expo prebuild --platform ios || return 1
  fi
  f=$(ls "$ios"/*/*.entitlements 2>/dev/null | head -1)
  [ -n "$f" ] || return 0
  for key in $ENTITLEMENTS; do
    "$PLISTBUDDY" -c "Print :$key" "$f" >/dev/null 2>&1 && found="$found $key"
  done
  [ -n "$found" ] || return 0
  if [ -n "$(git ls-files "$ios" 2>/dev/null | head -1)" ]; then
    warn "$(L "ios/ is tracked by git, so I do not edit it. It declares:$found; the build may ask for a certificate. Remove them yourself, or build on a device." "ios/ está versionado en git, así que no lo edito. Declara:$found; el build puede pedir un certificado. Quitalos vos, o compilá en un dispositivo.")"
    confirm "$(L 'Build anyway?' '¿Compilo igual?')" || return 1
    return 0
  fi
  if [ ! -f "$STATE/entitlements-ok" ]; then
    warn "$(L 'This simulator build does not run with these capabilities, so I remove them from the generated ios/ (the app config is untouched):' 'Este build de simulador no corre con estas capacidades, así que las quito del ios/ generado (la config de la app no se toca):')"
    for key in $found; do printf '    - %s\n' "$key"; done
    confirm "$(L 'Remove them? (I will remember the answer)' '¿Las quito? (recuerdo la respuesta)')" || return 1
    init_state && : >"$STATE/entitlements-ok"
  fi
  for key in $found; do "$PLISTBUDDY" -c "Delete :$key" "$f" 2>/dev/null; done
  ok "$(L "removed from ios/:$found" "quitado de ios/:$found")"
}

run_ios() {
  ensure base ios || return 1
  start_backend || return 1
  pick_ios || return 1
  I_ID=$I_UDID
  xcrun simctl boot "$I_UDID" 2>/dev/null # already booted is fine
  open -a Simulator
  xcrun simctl bootstatus "$I_UDID" -b >/dev/null
  free_port 8081 || return 1
  choose_client
  if [ "$USE_CLIENT" = dev-client ]; then
    choose_build_path ios "$I_ID" ios_installed || return 1
    if [ "$BUILD_PATH" = fast ]; then
      say "$(L 'Starting Metro and opening the app. Ctrl+C stops Metro.' 'Arrancando Metro y abriendo la app. Ctrl+C detiene Metro.')"
      fast_launch ios ios-metro
    else
      strip_entitlements || return 1
      say "$(L 'Building and installing on the simulator (first time: 10–20 min). Ctrl+C stops Metro.' 'Compilando e instalando en el simulador (la primera vez: 10–20 min). Ctrl+C detiene Metro.')"
      native_build ios "$I_ID" ios_installed ios env "$API_URL_ENV=$(api_url)" bash "$SELF" __expo run:ios --device "$I_NAME"
    fi
  else
    say "$(L 'Opening in Expo Go (it installs itself in the simulator). Ctrl+C stops Metro.' 'Abriendo en Expo Go (se instala solo en el simulador). Ctrl+C detiene Metro.')"
    expo_go_yes
    launch ios env "$API_URL_ENV=$(api_url)" bash "$SELF" __expo start --ios
  fi
}

# Only Metro: the app is opened by hand. adb reverse goes to every phone and emulator that is there.
run_metro() {
  ensure base || return 1
  start_backend || return 1
  local s
  if command -v adb >/dev/null; then
    for s in $(adb_list | awk -F'|' '$3=="device" {print $1}'); do
      adb -s "$s" reverse tcp:8081 tcp:8081 >/dev/null && ok "adb reverse 8081 → $s"
      [ -n "$API_DIR" ] && adb -s "$s" reverse "tcp:$API_PORT" "tcp:$API_PORT" >/dev/null && ok "adb reverse $API_PORT → $s"
    done
  fi
  free_port 8081 || return 1
  choose_client
  say "$(L 'Metro on http://localhost:8081. Open the app by hand. Ctrl+C stops Metro.' 'Metro en http://localhost:8081. Abrí la app a mano. Ctrl+C detiene Metro.')"
  if [ "$USE_CLIENT" = dev-client ]; then launch metro env "$API_URL_ENV=$(api_url)" bash "$SELF" __expo start --dev-client
  else launch metro env "$API_URL_ENV=$(api_url)" bash "$SELF" __expo start; fi
}

# ---------- entry ----------

# `launch` runs a program, not a shell function: it re-enters this script to reach `expo`.
if [ "${1:-}" = __expo ]; then shift; load_config; setup_env; expo "$@"; exit; fi

trap : INT # Ctrl+C stops the child (Metro), not this menu

# 0 done · 1 failed · 3 stopped on something only a person can do · 4 declined or no terminal
finish() { # <rc>
  [ "$1" = 0 ] && return 0
  [ "$BLOCKED" = 1 ] && return 3
  [ "$DECLINED" = 1 ] && return 4
  return 1
}

emit_json() { # doctor --json: messages, what is missing, blockers and the exit code, as JSON
  local m r
  {
    for m in "${MSGS[@]}"; do printf 'msg\t%s\n' "$m"; done
    for r in "${MISSING[@]}"; do printf 'missing\t%s\n' "$r"; done
    for r in "${BLOCKERS[@]}"; do printf 'blocker\t%s\n' "$r"; done
    printf 'exit\t%s\n' "$1"
  } | detect_py json_doctor
}

dispatch() {
  case "$CMD" in
    android) run_android ;;
    ios) run_ios ;;
    metro) run_metro ;;
    backend) ensure base && start_backend ;;
    seed) ensure base && NOSEED_FLAG=1 && start_backend && run_seed 1 ;;
    pair) pair_android ;;
    doctor) ensure base android ios ;;
    status) cmd_status ;;
    logs) cmd_logs ;;
    clean) cmd_clean ;;
    stop) stop_backend ;;
  esac
}

main() {
  local rc
  while [ $# -gt 0 ]; do
    case "$1" in
      --yes) YES=1 ;;
      --check) CHECK=1 ;;
      --no-install) NOINSTALL=1 ;;
      --json) JSONMODE=1 ;;
      --seed) SEED_FLAG=1 ;;
      --no-seed) NOSEED_FLAG=1 ;;
      --phone) PHONE_FLAG=1 ;;
      --rebuild) REBUILD=1 ;;
      --no-build) NOBUILD=1 ;;
      --emulator) EMULATOR_FLAG=1 ;;
      --new-avd) EMULATOR_FLAG=1; NEWAVD_FLAG=1 ;;
      --help | -h) HELP=1 ;;
      --device) [ -n "${2:-}" ] && [[ $2 != -* ]] || { echo "--device needs a value: a serial, a model, a simulator name or a UDID" >&2; exit 2; }; DEVICE=$2; shift ;;
      -*) usage; exit 2 ;;
      *) if [ -z "$CMD" ]; then CMD=$1; elif [ -z "$ARG2" ]; then ARG2=$1; else usage; exit 2; fi ;;
    esac
    shift
  done
  [ "$SEED_FLAG" = 1 ] && [ "$NOSEED_FLAG" = 1 ] && { echo "--seed and --no-seed exclude each other" >&2; exit 2; }
  [ "$PHONE_FLAG" = 1 ] && [ "$EMULATOR_FLAG" = 1 ] && { echo "--phone and --emulator exclude each other" >&2; exit 2; }
  case "$CMD" in "" | android | ios | metro | backend | seed | users | pair | doctor | status | logs | clean | stop | detect | help) ;; *) usage; exit 2 ;; esac
  if [ "$CMD" = help ]; then CMD=$ARG2; HELP=1; fi
  if [ "${HELP:-0}" = 1 ]; then
    if [ -z "$CMD" ]; then sed -n '2,/^set -o pipefail/p' "$SELF" | grep '^#' | sed 's/^# \{0,1\}//'; else help_text "$CMD"; fi
    exit 0
  fi
  if [ "$REBUILD" = 1 ] && [ "$NOBUILD" = 1 ]; then echo "--rebuild and --no-build exclude each other" >&2; exit 2; fi
  if [ "$CMD" = detect ]; then
    command -v python3 >/dev/null || { echo "python3 is needed" >&2; exit 1; }
    detect_py json
    exit
  fi
  [ "$CMD" = doctor ] && [ "$JSONMODE" = 1 ] && NOINSTALL=1
  load_config
  if [ "$CMD" = users ]; then cmd_users; exit; fi # reads project files only: any OS
  if [ "$CMD" = logs ]; then cmd_logs; exit; fi # reads files only: works on any OS, whatever [local] says
  if [ "$CMD" = doctor ] && [ "$CHECK" = 1 ]; then
    check_config
    rc=$?
    [ "$JSONMODE" = 1 ] && emit_json "$rc"
    exit "$rc"
  fi
  if [ "$(uname -s)" != Darwin ]; then
    emit ok "$(L 'run-local runs on macOS only for now.' 'run-local solo corre en macOS por ahora.')"
    if [ "$JSONMODE" = 1 ]; then emit_json 0; else echo "$(L 'run-local runs on macOS only for now.' 'run-local solo corre en macOS por ahora.')"; fi
    exit 0
  fi
  if [ "$HAS_LOCAL" = 0 ]; then
    setup_local
    case $? in 0) ;; 2) exit 0 ;; *) exit 1 ;; esac
  fi
  if [ "$CMD" = doctor ]; then check_config; rc=$?; else QUIET=1; check_config; rc=$?; QUIET=0; fi
  [ "$rc" = 0 ] || { [ "$JSONMODE" = 1 ] && emit_json 1; exit 1; }
  if [ -z "$CMD" ]; then
    while :; do
      printf '\n\033[1m%s\033[0m\n  1) %s\n  2) %s\n  3) %s\n  4) %s\n  5) %s\n  6) %s\n  q) %s\n' \
        "$(L 'Local environment' 'Entorno local')" "$(L 'Android: phone or emulator' 'Android: teléfono o emulador')" "$(L 'iOS: simulator' 'iOS: simulador')" \
        "$(L 'Only the API and the database' 'Solo la API y la base de datos')" "$(L 'Diagnosis' 'Diagnóstico')" \
        "$(L 'Stop the API and the database' 'Detener API y base de datos')" "$(L 'What is running' 'Qué está corriendo')" "$(L 'Quit' 'Salir')"
      ask rc "  $(L 'Choose: ' 'Elegí: ')" || break
      case "$rc" in
        1) run_android ;; 2) run_ios ;; 3) ensure base && start_backend ;;
        4) ensure base android ios ;; 5) stop_backend ;; 6) cmd_status ;; q | Q | "") break ;;
      esac
    done
    [ "$DECLINED" = 1 ] && exit 4
    exit 0
  fi
  dispatch
  rc=$?
  finish "$rc"
  rc=$?
  [ "$JSONMODE" = 1 ] && [ "$CMD" = doctor ] && emit_json "$rc"
  exit "$rc"
}
[ -n "${RUN_LOCAL_LIB:-}" ] && return 0 # sourced by the tests: functions only
main "$@"
