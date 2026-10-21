#!/usr/bin/env python
"""Script to approve all Circle of Trust invitations for a user."""

import asyncio
import sys
from datetime import UTC, datetime

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.circle_of_trust import CircleOfTrustMember
from app.models.user import User


async def approve_invitations(phone_number: str):
    """Approve all pending Circle of Trust invitations for a user."""
    async with AsyncSessionLocal() as session:
        # Ensure phone number has +1 prefix
        if not phone_number.startswith("+"):
            if not phone_number.startswith("1"):
                phone_number = "+1" + phone_number
            else:
                phone_number = "+" + phone_number

        print(f"Looking for user with phone number: {phone_number}")

        # Find user by phone
        user_result = await session.execute(
            select(User).where(User.phone_number == phone_number)
        )
        user = user_result.scalar_one_or_none()

        if not user:
            print(f"User not found with phone number: {phone_number}")
            return

        print(f"Found user: {user.full_name} ({user.phone_number}), ID: {user.id}")

        # Find all pending invitations for this user
        invitations_result = await session.execute(
            select(CircleOfTrustMember).where(
                CircleOfTrustMember.contact_phone_number == user.phone_number,
                CircleOfTrustMember.status == "pending",
            )
        )
        invitations = invitations_result.scalars().all()

        print(f"Found {len(invitations)} pending invitations")

        if not invitations:
            print("No pending invitations to approve")
            return

        for invitation in invitations:
            # Get the inviter's info
            inviter_result = await session.execute(
                select(User).where(User.id == invitation.user_id)
            )
            inviter = inviter_result.scalar_one_or_none()
            print(
                f"Approving invitation from {inviter.full_name if inviter else 'Unknown'} (user ID {invitation.user_id})"
            )

            # Update invitation status
            invitation.status = "active"
            invitation.contact_user_id = user.id
            invitation.accepted_at = datetime.now(UTC)

        await session.commit()
        print(f"Successfully approved {len(invitations)} invitations")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python approve_invitations.py <phone_number>")
        print("Example: python approve_invitations.py 5182608694")
        sys.exit(1)

    phone = sys.argv[1]
    asyncio.run(approve_invitations(phone))
