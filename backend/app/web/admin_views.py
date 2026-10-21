"""Generic CRUD admin view generator for SQLAlchemy models.

Register an AdminModelView in admin_registry.py and routes are
auto-generated (list/detail/create/edit/delete). row_class callback
enables conditional row highlighting (e.g. exhausted-retry alerts).

Related: web/admin_registry.py, web/templates/admin/
"""

from __future__ import annotations

import contextlib
import enum
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import String, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute, joinedload

from app.api.v1.deps.db import get_db
from app.core.config import settings
from app.models.user import User
from app.web.csrf import get_or_create_csrf_token, set_csrf_cookie, validate_csrf_token
from app.web.deps import get_current_admin

templates = Jinja2Templates(directory="app/web/templates")
# admin/base_admin.html's "Main Site" link points at the marketing site
# (owner decision 2026-09-23: marketing lives only on marketing-site).
templates.env.globals["marketing_origin"] = settings.MARKETING_ORIGIN


async def _write_audit_log(
    db: AsyncSession,
    *,
    admin_user_id: uuid.UUID,
    entity: str,
    action: str,
    entity_id: uuid.UUID | None = None,
    item: Any | None = None,
) -> None:
    """Write a row to admin_access_logs. Imported lazily to avoid circular deps."""
    from app.models.admin_access_log import AdminAccessLog

    target_user_id: uuid.UUID | None = None
    if item is not None:
        if entity == "user":
            target_user_id = getattr(item, "id", None)
        else:
            target_user_id = getattr(item, "user_id", None)

    log = AdminAccessLog(
        admin_user_id=admin_user_id,
        target_user_id=target_user_id,
        entity=entity,
        entity_id=entity_id,
        action=action,
    )
    db.add(log)
    await db.commit()


@dataclass
class AdminColumnConfig:
    """Configuration for a column in admin list/detail views."""

    key: str
    label: str
    sortable: bool = True
    searchable: bool = False
    formatter: Callable[[Any], str] | None = None
    link_to_detail: bool = False
    # For searching across a joined relationship (e.g. phone.number)
    join_model: type | None = None
    join_attr: str | None = None


@dataclass
class AdminFilterConfig:
    """Configuration for a filter dropdown in admin list views."""

    key: str
    label: str
    choices: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class AdminRelatedConfig:
    """A read-only table of related child rows rendered on a parent's detail
    page (e.g. a session's captured location/battery updates) — instead of a
    separate top-level admin section."""

    title: str
    model: type
    foreign_key: str  # attribute on `model` holding the parent's id
    columns: list[AdminColumnConfig]
    order_by: str | None = None
    descending: bool = False
    limit: int | None = 500  # None → show everything
    empty_text: str = "None recorded."


@dataclass
class AdminModelView:
    """Generic admin CRUD view generator for a SQLAlchemy model."""

    model: type
    name: str
    name_plural: str
    columns: list[AdminColumnConfig]
    detail_fields: list[AdminColumnConfig] | None = None
    filters: list[AdminFilterConfig] = field(default_factory=list)
    read_only: bool = False
    eager_loads: list[Any] = field(default_factory=list)
    page_size: int = 25
    # Editable fields for create/edit forms. Each is (key, label, field_type, choices).
    # field_type: "text", "select", "bool", "datetime", "number", "textarea"
    form_fields: list[tuple[str, str, str, list[tuple[str, str]] | None]] = field(
        default_factory=list
    )
    # Section name for sidebar highlighting
    section: str = ""
    # Optional callback returning a CSS class for a row (e.g. "row-warning")
    row_class: Callable[[Any], str] | None = None
    # Optional async hook to transform parsed form data before create/update
    # (e.g. resolve a "phone_number" string to a phone_number_id FK). Signature:
    # async (db, obj_data: dict) -> dict.
    form_transform: Callable[[Any, dict[str, Any]], Any] | None = None
    # Read-only related child tables rendered on this entity's detail page.
    related: list[AdminRelatedConfig] = field(default_factory=list)
    # Optional custom detail-page section (template + async context hook) for
    # things the generic tables can't render — e.g. a session's location map
    # and alerts table. Hook signature: async (db, item) -> dict; the returned
    # dict is merged into the detail template context.
    detail_extra_template: str | None = None
    detail_context_hook: Callable[[Any, Any], Any] | None = None

    def register_routes(self, router: APIRouter) -> None:
        """Register all CRUD routes for this entity on the router."""
        prefix = f"/{self.name_plural}"

        # Capture self in closure
        view = self

        if not self.read_only:
            # Create form — must register before {item_id} to avoid capturing "new" as UUID
            @router.get(
                f"{prefix}/new",
                response_class=HTMLResponse,
                name=f"admin_{self.name_plural}_new",
            )
            async def create_form(
                request: Request,
                db: AsyncSession = Depends(get_db),
                current_admin: User = Depends(get_current_admin),
            ):
                return await view._form_view(request)

            # Create action
            @router.post(
                prefix,
                response_class=HTMLResponse,
                name=f"admin_{self.name_plural}_create",
            )
            async def create_action(
                request: Request,
                db: AsyncSession = Depends(get_db),
                current_admin: User = Depends(get_current_admin),
            ):
                return await view._create_action(request, db, current_admin)

        # HTMX table fragment — must register before {item_id}
        @router.get(
            f"{prefix}/htmx/table",
            response_class=HTMLResponse,
            name=f"admin_{self.name_plural}_htmx_table",
        )
        async def htmx_table(
            request: Request,
            page: int = 1,
            search: str = "",
            sort: str = "",
            sort_dir: str = "asc",
            db: AsyncSession = Depends(get_db),
            current_admin: User = Depends(get_current_admin),
        ):
            return await view._htmx_table(request, db, page, search, sort, sort_dir)

        # List view
        @router.get(
            prefix, response_class=HTMLResponse, name=f"admin_{self.name_plural}_list"
        )
        async def list_view(
            request: Request,
            page: int = 1,
            search: str = "",
            sort: str = "",
            sort_dir: str = "asc",
            db: AsyncSession = Depends(get_db),
            current_admin: User = Depends(get_current_admin),
        ):
            return await view._list_view(
                request, db, page, search, sort, sort_dir, current_admin
            )

        if not self.read_only:
            # Edit form — must register before bare {item_id}
            @router.get(
                f"{prefix}/{{item_id}}/edit",
                response_class=HTMLResponse,
                name=f"admin_{self.name_plural}_edit",
            )
            async def edit_form(
                request: Request,
                item_id: uuid.UUID,
                db: AsyncSession = Depends(get_db),
                current_admin: User = Depends(get_current_admin),
            ):
                return await view._form_view(request, db, item_id)

            # Update action
            @router.post(
                f"{prefix}/{{item_id}}",
                response_class=HTMLResponse,
                name=f"admin_{self.name_plural}_update",
            )
            async def update_action(
                request: Request,
                item_id: uuid.UUID,
                db: AsyncSession = Depends(get_db),
                current_admin: User = Depends(get_current_admin),
            ):
                return await view._update_action(request, db, item_id, current_admin)

            # Delete action — HTML forms can't send DELETE
            @router.post(
                f"{prefix}/{{item_id}}/delete",
                response_class=HTMLResponse,
                name=f"admin_{self.name_plural}_delete",
            )
            async def delete_action(
                request: Request,
                item_id: uuid.UUID,
                db: AsyncSession = Depends(get_db),
                current_admin: User = Depends(get_current_admin),
            ):
                return await view._delete_action(request, db, item_id, current_admin)

        # Detail view — register last since {item_id} catches all paths
        @router.get(
            f"{prefix}/{{item_id}}",
            response_class=HTMLResponse,
            name=f"admin_{self.name_plural}_detail",
        )
        async def detail_view(
            request: Request,
            item_id: uuid.UUID,
            db: AsyncSession = Depends(get_db),
            current_admin: User = Depends(get_current_admin),
        ):
            return await view._detail_view(request, db, item_id, current_admin)

    # ── Internal view methods ──

    async def _build_query(self, db, search, sort, sort_dir):
        """Build the filtered/sorted query."""
        query = select(self.model)

        # Eager loads
        for rel in self.eager_loads:
            query = query.options(joinedload(rel))

        # Search
        if search:
            search_conditions = []
            joined_models = set()
            for col in self.columns:
                if not col.searchable:
                    continue
                if col.join_model and col.join_attr:
                    if col.join_model not in joined_models:
                        query = query.join(col.join_model)
                        joined_models.add(col.join_model)
                    search_conditions.append(
                        getattr(col.join_model, col.join_attr)
                        .cast(String)
                        .ilike(f"%{search}%")
                    )
                elif hasattr(self.model, col.key):
                    attr = getattr(self.model, col.key)
                    if isinstance(attr, InstrumentedAttribute):
                        search_conditions.append(attr.cast(String).ilike(f"%{search}%"))
            if search_conditions:
                query = query.where(or_(*search_conditions))

        # Sorting
        if sort and hasattr(self.model, sort):
            sort_col = getattr(self.model, sort)
            query = query.order_by(
                sort_col.desc() if sort_dir == "desc" else sort_col.asc()
            )
        elif hasattr(self.model, "created_at"):
            query = query.order_by(self.model.created_at.desc())
        else:
            query = query.order_by(self.model.id.desc())

        return query

    async def _get_filter_values(self, request: Request) -> dict[str, str]:
        """Extract active filter values from query params."""
        values = {}
        for f in self.filters:
            val = request.query_params.get(f"filter_{f.key}", "")
            if val:
                values[f.key] = val
        return values

    async def _apply_filters(self, query, filter_values):
        """Apply filter conditions to query."""
        from sqlalchemy import Boolean
        from sqlalchemy import inspect as sa_inspect

        for key, val in filter_values.items():
            if not hasattr(self.model, key):
                continue
            col = getattr(self.model, key)
            # Convert string "True"/"False" for boolean columns
            mapper = sa_inspect(self.model)
            if key in mapper.columns:
                col_type = mapper.columns[key].type
                if isinstance(col_type, Boolean):
                    val = val in ("True", "true", "1")
            query = query.where(col == val)
        return query

    async def _list_view(
        self, request, db, page, search, sort, sort_dir, current_admin=None
    ):
        section = self.section or self.name_plural
        filter_values = await self._get_filter_values(request)

        query = await self._build_query(db, search, sort, sort_dir)
        query = await self._apply_filters(query, filter_values)

        # Count total
        count_query = select(func.count()).select_from(
            query.with_only_columns(self.model.id).subquery()
        )
        total = (await db.execute(count_query)).scalar()

        # Paginate
        offset = (page - 1) * self.page_size
        items_result = await db.execute(query.offset(offset).limit(self.page_size))
        items = items_result.scalars().unique().all()

        total_pages = max(1, (total + self.page_size - 1) // self.page_size)

        if current_admin:
            await _write_audit_log(
                db, admin_user_id=current_admin.id, entity=self.name, action="list"
            )

        return templates.TemplateResponse(
            request,
            "admin/list.html",
            {
                "request": request,
                "active_section": section,
                "view": self,
                "items": items,
                "total": total,
                "page": page,
                "total_pages": total_pages,
                "search": search,
                "sort": sort,
                "sort_dir": sort_dir,
                "filter_values": filter_values,
            },
        )

    async def _htmx_table(self, request, db, page, search, sort, sort_dir):
        filter_values = await self._get_filter_values(request)

        query = await self._build_query(db, search, sort, sort_dir)
        query = await self._apply_filters(query, filter_values)

        count_query = select(func.count()).select_from(
            query.with_only_columns(self.model.id).subquery()
        )
        total = (await db.execute(count_query)).scalar()

        offset = (page - 1) * self.page_size
        items_result = await db.execute(query.offset(offset).limit(self.page_size))
        items = items_result.scalars().unique().all()

        total_pages = max(1, (total + self.page_size - 1) // self.page_size)

        return templates.TemplateResponse(
            request,
            "admin/fragments/table_body.html",
            {
                "request": request,
                "view": self,
                "items": items,
                "total": total,
                "page": page,
                "total_pages": total_pages,
                "search": search,
                "sort": sort,
                "sort_dir": sort_dir,
                "filter_values": filter_values,
            },
        )

    async def _detail_view(self, request, db, item_id, current_admin=None):
        section = self.section or self.name_plural
        query = select(self.model).where(self.model.id == item_id)
        for rel in self.eager_loads:
            query = query.options(joinedload(rel))

        result = await db.execute(query)
        item = result.scalars().unique().first()
        if not item:
            return HTMLResponse("Not found", status_code=404)

        if current_admin:
            await _write_audit_log(
                db,
                admin_user_id=current_admin.id,
                entity=self.name,
                action="view_detail",
                entity_id=item_id,
                item=item,
            )

        fields = self.detail_fields or self.columns
        csrf_token = get_or_create_csrf_token(request)

        # Read-only related child tables (e.g. a session's captured updates).
        related_sections = []
        for rel in self.related:
            rel_query = select(rel.model).where(
                getattr(rel.model, rel.foreign_key) == item_id
            )
            if rel.order_by:
                order_col = getattr(rel.model, rel.order_by)
                rel_query = rel_query.order_by(
                    order_col.desc() if rel.descending else order_col.asc()
                )
            if rel.limit is not None:
                rel_query = rel_query.limit(rel.limit)
            rel_rows = (await db.execute(rel_query)).scalars().all()
            related_sections.append({"config": rel, "rows": rel_rows})

        extra_context = (
            await self.detail_context_hook(db, item) if self.detail_context_hook else {}
        )

        response = templates.TemplateResponse(
            request,
            "admin/detail.html",
            {
                "request": request,
                "active_section": section,
                "view": self,
                "item": item,
                "fields": fields,
                "related_sections": related_sections,
                "csrf_token": csrf_token,
                **extra_context,
            },
        )
        set_csrf_cookie(response, csrf_token)
        return response

    async def _form_view(self, request, db=None, item_id=None):
        section = self.section or self.name_plural
        item = None
        if item_id and db:
            result = await db.execute(
                select(self.model).where(self.model.id == item_id)
            )
            item = result.scalars().first()
            if not item:
                return HTMLResponse("Not found", status_code=404)

        csrf_token = get_or_create_csrf_token(request)
        response = templates.TemplateResponse(
            request,
            "admin/form.html",
            {
                "request": request,
                "active_section": section,
                "view": self,
                "item": item,
                "csrf_token": csrf_token,
            },
        )
        set_csrf_cookie(response, csrf_token)
        return response

    async def _create_action(self, request, db, current_admin=None):
        await validate_csrf_token(request)
        form_data = await request.form()
        obj_data = self._parse_form_data(form_data)
        if self.form_transform:
            obj_data = await self.form_transform(db, obj_data)

        db_obj = self.model(**obj_data)
        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)

        if current_admin:
            await _write_audit_log(
                db,
                admin_user_id=current_admin.id,
                entity=self.name,
                action="create",
                entity_id=db_obj.id,
                item=db_obj,
            )

        return RedirectResponse(
            url=f"/admin/{self.name_plural}/{db_obj.id}",
            status_code=303,
        )

    async def _update_action(self, request, db, item_id, current_admin=None):
        await validate_csrf_token(request)
        result = await db.execute(select(self.model).where(self.model.id == item_id))
        item = result.scalars().first()
        if not item:
            return HTMLResponse("Not found", status_code=404)

        form_data = await request.form()
        obj_data = self._parse_form_data(form_data)
        if self.form_transform:
            obj_data = await self.form_transform(db, obj_data)

        for key, value in obj_data.items():
            setattr(item, key, value)

        db.add(item)
        await db.commit()

        if current_admin:
            await _write_audit_log(
                db,
                admin_user_id=current_admin.id,
                entity=self.name,
                action="edit",
                entity_id=item_id,
                item=item,
            )

        return RedirectResponse(
            url=f"/admin/{self.name_plural}/{item_id}",
            status_code=303,
        )

    async def _delete_action(self, request, db, item_id, current_admin=None):
        await validate_csrf_token(request)
        result = await db.execute(select(self.model).where(self.model.id == item_id))
        item = result.scalars().first()
        if not item:
            return HTMLResponse("Not found", status_code=404)

        if current_admin:
            await _write_audit_log(
                db,
                admin_user_id=current_admin.id,
                entity=self.name,
                action="delete",
                entity_id=item_id,
                item=item,
            )

        await db.delete(item)
        await db.commit()

        return RedirectResponse(
            url=f"/admin/{self.name_plural}",
            status_code=303,
        )

    def _parse_form_data(self, form_data) -> dict[str, Any]:
        """Convert form data to model field values based on form_fields config."""
        result: dict[str, Any] = {}
        for key, _label, field_type, _choices in self.form_fields:
            raw = form_data.get(key)
            if raw is None or raw == "":
                if field_type == "bool":
                    result[key] = False
                continue

            if field_type == "bool":
                result[key] = raw in ("true", "on", "1", "True")
            elif field_type == "number":
                result[key] = int(raw)
            elif field_type == "datetime":
                # benign: an unparsable admin filter value is ignored
                with contextlib.suppress(ValueError):
                    result[key] = datetime.fromisoformat(raw)
            elif field_type == "uuid":
                # benign: an unparsable admin filter value is ignored
                with contextlib.suppress(ValueError):
                    result[key] = uuid.UUID(raw)
            else:
                result[key] = raw

        return result

    def get_cell_value(self, item: Any, col: AdminColumnConfig) -> str:
        """Get the display value for a cell."""
        try:
            # Support dotted keys like "phone.number"
            value = item
            for part in col.key.split("."):
                if value is None:
                    break
                value = getattr(value, part, None)
        except Exception:
            # benign: an unresolvable admin column renders as "—"
            value = None

        if value is None:
            return "—"

        if col.formatter:
            return col.formatter(value)

        if isinstance(value, datetime):
            return value.strftime("%b %d, %Y %H:%M")

        if isinstance(value, bool):
            return "Yes" if value else "No"

        if isinstance(value, enum.Enum):
            return value.value

        if isinstance(value, uuid.UUID):
            return str(value)[:8] + "…"

        return str(value)
