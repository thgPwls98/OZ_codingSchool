from sqlalchemy import BigInteger, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db.databases import Base
from app.core.db.models import TimestampMixin
from app.models.enums import GENDER_ENUM, Gender


class Patient(TimestampMixin, Base):
    """환자 정보 테이블 (created_at, updated_at은 TimestampMixin에서 상속)"""

    __tablename__ = "patients"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(30), nullable=False)
    age: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    gender: Mapped[Gender | None] = mapped_column(GENDER_ENUM, nullable=True)
    phone: Mapped[str] = mapped_column(String(11), nullable=False)  # 하이픈 없이 01012345678
    medical_records: Mapped[list["MedicalRecord"]] = relationship(
        back_populates="patient"
    )
