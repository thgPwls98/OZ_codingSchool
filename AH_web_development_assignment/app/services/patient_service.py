from fastapi import HTTPException, status

from app.models.patient import Patient
from app.repositories.patient_repository import PatientRepository

PATIENT_NOT_FOUND = "환자를 찾을 수 없습니다."
NOTHING_TO_UPDATE = "수정할 항목을 하나 이상 입력하세요."


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
