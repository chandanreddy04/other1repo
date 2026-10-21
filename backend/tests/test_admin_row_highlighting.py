"""Tests for admin row_class highlighting callbacks."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from app.web.admin_registry import _alert_row_class, _session_row_class


class TestAlertRowClass:
    # Delivery retries now live in notification_deliveries; a FAILED alert
    # (its deliveries exhausted) is flagged purely by status.
    def test_failed(self):
        alert = MagicMock()
        alert.status = "failed"
        assert _alert_row_class(alert) == "row-warning"

    def test_delivered(self):
        alert = MagicMock()
        alert.status = "delivered"
        assert _alert_row_class(alert) == ""

    def test_sent(self):
        alert = MagicMock()
        alert.status = "sent"
        assert _alert_row_class(alert) == ""


class TestSessionRowClass:
    def test_stuck_missed(self):
        session = MagicMock()
        session.status = "missed"
        session.updated_at = datetime.now(UTC) - timedelta(minutes=15)
        assert _session_row_class(session) == "row-warning"

    def test_recent_missed(self):
        session = MagicMock()
        session.status = "missed"
        session.updated_at = datetime.now(UTC) - timedelta(minutes=5)
        assert _session_row_class(session) == ""

    def test_not_missed(self):
        session = MagicMock()
        session.status = "active"
        session.updated_at = datetime.now(UTC) - timedelta(minutes=15)
        assert _session_row_class(session) == ""

    def test_missed_no_updated_at(self):
        session = MagicMock()
        session.status = "missed"
        session.updated_at = None
        assert _session_row_class(session) == ""
