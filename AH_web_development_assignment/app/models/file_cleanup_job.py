from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.databases import Base
from app.core.db.models import TimestampMixin


class FileCleanupJob(TimestampMixin, Base):
    """커밋 후 지워야 할 파일 1개 = 1행 (5일차 설계 6-4, D18)

    - 자원 삭제·이미지 교체와 같은 트랜잭션으로 저장해 파일 경로가 유실되지 않게 한다.
    - 삭제된 자원을 가리키므로 외래키(CASCADE)를 두지 않는다.
    - 파일을 지우면 status=done으로 바꾸고 경로(file_path)는 비운다.
    """

    __tablename__ = "file_cleanup_jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # 어떤 자원 때문에 생긴 작업인지 (patient / medical_record / xray_image)
    target_type: Mapped[str] = mapped_column(String(30), nullable=False)
    target_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # 파일 종류 (xray / heatmap). 종류별 비공개 저장 폴더 기준 상대 경로를 해석한다.
    file_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    file_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    # pending: 삭제 대기·재시도 중 / done: 삭제 완료 / invalid: 저장 폴더 밖 경로라 삭제하지 않음
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_file_cleanup_jobs_status_next_attempt_at", "status", "next_attempt_at"),
        Index("ix_file_cleanup_jobs_target", "target_type", "target_id"),
    )
