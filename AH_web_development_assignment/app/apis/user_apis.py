from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.databases import async_get_db
from app.repositories.user_repository import UserRepository
from app.schemas.user import SignupRequest, UserResponse
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
