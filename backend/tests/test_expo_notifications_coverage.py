"""Full coverage for expo_notifications.py (mock httpx)."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.expo_notifications import ExpoPushNotificationService


@pytest.mark.asyncio
class TestExpoPushNotificationService:
    @patch("app.services.expo_notifications.httpx.AsyncClient")
    async def test_send_notification_success(self, mock_client_cls):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": [{"status": "ok"}]}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await ExpoPushNotificationService.send_notification(
            push_tokens=["ExponentPushToken[abc123]"],
            title="Test",
            body="Hello",
            data={"key": "val"},
        )
        assert result["status"] == "success"
        mock_client.post.assert_called_once()

    async def test_send_notification_empty_tokens(self):
        result = await ExpoPushNotificationService.send_notification(
            push_tokens=[],
            title="Test",
            body="Hello",
        )
        assert result["status"] == "error"

    async def test_send_notification_invalid_tokens_filtered(self):
        result = await ExpoPushNotificationService.send_notification(
            push_tokens=["invalid-token", "", None],
            title="Test",
            body="Hello",
        )
        assert result["status"] == "error"
        assert "No valid tokens" in result["message"]

    @patch("app.services.expo_notifications.httpx.AsyncClient")
    async def test_send_notification_http_error(self, mock_client_cls):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(
            side_effect=httpx.HTTPError("Connection failed")
        )
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await ExpoPushNotificationService.send_notification(
            push_tokens=["ExponentPushToken[abc]"],
            title="Test",
            body="Hello",
        )
        assert result["status"] == "error"

    @patch("app.services.expo_notifications.httpx.AsyncClient")
    async def test_send_notification_unexpected_error(self, mock_client_cls):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=RuntimeError("unexpected"))
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await ExpoPushNotificationService.send_notification(
            push_tokens=["ExponentPushToken[abc]"],
            title="Test",
            body="Hello",
        )
        assert result["status"] == "error"

    @patch("app.services.expo_notifications.httpx.AsyncClient")
    async def test_send_notification_with_badge(self, mock_client_cls):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": [{"status": "ok"}]}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await ExpoPushNotificationService.send_notification(
            push_tokens=["ExponentPushToken[abc]"],
            title="Test",
            body="Hello",
            badge=5,
        )
        assert result["status"] == "success"
        call_args = mock_client.post.call_args
        messages = call_args.kwargs.get("json") or call_args[1].get("json")
        assert messages[0]["badge"] == 5

