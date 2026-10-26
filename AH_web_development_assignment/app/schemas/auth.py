from pydantic import BaseModel

from app.schemas.user import UserResponse


class TokenResponse(BaseModel):
    """토큰 재발급 응답 (설계 문서 5-3)"""

    access_token: str
    token_type: str = "bearer"
    expires_in: int  # 만료까지 남은 시간(초). 발급 시 1800


class LoginResponse(TokenResponse):
    """로그인 응답 (설계 문서 4-3). 토큰 정보 + 로그인한 사용자 정보"""

    user: UserResponse
