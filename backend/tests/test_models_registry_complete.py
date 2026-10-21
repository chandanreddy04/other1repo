"""Every model module is registered in app/models/__init__.py.

alembic/env.py builds its autogenerate metadata with `from app.models import *`,
so a model module that the package __init__ doesn't import is invisible to
autogenerate — which then proposes DROPPING that live table. `account_grants`
sat in exactly that blind spot (found 2026-09-05 when an unrelated
autogenerate emitted `op.drop_table("account_grants")`). Guard it statically:
each module under app/models/ must be imported by the package, and every
mapped table must be present in Base.metadata after importing the package.

Related: app/models/__init__.py, alembic/env.py, tests/conftest.py.
"""

import re
from pathlib import Path

import app.models  # populates Base.metadata via the package __init__
from app.db.base import Base

_MODELS_DIR = Path(app.models.__file__).parent
_INIT = _MODELS_DIR / "__init__.py"


def _model_modules() -> list[str]:
    return sorted(
        p.stem
        for p in _MODELS_DIR.glob("*.py")
        if p.name != "__init__.py" and not p.name.startswith("_")
    )


def test_every_model_module_is_imported_by_the_package():
    init_src = _INIT.read_text()
    imported = set(re.findall(r"^from app\.models\.(\w+) import", init_src, re.M))
    missing = [m for m in _model_modules() if m not in imported]
    assert not missing, (
        f"app/models/__init__.py does not import {missing}; alembic autogenerate "
        "will not see their tables and will propose dropping them"
    )


def test_every_mapped_table_is_in_metadata():
    src = "\n".join((_MODELS_DIR / f"{m}.py").read_text() for m in _model_modules())
    declared = set(re.findall(r'__tablename__\s*=\s*"([a-z_]+)"', src))
    assert declared, "no __tablename__ declarations found — regex regression?"
    missing = sorted(declared - set(Base.metadata.tables))
    assert not missing, (
        f"tables declared by model modules but absent from metadata: {missing}"
    )
