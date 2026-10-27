from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.file_cleanup_job import FileCleanupJob

STATUS_PENDING = "pending"
STATUS_DONE = "done"
STATUS_INVALID = "invalid"


class FileCleanupRepository:
    """file_cleanup_jobs 테이블에 접근하는 DB 함수 모음.

    팀 규칙: 저장소는 commit하지 않는다. commit은 서비스가 DB 변경과 함께 한다.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    def add_all(self, jobs: list[FileCleanupJob]) -> None:
        self.db.add_all(jobs)

    async def flush(self) -> None:
        await self.db.flush()

    async def list_pending_for_target(self, target_type: str, target_id: int) -> list[FileCleanupJob]:
        result = await self.db.execute(
            select(FileCleanupJob)
            .where(
                FileCleanupJob.target_type == target_type,
                FileCleanupJob.target_id == target_id,
                FileCleanupJob.status == STATUS_PENDING,
            )
            .order_by(FileCleanupJob.id)
        )
        return list(result.scalars().all())

    async def list_due(self, now: datetime, limit: int) -> list[FileCleanupJob]:
        """재시도 시각이 된 미완료 작업 (주기적 재처리용)"""
        result = await self.db.execute(
            select(FileCleanupJob)
            .where(
                FileCleanupJob.status == STATUS_PENDING,
                (FileCleanupJob.next_attempt_at.is_(None)) | (FileCleanupJob.next_attempt_at <= now),
            )
            .order_by(FileCleanupJob.id)
            .limit(limit)
        )
        return list(result.scalars().all())
