"""Benchmark the /api/profiles query mix.

Sends a representative set of queries N times each and reports
P50/P95/P99 latency. Use this BEFORE and AFTER each optimization phase
to capture honest before/after numbers for SOLUTION.md.

Usage:
    # Default — local backend, 50 iterations per query
    uv run python scripts/benchmark.py

    # Specific URL / more iterations
    uv run python scripts/benchmark.py \\
        --base-url https://insighta-labs-production-c161.up.railway.app \\
        --iterations 100

Requires the backend to be running and reachable at --base-url.
"""

import argparse
import os
import statistics
import sys
import time

import httpx

# Allow `python scripts/benchmark.py` from the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# A representative mix. Each tuple: (label, path, query_params).
# These cover the real read patterns: bare list, single-filter, multi-filter,
# heavy filter, NL search, stats aggregation. The "heavy" query is the one
# that should benefit most from the composite index.
QUERY_MIX = [
    ("list:no-filter",
        "/api/profiles", {"limit": 10}),
    ("list:gender",
        "/api/profiles", {"gender": "female", "limit": 10}),
    ("list:gender+country",
        "/api/profiles", {"gender": "female", "country_id": "NG", "limit": 10}),
    ("list:heavy-filter",
        "/api/profiles", {
            "gender": "female", "country_id": "NG",
            "age_group": "adult", "min_age": 25, "max_age": 45, "limit": 10,
        }),
    ("search:nl",
        "/api/profiles/search", {"q": "young males from nigeria"}),
    ("stats",
        "/api/profiles/stats", {}),
]


def get_admin_token(base_url: str) -> str:
    """Fetch admin tokens via the test_code shortcut."""
    r = httpx.get(f"{base_url}/auth/github/callback?code=test_code", timeout=30.0)
    r.raise_for_status()
    return r.json()["access_token"]


def measure(
    client: httpx.Client,
    path: str,
    params: dict,
    iterations: int,
    warmup: int,
) -> list[float]:
    """Send `iterations` requests after `warmup` discards. Return ms samples."""
    for _ in range(warmup):
        client.get(path, params=params)

    samples: list[float] = []
    bad = 0
    for _ in range(iterations):
        t0 = time.perf_counter_ns()
        r = client.get(path, params=params)
        elapsed_ms = (time.perf_counter_ns() - t0) / 1_000_000
        if r.status_code >= 400:
            bad += 1
        samples.append(elapsed_ms)

    if bad:
        print(f"    WARN: {bad}/{iterations} responses >= 400")
    return samples


def percentile(samples: list[float], p: int) -> float:
    """Return the p-th percentile (1..99). Inclusive method."""
    if len(samples) < 2:
        return samples[0] if samples else 0.0
    qs = statistics.quantiles(samples, n=100, method="inclusive")
    return qs[p - 1]


def main(base_url: str, iterations: int, warmup: int) -> int:
    base_url = base_url.rstrip("/")
    print(f"\nBenchmark target: {base_url}")
    print(f"Iterations per query: {iterations}  (warmup: {warmup})")

    try:
        token = get_admin_token(base_url)
    except httpx.HTTPError as e:
        print(
            f"ERROR: could not get admin token from {base_url}: {e}",
            file=sys.stderr,
        )
        return 1

    headers = {
        "Authorization": f"Bearer {token}",
        "X-API-Version": "1",
    }

    header = (
        f"\n{'Query':<22} {'P50':>10} {'P95':>10} "
        f"{'P99':>10} {'min':>10} {'max':>10}"
    )
    print(header)
    print("-" * len(header))

    with httpx.Client(base_url=base_url, headers=headers, timeout=30.0) as client:
        for label, path, params in QUERY_MIX:
            samples = measure(client, path, params, iterations, warmup)
            p50 = percentile(samples, 50)
            p95 = percentile(samples, 95)
            p99 = percentile(samples, 99)
            print(
                f"{label:<22} "
                f"{p50:>8.1f}ms {p95:>8.1f}ms {p99:>8.1f}ms "
                f"{min(samples):>8.1f}ms {max(samples):>8.1f}ms"
            )
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument(
        "--iterations", type=int, default=50,
        help="requests per query type",
    )
    parser.add_argument(
        "--warmup", type=int, default=3,
        help="discarded warmup requests per query",
    )
    args = parser.parse_args()
    sys.exit(main(args.base_url, args.iterations, args.warmup))
