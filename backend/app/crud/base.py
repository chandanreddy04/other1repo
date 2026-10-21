from typing import Any, Generic, TypeVar
from uuid import UUID

from fastapi import HTTPException, status
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base
from app.models.user import User

ModelType = TypeVar("ModelType", bound=Base)
CreateSchemaType = TypeVar("CreateSchemaType", bound=BaseModel)
UpdateSchemaType = TypeVar("UpdateSchemaType", bound=BaseModel)


class CRUDBase(Generic[ModelType, CreateSchemaType, UpdateSchemaType]):
    def __init__(self, model: type[ModelType]):
        self.model = model

    async def _commit_and_refresh(
        self, db: AsyncSession, db_obj: ModelType
    ) -> ModelType:
        """
        Common pattern for add, commit, and refresh.

        Args:
            db: Database session
            db_obj: Database object to commit

        Returns:
            The refreshed database object
        """
        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj

    async def get(self, db: AsyncSession, id: UUID) -> ModelType | None:
        """Get a single item by ID."""
        result = await db.execute(select(self.model).where(self.model.id == id))
        return result.scalar_one_or_none()

    async def get_multi(
        self, db: AsyncSession, *, skip: int = 0, limit: int = 100
    ) -> list[ModelType]:
        """Get multiple items with pagination."""
        result = await db.execute(select(self.model).offset(skip).limit(limit))
        return result.scalars().all()

    async def get_multi_by_owner(
        self,
        db: AsyncSession,
        *,
        owner_id: UUID,
        skip: int = 0,
        limit: int = 100,
        user_field: str = "user_id",
    ) -> list[ModelType]:
        """
        Get multiple items by owner with pagination.

        Args:
            db: Database session
            owner_id: ID of the owner
            skip: Number of items to skip
            limit: Maximum number of items to return
            user_field: Name of the field containing user_id

        Returns:
            List of items owned by the user
        """
        # Build filter condition dynamically
        filter_condition = getattr(self.model, user_field) == owner_id

        result = await db.execute(
            select(self.model).filter(filter_condition).offset(skip).limit(limit)
        )
        return result.scalars().all()

    async def create(
        self, db: AsyncSession, *, obj_in: CreateSchemaType, **extra_fields
    ) -> ModelType:
        """
        Create with automatic commit and refresh.

        Args:
            db: Database session
            obj_in: Pydantic schema with creation data
            **extra_fields: Additional fields to set on the model

        Returns:
            The created database object
        """
        obj_in_data = jsonable_encoder(obj_in)
        # Merge extra fields
        obj_in_data.update(extra_fields)
        db_obj = self.model(**obj_in_data)
        return await self._commit_and_refresh(db, db_obj)

    async def update(
        self,
        db: AsyncSession,
        *,
        db_obj: ModelType,
        obj_in: UpdateSchemaType | dict[str, Any],
    ) -> ModelType:
        """
        Update with automatic commit and refresh.

        Args:
            db: Database session
            db_obj: Database object to update
            obj_in: Update data (Pydantic schema or dict)

        Returns:
            The updated database object
        """
        obj_data = jsonable_encoder(db_obj)
        if isinstance(obj_in, dict):
            update_data = obj_in
        else:
            update_data = obj_in.model_dump(exclude_unset=True)

        for field in obj_data:
            if field in update_data:
                setattr(db_obj, field, update_data[field])

        return await self._commit_and_refresh(db, db_obj)

    async def remove(self, db: AsyncSession, *, id: UUID) -> ModelType:
        """
        Remove an item by ID.

        Args:
            db: Database session
            id: ID of the item to remove

        Returns:
            The removed item
        """
        obj = await self.get(db=db, id=id)
        await db.delete(obj)
        await db.commit()
        return obj

    async def count(self, db: AsyncSession) -> int:
        """
        Count total number of items.

        Args:
            db: Database session

        Returns:
            Total count of items
        """
        from sqlalchemy import func

        result = await db.execute(select(func.count()).select_from(self.model))
        return result.scalar()

    async def count_by_owner(
        self, db: AsyncSession, *, owner_id: UUID, user_field: str = "user_id"
    ) -> int:
        """
        Count items owned by a specific user.

        Args:
            db: Database session
            owner_id: ID of the owner
            user_field: Name of the field containing user_id

        Returns:
            Count of items owned by the user
        """
        from sqlalchemy import func

        filter_condition = getattr(self.model, user_field) == owner_id
        result = await db.execute(
            select(func.count()).select_from(self.model).filter(filter_condition)
        )
        return result.scalar()

    async def get_multi_by_ids(
        self, db: AsyncSession, *, ids: list[UUID]
    ) -> list[ModelType]:
        """Get multiple items by their IDs in a single query."""
        if not ids:
            return []
        result = await db.execute(
            select(self.model).where(self.model.id.in_(ids))
        )
        return result.scalars().all()

    async def get_or_create_by_owner(
        self,
        db: AsyncSession,
        *,
        owner_id: UUID,
        user_field: str = "user_id",
        defaults: dict | None = None,
    ) -> ModelType:
        """Get existing record by owner or create with defaults."""
        filter_condition = getattr(self.model, user_field) == owner_id
        result = await db.execute(select(self.model).where(filter_condition))
        existing = result.scalar_one_or_none()
        if existing:
            return existing

        create_data = {user_field: owner_id}
        if defaults:
            create_data.update(defaults)
        db_obj = self.model(**create_data)
        return await self._commit_and_refresh(db, db_obj)

    async def exists(self, db: AsyncSession, *, id: UUID) -> bool:
        """
        Check if an item exists by ID.

        Args:
            db: Database session
            id: ID to check

        Returns:
            True if exists, False otherwise
        """
        result = await db.execute(select(self.model.id).where(self.model.id == id))
        return result.scalar_one_or_none() is not None

    async def get_owned_or_404(
        self,
        db: AsyncSession,
        *,
        id: UUID,
        owner: User,
        resource_name: str = "resource",
        user_field: str = "user_id",
        custom_error: str | None = None,
    ) -> ModelType:
        """
        Get a resource and validate ownership, or raise 404/403.

        Args:
            db: Database session
            id: ID of the resource
            owner: User who should own the resource
            resource_name: Name for error messages
            user_field: Field containing user_id
            custom_error: Custom error message

        Returns:
            The validated resource

        Raises:
            HTTPException: 404 if not found, 403 if not owned
        """
        resource = await self.get(db, id=id)

        if not resource:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"{resource_name.title()} not found",
            )

        resource_user_id = getattr(resource, user_field, None)
        if resource_user_id != owner.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=custom_error or f"You can only access your own {resource_name}s",
            )

        return resource
