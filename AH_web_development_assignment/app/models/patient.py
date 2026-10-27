from sqlalchemy import BigInteger, CheckConstraint, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db.databases import Base
from app.core.db.models import TimestampMixin
from app.models.enums import GENDER_ENUM, Gender


class Patient(TimestampMixin, Base):
    """환자 정보 테이블 (created_at, updated_at은 TimestampMixin에서 상속)"""

    __tablename__ = "patients"
    # 나이는 API 검증과 별개로 DB에서도 0~150만 허용한다 (설계 문서 2-3)
    __table_args__ = (
        CheckConstraint("age BETWEEN 0 AND 150", name="ck_patients_age_range"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(30), nullable=False)
    # 나이 범위 필터용 인덱스 (설계 문서 8절)
    age: Mapped[int] = mapped_column(SmallInteger, nullable=False, index=True)
    gender: Mapped[Gender] = mapped_column(GENDER_ENUM, nullable=False)
    # 화면·users 테이블과 같은 이름을 쓴다 (D19). 하이픈 없이 01012345678
    phone_number: Mapped[str] = mapped_column(String(11), nullable=False)
    # 진료기록은 DB의 ON DELETE CASCADE가 지운다 (D4)
    # - passive_deletes=True: 불러오지 않은 자식은 ORM이 조회하지 않고 DB에 맡긴다.
    # - cascade="all, delete-orphan": 이미 불러온 자식은 외래키를 NULL로 바꾸지 않고 함께 삭제한다.
    #   (cascade 없이 passive_deletes만 두면 불러온 자식의 patient_id를 NULL로 바꾸려다 실패한다)
    medical_records: Mapped[list["MedicalRecord"]] = relationship(
        back_populates="patient", cascade="all, delete-orphan", passive_deletes=True
    )
