from fastapi import HTTPException, status
from sqlalchemy.exc import SQLAlchemyError

from app.models.patient import Patient
from app.repositories.patient_repository import PatientRepository
from app.schemas.patient import PatientCreateRequest, PatientSearchParams, PatientUpdateRequest
from app.services.file_cleanup_service import TARGET_PATIENT, FileCleanupService, cleanup_incomplete_error

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

    # ===== 환자 상세·수정·삭제 (팀원 3) =====

    # REQ-PTNT-003 환자 상세
    async def get_patient(self, patient_id: int) -> Patient:
        return await self.get_or_404(patient_id)

    # REQ-PTNT-004 환자 수정 (이름·연락처 부분 수정)
    async def update_patient(self, patient_id: int, data: PatientUpdateRequest) -> Patient:
        # 보내지 않은 필드는 유지한다. null은 스키마에서 이미 422로 막는다. (설계 2-3)
        changes = data.model_dump(exclude_unset=True)
        if not changes:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=NOTHING_TO_UPDATE)

        patient = await self.get_or_404(patient_id)
        db = self.repository.db
        try:
            for field, value in changes.items():
                setattr(patient, field, value)
            await db.commit()  # updated_at은 TimestampMixin의 onupdate로 갱신된다
            await db.refresh(patient)
            return patient
        except SQLAlchemyError as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=TRY_AGAIN_LATER
            ) from e

    # REQ-PTNT-005 환자 삭제 (진료기록·X-Ray·AI 결과 연쇄 삭제 + 파일 정리)
    async def delete_patient(self, patient_id: int, cleanup: FileCleanupService | None = None) -> None:
        """설계 6-3, 6-4 순서: 잠금 → 경로 수집 → DB 삭제와 정리 작업을 한 번에 commit → 파일 삭제"""
        db = self.repository.db
        cleanup = cleanup or FileCleanupService(db)

        # ⑤ 재요청이면 이전에 못 끝낸 파일 정리부터 이어 한다.
        resumed = await cleanup.resume(TARGET_PATIENT, patient_id)

        try:
            # ① 환자 잠금: 같은 환자의 진료기록 등록·수정·삭제와 순서를 맞춘다 (환자 → 진료기록)
            patient = await self.repository.lock(patient_id)
            if patient is None:
                await db.rollback()
                if resumed is None:
                    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=PATIENT_NOT_FOUND)
                if resumed is False:
                    raise cleanup_incomplete_error()
                return  # 환자는 이미 지워졌고 남은 파일 정리도 끝났다

            # ② 지울 파일 경로 수집 → ③ DB 삭제 + 정리 작업 기록을 하나의 트랜잭션으로 commit
            files = await self.repository.file_paths(patient_id)
            jobs = cleanup.enqueue(TARGET_PATIENT, patient_id, files)
            await self.repository.delete(patient)
            await db.commit()
        except SQLAlchemyError as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=TRY_AGAIN_LATER
            ) from e

        # ④ commit 이후 실제 파일 삭제. 하나라도 못 지우면 작업을 남기고 500 (DB 삭제는 이미 완료)
        if not await cleanup.run(jobs) or resumed is False:
            raise cleanup_incomplete_error()
