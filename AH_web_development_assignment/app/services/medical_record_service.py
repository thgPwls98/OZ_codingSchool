import logging
from datetime import UTC, datetime
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.core.file_storage import (
    FILE_KIND_XRAY,
    OrphanedUploadError,
    delete_xray_file,
    resolve_xray_path,
    save_xray_image,
)
from app.models.medical_record import MedicalRecord
from app.models.user import User
from app.models.xray_image import XrayImage
from app.repositories.medical_record_repository import MedicalRecordRepository
from app.repositories.patient_repository import PatientRepository
from app.schemas.medical_record import (
    MedicalRecordListItem,
    MedicalRecordResponse,
    to_medical_record_list_item,
    to_medical_record_response,
)
from app.services.file_cleanup_service import TARGET_PATIENT, FileCleanupService

PATIENT_NOT_FOUND = "환자를 찾을 수 없습니다."
CHART_NUMBER_DUPLICATED = "이미 사용 중인 차트 넘버입니다."
SAVE_FAILED = "잠시 후 다시 시도해주세요."
RECORD_NOT_FOUND = "진료기록을 찾을 수 없습니다."
IMAGE_NOT_FOUND = "이미지 파일을 찾을 수 없습니다."

# 저장할 때 파일 서명으로 정한 확장자 → 응답 Content-Type
IMAGE_MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}

logger = logging.getLogger(__name__)


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

    # ===== 조회 (팀원 4) - 데이터를 바꾸지 않으므로 잠금·commit 없음 =====

    # REQ-MDR-002 환자별 진료기록 목록 (5일차 설계 5-2)
    async def list_by_patient(self, patient_id: int) -> list[MedicalRecordListItem]:
        if await self.repository.get_patient(patient_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=PATIENT_NOT_FOUND)
        records = await self.repository.list_by_patient(patient_id)
        return [to_medical_record_list_item(record) for record in records]

    # REQ-MDR-003 진료기록 상세 (5일차 설계 5-3)
    async def get_detail(self, record_id: int) -> MedicalRecordResponse:
        row = await self.repository.get_with_image(record_id)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=RECORD_NOT_FOUND)
        record, image, uploader_name = row
        return to_medical_record_response(record, image, uploader_name)

    # REQ-MDR-003 X-Ray 이미지 조회 (5일차 설계 5-4, 7-2)
    async def get_xray_file(self, record_id: int) -> tuple[Path, str]:
        """이미지 파일 경로와 Content-Type을 돌려준다. 실제 저장 경로는 응답에 노출하지 않는다."""
        image = await self.repository.get_image(record_id)
        if image is None:
            detail = IMAGE_NOT_FOUND if await self.repository.exists(record_id) else RECORD_NOT_FOUND
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)

        try:
            path = resolve_xray_path(image.image_url)
        except ValueError:
            # 저장 폴더 밖을 가리키는 값. 이유를 알려주지 않고 404로 처리하고 로그에만 남긴다 (경로는 기록하지 않음, 설계 7-5)
            logger.warning("저장 폴더 밖 X-Ray 경로가 조회됨: xray_image_id=%s", image.id)
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=IMAGE_NOT_FOUND)

        media_type = IMAGE_MEDIA_TYPES.get(path.suffix.lower())
        if media_type is None or not path.is_file():
            logger.warning("X-Ray 파일 없음: xray_image_id=%s", image.id)
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=IMAGE_NOT_FOUND)
        return path, media_type
