"""The public alert page (/alerts/{id}) presigns the outfit photo.

Photos live in a private S3 bucket, so the stored URL is not viewable on its
own — the page must render it through `photo_urls.to_viewable_url` (the same
presigner the API schemas and admin use). test_alert_page_sections.py checks
the photo section renders; this pins that the rendered `src` is the presigned
URL and the raw stored URL never reaches the page.

Related: app/web/routes_web.py::_alert_view_context,
app/services/photo_urls.py, app/web/templates/alert_view.html.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import Alert, AlertStatus, AlertType
from app.models.session import Session, SessionStatus
from tests.helpers import create_test_user

_RAW_URL = "https://made-it-home-photos.s3.amazonaws.com/outfits/raw-key.jpg"
_SIGNED_URL = "https://signed.example.com/outfits/raw-key.jpg?X-Amz-Signature=abc"


async def _alert_with_photo(db: AsyncSession, outfit_photo_url: str | None) -> Alert:
    owner = await create_test_user(
        db, phone_number="+14155596001", full_name="Ana Owner"
    )
    contact = await create_test_user(
        db, phone_number="+14155596002", full_name="Cody Contact"
    )
    session = Session(
        user_id=owner.id,
        expected_return_time=datetime.now(UTC) - timedelta(minutes=30),
        status=SessionStatus.MISSED.value,
        outfit_photo_url=outfit_photo_url,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    alert = Alert(
        session_id=session.id,
        sent_to_phone_id=contact.phone_number_id,
        alert_type=AlertType.MISSED_SESSION,
        status=AlertStatus.SENT,
        message="Ana missed their check-in.",
        sent_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    db.add(alert)
    await db.commit()
    await db.refresh(alert)
    return alert


def _fake_presign(stored_url: str | None) -> str | None:
    return _SIGNED_URL if stored_url == _RAW_URL else stored_url


@pytest.mark.asyncio
class TestAlertPagePhotoPresigned:
    async def test_photo_src_is_presigned_not_raw(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        alert = await _alert_with_photo(db_session, _RAW_URL)
        with patch(
            "app.services.photo_urls.to_viewable_url", side_effect=_fake_presign
        ) as presign:
            resp = await client.get(f"/alerts/{alert.id}")

        assert resp.status_code == 200
        presign.assert_any_call(_RAW_URL)
        # Jinja autoescapes & in the query string; this URL has none.
        assert f'src="{_SIGNED_URL}"' in resp.text
        assert _RAW_URL not in resp.text

    async def test_no_photo_renders_no_img(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        alert = await _alert_with_photo(db_session, None)
        with patch(
            "app.services.photo_urls.to_viewable_url", side_effect=_fake_presign
        ):
            resp = await client.get(f"/alerts/{alert.id}")

        assert resp.status_code == 200
        assert _SIGNED_URL not in resp.text
        assert "Outfit photo" not in resp.text
