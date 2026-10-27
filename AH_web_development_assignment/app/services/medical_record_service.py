from datetime import UTC, datetime

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.core.file_storage import FILE_KIND_XRAY, delete_xray_file, save_xray_image
from app.models.medical_record import MedicalRecord
from app.models.user import User
from app.models.xray_image import XrayImage
from app.repositories.medical_record_repository import MedicalRecordRepository
from app.schemas.medical_record import MedicalRecordResponse, to_medical_record_response
from app.services.file_cleanup_service import TARGET_PATIENT, FileCleanupService

PATIENT_NOT_FOUND = "환자를 찾을 수 없습니다."
CHART_NUMBER_DUPLICATED = "이미 사용 중인 차트 넘버입니다."
SAVE_FAILED = "잠시 후 다시 시도해주세요."


class MedicalRecordService:
    """팀 규칙: commit·rollback은 서비스가 한다. 잠금 순서는 환자 → 진료기록."""

    def __init__(self, repository: MedicalRecordRepository):
        self.repository = repository
        self.db = repository.db

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
        relative_path = await save_xray_image(xray_image, patient_id)

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
            if await self.repository.lock_patient(patient_id) is None:
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
