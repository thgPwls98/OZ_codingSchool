from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.databases import async_get_db
from app.core.dependencies import MedicalStaffUser, StaffUser
from app.repositories.patient_repository import PatientRepository
from app.schemas.patient import PatientCreateRequest, PatientResponse, PatientSearchParams
from app.services.patient_service import PatientService

# 환자 API 1~5와 진료기록 목록(7)을 이 라우터에 추가한다. (설계 문서 11절)
router = APIRouter(prefix="/api/v1/patients", tags=["patients"])


def get_patient_service(db: Annotated[AsyncSession, Depends(async_get_db)]) -> PatientService:
    return PatientService(PatientRepository(db))


# ===== 환자 등록·목록 (팀원 1) =====

# REQ-PTNT-001 환자 등록
@router.post(
    "",
    response_model=PatientResponse,
    status_code=status.HTTP_201_CREATED,
    summary="환자 등록",
    responses={
        401: {"description": "인증 실패"},
        403: {"description": "의료진이 아님"},
        422: {"description": "필수 값 누락, 나이 범위·연락처 형식 오류, 정의되지 않은 필드"},
    },
)
async def create_patient(
    body: PatientCreateRequest,
    response: Response,
    _: MedicalStaffUser,
    service: Annotated[PatientService, Depends(get_patient_service)],
):
    patient = await service.create_patient(body)
    response.headers["Location"] = f"{router.prefix}/{patient.id}"
    return patient


# REQ-PTNT-002 환자 목록 (이름 검색, 성별·나이 범위 필터)
@router.get(
    "",
    response_model=list[PatientResponse],
    summary="환자 목록 조회",
    responses={
        401: {"description": "인증 실패"},
        403: {"description": "대기자"},
        422: {"description": "잘못된 성별·나이 값, 최소 나이 > 최대 나이"},
    },
)
async def list_patients(
    # Query()로 받아야 model_validator 오류가 422가 된다 (설계 문서 4-2)
    params: Annotated[PatientSearchParams, Query()],
    _: StaffUser,
    service: Annotated[PatientService, Depends(get_patient_service)],
):
    return await service.list_patients(params)
