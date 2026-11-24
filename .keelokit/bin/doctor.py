#!/usr/bin/env python3
"""Keelokit harness health. Stdlib only (Python 3.11+ for tomllib).

    python3 .keelokit/bin/doctor.py            full report
    python3 .keelokit/bin/doctor.py --brief    where am I / what's next (SessionStart hook)
    python3 .keelokit/bin/doctor.py --ci       full report, exit 1 on any error
    python3 .keelokit/bin/doctor.py --scope ID files changed on this branch vs the story's `touches`,
                                               critical areas and acceptance tests
    python3 .keelokit/bin/doctor.py --critical [--changed]
                                               critical source files (all, or changed since main)

Any other command line (a missing ID, an unknown mode, an extra argument) prints the usage and exits 2.

Story states come from `.keelokit/bin/ledger.py --json` (docs/ledger.md: one reader): a story is done
when the ledger has it on the trunk or later, by its `Story:` commit or an approved correction (shown
apart as reconstructed: TRACE-1 and INV-1 skip it); ready when the ledger says so. A story file not on
the trunk yet is not done, and ready once its dependencies are done.
Without main or origin/main (a shallow CI checkout) nothing counts as done and the doctor says so,
`--scope` exits 2, and `--critical --changed` lists every critical file: never HEAD for main.
When the ledger can't answer (a cut history, a story it reads as unknown, no ledger.py) the done set is
unknown, not low: the Backlog line says unknown with the reason, an error in CI (`fetch-depth: 0`), a
warning elsewhere; rules that need "not done" become warnings.

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
check each escaped bug left behind. Status is never stored in a file (INV-005, read through the ledger).
"""
import sys

if sys.version_info < (3, 11):
    print(f"Keelokit needs Python 3.11+ (found {sys.version.split()[0]}); doctor and guard are off.")
    sys.exit(1)

import datetime as dt  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import ast  # noqa: E402
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
# Python tests (unittest, pytest): test_*.py or *_test.py, under the folders TITLE_DIRS walks.
PY_TEST_FILE_RE = re.compile(r"(^|/)(test_[^/]*|[^/]*_test)\.py$")
TITLE_DIRS = ("apps", "packages", "e2e", "tests", "test", "template")  # tests/ and test/: Python files only
# template/: Keelokit's own repo only (this copy is not shipped). A scenario covered by a TypeScript test the
# template ships (e.g. packages/shared/src/arch) runs in CI inside the generated project (scripts/test-template.sh).
# Folders of installed code: never read for titles (third-party test files, and slow).
VENDORED = {"node_modules", ".venv", "venv", "site-packages", "__pycache__", ".tox", ".nox"}
# A Python test's name cites ids with underscores: test_AUTH_001_S1_works → "test AUTH-001.S1 works".
PY_CITE_RE = re.compile(r"(?<![A-Za-z0-9])([A-Z][A-Z0-9]*)_(\d+)(?:_([Ss]\d+))?(?=_|$)")
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
    ".keelokit/guard-allow.toml": ({"allow": "tables"},
                                   {"allow": {"rule": "text", "path": "text", "glob": "text", "reason": "text",
                                              "approver": "text", "expires": "text|date"}}),
    ".keelokit/profile.toml": ({"kind": "text", "traits": "texts"}, {}),
    ".keelokit/critical.toml": ({"mutation_break": "whole", "area": "tables"},
                                {"area": {"name": "text", "why": "text", "paths": "texts"}}),
    ".keelokit/state.toml": ({"gates": "table", "ledger": "table"}, {}),
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
            if d == ".githooks":  # LEDGER-009: the plugin's SessionStart sets the hooks path when it is unset
                return ("Keelokit's SessionStart hook turns them on when a Claude session starts here; "
                        "a clone used without the plugin runs `git config core.hooksPath .githooks`")
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
        return f"git hook '{target}' is not installed (no {rel(hook)}; hooksPath: {hooks_dir}; {hook_remedy(hooks_dir, target)})"
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


def test_titles(text: str, path: str = "") -> list[str]:
    if path.endswith(".py"):
        return py_test_titles(text)
    return [m.group(2) for m in TEST_TITLE_RE.finditer(text)]


def py_test_titles(text: str) -> list[str]:
    """Active Python tests (`def test_*`, in a class or not), as titles that cite like the JS ones. Like
    `it.skip` and `it.failing`, these don't count: a test or class under a skip or expected-failure decorator
    (unittest.skip/skipIf/skipUnless/expectedFailure, pytest.mark.skip/skipif/xfail), a module with a
    skipping `pytestmark`, a test whose first statement is `self.skipTest(…)`. A file that doesn't parse
    (or nests too deep to) has none."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return []
    off = ("skip", "xfail", "expectedfailure")

    def says_off(node: ast.AST) -> bool:
        try:
            return any(w in ast.unparse(node).lower() for w in off)
        except RecursionError:
            return True

    def skipped(node: ast.AST) -> bool:
        if any(says_off(d) for d in getattr(node, "decorator_list", [])):
            return True
        body = getattr(node, "body", None)
        first = body[0] if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and body else None
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and len(body) > 1:
            first = body[1]  # past the docstring
        return (isinstance(first, ast.Expr) and isinstance(first.value, ast.Call)
                and isinstance(first.value.func, ast.Attribute) and first.value.func.attr in ("skipTest", "skip"))

    if any(isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in n.targets)
           and says_off(n.value) for n in tree.body):
        return []

    titles: list[str] = []

    def walk(nodes: list[ast.stmt]) -> None:
        for node in nodes:
            if isinstance(node, ast.ClassDef) and not skipped(node):
                walk(node.body)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test") \
                    and not skipped(node):
                cited = PY_CITE_RE.sub(lambda m: f"{m[1]}-{m[2]}" + (f".{m[3]}" if m[3] else ""), node.name)
                titles.append(re.sub(r"_+", " ", cited).strip())

    walk(tree.body)
    return titles


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
        live = [f for f, t in texts.items() if re.search(rf"\b{re.escape(rid)}\b", t) and test_titles(t, f.name)]
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


# --- The bounds of .keelokit/guard-allow.toml entries (HARN-020) ---------------------------------
# bin/guard.py keeps its own copy of everything between here and "end of the bounds" (allow_problem and
# allow_matches there): change both together (a test compares them).
ALLOW_RULES = ("SEC-1", "SEC-2")
ALLOW_WILDCARDS = "*?["


def allow_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and not any(ord(c) < 32 or ord(c) == 127 for c in value)


def allow_parts(value: str) -> list[str] | None:
    parts = value.split("/")
    return None if "\\" in value or any(p in ("", ".", "..") for p in parts) else parts


def allow_problem(entry: dict, today: dt.date) -> str | None:
    """Why an [[allow]] entry is not active (invalid, unbounded or expired), or None when it is."""
    if entry.get("rule") not in ALLOW_RULES:
        return "rule is SEC-1 or SEC-2"
    if not allow_text(entry.get("reason")) or not allow_text(entry.get("approver")):
        return "needs a reason and an approver"
    path, glob = entry.get("path"), entry.get("glob")
    if (path is None) == (glob is None):
        return "needs exactly one of path or glob"
    if path is not None:
        parts = allow_parts(path) if allow_text(path) else None
        if parts is None or any(c in path for c in ALLOW_WILDCARDS):
            return "path is a file relative to the repo root: no leading / or ./, no .., no wildcards, no trailing /"
    else:
        parts = allow_parts(glob) if allow_text(glob) else None
        if parts is None or len(parts) < 2 or "**" in glob or any(c in "[]" for c in glob) \
                or any(c in ALLOW_WILDCARDS for d in parts[:-1] for c in d):
            return "glob is directory/pattern: a literal directory, only * and ? in the file name, no **, no .., no [ or ]"
        if len(re.sub(r"[*?]", "", parts[-1])) < 2:
            return "glob's file name needs at least two literal characters"
    expires = entry.get("expires")
    if expires is not None and expires != "permanent":
        if isinstance(expires, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", expires):
            try:
                expires = dt.date.fromisoformat(expires)
            except ValueError:
                return "expires is a date (YYYY-MM-DD) or permanent"
        if not isinstance(expires, dt.date) or isinstance(expires, dt.datetime):
            return "expires is a date (YYYY-MM-DD) or permanent"
        if expires < today:
            return f"expired on {expires}"
    return None
# --- end of the bounds -----------------------------------------------------------------------------


def check_guard_allow() -> None:
    """.keelokit/guard-allow.toml: every entry valid and bounded, pointing at a file that exists; each active
    one is listed. Not an exception: an allowed path never excepts a rule from the enforcer checks."""
    name = ".keelokit/guard-allow.toml"
    today = dt.date.today()
    for i, e in enumerate(load_toml(ROOT / name, "allow"), 1):
        what = f"{name}: [[allow]] #{i}"
        if why := allow_problem(e, today):
            errors.append(f"{what}: {why}")
            continue
        target = e.get("path") or e["glob"]
        if "path" in e:
            found = (ROOT / target).is_file()
        else:
            files, why = repo_glob(target)
            found = bool(files)
            if why:
                errors.append(f"{what}: glob {why}")
                continue
        if not found:
            errors.append(f"{what}: {target} matches no file in the repo")
            continue
        warnings.append(f"guard allows {e['rule']} at {target} until {e.get('expires', 'permanent')}: "
                        f"{e['reason']} (approved by {e['approver']})")


_ledger_runs: dict[tuple[str, ...], tuple[dict | None, str]] = {}


def ledger_json(*args: str) -> tuple[dict | None, str]:
    """`ledger.py <args> --json`, parsed, run once per doctor run: (data, "") or (None, why)."""
    if args not in _ledger_runs:
        why, data = "", None
        try:
            out = subprocess.run([sys.executable, str(ROOT / ".keelokit/bin/ledger.py"), *args, "--json"], cwd=ROOT,
                                 capture_output=True, text=True, timeout=60)
            why = (out.stderr.strip().splitlines() or [""])[-1]
            data = json.loads(out.stdout) if out.returncode in (0, 1) else None
        except (OSError, subprocess.TimeoutExpired, ValueError):
            data = None
        _ledger_runs[args] = (data if isinstance(data, dict) else None, why)
    return _ledger_runs[args]


def check_corrections() -> None:
    """The ledger's corrections (backlog/ledger-corrections.toml): ledger.py checks them (docs/ledger.md,
    "Corrections file") and the doctor reports its CORRECTION_* differences: errors stay errors."""
    if not (ROOT / ".keelokit/bin/ledger.py").is_file():
        return
    data, why = ledger_json("check")
    diffs = data.get("diffs") if data else None
    if not isinstance(diffs, list):
        warnings.append(f"ledger: the corrections could not be checked ({why or 'run `python3 .keelokit/bin/ledger.py check`'})")
        return
    for d in diffs:
        if isinstance(d, dict) and str(d.get("code", "")).startswith("CORRECTION_"):
            (errors if d.get("level") == "error" else warnings).append(f"{d['code']}: {d.get('detail', '')}")


# --- LEDGER-1: the pieces that keep the ledger complete are alive (docs/ledger.md, "Mechanisms") -------
# Each hook of .githooks/ (LEDGER-009, LEDGER-010) and the ledger.py command it has to run.
LEDGER_HOOKS = {"commit-msg": "ledger.py hook msg", "prepare-commit-msg": "ledger.py hook prepare",
                "pre-push": "ledger.py prepush"}
# The differences that are errors under enforce = "block" (warnings under "warn"): ledger.py's attribution_diffs.
ATTRIBUTION_CODES = {"UNATTRIBUTED", "UNKNOWN_STORY", "BAD_CATEGORY", "STORY_NO_BODY", "SQUASH_LOST_TRAILERS"}
BLOCK_WINDOW = 3 * 86400  # docs/ledger.md decision 6: 3 days in a row with zero unattributed commits ...
BLOCK_COMMITS = 20        # ... and at least 20 commits in that window
UPGRADE = "/keelokit:harness-upgrade brings it"


def ledger_config() -> dict:
    """`[ledger]` of .keelokit/state.toml (its keys have the defaults docs/ledger.md gives: enforce block, the
    snapshot on); ledger.py reports a value it can't use."""
    table = state().get("ledger", {})
    return table if isinstance(table, dict) else {}


def workflow_steps(block: str) -> list[str]:
    """The steps of one job's text, each with its lines (a step starts at a `-` at the indent of the first)."""
    m = re.search(r"(?m)^ *steps:[ \t]*(?:#.*)?\n", block)
    if not m:
        return []
    steps: list[list[str]] = []
    indent = None
    for line in block[m.end():].splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        lead = len(line) - len(line.lstrip(" "))
        dash = re.match(r"( *)-(?:\s|$)", line)
        if indent is None:
            if not dash:
                break
            indent = lead
        if lead < indent or (lead == indent and not dash):
            break
        if dash and lead == indent:
            steps.append([line])
        else:
            steps[-1].append(line)
    return ["\n".join(s) for s in steps]


def workflow_job_texts(text: str) -> dict[str, str]:
    """Job id -> its text, for one workflow file (the jobs sit at the indent of the first one)."""
    jobs = re.search(r"(?ms)^jobs:[ \t]*(?:#[^\n]*)?\n(.*?)(?=^[^\s#]|\Z)", text)
    indent = jobs and re.search(r"(?m)^( +)[^\s#]", jobs.group(1))
    if not indent:
        return {}
    n = len(indent.group(1))
    return {m.group(1): m.group(2) for m in re.finditer(
        rf"(?ms)^ {{{n}}}([\w-]+):[ \t]*(?:#[^\n]*)?\n(.*?)(?=^ {{{n}}}[\w-]+:|\Z)", jobs.group(1))}


def runs_on_trunk_events(text: str) -> bool:
    """The workflow's `on:` names push or pull_request (a workflow_dispatch-only file, or a YAML file with no `on:`,
    never runs for a commit or a pull request)."""
    m = re.search(r"(?ms)^['\"]?on['\"]?:[ \t]*(.*?)(?=^[^\s#]|\Z)", text)
    return bool(m and re.search(r"(?m)(?:^|[\s\[,'\"])(push|pull_request)['\"]?[ \t]*(?::|,|\]|$)", m.group(1)))


FLOW_OFF = re.compile(r"(?:^|[{,\s])if:[ \t]*(?P<q>['\"]?)(?:false|\$\{\{\s*false\s*\}\})(?P=q)[ \t]*(?:[,}#]|$)",
                      re.I | re.M)
FLOW_SOFT = re.compile(r"(?:^|[{,\s])continue-on-error:[ \t]*(?P<q>['\"]?)(?:true|\$\{\{\s*true\s*\}\})(?P=q)"
                       r"[ \t]*(?:[,}#]|$)", re.I | re.M)
LEDGER_CHECK = re.compile(r"\bledger\.py[ \t]+check[ \t]+--ci\b")


def run_script(step: str) -> str:
    """The shell text of a step's `run:` (one line, a block scalar, or a flow mapping's value); "" without one."""
    m = re.search(r"(?m)^([ \t-]*)run:[ \t]*([|>][-+0-9]*)?[ \t]*(.*)$", step)
    if not m:
        flow = re.search(r"[{,][ \t]*run:[ \t]*([^,}]*)", step)
        return flow.group(1).strip().strip("'\"") if flow else ""
    if not m.group(2):
        return m.group(3).split(" #")[0].strip().strip("'\"")
    lines, deeper = [], len(m.group(1)) + 1
    for line in step[m.end():].splitlines()[1:]:
        if line.strip() and len(line) - len(line.lstrip(" ")) < deeper:
            break
        lines.append(line.strip())
    return "\n".join(lines)


def live_ledger_step(step: str) -> str | None:
    """None when this step runs `ledger.py check --ci` so that its failure fails the job; "absent" when it doesn't
    run it at all (the command only in its name); else why it can't fail the job."""
    lines = [ln.strip() for ln in run_script(step).splitlines() if ln.strip() and not ln.strip().startswith("#")]
    at = next((i for i, ln in enumerate(lines) if LEDGER_CHECK.search(ln)), None)
    if at is None:
        return "absent"
    if any(re.match(r"exit\b", ln) for ln in lines[:at]):
        return "never reaches the command (an `exit` comes first)"
    if re.search(r"(\|\||;|&)\s*\S", LEDGER_CHECK.split(lines[at], 1)[1]) or lines[at].rstrip().endswith("&"):
        return "hides its failure (`||`, `;` or `&` after the command)"
    if FLOW_SOFT.search(step):
        return "has continue-on-error"
    if FLOW_OFF.search(step):
        return "never runs (if: false)"
    return None


def dead_job(job: str, jobs: dict[str, str], seen: frozenset = frozenset()) -> str | None:
    """Why this job of one workflow never fails it, or None: missing, continue-on-error, `if: false`, or a job it
    needs that is dead (GitHub skips a job whose needs did not succeed)."""
    block = jobs.get(job)
    if block is None:
        return f"CI job '{job}' does not exist"
    if re.search(rf"(?m)^\s*continue-on-error:[ \t]*{ALWAYS['true']}", block):
        return f"CI job '{job}' has continue-on-error"
    key = re.match(r"(?:[ \t]*(?:#.*)?\n)*( *)", block).group(1)
    if re.search(rf"(?m)^{key}if:[ \t]*{ALWAYS['false']}", block):
        return f"CI job '{job}' never runs (if: false)"
    needs: list[str] = []
    if m := re.search(rf"(?m)^{key}needs:[ \t]*(.*)$", block):
        if inline := m.group(1).split("#")[0].strip():
            needs = re.findall(r"[\w-]+", inline)
        else:
            for line in block[m.end() + 1:].splitlines():
                if not (item := re.match(rf"{key}[ \t]+-[ \t]*([\w-]+)", line)):
                    break
                needs.append(item.group(1))
    for need in needs:
        if need not in seen and (why := dead_job(need, jobs, seen | {job})):
            return f"CI job '{job}' needs '{need}': {why}"
    return None


def ledger_ci_workflows() -> tuple[list[tuple[str, dict[str, str]]], str | None]:
    """The workflows that hold a live `ledger.py check --ci` step for pushes or pull requests, each with its jobs;
    when there is none, why. Files are read in name order and each on its own: a job of the same name in another
    workflow (the release workflow's tag-only snapshot) never stands in for this one's."""
    found: list[tuple[str, dict[str, str]]] = []
    why = None
    for path in sorted((ROOT / ".github/workflows").glob("*.y*ml")):
        text = read(path) or ""
        jobs = workflow_job_texts(text)
        live = False
        for job, block in jobs.items():
            for step in workflow_steps(block):
                if not LEDGER_CHECK.search(step) or (problem := live_ledger_step(step)) == "absent":
                    continue
                if problem is None and not runs_on_trunk_events(text):
                    problem = f"is in {rel(path)}, which runs on no push or pull_request"
                if problem is None and (job_why := dead_job(job, jobs)):
                    problem = f"is in a job that never fails the run ({job_why})"
                if problem is None:
                    live = True
                    break
                why = why or f"the CI step that runs `python3 .keelokit/bin/ledger.py check --ci` (job '{job}') {problem}"
            if live:
                break
        if live:
            found.append((rel(path), jobs))
    if found:
        return found, None
    return [], why or (f"no CI step runs `python3 .keelokit/bin/ledger.py check --ci` (LEDGER-010's "
                       f"\"Ledger attribution\"; {UPGRADE})")


def calls(text: str | None, call: str) -> bool:
    """Whether a hook's text runs `call` on a line that isn't a comment."""
    return any(call in line.split("#", 1)[0] for line in (text or "").splitlines() if not line.lstrip().startswith("#"))


def ledger_hook_problems(hooks_dir: str) -> list[tuple[str, bool]]:
    """(problem, shared) for the ledger's hooks: each shipped in .githooks/, executable, running its ledger.py
    command on a line that isn't a comment; prepare-commit-msg installed where git runs it (commit-msg and pre-push
    are LEDGER-1's own git-hook enforcers, which the rule loop checks); and a hooks path elsewhere whose hooks of
    these names don't run the ledger. A hook git can't run (missing, not executable) where the hooks path is
    .githooks is the git-hook check's one line, never a second one here."""
    problems: list[tuple[str, bool]] = []
    ours = (ROOT / hooks_dir).resolve() == (ROOT / ".githooks").resolve()
    husky = (ROOT / hooks_dir).resolve() == (ROOT / ".husky/_").resolve()
    for name, call in LEDGER_HOOKS.items():
        shipped = ROOT / ".githooks" / name
        text, why = read_file(shipped, lenient=True) if shipped.is_file() else (None, None)
        installed = hook_problem(name) if ours or name == "prepare-commit-msg" else None
        if name == "prepare-commit-msg" and installed:
            problems.append((installed, True))
        if why:
            problems.append((why, False))
        elif text is None:
            if not installed:
                problems.append((f"'.githooks/{name}' is missing ({UPGRADE})", False))
        elif not calls(text, call):
            problems.append((f"'.githooks/{name}' does not call `{call}` ({UPGRADE})", False))
        elif not os.access(shipped, os.X_OK) and not installed:
            problems.append((f"'.githooks/{name}' is not executable, so git never runs it "
                             f"(a human runs `chmod +x .githooks/{name}`)", False))
        run = ROOT / ".husky" / name if husky else ROOT / hooks_dir / name
        if not ours and run.is_file() and not calls(read_file(run, lenient=True)[0], call):
            problems.append((f"core.hooksPath is '{hooks_dir}', so git runs '{rel(run)}', which does not call "
                             f"`{call}`: the ledger's {name} never runs (`git config core.hooksPath .githooks`)", False))
    return problems


def first_parent_arrivals(trunk_sha: str, since_sha: str, moves: dict[str, int]) -> tuple[dict[str, int], int | None]:
    """sha -> when it reached the trunk, for the trunk commits after `since`, and when `since` did: the arrival of
    the first-parent commit that brought it, from moves.toml's exact time when it has one, else that commit's
    committer date. Never the clock (decision 6 is read from the history)."""
    graph: dict[str, list[str]] = {}
    for line in git("rev-list", "--parents", trunk_sha, f"^{since_sha}").splitlines():
        sha, *parents = line.split()
        graph[sha] = parents
    times = {}
    for line in git("log", "--first-parent", "--format=%H %ct", trunk_sha, "--").splitlines():
        sha, _, ct = line.partition(" ")
        if ct.isdigit():
            times[sha] = moves.get(sha, int(ct))
    chain = git("rev-list", "--first-parent", trunk_sha).split()
    # `since` reached the trunk with the oldest first-parent commit that holds it (itself when it is on that
    # chain). The chain, newest first, holds it from the newest down to that one: a binary search.
    lo, hi = 0, len(chain) - 1
    if since_sha not in times:
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if subprocess.run(["git", "merge-base", "--is-ancestor", since_sha, chain[mid]], cwd=ROOT,
                              capture_output=True).returncode == 0:
                lo = mid
            else:
                hi = mid - 1
    since_at = times.get(since_sha, times.get(chain[lo]) if chain else None)
    arrival: dict[str, int] = {}
    for f in reversed([s for s in chain if s in graph]):  # oldest first: a merge brings only what no earlier one did
        at = times.get(f)
        if at is None:
            continue
        arrival[f] = at
        todo = list(graph[f][1:])
        while todo:
            c = todo.pop()
            if c in graph and c not in arrival:
                arrival[c] = at
                todo += graph[c]
    return arrival, since_at


MOVE_ROW = re.compile(r'sha = "([0-9a-f]{40})"\nseen = "([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z)"\n'
                      r'run = "[^"\n]*"\nexact = (true|false)\n(left = )?')


def snapshot_moves(branch: str) -> dict[str, int]:
    """sha -> epoch of the exact rows (not `left`) of origin/<branch>'s moves.toml (LEDGER-011); {} without one.
    Only `ledger.py snapshot` writes it, always in this one layout (ledger.py's moves_toml): a row in any other
    shape, or bytes that aren't UTF-8, count as no row, so a reading never takes a time that isn't one."""
    found: dict[str, int] = {}
    if not branch:
        return found
    out = subprocess.run(["git", "show", f"refs/remotes/origin/{branch}:moves.toml"], cwd=ROOT, capture_output=True)
    try:
        text = out.stdout.decode("utf-8") if out.returncode == 0 else ""
    except UnicodeDecodeError:
        return found
    for block in text.split("[[move]]\n")[1:]:
        m = MOVE_ROW.match(block)
        if m and m[3] == "true" and not m[4]:
            try:
                at = dt.datetime.strptime(m[2], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
            except ValueError:
                continue
            found[m[1]] = int(at.timestamp())
    return found


def block_readiness(facts: dict, diffs: list, since_sha: str, snapshot: str) -> str:
    """Under enforce = "warn": whether the trunk history earns `block` (docs/ledger.md decision 6): in the last 3
    days of it (ending at the newest commit's arrival, not now) at least 20 commits, none unattributed, `since` on
    the trunk at least that long, and no difference that `block` would make an error."""
    blocking = [d for d in diffs if isinstance(d, dict)
                and (d.get("level") == "error" or d.get("code") in ATTRIBUTION_CODES)]
    if blocking:
        return f"block: not yet, {len(blocking)} difference(s) `block` would refuse (`ledger.py check`)"
    arrival, since_at = first_parent_arrivals(facts["trunk_sha"], since_sha, snapshot_moves(snapshot))
    if not arrival or since_at is None:
        return "block: not yet, no commits since [ledger] since"
    end = max(arrival.values())
    if end - since_at < BLOCK_WINDOW:
        return "block: not yet, less than 3 days of trunk history since [ledger] since"
    window = [s for s, at in arrival.items() if at > end - BLOCK_WINDOW]
    if len(window) < BLOCK_COMMITS:
        return f"block: not yet, {len(window)} of {BLOCK_COMMITS} commits in the last 3 days of the trunk"
    return (f'recommend enforce = "block": the last 3 days of the trunk hold {len(window)} commits, all attributed, '
            "and no error difference (a person or the coordinator switches it in .keelokit/state.toml)")


def check_ledger(rules: dict[str, dict], excepted: set[str]) -> str | None:
    """LEDGER-1 (docs/ledger.md, "Mechanisms"): every piece that keeps the ledger complete is alive — the hooks of
    .githooks/ and git running them, the CI's `ledger.py check --ci` step in a workflow for pushes or pull requests,
    the snapshot jobs in that same workflow unless `[ledger] snapshot = ""`, `[ledger] since` on the trunk (the
    corrections are check_corrections'). Like any rule's, its problems are errors, or warnings under a dated
    exception. Returns the Ledger line: the share of unattributed commits since `since` and, under `warn`, whether
    to switch to `block` (only recommended: the doctor never writes `enforce`)."""
    rid = "LEDGER-1"
    if rid not in rules or rid in not_applicable:
        return None
    hooks_dir = git("rev-parse", "--git-path", "hooks").strip() or ".git/hooks"
    problems = ledger_hook_problems(hooks_dir)
    workflows, why = ledger_ci_workflows()
    if why:
        problems.append((why, False))
    cfg = ledger_config()
    snapshot = cfg.get("snapshot", "keelokit/ledger")
    snapshot = snapshot.strip() if isinstance(snapshot, str) else "keelokit/ledger"
    if snapshot and workflows:
        path, jobs = workflows[0]
        for job in ("ledger-config", "ledger-snapshot"):
            if p := dead_job(job, jobs):
                problems.append((f"{p} in {path}, where the ledger step runs: LEDGER-011's snapshot runs there while "
                                 f"[ledger] snapshot is \"{snapshot}\" ({UPGRADE}; snapshot = \"\" turns the snapshot off)",
                                 False))
    enforce = cfg.get("enforce", "block")
    enforce = "warn" if isinstance(enforce, str) and enforce.strip() == "warn" else "block"  # as ledger.py reads it
    tail = f' · enforce = "{enforce}"'
    line = None
    if (ROOT / ".keelokit/bin/ledger.py").is_file():
        facts, why = ledger_json()
        since = facts.get("unattributed", {}).get("since") if facts and isinstance(facts.get("unattributed"), dict) else None
        if not facts or not isinstance(facts.get("unattributed"), dict):
            line = f"Ledger: unknown ({why or 'run `python3 .keelokit/bin/ledger.py check`'}){tail}"
        elif facts.get("history") != "complete":
            line = f"Ledger: the history is cut, so the share is unknown (`ledger.py history --ensure`){tail}"
        elif not since or not isinstance(since, str):
            line = f"Ledger: no [ledger] since, so attribution is not required yet{tail}"
        else:
            since_sha = git("rev-parse", "--verify", "--quiet", f"{since}^{{commit}}").strip()
            on_trunk = bool(since_sha) and subprocess.run(
                ["git", "merge-base", "--is-ancestor", since_sha, facts["trunk_sha"]], cwd=ROOT,
                capture_output=True).returncode == 0
            if not on_trunk:
                problems.append((f"[ledger] since = \"{since[:40]}\" is not on the trunk, so ledger.py checks "
                                 "the attribution of no commit (set it to a trunk commit, e.g. the adoption commit)", False))
                line = f"Ledger: [ledger] since is not on the trunk, so the share is unknown{tail}"
            else:
                total = len(git("rev-list", facts["trunk_sha"], f"^{since_sha}").split())
                loose = facts["unattributed"].get("commits", 0)
                share = 100 * loose / total if total else 0.0
                line = f"Ledger: {loose} of {total} commits unattributed since {since_sha[:7]} ({share:.1f}%){tail}"
                if enforce == "warn":
                    data, _ = ledger_json("check")
                    diffs = data.get("diffs") if data else None
                    line += " · " + block_readiness(facts, diffs if isinstance(diffs, list) else [{"level": "error"}],
                                                    since_sha, snapshot)
    for problem, shared in problems:
        report_rule(rid, problem, rid in excepted, shared)
    return line


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


_shared_lines: dict[tuple[bool, str], int] = {}


def report_rule(rid: str, problem: str, excepted: bool, shared: bool = False) -> None:
    """One enforcer problem of a rule: an error, or a warning under an approved, unexpired exception (which keeps
    the debt visible without turning CI red). A `shared` problem (a git hook) that another rule already reported at
    the same level is that line, naming this rule too: one missing hook, one line (LEDGER-012)."""
    target = warnings if excepted else errors
    key = (excepted, problem)
    if shared and key in _shared_lines:
        i = _shared_lines[key]
        line = target[i]
        target[i] = line[:-1] + f", {rid})" if line.endswith(")") and " (also " in line else f"{line} (also {rid})"
        return
    if shared:
        _shared_lines[key] = len(target)
    target.append(f"rule {rid}: {problem}" + (" (excepted)" if excepted else ""))


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
        problems = [("", "MUST rule without an enforcer")] if must and not refs else []
        problems += [(ref, p) for ref in refs if (p := enforcer_problem(rid, ref))]
        for ref, problem in problems:
            report_rule(rid, problem, rid in excepted, shared=ref.startswith("git-hook:"))
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


ON_TRUNK = ("on-trunk", "in-version", "in-staging", "in-production")
STATES = {"defined", "ready", "in-progress", "delivered", "unknown", *ON_TRUNK}  # docs/ledger.md, "States"


def ledger_states() -> tuple[dict[str, dict] | None, str | None]:
    """LEDGER-006: the trunk's story records by id, from `ledger.py --json` (docs/ledger.md, "The principle":
    one reader, so the doctor never reads `Story:` trailers itself), and why the states are unknown, or None.
    Unknown when the ledger is missing or cannot answer, its answer is not schema 1 as documented, the history
    is incomplete, or any story is unknown: never a lower state. A repo with no commit yet has nothing on the
    trunk. None for the records: the ledger found no trunk (exit 2) and there is no main either."""
    if not git("rev-parse", "--verify", "--quiet", "HEAD").strip():
        return {}, None
    ledger = ROOT / ".keelokit/bin/ledger.py"
    if not ledger.is_file():
        return {}, "no .keelokit/bin/ledger.py to read story states from (`/keelokit:harness-upgrade` brings it)"
    try:
        out = subprocess.run([sys.executable, str(ledger), "--json"], cwd=ROOT, capture_output=True, text=True,
                             timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {}, f"ledger.py could not answer ({e.__class__.__name__})"
    why = (out.stderr.strip().splitlines() or [""])[-1].removeprefix("Keelokit: ")
    if out.returncode == 2 and main_ref() is None:
        return None, None
    try:
        facts = json.loads(out.stdout) if out.returncode in (0, 1) else None
    except ValueError:
        facts = None
    stories = facts.get("stories") if isinstance(facts, dict) else None
    history = facts.get("history") if isinstance(facts, dict) else None
    if (not isinstance(stories, list) or facts.get("schema") != 1 or isinstance(facts.get("schema"), bool) or not isinstance(history, str)
            or not all(isinstance(x, dict) and isinstance(x.get("id"), str) and isinstance(x.get("state"), str) and x["state"] in STATES for x in stories)):
        return {}, f"ledger.py could not answer ({why or 'run `python3 .keelokit/bin/ledger.py`'})"
    records = {x["id"]: x for x in stories}
    unknown = [x for x in stories if x["state"] == "unknown"]
    if history == "incomplete" or unknown:
        diffs = facts.get("diffs") if isinstance(facts.get("diffs"), list) else []
        reason = next((x["reason"] for x in unknown if isinstance(x.get("reason"), str) and x["reason"]), None)
        reason = reason or next((d["detail"] for d in diffs if isinstance(d, dict)
                                 and d.get("code") == "HISTORY_INCOMPLETE" and isinstance(d.get("detail"), str)), None)
        return {}, reason or "the ledger reads the history as incomplete (run `python3 .keelokit/bin/ledger.py`)"
    if history != "complete" and not history.startswith("snapshot:"):
        return {}, f"the ledger's history is {history!r} (run `python3 .keelokit/bin/ledger.py`)"
    return records, None


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
    for base in TITLE_DIRS:
        for path in (ROOT / base).rglob("*") if (ROOT / base).exists() else []:
            rel = path.relative_to(ROOT).as_posix()
            if VENDORED & set(rel.split("/")) or not path.is_file():
                continue
            if (TEST_FILE_RE.search(rel) and base not in ("tests", "test")) or PY_TEST_FILE_RE.search(rel):
                titles += test_titles(read(path, lenient=True) or "", rel)
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
        meta["_path"] = rel.as_posix()
        stories[sid] = meta
    records, gap = ledger_states() if stories else ({}, None)
    if records is None:  # no trunk for the ledger, and no main: as before, nothing counts as done
        errors.append(NO_MAIN.format(what="count done stories from"))
        records = {}
    # States come from the ledger (its ids and files, whatever `[ledger]` configures). A story file is matched
    # to its record by path, else by id; one not on the trunk yet (a plan on a branch) has no record: not done,
    # and ready once every dependency is on the trunk by the ledger.
    by_path = {r["path"]: r for r in records.values() if isinstance(r.get("path"), str)}
    rec = {sid: by_path.get(m["_path"]) or records.get(sid) for sid, m in stories.items()}
    on_trunk = {i for i, r in records.items() if r["state"] in ON_TRUNK}
    done = {sid for sid, r in rec.items() if r and r["state"] in ON_TRUNK}
    reconstructed = sorted(i for i in on_trunk if records[i].get("reconstructed") is True)
    matched = {r["id"] for r in rec.values() if r}
    done_count, total = len(on_trunk), len(records) + sum(1 for r in rec.values() if not r)
    if gap:
        if os.environ.get("CI"):
            errors.append(f"done state unknown: {gap} (CI: checkout with `fetch-depth: 0`)")
        else:
            warnings.append(f"done state unknown: {gap}")
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
        if (hit := areas_hit(meta.get("touches", []), areas)) and "integrity" not in (dims or []):
            if sid not in done and gap:  # it may be done: no red CI for lack of history
                warnings.append(f"story {sid}: touches critical area {', '.join(hit)} without 'integrity'; its done state is unknown "
                                "(shallow clone), declare 'integrity' and the invariants it must keep if it is not done")
            elif sid not in done:
                errors.append(f"story {sid}: touches critical area {', '.join(hit)} — declare 'integrity' and the invariants it must keep")
            else:  # LOG-304: shipped before (or despite) the area; visible, but not a retroactive red CI
                warnings.append(f"story {sid} is done but touches critical area {', '.join(hit)} without 'integrity': "
                                "add it with the invariants the code keeps, and their tests")
    kept = {i for m in stories.values() for i in m.get("invariants", [])}
    if stories:
        for iid in sorted(set(invariants) - kept):
            warnings.append(f"invariant {iid} ({invariants[iid]}) is kept by no story yet")
    pending = [s for s in stories if s not in done]
    clashes = warnings if gap else errors  # pending may include done stories: only a warning then
    maybe = " (done state unknown: shallow clone)" if gap else ""
    for a, b in wave_clashes(pending, stories, areas):
        clash = [f"{x}" for x in stories[a].get("touches", []) for y in stories[b].get("touches", []) if overlaps(x, y)]
        if clash:
            clashes.append(f"stories {a} and {b} share wave {stories[a].get('wave')} but both touch {', '.join(clash)} — move one to a later wave" + maybe)
        shared = set(areas_hit(stories[a].get("touches", []), areas)) & set(areas_hit(stories[b].get("touches", []), areas))
        if shared:
            clashes.append(f"stories {a} and {b} share wave {stories[a].get('wave')} and critical area {', '.join(sorted(shared))} — critical work goes one story at a time" + maybe)
    # Reconstructed stories (done by an approved correction row) predate TRACE-1 and INV-1: they skip both
    # and are listed apart (docs/ledger.md, decision 5).
    checked = {sid for sid in done if rec[sid].get("reconstructed") is not True}
    corpus = cited_titles() if checked else ""
    # One pass over the titles, not one search per done story (NFR-1): every `<text>.S<n>` citation
    # (.S1 must not match .S10), keyed by the text's last characters at each length a done id has.
    lengths = {len(sid) for sid in checked}
    cited = {(corpus[max(0, m.start() - n):m.start()], m.group(1))
             for m in re.finditer(r"\.([Ss]\d+)\b", corpus) for n in lengths}
    proven: dict[str, bool] = {}  # one search per invariant, not per story
    for sid in sorted(checked):
        untested = [f"{sid}.{s}" for s in stories[sid]["_scenarios"] if (sid, s) not in cited]
        if untested:
            errors.append(f"story {sid} is done but no active test title cites {', '.join(untested)} (TRACE-1)")
        for i in stories[sid].get("invariants", []):
            if i not in proven:
                proven[i] = bool(re.search(rf"\b{re.escape(i)}\b", corpus))
        unproven = [i for i in stories[sid].get("invariants", []) if not proven[i]]
        if unproven:
            errors.append(f"story {sid} is done but no active test title cites invariant {', '.join(unproven)} (INV-1)")
    waves = {sid: m.get("wave", 99) for sid, m in stories.items()}
    ready = [] if gap else [
        sid for sid, m in stories.items()
        if (rec[sid]["state"] == "ready" if rec[sid] else all(d in on_trunk for d in m.get("depends_on", [])))
    ]
    for i, r in ([] if gap else records.items()):  # ready on the trunk, its file not checked out here
        if r["state"] == "ready" and i not in matched:
            ready.append(i)
            waves[i] = r["wave"] if isinstance(r.get("wave"), int) and not isinstance(r.get("wave"), bool) else 99
    ready.sort(key=lambda s: (waves[s], s))
    return {"total": total, "done": done, "done_count": done_count, "ready": ready, "stories": stories,
            "unknown": gap, "reconstructed": reconstructed}


_state: list[dict] = []


def state() -> dict:
    """.keelokit/state.toml, read once (its errors are reported once)."""
    if not _state:
        _state.append(read_toml(ROOT / ".keelokit/state.toml", ".keelokit/state.toml") or {})
    return _state[0]


def gate_state() -> dict:
    return state().get("gates", {})


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


USAGE = """usage: doctor.py
       doctor.py --brief
       doctor.py --ci
       doctor.py --scope ID
       doctor.py --critical [--changed]"""


def main() -> int:
    args = sys.argv[1:]
    if args in (["-h"], ["--help"]):
        print(USAGE)
        return 0
    mode = args[0] if args else ""
    # Only the command lines the docstring documents run: anything else (DX-8: `--scope` with no
    # id, an unknown mode, a stray argument) says how to call it instead of running something else.
    if mode == "--scope" and (len(args) != 2 or not args[1] or args[1].startswith("-")):
        print("usage: doctor.py --scope ID  (a story id, e.g. AUTH-001)", file=sys.stderr)
        return 2
    if mode != "--scope" and args not in ([], ["--brief"], ["--ci"], ["--critical"], ["--critical", "--changed"]):
        print(f"doctor.py: unexpected arguments: {' '.join(args)}\n{USAGE}", file=sys.stderr)
        return 2
    if mode == "--scope":
        return check_scope(args[1])
    if mode == "--critical":
        areas, _ = load_critical()
        if errors:
            print("\n".join(errors), file=sys.stderr)
            return 1
        files = critical_files(areas)
        if "--changed" in args and (base := main_base()) is None:
            # Unknown base: every critical file counts as changed (fail safe, like `pnpm verify`).
            print(NO_MAIN.format(what="diff against") + "; taking every critical file", file=sys.stderr)
        elif "--changed" in args:
            changed = set(git("diff", "--name-only", base).split())
            changed |= set(git("ls-files", "--others", "--exclude-standard").split())
            files = [f for f in files if f in changed]
        print("\n".join(files))
        return 0
    rules = load_rules()
    profile = load_profile()
    excepted = check_exceptions(set(rules))
    check_rules(rules, excepted, profile)
    check_guard_allow()
    check_corrections()
    ledger_line = check_ledger(rules, excepted)
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
              + (f"Backlog: unknown, {backlog['unknown']}" if backlog["unknown"]
                 else f"Backlog: {backlog['done_count']}/{backlog['total']} done"))
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
    print((f"  Backlog: unknown, {backlog['unknown']}" if backlog["unknown"]
           else f"  Backlog: {backlog['done_count']}/{backlog['total']} done")
          + (f" · next: {', '.join(backlog['ready'][:3])}" if backlog["ready"] else ""))
    if backlog["reconstructed"]:
        print(f"  Reconstructed (approved corrections; TRACE-1 and INV-1 skip them): {', '.join(backlog['reconstructed'])}")
    if ledger_line:
        print(f"  {ledger_line}")
    for w in warnings:
        print(f"  warn  {w}")
    for e in errors:
        print(f"  ERROR {e}")
    if not errors:
        print("  ✔ harness healthy")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
