#!/usr/bin/env python3
"""Keelokit harness health. Stdlib only (Python 3.11+ for tomllib).

    python3 .keelokit/bin/doctor.py            full report
    python3 .keelokit/bin/doctor.py --brief    where am I / what's next (SessionStart hook)
    python3 .keelokit/bin/doctor.py --ci       full report, exit 1 on any error
    python3 .keelokit/bin/doctor.py --scope ID files changed on this branch vs the story's `touches`,
                                               critical areas and acceptance tests
    python3 .keelokit/bin/doctor.py --critical [--changed]
                                               critical source files (all, or changed since main)

Without main or origin/main (a shallow CI checkout) nothing counts as done and the doctor says so,
`--scope` exits 2, and `--critical --changed` lists every critical file: never HEAD for main.

Checks: every MUST rule has an enforcer, and each enforcer looks alive (a test that cites the rule
and has active cases, a lint rule that is on, a CI job with real steps, no continue-on-error and no
`if: false` (bare, `${{ false }}` or quoted) at any indent, a git hook that is installed) unless an approved exception
is active; exceptions are complete and not expired; every file it reads is UTF-8 (TOML ones valid, with values of the kinds SHAPES
expects) and every path it looks up from them (enforcers, `when`, critical areas) stays inside the
repo, or that is an error too, never a crash; docs/context is complete, precise and its gaps are
tracked; every invariant in domain.md has an id and a class; critical areas point at real paths;
backlog stories are well-formed, stories in one wave don't touch the same paths or the same
critical area, a story touching a critical area declares `integrity` and its invariants, and every
scenario and invariant of a done story is cited by an active test title; the escape log names the
check each escaped bug left behind. A story is done when a commit reachable from main carries the
trailer `Story: <ID>` — status is never stored in a file.
"""
import sys

if sys.version_info < (3, 11):
    print(f"Keelokit needs Python 3.11+ (found {sys.version.split()[0]}); doctor and guard are off.")
    sys.exit(1)

import datetime as dt  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
import tomllib  # noqa: E402
from pathlib import Path  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CONTEXT_FILES = ["product.md", "domain.md", "constraints.md", "environments.md", "gaps.md"]
VAGUE = [
    "best practices", "clean code", "as appropriate", "where possible", "if needed", "etc.",
    "and so on", "robust", "industry standard", "properly", "reasonable", "state of the art",
    "user-friendly", "buenas prácticas", "código limpio", "según corresponda", "si aplica",
    "adecuado", "amigable",
]
GAP_RE = re.compile(r"\[(GAP-\d+)\]")  # inline marker in a context file
GAP_ROW_RE = re.compile(r"^\|\s*(GAP-\d+)\s*\|")  # row in gaps.md
STORY_ID_RE = re.compile(r"^[A-Z][A-Z0-9]*-\d{3}$")
# What a story may touch; each one pulls its checks into the story's contract (skills/build).
DIMENSIONS = {
    "data", "api", "contract", "logic", "integrity", "auth", "ux", "ui", "web", "mobile", "i18n",
    "copy", "a11y", "security", "nfr", "config", "ops", "dx", "docs", "packaging",
}
# Invariant classes (references/invariants.md in the plugin): each one fixes the kind of test that
# proves it — a property test, a concurrency test, a replay test, a transition table.
INVARIANT_CLASSES = {"conservation", "once", "limit", "transition", "isolation", "time", "consistency"}
# `- [INV-001] [MUST] … — class: conservation (S1)` in docs/context/domain.md defines an invariant.
INV_DEF_RE = re.compile(r"(?m)^\s*[-*]\s*\[(INV-\d{3})\](.*)$")
INV_CLASS_RE = re.compile(r"\bclass:\s*([a-z]+)")
ESCAPE_ROW_RE = re.compile(r"^\|\s*(ESC-\d{3})\s*\|")
SOURCE_RE = re.compile(r"\.[cm]?[jt]sx?$")
SCENARIO_RE = re.compile(r"(?im)^\s*(?:scenario|escenario)[^:\n]*:\s*\[(S\d+)\]")
TEST_FILE_RE = re.compile(r"(\.(test|spec)\.[cm]?[jt]sx?$)|(/e2e/.*\.[jt]s$)")
# Title of an active test/describe call. `.skip`, `.todo`, `xit` and friends never match, so a
# skipped test (or a comment) can't satisfy a rule or a scenario.
TEST_TITLE_RE = re.compile(
    r"(?<![\w.])(?:it|test|describe|test\.describe)"
    r"(?:\.(?:only|concurrent|serial|parallel|each\((?:[^()]|\([^()]*\))*\)))*\s*\(\s*(['\"`])((?:\\.|(?!\1).)*)\1",
    re.S,
)
# What a project can be (.keelokit/profile.toml `traits`). A rule with `needs` applies only when the
# profile lists every trait it needs, so a plugin without UI or hosting isn't held to UI or deploy
# rules. No profile file → every rule applies (projects from before profiles).
TRAITS = {
    "typescript", "ui", "web", "mobile", "site", "api", "database", "hosted", "i18n",
    "personal-data", "payments", "developer-facing",
}
# What in the repo shows a trait. The doctor warns when the repo shows one the profile lacks, or
# the profile lists a structural one nothing in the repo backs — the profile has to keep up.
TRAIT_EVIDENCE = {
    "typescript": ["tsconfig.json", "tsconfig.base.json"],
    "api": ["apps/api", "nest-cli.json"],
    "database": ["prisma/schema.prisma", "apps/*/prisma/schema.prisma", "alembic.ini", "db/migrations", "migrations"],
    "web": ["apps/web", "vite.config.ts", "next.config.js", "next.config.mjs", "next.config.ts"],
    "mobile": ["apps/mobile", "app.json", "eas.json"],
    "site": ["apps/site", "astro.config.mjs"],
    "hosted": ["fly.toml", "apps/*/fly.*.toml", "Dockerfile", "vercel.json", "netlify.toml", "render.yaml", "Procfile"],
}
STRUCTURAL = {"api", "database", "web", "mobile", "site"}  # hosted: a static host may leave nothing in the repo
# How --brief words each kind of drift. The dashboard reads these lines back into (trait, path) and
# says them in the page's language (I18N-1), so a change here needs one in its DRIFT_LINES too.
DRIFT_SEEN = "the repo shows `{trait}` ({seen}) but the profile doesn't list it"
DRIFT_MISSING = "the profile lists `{trait}` but nothing in the repo shows it yet"

# What each TOML file the doctor reads may hold (top-level keys, then each [[entry]]'s): key → the
# kinds of value it accepts. People and agents edit these files by hand, so a value of another kind
# is an ERROR that names the file and the key, and that value or entry is left out; never a
# traceback (INT-2). tests/test_doctor.py holds every key the templates document to a shape here.
KINDS = {
    "text": ("text", lambda v: isinstance(v, str)),
    "texts": ("a list of text", lambda v: isinstance(v, list) and all(isinstance(x, str) for x in v)),
    "whole": ("a whole number", lambda v: isinstance(v, int) and not isinstance(v, bool)),
    "date": ("a date", lambda v: isinstance(v, dt.date) and not isinstance(v, dt.datetime)),
    "table": ("a table", lambda v: isinstance(v, dict)),
    "tables": ("a list of tables", lambda v: isinstance(v, list) and all(isinstance(x, dict) for x in v)),
}
RULE_SHAPE = {"id": "text", "level": "text", "rule": "text", "why": "text", "enforced_by": "texts",
              "when": "text|texts", "needs": "texts"}
SHAPES = {
    ".keelokit/harness/rules.toml": ({"rule": "tables"}, {"rule": RULE_SHAPE}),
    ".keelokit/rules.local.toml": ({"rule": "tables"}, {"rule": RULE_SHAPE}),
    ".keelokit/exceptions.toml": ({"exception": "tables"},
                                  {"exception": {"rule": "text", "reason": "text", "approver": "text", "expires": "text|date"}}),
    ".keelokit/profile.toml": ({"kind": "text", "traits": "texts"}, {}),
    ".keelokit/critical.toml": ({"mutation_break": "whole", "area": "tables"},
                                {"area": {"name": "text", "why": "text", "paths": "texts"}}),
    ".keelokit/state.toml": ({"gates": "table"}, {}),
    # Story front matter (backlog/README.md).
    "backlog/stories/*.md": ({"id": "text", "epic": "text", "title": "text", "wave": "whole", "depends_on": "texts",
                              "touches": "texts", "dimensions": "texts", "invariants": "texts", "origin": "text"}, {}),
}

GATES = {
    "project": ["intake", "product", "stack", "skeleton", "backlog"],  # /keelokit:project-new
    "harness": ["intake", "adopt", "backlog"],  # /keelokit:project-adopt on an existing repo
}

errors: list[str] = []
warnings: list[str] = []
profile_drift: list[tuple[str, str | None]] = []  # (trait, what shows it, or None)
not_applicable: list[str] = []


def misshapen(table: dict, shape: dict[str, str]) -> dict[str, str]:
    """Each key of `table` whose value isn't a kind `shape` allows → "'wave' must be a whole number (found '2')"."""
    return {
        key: f"'{key}' must be {' or '.join(KINDS[k][0] for k in allowed.split('|'))} (found {repr(table[key])[:60]})"
        for key, allowed in shape.items()
        if key in table and not any(KINDS[k][1](table[key]) for k in allowed.split("|"))
    }


def rel(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def read_file(path: Path, lenient: bool = False) -> tuple[str | None, str | None]:
    """(text, None), or (None, why) when the file can't be read: a directory, bytes that aren't UTF-8
    (a file saved as Latin-1), no permission. The doctor reads every file through here, so a
    hand-edited one is an error that names it, never a traceback (INT-2). `lenient` drops the bytes
    that aren't UTF-8 instead (source files it only scans for test titles)."""
    try:
        return path.read_text(encoding="utf-8", errors="ignore" if lenient else "strict"), None
    except UnicodeDecodeError as e:
        return None, f"{rel(path)}: not UTF-8 (byte {e.object[e.start]:#04x} at offset {e.start}); save it as UTF-8"
    except IsADirectoryError:
        return None, f"{rel(path)}: is a directory, not a file"
    except (OSError, ValueError) as e:
        return None, f"{rel(path)}: can't be read ({getattr(e, 'strerror', None) or e})"


def read(path: Path, lenient: bool = False) -> str | None:
    """The text of a file, or None with the reason among the errors (once)."""
    text, why = read_file(path, lenient)
    if why and why not in errors:
        errors.append(why)
    return text


def outside(value: str) -> str | None:
    """Why a path from a hand-edited file (an enforcer, `when`, a critical area) isn't one inside the
    repo, or None when it is: absolute paths, `..`, empty ones and NULs read outside it or crash."""
    if not value.strip():
        return "is empty"
    if "\0" in value:
        return "contains a NUL character"
    if value.startswith(("/", "\\")) or re.match(r"[A-Za-z]:[\\/]", value):
        return "must be a path relative to the repo root"
    if ".." in re.split(r"[\\/]", value):
        return "must stay inside the repo (no '..')"
    return None


def repo_glob(pattern: str) -> tuple[list[Path], str | None]:
    """The files (not directories) a glob from a hand-edited file matches, or why it can't be used."""
    if why := outside(pattern):
        return [], why
    try:
        return [p for p in ROOT.glob(pattern) if p.is_file()], None
    except (ValueError, NotImplementedError, OSError) as e:  # 'a/**b', a pattern pathlib refuses
        return [], f"is not a glob pathlib accepts ({e})"


def read_toml(path: Path, shape: str) -> dict | None:
    """A TOML file, keeping only the values SHAPES[shape] allows; anything else is an error that names
    the file and is left out. None when the file is missing, unreadable or isn't valid TOML."""
    if not path.exists() or (text := read(path)) is None:
        return None
    name = rel(path)
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        errors.append(f"{name}: invalid TOML ({e})")
        return None
    top, entries = SHAPES[shape]
    bad = misshapen(data, top)
    errors.extend(f"{name}: {why}" for why in bad.values())
    data = {k: v for k, v in data.items() if k not in bad}
    for key, entry_shape in entries.items():
        kept = []
        for i, entry in enumerate(data.get(key, []), 1):
            if bad := misshapen(entry, entry_shape):
                errors.append(f"{name}: [[{key}]] #{i}: {'; '.join(bad.values())}")
            else:
                kept.append(entry)
        data[key] = kept
    return data


def load_toml(path: Path, key: str) -> list[dict]:
    return (read_toml(path, path.relative_to(ROOT).as_posix()) or {}).get(key, [])


def git(*args: str) -> str:
    out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    return out.stdout if out.returncode == 0 else ""


NO_MAIN = "no main or origin/main to {what}; fetch it (CI: fetch-depth: 0)"


def main_ref() -> str | None:
    """origin/main, else main; None when neither resolves (a shallow CI checkout, a detached HEAD).
    Never HEAD: a branch's own `Story:` trailers would count as done and its diffs come out empty."""
    for ref in ("origin/main", "main"):
        if git("rev-parse", "--verify", "--quiet", ref).strip():
            return ref
    return None


def main_base() -> str | None:
    """Where this branch left main (the merge base), or None when main or the shared history is missing."""
    ref = main_ref()
    return (git("merge-base", ref, "HEAD").strip() or None) if ref else None


def ci_job(job: str) -> str | None:
    """The text of a job under `jobs:` in any workflow, or None. The jobs sit at the indent of the
    first one, whatever the file uses (LOG-202), and a job ends at the next line no deeper than its
    name; comment lines don't end it, and keys under `on:` or elsewhere are never jobs."""
    for path in (ROOT / ".github/workflows").glob("*.y*ml"):
        jobs = re.search(r"(?ms)^jobs:[ \t]*(?:#[^\n]*)?\n(.*?)(?=^[^\s#]|\Z)", read(path) or "")
        indent = jobs and re.search(r"(?m)^( +)[^\s#]", jobs.group(1))
        if not indent:
            continue
        n = len(indent.group(1))
        m = re.search(rf"(?ms)^ {{{n}}}{re.escape(job)}:[ \t]*(?:#[^\n]*)?\n(.*?)(?=^ {{0,{n}}}[^\s#]|\Z)", jobs.group(1))
        if m:
            return m.group(1)
    return None


# How to run the doctor in any repo that has it: pnpm has its own `doctor` command (so that never runs
# the package script), and an adopted repo may have no package.json at all (CPY-1).
DOCTOR_CMD = "python3 .keelokit/bin/doctor.py"
LOCKFILES = {"pnpm-lock.yaml": "pnpm", "pnpm-workspace.yaml": "pnpm", "yarn.lock": "yarn", "bun.lock": "bun",
             "bun.lockb": "bun", "package-lock.json": "npm"}


def hook_remedy(hooks_dir: str, target: str) -> str:
    """How a human installs a missing git hook in this repo, naming only commands it has (CPY-1): the
    package manager's install when a package.json script sets the hooks up (`prepare` in a generated
    project, husky), else the hooks path when the repo ships the hook, else what to add."""
    text, _ = read_file(ROOT / "package.json")  # the product's file: unreadable just means no install step
    try:
        pkg = json.loads(text) if text else {}
    except ValueError:
        pkg = {}
    scripts = pkg.get("scripts") if isinstance(pkg, dict) else None
    scripts = scripts if isinstance(scripts, dict) else {}
    installs = [v for k, v in scripts.items() if k in ("preinstall", "install", "postinstall", "prepare")]
    if any(isinstance(v, str) and re.search(r"(?i)hookspath|husky|lefthook|simple-git-hooks", v) for v in installs):
        declared = pkg.get("packageManager")  # "pnpm@10.33.0"
        pm = declared.partition("@")[0] if isinstance(declared, str) else ""
        if pm not in LOCKFILES.values():
            pm = next((m for f, m in LOCKFILES.items() if (ROOT / f).is_file()), "npm")
        return f"run `{pm} install`"
    for d in (".githooks", ".husky"):
        if d != hooks_dir and (ROOT / d / target).is_file():
            return f"a human runs `git config core.hooksPath {d}`"
    return add_hook(f"add a '{target}' hook", target)


def add_hook(what: str, target: str) -> str:
    """The fix-it tail when the hook itself has to be written: what it runs, or the way out."""
    guard = " that runs `python3 .keelokit/bin/guard.py git-pre-commit`" if target == "pre-commit" else ""
    return f"{what}{guard}, or map or except the rule with /keelokit:check-health"


def hook_problem(target: str) -> str | None:
    """Why git won't run the hook `target` in this repo, or None when it will (LOG-207). Git runs
    only the file of that name in its hooks path (core.hooksPath, else the .git/hooks that linked
    worktrees share), and only when it's executable; an empty one checks nothing. A stray file of
    that name anywhere else, .husky/ included, is never run. husky v9 sets the hooks path to
    .husky/_, whose wrappers run .husky/<name> (sourced, so it needn't be executable) and succeed
    without a word when it's missing or empty."""
    hooks_dir = git("rev-parse", "--git-path", "hooks").strip() or ".git/hooks"
    hook = ROOT / hooks_dir / target
    if not hook.is_file():
        return f"git hook '{target}' is not installed (hooksPath: {hooks_dir}; {hook_remedy(hooks_dir, target)})"
    shown = rel(hook)
    text, why = read_file(hook, lenient=True)
    if why:
        return why
    if not text.strip():
        return f"git hook '{shown}' is empty, so it checks nothing ({add_hook('write the hook', target)})"
    if not os.access(hook, os.X_OK):
        return f"git hook '{shown}' is not executable, so git never runs it (a human runs `chmod +x {shown}`)"
    if (ROOT / hooks_dir).resolve() == (ROOT / ".husky/_").resolve():
        user = ROOT / ".husky" / target
        text, why = read_file(user, lenient=True) if user.is_file() else ("", None)
        if why:
            return why
        if not text.strip():
            state = "empty" if user.is_file() else "missing"
            return f"husky runs '.husky/{target}', which is {state} ({add_hook(f'add .husky/{target}', target)})"
    return None


SETUP_STEPS = re.compile(r"(checkout|setup-node|action-setup|setup-uv|setup-python|upload-artifact|cache)@")
# A YAML value GitHub Actions always reads as true or false, in each spelling (LOG-202): true, True,
# ${{ true }}, each bare or inside a matching quote ('true', "${{ true }}": YAML drops the quotes).
# An expression such as ${{ matrix.experimental }} is neither.
ALWAYS = {v: rf"(?i:(?P<q>['\"]?)(?:{v}|\$\{{\{{\s*{v}\s*\}}\}})(?P=q))[ \t]*(?:#.*)?$" for v in ("true", "false")}


def test_titles(text: str) -> list[str]:
    return [m.group(2) for m in TEST_TITLE_RE.finditer(text)]


def enforcer_problem(rid: str, ref: str) -> str | None:
    """Why this enforcer can't be trusted to enforce the rule, or None if it looks alive."""
    kind, _, target = ref.partition(":")
    if kind in ("test", "file", "script", "claude-hook", "git-hook"):
        path = target.partition("#")[0] if kind in ("file", "script") else target
        if why := outside(path):
            return f"'{path}' {why}"
    if kind == "ci":
        block = ci_job(target)
        if block is None:
            return f"CI job '{target}' does not exist"
        if re.search(rf"(?m)^\s*continue-on-error:[ \t]*{ALWAYS['true']}", block):
            return f"CI job '{target}' has continue-on-error"
        key = re.match(r"(?:[ \t]*(?:#.*)?\n)*( *)", block).group(1)  # the indent of the job's own keys
        if re.search(rf"(?m)^{key}if:[ \t]*{ALWAYS['false']}", block):
            return f"CI job '{target}' never runs (if: false)"
        steps = re.findall(r"(?m)^\s*-?\s*(?:run|uses):\s*(.+)$", block)
        real = [s for s in steps if not SETUP_STEPS.search(s) and s.strip().strip("'\"") not in ("true", "exit 0", ":", "")]
        return None if real else f"CI job '{target}' has no real step"
    if kind == "git-hook":
        return hook_problem(target)
    if kind == "claude-hook":
        return None if (ROOT / ".keelokit/bin" / target).exists() else f"'.keelokit/bin/{target}' is missing"
    if kind == "test":
        if any(c in target for c in "*?["):
            files, why = repo_glob(target)
            if why:
                return f"'{target}' {why}"
        elif (ROOT / target).is_dir():
            return f"'{target}' is a directory: name a test file, or a glob such as '{target.rstrip('/')}/**/*.spec.ts'"
        else:
            files = [ROOT / target] if (ROOT / target).exists() else []
        if not files:
            return f"no test at '{target}'"
        # A glob (apps/*/e2e/*.spec.ts) is satisfied when at least one match names the rule and
        # has an active test; a plain path must do both itself.
        texts = {f: t for f in files if (t := read_file(f, lenient=True)[0]) is not None}
        live = [f for f, t in texts.items() if re.search(rf"\b{re.escape(rid)}\b", t) and test_titles(t)]
        if live:
            return None
        rel = ", ".join(str(f.relative_to(ROOT)) for f in files)
        return f"{rel}: no active test that names {rid} (add a comment or title citing it)"
    if kind == "lint":
        configs = [*ROOT.glob("eslint.config.*"), *ROOT.glob(".eslintrc*")]
        texts = [t for c in configs if (t := read(c)) is not None]
        rule = re.escape(target)
        if any(re.search(rf"['\"]{rule}['\"]\s*:\s*\[?\s*['\"]?(off|0)\b", t) for t in texts):
            return f"lint rule '{target}' is turned off somewhere"
        on = any(re.search(rf"['\"]{rule}['\"]\s*:\s*\[?\s*['\"]?(error|warn|2|1)\b", t) for t in texts)
        return None if on else f"lint rule '{target}' is not enabled"
    if kind in ("script", "file"):
        path, _, needle = target.partition("#")  # file:tsconfig.base.json#"strict": true
        if not (ROOT / path).exists():
            return f"'{path}' does not exist"
        if needle:
            text, why = read_file(ROOT / path)
            if why:
                return why
            if needle not in text:
                return f"'{path}' does not contain {needle}"
        return None
    if kind == "review":
        return None if target else "review enforcer needs an agent name"
    return f"unknown enforcer kind '{kind}'"


def load_rules() -> dict[str, dict]:
    """House rules, plus local ones. A local entry with a house rule's id may only remap that
    rule's enforcers to checks this repo already has (how /keelokit:project-adopt fits existing repos)."""
    rules: dict[str, dict] = {}
    for r in load_toml(ROOT / ".keelokit/harness/rules.toml", "rule"):
        if r.get("id") in rules:
            errors.append(f"rule {r.get('id')}: duplicate id")
        rules[r.get("id", "?")] = {**r, "origin": "house"}
    for r in load_toml(ROOT / ".keelokit/rules.local.toml", "rule"):
        rid = r.get("id", "?")
        if rules.get(rid, {}).get("origin") == "house":
            extra = sorted(set(r) - {"id", "enforced_by"})
            if extra:
                errors.append(f"rule {rid}: a local entry for a house rule may only set enforced_by (found {', '.join(extra)})")
            rules[rid]["enforced_by"] = r.get("enforced_by", [])
        elif rid in rules:
            errors.append(f"rule {rid}: duplicate id")
        else:
            rules[rid] = {**r, "origin": "local"}
    return rules


def check_exceptions(rule_ids: set[str]) -> set[str]:
    """Returns the rules with an active exception."""
    today = dt.date.today()
    active = set()
    for e in load_toml(ROOT / ".keelokit/exceptions.toml", "exception"):
        rid = e.get("rule", "?")
        missing = [k for k in ("rule", "reason", "approver", "expires") if not e.get(k)]
        if missing:
            errors.append(f"exception for {rid}: missing {', '.join(missing)}")
            continue
        if rid not in rule_ids:
            errors.append(f"exception for {rid}: no such rule")
        expires = e["expires"]
        if expires != "permanent":
            if isinstance(expires, str):
                try:
                    expires = dt.date.fromisoformat(expires)
                except ValueError:
                    errors.append(f"exception for {rid}: 'expires' is not a date (YYYY-MM-DD) or 'permanent' ({expires!r})")
                    continue
            if expires < today:
                errors.append(f"exception for {rid}: expired on {expires}")
                continue
        active.add(rid)
        warnings.append(f"exception for {rid} until {expires}: {e['reason']}")
    return active


def drift_text(trait: str, seen: str | None) -> str:
    return DRIFT_SEEN.format(trait=trait, seen=seen) if seen else DRIFT_MISSING.format(trait=trait)


def load_profile() -> dict | None:
    """.keelokit/profile.toml: the project's kind and traits, and whether the repo still matches them."""
    path = ROOT / ".keelokit/profile.toml"
    if not path.exists():
        return None
    if (profile := read_toml(path, ".keelokit/profile.toml")) is None:
        return None
    traits = set(profile.get("traits", []))
    if profile.get("kind", "unknown") == "unknown":
        errors.append(".keelokit/profile.toml: the project's kind isn't diagnosed yet — /keelokit:project-adopt or /keelokit:check-health writes it")
    if unknown := traits - TRAITS:
        errors.append(f".keelokit/profile.toml: unknown traits {', '.join(sorted(unknown))} (known: {', '.join(sorted(TRAITS))})")
    for trait, patterns in TRAIT_EVIDENCE.items():
        seen = next((m.relative_to(ROOT).as_posix() for pat in patterns for m in ROOT.glob(pat)
                     if "node_modules" not in m.parts), None)
        if seen and trait not in traits:
            profile_drift.append((trait, seen))
        elif trait in traits and trait in STRUCTURAL and not seen and profile.get("kind") != "unknown":
            profile_drift.append((trait, None))
    for d in profile_drift:
        warnings.append(f"profile: {drift_text(*d)} — update .keelokit/profile.toml")
    return {**profile, "traits": traits}


def check_rules(rules: dict[str, dict], excepted: set[str], profile: dict | None = None) -> None:
    for rid, r in rules.items():
        when = r.get("when")
        whens = [when] if isinstance(when, str) else when or []
        if bad := [f"'{w}' {why}" for w in whens if (why := outside(w))]:
            errors.append(f"rule {rid}: when {', '.join(bad)}")
        if when and not any((ROOT / w).exists() for w in whens if not outside(w)):
            continue
        if profile is not None and not set(r.get("needs", [])) <= profile["traits"]:
            not_applicable.append(rid)
            continue
        refs = r.get("enforced_by", [])
        must = r.get("level", "").startswith("MUST")
        problems = []
        if must and not refs:
            problems.append("MUST rule without an enforcer")
        problems += [p for ref in refs if (p := enforcer_problem(rid, ref))]
        for problem in problems:
            # An approved, unexpired exception keeps the debt visible without turning CI red.
            (warnings if rid in excepted else errors).append(
                f"rule {rid}: {problem}" + (" (excepted)" if rid in excepted else "")
            )
        if must and refs and all(ref.startswith("review:") for ref in refs):
            warnings.append(f"rule {rid}: MUST rule enforced only by review (inferential)")


def check_context() -> tuple[int, int]:
    ctx = ROOT / "docs/context"
    missing = [f for f in CONTEXT_FILES if not (ctx / f).exists()]
    if missing:
        errors.append(f"docs/context missing {', '.join(missing)} — run the intake (/keelokit:plan-intake)")
        return 0, 0
    gaps_text = read(ctx / "gaps.md") or ""
    tracked = {m.group(1): line for line in gaps_text.splitlines() if (m := GAP_ROW_RE.match(line))}
    for f in CONTEXT_FILES[:-1]:
        if (text := read(ctx / f)) is None:
            continue
        low = re.sub(r"(?s)<!--.*?-->", "", text).lower()
        for phrase in VAGUE:
            if phrase in low:
                errors.append(f"docs/context/{f}: vague phrase '{phrase}' — replace with a number, name or check")
        for gid in set(GAP_RE.findall(text)) - tracked.keys():
            errors.append(f"docs/context/{f}: {gid} is not listed in gaps.md")
    blocking = sum(1 for line in tracked.values() if re.search(r"\|\s*yes\s*\|?\s*$", line, re.I))
    return len(tracked), blocking


def check_invariants() -> dict[str, str]:
    """Invariants defined in docs/context/domain.md, id → class."""
    path = ROOT / "docs/context/domain.md"
    found: dict[str, str] = {}
    if not path.exists() or (text := read(path)) is None:
        return found
    text = re.sub(r"(?s)<!--.*?-->", "", text)
    for iid, rest in INV_DEF_RE.findall(text):
        m = INV_CLASS_RE.search(rest)
        if iid in found:
            errors.append(f"docs/context/domain.md: {iid} is defined twice")
        if not m or m.group(1) not in INVARIANT_CLASSES:
            errors.append(f"docs/context/domain.md: {iid} needs 'class: <{'|'.join(sorted(INVARIANT_CLASSES))}>'")
        found[iid] = m.group(1) if m else "?"
    return found


def load_critical() -> tuple[list[dict], int]:
    """Critical areas from .keelokit/critical.toml, and the mutation score that fails the build."""
    path = ROOT / ".keelokit/critical.toml"
    if not path.exists():
        return [], 0
    if (data := read_toml(path, ".keelokit/critical.toml")) is None:
        return [], 0
    threshold = data.get("mutation_break", 70)  # scripts/mutation.sh uses the same default
    if not isinstance(threshold, int) or not 0 <= threshold <= 100:
        errors.append(".keelokit/critical.toml: mutation_break must be a whole percentage (0-100)")
        threshold = 70
    areas = []
    for a in data.get("area", []):
        name = a.get("name", "?")
        if not a.get("name") or not a.get("why") or not a.get("paths"):
            errors.append(f".keelokit/critical.toml: area '{name}' needs name, why and paths")
            continue
        paths = []
        for p in a["paths"]:
            if why := outside(p):
                errors.append(f".keelokit/critical.toml: area '{name}' path '{p}' {why}")
                continue
            if not (ROOT / p).exists():
                errors.append(f".keelokit/critical.toml: area '{name}' points at '{p}', which does not exist")
            paths.append(p)
        areas.append({**a, "paths": paths})
    return areas, threshold


def areas_hit(paths: list[str], areas: list[dict]) -> list[str]:
    return [a["name"] for a in areas if any(overlaps(p, q) for p in paths for q in a["paths"])]


def critical_files(areas: list[dict]) -> list[str]:
    """Source files (not tests) under the critical areas."""
    files = set()
    for a in areas:
        for p in a["paths"]:
            path = ROOT / p
            for f in path.rglob("*") if path.is_dir() else [path]:
                rel = f.relative_to(ROOT).as_posix()
                if (f.is_file() and SOURCE_RE.search(rel) and not TEST_FILE_RE.search(rel)
                        and not rel.endswith(".d.ts")
                        and not re.search(r"(^|/)(node_modules|dist|generated)/", rel)):
                    files.add(rel)
    return sorted(files)


def check_escapes() -> int:
    """docs/escapes.md: every bug that got past a story's own tests, and the check it left behind."""
    path = ROOT / "docs/escapes.md"
    if not path.exists():
        return 0
    rows = 0
    for line in (read(path) or "").splitlines():
        if not (m := ESCAPE_ROW_RE.match(line)):
            continue
        rows += 1
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 6 or not all(cells[:6]):
            errors.append(f"docs/escapes.md: {m.group(1)} needs id, date, found by, what escaped, class and check added")
    return rows


def done_story_ids() -> set[str]:
    """Stories closed by a `Story: <ID>` trailer on a commit reachable from main."""
    if (ref := main_ref()) is None:
        if git("rev-parse", "--verify", "--quiet", "HEAD").strip():
            errors.append(NO_MAIN.format(what="count done stories from"))
        return set()
    trailers = git("log", ref, "--format=%(trailers:key=Story,valueonly,separator=%x2C)")
    return {sid.strip() for line in trailers.splitlines() for sid in line.split(",") if sid.strip()}


def read_story(path: Path) -> dict | None:
    if (text := read(path)) is None:
        return None
    m = re.match(r"\+\+\+\n(.*?)\n\+\+\+(?:\n|$)", text, re.S)
    if not m:
        if not re.match(r"\ufeff?\+\+\+[ \t]*(?:\n|$)", text):
            # No `+++` first line: not a Keelokit story (an adopted repo's own tickets, a README).
            # The dashboard doesn't list it either (INT-202).
            warnings.append(f"{path.relative_to(ROOT)}: not a Keelokit story (no +++ front matter), ignored")
            return None
        errors.append(f"{path.relative_to(ROOT)}: +++ front matter must be a '+++' line, TOML, then a '+++' line"
                      " (no BOM, no spaces after +++)")
        return None
    try:
        meta = tomllib.loads(m.group(1))
    except tomllib.TOMLDecodeError as e:
        errors.append(f"{path.relative_to(ROOT)}: invalid front matter ({e})")
        return None
    if bad := misshapen(meta, SHAPES["backlog/stories/*.md"][0]):
        errors.append(f"{path.relative_to(ROOT)}: front matter {'; '.join(bad.values())}")
        return None
    meta["_scenarios"] = SCENARIO_RE.findall(text[m.end():])
    return meta


def cited_titles() -> str:
    """Active test titles across the repo, for TRACE-1."""
    titles = []
    for base in ("apps", "packages", "e2e"):
        for path in (ROOT / base).rglob("*") if (ROOT / base).exists() else []:
            rel = path.relative_to(ROOT).as_posix()
            if path.is_file() and "node_modules" not in rel and TEST_FILE_RE.search(rel):
                titles += test_titles(read(path, lenient=True) or "")
    return "\n".join(titles)


def overlaps(a: str, b: str) -> bool:
    a, b = a.rstrip("/"), b.rstrip("/")
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")


def ancestors(path: str) -> list[str]:
    """Every b with overlaps(path, b) because path lies under it: 'a/b/c' → ['a', 'a/b']."""
    return [path[:k] for k, c in enumerate(path) if c == "/"]


def wave_clashes(pending: list[str], stories: dict, areas: list[dict]) -> list[tuple[str, str]]:
    """Pairs of pending stories (in `pending` order) that share a wave and a path or critical area.
    Found through an index of paths and areas per wave, not by comparing every pair: the
    SessionStart `--brief` runs this on every backlog, however big (NFR-1)."""
    order = {sid: i for i, sid in enumerate(pending)}
    waves: dict = {}
    for sid in pending:
        waves.setdefault(stories[sid].get("wave"), []).append(sid)
    pairs = set()
    for group in waves.values():
        exact: dict[str, set] = {}  # path → stories that touch it
        under: dict[str, set] = {}  # path → stories that touch something under it
        in_area: dict[str, set] = {}  # critical area → stories that touch it
        for sid in group:
            for t in stories[sid].get("touches", []):
                exact.setdefault(t := t.rstrip("/"), set()).add(sid)
                for up in ancestors(t):
                    under.setdefault(up, set()).add(sid)
            for name in areas_hit(stories[sid].get("touches", []), areas):
                in_area.setdefault(name, set()).add(sid)
        for sid in group:
            near = set()
            for t in stories[sid].get("touches", []):
                near |= exact.get(t := t.rstrip("/"), set()) | under.get(t, set())
                for up in ancestors(t):
                    near |= exact.get(up, set())
            for sids in in_area.values():
                if sid in sids:
                    near |= sids
            pairs |= {(sid, o) for o in near if order[o] > order[sid]}
    return sorted(pairs, key=lambda p: (order[p[0]], order[p[1]]))


def check_backlog(invariants: dict[str, str], areas: list[dict]) -> dict:
    stories = {}
    for path in sorted((ROOT / "backlog/stories").glob("*.md")):
        meta = read_story(path)
        if meta is None:
            continue
        sid = meta.get("id", "")
        rel = path.relative_to(ROOT)
        if not STORY_ID_RE.match(sid):
            errors.append(f"{rel}: id '{sid}' must look like AUTH-001")
        if not path.name.startswith(sid + "-"):
            errors.append(f"{rel}: file name must start with '{sid}-'")
        if "status" in meta:
            errors.append(f"{rel}: remove 'status' — status comes from git")
        if sid in stories:
            errors.append(f"{rel}: duplicate id {sid}")
        stories[sid] = meta
    done = done_story_ids() & stories.keys() if stories else set()
    for sid, meta in stories.items():
        for dep in meta.get("depends_on", []):
            if dep not in stories:
                errors.append(f"story {sid}: depends_on unknown story {dep}")
        dims = meta.get("dimensions")
        if not dims:
            errors.append(f"story {sid}: list its impact 'dimensions' ({', '.join(sorted(DIMENSIONS))})")
        elif unknown := set(dims) - DIMENSIONS:
            errors.append(f"story {sid}: unknown dimensions {', '.join(sorted(unknown))}")
        if not meta["_scenarios"]:
            errors.append(f"story {sid}: acceptance criteria need scenario ids, e.g. 'Scenario: [S1] …'")
        invs = meta.get("invariants", [])
        if unknown := [i for i in invs if i not in invariants]:
            errors.append(f"story {sid}: invariants {', '.join(unknown)} are not defined in docs/context/domain.md")
        if "integrity" in (dims or []) and not invs:
            errors.append(f"story {sid}: declares 'integrity' — list the invariants it must keep (invariants = [\"INV-001\"])")
        if invs and "integrity" not in (dims or []):
            errors.append(f"story {sid}: lists invariants — declare the 'integrity' dimension too")
        if sid not in done and (hit := areas_hit(meta.get("touches", []), areas)) and "integrity" not in (dims or []):
            errors.append(f"story {sid}: touches critical area {', '.join(hit)} — declare 'integrity' and the invariants it must keep")
    kept = {i for m in stories.values() for i in m.get("invariants", [])}
    if stories:
        for iid in sorted(set(invariants) - kept):
            warnings.append(f"invariant {iid} ({invariants[iid]}) is kept by no story yet")
    pending = [s for s in stories if s not in done]
    for a, b in wave_clashes(pending, stories, areas):
        clash = [f"{x}" for x in stories[a].get("touches", []) for y in stories[b].get("touches", []) if overlaps(x, y)]
        if clash:
            errors.append(f"stories {a} and {b} share wave {stories[a].get('wave')} but both touch {', '.join(clash)} — move one to a later wave")
        shared = set(areas_hit(stories[a].get("touches", []), areas)) & set(areas_hit(stories[b].get("touches", []), areas))
        if shared:
            errors.append(f"stories {a} and {b} share wave {stories[a].get('wave')} and critical area {', '.join(sorted(shared))} — critical work goes one story at a time")
    corpus = cited_titles() if done else ""
    # One pass over the titles, not one search per done story (NFR-1): every `<text>.S<n>` citation
    # (.S1 must not match .S10), keyed by the text's last characters at each length a done id has.
    lengths = {len(sid) for sid in done}
    cited = {(corpus[max(0, m.start() - n):m.start()], m.group(1))
             for m in re.finditer(r"\.([Ss]\d+)\b", corpus) for n in lengths}
    proven: dict[str, bool] = {}  # one search per invariant, not per story
    for sid in sorted(done):
        untested = [f"{sid}.{s}" for s in stories[sid]["_scenarios"] if (sid, s) not in cited]
        if untested:
            errors.append(f"story {sid} is done but no active test title cites {', '.join(untested)} (TRACE-1)")
        for i in stories[sid].get("invariants", []):
            if i not in proven:
                proven[i] = bool(re.search(rf"\b{re.escape(i)}\b", corpus))
        unproven = [i for i in stories[sid].get("invariants", []) if not proven[i]]
        if unproven:
            errors.append(f"story {sid} is done but no active test title cites invariant {', '.join(unproven)} (INV-1)")
    ready = [
        sid for sid, m in stories.items()
        if sid not in done and all(d in done for d in m.get("depends_on", []))
    ]
    ready.sort(key=lambda s: (stories[s].get("wave", 99), s))
    return {"total": len(stories), "done": done, "ready": ready, "stories": stories}


def gate_state() -> dict:
    return (read_toml(ROOT / ".keelokit/state.toml", ".keelokit/state.toml") or {}).get("gates", {})


def check_scope(sid: str) -> int:
    """Files this branch changed outside the story's `touches` (scope creep or a missing path)."""
    stories = {m.get("id"): m for p in sorted((ROOT / "backlog/stories").glob("*.md"))
               if p.name.startswith(f"{sid}-") and (m := read_story(p))}  # sid is never a glob
    if sid not in stories:
        for e in errors + warnings:  # a story file the doctor can't read or ignored says why
            print(e)
        print(f"No story {sid} in backlog/stories")
        return 1
    story = stories[sid]
    touches = story.get("touches", [])
    if (base := main_base()) is None:
        print(f"{sid}: " + NO_MAIN.format(what="compare this branch with"))
        return 2
    changed = git("diff", "--name-only", base, "HEAD").split()
    status = 0
    outside = [f for f in changed if not any(overlaps(f, t) or f.startswith(t.rstrip("/") + "/") for t in touches)
               and not f.startswith(("backlog/", "docs/"))]
    if outside:
        print(f"{sid} changed files outside its touches: " + ", ".join(outside))
        print("Add them to the story's touches (and re-check its wave) or move the change to its own story.")
        status = 1
    areas, _ = load_critical()
    hit = areas_hit(changed, areas)
    if hit and "integrity" not in story.get("dimensions", []):
        print(f"{sid} changed critical area {', '.join(hit)} but does not declare 'integrity': "
              "add it and the invariants it keeps, then run the full build (no --light).")
        status = 1
    # The builder makes the verifier's acceptance tests pass; it never edits them. Only a later
    # `test(<ID>): …` commit (the verifier fixing a test openly) may change them.
    log = git("log", "--reverse", "--format=%H%x09%s", f"{base}..HEAD").splitlines()
    marker = f"test({sid.lower()})"
    first = next((i for i, line in enumerate(log) if line.partition("\t")[2].lower().startswith(marker)), None)
    if first is not None:
        tests = set(git("show", "--name-only", "--format=", log[first].split("\t")[0]).split())
        for line in log[first + 1:]:
            sha, _, subject = line.partition("\t")
            if subject.lower().startswith(marker):
                continue
            if edited := tests & set(git("show", "--name-only", "--format=", sha).split()):
                print(f"{sid}: acceptance tests changed outside a 'test({sid}): …' commit — {sha[:9]} "
                      f"\"{subject}\" edits {', '.join(sorted(edited))}")
                status = 1
    if status == 0:
        print(f"{sid}: all {len(changed)} changed files are within its touches"
              + (f"; critical area {', '.join(hit)} declared" if hit else ""))
    return status


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "--scope":
        return check_scope(sys.argv[2] if len(sys.argv) > 2 else "")
    if mode == "--critical":
        areas, _ = load_critical()
        if errors:
            print("\n".join(errors), file=sys.stderr)
            return 1
        files = critical_files(areas)
        if "--changed" in sys.argv and (base := main_base()) is None:
            # Unknown base: every critical file counts as changed (fail safe, like `pnpm verify`).
            print(NO_MAIN.format(what="diff against") + "; taking every critical file", file=sys.stderr)
        elif "--changed" in sys.argv:
            changed = set(git("diff", "--name-only", base).split())
            changed |= set(git("ls-files", "--others", "--exclude-standard").split())
            files = [f for f in files if f in changed]
        print("\n".join(files))
        return 0
    rules = load_rules()
    profile = load_profile()
    check_rules(rules, check_exceptions(set(rules)), profile)
    gaps, blocking = check_context()
    invariants = check_invariants()
    areas, _ = load_critical()
    escapes = check_escapes()
    backlog = check_backlog(invariants, areas)
    gates = gate_state()
    answers = ROOT / ".keelokit/answers.yml"
    layout = "harness" if answers.exists() and re.search(r"(?m)^mode: harness$", read(answers) or "") else "project"
    gate_names = GATES[layout]
    pending = next((g for g in gate_names if not gates.get(g)), None)

    if mode == "--brief":
        print("Keelokit:", f"gate pending → {pending}" if pending else "all gates approved")
        print(f"Context gaps: {gaps} ({blocking} blocking) · "
              f"Backlog: {len(backlog['done'])}/{backlog['total']} done")
        if backlog["ready"]:
            print("Next ready stories:", ", ".join(backlog["ready"][:3]))
        if profile is not None:
            print(f"Profile: {profile.get('kind', 'unknown')} · {len(not_applicable)} rules don't apply")
        for d in profile_drift:
            print(f"Profile drift: {drift_text(*d)}")
        if errors:
            print(f"Harness errors: {len(errors)} — run `{DOCTOR_CMD}`")
        return 0

    print("Keelokit doctor")
    print(f"  Gates: " + " → ".join(f"{g}{' ✓' if gates.get(g) else ''}" for g in gate_names))
    print(f"  Rules: {len(rules)} · Context gaps: {gaps} ({blocking} blocking)")
    if profile is not None:
        print(f"  Profile: {profile.get('kind', 'unknown')} · traits: {', '.join(sorted(profile['traits'])) or 'none'}"
              + (f" · not applicable: {', '.join(not_applicable)}" if not_applicable else ""))
    print(f"  Invariants: {len(invariants)} · Critical areas: {len(areas)} · Escapes logged: {escapes}")
    print(f"  Backlog: {len(backlog['done'])}/{backlog['total']} done"
          + (f" · next: {', '.join(backlog['ready'][:3])}" if backlog["ready"] else ""))
    for w in warnings:
        print(f"  warn  {w}")
    for e in errors:
        print(f"  ERROR {e}")
    if not errors:
        print("  ✔ harness healthy")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
