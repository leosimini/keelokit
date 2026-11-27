#!/usr/bin/env python3
"""Print the test modules of one CI shard: `python3 scripts/unit_shard.py <shard> <shards>` (1-based).

The unit suite outgrew one 10-minute CI job (it reached 9m54s on 2026-11-23). Keelokit's rule is to split a
slow job, never to raise its timeout, so CI runs the suite in shards. Each tests/test_*.py goes to exactly one
shard, the slowest first onto the lightest shard, so the split is deterministic and every new test file lands
somewhere without editing the workflow.

How slow a file is comes from SECONDS, measured (each module alone, `python3 -m unittest <module>`); file size did
not track it (LEDGER-010: test_verify_operativo is mid-sized and the slowest, and the size split left one of three
shards at twice the others). A file the table lacks weighs its size, scaled to seconds by the files it has.
Re-measure when a shard nears the job's timeout."""
import sys
from pathlib import Path

TESTS = Path(__file__).resolve().parents[1] / "tests"


# Seconds per module, measured 2026-11-24 on a 4-core machine, two modules at a time (test_breaker and
# test_ledger_swarm re-measured 2026-11-25 for HARN-022).
SECONDS = {
    "test_verify_operativo": 254, "test_ledger": 245, "test_ledger_harbor": 40, "test_ledger_swarm": 30, "test_breaker": 60, "test_doctor": 165, "test_run_local": 105, "test_guard": 120,
    "test_verify": 80, "test_dashboard": 72, "test_hooks": 44, "test_guard_corrections": 26, "test_copier": 13,
    "test_ux_gate": 10, "test_first_commit": 10, "test_landing": 6, "test_verify_plan": 3, "test_process": 3,
    "test_scripts": 2, "test_session_titles": 1, "test_release": 1, "test_ci": 1, "test_workflows": 0.5,
    "test_paths": 0.5,
}


def weights(files: list[Path]) -> dict[str, float]:
    """module -> its weight in seconds: SECONDS, else its size at the seconds per byte of the measured files."""
    known = [f for f in files if f.stem in SECONDS]
    size = sum(f.stat().st_size for f in known)
    rate = sum(SECONDS[f.stem] for f in known) / size if size else 1.0
    return {f.stem: SECONDS.get(f.stem, f.stat().st_size * rate) for f in files}


def shards(k: int) -> list[list[str]]:
    files = list(TESTS.glob("test_*.py"))
    weight = weights(files)
    bins: list[list[str]] = [[] for _ in range(k)]
    load = [0.0] * k
    for name in sorted(weight, key=lambda n: (-weight[n], n)):
        i = load.index(min(load))
        bins[i].append(name)
        load[i] += weight[name]
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
