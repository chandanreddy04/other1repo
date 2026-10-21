from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.v1.deps.db import get_db
from app.db.base import Base
from app.main import app
from app.models.account_grant import AccountGrant  # noqa: F401
from app.models.admin_access_log import AdminAccessLog  # noqa: F401
from app.models.alert import Alert  # noqa: F401
from app.models.circle_of_trust import CircleOfTrustMember  # noqa: F401
from app.models.circle_of_trust_settings import CircleOfTrustSettings  # noqa: F401
from app.models.group_plan import GroupPlan, GroupPlanMember  # noqa: F401
from app.models.notification_delivery import (  # noqa: F401
    NotificationDelivery,
)
from app.models.otp import OTP  # noqa: F401
from app.models.phone_number import PhoneNumber  # noqa: F401
from app.models.processed_stripe_event import ProcessedStripeEvent  # noqa: F401
from app.models.session import Session as SessionModel  # noqa: F401
from app.models.session_reminder import SessionReminder  # noqa: F401
from app.models.sponsor import SponsorshipRequest  # noqa: F401
from app.models.sponsorship_sign_in_token import SponsorshipSignInToken  # noqa: F401
from app.models.subscription import Promotion, Referral, Subscription  # noqa: F401
from app.models.user import User
from tests.helpers import create_test_admin, create_test_user

# Test database URL - using PostgreSQL test database
TEST_DATABASE_URL = (
    "postgresql+asyncpg://madeithome:madeithome@localhost:5432/made_it_home_test"
)

# Create test engine
test_engine = create_async_engine(
    TEST_DATABASE_URL,
    poolclass=NullPool,
)

# Track whether tables have been created this session
_tables_created = False


@pytest_asyncio.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide a clean database session for each test using nested transactions.

    Uses the savepoint pattern so that endpoint code can call db.commit()
    without actually persisting data between tests. Each test's changes
    are rolled back at the end via the outer transaction.
    """
    global _tables_created

    # Create tables once per test session (drop first to handle stale enum types)
    if not _tables_created:
        async with test_engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
            await conn.run_sync(Base.metadata.create_all)
        _tables_created = True

    # Open a real connection and begin a non-auto-committing transaction
    connection = await test_engine.connect()
    transaction = await connection.begin()

    # Create session bound to this connection
    session = AsyncSession(bind=connection, expire_on_commit=False)

    # Begin a nested transaction (SAVEPOINT)
    await connection.begin_nested()

    # After each commit within the test (e.g. from endpoint code),
    # restart the savepoint so subsequent operations still work
    @event.listens_for(session.sync_session, "after_transaction_end")
    def restart_savepoint(sync_session: object, trans: object) -> None:
        if connection.sync_connection is not None and not connection.closed:
            if connection.sync_connection.in_nested_transaction():
                return
            connection.sync_connection.begin_nested()

    yield session

    # Cleanup: close session, rollback outer transaction, close connection
    await session.close()
    if transaction.is_active:
        await transaction.rollback()
    await connection.close()


@pytest_asyncio.fixture(scope="function")
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Create a test client with overridden database dependency."""

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    from httpx import ASGITransport

    # Reset slowapi counters between tests. The limiter is disabled in
    # test env by default, but a single test that re-enables it (e.g.
    # to exercise the per-IP enumeration cap on /request-otp) can leave
    # a counter at the cap for the next test that uses the same IP.
    from app.core.rate_limit import limiter

    limiter.reset()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    limiter.reset()


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession) -> User:
    """Create a test user."""
    return await create_test_user(db_session, phone_number="+1234567890", full_name="Test User")


@pytest_asyncio.fixture
async def test_user2(db_session: AsyncSession) -> User:
    """Create a second test user."""
    return await create_test_user(db_session, phone_number="+19876543210", full_name="Test User 2")


@pytest_asyncio.fixture
async def auth_headers(client: AsyncClient, test_user: User) -> dict:
    """Get authentication headers for test user."""
    from app.core.security import create_access_token

    token = create_access_token(str(test_user.id))
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def auth_headers2(client: AsyncClient, test_user2: User) -> dict:
    """Get authentication headers for second test user."""
    from app.core.security import create_access_token

    token = create_access_token(str(test_user2.id))
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def test_admin(db_session: AsyncSession) -> User:
    """Create a test admin user."""
    return await create_test_admin(db_session)


@pytest_asyncio.fixture
async def admin_cookies(test_admin: User) -> dict[str, str]:
    """Get auth cookies for the admin user."""
    from app.core.security import create_access_token

    token = create_access_token(str(test_admin.id))
    return {"access_token": token}


