#!/usr/bin/env python3
"""Print the test modules of one CI shard: `python3 scripts/unit_shard.py <shard> <shards>` (1-based).

The unit suite outgrew one 10-minute CI job (it reached 9m54s on 2026-11-23). Keelokit's rule is to split a
slow job, never to raise its timeout, so CI runs the suite in shards. Each tests/test_*.py goes to exactly one
shard, the largest files first onto the lightest shard (file size stands in for duration), so the split is
deterministic and every new test file lands somewhere without editing the workflow."""
import sys
from pathlib import Path

TESTS = Path(__file__).resolve().parents[1] / "tests"


def shards(k: int) -> list[list[str]]:
    files = sorted(TESTS.glob("test_*.py"), key=lambda p: (-p.stat().st_size, p.name))
    bins: list[list[str]] = [[] for _ in range(k)]
    load = [0] * k
    for f in files:
        i = load.index(min(load))
        bins[i].append(f.stem)
        load[i] += f.stat().st_size
    return [sorted(b) for b in bins]


def main(argv: list[str]) -> int:
    try:
        n, k = int(argv[0]), int(argv[1])
        if not 1 <= n <= k:
            raise ValueError
    except (IndexError, ValueError):
        print("usage: unit_shard.py <shard> <shards>, 1 <= shard <= shards", file=sys.stderr)
        return 2
    print(" ".join(shards(k)[n - 1]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
