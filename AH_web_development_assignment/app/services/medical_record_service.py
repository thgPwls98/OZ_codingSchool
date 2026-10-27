from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.models.xray_image import XrayImage

CLEANUP_FAILED = "파일 정리가 완료되지 않았습니다. 상태를 다시 조회해주세요."


class MedicalRecordService:
    """파일 모듈과 FileCleanupService(db) 인스턴스를 같은 DB 세션으로 사용한다."""

    def __init__(self, repository, patient_repository, storage, cleanup,
                 cleanup_error=None, target_type="medical_record"):
        self.repository = repository
        self.db = repository.db
        self.patients = patient_repository
        self.storage = storage
        self.cleanup = cleanup
        self.cleanup_error = cleanup_error or (lambda: HTTPException(500, CLEANUP_FAILED))
        self.target_type = target_type

    async def _lock(self, record_id):
        patient_id = await self.repository.patient_id_for(record_id)
        if patient_id is None or await self.patients.lock(patient_id) is None:
            raise HTTPException(404, "진료기록을 찾을 수 없습니다.")
        record = await self.repository.lock(record_id)
        if record is None or record.patient_id != patient_id:
            raise HTTPException(404, "진료기록을 찾을 수 없습니다.")
        return record

    async def _run_cleanup(self, jobs):
        if not jobs:
            return
        try:
            completed = await self.cleanup.run(jobs)
        except Exception as exc:
            await self.db.rollback()
            raise self.cleanup_error() from exc

        if not completed:
            raise self.cleanup_error()

    async def _discard_new_file(self, path, record_id):
        try:
            await self.storage.delete_xray_file(path)
        except Exception:
            # 원래 변경은 rollback된 상태. 새 파일 정리 작업만 별도로 영속화한다.
            self.cleanup.enqueue(self.target_type, record_id, [(self.storage.FILE_KIND_XRAY, path)])
            await self.db.commit()

    @staticmethod
    def _is_chart_conflict(exc):
        # UNIQUE 외의 무결성 오류를 차트 번호 중복으로 오인하지 않는다.
        message = str(exc.orig).lower()
        return "chart_number" in message and ("duplicate" in message or "unique" in message)

    async def update(self, record_id, data, upload, uploader_id):
        updates = data.model_dump(exclude_unset=True)
        if not updates and upload is None:
            raise HTTPException(400, "수정할 항목을 하나 이상 입력하세요.")
        new_path = None
        try:
            record = await self._lock(record_id)
            if "chart_number" in updates and await self.repository.chart_exists(updates["chart_number"], record_id):
                raise HTTPException(409, "이미 사용 중인 차트 넘버입니다.")
            jobs = []
            if upload is not None:
                new_path = await self.storage.save_xray_image(upload, record.patient_id)
                paths = await self.repository.file_paths(record_id)
                await self.repository.remove_image_data(record_id)
                self.db.add(XrayImage(record_id=record_id, uploader_id=uploader_id,
                                      image_url=new_path, shooting_datetime=datetime.now(UTC).replace(tzinfo=None)))
                jobs = self.cleanup.enqueue(self.target_type, record_id, paths)
            for key, value in updates.items():
                setattr(record, key, value)
            record.updated_at = datetime.now(UTC).replace(tzinfo=None)
            await self.db.flush()
            # 커밋 후 동시 삭제의 영향을 받지 않도록 응답을 먼저 구성한다.
            response = await self.repository.response(record_id)
            await self.db.commit()
        except Exception as exc:
            await self.db.rollback()
            if new_path is not None:
                await self._discard_new_file(new_path, record_id)
            if isinstance(exc, IntegrityError) and self._is_chart_conflict(exc):
                raise HTTPException(409, "이미 사용 중인 차트 넘버입니다.") from exc
            if isinstance(exc, SQLAlchemyError):
                raise HTTPException(500, "잠시 후 다시 시도해주세요.") from exc
            raise
        await self._run_cleanup(jobs)
        return response

    async def delete(self, record_id):
        # 삭제된 자원이라도 미완료 정리 작업이 있으면 재개한다.
        try:
            resumed = await self.cleanup.resume(self.target_type, record_id)
        except Exception as exc:
            await self.db.rollback()
            raise self.cleanup_error() from exc
        if resumed is False:
            raise self.cleanup_error()
        if resumed is True and await self.repository.patient_id_for(record_id) is None:
            return
        try:
            record = await self._lock(record_id)
            paths = await self.repository.file_paths(record_id)
            jobs = self.cleanup.enqueue(self.target_type, record_id, paths)
            # 자식은 공통 기반의 DB CASCADE 마이그레이션으로 삭제한다.
            await self.db.delete(record)
            await self.db.commit()
        except Exception as exc:
            await self.db.rollback()
            if isinstance(exc, SQLAlchemyError):
                raise HTTPException(500, "잠시 후 다시 시도해주세요.") from exc
            raise
        await self._run_cleanup(jobs)
