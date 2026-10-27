from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.databases import async_get_db
from app.core.dependencies import MedicalStaffUser, StaffUser
from app.repositories.patient_repository import PatientRepository
from app.schemas.patient import (
    PatientCreateRequest,
    PatientResponse,
    PatientSearchParams,
    PatientUpdateRequest,
)
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


# ===== 환자 상세·수정·삭제 (팀원 3) =====
PatientId = Annotated[int, Path(ge=1, description="환자 고유 ID")]


# REQ-PTNT-003 환자 상세
@router.get(
    "/{patient_id}",
    response_model=PatientResponse,
    summary="환자 상세 조회",
    responses={
        401: {"description": "인증 실패"},
        403: {"description": "대기자"},
        404: {"description": "환자 없음"},
    },
)
async def get_patient(
    patient_id: PatientId,
    _: StaffUser,
    service: Annotated[PatientService, Depends(get_patient_service)],
):
    return await service.get_patient(patient_id)


# REQ-PTNT-004 환자 수정 (이름·연락처 부분 수정)
@router.patch(
    "/{patient_id}",
    response_model=PatientResponse,
    summary="환자 정보 수정",
    responses={
        400: {"description": "수정할 항목 없음 (빈 객체)"},
        401: {"description": "인증 실패"},
        403: {"description": "대기자"},
        404: {"description": "환자 없음"},
        422: {"description": "형식 오류, 나이·성별 등 수정 불가 필드, null 값"},
    },
)
async def update_patient(
    patient_id: PatientId,
    body: PatientUpdateRequest,
    _: StaffUser,
    service: Annotated[PatientService, Depends(get_patient_service)],
):
    return await service.update_patient(patient_id, body)


# REQ-PTNT-005 환자 삭제 (진료기록·X-Ray·AI 결과와 파일까지 삭제)
@router.delete(
    "/{patient_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="환자 삭제 (관련 진료기록·이미지 영구 삭제)",
    responses={
        401: {"description": "인증 실패"},
        403: {"description": "대기자"},
        404: {"description": "환자 없음"},
        500: {"description": "DB 처리 실패 또는 파일 정리 미완료 (다시 요청하면 이어서 정리)"},
    },
)
async def delete_patient(
    patient_id: PatientId,
    _: StaffUser,
    service: Annotated[PatientService, Depends(get_patient_service)],
):
    await service.delete_patient(patient_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
