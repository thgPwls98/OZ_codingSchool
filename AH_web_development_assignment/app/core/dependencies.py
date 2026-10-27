from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.databases import async_get_db
from app.core.security import decode_token
from app.models.enums import Department, Role
from app.models.user import User
from app.repositories.user_repository import UserRepository

# Swagger의 Authorize 버튼이 이 주소로 로그인해서 토큰을 받아온다.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/users/login")


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> User:
    """Authorization 헤더의 액세스 토큰으로 로그인한 회원을 찾는다 (설계 문서 1-1, 13-1)

    - 토큰 위조·만료, 리프레시 토큰 사용, 탈퇴한 회원 → 401
    - 비활성 계정 → 403
    """
    user_id = decode_token(token, "access")
    user = await UserRepository(db).get_by_id(user_id) if user_id is not None else None
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="인증 정보가 유효하지 않습니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="비활성화된 사용자입니다.",
        )
    return user


async def require_admin(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """어드민 권한을 확인한다. 권한은 매 요청마다 DB 값으로 확인한다 (설계 문서 1-2)"""
    if current_user.role != Role.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="접근 권한이 없습니다.",
        )
    return current_user


async def require_staff(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """스태프 이상(staff, admin)만 통과한다. 대기자(pending)는 403 (5일차 설계 2-2)"""
    if current_user.role not in (Role.STAFF, Role.ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="접근 권한이 없습니다.",
        )
    return current_user


async def require_medical_staff(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """어드민 또는 의료 부서 스태프만 통과한다 (5일차 설계 2-2, D2)"""
    is_admin = current_user.role == Role.ADMIN
    is_medical_staff = (
        current_user.role == Role.STAFF and current_user.department == Department.MEDICAL
    )
    if not (is_admin or is_medical_staff):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="의료진만 접근할 수 있습니다.",
        )
    return current_user


# 다른 API에서 짧게 쓰기 위한 별칭
CurrentUser = Annotated[User, Depends(get_current_user)]
AdminUser = Annotated[User, Depends(require_admin)]
StaffUser = Annotated[User, Depends(require_staff)]
MedicalStaffUser = Annotated[User, Depends(require_medical_staff)]
