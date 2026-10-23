from sqlalchemy import BigInteger, Enum, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.databases import Base
from app.core.db.models import TimestampMixin
from app.models.enums import Gender


class Patient(TimestampMixin, Base):
    """환자 정보 테이블 (created_at, updated_at은 TimestampMixin에서 상속)"""

    __tablename__ = "patients"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(30), nullable=False)
    age: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    gender: Mapped[Gender | None] = mapped_column(Enum(Gender, name="gender"), nullable=True)
    phone: Mapped[str] = mapped_column(String(11), nullable=False)  # 하이픈 없이 01012345678
