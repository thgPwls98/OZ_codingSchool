from sqlalchemy import BigInteger, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db.databases import Base
from app.core.db.models import TimestampMixin


class MedicalRecord(TimestampMixin, Base):
    __tablename__ = "medical_records"
    # 환자별 진료기록 목록을 최신순으로 조회한다 (설계 문서 8절)
    __table_args__ = (
        Index("ix_medical_records_patient_id_created_at", "patient_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # 환자가 삭제되면 진료기록도 함께 삭제한다 (D4)
    patient_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False
    )
    chart_number: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    symptoms: Mapped[str] = mapped_column(Text, nullable=False)

    patient: Mapped["Patient"] = relationship(back_populates="medical_records")
    # X-Ray 이미지·AI 결과는 DB의 ON DELETE CASCADE가 지운다 (D4, Patient.medical_records 주석 참고)
    xray_images: Mapped[list["XrayImage"]] = relationship(
        back_populates="record", cascade="all, delete-orphan", passive_deletes=True
    )
    ai_analysis_results: Mapped[list["AIAnalysisResult"]] = relationship(
        back_populates="record", cascade="all, delete-orphan", passive_deletes=True
    )
