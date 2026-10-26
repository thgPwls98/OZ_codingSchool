from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.apis.auth import _delete_refresh_cookie
from app.core.db.databases import async_get_db
from app.core.dependencies import CurrentUser
from app.repositories.user_repository import UserRepository
from app.schemas.user import ChangePasswordRequest, SignupRequest, UpdateMeRequest, UserResponse
from app.services.user_service import UserService

router = APIRouter(prefix="/api/v1/users", tags=["users"])


def get_user_service(db: Annotated[AsyncSession, Depends(async_get_db)]) -> UserService:
    return UserService(UserRepository(db))


# REQ-USER-001 회원가입
@router.post(
    "/signup",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="회원가입",
    responses={
        409: {"description": "이메일 또는 휴대폰 번호 중복"},
        422: {"description": "필수 항목 누락, 형식·길이 오류, 허용되지 않은 입력"},
    },
)
async def signup(
    body: SignupRequest,
    service: Annotated[UserService, Depends(get_user_service)],
):
    return await service.signup(body)


# ===== 마이페이지 (팀원 4) =====
# 본인은 토큰의 user_id로만 판별한다. (경로·본문으로 회원 ID를 받지 않는다)

# REQ-USER-006 내 정보 조회
@router.get(
    "/me",
    response_model=UserResponse,
    summary="내 정보 조회",
    responses={401: {"description": "인증 실패"}, 403: {"description": "비활성 계정"}},
)
async def get_me(current_user: CurrentUser):
    return current_user


# REQ-USER-007 내 정보 수정
@router.patch(
    "/me",
    response_model=UserResponse,
    summary="내 정보 수정 (부서·휴대폰 번호)",
    responses={
        400: {"description": "수정할 항목 없음"},
        401: {"description": "인증 실패"},
        403: {"description": "비활성 계정"},
        409: {"description": "휴대폰 번호 중복"},
        422: {"description": "null·형식 오류, 수정할 수 없는 필드 입력"},
    },
)
async def update_me(
    body: UpdateMeRequest,
    current_user: CurrentUser,
    service: Annotated[UserService, Depends(get_user_service)],
):
    return await service.update_me(current_user, body)


# REQ-USER-008 비밀번호 변경
@router.patch(
    "/me/password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="비밀번호 변경",
    responses={
        400: {"description": "기존 비밀번호 불일치 또는 새 비밀번호가 기존과 같음"},
        401: {"description": "인증 실패"},
        403: {"description": "비활성 계정"},
        422: {"description": "새 비밀번호 규칙 위반"},
    },
)
async def change_password(
    body: ChangePasswordRequest,
    response: Response,
    current_user: CurrentUser,
    service: Annotated[UserService, Depends(get_user_service)],
) -> None:
    await service.change_password(current_user, body)
    # 현재 브라우저는 다시 로그인하도록 리프레시 쿠키를 삭제한다. (설계 문서 11-3)
    _delete_refresh_cookie(response)


# REQ-USER-009 회원탈퇴
@router.delete(
    "/me",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="회원탈퇴",
    responses={
        401: {"description": "인증 실패"},
        403: {"description": "비활성 계정"},
        500: {"description": "삭제 실패 (롤백)"},
    },
)
async def delete_me(
    response: Response,
    current_user: CurrentUser,
    service: Annotated[UserService, Depends(get_user_service)],
) -> None:
    await service.delete_me(current_user)
    _delete_refresh_cookie(response)
