"""to_viewable_url: stored photo URLs are presigned for client viewing.

Photos are stored as raw private-S3 URLs the client can't load; the response
schemas run them through to_viewable_url so every endpoint returns a viewable
URL. Must be fail-safe — a signing/config problem returns the original value,
never blanks a photo or 500s a response.

Related: services/photo_urls.py, schemas/{session,user}.py.
"""

from unittest.mock import MagicMock, patch

from app.services import photo_urls

_S3 = "https://bkt.s3.us-west-2.amazonaws.com/outfit-photos/u1/2026.jpg"
_KEY = "outfit-photos/u1/2026.jpg"


def test_none_and_empty_pass_through():
    assert photo_urls.to_viewable_url(None) is None
    assert photo_urls.to_viewable_url("") == ""


def test_local_dev_path_passes_through_unsigned():
    # /uploads/... is served by the dev static mount — never presign it.
    assert photo_urls.to_viewable_url("/uploads/x.jpg") == "/uploads/x.jpg"


def test_s3_url_is_presigned_with_the_object_key():
    svc = MagicMock()
    svc.generate_presigned_url_sync.return_value = "https://signed.example/x?sig=1"
    with patch.object(photo_urls, "_get_service", return_value=svc):
        out = photo_urls.to_viewable_url(_S3)
    assert out == "https://signed.example/x?sig=1"
    # Key is the full path after the host (not just the filename).
    svc.generate_presigned_url_sync.assert_called_once_with(_KEY)


def test_failsafe_when_storage_unavailable():
    with patch.object(photo_urls, "_get_service", return_value=None):
        assert photo_urls.to_viewable_url(_S3) == _S3


def test_failsafe_when_signer_returns_none():
    svc = MagicMock()
    svc.generate_presigned_url_sync.return_value = None
    with patch.object(photo_urls, "_get_service", return_value=svc):
        assert photo_urls.to_viewable_url(_S3) == _S3


def test_failsafe_when_signer_raises():
    svc = MagicMock()
    svc.generate_presigned_url_sync.side_effect = RuntimeError("bad signer")
    with patch.object(photo_urls, "_get_service", return_value=svc):
        assert photo_urls.to_viewable_url(_S3) == _S3


def test_session_schema_presigns_outfit_photo_on_serialize():
    from datetime import UTC, datetime
    from uuid import uuid4

    from app.models.session import SessionStatus, SessionType
    from app.schemas.session import Session

    now = datetime.now(UTC)
    svc = MagicMock()
    svc.generate_presigned_url_sync.return_value = "https://signed.example/p"
    with patch.object(photo_urls, "_get_service", return_value=svc):
        session = Session(
            id=uuid4(),
            user_id=uuid4(),
            session_type=SessionType.CHECKIN,
            expected_return_time=now,
            actual_return_time=None,
            destination=None,
            outfit_photo_url=_S3,
            outfit_photo_uploaded_at=now,
            location_sharing_enabled=False,
            last_known_latitude=None,
            last_known_longitude=None,
            last_location_update=None,
            last_battery_level=None,
            last_battery_state=None,
            status=SessionStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
    assert session.outfit_photo_url == "https://signed.example/p"
