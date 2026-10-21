from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.phone_number import crud_phone_number
from app.models.group_plan import GroupPlan
from app.models.subscription import Subscription, SubscriptionSource, SubscriptionStatus
from app.models.user import STRIPE_CUSTOMER_PENDING_PREFIX, User
from app.services import group_plan_service


async def create_test_admin(
    db: AsyncSession,
    phone_number: str = "+14155551234",
    full_name: str = "Admin User",
    **kwargs,
) -> User:
    """Create a test user with admin privileges."""
    return await create_test_user(
        db,
        phone_number=phone_number,
        full_name=full_name,
        is_admin=True,
        **kwargs,
    )


async def create_test_user(
    db: AsyncSession,
    phone_number: str,
    full_name: str | None = "Test User",
    is_active: bool = True,
    phone_ownership_verified: bool = True,
    **kwargs,
) -> User:
    """Create a test user with the required PhoneNumber record."""
    phone, _ = await crud_phone_number.get_or_create(db, number=phone_number)

    import uuid as _uuid

    user = User(
        phone_number_id=phone.id,
        full_name=full_name,
        is_active=is_active,
        phone_ownership_verified=phone_ownership_verified,
        stripe_customer_id=kwargs.pop("stripe_customer_id", f"{STRIPE_CUSTOMER_PENDING_PREFIX}{_uuid.uuid4()}"),
        **kwargs,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def create_test_subscription(
    db: AsyncSession,
    user: User,
    plan_type: str = "monthly",
    source: str = SubscriptionSource.STRIPE_WEB.value,
    days_remaining: int = 30,
) -> Subscription:
    """Create an active subscription for a test user."""
    now = datetime.now(UTC)
    sub = Subscription(
        user_id=user.id,
        phone_number_id=user.phone_number_id,
        plan_type=plan_type,
        status=SubscriptionStatus.ACTIVE.value,
        source=source,
        current_period_start=now,
        current_period_end=now + timedelta(days=days_remaining),
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)
    return sub


async def create_test_group_plan(
    db: AsyncSession,
    owner: User,
    subscription: Subscription,
) -> GroupPlan:
    """Create a group plan with the owner as the first member."""
    return await group_plan_service.create_group_plan(
        db, owner=owner, subscription_id=subscription.id
    )
