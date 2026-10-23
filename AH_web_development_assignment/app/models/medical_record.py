# app/models/medical_record.py
from sqlalchemy import CHAR, Float, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db.models import Base


class MedicalRecord(Base):
    __tablename__ = "medical_records"

    id: Mapped[int] = mapped_column(primary_key=True)

    # 회원 탈퇴 시 해당 회원의 진료 기록도 함께 삭제
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    # 한글 정보 → CHAR, NULL 허용
    patient_name: Mapped[str | None] = mapped_column(CHAR(20), comment="환자 이름")
    gender: Mapped[str | None] = mapped_column(CHAR(1), comment="성별 (남/여)")
    has_prescription: Mapped[str | None] = mapped_column(CHAR(1), comment="처방 약 유무 (유/무)")
    admission_checked: Mapped[str | None] = mapped_column(CHAR(1), comment="입원 기록 확인 (유/무)")

    # 숫자 정보 → FLOAT, NULL 허용
    patient_number: Mapped[float | None] = mapped_column(Float, comment="환자 관리 번호")
    age: Mapped[float | None] = mapped_column(Float, comment="나이")

    user: Mapped["User"] = relationship(back_populates="medical_records")
