from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db.databases import Base
from app.core.db.models import TimestampMixin


class AIAnalysisResult(TimestampMixin, Base):
    """AI 폐렴 판독 결과"""

    __tablename__ = "ai_analysis_results"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    record_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("medical_records.id", ondelete="CASCADE"), nullable=False, comment="진료 기록 ID"
    )
    is_pneumonia: Mapped[bool] = mapped_column(Boolean, nullable=False, comment="폐렴 여부")
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, comment="판독 신뢰도 (%)")
    heatmap_url: Mapped[str] = mapped_column(String(255), nullable=False, comment="히트맵 이미지 경로")
    ai_model: Mapped[str] = mapped_column(String(50), nullable=False, comment="사용한 AI 모델명")
    record: Mapped["MedicalRecord"] = relationship(
        back_populates="ai_analysis_results"
    )
