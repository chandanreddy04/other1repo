"""Test CRUD base operations."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.base import CRUDBase
from app.models.phone_number import PhoneNumber
from app.models.user import User


@pytest.mark.asyncio
class TestCRUDBase:
    """Test CRUD base functionality."""

    async def test_crud_get(self, db_session: AsyncSession, test_user):
        """Test getting a record by ID."""
        crud = CRUDBase(User)
        user = await crud.get(db_session, id=test_user.id)
        assert user is not None
        assert user.id == test_user.id

    async def test_crud_get_multi(
        self, db_session: AsyncSession, test_user, test_user2
    ):
        """Test getting multiple records."""
        crud = CRUDBase(User)
        users = await crud.get_multi(db_session)
        assert len(users) >= 2
        user_ids = [u.id for u in users]
        assert test_user.id in user_ids
        assert test_user2.id in user_ids

    async def test_crud_get_multi_with_skip_limit(
        self, db_session: AsyncSession, test_user, test_user2
    ):
        """Test getting multiple records with pagination."""
        crud = CRUDBase(User)
        users = await crud.get_multi(db_session, skip=0, limit=1)
        assert len(users) == 1

    async def test_crud_create(self, db_session: AsyncSession):
        """Test creating a new record."""
        phone = PhoneNumber(number="+12065551234")
        db_session.add(phone)
        await db_session.flush()

        crud = CRUDBase(User)
        user_data = {"phone_number_id": str(phone.id), "full_name": "New User"}
        user = await crud.create(db_session, obj_in=user_data)
        assert user.phone_number == "+12065551234"
        assert user.full_name == "New User"

    async def test_crud_update_with_dict(self, db_session: AsyncSession, test_user):
        """Test updating with dict."""
        crud = CRUDBase(User)
        update_data = {"full_name": "Updated Name"}
        updated_user = await crud.update(
            db_session, db_obj=test_user, obj_in=update_data
        )
        assert updated_user.full_name == "Updated Name"

    async def test_crud_remove(self, db_session: AsyncSession):
        """Test removing a record."""
        phone = PhoneNumber(number="+12065559999")
        db_session.add(phone)
        await db_session.flush()

        crud = CRUDBase(User)
        user_data = {"phone_number_id": str(phone.id), "full_name": "To Delete"}
        user = await crud.create(db_session, obj_in=user_data)

        # Delete the user
        deleted_user = await crud.remove(db_session, id=user.id)
        assert deleted_user.id == user.id

        # Verify it's deleted
        fetched = await crud.get(db_session, id=user.id)
        assert fetched is None

    async def test_crud_get_by_field(self, db_session: AsyncSession, test_user):
        """Test getting by specific field."""
        from app.crud.user import crud_user

        user = await crud_user.get_by_phone(
            db_session, phone_number=test_user.phone_number
        )
        assert user is not None
        assert user.id == test_user.id
