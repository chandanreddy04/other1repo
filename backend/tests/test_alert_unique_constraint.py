"""Tests for the alerts (session_id, sent_to_user_id, alert_type) unique constraint.

Defense-in-depth against duplicate dispatch when overlapping worker ticks
process the same MISSED session — see worker_tick.run_tick_with_lock and the
constraint on app.models.alert.Alert.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import Alert, AlertType
from app.models.session import Session, SessionStatus, SessionType
from tests.helpers import create_test_user


async def _make_missed_session(db: AsyncSession, owner: object) -> Session:
    session = Session(
        user_id=owner.id,
        session_type=SessionType.CHECKIN.value,
        expected_return_time=datetime.now(UTC) + timedelta(hours=1),
        status=SessionStatus.MISSED.value,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


@pytest.mark.asyncio
async def test_duplicate_alert_same_type_rejected(db_session: AsyncSession) -> None:
    """Two alerts of the same type to the same recipient for one session conflict."""
    owner = await create_test_user(
        db_session, phone_number="+14155571000", full_name="Owner"
    )
    recipient = await create_test_user(
        db_session, phone_number="+14155571001", full_name="Recipient"
    )
    session = await _make_missed_session(db_session, owner)

    db_session.add(
        Alert(
            session_id=session.id,
            sent_to_user_id=recipient.id,
            alert_type=AlertType.MISSED_SESSION,
        )
    )
    await db_session.commit()

    db_session.add(
        Alert(
            session_id=session.id,
            sent_to_user_id=recipient.id,
            alert_type=AlertType.MISSED_SESSION,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_same_recipient_different_type_allowed(db_session: AsyncSession) -> None:
    """A REMINDER follow-up must coexist with the initial MISSED_SESSION alert."""
    owner = await create_test_user(
        db_session, phone_number="+14155571002", full_name="Owner2"
    )
    recipient = await create_test_user(
        db_session, phone_number="+14155571003", full_name="Recipient2"
    )
    session = await _make_missed_session(db_session, owner)

    db_session.add(
        Alert(
            session_id=session.id,
            sent_to_user_id=recipient.id,
            alert_type=AlertType.MISSED_SESSION,
        )
    )
    await db_session.commit()

    db_session.add(
        Alert(
            session_id=session.id,
            sent_to_user_id=recipient.id,
            alert_type=AlertType.REMINDER,
        )
    )
    await db_session.commit()  # must not raise — different alert_type
