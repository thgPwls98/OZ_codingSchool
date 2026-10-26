from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db.databases import async_get_db
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,  # 팀원 1(공통 기반) 담당 함수
)
from app.repositories.user_repository import UserRepository
from app.schemas.auth import LoginResponse, TokenResponse
from app.schemas.user import UserResponse

router = APIRouter(prefix="/api/v1/users", tags=["auth"])

REFRESH_COOKIE_NAME = "refresh_token"
REFRESH_COOKIE_PATH = "/api/v1/users"
ACCESS_TOKEN_EXPIRE_SECONDS = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
REFRESH_TOKEN_EXPIRE_SECONDS = settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60


# ---------------------------------------------------------------------------
# 쿠키 도우미: 발급과 삭제에 같은 속성(Path 등)을 써야 브라우저가 쿠키를 지운다.
# ---------------------------------------------------------------------------
def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=token,
        max_age=REFRESH_TOKEN_EXPIRE_SECONDS,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
    )


def _delete_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
    )


def _error_and_clear_cookie(status_code: int, detail: str) -> JSONResponse:
    """오류 응답을 보내면서 리프레시 쿠키도 삭제한다 (설계 문서 5-3)"""
    response = JSONResponse(status_code=status_code, content={"detail": detail})
    _delete_refresh_cookie(response)
    return response


# ---------------------------------------------------------------------------
# 로그인 (REQ-USER-002, NFR-USER-001) - 설계 문서 4절
# ---------------------------------------------------------------------------
@router.post("/login", response_model=LoginResponse)
async def login(
    response: Response,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> LoginResponse:
    email = form_data.username.strip().lower()  # 회원가입과 같은 방식으로 정규화
    user = await UserRepository(db).get_by_email(email)

    # 이메일과 비밀번호 중 무엇이 틀렸는지 구분하지 않는다.
    if user is None or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="이메일 또는 비밀번호가 일치하지 않습니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="비활성화된 사용자입니다.",
        )

    _set_refresh_cookie(response, create_refresh_token(user.id))
    response.headers["Cache-Control"] = "no-store"

    return LoginResponse(
        access_token=create_access_token(user.id),
        expires_in=ACCESS_TOKEN_EXPIRE_SECONDS,
        user=UserResponse.model_validate(user),
    )


# ---------------------------------------------------------------------------
# 액세스 토큰 재발급 (NFR-USER-001) - 설계 문서 5절
# ---------------------------------------------------------------------------
@router.post(
    "/refresh",
    response_model=TokenResponse,
    responses={401: {"description": "다시 로그인 필요"}, 403: {"description": "비활성 계정"}},
)
async def refresh(
    response: Response,
    db: Annotated[AsyncSession, Depends(async_get_db)],
    refresh_token: Annotated[str | None, Cookie()] = None,
):
    user_id = decode_token(refresh_token, "refresh") if refresh_token else None
    if user_id is None:
        return _error_and_clear_cookie(status.HTTP_401_UNAUTHORIZED, "다시 로그인해주세요.")

    user = await UserRepository(db).get_by_id(user_id)
    if user is None:  # 탈퇴한 사용자
        return _error_and_clear_cookie(status.HTTP_401_UNAUTHORIZED, "다시 로그인해주세요.")
    if not user.is_active:
        return _error_and_clear_cookie(status.HTTP_403_FORBIDDEN, "비활성화된 사용자입니다.")

    # 리프레시 쿠키는 갱신하지 않는다. 최초 발급 시점부터 7일 유지 (설계 문서 5-3)
    response.headers["Cache-Control"] = "no-store"
    return TokenResponse(
        access_token=create_access_token(user.id),
        expires_in=ACCESS_TOKEN_EXPIRE_SECONDS,
    )


# ---------------------------------------------------------------------------
# 로그아웃 (REQ-USER-003) - 설계 문서 6절
# ---------------------------------------------------------------------------
@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response) -> None:
    # 쿠키가 없거나 만료된 경우에도 똑같이 204로 응답한다.
    _delete_refresh_cookie(response)
