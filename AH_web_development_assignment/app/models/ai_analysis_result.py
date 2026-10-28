from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, CheckConstraint, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db.databases import Base
from app.core.db.models import TimestampMixin


class AIAnalysisResult(TimestampMixin, Base):
    """AI 폐렴 판독 결과"""

    __tablename__ = "ai_analysis_results"
    __table_args__ = (
        # 같은 진료기록·같은 모델 버전의 결과는 1건만 (6일차 설계 D6). 맨 앞이 record_id라 목록 조회에도 쓰인다
        UniqueConstraint("record_id", "ai_model", "model_version", name="uq_ai_analysis_results_record_model"),
        CheckConstraint("confidence BETWEEN 0 AND 100", name="ck_ai_analysis_results_confidence_range"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    record_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("medical_records.id", ondelete="CASCADE"), nullable=False, comment="진료 기록 ID"
    )
    is_pneumonia: Mapped[bool] = mapped_column(Boolean, nullable=False, comment="폐렴 여부")
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, comment="판독 신뢰도 (%)")
    # 히트맵은 선택사항이라 없으면 NULL (6일차 설계 D4). 값은 HEATMAP_STORAGE_DIR 기준 상대 경로
    heatmap_url: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="히트맵 이미지 상대 경로")
    ai_model: Mapped[str] = mapped_column(String(50), nullable=False, comment="사용한 AI 모델명")
    # 가중치·전처리·threshold가 바뀌면 올린다. 재사용 판단에 ai_model과 함께 쓴다 (6일차 설계 D5)
    model_version: Mapped[str] = mapped_column(String(20), nullable=False, comment="모델 버전")
    record: Mapped["MedicalRecord"] = relationship(
        back_populates="ai_analysis_results"
    )
