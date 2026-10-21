"""One-off provisioning of the least-privilege app role + its database.

Runs INSIDE the VPC as the RDS master user — the Postgres instance is in
private subnets (no public endpoint), so this executes via a one-off ECS
RunTask using the backend image. Idempotent: safe to re-run.

Least-privilege role pattern: the app role has no server-level privileges but
*owns* its one database (and that database's ``public`` schema), so the app and
its Alembic migrations both run under it.

Env vars:
  ADMIN_DSN     libpq DSN for the server admin, pointed at a maintenance DB
                (e.g. ``host=... port=5432 dbname=postgres user=mihadmin
                password=*** sslmode=require``)
  APP_ROLE      app login role to create (e.g. ``madeithome``)
  APP_PASSWORD  password to set on the app role (must match DATABASE_URL)
  APP_DB        database the app role should own (e.g. ``made_it_home``)

Related: infra/aws/scripts/init-db.sh (driver), infra/aws/scripts/bootstrap.sh
         (provisioner), infra/aws/primary/ (VPC + private RDS networking).
"""

from __future__ import annotations

import os
import sys

import psycopg2  # type: ignore[import-untyped]
from psycopg2 import sql  # type: ignore[import-untyped]


def _require(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        sys.exit(f"init_db: missing required env var {name}")
    return value


def main() -> int:
    admin_dsn = _require("ADMIN_DSN")
    role = _require("APP_ROLE")
    password = _require("APP_PASSWORD")
    app_db = _require("APP_DB")

    # Maintenance connection as the server admin. Autocommit is required:
    # CREATE DATABASE cannot run inside a transaction block.
    conn = psycopg2.connect(admin_dsn)
    conn.autocommit = True
    cur = conn.cursor()

    # 1) App login role — create, or reset its password if it already exists.
    #    No server-level attributes (no CREATEDB/CREATEROLE/SUPERUSER).
    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
    verb = "ALTER" if cur.fetchone() else "CREATE"
    cur.execute(
        sql.SQL("{} ROLE {} WITH LOGIN PASSWORD {}").format(
            sql.SQL(verb), sql.Identifier(role), sql.Literal(password)
        )
    )
    print(f"init_db: {verb.lower()}d role {role!r}")

    # Admin must be a member of the app role to set it as a database owner
    # (no-op if already a member, e.g. PG16 auto-grants this to the creator).
    cur.execute(sql.SQL("GRANT {} TO CURRENT_USER").format(sql.Identifier(role)))

    # 2) Application database owned by the app role.
    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (app_db,))
    if cur.fetchone():
        cur.execute(
            sql.SQL("ALTER DATABASE {} OWNER TO {}").format(
                sql.Identifier(app_db), sql.Identifier(role)
            )
        )
        print(f"init_db: database {app_db!r} exists — owner set to {role!r}")
    else:
        cur.execute(
            sql.SQL("CREATE DATABASE {} OWNER {}").format(
                sql.Identifier(app_db), sql.Identifier(role)
            )
        )
        print(f"init_db: created database {app_db!r} owned by {role!r}")

    cur.close()
    conn.close()

    # 3) The app role owns the public schema in its database, so migrations
    #    (run as the app role) can create objects there.
    app_conn = psycopg2.connect(admin_dsn, dbname=app_db)
    app_conn.autocommit = True
    app_cur = app_conn.cursor()
    app_cur.execute(
        sql.SQL("ALTER SCHEMA public OWNER TO {}").format(sql.Identifier(role))
    )
    app_cur.close()
    app_conn.close()
    print(f"init_db: schema public in {app_db!r} now owned by {role!r}")
    print("init_db: done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
