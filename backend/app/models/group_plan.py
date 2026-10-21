import enum
import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class GroupPlanMemberRole(enum.StrEnum):
    OWNER = "owner"
    MEMBER = "member"


class GroupPlan(Base):
    __tablename__ = "group_plans"
    __table_args__ = (
        UniqueConstraint("subscription_id", name="uq_group_plans_subscription"),
        UniqueConstraint("invite_code", name="uq_group_plans_invite_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscriptions.id")
    )
    invite_code: Mapped[str] = mapped_column(
        String, default=lambda: secrets.token_urlsafe(16)
    )
    max_members: Mapped[int] = mapped_column(Integer, default=5)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    owner = relationship("User", foreign_keys=[owner_user_id], lazy="joined")
    subscription = relationship("Subscription", foreign_keys=[subscription_id])
    members = relationship(
        "GroupPlanMember",
        back_populates="group_plan",
        cascade="all, delete-orphan",
    )


class GroupPlanMember(Base):
    __tablename__ = "group_plan_members"
    __table_args__ = (
        UniqueConstraint(
            "group_plan_id", "user_id", name="uq_gpm_plan_user"
        ),
        Index("ix_gpm_plan_left", "group_plan_id", "left_at"),
        Index("ix_group_plan_members_user_id", "user_id"),
        # One active plan per user. Lived only in the migration before; declared
        # here so autogenerate can't drop it (it backs join_plan's guarantee).
        Index(
            "ix_gpm_one_active_per_user",
            "user_id",
            unique=True,
            postgresql_where=text("left_at IS NULL"),
        ),
        CheckConstraint(
            "role IN ('owner','member')", name="ck_group_plan_members_role"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    group_plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("group_plans.id")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    role: Mapped[str] = mapped_column(String, default=GroupPlanMemberRole.MEMBER.value)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    left_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    group_plan = relationship("GroupPlan", back_populates="members")
    user = relationship("User", foreign_keys=[user_id], lazy="joined")
