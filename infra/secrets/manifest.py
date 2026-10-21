"""Loader/resolver for the secret manifest — the single source of truth.

Reads ``infra/secrets/manifest.json`` and resolves which env vars belong to the
backend vs mobile, which are secrets (Secrets Manager / EAS) vs static inline values,
and emits machine-readable output consumed by ``infra/aws/scripts/populate-secrets.sh``.

Subcommands:
  template            print ``NAME=`` lines for every secret (value-file scaffold)
  validate ENV FILE   exit non-zero if any secret for ENV lacks a value in FILE
  dotenv  ENV SIDE FILE  print ``NAME=value`` lines for a local .env (dev)
  cloud   ENV SIDE FILE  print TSV ``kind\tenv_var\tvalue`` for the secret-push script / eas

Related:
  - infra/secrets/manifest.json            — the manifest data
  - infra/aws/scripts/populate-secrets.sh  — orchestrates aws / eas using this
  - backend/tests/test_secret_manifest.py  — drift guard vs app/core/config.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

MANIFEST_PATH = Path(__file__).resolve().parent / "manifest.json"


def load_entries(path: Path = MANIFEST_PATH) -> list[dict[str, Any]]:
    """Return the list of manifest entries."""
    data = json.loads(path.read_text())
    return list(data["secrets"])


def parse_value_file(path: Path) -> dict[str, str]:
    """Parse a ``KEY=value`` value file. Values may contain ``=``; quotes/blank
    lines and ``#`` comments are ignored. Splits on the first ``=`` only."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        values[key.strip()] = val
    return values


def resolve_static(entry: dict[str, Any], env: str) -> str | None:
    """Resolve an entry's static value for ``env`` (env-specific, then ``all``)."""
    static = entry.get("static")
    if not isinstance(static, dict):
        return None
    if env in static:
        return str(static[env])
    if "all" in static:
        return str(static["all"])
    return None


def env_var_name(entry: dict[str, Any]) -> str:
    """The environment-variable name an entry maps to on its side."""
    if entry["side"] == "backend":
        return str(entry["backend_env"])
    return str(entry["name"])  # mobile uses the canonical name


def for_side(entries: list[dict[str, Any]], side: str) -> list[dict[str, Any]]:
    return [e for e in entries if e["side"] == side]


def cmd_template(entries: list[dict[str, Any]]) -> int:
    print("# Fill in real values. This file holds SECRETS — never commit it.")
    for entry in entries:
        if entry.get("secret"):
            print(f"{entry['name']}=")
    return 0


def cmd_validate(entries: list[dict[str, Any]], env: str, values: dict[str, str]) -> int:
    # `optional: true` lets an entry be blank without failing validation —
    # used for vars that only apply to one deploy target.
    # When blank, the entry is skipped by `cloud`/`dotenv` too.
    missing = [
        e["name"]
        for e in entries
        if e.get("secret")
        and not e.get("optional")
        and not values.get(e["name"], "").strip()
    ]
    if missing:
        sys.stderr.write(
            f"Missing values for {len(missing)} secret(s) required for '{env}':\n"
        )
        for name in missing:
            sys.stderr.write(f"  - {name}\n")
        return 1
    return 0


def cmd_dotenv(
    entries: list[dict[str, Any]], env: str, side: str, values: dict[str, str]
) -> int:
    for entry in for_side(entries, side):
        if entry.get("secret"):
            val = values.get(entry["name"], "")
            if not val:
                continue  # dev is lenient: skip unset secrets, code defaults apply
        else:
            resolved = resolve_static(entry, env)
            if resolved is None:
                continue
            val = resolved
        print(f"{env_var_name(entry)}={val}")
    return 0


def cmd_cloud(
    entries: list[dict[str, Any]], env: str, side: str, values: dict[str, str]
) -> int:
    """Emit TSV rows: ``kind \t env_var \t value``.

    kind is ``secret`` or ``static``."""
    for entry in for_side(entries, side):
        name = env_var_name(entry)
        if entry.get("secret"):
            val = values.get(entry["name"], "")
            if not val.strip():
                if entry.get("optional"):
                    continue
                sys.stderr.write(f"Missing value for secret '{entry['name']}'\n")
                return 1
            print(f"secret\t{name}\t{val}")
        else:
            resolved = resolve_static(entry, env)
            if resolved is None:
                continue
            print(f"static\t{name}\t{resolved}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("template")

    p_validate = sub.add_parser("validate")
    p_validate.add_argument("env")
    p_validate.add_argument("values")

    p_dotenv = sub.add_parser("dotenv")
    p_dotenv.add_argument("env")
    p_dotenv.add_argument("side", choices=["backend", "mobile"])
    p_dotenv.add_argument("values")

    p_cloud = sub.add_parser("cloud")
    p_cloud.add_argument("env")
    p_cloud.add_argument("side", choices=["backend", "mobile"])
    p_cloud.add_argument("values")

    args = parser.parse_args(argv)
    entries = load_entries()

    if args.cmd == "template":
        return cmd_template(entries)
    if args.cmd == "validate":
        return cmd_validate(entries, args.env, parse_value_file(Path(args.values)))
    if args.cmd == "dotenv":
        return cmd_dotenv(
            entries, args.env, args.side, parse_value_file(Path(args.values))
        )
    if args.cmd == "cloud":
        return cmd_cloud(
            entries, args.env, args.side, parse_value_file(Path(args.values))
        )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
