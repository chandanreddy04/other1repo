"""Worker-tick integration for the hard-purge step.

Verifies that the hourly branch in worker_tick.tick() actually invokes
process_pending_purges, and that the non-hourly branches don't.

Related: worker_tick.py, app/services/account_deletion.py
"""
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from worker_tick import tick


def _stub_db():
    db = AsyncMock()
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=db)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    return db, factory


@pytest.mark.asyncio
class TestPurgeOnHourBoundary:
    @pytest.fixture(autouse=True)
    def _mock_outbox(self):
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
            yield

    @patch("worker_tick.AsyncSessionLocal")
    @patch("worker_tick.cleanup_expired_data", new_callable=AsyncMock)
    @patch("worker_tick.process_pending_reminders", new_callable=AsyncMock)
    @patch("worker_tick.crud_session")
    @patch(
        "app.services.account_deletion.process_pending_purges",
        new_callable=AsyncMock,
    )
    async def test_runs_at_minute_zero(
        self,
        mock_purges,
        mock_crud,
        mock_reminders,
        mock_cleanup,
        mock_db_factory,
    ):
        db, factory = _stub_db()
        mock_db_factory.return_value = factory.return_value
        mock_crud.get_overdue_sessions = AsyncMock(return_value=[])
        mock_crud.get_missed_sessions = AsyncMock(return_value=[])
        mock_reminders.return_value = 0
        mock_purges.return_value = 2

        with patch("worker_tick.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
            mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
            await tick()

        mock_purges.assert_called_once_with(db)

    @patch("worker_tick.AsyncSessionLocal")
    @patch("worker_tick.cleanup_expired_data", new_callable=AsyncMock)
    @patch("worker_tick.process_pending_reminders", new_callable=AsyncMock)
    @patch("worker_tick.crud_session")
    @patch(
        "app.services.account_deletion.process_pending_purges",
        new_callable=AsyncMock,
    )
    async def test_skipped_on_non_hour_minute(
        self,
        mock_purges,
        mock_crud,
        mock_reminders,
        mock_cleanup,
        mock_db_factory,
    ):
        _db, factory = _stub_db()
        mock_db_factory.return_value = factory.return_value
        mock_crud.get_overdue_sessions = AsyncMock(return_value=[])
        mock_crud.get_missed_sessions = AsyncMock(return_value=[])
        mock_reminders.return_value = 0

        with patch("worker_tick.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 10, 12, 15, tzinfo=UTC)
            mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
            await tick()

        mock_purges.assert_not_called()
