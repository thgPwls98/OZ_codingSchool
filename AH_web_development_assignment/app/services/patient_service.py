from fastapi import HTTPException, status
from sqlalchemy.exc import SQLAlchemyError

from app.models.patient import Patient
from app.repositories.patient_repository import PatientRepository
from app.schemas.patient import PatientCreateRequest, PatientSearchParams

PATIENT_NOT_FOUND = "환자를 찾을 수 없습니다."
NOTHING_TO_UPDATE = "수정할 항목을 하나 이상 입력하세요."
TRY_AGAIN_LATER = "잠시 후 다시 시도해주세요."


class PatientService:
    """환자 API의 업무 로직. API 담당자가 자기 함수를 추가한다. (설계 문서 11절)"""

    def __init__(self, repository: PatientRepository):
        self.repository = repository

    async def get_or_404(self, patient_id: int) -> Patient:
        """환자를 조회하고, 없으면 404를 낸다. (상세·수정·삭제·진료기록 목록에서 공통 사용)"""
        patient = await self.repository.get_by_id(patient_id)
        if patient is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=PATIENT_NOT_FOUND)
        return patient

    # ===== 환자 등록·목록 (팀원 1) =====

    # REQ-PTNT-001 환자 등록
    async def create_patient(self, data: PatientCreateRequest) -> Patient:
        patient = Patient(**data.model_dump())
        db = self.repository.db
        try:
            await self.repository.add(patient)
            await db.commit()
            await db.refresh(patient)
            return patient
        except SQLAlchemyError as e:
            await db.rollback()
            # 내부 SQL·경로는 응답하지 않는다 (설계 문서 7-5)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=TRY_AGAIN_LATER
            ) from e

    # REQ-PTNT-002 환자 목록
    async def list_patients(self, params: PatientSearchParams) -> list[Patient]:
        return await self.repository.search(params)
