"""Tests for the advisory-lock gate in worker_tick.run_tick_with_lock.

Verifies the control flow only (acquire -> run -> unlock; skip when held;
always unlock) — the auto-release-on-disconnect behaviour is Postgres's, not
ours, so it isn't re-tested here.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import worker_tick


def _mock_lock_connection(acquired: bool) -> tuple[MagicMock, MagicMock]:
    """Async-context-manager mock whose pg_try_advisory_lock returns `acquired`.

    scalar() is awaited twice in the happy path: once to acquire, once to unlock.
    """
    lock_conn = MagicMock()
    lock_conn.scalar = AsyncMock(side_effect=[acquired, None])
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=lock_conn)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm, lock_conn


@pytest.mark.asyncio
async def test_runs_tick_when_lock_acquired() -> None:
    cm, lock_conn = _mock_lock_connection(acquired=True)
    with (
        patch.object(worker_tick, "async_engine") as mock_engine,
        patch.object(worker_tick, "tick", new=AsyncMock()) as mock_tick,
    ):
        mock_engine.connect.return_value = cm
        await worker_tick.run_tick_with_lock()

    mock_tick.assert_awaited_once()
    # acquire + explicit unlock
    assert lock_conn.scalar.await_count == 2


@pytest.mark.asyncio
async def test_skips_tick_when_lock_held() -> None:
    cm, lock_conn = _mock_lock_connection(acquired=False)
    with (
        patch.object(worker_tick, "async_engine") as mock_engine,
        patch.object(worker_tick, "tick", new=AsyncMock()) as mock_tick,
    ):
        mock_engine.connect.return_value = cm
        await worker_tick.run_tick_with_lock()

    mock_tick.assert_not_awaited()
    # only the acquire attempt — nothing to unlock since we never held it
    assert lock_conn.scalar.await_count == 1


@pytest.mark.asyncio
async def test_unlocks_even_if_tick_raises() -> None:
    cm, lock_conn = _mock_lock_connection(acquired=True)
    with (
        patch.object(worker_tick, "async_engine") as mock_engine,
        patch.object(
            worker_tick, "tick", new=AsyncMock(side_effect=RuntimeError("boom"))
        ),
    ):
        mock_engine.connect.return_value = cm
        with pytest.raises(RuntimeError):
            await worker_tick.run_tick_with_lock()

    # acquire + unlock-in-finally, despite the tick raising
    assert lock_conn.scalar.await_count == 2
