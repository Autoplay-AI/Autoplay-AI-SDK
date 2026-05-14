"""
Stress test: fires concurrent POST requests across N synthetic products to the
event-connector webhook, simulating a burst of PostHog events.

Each product gets its own pool of sessions, and each session's events are
chunked into batches before being sent as individual HTTP requests.

CSV rows are streamed to disk immediately — no in-memory row accumulation —
so the full-scale run (50 × 1 000 × 1 000 = 50 M events, 5 M requests) stays
within a ~200 MB RAM footprint for the in-flight latency list.

Usage:
    python3 src/customer_sdk/tests/stress_test_sdk.py [OPTIONS]

Examples:
    # Smoke (500 requests) — seed PRODUCTS_CONFIG with stress-product-* rows, then:
    python3 src/customer_sdk/tests/stress_test_sdk.py --sessions 10 --events 10 --concurrency 20 --skip-product-registration

    # Auto-register via POST /products (open registration; needs Redis + Render on connector)
    python3 src/customer_sdk/tests/stress_test_sdk.py --sessions 10 --events 10
    # Optional: pass --admin-key for DELETE teardown of synthetic products only

    # Medium (50 K requests)
    python3 src/customer_sdk/tests/stress_test_sdk.py --sessions 100 --events 100 --concurrency 100

    # Full target (5 M requests)
    python3 src/customer_sdk/tests/stress_test_sdk.py --sessions 1000 --events 1000 --concurrency 500
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import math
import random
import sys
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

import httpx

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BUTTON_TEXTS = [
    "Submit",
    "Save",
    "Cancel",
    "Delete",
    "Edit",
    "View",
    "Confirm",
    "Next",
    "Back",
    "Search",
    "Filter",
    "Export",
    "Import",
    "Refresh",
]

_URLS = [
    "https://app.example.com/dashboard",
    "https://app.example.com/settings",
    "https://app.example.com/reports",
    "https://app.example.com/users",
    "https://app.example.com/billing",
]

_EVENT_TYPES = ["click", "change", "submit", "keydown"]


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


class RequestResult(NamedTuple):
    timestamp_utc: str
    product_id: str
    session_id: str
    chunk_idx: int
    events_in_batch: int
    latency_ms: float
    status_code: int
    success: bool
    error: str


# ---------------------------------------------------------------------------
# Payload builder
# ---------------------------------------------------------------------------


def _build_payload(session_id: str, distinct_id: str, events: int) -> dict:
    """Build a PostHog-shaped batch payload for one session chunk."""
    now = datetime.now(timezone.utc).isoformat()
    return {
        "batch": [
            {
                "event": "$autocapture",
                "timestamp": now,
                "distinct_id": distinct_id,
                "properties": {
                    "$event_type": random.choice(_EVENT_TYPES),
                    "$current_url": random.choice(_URLS),
                    "$session_id": session_id,
                    "$button_text": random.choice(_BUTTON_TEXTS),
                    "$elements_chain": f"button.btn:nth-child({i + 1})",
                },
            }
            for i in range(events)
        ]
    }


# ---------------------------------------------------------------------------
# Core worker
# ---------------------------------------------------------------------------


async def _send_request(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    base_url: str,
    product_id: str,
    session_id: str,
    distinct_id: str,
    chunk_idx: int,
    batch_size: int,
    secret: str,
) -> RequestResult:
    """Send one batched POST and return a fully-populated result."""
    payload = _build_payload(session_id, distinct_id, batch_size)
    headers = {"Content-Type": "application/json"}
    if secret:
        headers["X-PostHog-Secret"] = secret

    url = f"{base_url.rstrip('/')}/webhook/{product_id}"
    status_code = 0
    error = ""
    t0 = time.perf_counter()  # will be reset inside sem — measures connector time only

    async with sem:
        t0 = time.perf_counter()  # start timing after acquiring slot, not in queue
        try:
            resp = await client.post(url, json=payload, headers=headers)
            status_code = resp.status_code
            if status_code >= 400:
                error = resp.text[:200]
        except httpx.TimeoutException as exc:
            error = f"timeout: {exc}"
        except httpx.RequestError as exc:
            error = f"request_error: {exc}"

    latency_ms = (time.perf_counter() - t0) * 1000
    success = 200 <= status_code < 300

    return RequestResult(
        timestamp_utc=datetime.now(timezone.utc).isoformat(),
        product_id=product_id,
        session_id=session_id,
        chunk_idx=chunk_idx,
        events_in_batch=batch_size,
        latency_ms=round(latency_ms, 3),
        status_code=status_code,
        success=success,
        error=error,
    )


# ---------------------------------------------------------------------------
# Work generator
# ---------------------------------------------------------------------------


def _generate_work(products: int, sessions: int, events: int, batch_size: int):
    """Yield (product_id, session_id, distinct_id, chunk_idx, batch_size) tuples."""
    chunks_per_session = math.ceil(events / batch_size)
    final_chunk_size = events - (chunks_per_session - 1) * batch_size

    for p in range(1, products + 1):
        product_id = f"stress-product-{p:03d}"
        for _ in range(sessions):
            session_id = str(uuid.uuid4())
            distinct_id = str(uuid.uuid4())
            for c in range(chunks_per_session):
                size = final_chunk_size if c == chunks_per_session - 1 else batch_size
                yield (product_id, session_id, distinct_id, c, size)


# ---------------------------------------------------------------------------
# Progress tracker
# ---------------------------------------------------------------------------


class _Progress:
    """Thread-safe counter for real-time progress printing."""

    def __init__(self, total: int) -> None:
        self._total = total
        self._done = 0
        self._success = 0
        self._fail = 0
        self._start = time.perf_counter()
        self._lock = asyncio.Lock()

    async def record(self, success: bool) -> None:
        async with self._lock:
            self._done += 1
            if success:
                self._success += 1
            else:
                self._fail += 1
            if (
                self._done % max(1, self._total // 200) == 0
                or self._done == self._total
            ):
                self._print()

    def _print(self) -> None:
        elapsed = time.perf_counter() - self._start
        rps = self._done / elapsed if elapsed > 0 else 0
        pct = self._done / self._total * 100
        eta = (self._total - self._done) / rps if rps > 0 else float("inf")
        eta_str = f"{eta:.0f}s" if eta != float("inf") else "∞"
        print(
            f"\r  {pct:5.1f}%  {self._done:>8}/{self._total}  "
            f"{rps:7.1f} req/s  ETA {eta_str:>6}  "
            f"ok={self._success} fail={self._fail}",
            end="",
            flush=True,
        )


# ---------------------------------------------------------------------------
# Percentile helpers
# ---------------------------------------------------------------------------


def _percentile(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return 0.0
    idx = int(math.ceil(p / 100 * len(sorted_values))) - 1
    return sorted_values[max(0, idx)]


# ---------------------------------------------------------------------------
# Summary printer
# ---------------------------------------------------------------------------


def _print_summary(
    all_latencies: list[float],
    per_product: dict[str, dict],
    elapsed: float,
    thresholds: dict,
) -> bool:
    """Print aggregate + per-product table. Returns True if all thresholds pass."""
    print("\n\n" + "=" * 72)
    print("STRESS TEST RESULTS")
    print("=" * 72)

    total = sum(v["n"] for v in per_product.values())
    success = sum(v["ok"] for v in per_product.values())
    fail = total - success
    success_rate = success / total * 100 if total else 0

    sl = sorted(all_latencies)
    p50 = _percentile(sl, 50)
    p95 = _percentile(sl, 95)
    p99 = _percentile(sl, 99)
    throughput = total / elapsed if elapsed > 0 else 0

    print(f"\n  Total requests : {total:>10,}")
    print(f"  Success        : {success:>10,}  ({success_rate:.2f}%)")
    print(f"  Failures       : {fail:>10,}")
    print(f"  Elapsed        : {elapsed:>10.1f}s")
    print(f"  Throughput     : {throughput:>10.1f} req/s")
    print(f"\n  Latency (ms)   :    p50={p50:.1f}    p95={p95:.1f}    p99={p99:.1f}")

    # Per-product table
    print(
        f"\n{'Product':>30}  {'Reqs':>8}  {'OK%':>6}  {'p50':>7}  {'p95':>7}  {'p99':>7}"
    )
    print("-" * 72)
    for pid, stats in sorted(per_product.items()):
        pl = sorted(stats["latencies"])
        pp50 = _percentile(pl, 50)
        pp95 = _percentile(pl, 95)
        pp99 = _percentile(pl, 99)
        ok_pct = stats["ok"] / stats["n"] * 100 if stats["n"] else 0
        print(
            f"  {pid:>28}  {stats['n']:>8,}  {ok_pct:>5.1f}%"
            f"  {pp50:>7.1f}  {pp95:>7.1f}  {pp99:>7.1f}"
        )

    # Threshold evaluation
    print("\n" + "=" * 72)
    print("THRESHOLD CHECK")
    print("=" * 72)

    min_success_rate = thresholds["min_success_rate"]
    max_p99_ms = thresholds["max_p99_ms"]
    max_p50_ms = thresholds["max_p50_ms"]

    checks = [
        (
            "Success rate",
            f"{success_rate:.2f}% >= {min_success_rate}%",
            success_rate >= min_success_rate,
        ),
        ("p99 latency", f"{p99:.1f}ms <= {max_p99_ms}ms", p99 <= max_p99_ms),
        ("p50 latency", f"{p50:.1f}ms <= {max_p50_ms}ms", p50 <= max_p50_ms),
    ]

    all_pass = True
    for name, detail, passed in checks:
        status = "PASS" if passed else "FAIL"
        if not passed:
            all_pass = False
        print(f"  [{status}]  {name}: {detail}")

    print("=" * 72)
    overall = "ALL CHECKS PASSED" if all_pass else "ONE OR MORE CHECKS FAILED"
    print(f"  {overall}")
    print("=" * 72 + "\n")

    return all_pass


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def _run(args: argparse.Namespace) -> bool:
    """Run the stress test. Returns True if all thresholds pass."""
    products = args.products
    sessions = args.sessions
    events = args.events
    batch_size = args.batch_size
    concurrency = args.concurrency

    total_requests = products * sessions * math.ceil(events / batch_size)
    total_events = products * sessions * events

    print("\nStress Test — event-connector webhook")
    print(f"  Target : {args.base_url}")
    print(f"  Matrix : {products} products × {sessions} sessions × {events} events")
    print(
        f"  Batches: {math.ceil(events / batch_size)} requests/session "
        f"(batch_size={batch_size})"
    )
    print(f"  Total  : {total_requests:,} requests  ({total_events:,} events)")
    print(
        f"  Concur.: {concurrency}  |  Secret: {'(set)' if args.secret else '(none)'}"
    )

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = Path(args.out or f"stress_results_{ts}.csv")

    print(f"  Output : {out_path}\n")

    base = args.base_url.rstrip("/")

    # Pre-flight: verify the connector is reachable before firing all requests
    try:
        async with httpx.AsyncClient(timeout=5.0) as probe:
            r = await probe.get(f"{base}/health")
        print(f"  Health : {base}/health → {r.status_code} OK")
    except Exception as exc:
        print(f"\n  ERROR: Cannot reach connector at {base}/health")
        print(f"         {exc}")
        print("\n  Is the connector running?  Try:")
        print("    uvicorn event_connector.api.app:app --host 0.0.0.0 --port 8080 --reload\n")
        return False

    # Register all synthetic products before firing events (optional).
    product_ids = [f"stress-product-{p:03d}" for p in range(1, products + 1)]

    do_register = not args.skip_product_registration
    if args.skip_product_registration:
        print(
            "  Setup  : --skip-product-registration (no POST /products; "
            "expect stress-product-* in PRODUCTS_CONFIG or Redis)\n"
        )
    elif do_register:
        print(f"  Setup  : registering {products} synthetic products …")
        post_headers = {"Content-Type": "application/json"}
        registered: list[str] = []
        async with httpx.AsyncClient(timeout=10.0) as admin:
            for pid in product_ids:
                try:
                    resp = await admin.post(
                        f"{base}/products",
                        json={
                            "product_id": pid,
                            "contact_email": "stress-load@example.com",
                            "integration_type": "event_stream",
                            "integration_config": {"mode": "sse"},
                        },
                        headers=post_headers,
                    )
                    if resp.status_code in (200, 201, 409):
                        registered.append(pid)
                    else:
                        print(
                            f"\n  WARNING: Could not register {pid}: {resp.status_code} {resp.text[:120]}"
                        )
                except Exception as exc:
                    print(f"\n  WARNING: Error registering {pid}: {exc}")
        print(f"  Setup  : {len(registered)}/{products} products ready\n")

    all_latencies: list[float] = []
    per_product: dict[str, dict] = defaultdict(
        lambda: {"n": 0, "ok": 0, "latencies": []}
    )

    sem = asyncio.Semaphore(concurrency)
    progress = _Progress(total_requests)

    work = list(_generate_work(products, sessions, events, batch_size))

    t_start = time.perf_counter()

    with out_path.open("w", newline="") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(RequestResult._fields)

        async with httpx.AsyncClient(timeout=30.0) as client:
            tasks = [
                asyncio.create_task(
                    _send_request(
                        client,
                        sem,
                        args.base_url,
                        product_id,
                        session_id,
                        distinct_id,
                        chunk_idx,
                        size,
                        args.secret,
                    )
                )
                for product_id, session_id, distinct_id, chunk_idx, size in work
            ]

            for coro in asyncio.as_completed(tasks):
                result: RequestResult = await coro
                writer.writerow(result)
                all_latencies.append(result.latency_ms)
                pp = per_product[result.product_id]
                pp["n"] += 1
                pp["latencies"].append(result.latency_ms)
                if result.success:
                    pp["ok"] += 1
                await progress.record(result.success)

    elapsed = time.perf_counter() - t_start

    # Teardown: DELETE /products/{id} still requires X-Admin-Key when CONNECTOR_ADMIN_KEY is set.
    if do_register and args.admin_key:
        print(
            "\n  Teardown: deregistering synthetic products (DELETE uses --admin-key) …"
        )
        admin_headers = {"X-Admin-Key": args.admin_key}
        async with httpx.AsyncClient(timeout=10.0) as admin:
            for pid in product_ids:
                try:
                    await admin.delete(f"{base}/products/{pid}", headers=admin_headers)
                except Exception:
                    pass
        print("  Teardown: done\n")
    elif do_register:
        print(
            "\n  Teardown: skipped (pass --admin-key matching CONNECTOR_ADMIN_KEY to DELETE "
            "stress-product-* rows)\n"
        )

    thresholds = {
        "min_success_rate": args.min_success_rate,
        "max_p99_ms": args.max_p99_ms,
        "max_p50_ms": args.max_p50_ms,
    }

    return _print_summary(all_latencies, per_product, elapsed, thresholds)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stress test the event-connector webhook across multiple synthetic products.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--base-url", default="http://localhost:8080", help="Connector base URL"
    )
    parser.add_argument(
        "--products", type=int, default=50, help="Number of synthetic products"
    )
    parser.add_argument(
        "--sessions", type=int, default=1000, help="Sessions per product"
    )
    parser.add_argument("--events", type=int, default=1000, help="Events per session")
    parser.add_argument(
        "--batch-size", type=int, default=10, help="Events per HTTP request"
    )
    parser.add_argument(
        "--concurrency", type=int, default=200, help="Max in-flight requests"
    )
    parser.add_argument("--secret", default="", help="X-PostHog-Secret header value")
    parser.add_argument(
        "--admin-key",
        default="",
        help=(
            "X-Admin-Key for DELETE /products/{id} teardown only (CONNECTOR_ADMIN_KEY); "
            "POST /products registration does not use it"
        ),
    )
    parser.add_argument(
        "--skip-product-registration",
        action="store_true",
        help=(
            "Do not POST/DELETE /products. Assume stress-product-* rows already exist "
            "(e.g. PRODUCTS_CONFIG). Webhook latency only."
        ),
    )
    parser.add_argument(
        "--out", default="", help="Output CSV path (default: stress_results_<ts>.csv)"
    )
    parser.add_argument(
        "--min-success-rate",
        type=float,
        default=99.0,
        help="Minimum success rate %% to pass",
    )
    parser.add_argument(
        "--max-p99-ms",
        type=float,
        default=500.0,
        help="Maximum p99 latency (ms) to pass",
    )
    parser.add_argument(
        "--max-p50-ms",
        type=float,
        default=100.0,
        help="Maximum p50 latency (ms) to pass",
    )

    args = parser.parse_args()
    passed = asyncio.run(_run(args))
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
