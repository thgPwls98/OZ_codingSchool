from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.databases import Base


class AIAnalysisResult(Base):
    """AI 폐렴 판독 결과"""

    __tablename__ = "ai_analysis_results"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    record_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("medical_records.id"), nullable=False, comment="진료 기록 ID"
    )
    is_pneumonia: Mapped[bool] = mapped_column(Boolean, nullable=False, comment="폐렴 여부")
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, comment="판독 신뢰도 (%)")
    heatmap_url: Mapped[str] = mapped_column(String(255), nullable=False, comment="히트맵 이미지 경로")
    ai_model: Mapped[str] = mapped_column(String(50), nullable=False, comment="사용한 AI 모델명")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), comment="판독 일시"
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, onupdate=func.now(), comment="수정 일시"
    )
