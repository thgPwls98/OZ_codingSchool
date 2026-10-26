from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError

from app.core.security import hash_password
from app.models.enums import Department, Role
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.user import RoleChangeRequest, SignupRequest

EMAIL_DUPLICATED = "이미 사용 중인 이메일입니다."
PHONE_DUPLICATED = "이미 사용 중인 휴대폰 번호입니다."


class UserService:
    def __init__(self, repository: UserRepository):
        self.repository = repository

    async def list_users(
        self, query: str = "", department: Department | None = None
    ) -> list[User]:
        return await self.repository.list_users(query, department)

    async def change_role(self, current_user_id: int, data: RoleChangeRequest) -> User:
        if current_user_id == data.user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="본인의 권한은 변경할 수 없습니다.",
            )
        user = await self.repository.get_by_id(data.user_id)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="회원을 찾을 수 없습니다."
            )
        if user.role == data.new_role:
            return user
        return await self.repository.update_role(user, data.new_role)

    async def signup(self, data: SignupRequest) -> User:
        # 1. 중복 사전 조회
        if await self.repository.get_by_email(data.email):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=EMAIL_DUPLICATED)
        if await self.repository.get_by_phone_number(data.phone_number):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=PHONE_DUPLICATED)

        # 2. 비밀번호 해싱 후 저장 (권한은 서버에서 pending, 활성화 true로 지정)
        user = User(
            email=data.email,
            hashed_password=hash_password(data.password),
            name=data.name,
            department=data.department,
            gender=data.gender,
            phone_number=data.phone_number,
            role=Role.PENDING,
            is_active=True,
        )
        try:
            return await self.repository.create(user)
        except IntegrityError as e:
            # 동시에 같은 값으로 가입한 경우: DB UNIQUE 제약 위반 처리
            await self.repository.db.rollback()
            message = str(e.orig).lower()
            detail = PHONE_DUPLICATED if "phone_number" in message else EMAIL_DUPLICATED
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail) from e
