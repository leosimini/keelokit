#!/usr/bin/env python3
"""Review rounds and report formats, checked by a script instead of by good will. Stdlib only.

    review.py round ID [--blocking-open]   count a review round for story ID; the 3rd is refused
                                           unless a BLOCKING finding is still open
    review.py rounds ID                    how many rounds ID has had
    review.py reset ID                     forget ID's rounds (the story landed)
    review.py lint-review FILE|-           a reviewer's report: the format agents/reviewer.md fixes
    review.py lint-report FILE|-           an agent's final report: 8 lines at most, with a hash,
                                           no pasted blocks

Two rounds per story is the rule (build-story): the second only reviews what the first round's fixes
changed; a third means the story itself is wrong, so it is refused unless a BLOCKING item is open.
Counters live in the git directory (they belong to this clone, not to history).
"""
import sys

if sys.version_info < (3, 11):
    sys.exit(f"Keelokit needs Python 3.11+ (found {sys.version.split()[0]})")

import re  # noqa: E402
import subprocess  # noqa: E402
from pathlib import Path  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
MAX_ROUNDS = 2
FINDING = re.compile(r"^(BLOCKING|NON-BLOCKING)\s+-\s+\S+:\d+\S*\s+·\s+.+\s+·\s+.+\s+·\s+.+$")
REVIEW_HEAD = re.compile(r"^VERDICT:\s+(APPROVE|CHANGES REQUESTED)\s*$")
SECTIONS = ("UNDECLARED DIMENSIONS", "MISSING TESTS", "ESCAPES")
HASH = re.compile(r"\b[0-9a-f]{7,40}\b")


def counters() -> Path:
    out = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    d = (ROOT / out).resolve() / "keelokit-rounds"
    d.mkdir(exist_ok=True)
    return d


def read(src: str) -> str:
    return sys.stdin.read() if src == "-" else Path(src).read_text(errors="replace")


def rounds_of(sid: str) -> int:
    try:
        return int((counters() / sid).read_text().strip())
    except (OSError, ValueError):
        return 0


def cmd_round(args: list[str]) -> int:
    sid = args[0]
    n = rounds_of(sid) + 1
    if n > MAX_ROUNDS and "--blocking-open" not in args:
        print(f"review: {sid} already had {MAX_ROUNDS} rounds. A third needs a BLOCKING finding still open (--blocking-open); "
              "otherwise the remaining items are NON-BLOCKING and go in one commit at the end, or the story itself is wrong: stop and say so.")
        return 1
    (counters() / sid).write_text(str(n))
    print(f"review: round {n} for {sid}")
    return 0


def lint_review(text: str) -> list[str]:
    lines = [l.rstrip() for l in text.splitlines() if l.strip()]
    problems = []
    if not lines or not REVIEW_HEAD.match(lines[0]):
        problems.append("the first line must be `VERDICT: APPROVE` or `VERDICT: CHANGES REQUESTED`")
    findings = [l for l in lines[1:] if l.startswith(("BLOCKING", "NON-BLOCKING"))]
    for l in findings:
        if not FINDING.match(l):
            problems.append(f"not `BLOCKING|NON-BLOCKING - file:line · problem · why it matters · fix`: {l[:90]}")
    blocking = sum(1 for l in findings if l.startswith("BLOCKING"))
    if lines and REVIEW_HEAD.match(lines[0]):
        verdict = REVIEW_HEAD.match(lines[0]).group(1)
        if verdict == "APPROVE" and blocking:
            problems.append("APPROVE with BLOCKING findings")
        if verdict == "CHANGES REQUESTED" and not blocking:
            problems.append("CHANGES REQUESTED without a BLOCKING finding (NON-BLOCKING items alone approve)")
    if len(lines) > 25:
        problems.append(f"{len(lines)} lines: a review is 10 lines, 25 at the very most")
    return problems


def lint_report(text: str) -> list[str]:
    lines = [l for l in text.splitlines() if l.strip()]
    problems = []
    if len(lines) > 8:
        problems.append(f"{len(lines)} lines; a report is 8 lines or fewer")
    if not HASH.search(text):
        problems.append("no commit hash: 'done' without a pushed hash is not done")
    if "```" in text:
        problems.append("a pasted code block: give the path and the hash, not the content")
    if any(len(l) > 400 for l in lines):
        problems.append("a line over 400 characters: this looks like pasted content")
    return problems


def main() -> int:
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd, rest = a[0], a[1:]
    if cmd == "round" and rest:
        return cmd_round(rest)
    if cmd == "rounds" and rest:
        print(rounds_of(rest[0]))
        return 0
    if cmd == "reset" and rest:
        (counters() / rest[0]).unlink(missing_ok=True)
        return 0
    if cmd in ("lint-review", "lint-report") and rest:
        problems = (lint_review if cmd == "lint-review" else lint_report)(read(rest[0]))
        for p in problems:
            print(f"- {p}")
        print("ok" if not problems else f"{len(problems)} problem(s): rewrite the report and send it again")
        return 1 if problems else 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
