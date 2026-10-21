"""Every value of a Postgres-native enum column appears in a migration.

The test DB is built with `Base.metadata.create_all` (conftest.py), so a new
enum member (e.g. a NotificationKind) works in tests even if no migration ever
adds it — and then every INSERT of that value fails in staging/production with
"invalid input value for enum". Guard it statically (no DB): for every mapped
column whose type is a native `sqlalchemy.Enum` with a `name=`, each stored
value must appear as a quoted string literal in at least one file under
alembic/versions/ (a CREATE TYPE list, an `ADD VALUE`, or a `RENAME VALUE`).

Related: app/models/ (Enum(..., name=...) columns), alembic/versions/,
         tests/test_enum_check_constraints.py (the String+CHECK equivalent).
"""

from pathlib import Path

import pytest
from sqlalchemy import Enum as SAEnum

import app.models  # noqa: F401 — populates Base.metadata via the package __init__
from app.db.base import Base

_VERSIONS_DIR = Path(__file__).resolve().parent.parent / "alembic" / "versions"


def _native_enum_types() -> dict[str, list[str]]:
    """{enum type name: stored values} for every native named Enum column."""
    found: dict[str, list[str]] = {}
    for table in Base.metadata.tables.values():
        for column in table.columns:
            col_type = column.type
            if isinstance(col_type, SAEnum) and col_type.native_enum and col_type.name:
                found[col_type.name] = list(col_type.enums)
    return found


_ENUM_TYPES = _native_enum_types()
_MIGRATIONS_SRC = "\n".join(
    p.read_text() for p in sorted(_VERSIONS_DIR.glob("*.py"))
)


def test_discovers_the_known_enum_types():
    # Guards the discovery itself: if it silently found nothing, the
    # parametrized test below would pass vacuously.
    assert {
        "notification_kind_enum",
        "notification_channel_enum",
        "notification_delivery_status_enum",
        "alert_type_enum",
        "alert_status_enum",
        "session_type_enum",
        "session_status_enum",
        "contact_status_enum",
    } <= set(_ENUM_TYPES)


@pytest.mark.parametrize("enum_name", sorted(_ENUM_TYPES))
def test_every_enum_value_is_in_a_migration(enum_name: str):
    missing = [
        value
        for value in _ENUM_TYPES[enum_name]
        if f"'{value}'" not in _MIGRATIONS_SRC and f'"{value}"' not in _MIGRATIONS_SRC
    ]
    assert not missing, (
        f"{enum_name} values {missing} appear in no alembic migration; add an "
        "`ALTER TYPE ... ADD VALUE IF NOT EXISTS` migration (autocommit_block) "
        "or production INSERTs of these values will fail"
    )
