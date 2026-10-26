from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.core.security import hash_password, verify_password
from app.models.enums import Department, Role
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.user import ChangePasswordRequest, RoleChangeRequest, SignupRequest, UpdateMeRequest

EMAIL_DUPLICATED = "이미 사용 중인 이메일입니다."
PHONE_DUPLICATED = "이미 사용 중인 휴대폰 번호입니다."
NOTHING_TO_UPDATE = "수정할 항목을 하나 이상 입력하세요."
WRONG_CURRENT_PASSWORD = "기존 비밀번호가 일치하지 않습니다."
SAME_AS_CURRENT_PASSWORD = "새 비밀번호는 기존 비밀번호와 달라야 합니다."
DELETE_FAILED = "잠시 후 다시 시도해주세요."


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

    # ===== 마이페이지 (팀원 4) =====
    # user는 인증 의존성(get_current_user)이 토큰의 user_id로 조회한 본인 객체다.

    # REQ-USER-007 내 정보 수정
    async def update_me(self, user: User, data: UpdateMeRequest) -> User:
        # 1. 보낸 필드만 수정 (생략한 필드는 유지)
        updates = data.model_dump(exclude_unset=True)
        if not updates:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=NOTHING_TO_UPDATE)

        # 2. 다른 회원이 쓰는 번호인지 확인 (본인이 쓰던 번호는 허용)
        phone_number = updates.get("phone_number")
        if phone_number and phone_number != user.phone_number:
            if await self.repository.get_by_phone_number(phone_number):
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=PHONE_DUPLICATED)

        for field, value in updates.items():
            setattr(user, field, value)
        try:
            return await self.repository.save(user)
        except IntegrityError as e:
            # 동시에 같은 번호로 수정한 경우: DB UNIQUE 제약 위반 처리
            await self.repository.db.rollback()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=PHONE_DUPLICATED) from e

    # REQ-USER-008 비밀번호 변경
    async def change_password(self, user: User, data: ChangePasswordRequest) -> None:
        if not verify_password(data.current_password, user.hashed_password):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=WRONG_CURRENT_PASSWORD)
        if verify_password(data.new_password, user.hashed_password):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=SAME_AS_CURRENT_PASSWORD)

        user.hashed_password = hash_password(data.new_password)
        await self.repository.save(user)

    # REQ-USER-009 회원탈퇴
    async def delete_me(self, user: User) -> None:
        # 사용자 행만 물리 삭제하고 X-ray·진료 데이터는 보존한다. 실패 시 롤백 후 500.
        try:
            await self.repository.delete(user)
        except SQLAlchemyError as e:
            await self.repository.db.rollback()
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=DELETE_FAILED) from e
