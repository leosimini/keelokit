#!/usr/bin/env python3
"""Keelokit harness health. Stdlib only (Python 3.11+ for tomllib).

    python3 .keelokit/bin/doctor.py            full report
    python3 .keelokit/bin/doctor.py --brief    where am I / what's next (SessionStart hook)
    python3 .keelokit/bin/doctor.py --ci       full report, exit 1 on any error
    python3 .keelokit/bin/doctor.py --scope ID files changed on this branch vs the story's `touches`,
                                               critical areas and acceptance tests
    python3 .keelokit/bin/doctor.py --critical [--changed]
                                               critical source files (all, or changed since main)

Checks: every MUST rule has an enforcer, and each enforcer looks alive (a test that cites the
rule and has active cases, a lint rule that is on, a CI job with real steps and no
continue-on-error, a git hook that is installed) unless an approved exception is active;
exceptions are complete and not expired; docs/context is complete, precise and its gaps are
tracked; every invariant in domain.md has an id and a class; critical areas point at real
paths; backlog stories are well-formed, stories in one wave don't touch the same paths or the
same critical area, a story touching a critical area declares `integrity` and its invariants,
and every scenario and invariant of a done story is cited by an active test title; the escape
log names the check each escaped bug left behind. A story is done when a commit reachable from
main carries the trailer `Story: <ID>` — status is never stored in a file.
"""
import sys

if sys.version_info < (3, 11):
    print(f"Keelokit needs Python 3.11+ (found {sys.version.split()[0]}); doctor and guard are off.")
    sys.exit(1)

import datetime as dt  # noqa: E402
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
    "copy", "a11y", "security", "nfr", "config", "ops",
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
GATES = {
    "project": ["intake", "product", "stack", "skeleton", "backlog"],  # /keelokit:project-new
    "harness": ["intake", "adopt", "backlog"],  # /keelokit:project-adopt on an existing repo
}

errors: list[str] = []
warnings: list[str] = []


def load_toml(path: Path, key: str) -> list[dict]:
    if not path.exists():
        return []
    try:
        return tomllib.loads(path.read_text()).get(key, [])
    except tomllib.TOMLDecodeError as e:
        errors.append(f"{path.relative_to(ROOT)}: invalid TOML ({e})")
        return []


def git(*args: str) -> str:
    out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    return out.stdout if out.returncode == 0 else ""


def main_ref() -> str:
    for ref in ("origin/main", "main"):
        if git("rev-parse", "--verify", "--quiet", ref).strip():
            return ref
    return "HEAD"


def ci_job(job: str) -> str | None:
    """The text of a top-level job in any workflow, or None."""
    for path in (ROOT / ".github/workflows").glob("*.y*ml"):
        m = re.search(rf"(?ms)^  {re.escape(job)}:\s*\n(.*?)(?=^  \S|\Z)", path.read_text())
        if m:
            return m.group(1)
    return None


SETUP_STEPS = re.compile(r"(checkout|setup-node|action-setup|setup-uv|setup-python|upload-artifact|cache)@")


def test_titles(path: Path) -> list[str]:
    return [m.group(2) for m in TEST_TITLE_RE.finditer(path.read_text(errors="ignore"))]


def enforcer_problem(rid: str, ref: str) -> str | None:
    """Why this enforcer can't be trusted to enforce the rule, or None if it looks alive."""
    kind, _, target = ref.partition(":")
    if kind == "ci":
        block = ci_job(target)
        if block is None:
            return f"CI job '{target}' does not exist"
        if re.search(r"(?m)^\s*continue-on-error:\s*true", block):
            return f"CI job '{target}' has continue-on-error"
        steps = re.findall(r"(?m)^\s*-?\s*(?:run|uses):\s*(.+)$", block)
        real = [s for s in steps if not SETUP_STEPS.search(s) and s.strip().strip("'\"") not in ("true", "exit 0", ":", "")]
        return None if real else f"CI job '{target}' has no real step"
    if kind == "git-hook":
        hooks_dir = git("config", "core.hooksPath").strip() or ".git/hooks"
        for d in (hooks_dir, ".husky"):
            if (ROOT / d / target).exists():
                return None
        return f"git hook '{target}' is not installed (hooksPath: {hooks_dir}; run pnpm install)"
    if kind == "claude-hook":
        return None if (ROOT / ".keelokit/bin" / target).exists() else f"'.keelokit/bin/{target}' is missing"
    if kind == "test":
        files = list(ROOT.glob(target)) if any(c in target for c in "*?[") else [ROOT / target]
        files = [f for f in files if f.exists()]
        if not files:
            return f"no test at '{target}'"
        # A glob (apps/*/e2e/*.spec.ts) is satisfied when at least one match names the rule and
        # has an active test; a plain path must do both itself.
        live = [f for f in files if re.search(rf"\b{re.escape(rid)}\b", f.read_text(errors="ignore")) and test_titles(f)]
        if live:
            return None
        rel = ", ".join(str(f.relative_to(ROOT)) for f in files)
        return f"{rel}: no active test that names {rid} (add a comment or title citing it)"
    if kind == "lint":
        texts = [c.read_text() for c in [*ROOT.glob("eslint.config.*"), *ROOT.glob(".eslintrc*")]]
        rule = re.escape(target)
        if any(re.search(rf"['\"]{rule}['\"]\s*:\s*\[?\s*['\"]?(off|0)\b", t) for t in texts):
            return f"lint rule '{target}' is turned off somewhere"
        on = any(re.search(rf"['\"]{rule}['\"]\s*:\s*\[?\s*['\"]?(error|warn|2|1)\b", t) for t in texts)
        return None if on else f"lint rule '{target}' is not enabled"
    if kind in ("script", "file"):
        path, _, needle = target.partition("#")  # file:tsconfig.base.json#"strict": true
        if not (ROOT / path).exists():
            return f"'{path}' does not exist"
        if needle and needle not in (ROOT / path).read_text():
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
                expires = dt.date.fromisoformat(expires)
            if expires < today:
                errors.append(f"exception for {rid}: expired on {expires}")
                continue
        active.add(rid)
        warnings.append(f"exception for {rid} until {expires}: {e['reason']}")
    return active


def check_rules(rules: dict[str, dict], excepted: set[str]) -> None:
    for rid, r in rules.items():
        when = r.get("when")
        if when and not any((ROOT / w).exists() for w in ([when] if isinstance(when, str) else when)):
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
    gaps_text = (ctx / "gaps.md").read_text()
    tracked = {m.group(1): line for line in gaps_text.splitlines() if (m := GAP_ROW_RE.match(line))}
    for f in CONTEXT_FILES[:-1]:
        text = (ctx / f).read_text()
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
    if not path.exists():
        return found
    text = re.sub(r"(?s)<!--.*?-->", "", path.read_text())
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
    try:
        data = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as e:
        errors.append(f".keelokit/critical.toml: invalid TOML ({e})")
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
        for p in a["paths"]:
            if not (ROOT / p).exists():
                errors.append(f".keelokit/critical.toml: area '{name}' points at '{p}', which does not exist")
        areas.append(a)
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
    for line in path.read_text().splitlines():
        if not (m := ESCAPE_ROW_RE.match(line)):
            continue
        rows += 1
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 6 or not all(cells[:6]):
            errors.append(f"docs/escapes.md: {m.group(1)} needs id, date, found by, what escaped, class and check added")
    return rows


def done_story_ids() -> set[str]:
    """Stories closed by a `Story: <ID>` trailer on a commit reachable from main."""
    trailers = git("log", main_ref(), "--format=%(trailers:key=Story,valueonly,separator=%x2C)")
    return {sid.strip() for line in trailers.splitlines() for sid in line.split(",") if sid.strip()}


def read_story(path: Path) -> dict | None:
    text = path.read_text()
    m = re.match(r"\+\+\+\n(.*?)\n\+\+\+\n", text, re.S)
    if not m:
        errors.append(f"{path.relative_to(ROOT)}: missing +++ TOML front matter")
        return None
    try:
        meta = tomllib.loads(m.group(1))
    except tomllib.TOMLDecodeError as e:
        errors.append(f"{path.relative_to(ROOT)}: invalid front matter ({e})")
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
                titles += test_titles(path)
    return "\n".join(titles)


def overlaps(a: str, b: str) -> bool:
    a, b = a.rstrip("/"), b.rstrip("/")
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")


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
    done = done_story_ids() & stories.keys()
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
    for i, a in enumerate(pending):
        for b in pending[i + 1:]:
            if stories[a].get("wave") != stories[b].get("wave"):
                continue
            clash = [f"{x}" for x in stories[a].get("touches", []) for y in stories[b].get("touches", []) if overlaps(x, y)]
            if clash:
                errors.append(f"stories {a} and {b} share wave {stories[a].get('wave')} but both touch {', '.join(clash)} — move one to a later wave")
            shared = set(areas_hit(stories[a].get("touches", []), areas)) & set(areas_hit(stories[b].get("touches", []), areas))
            if shared:
                errors.append(f"stories {a} and {b} share wave {stories[a].get('wave')} and critical area {', '.join(sorted(shared))} — critical work goes one story at a time")
    corpus = cited_titles() if done else ""
    for sid in sorted(done):
        untested = [
            f"{sid}.{s}" for s in stories[sid]["_scenarios"]
            if not re.search(rf"{re.escape(sid)}\.{s}\b", corpus)  # .S1 must not match .S10
        ]
        if untested:
            errors.append(f"story {sid} is done but no active test title cites {', '.join(untested)} (TRACE-1)")
        unproven = [i for i in stories[sid].get("invariants", []) if not re.search(rf"\b{i}\b", corpus)]
        if unproven:
            errors.append(f"story {sid} is done but no active test title cites invariant {', '.join(unproven)} (INV-1)")
    ready = [
        sid for sid, m in stories.items()
        if sid not in done and all(d in done for d in m.get("depends_on", []))
    ]
    ready.sort(key=lambda s: (stories[s].get("wave", 99), s))
    return {"total": len(stories), "done": done, "ready": ready, "stories": stories}


def gate_state() -> dict:
    path = ROOT / ".keelokit/state.toml"
    return tomllib.loads(path.read_text()).get("gates", {}) if path.exists() else {}


def check_scope(sid: str) -> int:
    """Files this branch changed outside the story's `touches` (scope creep or a missing path)."""
    stories = {m.get("id"): m for p in (ROOT / "backlog/stories").glob(f"{sid}-*.md") if (m := read_story(p))}
    if sid not in stories:
        print(f"No story {sid} in backlog/stories")
        return 1
    story = stories[sid]
    touches = story.get("touches", [])
    changed = git("diff", "--name-only", f"{main_ref()}...HEAD").split()
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
    log = git("log", "--reverse", "--format=%H%x09%s", f"{main_ref()}..HEAD").splitlines()
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
        if "--changed" in sys.argv:
            base = git("merge-base", main_ref(), "HEAD").strip() or "HEAD"
            changed = set(git("diff", "--name-only", base).split())
            changed |= set(git("ls-files", "--others", "--exclude-standard").split())
            files = [f for f in files if f in changed]
        print("\n".join(files))
        return 0
    rules = load_rules()
    check_rules(rules, check_exceptions(set(rules)))
    gaps, blocking = check_context()
    invariants = check_invariants()
    areas, _ = load_critical()
    escapes = check_escapes()
    backlog = check_backlog(invariants, areas)
    gates = gate_state()
    answers = ROOT / ".keelokit/answers.yml"
    layout = "harness" if answers.exists() and re.search(r"(?m)^mode: harness$", answers.read_text()) else "project"
    gate_names = GATES[layout]
    pending = next((g for g in gate_names if not gates.get(g)), None)

    if mode == "--brief":
        print("Keelokit:", f"gate pending → {pending}" if pending else "all gates approved")
        print(f"Context gaps: {gaps} ({blocking} blocking) · "
              f"Backlog: {len(backlog['done'])}/{backlog['total']} done")
        if backlog["ready"]:
            print("Next ready stories:", ", ".join(backlog["ready"][:3]))
        if errors:
            print(f"Harness errors: {len(errors)} — run `pnpm doctor`")
        return 0

    print("Keelokit doctor")
    print(f"  Gates: " + " → ".join(f"{g}{' ✓' if gates.get(g) else ''}" for g in gate_names))
    print(f"  Rules: {len(rules)} · Context gaps: {gaps} ({blocking} blocking)")
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
