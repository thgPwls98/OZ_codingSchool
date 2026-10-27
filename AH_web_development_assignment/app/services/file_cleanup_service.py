"""파일 정리 작업 공통 서비스 (5일차 설계 6-4, D18)

환자 삭제·진료기록 삭제·이미지 교체에서 같은 방식으로 쓴다.

    cleanup = FileCleanupService(db)
    # 1) 잠금 → 경로 수집 → DB 변경과 함께 작업을 세션에 추가 (commit은 호출한 서비스)
    jobs = cleanup.enqueue(TARGET_PATIENT, patient.id, [(FILE_KIND_XRAY, path), ...])
    await db.commit()
    # 2) commit 이후 실제 파일 삭제
    if not await cleanup.run(jobs):
        raise cleanup_incomplete_error()   # 500, DB 변경은 이미 완료됨

DELETE 재요청이면 자원을 찾기 전에 resume(target_type, target_id)로 미완료 작업을 먼저 이어 한다.
"""

import logging
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.file_storage import delete_stored_file
from app.models.file_cleanup_job import FileCleanupJob
from app.repositories.file_cleanup_repository import (
    STATUS_DONE,
    STATUS_INVALID,
    STATUS_PENDING,
    FileCleanupRepository,
)

logger = logging.getLogger(__name__)

# 작업 대상 종류 (target_type)
TARGET_PATIENT = "patient"
TARGET_MEDICAL_RECORD = "medical_record"
TARGET_XRAY_IMAGE = "xray_image"

CLEANUP_INCOMPLETE = "파일 정리가 완료되지 않았습니다. 상태를 다시 조회해주세요."

# 재시도 간격: 1분, 2분, 4분 ... 최대 1시간
BASE_RETRY_DELAY = timedelta(minutes=1)
MAX_RETRY_DELAY = timedelta(hours=1)
# 이 횟수 이상 실패하면 운영자 확인이 필요하다고 경고 로그를 남긴다.
ALERT_AFTER_ATTEMPTS = 5


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def cleanup_incomplete_error() -> HTTPException:
    """파일 삭제가 끝나지 않았을 때 서비스가 그대로 raise하면 되는 500 오류 (설계 6-4 ④)"""
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=CLEANUP_INCOMPLETE)


class FileCleanupService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repository = FileCleanupRepository(db)

    def enqueue(
        self, target_type: str, target_id: int, files: list[tuple[str, str]]
    ) -> list[FileCleanupJob]:
        """지울 파일을 작업으로 세션에 추가만 한다. commit은 호출한 서비스가 DB 변경과 함께 한다.

        files: [(file_kind, 상대 경로), ...]  예) [("xray", "3/abc123.png")]
        """
        jobs = [
            FileCleanupJob(
                target_type=target_type,
                target_id=target_id,
                file_kind=file_kind,
                file_path=path,
                status=STATUS_PENDING,
                attempts=0,
            )
            for file_kind, path in files
            if path
        ]
        self.repository.add_all(jobs)
        return jobs

    async def run(self, jobs: list[FileCleanupJob]) -> bool:
        """commit 이후 호출한다. 파일을 지우고 작업 상태를 저장(commit)한다.

        모두 끝나면 True, 하나라도 실패하면 False (실패한 작업은 다음 재처리 때 다시 시도)
        """
        all_done = True
        for job in jobs:
            if job.status != STATUS_PENDING:
                continue
            try:
                await delete_stored_file(job.file_kind, job.file_path)
            except ValueError:
                # 저장 폴더 밖 경로·알 수 없는 종류: 지우지 않고 더 시도하지 않는다.
                logger.error("파일 정리 작업 %s: 잘못된 경로라 삭제하지 않음", job.id)
                job.status = STATUS_INVALID
                job.file_path = None
            except OSError:
                all_done = False
                self._schedule_retry(job)
            else:
                job.status = STATUS_DONE
                job.file_path = None  # 완료한 작업의 경로는 정리한다 (설계 6-4 ⑥)
        await self.db.commit()
        return all_done

    async def resume(self, target_type: str, target_id: int) -> bool | None:
        """같은 자원의 미완료 작업을 이어서 처리한다 (DELETE 재요청용, 설계 6-4 ⑤)

        미완료 작업이 없으면 None, 모두 끝나면 True, 다시 실패하면 False
        """
        jobs = await self.repository.list_pending_for_target(target_type, target_id)
        if not jobs:
            return None
        return await self.run(jobs)

    async def retry_pending(self, limit: int = 100) -> int:
        """재시도 시각이 된 미완료 작업을 처리하고, 이번에 완료한 개수를 돌려준다 (주기적 재처리용)"""
        jobs = await self.repository.list_due(_utcnow(), limit)
        if not jobs:
            return 0
        await self.run(jobs)
        return sum(1 for job in jobs if job.status != STATUS_PENDING)

    async def record_orphan(self, target_type: str, target_id: int, files: list[tuple[str, str]]) -> None:
        """등록 롤백 후 새 파일 삭제까지 실패했을 때, 별도 트랜잭션으로 정리 작업만 남긴다 (설계 6-4 ⑥)

        호출 전에 원래 트랜잭션은 롤백되어 있어야 한다. 여기서 실패해도 원래 오류 응답을 막지 않는다.
        """
        try:
            self.enqueue(target_type, target_id, files)
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            logger.exception("고아 파일 정리 작업 기록 실패 (대상 %s %s)", target_type, target_id)

    def _schedule_retry(self, job: FileCleanupJob) -> None:
        job.attempts += 1
        delay = min(BASE_RETRY_DELAY * (2 ** (job.attempts - 1)), MAX_RETRY_DELAY)
        job.next_attempt_at = _utcnow() + delay
        log = logger.error if job.attempts >= ALERT_AFTER_ATTEMPTS else logger.warning
        # 경로·환자 정보는 로그에 남기지 않는다 (설계 7-5)
        log("파일 정리 작업 %s 삭제 실패 (%s회째)", job.id, job.attempts)
