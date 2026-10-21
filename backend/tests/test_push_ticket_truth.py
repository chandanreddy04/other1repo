"""Push delivery truth.

`_map_tickets` / `send_notification` surface which tokens Expo actually ACCEPTED
(per-ticket `status == "ok"`) — a batch HTTP 200 carrying a per-ticket error
(bad/dead token) is NOT delivery. The reconciler (notification_outbox._dispatch_
push) keys "sent" off ok_tokens on top of this; see test_outbox_reconciler.py.

Related: app/services/expo_notifications.py.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.expo_notifications import ExpoPushNotificationService, _map_tickets

TOKEN = "ExponentPushToken[abc123]"


class TestMapTickets:
    def test_ok_ticket_yields_ok_token_and_id(self):
        ok, dead, ids = _map_tickets(
            [TOKEN], {"data": [{"status": "ok", "id": "ticket-1"}]}
        )
        assert ok == [TOKEN]
        assert dead == []
        assert ids == {TOKEN: "ticket-1"}

    def test_error_ticket_is_not_ok(self):
        ok, dead, ids = _map_tickets(
            [TOKEN],
            {"data": [{"status": "error", "details": {"error": "MessageTooBig"}}]},
        )
        assert ok == []
        assert dead == []  # errored, but not DeviceNotRegistered
        assert ids == {}

    def test_device_not_registered_is_dead_not_ok(self):
        ok, dead, _ids = _map_tickets(
            [TOKEN],
            {
                "data": [
                    {"status": "error", "details": {"error": "DeviceNotRegistered"}}
                ]
            },
        )
        assert ok == []
        assert dead == [TOKEN]

    def test_shape_mismatch_returns_empties(self):
        assert _map_tickets([TOKEN], {"data": []}) == ([], [], {})
        assert _map_tickets([TOKEN], {}) == ([], [], {})

    def test_ok_ticket_without_id(self):
        ok, _dead, ids = _map_tickets([TOKEN], {"data": [{"status": "ok"}]})
        assert ok == [TOKEN]
        assert ids == {}


@pytest.mark.asyncio
class TestSendNotificationShape:
    @patch("app.services.expo_notifications.httpx.AsyncClient")
    async def test_success_surfaces_ok_tokens_and_ids(self, mock_client_cls):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": [{"status": "ok", "id": "t1"}]}
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await ExpoPushNotificationService.send_notification(
            push_tokens=[TOKEN], title="t", body="b"
        )
        assert result["ok_tokens"] == [TOKEN]
        assert result["ticket_ids"] == {TOKEN: "t1"}

    @patch("app.services.expo_notifications.httpx.AsyncClient")
    async def test_http_error_yields_empty_ok_tokens(self, mock_client_cls):
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPError("boom")
        )
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await ExpoPushNotificationService.send_notification(
            push_tokens=[TOKEN], title="t", body="b"
        )
        assert result["status"] == "error"
        assert result["ok_tokens"] == []
        assert result["ticket_ids"] == {}

    async def test_no_valid_tokens_has_empty_ok(self):
        result = await ExpoPushNotificationService.send_notification(
            push_tokens=["not-a-token"], title="t", body="b"
        )
        assert result["ok_tokens"] == []
