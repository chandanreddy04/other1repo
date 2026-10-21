"""Tests for the deletion-scoped JWT used by the web /account/delete flow.

Related:
- app/services/account_deletion.py (mint_deletion_token, decode_deletion_token)
- docs/account-deletion-plan.md (web deletion path)
"""

import time
import uuid
from datetime import UTC, datetime, timedelta

import jwt

from app.core.config import settings
from app.services.account_deletion import (
    DELETION_TOKEN_TTL_MINUTES,
    decode_deletion_token,
    mint_deletion_token,
)


class TestDeletionTokenRoundtrip:
    def test_decode_returns_original_user_id(self):
        user_id = uuid.uuid4()
        token = mint_deletion_token(user_id)
        assert decode_deletion_token(token) == user_id

    def test_returns_none_for_garbage(self):
        assert decode_deletion_token("not-a-jwt") is None

    def test_rejects_access_token(self):
        """An access_token must NOT be usable as a deletion token —
        otherwise stealing a regular session token would unlock the
        destructive deletion endpoint."""
        from app.core.security import create_access_token

        user_id = uuid.uuid4()
        access = create_access_token(str(user_id))
        assert decode_deletion_token(access) is None

    def test_rejects_expired_token(self):
        """Issued in the past with negative TTL — decode must refuse."""
        expire = datetime.now(UTC) - timedelta(minutes=1)
        token = jwt.encode(
            {"sub": str(uuid.uuid4()), "exp": expire, "type": "delete"},
            settings.SECRET_KEY,
            algorithm=settings.ALGORITHM,
        )
        assert decode_deletion_token(token) is None

    def test_rejects_wrong_type_field(self):
        token = jwt.encode(
            {
                "sub": str(uuid.uuid4()),
                "exp": datetime.now(UTC) + timedelta(minutes=5),
                "type": "magic",
            },
            settings.SECRET_KEY,
            algorithm=settings.ALGORITHM,
        )
        assert decode_deletion_token(token) is None

    def test_rejects_non_uuid_subject(self):
        token = jwt.encode(
            {
                "sub": "not-a-uuid",
                "exp": datetime.now(UTC) + timedelta(minutes=5),
                "type": "delete",
            },
            settings.SECRET_KEY,
            algorithm=settings.ALGORITHM,
        )
        assert decode_deletion_token(token) is None

    def test_token_expires_around_configured_ttl(self):
        """Sanity check the TTL constant is reflected in the issued
        claim — guards against accidentally changing the policy by
        editing one but not the other."""
        token = mint_deletion_token(uuid.uuid4())
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        now_ts = int(time.time())
        expected_exp = now_ts + DELETION_TOKEN_TTL_MINUTES * 60
        # within 5 seconds of expected (clock skew + test exec time)
        assert abs(payload["exp"] - expected_exp) < 5
