"""Background loops must survive errors; failed reads must back off."""

from __future__ import annotations

import asyncio

import pytest


async def test_run_forever_restarts_a_crashed_loop(r, caplog):
    calls = []

    async def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("boom")

    await asyncio.wait_for(r._run_forever("flaky", flaky, first_delay=0.01), 2)
    assert len(calls) == 3
    assert sum("flaky crashed" in m for m in caplog.messages) == 2


async def test_run_forever_ends_on_a_normal_return(r):
    calls = []

    async def not_configured():
        calls.append(1)

    await asyncio.wait_for(r._run_forever("x", not_configured, first_delay=0.01), 1)
    assert calls == [1]


async def test_spawned_task_is_referenced_and_its_crash_logged(r, caplog):
    async def bad():
        raise ValueError("nope")

    task = r._spawn(bad(), "bad-task")
    assert task in r._tasks
    await asyncio.gather(task, return_exceptions=True)
    await asyncio.sleep(0)
    assert task not in r._tasks
    assert any("bad-task failed" in m for m in caplog.messages)


async def test_motion_watcher_survives_a_scan_error(r, monkeypatch):
    """A BlueZ error while scanning for the tracker used to kill the watcher
    (and with it the armed alarm's motion sensor) until the add-on restarted."""
    calls = []

    async def find_comodule():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("org.bluez.Error.InProgress")
        return None

    real_sleep = asyncio.sleep

    async def fast_sleep(_delay, *args, **kwargs):
        await real_sleep(0)

    monkeypatch.setattr(r, "_want_tracker", lambda: True)
    monkeypatch.setattr(r, "find_comodule", find_comodule)
    monkeypatch.setattr(r.asyncio, "sleep", fast_sleep)
    task = asyncio.get_running_loop().create_task(r.motion_watcher())
    for _ in range(200):
        if len(calls) >= 3:
            break
        await real_sleep(0.001)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert len(calls) >= 3
    assert r._last.get("tracker_connected") is False


@pytest.mark.parametrize(("fails", "expected"), [(0, 3.0), (1, 6.0), (2, 12.0), (3, 24.0),
                                                  (6, 120.0), (50, 120.0)])
def test_read_retry_backoff(r, monkeypatch, fails, expected):
    monkeypatch.setattr(r, "SCAN_GAP", 3.0)
    monkeypatch.setattr(r, "COOLDOWN", 120.0)
    assert r._read_retry_delay(fails) == expected


def test_error_text_for_bare_timeouts(r):
    assert r._err_text(TimeoutError()).startswith("TimeoutError: timed out")
    assert r._err_text(asyncio.TimeoutError()).startswith("TimeoutError: timed out")
    assert r._err_text(RuntimeError("x")) == "RuntimeError: x"
    assert r._err_text(RuntimeError()) == "RuntimeError: no details"
