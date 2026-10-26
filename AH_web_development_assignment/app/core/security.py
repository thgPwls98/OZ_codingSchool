"""인증 공통 기능 (팀원 1).

- 비밀번호 해싱: hash_password, verify_password
  → 회원가입(1번), 로그인(2번), 비밀번호 변경(4번)에서 사용
- JWT: create_access_token, create_refresh_token, decode_token
  → 로그인·토큰 재발급(2번), 로그인 확인 의존성에서 사용
"""

from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any

import jwt
from jwt import InvalidTokenError
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

from app.core.config import settings

__all__ = [
    "TokenType",
    "InvalidTokenError",
    "hash_password",
    "verify_password",
    "create_access_token",
    "create_refresh_token",
    "decode_token",
]


# ===== 비밀번호 해싱 (Argon2) =====
password_hash = PasswordHash((Argon2Hasher(),))


def hash_password(plain_password: str) -> str:
    """비밀번호 원문을 Argon2 해시 문자열로 변환한다. (DB의 hashed_password에 저장)"""
    return password_hash.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """입력한 비밀번호가 저장된 해시와 일치하는지 확인한다."""
    return password_hash.verify(plain_password, hashed_password)


# ===== JWT =====
class TokenType(str, Enum):
    ACCESS = "access"
    REFRESH = "refresh"


def _create_token(user_id: int, token_type: TokenType, expires_delta: timedelta) -> str:
    # payload에는 개인정보 중 user_id만 넣고, 검증용 메타데이터(exp, iat, token_type)를 함께 넣는다.
    now = datetime.now(UTC)
    payload = {
        "user_id": user_id,
        "exp": now + expires_delta,
        "iat": now,
        "token_type": token_type.value,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_access_token(user_id: int) -> str:
    """Access Token(기본 30분)을 만든다. 응답 JSON으로 전달한다."""
    return _create_token(
        user_id, TokenType.ACCESS, timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )


def create_refresh_token(user_id: int) -> str:
    """Refresh Token(기본 7일)을 만든다. HttpOnly 쿠키로만 전달한다."""
    return _create_token(
        user_id, TokenType.REFRESH, timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    )


def decode_token(token: str, expected_type: TokenType) -> dict[str, Any]:
    """토큰을 해독·검증하고 payload를 반환한다.

    서명 위조, 만료, 필수 항목 누락, 토큰 종류 불일치(access 자리에 refresh 등)이면
    InvalidTokenError를 발생시킨다. 호출하는 쪽에서 잡아서 401로 응답한다.

    사용 예:
        try:
            payload = decode_token(token, TokenType.ACCESS)
        except InvalidTokenError:
            raise HTTPException(status_code=401, detail="인증 정보가 유효하지 않습니다.",
                                headers={"WWW-Authenticate": "Bearer"})
        user_id = payload["user_id"]
    """
    payload = jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
        options={"require": ["exp", "iat", "user_id", "token_type"]},
    )
    if payload.get("token_type") != expected_type.value:
        raise InvalidTokenError("토큰 종류가 올바르지 않습니다.")
    if not isinstance(payload.get("user_id"), int):
        raise InvalidTokenError("user_id가 올바르지 않습니다.")
    return payload
