"""Full coverage for worker_tick.py — the processing phases + error handling.

The alert-retry pass is now the outbox reconciler (send_due_deliveries /
derive_session_promotions / poll_expo_receipts / expire_and_escalate); those are
mocked here so the tick's orchestration is what's under test.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from worker_tick import _safe, tick


@pytest.mark.asyncio
class TestSafeContextManager:
    async def test_safe_catches_exception(self):
        errors: list[str] = []
        async with _safe("test_op", errors):
            raise ValueError("boom")
        assert len(errors) == 1
        assert "test_op" in errors[0]
        assert "boom" in errors[0]

    async def test_safe_passes_through_on_success(self):
        errors: list[str] = []
        async with _safe("test_op", errors):
            pass
        assert errors == []


@pytest.mark.asyncio
class TestWorkerTick:
    @pytest.fixture(autouse=True)
    def _mock_outbox(self):
        """The reconciler phases are exercised in the outbox tests; here they're
        mocked to no-op counts so the tick orchestration is isolated."""
        with (
            patch("worker_tick.send_due_deliveries", new_callable=AsyncMock) as send,
            patch(
                "worker_tick.derive_session_promotions", new_callable=AsyncMock
            ) as derive,
            patch("worker_tick.poll_expo_receipts", new_callable=AsyncMock) as poll,
            patch("worker_tick.expire_and_escalate", new_callable=AsyncMock) as expire,
        ):
            send.return_value = {"sent": 0, "delivered": 0, "failed": 0, "refused": 0}
            derive.return_value = {"promoted": 0}
            poll.return_value = {"delivered": 0, "failed": 0, "refused": 0}
            expire.return_value = {"expired": 0, "escalated": 0}
            self.send_mock = send
            yield

    @patch("worker_tick.AsyncSessionLocal")
    @patch("worker_tick.process_pending_reminders", new_callable=AsyncMock)
    @patch("worker_tick.process_overdue", new_callable=AsyncMock)
    @patch("worker_tick.crud_session")
    async def test_tick_processes_overdue_sessions(
        self, mock_crud, mock_overdue, mock_reminders, mock_db_factory
    ):
        db = AsyncMock()
        mock_db_factory.return_value.__aenter__ = AsyncMock(return_value=db)
        mock_db_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_crud.get_overdue_sessions = AsyncMock(
            return_value=[MagicMock(id="sess-1")]
        )
        mock_crud.get_missed_sessions = AsyncMock(return_value=[])
        mock_reminders.return_value = 0

        with patch("worker_tick.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 10, 12, 30, tzinfo=UTC)
            mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
            await tick()

        mock_overdue.assert_called_once_with(db, "sess-1")

    @patch("worker_tick.AsyncSessionLocal")
    @patch("worker_tick.process_pending_reminders", new_callable=AsyncMock)
    @patch("worker_tick.crud_session")
    async def test_tick_retries_missed_sessions(
        self, mock_crud, mock_reminders, mock_db_factory
    ):
        db = AsyncMock()
        mock_db_factory.return_value.__aenter__ = AsyncMock(return_value=db)
        mock_db_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_crud.get_overdue_sessions = AsyncMock(return_value=[])
        mock_crud.get_missed_sessions = AsyncMock(
            return_value=[MagicMock(id="sess-missed")]
        )
        mock_reminders.return_value = 0

        with (
            patch("worker_tick.datetime") as mock_dt,
            patch(
                "app.services.session_tasks.process_missed_session",
                new_callable=AsyncMock,
            ) as mock_process_missed,
        ):
            mock_dt.now.return_value = datetime(2026, 5, 10, 12, 30, tzinfo=UTC)
            mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
            await tick()

        mock_process_missed.assert_called_once_with(db, "sess-missed")

    @patch("worker_tick.AsyncSessionLocal")
    @patch("worker_tick.process_pending_reminders", new_callable=AsyncMock)
    @patch("worker_tick.crud_session")
    async def test_tick_runs_outbox_reconciler(
        self, mock_crud, mock_reminders, mock_db_factory
    ):
        db = AsyncMock()
        mock_db_factory.return_value.__aenter__ = AsyncMock(return_value=db)
        mock_db_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_crud.get_overdue_sessions = AsyncMock(return_value=[])
        mock_crud.get_missed_sessions = AsyncMock(return_value=[])
        mock_reminders.return_value = 0

        with patch("worker_tick.datetime") as mock_dt:
            now = datetime(2026, 5, 10, 12, 30, tzinfo=UTC)
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
            await tick()

        self.send_mock.assert_called_once_with(db, now=now)

    @patch("worker_tick.AsyncSessionLocal")
    @patch("worker_tick.process_pending_reminders", new_callable=AsyncMock)
    @patch("worker_tick.crud_session")
    async def test_tick_sends_pending_reminders(
        self, mock_crud, mock_reminders, mock_db_factory
    ):
        db = AsyncMock()
        mock_db_factory.return_value.__aenter__ = AsyncMock(return_value=db)
        mock_db_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_crud.get_overdue_sessions = AsyncMock(return_value=[])
        mock_crud.get_missed_sessions = AsyncMock(return_value=[])
        mock_reminders.return_value = 3

        with patch("worker_tick.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 10, 12, 30, tzinfo=UTC)
            mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
            await tick()

        mock_reminders.assert_called_once_with(db)

    @patch("worker_tick.AsyncSessionLocal")
    @patch("worker_tick.cleanup_expired_data", new_callable=AsyncMock)
    @patch("worker_tick.process_pending_reminders", new_callable=AsyncMock)
    @patch("worker_tick.crud_session")
    async def test_tick_hourly_cleanup(
        self, mock_crud, mock_reminders, mock_cleanup, mock_db_factory
    ):
        db = AsyncMock()
        mock_db_factory.return_value.__aenter__ = AsyncMock(return_value=db)
        mock_db_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_crud.get_overdue_sessions = AsyncMock(return_value=[])
        mock_crud.get_missed_sessions = AsyncMock(return_value=[])
        mock_reminders.return_value = 0

        with patch("worker_tick.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
            mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
            await tick()

        mock_cleanup.assert_called_once_with(db)

    @patch("worker_tick.AsyncSessionLocal")
    @patch("worker_tick.cleanup_expired_data", new_callable=AsyncMock)
    @patch("worker_tick.process_pending_reminders", new_callable=AsyncMock)
    @patch("worker_tick.crud_session")
    async def test_tick_no_cleanup_on_non_zero_minute(
        self, mock_crud, mock_reminders, mock_cleanup, mock_db_factory
    ):
        db = AsyncMock()
        mock_db_factory.return_value.__aenter__ = AsyncMock(return_value=db)
        mock_db_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_crud.get_overdue_sessions = AsyncMock(return_value=[])
        mock_crud.get_missed_sessions = AsyncMock(return_value=[])
        mock_reminders.return_value = 0

        with patch("worker_tick.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 10, 12, 15, tzinfo=UTC)
            mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
            await tick()

        mock_cleanup.assert_not_called()

    @patch("worker_tick.AsyncSessionLocal")
    @patch("worker_tick.process_pending_reminders", new_callable=AsyncMock)
    @patch("worker_tick.crud_session")
    async def test_tick_error_in_one_step_does_not_block_others(
        self, mock_crud, mock_reminders, mock_db_factory
    ):
        db = AsyncMock()
        mock_db_factory.return_value.__aenter__ = AsyncMock(return_value=db)
        mock_db_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_crud.get_overdue_sessions = AsyncMock(
            side_effect=RuntimeError("DB down")
        )
        mock_crud.get_missed_sessions = AsyncMock(return_value=[])
        mock_reminders.return_value = 0

        with patch("worker_tick.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 10, 12, 30, tzinfo=UTC)
            mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
            await tick()

        mock_crud.get_missed_sessions.assert_called_once()
        mock_reminders.assert_called_once()
