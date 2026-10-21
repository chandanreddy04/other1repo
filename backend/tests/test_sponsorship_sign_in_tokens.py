"""Tests for the one-time sponsorship sign-in token (replaces the JWT-based
sponsorship magic link, removed 2026-09-27).

Related: app/models/sponsorship_sign_in_token.py,
app/crud/sponsorship_sign_in_token.py,
app/services/session_tasks.py::cleanup_expired_data (hourly purge).
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.sponsorship_sign_in_token import crud_sponsorship_sign_in_token
from app.models.sponsorship_sign_in_token import (
    TOKEN_LENGTH,
    SponsorshipSignInToken,
    generate_token,
)
from tests.helpers import create_test_user


class TestGenerateToken:
    def test_token_is_twelve_url_safe_chars(self):
        for _ in range(20):
            token = generate_token()
            assert len(token) == TOKEN_LENGTH == 12
            assert all(
                c.isalnum() or c in "-_" for c in token
            ), f"non-URL-safe char in {token!r}"

    def test_tokens_are_not_all_identical(self):
        # Cheap non-vacuity check on secrets.token_urlsafe's randomness.
        tokens = {generate_token() for _ in range(20)}
        assert len(tokens) == 20


@pytest.mark.asyncio
class TestCreateForPhone:
    async def test_creates_row_with_ttl_and_no_used_at(
        self, db_session: AsyncSession
    ):
        user = await create_test_user(db_session, phone_number="+14155551001")

        before = datetime.now(UTC)
        row = await crud_sponsorship_sign_in_token.create_for_phone(
            db_session, phone_number_id=user.phone_number_id
        )
        after = datetime.now(UTC)

        assert len(row.token) == 12
        assert row.phone_number_id == user.phone_number_id
        assert row.used_at is None
        # TTL is 10 minutes (SPONSORSHIP_TOKEN_TTL_MINUTES).
        assert before + timedelta(minutes=9) < row.expires_at < after + timedelta(
            minutes=11
        )


@pytest.mark.asyncio
class TestConsume:
    async def test_valid_token_returns_phone_and_marks_used(
        self, db_session: AsyncSession
    ):
        user = await create_test_user(db_session, phone_number="+14155551002")
        row = await crud_sponsorship_sign_in_token.create_for_phone(
            db_session, phone_number_id=user.phone_number_id
        )

        phone = await crud_sponsorship_sign_in_token.consume(
            db_session, token=row.token
        )

        assert phone is not None
        assert phone.id == user.phone_number_id
        assert phone.number == "+14155551002"

    async def test_second_consume_of_same_token_returns_none(
        self, db_session: AsyncSession
    ):
        user = await create_test_user(db_session, phone_number="+14155551003")
        row = await crud_sponsorship_sign_in_token.create_for_phone(
            db_session, phone_number_id=user.phone_number_id
        )

        first = await crud_sponsorship_sign_in_token.consume(
            db_session, token=row.token
        )
        second = await crud_sponsorship_sign_in_token.consume(
            db_session, token=row.token
        )

        assert first is not None
        assert second is None

    async def test_expired_token_returns_none(self, db_session: AsyncSession):
        user = await create_test_user(db_session, phone_number="+14155551004")
        db_session.add(
            SponsorshipSignInToken(
                token="expiredtok01",
                phone_number_id=user.phone_number_id,
                expires_at=datetime.now(UTC) - timedelta(minutes=1),
            )
        )
        await db_session.commit()

        phone = await crud_sponsorship_sign_in_token.consume(
            db_session, token="expiredtok01"
        )

        assert phone is None

    async def test_unknown_token_returns_none(self, db_session: AsyncSession):
        phone = await crud_sponsorship_sign_in_token.consume(
            db_session, token="doesnotexist"
        )
        assert phone is None


@pytest.mark.asyncio
class TestPurgeExpired:
    async def test_removes_expired_but_keeps_live_tokens(
        self, db_session: AsyncSession
    ):
        user = await create_test_user(db_session, phone_number="+14155551005")
        live = await crud_sponsorship_sign_in_token.create_for_phone(
            db_session, phone_number_id=user.phone_number_id
        )
        db_session.add(
            SponsorshipSignInToken(
                token="expiredtok02",
                phone_number_id=user.phone_number_id,
                expires_at=datetime.now(UTC) - timedelta(minutes=1),
            )
        )
        await db_session.commit()

        purged = await crud_sponsorship_sign_in_token.purge_expired(db_session)

        assert purged == 1
        assert (
            await db_session.get(SponsorshipSignInToken, "expiredtok02")
        ) is None
        assert (await db_session.get(SponsorshipSignInToken, live.token)) is not None

    async def test_removes_used_and_expired_token(self, db_session: AsyncSession):
        """A used token that's also past its expiry is purged too — used_at
        alone doesn't keep a row around forever."""
        user = await create_test_user(db_session, phone_number="+14155551006")
        db_session.add(
            SponsorshipSignInToken(
                token="usedexpired1",
                phone_number_id=user.phone_number_id,
                expires_at=datetime.now(UTC) - timedelta(minutes=1),
                used_at=datetime.now(UTC) - timedelta(minutes=1),
            )
        )
        await db_session.commit()

        purged = await crud_sponsorship_sign_in_token.purge_expired(db_session)

        assert purged == 1
        assert (
            await db_session.get(SponsorshipSignInToken, "usedexpired1")
        ) is None

    async def test_no_expired_tokens_is_a_noop(self, db_session: AsyncSession):
        user = await create_test_user(db_session, phone_number="+14155551007")
        await crud_sponsorship_sign_in_token.create_for_phone(
            db_session, phone_number_id=user.phone_number_id
        )

        purged = await crud_sponsorship_sign_in_token.purge_expired(db_session)

        assert purged == 0


@pytest.mark.asyncio
class TestRelease:
    async def test_released_token_can_be_consumed_again(
        self, db_session: AsyncSession
    ):
        user = await create_test_user(db_session, phone_number="+14155551008")
        row = await crud_sponsorship_sign_in_token.create_for_phone(
            db_session, phone_number_id=user.phone_number_id
        )

        assert await crud_sponsorship_sign_in_token.consume(
            db_session, token=row.token
        )
        await crud_sponsorship_sign_in_token.release(db_session, token=row.token)

        assert await crud_sponsorship_sign_in_token.consume(
            db_session, token=row.token
        )

    async def test_release_does_not_extend_expiry(self, db_session: AsyncSession):
        user = await create_test_user(db_session, phone_number="+14155551009")
        db_session.add(
            SponsorshipSignInToken(
                token="usedexpired2",
                phone_number_id=user.phone_number_id,
                expires_at=datetime.now(UTC) - timedelta(minutes=1),
                used_at=datetime.now(UTC) - timedelta(minutes=2),
            )
        )
        await db_session.commit()

        await crud_sponsorship_sign_in_token.release(
            db_session, token="usedexpired2"
        )

        assert (
            await crud_sponsorship_sign_in_token.consume(
                db_session, token="usedexpired2"
            )
        ) is None


@pytest.mark.asyncio
class TestConsumeIsAtomic:
    async def test_consume_is_a_single_conditional_update(
        self, db_session: AsyncSession
    ):
        """consume() must be ONE UPDATE ... WHERE used_at IS NULL AND
        expires_at > now RETURNING — never a SELECT then a write, which
        lets two concurrent clicks both see used_at IS NULL and both win."""
        user = await create_test_user(db_session, phone_number="+14155551010")
        row = await crud_sponsorship_sign_in_token.create_for_phone(
            db_session, phone_number_id=user.phone_number_id
        )
        statements: list[str] = []
        real_execute = db_session.execute

        async def spy(stmt, *args, **kwargs):
            statements.append(str(stmt).upper())
            return await real_execute(stmt, *args, **kwargs)

        db_session.execute = spy  # type: ignore[method-assign]
        try:
            await crud_sponsorship_sign_in_token.consume(db_session, token=row.token)
        finally:
            del db_session.execute

        assert statements, "consume() issued no statement"
        first = statements[0]
        assert first.startswith("UPDATE SPONSORSHIP_SIGN_IN_TOKENS")
        assert "USED_AT IS NULL" in first
        assert "EXPIRES_AT >" in first
        assert "RETURNING" in first

    async def test_expired_unused_token_is_left_unused(
        self, db_session: AsyncSession
    ):
        user = await create_test_user(db_session, phone_number="+14155551011")
        db_session.add(
            SponsorshipSignInToken(
                token="expiredtok03",
                phone_number_id=user.phone_number_id,
                expires_at=datetime.now(UTC) - timedelta(minutes=1),
            )
        )
        await db_session.commit()

        await crud_sponsorship_sign_in_token.consume(db_session, token="expiredtok03")

        row = await db_session.get(SponsorshipSignInToken, "expiredtok03")
        await db_session.refresh(row)
        assert row.used_at is None


class TestOtherTokenTypesDontCross:
    def test_sign_in_token_is_not_a_deletion_token(self):
        """Re-homed from the removed JWT tests: the sign-in token can't be
        substituted for the /account/delete JWT."""
        from app.services.account_deletion import decode_deletion_token

        assert decode_deletion_token(generate_token()) is None
