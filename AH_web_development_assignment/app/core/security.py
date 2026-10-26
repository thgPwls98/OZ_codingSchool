from datetime import UTC, datetime, timedelta
from typing import Literal

import jwt

from app.core.config import settings

TokenType = Literal["access", "refresh"]


# ---------------------------------------------------------------------------
# JWT 토큰 (NFR-USER-001)
# - payload에는 사용자 식별 정보로 user_id만 넣는다.
# - exp(만료), iat(발급), token_type(access/refresh)은 검증용 메타데이터다.
# ---------------------------------------------------------------------------
def _create_token(user_id: int, token_type: TokenType, expires_delta: timedelta) -> str:
    now = datetime.now(UTC)
    payload = {
        "user_id": user_id,
        "token_type": token_type,
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_access_token(user_id: int) -> str:
    """유효기간 30분의 액세스 토큰을 만든다."""
    return _create_token(
        user_id, "access", timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )


def create_refresh_token(user_id: int) -> str:
    """유효기간 7일의 리프레시 토큰을 만든다."""
    return _create_token(
        user_id, "refresh", timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    )


def decode_token(token: str, expected_type: TokenType) -> int | None:
    """토큰을 검증하고 user_id를 돌려준다.

    서명 위조, 만료, 토큰 종류 불일치(access ↔ refresh)이면 None을 돌려준다.
    """
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
    except jwt.InvalidTokenError:
        return None

    if payload.get("token_type") != expected_type:
        return None

    user_id = payload.get("user_id")
    if not isinstance(user_id, int):
        return None
    return user_id
