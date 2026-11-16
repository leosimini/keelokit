#!/usr/bin/env python3
"""UX-2: a branch that changes the interface carries its captures and its critique.

    python3 .keelokit/bin/ux_gate.py            check this branch against main
    python3 .keelokit/bin/ux_gate.py --config   print the settings in force

Reads `.keelokit/ux.toml` (product-owned; without it the defaults below apply to a project whose
profile lists the `ui` trait, and nothing applies to one without). The doctor runs it, so `pnpm
verify`, the pre-push hook and CI all stop a branch that fails.

A branch "changes the interface" when it touches a file matching `ui_paths` that no `exempt_paths`
glob excuses. It then needs, for at least one piece under `<evidence_dir>/<piece>/` touched on the
branch: a capture `<surface>-<width>-<theme>-<state>.png` for every configured surface, width and
theme, and a non-empty `CRITIQUE.md` holding every required section. Or a commit message line
`ux-gate: n/a — <reason>` (reason mandatory); the gate then passes and says so.
Exit 0 pass or not applicable, 1 fail, 2 cannot tell (no main to compare with)."""
from __future__ import annotations

import fnmatch
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
    "critique_sections": ["Design critique", "Consistency and coherence", "Real device"],
    "capture_ext": ["png"],
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


def piece_problems(piece: str, files: list[str], cfg: dict) -> list[str]:
    """What a piece's folder lacks. `files` are the piece's files on disk, relative to its folder."""
    problems = []
    names = [Path(f).name.lower() for f in files]
    exts = "|".join(re.escape(e) for e in cfg["capture_ext"])
    for want in expected_captures(cfg):
        if not any(re.fullmatch(rf"{re.escape(want)}-[a-z0-9][a-z0-9_-]*\.(?:{exts})", n) for n in names):
            problems.append(f"{piece}: no capture {want}-<state>.{cfg['capture_ext'][0]}")
    crit = piece_dir(cfg, piece) / cfg["critique_file"]
    text = crit.read_text() if crit.is_file() else ""
    if not text.strip():
        problems.append(f"{piece}: {cfg['critique_file']} missing or empty")
    else:
        for sec in cfg["critique_sections"]:
            if not re.search(rf"(?mi)^#+\s*{re.escape(sec)}\b", text):
                problems.append(f"{piece}: {cfg['critique_file']} lacks the section \"{sec}\"")
    return problems


def piece_dir(cfg: dict, piece: str) -> Path:
    return ROOT / cfg["evidence_dir"] / piece


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
    changed = git("diff", "--name-only", base, "HEAD").split()
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
        d = piece_dir(cfg, piece)
        files = [p.relative_to(d).as_posix() for p in d.rglob("*") if p.is_file()] if d.is_dir() else []
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
