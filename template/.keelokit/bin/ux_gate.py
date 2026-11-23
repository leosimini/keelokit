#!/usr/bin/env python3
"""UX-3: a branch that changes the interface carries its captures and its critique.

    python3 .keelokit/bin/ux_gate.py            check this branch against main
    python3 .keelokit/bin/ux_gate.py --config   print the settings in force

Reads `.keelokit/ux.toml` (product-owned; without it the defaults below apply to a project whose
profile lists the `ui` trait, and nothing applies to one without). The doctor runs it, so `pnpm
verify`, the pre-push hook and CI all stop a branch that fails.

A branch "changes the interface" when it touches a file matching `ui_paths` that no `exempt_paths`
glob excuses. It then needs, for every piece under `<evidence_dir>/<piece>/` touched on the
branch (and at least one): a capture `<surface>-<width>-<theme>-<state>.png` for every configured surface, width and
theme, and a non-empty `CRITIQUE.md` holding every required section and, unless `critique_skills` is
empty, a `## Skills` section with one `### <skill id>` subsection per listed skill, each with a line
`Ran: YYYY-MM-DD` and every P0/P1/P2 finding (a list item starting `P1`…) ending `— fixed in <commit or
file>` or `— decided: <reason>` (docs/ux-quality.md §4). Or a commit message line
`ux-gate: n/a — <reason>` (reason mandatory); the gate then passes and says so.
Exit 0 pass or not applicable, 1 fail, 2 cannot tell (no main to compare with)."""
from __future__ import annotations

import datetime
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

DEFAULTS = {
    "ui_paths": ["apps/web/src/**", "apps/mobile/src/**", "apps/site/src/**", "packages/ui*/src/**"],
    "exempt_paths": ["**/*.test.*", "**/*.spec.*", "**/__tests__/**", "**/*.md", "**/i18n/**", "**/locales/**"],
    "evidence_dir": "docs/design/captures",
    "surfaces": ["mobile", "desktop"],
    "widths": {"mobile": [360, 390], "desktop": [1280, 1440]},
    "themes": ["light", "dark"],
    "critique_file": "CRITIQUE.md",
    "critique_sections": ["Journey", "Design critique", "Consistency and coherence", "Real device"],
    "capture_ext": ["png"],
    "critique_skills": ["design:design-critique", "design:ux-copy", "design:accessibility-review"],
}
MARKER = re.compile(r"(?mi)^ux-gate:\s*n/a\s*[—–-]+\s*(\S.*)$")


def glob_re(pattern: str) -> re.Pattern:
    """`**` crosses folders, `*` and `?` stay inside one."""
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif pattern.startswith("**", i):
            out, i = out + ".*", i + 2
        elif pattern[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif pattern[i] == "?":
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(pattern[i]), i + 1
    return re.compile(out + r"\Z")


def matches(path: str, patterns: list[str]) -> bool:
    return any(glob_re(p).match(path) for p in patterns)


def git(*args: str) -> str:
    out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    return out.stdout if out.returncode == 0 else ""


def settings() -> tuple[dict, str | None]:
    cfg = dict(DEFAULTS)
    path = ROOT / ".keelokit/ux.toml"
    if path.exists():
        try:
            cfg.update(tomllib.loads(path.read_text()).get("gate", {}))
        except (tomllib.TOMLDecodeError, OSError) as e:
            return cfg, f".keelokit/ux.toml: {e}"
    return cfg, None


def has_ui_trait() -> bool:
    try:
        return "ui" in tomllib.loads((ROOT / ".keelokit/profile.toml").read_text()).get("traits", [])
    except (OSError, tomllib.TOMLDecodeError):
        return False


def expected_captures(cfg: dict) -> list[str]:
    """The matrix every piece covers: one capture per surface x width x theme (any state)."""
    themes = cfg["themes"] or [""]
    return [f"{s}-{w}" + (f"-{t}" if t else "") for s in cfg["surfaces"] for w in cfg["widths"].get(s, []) for t in themes]


HEADING = re.compile(r"(?m)^(#{1,6})[ \t]+(.*?)[ \t]*#*[ \t]*$")
RAN = re.compile(r"(?mi)^[ \t]*(?:[-*+][ \t]+)?\**Ran:\**[ \t]*(\d{4}-\d{2}-\d{2})\b")
FINDING = re.compile(r"(?m)^[ \t]*(?:[-*+]|\d+[.)])[ \t]+\**(P\d)\b\**(.*)$")
# The item ends with a dash, then "fixed in <x>" or "decided: <reason>" (a reason may hold dashes).
RESOLUTION = re.compile(r"(?i)(?:[—–]|(?:^|\s)-{1,2})\s*(?:fixed in\s+[^\s—–][^—–]*|decided:\s*\S.*)$")


def sections(text: str, name: str) -> list[tuple[int, str]]:
    """(level, body) of every heading called `name`; a body runs to the next heading of its level or higher."""
    heads = [(m.start(), m.end(), len(m.group(1)), m.group(2).strip().strip("`").strip()) for m in HEADING.finditer(text)]
    out = []
    for i, (_, end, level, title) in enumerate(heads):
        if title.lower() == name.lower():
            stop = next((s for s, _, lv, _ in heads[i + 1:] if lv <= level), len(text))
            out.append((level, text[end:stop]))
    return out


def resolved(rest: str) -> bool:
    """A finding is resolved when it ends `— fixed in <x>` or `— decided: <reason>` (`-` or `–` will do)."""
    return bool(RESOLUTION.search(rest))


def skills_problems(text: str, skills: list[str], where: str) -> list[str]:
    """What the critique's `## Skills` section lacks (FLEET-004): a subsection per skill, its date, and
    a fix or a decision for every P0, P1 and P2 finding. Shape only: the reviewer judges the content."""
    if not skills:
        return []
    found = sections(text, "Skills")
    if not found:
        return [f'{where} lacks the section "Skills" (one "### <skill id>" subsection per skill the critique ran: '
                f'{", ".join(skills)}; see docs/ux-quality.md §4)']
    level, body = found[0]
    problems = []
    for skill in skills:
        subs = [b for lv, b in sections(body, skill) if lv > level]
        if not subs:
            problems.append(f'{where}, Skills: no "### {skill}" subsection (run the skill and record what it found)')
            continue
        sub = subs[0]
        dates = RAN.findall(sub)
        try:
            ok = bool(dates) and bool(datetime.date.fromisoformat(dates[0]))
        except ValueError:
            ok = False
        if not ok:
            problems.append(f'{where}, {skill}: no "Ran: YYYY-MM-DD" line saying when the skill ran')
        for prio, rest in FINDING.findall(sub):
            if prio in ("P0", "P1", "P2") and not resolved(rest):
                item = f"{prio}{rest}".strip()
                item = item if len(item) <= 90 else item[:87] + "…"
                problems.append(f'{where}, {skill}: open finding "{item}" — end it with "— fixed in <commit or file>" '
                                'or "— decided: <reason>"')
    return problems


def piece_problems(piece: str, files: list[str], cfg: dict) -> list[str]:
    """What a piece's folder lacks. `files` are the piece's files on disk, relative to its folder."""
    problems = []
    # `before/` holds the captures from before a fix: they show the change, they don't fill the matrix.
    names = [Path(f).name.lower() for f in files if not f.startswith("before/")]
    exts = "|".join(re.escape(e) for e in cfg["capture_ext"])
    for want in (w.lower() for w in expected_captures(cfg)):
        if not any(re.fullmatch(rf"{re.escape(want)}-[a-z0-9][a-z0-9_-]*\.(?:{exts})", n) for n in names):
            problems.append(f"{piece}: no capture {want}-<state>.{cfg['capture_ext'][0]}")
    text = git("show", f"HEAD:{cfg['evidence_dir'].rstrip('/')}/{piece}/{cfg['critique_file']}")
    if not text.strip():
        problems.append(f"{piece}: {cfg['critique_file']} missing or empty")
    else:
        for sec in cfg["critique_sections"]:
            if not re.search(rf"(?mi)^#+\s*{re.escape(sec)}\b", text):
                problems.append(f"{piece}: {cfg['critique_file']} lacks the section \"{sec}\"")
        problems += skills_problems(text, cfg["critique_skills"], f"{piece}: {cfg['critique_file']}")
    return problems


def check() -> int:
    cfg, err = settings()
    if err:
        print(f"ux-gate: {err}")
        return 1
    if not (ROOT / ".keelokit/ux.toml").exists() and not has_ui_trait():
        print("ux-gate: not applicable (no ux.toml, no `ui` trait)")
        return 0
    if cfg.get("enabled", True) is False:
        print("ux-gate: switched off in .keelokit/ux.toml")
        return 0
    ref = next((r for r in ("origin/main", "main") if git("rev-parse", "--verify", "--quiet", r).strip()), None)
    base = ref and git("merge-base", ref, "HEAD").strip()
    if not base:
        print("ux-gate: no main or origin/main to compare with; fetch it (CI: fetch-depth: 0)")
        return 2
    changed = [f for f in git("diff", "-z", "--name-only", base, "HEAD").split("\0") if f]
    tracked = [f for f in git("ls-tree", "-r", "-z", "--name-only", "HEAD").split("\0") if f]
    if not any(matches(f, cfg["ui_paths"]) for f in tracked):
        print("ux-gate: no tracked file matches `ui_paths` in .keelokit/ux.toml, so nothing is ever treated as interface; "
              "set it to your apps' folders")
    ui = [f for f in changed if matches(f, cfg["ui_paths"]) and not matches(f, cfg["exempt_paths"])]
    if not ui:
        print("ux-gate: no interface files changed")
        return 0
    reasons = MARKER.findall(git("log", "--format=%B", f"{base}..HEAD"))
    if reasons:
        print(f"ux-gate: n/a — {reasons[-1].strip()} (exception on {len(ui)} interface file(s); the reviewer judges it)")
        return 0
    ev = cfg["evidence_dir"].rstrip("/") + "/"
    pieces = sorted({f[len(ev):].split("/")[0] for f in changed if f.startswith(ev) and "/" in f[len(ev):]})
    if not pieces:
        print(f"ux-gate: {len(ui)} interface file(s) changed ({', '.join(ui[:3])}{'…' if len(ui) > 3 else ''}) "
              f"but nothing under {ev}<piece>/. Add the captures and {cfg['critique_file']}, "
              "or a commit line `ux-gate: n/a — <reason>`.")
        return 1
    problems = []
    for piece in pieces:
        pre = f"{ev}{piece}/"
        files = [f[len(pre):] for f in tracked if f.startswith(pre)]  # committed files only: what CI will see
        problems += piece_problems(piece, files, cfg)
    if problems:
        print("ux-gate: the evidence is incomplete:\n  " + "\n  ".join(problems))
        return 1
    print(f"ux-gate: {len(pieces)} piece(s) with captures and critique: {', '.join(pieces)}")
    return 0


def main() -> int:
    if sys.argv[1:] == ["--config"]:
        cfg, err = settings()
        print(err or "\n".join(f"{k} = {v}" for k, v in cfg.items()))
        return 1 if err else 0
    if sys.argv[1:]:
        print(__doc__.split("\n\n")[0], file=sys.stderr)
        return 2
    return check()


if __name__ == "__main__":
    sys.exit(main())
