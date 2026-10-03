#!/usr/bin/env bash
# Runs the product's Expo app and its API on this Mac, in one command, on ONE target at a time: an
# Android phone (USB or wireless debugging) or an iOS Simulator. It checks what the Mac is missing,
# shows it all at once and, after one yes, installs it; then starts the database and the API, and
# launches the app. It runs without Claude and without the plugin, like scripts/verify.sh.
#
#   bash .keelokit/bin/run-local.sh                          menu
#   bash .keelokit/bin/run-local.sh android | ios | backend | doctor | stop | detect
#   --yes        answer yes to every question
#   --check      with `doctor`: only check that [local] in .keelokit/profile.toml is coherent and
#                the Expo app is where it says (any OS, installs nothing, asks nothing, exit 1 if not)
#   --no-install with `doctor`: also diagnose this Mac, but install nothing
#
# Settings live in the [local] block of .keelokit/profile.toml; whatever it leaves out is detected
# from the repo (`detect` prints what it finds as JSON). Messages follow the project's language
# ([dashboard] lang in .keelokit/state.toml, else $LANG; English or Spanish).
# Every step logs to .local-dev/logs/. When one fails, the tail of its log goes to
# .local-dev/last-error.txt (hand that file to Claude), a few known causes are repaired and the
# step runs again once. Nothing is killed, stopped or deleted without asking.
# macOS only, and tested on Intel with Xcode 26; Apple Silicon, a real Android phone and Expo Go
# are written from the same lessons but UNTESTED. macOS ships bash 3.2: no mapfile, no
# associative arrays.
set -o pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.." || exit 1

SELF=$PWD/.keelokit/bin/run-local.sh
PROFILE=.keelokit/profile.toml
STATE=.local-dev
LOG=$STATE/logs
YES=0 CHECK=0 NOINSTALL=0 CMD=
PLAN_D=() PLAN_C=() BLOCKERS=()
QUIET=0 DETECTED=0 HAS_LOCAL=0
PLISTBUDDY=${PLISTBUDDY:-/usr/libexec/PlistBuddy} # the two overridable tools are test hooks (tests/test_run_local.py)

# ---------- language and output ----------

LNG=$(awk '/^[ \t]*\[/{s=$0;gsub(/^[ \t]*\[|\][ \t]*(#.*)?$/,"",s);i=(s=="dashboard");next} i&&/^[ \t]*lang[ \t]*=/{v=$0;sub(/^[^=]*=[ \t]*"?/,"",v);sub(/".*$/,"",v);print v;exit}' .keelokit/state.toml 2>/dev/null)
if [ -z "$LNG" ]; then case "${LANG:-}" in es*) LNG=es ;; *) LNG=en ;; esac; fi
L() { if [ "$LNG" = es ]; then printf '%s' "$2"; else printf '%s' "$1"; fi; } # L <english> <spanish>

say() { printf '\n\033[1m▶ %s\033[0m\n' "$*"; }
ok() { [ "$QUIET" = 1 ] || printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
bad() { printf '  \033[31m✗\033[0m %s\n' "$*"; }
confirm() {
  [ "$YES" = 1 ] && return 0
  local a
  read -r -p "  $1 $(L '[Y/n]' '[S/n]') " a || return 1 # no terminal, no yes
  [[ -z $a || $a =~ ^[sSyY] ]]
}
need() { PLAN_D+=("$1"); PLAN_C+=("$2"); bad "$(L 'missing:' 'falta:') ${1#\?}"; } # "?desc" = optional
block() { BLOCKERS+=("$1"); bad "$1"; }                                          # only a person can fix it

usage() { echo "usage: bash .keelokit/bin/run-local.sh [android|ios|backend|doctor|stop|detect] [--yes] [--check] [--no-install]" >&2; }

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
# skills; `client`: Expo Go or a dev client, and why.
detect_py() { # <kv|json|client> [mobile_dir]
  python3 - "$PWD" "$@" <<'PY'
import json, os, re, sys
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

def pm_run(pm, d, script):
    if pm == "pnpm":
        return f"pnpm --dir {d} run {script}"
    if pm == "yarn":
        return f"yarn --cwd {d} run {script}"
    return f"npm --prefix {d} run {script}"

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
    for lock, name in (("pnpm-lock.yaml", "pnpm"), ("yarn.lock", "yarn"), ("package-lock.json", "npm")):
        if not pm and os.path.exists(os.path.join(root, base, lock)):
            pm = name
if not pm:
    pm = (readj(os.path.join(root, "package.json")).get("packageManager", "npm").split("@")[0]) or "npm"
    unc.append("pm")
out["pm"] = pm

# android package
pkgname = ""
if mobile:
    app = os.path.join(root, md)
    aj = readj(os.path.join(app, "app.json")).get("expo", {})
    pkgname = aj.get("android", {}).get("package", "")
    if not pkgname:
        for f in sorted(os.listdir(app)):
            if f.startswith("app.config."):
                t = reads(os.path.join(app, f))
                m = re.search(r"android\s*:\s*\{[^}]*?package\s*:\s*['\"]([\w.]+)['\"]", t, re.S) or re.search(r"package\s*:\s*['\"]([\w.]+)['\"]", t)
                pkgname = m.group(1) if m else ""
    if not pkgname:
        unc.append("android_package")
out["android_package"] = pkgname

# the database service: a compose service running postgres
db = ""
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
    break
out["db_service"] = db

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
    scripts = readj(os.path.join(ap, "package.json")).get("scripts", {})
    rs = readj(os.path.join(root, "package.json")).get("scripts", {})
    if "dev:api" in rs:
        out["api_start"] = {"pnpm": "pnpm run dev:api", "yarn": "yarn run dev:api"}.get(pm, "npm run dev:api")
    else:
        s = next((k for k in ("dev", "start:dev", "start") if k in scripts), "")
        out["api_start"] = pm_run(pm, api, s) if s else ""
        if not s:
            unc.append("api_start")
    if "prisma:migrate:deploy" in scripts:
        out["api_migrate"] = pm_run(pm, api, "prisma:migrate:deploy")
    elif os.path.isdir(os.path.join(ap, "prisma")):
        out["api_migrate"] = f"cd {api} && npx prisma migrate deploy"
    m = re.search(r"(?m)^PORT=(\d+)", reads(os.path.join(ap, ".env.example")))
    if m:
        out["api_port"] = m.group(1)

# the app's API url: the EXPO_PUBLIC_*URL variable the app reads, and the path its default carries
name, suffix = "", ""
if mobile:
    app = os.path.join(root, md)
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

if mode == "json":
    print(json.dumps(out, indent=2))
else:
    for k, v in out.items():
        print(f"{k}={','.join(v) if isinstance(v, list) else v}")
PY
}

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

load_config() {
  grep -q '^\[local\]' "$PROFILE" 2>/dev/null && HAS_LOCAL=1
  load_detect
  MOBILE_DIR=$(cfg mobile_dir)
  [ "$MOBILE_DIR" = . ] && MOBILE_DIR=
  PM=$(cfg pm)
  ANDROID_PKG=$(cfg android_package)
  API_DIR=$(cfg api_dir)
  API_START=$(cfg api_start)
  API_READY=$(cfg api_ready_url)
  API_MIGRATE=$(cfg api_migrate)
  API_SEED=$(cfg api_seed)
  DB_SERVICE=$(cfg db_service)
  API_PORT=$(cfg api_port)
  API_URL_ENV=$(cfg api_url_env)
  API_URL_SUFFIX=$(cfg api_url_suffix)
  CLIENT=$(cfg client)
  JDK=$(cfg jdk)
  [ -n "$API_PORT" ] || API_PORT=3000
  [ -n "$CLIENT" ] || CLIENT=auto
  [ -n "$JDK" ] || JDK=17
}

has_expo_app() { # the folder holds an Expo app
  local d=${MOBILE_DIR:-.}
  [ -f "$d/app.json" ] || ls "$d"/app.config.* >/dev/null 2>&1 || grep -q '"expo"' "$d/package.json" 2>/dev/null
}

# Coherence of [local], on any OS: what RUN-1 asks of the project. Prints problems, returns 1 on any.
check_config() {
  local n=0 p
  if [ "$HAS_LOCAL" = 0 ]; then
    if [ -z "${DET_mobile_dir:-}" ] && ! has_expo_app; then
      ok "$(L 'no Expo app here: nothing to run' 'no hay app Expo: no hay nada que lanzar')"
      return 0
    fi
    bad "$(L "an Expo app is in ${DET_mobile_dir:-.} but .keelokit/profile.toml has no [local] block: run /keelokit:run-local, or: bash .keelokit/bin/run-local.sh doctor" "hay una app Expo en ${DET_mobile_dir:-.} pero .keelokit/profile.toml no tiene el bloque [local]: corré /keelokit:run-local, o: bash .keelokit/bin/run-local.sh doctor")"
    return 1
  fi
  has_expo_app || { bad "$(L "mobile_dir \"$MOBILE_DIR\" has no Expo app (app.json, app.config.* or expo in package.json)" "mobile_dir \"$MOBILE_DIR\" no tiene una app Expo (app.json, app.config.* o expo en package.json)")"; n=1; }
  case "$PM" in pnpm | npm | yarn) ;; *) bad "$(L "pm \"$PM\" is not pnpm, npm or yarn" "pm \"$PM\" no es pnpm, npm ni yarn")"; n=1 ;; esac
  if [ -n "$API_DIR" ] && [ ! -d "$API_DIR" ]; then bad "$(L "api_dir \"$API_DIR\" does not exist" "api_dir \"$API_DIR\" no existe")"; n=1; fi
  if [ -n "$DB_SERVICE" ]; then
    p=$(ls docker-compose.yml docker-compose.yaml compose.yml compose.yaml 2>/dev/null | head -1)
    [ -n "$p" ] || { bad "$(L "db_service \"$DB_SERVICE\" but there is no docker compose file" "db_service \"$DB_SERVICE\" pero no hay un archivo de docker compose")"; n=1; }
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
      read -r -p "  $(L 'Which one? [1] ' '¿Cuál? [1] ') " ans || return 1
      DET_mobile_dir=$(tr ',' '\n' <<<"$dirs" | sed -n "${ans:-1}p")
      [ -n "$DET_mobile_dir" ] || return 1
    fi
  fi
  for k in mobile_dir pm android_package api_dir api_start api_ready_url api_migrate db_service api_port api_url_env api_url_suffix; do
    eval "cur=\${DET_$k:-}"
    printf '  %-16s %s\n' "$k" "${cur:-—}"
  done
  for k in $(tr ',' ' ' <<<"${DET_uncertain:-}"); do
    [ "$k" = mobile_dir ] && continue
    eval "cur=\${DET_$k:-}"
    warn "$(L "not certain: $k" "no estoy seguro: $k")"
    if [ "$YES" = 0 ]; then
      read -r -p "  $k [$cur]: " ans || return 1
      [ -n "$ans" ] && eval "DET_$k=\$ans"
    fi
  done
  confirm "$(L 'Save this as [local] in .keelokit/profile.toml?' '¿Guardo esto como [local] en .keelokit/profile.toml?')" || return 1
  [ -f "$PROFILE" ] || { bad "$(L 'there is no .keelokit/profile.toml' 'no existe .keelokit/profile.toml')"; return 1; }
  {
    [ -n "$(tail -c1 "$PROFILE")" ] && echo
    echo
    echo '[local]'
    for k in mobile_dir android_package pm api_dir api_start api_ready_url api_migrate api_seed db_service api_port api_url_env api_url_suffix client; do
      eval "cur=\${DET_$k:-}"
      case $k in api_port) [ -n "$cur" ] || cur=3000 ;; client) cur=auto ;; esac
      if [ "$k" = api_port ]; then printf '%s = %s\n' "$k" "$cur"
      elif [[ $cur == *\"* ]]; then printf "%s = '%s'\n" "$k" "$cur"
      else printf '%s = "%s"\n' "$k" "$cur"; fi
    done
  } >>"$PROFILE"
  HAS_LOCAL=1
  ok "$(L '[local] saved. Correct by hand whatever is wrong.' '[local] guardado. Corregí a mano lo que esté mal.')"
  load_config
}

# ---------- environment ----------

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
  PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin:$brewtools:$PATH"
  if ! command -v node >/dev/null && [ -s "$HOME/.nvm/nvm.sh" ]; then . "$HOME/.nvm/nvm.sh" >/dev/null; fi
}

# The first write into .local-dev/: asks once when git would otherwise see it.
init_state() {
  [ -d "$STATE" ] && return 0
  if git rev-parse --git-dir >/dev/null 2>&1 && ! git check-ignore -q "$STATE/x"; then
    confirm "$(L "Create $STATE/ (logs, last-error.txt) and add it to .gitignore?" "¿Creo $STATE/ (logs, last-error.txt) y lo agrego a .gitignore?")" || return 1
    { [ -f .gitignore ] && [ -n "$(tail -c1 .gitignore)" ] && echo; echo "$STATE/"; } >>.gitignore
  fi
  mkdir -p "$LOG"
}

# ---------- running things, logging, repairs ----------

record_error() { # <step> <exit code> <log>
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

# Known causes of a failed build, repaired in place. Returns 0 when it changed something, so the
# step is worth running again; 1 when the failure is unknown (it stays in last-error.txt).
repair() { # <log>
  local log=$1 props
  if grep -qE 'INSTALL_FAILED_UPDATE_INCOMPATIBLE|signatures do not match' "$log" && [ -n "$ANDROID_PKG" ] && [ -n "$A_SERIAL" ]; then
    warn "$(L 'the installed app is signed differently' 'la app instalada está firmada distinto')"
    confirm "$(L "Uninstall $ANDROID_PKG from the phone?" "¿Desinstalo $ANDROID_PKG del teléfono?")" || return 1
    adb -s "$A_SERIAL" uninstall "$ANDROID_PKG" >/dev/null
  elif grep -qE 'EADDRINUSE|[Pp]ort 8081 .*(in use|already)' "$log"; then
    free_port 8081 || return 1
  elif grep -qE 'OutOfMemoryError|Java heap space|Gradle daemon.*(disappeared|stopped)|Daemon will be stopped' "$log"; then
    warn "$(L 'Gradle ran out of memory: 4 GB for it, and its daemon restarts' 'Gradle se quedó sin memoria: le doy 4 GB y reinicio su daemon')"
    props=${MOBILE_DIR:-.}/android/gradle.properties
    [ -f "$props" ] && sed -i '' 's/^org.gradle.jvmargs=.*/org.gradle.jvmargs=-Xmx4096m -XX:MaxMetaspaceSize=1g/' "$props"
    (cd "${MOBILE_DIR:-.}/android" && ./gradlew --stop >/dev/null 2>&1)
  elif grep -qE 'pod install|CocoaPods could not find compatible|Unable to find a specification' "$log"; then
    warn "$(L 'CocoaPods: updating its index and reinstalling the pods' 'CocoaPods: actualizo su índice y reinstalo los pods')"
    (cd "${MOBILE_DIR:-.}/ios" && pod install --repo-update)
  elif grep -q 'google-services.json\|GoogleService-Info.plist' "$log"; then
    warn "$(L 'a Google services file the app points to is missing: it is a secret of the project, put it where app.json says' 'falta un archivo de servicios de Google al que apunta la app: es un secreto del proyecto, ponelo donde dice app.json')"
    return 1
  else
    return 1
  fi
}

# An interactive step (Metro keeps running in it): `script` keeps the terminal live and logs it.
# Ctrl+C is a normal stop, not a failure.
launch() { # <step> <command...>
  local step=$1 attempt=1 rc
  shift
  init_state || return 1
  while :; do
    : >"$LOG/$step.log"
    script -q "$LOG/$step.log" "$@"
    rc=$?
    if [ "$rc" = 0 ] || [ "$rc" = 130 ] ||
      ! grep -qE 'BUILD FAILED|FAILURE:|error: |CommandError|\*\* BUILD FAILED' "$LOG/$step.log"; then
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
    *) in_dir "${MOBILE_DIR:-.}" npx expo "$@" ;;
  esac
}

# ---------- diagnosis ----------

node_min() {
  local v
  v=$(sed -n 's/^v\{0,1\}\([0-9][0-9]*\).*/\1/p' .nvmrc 2>/dev/null | head -1)
  [ -n "$v" ] || v=$(sed -n 's/.*"node"[ ]*:[ ]*">=\([0-9][0-9]*\).*/\1/p' package.json 2>/dev/null | head -1)
  echo "${v:-18}"
}

deps_fresh() {
  case "$PM" in
    pnpm) [ -d node_modules/.pnpm ] && [ node_modules/.modules.yaml -nt pnpm-lock.yaml ] ;;
    yarn) [ -f node_modules/.yarn-integrity ] && [ node_modules/.yarn-integrity -nt yarn.lock ] ;;
    *) [ -f node_modules/.package-lock.json ] && [ node_modules/.package-lock.json -nt package-lock.json ] ;;
  esac
}

check_base() {
  local min have
  min=$(node_min)
  have=$(node -v 2>/dev/null | sed 's/^v//')
  if [ -n "$have" ] && [ "$(printf '%s\n%s\n' "$min" "${have%%.*}" | sort -n | head -1)" = "$min" ]; then
    ok "Node v$have"
  else need "Node $min" "brew install node@$min && brew link --overwrite --force node@$min"; fi
  if command -v python3 >/dev/null; then ok "Python $(python3 -V 2>&1 | cut -d' ' -f2)"; else need "Python 3" "brew install python"; fi
  case "$PM" in
    pnpm) if command -v pnpm >/dev/null; then ok "pnpm $(pnpm -v)"; else need "pnpm" "corepack enable"; fi ;;
    yarn) if command -v yarn >/dev/null; then ok "yarn $(yarn -v)"; else need "yarn" "corepack enable"; fi ;;
    *) command -v npm >/dev/null && ok "npm $(npm -v)" ;;
  esac
  if [ -n "$DB_SERVICE" ]; then
    if command -v docker >/dev/null; then ok "$(L 'Docker installed' 'Docker instalado')"
    else need "Docker Desktop" "brew install --cask docker"; fi
    if docker info >/dev/null 2>&1; then ok "$(L 'Docker running' 'Docker corriendo')"
    else need "$(L 'Docker Desktop open' 'Docker Desktop abierto')" "start_docker"; fi
  fi
  if deps_fresh; then ok "$(L 'dependencies' 'dependencias')"
  else
    case "$PM" in
      pnpm) need "$(L 'dependencies (pnpm install)' 'dependencias (pnpm install)')" "pnpm install --frozen-lockfile" ;;
      yarn) need "$(L 'dependencies (yarn install)' 'dependencias (yarn install)')" "yarn install --frozen-lockfile" ;;
      *) need "$(L 'dependencies (npm ci)' 'dependencias (npm ci)')" "npm ci" ;;
    esac
  fi
  if [ -n "$API_DIR" ]; then
    if [ -f "$API_DIR/.env" ]; then ok "$API_DIR/.env"
    else need "$API_DIR/.env $(L 'with local values' 'con valores locales')" "write_api_env"; fi
  fi
}

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
    PLAN_D=() PLAN_C=() BLOCKERS=()
    QUIET=$((pass - 1))
    setup_env
    [ "$pass" = 1 ] && say "$(L 'Diagnosis' 'Diagnóstico')"
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

start_backend() {
  [ -n "$API_DIR" ] || { warn "$(L 'no backend in [local] (api_dir is empty)' 'no hay backend en [local] (api_dir está vacío)')"; return 0; }
  say "$(L 'Database and API' 'Base de datos y API')"
  init_state || return 1
  local envfile=() _
  [ -f "$MAIN/.env" ] && envfile=(--env-file "$MAIN/.env")
  [ -f "$STATE/compose.env" ] && envfile=(--env-file "$STATE/compose.env")
  if [ -n "$DB_SERVICE" ]; then
    db_port "${envfile[@]}" || return 1
    [ -f "$STATE/compose.env" ] && envfile=(--env-file "$STATE/compose.env")
    # only the database: a compose file may also define the API itself
    run db docker compose "${envfile[@]}" up -d --wait "$DB_SERVICE" || return 1
  fi
  [ -n "$API_MIGRATE" ] && { run migrate bash -c "$API_MIGRATE" || return 1; }
  [ -n "$API_SEED" ] && { run seed bash -c "$API_SEED" || return 1; }
  if api_up; then ok "$(L "API already running on port $API_PORT" "API ya corriendo en el puerto $API_PORT")"; return 0; fi
  nohup bash -c "$API_START" >"$LOG/api.log" 2>&1 &
  for _ in $(seq 90); do # the first build takes a while
    api_up && { ok "$(L "API on port $API_PORT (log: $LOG/api.log)" "API en el puerto $API_PORT (log: $LOG/api.log)")"; return 0; }
    sleep 2
  done
  record_error api 1 "$LOG/api.log"
  return 1
}

stop_backend() {
  say "$(L 'Stop the API and the database' 'Detener API y base de datos')"
  setup_env
  # a watcher respawns its child: stop the listener's parents (pnpm, nest...) first
  local pid chain p
  pid=$(lsof -ti "tcp:$API_PORT" -sTCP:LISTEN 2>/dev/null | head -1)
  if [ -n "$pid" ]; then
    warn "$(L "port $API_PORT is used by: $(ps -o comm= -p "$pid")" "el puerto $API_PORT lo usa: $(ps -o comm= -p "$pid")")"
    if confirm "$(L 'Stop it?' '¿La detengo?')"; then
      chain=$pid
      p=$pid
      while p=$(ps -o ppid= -p "$p" | tr -d ' ') && ps -o command= -p "$p" | grep -qE 'node|pnpm|npm|yarn|nest|tsx'; do chain="$p $chain"; done
      # shellcheck disable=SC2086
      kill $chain 2>/dev/null && ok "$(L 'API stopped' 'API detenida')"
    fi
  fi
  if [ -n "$DB_SERVICE" ] && confirm "$(L "Stop the $DB_SERVICE container? (the data stays)" "¿Detengo el contenedor $DB_SERVICE? (los datos se conservan)")"; then
    local envfile=()
    [ -f "$MAIN/.env" ] && envfile=(--env-file "$MAIN/.env")
    [ -f "$STATE/compose.env" ] && envfile=(--env-file "$STATE/compose.env")
    docker compose "${envfile[@]}" stop "$DB_SERVICE" >/dev/null 2>&1 && ok "$(L "$DB_SERVICE stopped (the data stays)" "$DB_SERVICE detenido (los datos se conservan)")"
  fi
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

pick_android() { # sets A_SERIAL and A_MODEL; only physical devices, never an Android emulator
  local lines ready n i choice l
  while :; do
    lines=$(adb devices -l | grep -E '[[:space:]](device|unauthorized|offline)[[:space:]]' | grep -v '^emulator-')
    ready=$(grep -E '[[:space:]]device[[:space:]]' <<<"$lines")
    if [ -n "$ready" ]; then break; fi
    if grep -q unauthorized <<<"$lines"; then warn "$(L 'The phone asks for permission: unlock it and accept «Allow USB debugging».' 'El teléfono pide permiso: desbloquealo y aceptá «Permitir depuración USB».')"
    else warn "$(L 'No phone in sight. Connect it by USB (or pair it over Wi-Fi) with USB debugging on.' 'No veo ningún teléfono. Conectalo por USB (o emparejalo por Wi-Fi) con «Depuración USB» activada.')"; fi
    read -r -p "  $(L 'Enter to retry, q to quit: ' 'Enter para reintentar, q para salir: ')" choice || return 1
    [ "$choice" = q ] && return 1
  done
  n=$(grep -c . <<<"$ready")
  if [ "$n" -gt 1 ]; then
    i=0
    while read -r l; do i=$((i + 1)); printf '  %d) %s\n' "$i" "$l"; done <<<"$ready"
    read -r -p "  $(L 'Which one? ' '¿Cuál? ')" choice || return 1
    ready=$(sed -n "${choice:-1}p" <<<"$ready")
  fi
  A_SERIAL=$(awk '{print $1}' <<<"$ready")
  A_MODEL=$(sed -n 's/.*model:\([^ ]*\).*/\1/p' <<<"$ready")
  ok "$(L "phone: $A_MODEL ($A_SERIAL)" "teléfono: $A_MODEL ($A_SERIAL)")"
}

run_android() {
  ensure base android || return 1
  start_backend || return 1
  pick_android || return 1
  adb -s "$A_SERIAL" reverse tcp:8081 tcp:8081 || { bad "adb reverse failed"; return 1; }
  if [ -n "$API_DIR" ]; then
    adb -s "$A_SERIAL" reverse "tcp:$API_PORT" "tcp:$API_PORT" || { bad "adb reverse failed"; return 1; }
  fi
  free_port 8081 || return 1
  choose_client
  if [ "$USE_CLIENT" = dev-client ]; then
    say "$(L 'Building and installing on the phone (first time: 10–20 min; after that, fast). Ctrl+C stops Metro.' 'Compilando e instalando en el teléfono (la primera vez: 10–20 min; después, rápido). Ctrl+C detiene Metro.')"
    launch android env "$API_URL_ENV=$(api_url)" bash "$SELF" __expo run:android --device "$A_MODEL"
  else
    # UNTESTED: Expo Go on a real Android phone. Expo Go must come from the store; it is never installed from here.
    if ! adb -s "$A_SERIAL" shell pm list packages 2>/dev/null | grep -q host.exp.exponent; then
      bad "$(L 'Expo Go is not on the phone: install it from the Play Store and run again.' 'Expo Go no está en el teléfono: instalalo desde Play Store y volvé a correr.')"
      return 1
    fi
    say "$(L 'Opening in Expo Go. Ctrl+C stops Metro.' 'Abriendo en Expo Go. Ctrl+C detiene Metro.')"
    launch android env "$API_URL_ENV=$(api_url)" bash "$SELF" __expo start --android
  fi
}

pick_ios() { # sets I_UDID and I_NAME: the simulator you chose last time, or a menu; the others get shut down
  local last="" sims i=0 choice l
  [ -f $STATE/ios-device ] && last=$(cat $STATE/ios-device)
  sims=$(xcrun simctl list devices available | sed -nE 's/^ +(iPhone[^()]*[^ (]) \(([0-9A-F-]{36})\) \((Booted|Shutdown)\).*/\2 \1 (\3)/p')
  if [ -n "$last" ] && grep -q "^$last" <<<"$sims"; then
    I_UDID=$last
    ok "$(L "simulator: $(grep "^$last" <<<"$sims" | cut -d' ' -f2-) (to change it: rm $STATE/ios-device)" "simulador: $(grep "^$last" <<<"$sims" | cut -d' ' -f2-) (para cambiarlo: rm $STATE/ios-device)")"
  else
    while read -r l; do i=$((i + 1)); printf '  %d) %s\n' "$i" "${l#* }"; done <<<"$sims"
    read -r -p "  $(L 'Which simulator? [1] ' '¿Qué simulador? [1] ')" choice || return 1
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
  xcrun simctl boot "$I_UDID" 2>/dev/null # already booted is fine
  open -a Simulator
  xcrun simctl bootstatus "$I_UDID" -b >/dev/null
  free_port 8081 || return 1
  choose_client
  if [ "$USE_CLIENT" = dev-client ]; then
    strip_entitlements || return 1
    say "$(L 'Building and installing on the simulator (first time: 10–20 min). Ctrl+C stops Metro.' 'Compilando e instalando en el simulador (la primera vez: 10–20 min). Ctrl+C detiene Metro.')"
    launch ios env "$API_URL_ENV=$(api_url)" bash "$SELF" __expo run:ios --device "$I_NAME"
  else
    say "$(L 'Opening in Expo Go (it installs itself in the simulator). Ctrl+C stops Metro.' 'Abriendo en Expo Go (se instala solo en el simulador). Ctrl+C detiene Metro.')"
    launch ios env "$API_URL_ENV=$(api_url)" bash "$SELF" __expo start --ios
  fi
}

# ---------- entry ----------

# `launch` runs a program, not a shell function: it re-enters this script to reach `expo`.
if [ "${1:-}" = __expo ]; then shift; load_config; setup_env; expo "$@"; exit; fi

trap : INT # Ctrl+C stops the child (Metro), not this menu

main() {
  local arg
  for arg in "$@"; do
    case "$arg" in
      --yes) YES=1 ;;
      --check) CHECK=1 ;;
      --no-install) NOINSTALL=1 ;;
      -*) usage; exit 2 ;;
      *) [ -z "$CMD" ] && CMD=$arg || { usage; exit 2; } ;;
    esac
  done
  case "$CMD" in "" | android | ios | backend | doctor | stop | detect) ;; *) usage; exit 2 ;; esac
  if [ "$CMD" = detect ]; then
    command -v python3 >/dev/null || { echo "python3 is needed" >&2; exit 1; }
    detect_py json
    exit
  fi
  load_config
  if [ "$CMD" = doctor ] && [ "$CHECK" = 1 ]; then check_config; exit; fi
  if [ "$(uname -s)" != Darwin ]; then
    echo "$(L 'run-local runs on macOS only for now.' 'run-local solo corre en macOS por ahora.')"
    exit 0
  fi
  if [ "$HAS_LOCAL" = 0 ]; then
    setup_local
    case $? in 0) ;; 2) exit 0 ;; *) exit 1 ;; esac
  fi
  check_config || exit 1
  case "$CMD" in
    android) run_android ;;
    ios) run_ios ;;
    backend) ensure base && start_backend ;;
    doctor) ensure base android ios ;;
    stop) stop_backend ;;
    "")
      while :; do
        printf '\n\033[1m%s\033[0m\n  1) %s\n  2) %s\n  3) %s\n  4) %s\n  5) %s\n  q) %s\n' \
          "$(L 'Local environment' 'Entorno local')" "$(L 'Android: my phone' 'Android: mi teléfono')" "$(L 'iOS: simulator' 'iOS: simulador')" \
          "$(L 'Only the API and the database' 'Solo la API y la base de datos')" "$(L 'Diagnosis' 'Diagnóstico')" \
          "$(L 'Stop the API and the database' 'Detener API y base de datos')" "$(L 'Quit' 'Salir')"
        read -r -p "  $(L 'Choose: ' 'Elegí: ')" arg || break
        case "$arg" in
          1) run_android ;; 2) run_ios ;; 3) ensure base && start_backend ;;
          4) ensure base android ios ;; 5) stop_backend ;; q | Q | "") break ;;
        esac
      done ;;
  esac
}
[ -n "${RUN_LOCAL_LIB:-}" ] && return 0 # sourced by the tests: functions only
main "$@"
