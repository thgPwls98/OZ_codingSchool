from datetime import UTC, datetime

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.core import file_storage
from app.core.file_storage import FILE_KIND_XRAY, OrphanedUploadError, delete_xray_file, save_xray_image
from app.models.medical_record import MedicalRecord
from app.models.user import User
from app.models.xray_image import XrayImage
from app.repositories.medical_record_repository import MedicalRecordRepository
from app.repositories.patient_repository import PatientRepository
from app.schemas.medical_record import MedicalRecordResponse, to_medical_record_response
from app.services.file_cleanup_service import (
    TARGET_MEDICAL_RECORD, TARGET_PATIENT, FileCleanupService, cleanup_incomplete_error,
)

PATIENT_NOT_FOUND = "환자를 찾을 수 없습니다."
CHART_NUMBER_DUPLICATED = "이미 사용 중인 차트 넘버입니다."
SAVE_FAILED = "잠시 후 다시 시도해주세요."
CLEANUP_FAILED = "파일 정리가 완료되지 않았습니다. 상태를 다시 조회해주세요."


class MedicalRecordService:
    """파일 모듈과 FileCleanupService(db) 인스턴스를 같은 DB 세션으로 사용한다."""

    def __init__(self, repository, patient_repository=None, storage=None, cleanup=None,
                 cleanup_error=cleanup_incomplete_error, target_type=TARGET_MEDICAL_RECORD):
        self.repository = repository
        self.db = repository.db
        self.patients = patient_repository if patient_repository is not None else PatientRepository(self.db)
        self.storage = storage if storage is not None else file_storage
        self.cleanup = cleanup if cleanup is not None else FileCleanupService(self.db)
        self.cleanup_error = cleanup_error
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

    async def _discard_replacement_file(self, path, record_id):
        try:
            await self.storage.delete_xray_file(path)
        except Exception:
            # 원래 변경은 rollback된 상태. 새 파일 정리 작업만 별도로 영속화한다.
            await self._persist_replacement_cleanup(path, record_id)

    async def _persist_replacement_cleanup(self, path, record_id):
        try:
            self.cleanup.enqueue(
                self.target_type, record_id, [(self.storage.FILE_KIND_XRAY, path)]
            )
            await self.db.commit()
        except SQLAlchemyError as exc:
            await self.db.rollback()
            raise HTTPException(500, SAVE_FAILED) from exc

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
            if isinstance(exc, OrphanedUploadError):
                # 저장이 끝나기 전 실패해서 반환받지 못한 부분 파일도 추적한다.
                await self._persist_replacement_cleanup(exc.relative_path, record_id)
                raise exc.original from None
            if new_path is not None:
                await self._discard_replacement_file(new_path, record_id)
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

    # REQ-MDR-001 진료기록 등록 (5일차 설계 5-1, 6-1)
    async def create(
        self,
        uploader: User,
        patient_id: int,
        chart_number: str,
        symptoms: str,
        xray_image: UploadFile,
    ) -> MedicalRecordResponse:
        # ① 환자 존재 확인
        if await self.repository.get_patient(patient_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=PATIENT_NOT_FOUND)

        # ② 차트 넘버 중복 사전 확인 (빠른 실패용, 최종 판단은 DB UNIQUE - D14)
        if await self.repository.get_by_chart_number(chart_number) is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=CHART_NUMBER_DUPLICATED)

        # ③④ 파일 서명 확인 후 청크 단위 저장 (실패 시 415 / 413, 쓰던 파일은 삭제됨)
        # 업로드는 시간이 걸리므로 환자 잠금 전에 끝내서 잠금 시간을 줄인다.
        try:
            relative_path = await save_xray_image(xray_image, patient_id)
        except OrphanedUploadError as e:
            # 중단 후 쓰던 파일 삭제까지 실패: 정리 작업으로 남기고 원래 오류(413 등)를 돌려준다.
            await FileCleanupService(self.db).record_orphan(
                TARGET_PATIENT, patient_id, [(FILE_KIND_XRAY, e.relative_path)]
            )
            raise e.original from None

        # ⑤ 환자 잠금 → 진료기록 + X-Ray 이미지 저장 → commit (하나의 트랜잭션)
        record = MedicalRecord(patient_id=patient_id, chart_number=chart_number, symptoms=symptoms)
        image = XrayImage(
            uploader_id=uploader.id,
            image_url=relative_path,
            # 화면에 촬영 일시 입력칸이 없어 업로드 시각으로 채운다 (D8)
            shooting_datetime=datetime.now(UTC).replace(tzinfo=None),
        )
        try:
            # 업로드하는 동안 환자가 삭제되었을 수 있으므로 잠근 상태에서 다시 확인한다.
            if await PatientRepository(self.db).lock(patient_id) is None:
                await self.db.rollback()
                await self._discard_new_file(patient_id, relative_path)
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=PATIENT_NOT_FOUND)
            await self.repository.add_with_image(record, image)
            await self.db.commit()
        except IntegrityError as e:
            # 동시 요청이 ②를 함께 통과한 경우 DB UNIQUE 위반으로 걸러진다.
            await self.db.rollback()
            await self._discard_new_file(patient_id, relative_path)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=CHART_NUMBER_DUPLICATED
            ) from e
        except SQLAlchemyError as e:
            await self.db.rollback()
            await self._discard_new_file(patient_id, relative_path)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=SAVE_FAILED
            ) from e

        await self.db.refresh(record)
        return to_medical_record_response(record, image, uploader.name)

    async def _discard_new_file(self, patient_id: int, relative_path: str) -> None:
        """롤백된 등록의 새 파일을 지운다. 삭제마저 실패하면 별도 트랜잭션으로 정리 작업을 남긴다 (설계 6-4 ⑥)"""
        try:
            await delete_xray_file(relative_path)
        except (OSError, ValueError):
            await FileCleanupService(self.db).record_orphan(
                TARGET_PATIENT, patient_id, [(FILE_KIND_XRAY, relative_path)]
            )
