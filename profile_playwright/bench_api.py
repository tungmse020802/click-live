#!/usr/bin/env python3
"""Quick concurrency check for deeplink API decode path."""

import concurrent.futures
import time
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8792"
URL = "https://i.junb.io.vn/i/?b7YVmORSncRD4"


def one_request(_: int) -> float:
    started = time.perf_counter()
    q = urllib.parse.urlencode({"url": URL})
    with urllib.request.urlopen(f"{BASE}/api/deeplink?{q}", timeout=5) as resp:
        resp.read()
    return time.perf_counter() - started


def main() -> None:
    for workers in (1, 4, 8, 16, 32):
        started = time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            times = list(pool.map(one_request, range(workers * 10)))
        elapsed = time.perf_counter() - started
        rps = (workers * 10) / elapsed
        p95 = sorted(times)[int(len(times) * 0.95) - 1]
        print(f"workers={workers:2d} total={workers*10:3d} elapsed={elapsed:.2f}s rps={rps:.0f} p95={p95*1000:.1f}ms")


if __name__ == "__main__":
    main()
