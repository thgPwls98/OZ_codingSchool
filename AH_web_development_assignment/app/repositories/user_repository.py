from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.enums import Department, Role


class UserRepository:
    """users 테이블에 접근하는 DB 함수 모음."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, user_id: int) -> User | None:
        return await self.db.get(User, user_id)

    async def list_users(
        self, query: str = "", department: Department | None = None
    ) -> list[User]:
        statement = select(User)
        if query:
            # 검색어의 %와 _도 와일드카드가 아닌 일반 문자로 검색한다.
            statement = statement.where(
                User.email.icontains(query, autoescape=True)
                | User.name.icontains(query, autoescape=True)
            )
        if department is not None:
            statement = statement.where(User.department == department)
        result = await self.db.execute(statement.order_by(User.id.asc()))
        return list(result.scalars().all())

    async def update_role(self, user: User, new_role: Role) -> User:
        user.role = new_role
        try:
            await self.db.commit()
            await self.db.refresh(user)
        except Exception:
            await self.db.rollback()
            raise
        return user

    async def get_by_email(self, email: str) -> User | None:
        result = await self.db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def get_by_phone_number(self, phone_number: str) -> User | None:
        result = await self.db.execute(select(User).where(User.phone_number == phone_number))
        return result.scalar_one_or_none()

    async def create(self, user: User) -> User:
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def save(self, user: User) -> User:
        """이미 조회한 사용자 객체의 변경 사항을 저장한다."""
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def delete(self, user: User) -> None:
        # 업로드한 X-ray의 uploader_id는 같은 트랜잭션에서 NULL로 바뀐다. (ON DELETE SET NULL)
        await self.db.delete(user)
        await self.db.commit()
