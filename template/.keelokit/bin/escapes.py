#!/usr/bin/env python3
"""Log a bug that escaped, with the guard of its whole class. Stdlib only.

    escapes.py add --found-by WHO --what TEXT --class CLASS --guard KIND --check TEXT [--date D]
    escapes.py add ... --guard none --because WHY --owner WHO     (an exception, with an owner)
    escapes.py classes                                           the classes already in the log

KIND is one of: invariant, concurrency, arch-spec, lint, reviewer-checklist, test, none. A fix of
the single case is not a guard: without one this refuses to write (ESC-1). `arch-spec` is a test
that walks the source tree and fails on a forbidden pattern (references/arch-specs/). The row
goes into docs/escapes.md in the table's own format, so the doctor reads it as before, and the
reviewer and the spec-test writer read the same file as "the classes that already bit us".
"""
import sys

if sys.version_info < (3, 11):
    sys.exit(f"Keelokit needs Python 3.11+ (found {sys.version.split()[0]})")

import datetime as dt  # noqa: E402
import re  # noqa: E402
from pathlib import Path  # noqa: E402

PATH = Path(__file__).resolve().parents[2] / "docs/escapes.md"
KINDS = {"invariant", "concurrency", "arch-spec", "lint", "reviewer-checklist", "test", "none"}
ROW = re.compile(r"^\|\s*(ESC-(\d{3}))\s*\|")


def opt(args, name):
    return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else None


def rows() -> list[list[str]]:
    out = []
    for line in PATH.read_text().splitlines() if PATH.exists() else []:
        if ROW.match(line):
            out.append([c.strip() for c in line.strip().strip("|").split("|")])
    return out


def add(args: list[str]) -> int:
    need = {k: opt(args, f"--{k}") for k in ("found-by", "what", "class", "guard")}
    missing = [k for k, v in need.items() if not v]
    if missing:
        print("escapes: missing " + ", ".join(f"--{k}" for k in missing), file=sys.stderr)
        return 2
    kind = need["guard"]
    if kind not in KINDS:
        print(f"escapes: --guard must be one of {', '.join(sorted(KINDS))}", file=sys.stderr)
        return 2
    if kind == "none":
        if not (opt(args, "--because") and opt(args, "--owner")):
            print("escapes: no guard is an exception: say why (--because) and who owns the risk (--owner). "
                  "Fixing the single case is not enough: the same class comes back.", file=sys.stderr)
            return 1
        check = f"none — {opt(args, '--because')} (owner: {opt(args, '--owner')})"
    else:
        if not opt(args, "--check"):
            print("escapes: name the check (--check): the test, rule or line that now catches the whole class", file=sys.stderr)
            return 2
        check = f"{kind}: {opt(args, '--check')}"
    if not PATH.exists():
        print(f"escapes: {PATH} does not exist", file=sys.stderr)
        return 2
    text = PATH.read_text()
    n = max([int(m.group(2)) for l in text.splitlines() if (m := ROW.match(l))], default=0) + 1
    clean = lambda s: s.replace("|", "/").replace("\n", " ").strip()
    row = f"| ESC-{n:03d} | {opt(args, '--date') or dt.date.today().isoformat()} | {clean(need['found-by'])} | {clean(need['what'])} | {clean(need['class'])} | {clean(check)} |"
    PATH.write_text(text.rstrip("\n") + "\n" + row + "\n")
    same = [r[0] for r in rows()[:-1] if len(r) > 4 and r[4].lower() == need["class"].lower()]
    print(f"escapes: logged ESC-{n:03d}" + (f" — this class had already bitten before ({', '.join(same)}): the old guard did not hold; strengthen it" if same else ""))
    return 0


def main() -> int:
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if a[0] == "add":
        return add(a[1:])
    if a[0] == "classes":
        seen = {}
        for r in rows():
            if len(r) > 4:
                seen.setdefault(r[4], []).append(r[0])
        for c, ids in sorted(seen.items()):
            print(f"{c}\t{', '.join(ids)}")
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
