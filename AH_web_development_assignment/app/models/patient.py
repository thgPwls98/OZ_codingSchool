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
    # 연쇄 삭제 (D4)
    # - passive_deletes=True: 로딩하지 않은 자식은 삭제 목적으로 조회하지 않고 DB의 ON DELETE CASCADE에 맡긴다.
    # - delete cascade: 로딩된 자식은 ORM이 함께 삭제한다.
    #   (없으면 로딩된 자식의 patient_id를 NULL로 바꾸려다 NOT NULL 제약에 걸린다)
    # - delete-orphan: 컬렉션에서 분리된 자식도 삭제한다. (부모 없는 진료기록을 남기지 않는다)
    medical_records: Mapped[list["MedicalRecord"]] = relationship(
        back_populates="patient", cascade="all, delete-orphan", passive_deletes=True
    )
