from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db.databases import Base


class XrayImage(Base):
    """흉부 X-Ray 이미지"""

    __tablename__ = "xray_images"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    record_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("medical_records.id"), nullable=False, comment="진료 기록 ID"
    )
    # 회원 탈퇴 시 NULL로 바뀐다 (X-Ray 기록은 보존)
    uploader_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="업로드한 의료진 ID",
    )
    image_url: Mapped[str] = mapped_column(String(2048), nullable=False, comment="이미지 경로")
    shooting_datetime: Mapped[datetime] = mapped_column(DateTime, nullable=False, comment="촬영 일시")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )

    record: Mapped["MedicalRecord"] = relationship(back_populates="xray_images")
    uploader: Mapped["User | None"] = relationship(back_populates="xray_images")
