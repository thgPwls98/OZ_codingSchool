"""파일 정리 작업 서비스 테스트 (5일차 설계 6-4, 12-1)

실행: python -m unittest tests.test_file_cleanup_service -v  (aiosqlite 필요)
"""

import asyncio
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import select

from app.core.config import settings
from app.core.file_storage import FILE_KIND_HEATMAP, FILE_KIND_XRAY
from app.models import FileCleanupJob
from app.services.file_cleanup_service import (
    CLEANUP_INCOMPLETE,
    TARGET_MEDICAL_RECORD,
    TARGET_PATIENT,
    FileCleanupService,
    cleanup_incomplete_error,
)
sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests 폴더의 도우미를 어떤 실행 방식으로도 불러오도록
from sqlite_db import create_test_db  # noqa: E402


class FileCleanupServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        self.xray_root = tmp / "xray"
        self.heatmap_root = tmp / "heatmap"
        for name, value in (("XRAY_STORAGE_DIR", self.xray_root), ("HEATMAP_STORAGE_DIR", self.heatmap_root)):
            p = patch.object(settings, name, str(value))
            p.start()
            self.addCleanup(p.stop)
        self.engine, self.Session = asyncio.run(create_test_db(tmp))

    def tearDown(self):
        asyncio.run(self.engine.dispose())
        self.tmp.cleanup()

    def make_file(self, root: Path, relative: str) -> Path:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
        return path

    def run_async(self, coro_fn):
        async def wrapper():
            async with self.Session() as db:
                return await coro_fn(db)
        return asyncio.run(wrapper())

    def all_jobs(self):
        async def fetch(db):
            return list((await db.execute(select(FileCleanupJob))).scalars().all())
        return self.run_async(fetch)

    # ---- 정상 흐름: enqueue → (호출한 서비스가) commit → run ----
    def test_enqueue_commit_run_deletes_files_and_marks_done(self):
        xray = self.make_file(self.xray_root, "3/a.png")
        heatmap = self.make_file(self.heatmap_root, "3/h.png")

        async def flow(db):
            cleanup = FileCleanupService(db)
            jobs = cleanup.enqueue(TARGET_PATIENT, 3, [(FILE_KIND_XRAY, "3/a.png"), (FILE_KIND_HEATMAP, "3/h.png")])
            await db.commit()  # 실제로는 DB 변경(환자 삭제 등)과 함께 commit
            return await cleanup.run(jobs)

        self.assertTrue(self.run_async(flow))
        self.assertFalse(xray.exists())
        self.assertFalse(heatmap.exists())
        self.assertFalse((self.xray_root / "3").exists())  # 빈 환자 폴더 정리
        jobs = self.all_jobs()
        self.assertEqual([j.status for j in jobs], ["done", "done"])
        self.assertTrue(all(j.file_path is None for j in jobs))  # 완료 후 경로 정리

    def test_rollback_discards_enqueued_jobs(self):
        # enqueue는 세션에 추가만 하므로, 호출한 서비스가 롤백하면 작업도 남지 않는다.
        async def flow(db):
            FileCleanupService(db).enqueue(TARGET_PATIENT, 1, [(FILE_KIND_XRAY, "1/a.png")])
            await db.rollback()

        self.run_async(flow)
        self.assertEqual(self.all_jobs(), [])

    def test_missing_file_is_done(self):
        async def flow(db):
            cleanup = FileCleanupService(db)
            jobs = cleanup.enqueue(TARGET_MEDICAL_RECORD, 1, [(FILE_KIND_XRAY, "1/none.png")])
            await db.commit()
            return await cleanup.run(jobs)

        self.assertTrue(self.run_async(flow))
        self.assertEqual(self.all_jobs()[0].status, "done")

    def test_path_outside_storage_is_invalid_and_not_deleted(self):
        outside = Path(self.tmp.name) / "important.txt"
        outside.write_text("keep")

        async def flow(db):
            cleanup = FileCleanupService(db)
            jobs = cleanup.enqueue(TARGET_PATIENT, 1, [(FILE_KIND_XRAY, "../important.txt")])
            await db.commit()
            return await cleanup.run(jobs)

        self.assertTrue(self.run_async(flow))
        self.assertTrue(outside.exists())
        self.assertEqual(self.all_jobs()[0].status, "invalid")

    # ---- 삭제 실패 → 미완료 유지 → 재처리 ----
    def test_failure_keeps_job_pending_then_retry_completes(self):
        path = self.make_file(self.xray_root, "5/a.png")

        async def fail_first(db):
            cleanup = FileCleanupService(db)
            jobs = cleanup.enqueue(TARGET_PATIENT, 5, [(FILE_KIND_XRAY, "5/a.png")])
            await db.commit()
            with patch("app.services.file_cleanup_service.delete_stored_file", side_effect=PermissionError):
                return await cleanup.run(jobs)

        self.assertFalse(self.run_async(fail_first))
        job = self.all_jobs()[0]
        self.assertEqual((job.status, job.attempts), ("pending", 1))
        self.assertGreater(job.next_attempt_at, datetime.now(UTC).replace(tzinfo=None))
        self.assertTrue(path.exists())

        # 재시도 시각 전에는 처리하지 않는다.
        self.assertEqual(self.run_async(lambda db: FileCleanupService(db).retry_pending()), 0)

        # 재시도 시각이 지나면 처리한다.
        async def make_due(db):
            job = (await db.execute(select(FileCleanupJob))).scalar_one()
            job.next_attempt_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
            await db.commit()

        self.run_async(make_due)
        self.assertEqual(self.run_async(lambda db: FileCleanupService(db).retry_pending()), 1)
        self.assertFalse(path.exists())
        self.assertEqual(self.all_jobs()[0].status, "done")

    def test_resume_for_delete_retry(self):
        # 미완료 작업이 없으면 None → 호출한 쪽은 404 판단으로 넘어간다.
        self.assertIsNone(self.run_async(lambda db: FileCleanupService(db).resume(TARGET_PATIENT, 7)))

        self.make_file(self.xray_root, "7/a.png")

        async def leave_pending(db):
            FileCleanupService(db).enqueue(TARGET_PATIENT, 7, [(FILE_KIND_XRAY, "7/a.png")])
            await db.commit()

        self.run_async(leave_pending)
        self.assertTrue(self.run_async(lambda db: FileCleanupService(db).resume(TARGET_PATIENT, 7)))
        self.assertIsNone(self.run_async(lambda db: FileCleanupService(db).resume(TARGET_PATIENT, 7)))

    def test_record_orphan_commits_separately(self):
        async def flow(db):
            await FileCleanupService(db).record_orphan(TARGET_PATIENT, 9, [(FILE_KIND_XRAY, "9/a.png")])

        self.run_async(flow)
        job = self.all_jobs()[0]
        self.assertEqual((job.target_type, job.target_id, job.status), (TARGET_PATIENT, 9, "pending"))

    def test_incomplete_error_message(self):
        error = cleanup_incomplete_error()
        self.assertEqual((error.status_code, error.detail), (500, CLEANUP_INCOMPLETE))


if __name__ == "__main__":
    unittest.main()
