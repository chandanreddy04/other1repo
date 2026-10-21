"""ExpoPushNotificationService.get_receipts — parses delivery receipts into
ok / dead / error outcomes (the real APNs/FCM handoff result the reconciler
uses to confirm or retry a sent push).

Related: app/services/expo_notifications.py.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.expo_notifications import ExpoPushNotificationService


@pytest.mark.asyncio
class TestGetReceipts:
    async def test_empty_ids_short_circuits(self):
        result = await ExpoPushNotificationService.get_receipts([])
        assert result == {"status": "success", "receipts": {}}

    @patch("app.services.expo_notifications.httpx.AsyncClient")
    async def test_parses_ok_dead_and_error(self, mock_client_cls):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": {
                "t-ok": {"status": "ok"},
                "t-dead": {
                    "status": "error",
                    "details": {"error": "DeviceNotRegistered"},
                },
                "t-err": {
                    "status": "error",
                    "message": "boom",
                    "details": {"error": "MessageTooBig"},
                },
            }
        }
        mock_response.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await ExpoPushNotificationService.get_receipts(
            ["t-ok", "t-dead", "t-err"]
        )
        receipts = result["receipts"]
        assert receipts["t-ok"] == {"ok": True, "dead": False, "error": None}
        assert receipts["t-dead"]["dead"] is True
        assert receipts["t-dead"]["ok"] is False
        assert receipts["t-err"]["ok"] is False
        assert receipts["t-err"]["dead"] is False

    @patch("app.services.expo_notifications.httpx.AsyncClient")
    async def test_http_error_returns_error_status(self, mock_client_cls):
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPError("down")
        )
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await ExpoPushNotificationService.get_receipts(["t"])
        assert result == {"status": "error", "receipts": {}}
