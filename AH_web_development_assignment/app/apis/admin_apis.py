from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BeforeValidator

from app.apis.user_apis import get_user_service
from app.core.dependencies import AdminUser
from app.models.enums import Department
from app.schemas.user import RoleChangeRequest, UserResponse
from app.services.user_service import UserService

router = APIRouter(prefix="/api/v1/admin/users", tags=["admin"])


def strip_query(value: object) -> object:
    return value.strip() if isinstance(value, str) else value


SearchQuery = Annotated[str, BeforeValidator(strip_query), Query(max_length=255)]
UserServiceDependency = Annotated[UserService, Depends(get_user_service)]


@router.get("", response_model=list[UserResponse], summary="관리자 회원 목록 조회")
async def list_users(
    current_user: AdminUser,
    service: UserServiceDependency,
    query: SearchQuery = "",
    department: Department | None = None,
):
    return await service.list_users(query, department)


@router.patch("/role", response_model=UserResponse, summary="회원 권한 변경")
async def change_role(
    body: RoleChangeRequest,
    current_user: AdminUser,
    service: UserServiceDependency,
):
    return await service.change_role(current_user.id, body)
