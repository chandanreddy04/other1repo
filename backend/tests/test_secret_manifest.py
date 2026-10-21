"""Guards that the secret manifest stays in sync with backend config.

The single source of truth for deployment env vars is
``infra/secrets/manifest.json``, distributed by ``infra/aws/scripts/populate-secrets.sh``.
These tests fail if a backend env var read in ``app/core/config.py`` is missing
from the manifest, and sanity-check the manifest's shape and resolver.

Related:
  - infra/secrets/manifest.json
  - infra/secrets/manifest.py
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PY = REPO_ROOT / "infra" / "secrets" / "manifest.py"
CONFIG_PY = REPO_ROOT / "backend" / "app" / "core" / "config.py"


def _load_manifest_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("secret_manifest_lib", MANIFEST_PY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


manifest = _load_manifest_module()


def _config_env_var_names() -> set[str]:
    """Every NAME read via os.getenv("NAME", ...) in config.py."""
    source = CONFIG_PY.read_text()
    return set(re.findall(r'os\.getenv\(\s*"([A-Z0-9_]+)"', source))


def test_config_env_vars_present_in_manifest() -> None:
    entries = manifest.load_entries()
    backend_envs = {e["backend_env"] for e in entries if e["side"] == "backend"}
    missing = _config_env_var_names() - backend_envs
    assert not missing, f"config.py env vars missing from manifest.json: {sorted(missing)}"


def test_manifest_entries_wellformed() -> None:
    for entry in manifest.load_entries():
        assert entry.get("name"), f"entry missing name: {entry}"
        assert entry["side"] in {"backend", "mobile"}, entry
        assert isinstance(entry["secret"], bool), entry
        if entry["side"] == "backend":
            assert entry.get("backend_env"), f"backend entry needs backend_env: {entry}"
        else:
            assert entry.get("mobile_extra"), f"mobile entry needs mobile_extra: {entry}"


def test_manifest_names_unique() -> None:
    names = [e["name"] for e in manifest.load_entries()]
    assert len(names) == len(set(names)), "duplicate names in manifest.json"


def test_resolve_static_env_precedence() -> None:
    entry = {"static": {"all": "x", "production": "prod"}}
    assert manifest.resolve_static(entry, "production") == "prod"  # env wins over all
    assert manifest.resolve_static(entry, "staging") == "x"  # falls back to all
    assert manifest.resolve_static({}, "production") is None  # no static -> None


def test_value_file_parsing(tmp_path: Path) -> None:
    f = tmp_path / "vals.env"
    f.write_text(
        "# comment\n"
        "\n"
        "SECRET_KEY=abc123\n"
        "DATABASE_URL=postgresql://u:p@host/db?sslmode=require\n"
    )
    values = manifest.parse_value_file(f)
    assert values["SECRET_KEY"] == "abc123"
    # value containing '=' is preserved (split on first '=' only)
    assert values["DATABASE_URL"] == "postgresql://u:p@host/db?sslmode=require"
    assert "comment" not in values
