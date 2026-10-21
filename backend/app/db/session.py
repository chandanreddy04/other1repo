import os
import ssl as ssl_module

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings

# SSL configuration for cloud Postgres providers.
#
# AWS RDS signs its server cert with an Amazon root that isn't in the
# default system trust store, so a default SSL context fails verification
# with "self-signed certificate in certificate chain". The container
# Dockerfile installs the AWS RDS global bundle at
# /etc/ssl/certs/rds-global-bundle.pem; load it when present so the
# context trusts RDS. Other providers (e.g. Neon) use roots
# already in the default store, so they work without the bundle.
_async_connect_args: dict = {}
_sync_connect_args: dict = {}

_RDS_BUNDLE = "/etc/ssl/certs/rds-global-bundle.pem"

if settings.DB_SSL_REQUIRE:
    if os.path.exists(_RDS_BUNDLE):
        _ssl_ctx = ssl_module.create_default_context(cafile=_RDS_BUNDLE)
        _sync_connect_args["sslrootcert"] = _RDS_BUNDLE
    else:
        _ssl_ctx = ssl_module.create_default_context()
    _async_connect_args["ssl"] = _ssl_ctx
    _sync_connect_args["sslmode"] = "verify-full"

# Async engine for general use
async_engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.ENVIRONMENT == "development",
    future=True,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_recycle=settings.DB_POOL_RECYCLE,
    pool_pre_ping=settings.DB_POOL_PRE_PING,
    connect_args=_async_connect_args,
)

# Async session factory
AsyncSessionLocal = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Sync engine for Alembic migrations
sync_engine = create_engine(
    settings.SYNC_DATABASE_URL,
    echo=settings.ENVIRONMENT == "development",
    connect_args=_sync_connect_args,
)

# Sync session factory for migrations
SessionLocal = sessionmaker(
    bind=sync_engine,
    autocommit=False,
    autoflush=False,
)
