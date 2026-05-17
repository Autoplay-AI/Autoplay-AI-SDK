"""Shared pytest fixtures for the autoplay SDK test suite."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

# Make autoplay_sdk importable without installing it.
_SDK_DIR = Path(__file__).parent.parent
if str(_SDK_DIR) not in sys.path:
    sys.path.insert(0, str(_SDK_DIR))

_DEBUG_LOG_PATH = Path(
    "/Users/marieliesse/Desktop/CODE/real-time-chatbot-poc/.cursor/debug-a1da9d.log"
)


@pytest.fixture(autouse=True)
def _clear_autoplay_unkey_token_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent developer ``AUTOPLAY_APP_UNKEY_TOKEN`` from affecting unrelated tests."""
    monkeypatch.delenv("AUTOPLAY_APP_UNKEY_TOKEN", raising=False)


def _debug_log(
    *, run_id: str, hypothesis_id: str, location: str, message: str, data: dict
) -> None:
    # region agent log
    payload = {
        "sessionId": "a1da9d",
        "runId": run_id,
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data,
        "timestamp": int(time.time() * 1000),
    }
    try:
        with _DEBUG_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, sort_keys=True) + "\n")
    except OSError:
        pass
    # endregion


def pytest_runtest_logstart(nodeid: str, location: tuple[str, int | None, str]) -> None:
    _debug_log(
        run_id="pre-fix",
        hypothesis_id="H1",
        location="tests/conftest.py:pytest_runtest_logstart",
        message="test_start",
        data={"nodeid": nodeid, "file": location[0], "line": location[1]},
    )


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    hypothesis = "H2" if report.when == "call" else "H3"
    _debug_log(
        run_id="pre-fix",
        hypothesis_id=hypothesis,
        location="tests/conftest.py:pytest_runtest_logreport",
        message="test_phase_complete",
        data={
            "nodeid": report.nodeid,
            "phase": report.when,
            "outcome": report.outcome,
            "duration_s": round(report.duration, 6),
        },
    )


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    _debug_log(
        run_id="pre-fix",
        hypothesis_id="H4",
        location="tests/conftest.py:pytest_sessionfinish",
        message="session_finish",
        data={"exitstatus": exitstatus, "tests_collected": session.testscollected},
    )
