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
import os
import subprocess
import sys
import tomllib
import unicodedata
from pathlib import Path


def root_of(argv: list[str]) -> Path:
    """The project this runs on: `--root DIR`, first on the command line, or the one this file sits in. The plugin's
    hooks run their own copy with `--root <project>` (hooks/trusted.py, HARN-004)."""
    if argv[1:2] == ["--root"] and len(argv) > 2:
        root = Path(argv[2]).resolve()
        del argv[1:3]
        return root
    return Path(__file__).resolve().parents[2]


ROOT = root_of(sys.argv)

PLUGIN_MODE = ROOT != Path(__file__).resolve().parents[2]  # run with --root: by the plugin's hooks (HARN-004)
# Variables that point git at another repository, or at programs to run: none comes from the session's environment.
GIT_SCRUB = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
             "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE", "GIT_EXEC_PATH", "GIT_CONFIG", "GIT_SSH",
             "GIT_SSH_COMMAND", "GIT_ASKPASS", "GIT_EXTERNAL_DIFF", "GIT_PAGER", "GIT_EDITOR")


def harden_git(hooks_off: bool) -> None:
    """HARN-004 (ESC-271, ESC-280): run by the plugin's hooks, every git call of this copy reads no repository the
    project ships (a directory with HEAD, config, objects/ and refs/ is not a bare repository to it), runs no
    transport helper (ext::), no lazy fetch, no fsmonitor, prompts for nothing. git
    reads GIT_CONFIG_* as `-c`, above every config file. The hooks path is left as it is: the doctor reports it."""
    for key in GIT_SCRUB:
        os.environ.pop(key, None)
    config = {"safe.bareRepository": "explicit", "protocol.ext.allow": "never", "protocol.file.allow": "always",
              "core.fsmonitor": "false"}
    if hooks_off:
        config["core.hooksPath"] = os.devnull
    try:
        n = max(int(os.environ.get("GIT_CONFIG_COUNT") or 0), 0)
    except ValueError:
        n = 0
    for key, value in config.items():
        os.environ[f"GIT_CONFIG_KEY_{n}"] = key
        os.environ[f"GIT_CONFIG_VALUE_{n}"] = value
        n += 1
    os.environ["GIT_CONFIG_COUNT"] = str(n)
    os.environ.update(GIT_NO_LAZY_FETCH="1", GIT_TERMINAL_PROMPT="0", GIT_PROTOCOL_FROM_USER="0")


def git_dir_problem() -> str | None:
    """Why git must not run for ROOT, or None: the repository git finds has its git dir inside ROOT but is not
    ROOT/.git (a directory the repo ships, read as a repository by a git too old for safe.bareRepository)."""
    try:
        out = subprocess.run(["git", "rev-parse", "--absolute-git-dir"], cwd=ROOT, capture_output=True, text=True,
                             timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    found, root = Path(out.stdout.strip()).resolve(), ROOT.resolve()
    if found == root / ".git" or root not in (found, *found.parents):
        return None
    return (f"git reads {found} as this project's repository, a directory inside it that is not its .git, so "
            f"Keelokit runs no git here")


if PLUGIN_MODE:
    harden_git(False)
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
    skills = cfg["critique_skills"]
    if not isinstance(skills, list) or not all(isinstance(s, str) and s.strip() for s in skills):
        return cfg, (".keelokit/ux.toml: critique_skills must be a list of skill ids, like "
                     '["design:design-critique", "design:ux-copy"] ([] for none), not ' + repr(skills))
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


HEADING = re.compile(r"(?m)^ {0,3}(#{1,6})[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$")
FENCE = re.compile(r"^[ \t]*(?:(?:[-*+]|\d+[.)])[ \t]+)?(`{3,}|~{3,})")
RAN = re.compile(r"(?mi)^[ \t]*(?:[-*+][ \t]+)?[*_]*Ran[*_]*:[*_]*[ \t]*[*_]*(\d{4}-\d{2}-\d{2})\b")
ITEM = re.compile(r"^([ \t]*)(?:[-*+]|\d+[.)])[ \t]+(.*)$")
# What may come before a priority: a task box, emoji or other symbols, bold, a bracket.
PRIORITY = re.compile(r"(?i)^(?:\[[ xX]\][ \t]*)?[^\w\[(]*[\[(]?(P\d)\b[\])]?[*_:]*(.*)$")
# A skill's own severity where a priority belongs: a table cell that is only that, or an item that
# opens with it as a label ("Critical:", "**Major**", "🔴 …"), not a sentence that starts with the word.
SEVERITY_WORD = r"(?:critical|major|moderate|serious|blocker)"
SEVERITY_CELL = re.compile(rf"(?i)^\W*{SEVERITY_WORD}\W*$|^\W*[🔴🟠🟡]")
SEVERITY_HEAD = re.compile(rf"(?i)^\W*(?:{SEVERITY_WORD}|minor|total)\W*$")
SEVERITY_ITEM = re.compile(rf"(?i)^(?:[*_]+{SEVERITY_WORD}[*_]+|[\[(]?{SEVERITY_WORD}[\])]?[ \t]*[:—–]|\W*[🔴🟠🟡])")
STARTS_RESOLVED = re.compile(r"(?i)^(?:[—–]|-{1,2})?\s*(?:fixed in\s+\S|decided:\s*\S)")
# The item ends with a dash, then "fixed in <x>" or "decided: <reason>" (a reason may hold dashes,
# a "fixed in" may not: whatever follows another dash is not the end).
RESOLUTION = re.compile(r"(?i)(?:[—–]|(?:^|\s)-{1,2})\s*(?:fixed in\s+(?:(?![—–]|\s-{1,2}\s).)*\S|decided:\s*\S.*)$")


def unfenced(text: str) -> str:
    """The text with fenced code blocks blanked, NFKC-normalized (a fullwidth digit is a digit, a
    non-breaking space a space): a `# comment` in a code block is not a heading."""
    out, fence = [], None
    for line in unicodedata.normalize("NFKC", text).replace("\r\n", "\n").split("\n"):
        m = FENCE.match(line)
        if m and m.group(1)[0] == "`" and "`" in line[m.end():]:
            m = None  # ```code``` inline: a backtick fence's info string holds no backtick
        if fence:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence):
                fence = None
            out.append("")
        elif m:
            fence = m.group(1)
            out.append("")
        else:
            out.append(line)
    return "\n".join(out)


def sections(text: str, name: str) -> list[tuple[int, str]]:
    """(level, body) of every heading called `name` (any case, backticks or bold around it allowed);
    a body runs to the next heading of its level or higher."""
    heads = [(m.start(), m.end(), len(m.group(1)), m.group(2).strip().strip("`*").strip()) for m in HEADING.finditer(text)]
    out = []
    for i, (_, end, level, title) in enumerate(heads):
        if title.lower() == name.lower():
            stop = next((s for s, _, lv, _ in heads[i + 1:] if lv <= level), len(text))
            out.append((level, text[end:stop]))
    return out


def resolved(rest: str) -> bool:
    """A finding is resolved when it ends `— fixed in <x>` or `— decided: <reason>` (`-` or `–` will do)."""
    return bool(RESOLUTION.search(rest.strip()))


def findings(body: str) -> list[tuple[str | None, str, bool]]:
    """(priority or None, text, resolved) of each finding in a subsection: a list item, joined with
    the lines indented under it (a wrapped line, a sub-bullet holding the fix), or a table row."""
    out, lines, i = [], body.split("\n"), 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if line.strip().startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if all(re.fullmatch(r":?-*:?", c) for c in cells):
                continue
            at = next((k for k, c in enumerate(cells) if PRIORITY.match(c) and PRIORITY.match(c).group(2).strip() == ""), None)
            text = " | ".join(c for c in cells if c)
            after = [c for c in cells[at + 1:] if c] if at is not None else []
            if at is not None:  # the fix or the decision is the row's last cell
                out.append((PRIORITY.match(cells[at]).group(1).upper(), text,
                            bool(after) and bool(STARTS_RESOLVED.match(after[-1]))))
            elif any(SEVERITY_CELL.match(c) for c in cells) and not all(SEVERITY_HEAD.match(c) for c in cells if c):
                out.append((None, text, False))  # a row graded by severity (a header of severities is not)
            continue
        m = ITEM.match(line)
        if not m:
            continue
        indent, text, subs = len(m.group(1).expandtabs()), m.group(2), []
        while i < len(lines) and lines[i].strip() and len(lines[i]) - len(lines[i].lstrip()) > indent:
            sub = ITEM.match(lines[i])
            if sub and PRIORITY.match(sub.group(2)):
                break  # a finding of its own
            if sub:
                subs.append(sub.group(2).strip())  # a sub-bullet: the fix, or a note
            elif subs:
                subs[-1] += " " + lines[i].strip()
            else:
                text += " " + lines[i].strip()  # a wrapped line
            i += 1
        p = PRIORITY.match(text)
        if p:
            done = resolved(p.group(2)) or any(STARTS_RESOLVED.match(x) for x in subs)
            shown = " ".join([f"{p.group(1).upper()}{p.group(2)}".strip(), *subs])
            out.append((p.group(1).upper(), shown, done))
        elif SEVERITY_ITEM.match(text):
            out.append((None, text.strip(), False))
    return out


def skills_problems(text: str, skills: list[str], where: str) -> list[str]:
    """What the critique's `## Skills` sections lack (FLEET-004): a subsection per skill, its date, and
    a fix or a decision for every P0, P1 and P2 finding. Every Skills section and every subsection of a
    skill is read, so a later run is checked like the first. Shape only: the reviewer judges the content."""
    if not skills:
        return []
    found = sections(unfenced(text), "Skills")
    if not found:
        return [f'{where} lacks the section "Skills" (one "### <skill id>" subsection per skill the critique ran: '
                f'{", ".join(skills)}; see docs/ux-quality.md §4)']
    problems = []
    for skill in skills:
        subs = [b for level, body in found for lv, b in sections(body, skill) if lv > level]
        if not subs:
            problems.append(f'{where}, Skills: no "### {skill}" subsection (run the skill and record what it found)')
        for sub in subs:
            dates = RAN.findall(sub)
            try:
                ok = bool(dates) and bool(datetime.date.fromisoformat(dates[0]))
            except ValueError:
                ok = False
            if not ok:
                problems.append(f'{where}, {skill}: no "Ran: YYYY-MM-DD" line saying when the skill ran')
            for prio, item, done in findings(sub):
                item = item if len(item) <= 90 else item[:87] + "…"
                if prio is None:
                    problems.append(f'{where}, {skill}: "{item}" has a severity but no priority; write it as P0, P1, P2 or P3')
                elif prio in ("P0", "P1", "P2") and not done:
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
    if PLUGIN_MODE and (why := git_dir_problem()):  # ESC-280
        print(f"{why}.")
        return 2
    return check()


if __name__ == "__main__":
    sys.exit(main())
