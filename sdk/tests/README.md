# Tests — autoplay-sdk / event-connector

This directory contains both unit tests (run via pytest) and the standalone
stress test script.

---

## Unit tests

Run from the `.` directory:

```bash
cd .
source ../../.venv/bin/activate
pytest tests/ -v
```

---

## Stress test — `stress_test_sdk.py`

Fires concurrent POST requests to the event-connector webhook across multiple
synthetic products, measures throughput and latency, and exports every request
to a CSV.

### Prerequisites

The connector must be running before the script starts. It performs a `/health`
pre-flight check and exits immediately with a clear error if the connector is
unreachable.

### Starting the connector (macOS)

On macOS the default file descriptor limit is 256, which is exhausted by
~100 concurrent connections. Raise it before starting uvicorn, or you will
see connection failures above `--concurrency 30`:

```bash
cd 
source .venv/bin/activate
ulimit -n 65536          # raise fd limit — macOS only, not needed on Linux
uvicorn event_connector.api.app:app --host 0.0.0.0 --port 8080 --workers 1
```

> On Linux (CI / production) `ulimit -n` defaults to 65536, so this step is
> not required there.

### Running the stress test

Open a second terminal (same directory, same venv):

```bash
# Smoke — 500 requests, completes in seconds
python3 src/customer_sdk/tests/stress_test_sdk.py \
  --sessions 10 --events 10 --concurrency 20 \
  --admin-key YOUR_ADMIN_KEY

# Medium — 50 000 requests, stable at concurrency 30 on macOS
python3 src/customer_sdk/tests/stress_test_sdk.py \
  --sessions 100 --events 100 --concurrency 30 \
  --admin-key YOUR_ADMIN_KEY

# Medium at higher concurrency — requires ulimit fix above on macOS
python3 src/customer_sdk/tests/stress_test_sdk.py \
  --sessions 100 --events 100 --concurrency 100 \
  --admin-key YOUR_ADMIN_KEY

# ~30 min run — 1.25M requests / 12.5M events (requires ulimit fix on macOS)
# Good balance between coverage and run time before going full scale.
python3 src/customer_sdk/tests/stress_test_sdk.py \
  --sessions 500 --events 500 --concurrency 100 \
  --admin-key YOUR_ADMIN_KEY

# Full target — 5 000 000 requests / 50M events (~2 hours, requires ulimit fix on macOS)
# CSV output will be ~400–500 MB. Safe to Ctrl+C mid-run; results written as they complete.
python3 src/customer_sdk/tests/stress_test_sdk.py \
  --sessions 1000 --events 1000 --concurrency 100 \
  --admin-key YOUR_ADMIN_KEY
```

### CLI flags

| Flag | Default | Description |
|------|---------|-------------|
| `--base-url` | `http://localhost:8080` | Connector base URL |
| `--products` | `50` | Synthetic products (`stress-product-001` … `stress-product-050`) |
| `--sessions` | `1000` | Sessions per product |
| `--events` | `1000` | Events per session |
| `--batch-size` | `10` | PostHog events per HTTP request |
| `--concurrency` | `200` | Max in-flight requests |
| `--admin-key` | `""` | `X-Admin-Key` for `DELETE /products/{id}` teardown only (not used for `POST /products`) |
| `--secret` | `""` | `X-PostHog-Secret` header (leave empty if product has no secret) |
| `--out` | `stress_results_<ts>.csv` | Output CSV path |
| `--min-success-rate` | `99.0` | Minimum success rate % to pass |
| `--max-p99-ms` | `500.0` | Maximum p99 latency (ms) to pass |
| `--max-p50-ms` | `100.0` | Maximum p50 latency (ms) to pass |

### Product setup and `--admin-key`

The script calls `POST /products` (no admin header) for each synthetic product
ID before firing requests, using `integration_type: event_stream` + `mode: sse`.
After the run, it calls `DELETE /products/{id}` to clean up **only** if
`--admin-key` is set to the connector’s `CONNECTOR_ADMIN_KEY` (list/delete
still require the admin key). If `--admin-key` is omitted, registration still
runs, but synthetic products are left registered unless you clean them up
manually.

### Output

Results are streamed to a CSV as each request completes — no in-memory
buffering — so large runs stay within ~200 MB RAM.

CSV columns: `timestamp_utc, product_id, session_id, chunk_idx, events_in_batch,
latency_ms, status_code, success, error`

`stress_results*.csv` files are gitignored and will not be committed.

### Threshold checks

The script exits with code `1` if any threshold fails, making it suitable as a
CI gate. Thresholds are printed at the end:

```
========================================================================
THRESHOLD CHECK
========================================================================
  [PASS]  Success rate: 100.00% >= 99.0%
  [PASS]  p99 latency: 362.4ms <= 500.0ms
  [PASS]  p50 latency: 30.4ms <= 100.0ms
========================================================================
  ALL CHECKS PASSED
========================================================================
```

### Known macOS concurrency limit

| Concurrency | macOS (default ulimit) | macOS (ulimit 65536) | Linux / CI |
|-------------|----------------------|----------------------|------------|
| ≤ 30 | Stable ✓ | Stable ✓ | Stable ✓ |
| 31–99 | May crash | Stable ✓ | Stable ✓ |
| ≥ 100 | Crashes (fd exhaustion) | Stable ✓ | Stable ✓ |

The connector itself is healthy — this is a macOS OS-level constraint, not an
architectural issue.

---

## GitHub Actions

Two workflows are configured:

- **`.github/workflows/stress-test-smoke.yml`** — runs automatically on every
  PR. Fixed thresholds: 100% success, p99 < 100ms, p50 < 20ms (low load,
  concurrency 20).
- **`.github/workflows/stress-test-manual.yml`** — triggered manually from the
  GitHub Actions UI with configurable inputs. Uploads the CSV as a downloadable
  artifact.

Both workflows require a `CONNECTOR_ADMIN_KEY` repository secret (value:
`YOUR_ADMIN_KEY`).
