"""Warm worker entrypoint — runs the tick in a long-lived loop.

The scheduled variant (`worker_tick.py`, one tick per ECS RunTask) pays a
~20-60s Fargate cold start on every minute-ly invocation, so a notification due
at T isn't actually processed until well after T. This entrypoint runs
`run_tick_with_lock` in a WARM process on a ~60s cadence, so due work goes out
within seconds of the minute boundary.

Safety: the Postgres session-level advisory lock inside `run_tick_with_lock`
still serializes ticks, so this is safe alongside any other tick — a rolling
deploy's old+new task, or a leftover EventBridge schedule during the cutover.
SIGTERM/SIGINT finish the in-flight tick, then exit cleanly; an uncaught error
exits non-zero so ECS restarts the task. `worker_tick.py` stays for manual /
one-off runs and as the rollback path.

Deployed as an always-on ECS service — see infra/aws/primary/ecs_worker.tf.
Related: worker_tick.py.
"""

import asyncio
import contextlib
import logging
import signal
import sys
from collections.abc import Awaitable, Callable

from app.core.logging import setup_logging
from worker_tick import run_tick_with_lock

setup_logging()
logger = logging.getLogger("worker_loop")

TICK_INTERVAL_SECONDS = 60.0


def compute_delay(
    elapsed_seconds: float, interval_seconds: float = TICK_INTERVAL_SECONDS
) -> float:
    """Seconds to sleep before the next tick — the remainder of the interval,
    never negative (a tick that ran longer than the interval starts the next
    immediately)."""
    return max(0.0, interval_seconds - elapsed_seconds)


async def run_loop(
    run_tick: Callable[[], Awaitable[None]] = run_tick_with_lock,
    *,
    stop: asyncio.Event | None = None,
    interval_seconds: float = TICK_INTERVAL_SECONDS,
    install_signal_handlers: bool = True,
) -> None:
    """Run `run_tick` every `interval_seconds` until `stop` is set. A tick that
    raises is logged and the loop continues (a warm process must survive a bad
    tick). Shutdown finishes the in-flight tick, then exits."""
    stop = stop or asyncio.Event()
    loop = asyncio.get_running_loop()

    if install_signal_handlers:
        for sig in (signal.SIGTERM, signal.SIGINT):
            # benign: signal handlers aren't available off the main thread (tests).
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(sig, stop.set)

    logger.info("worker_loop started (interval=%ss)", interval_seconds)
    while not stop.is_set():
        started = loop.time()
        try:
            await run_tick()
        except Exception:
            logger.exception("worker_loop tick failed — continuing")
        delay = compute_delay(loop.time() - started, interval_seconds)
        # benign: a timeout just means the sleep completed; wake early on shutdown.
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=delay)

    logger.info("worker_loop exiting cleanly")


if __name__ == "__main__":
    # Same boot contract as the web: refuse to run blind (no error reporting)
    # or mute (no SMS backend) in staging/production.
    from app.core.config import settings
    from app.core.startup_checks import run_production_startup_checks

    run_production_startup_checks(settings)
    try:
        asyncio.run(run_loop())
    except Exception:
        logger.exception("worker_loop crashed")
        sys.exit(1)
