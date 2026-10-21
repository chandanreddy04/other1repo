"""Warm worker loop: honors shutdown after the in-flight tick, never sleeps a
negative amount, and survives a failing tick.

Related: worker_loop.py.
"""

import asyncio

import pytest

from worker_loop import TICK_INTERVAL_SECONDS, compute_delay, run_loop


class TestComputeDelay:
    def test_remainder_of_interval(self):
        assert compute_delay(10.0, 60.0) == 50.0

    def test_never_negative_when_tick_overran(self):
        assert compute_delay(75.0, 60.0) == 0.0

    def test_exact_boundary_is_zero(self):
        assert compute_delay(60.0, 60.0) == 0.0

    def test_default_interval(self):
        assert compute_delay(0.0) == TICK_INTERVAL_SECONDS


@pytest.mark.asyncio
class TestRunLoop:
    async def test_stops_after_in_flight_tick(self):
        stop = asyncio.Event()
        calls = 0

        async def tick():
            nonlocal calls
            calls += 1
            stop.set()  # request shutdown from within the tick

        await run_loop(
            tick,
            stop=stop,
            interval_seconds=0,
            install_signal_handlers=False,
        )
        # The in-flight tick completed, then the loop exited.
        assert calls == 1

    async def test_tick_exception_does_not_kill_the_loop(self):
        stop = asyncio.Event()
        calls = 0

        async def tick():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("boom")
            stop.set()  # stop on the second iteration

        await run_loop(
            tick,
            stop=stop,
            interval_seconds=0,
            install_signal_handlers=False,
        )
        # First tick raised (caught), loop continued and ran a second tick.
        assert calls == 2

    async def test_already_stopped_runs_no_ticks(self):
        stop = asyncio.Event()
        stop.set()
        calls = 0

        async def tick():
            nonlocal calls
            calls += 1

        await run_loop(
            tick,
            stop=stop,
            interval_seconds=0,
            install_signal_handlers=False,
        )
        assert calls == 0
