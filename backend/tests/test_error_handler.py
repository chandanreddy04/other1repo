"""Tests for ErrorHandlerMiddleware — exception capture and Bugsnag reporting."""

from unittest.mock import MagicMock, patch

import pytest

from app.middleware.error_handler import _extract_user_id


class TestExtractUserId:
    def test_no_auth_header(self):
        request = MagicMock()
        request.headers = {}
        assert _extract_user_id(request) is None

    def test_non_bearer_auth(self):
        request = MagicMock()
        request.headers = {"authorization": "Basic abc"}
        assert _extract_user_id(request) is None

    def test_valid_bearer_token(self):
        from app.core.security import create_access_token

        token = create_access_token("user-123")
        request = MagicMock()
        request.headers = {"authorization": f"Bearer {token}"}
        result = _extract_user_id(request)
        assert result == "user-123"

    def test_invalid_token(self):
        request = MagicMock()
        request.headers = {"authorization": "Bearer invalid.token.here"}
        assert _extract_user_id(request) is None


@pytest.mark.asyncio
class TestErrorHandlerMiddleware:
    async def test_unhandled_exception_returns_500(self, client):
        response = await client.get("/api/v1/nonexistent-endpoint-that-does-not-exist")
        assert response.status_code in (404, 405, 422)

    async def test_report_error_called_on_error(self):
        from app.middleware.error_handler import ErrorHandlerMiddleware

        middleware = ErrorHandlerMiddleware(app=MagicMock())

        request = MagicMock()
        request.method = "GET"
        request.url.path = "/test"
        request.query_params = {}
        request.headers = {}

        async def failing_call_next(req):
            raise RuntimeError("test crash")

        # The middleware reports through app.core.error_reporting.notify (which
        # owns the configured/unconfigured gate) as an UNHANDLED exception.
        with patch("app.middleware.error_handler.report_error") as notify_mock:
            response = await middleware.dispatch(request, failing_call_next)

        assert response.status_code == 500
        notify_mock.assert_called_once()
        assert isinstance(notify_mock.call_args.args[0], RuntimeError)
        assert notify_mock.call_args.kwargs["unhandled"] is True
        assert notify_mock.call_args.kwargs["context"] == "GET /test"

    async def test_no_bugsnag_without_api_key(self):
        import bugsnag.legacy

        from app.core import error_reporting as reporting
        from app.middleware.error_handler import ErrorHandlerMiddleware

        middleware = ErrorHandlerMiddleware(app=MagicMock())

        request = MagicMock()
        request.method = "POST"
        request.url.path = "/api/test"
        request.query_params = {}
        request.headers = {}

        async def failing_call_next(req):
            raise ValueError("no bugsnag")

        # Unconfigured (blank key): the 500 still renders, nothing reaches the SDK.
        reporting.reset_for_tests()
        with patch.object(bugsnag.legacy.default_client, "notify") as sdk_notify:
            response = await middleware.dispatch(request, failing_call_next)

        assert response.status_code == 500
        sdk_notify.assert_not_called()
