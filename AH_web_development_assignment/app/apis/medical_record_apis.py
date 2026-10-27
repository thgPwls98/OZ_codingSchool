from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.databases import async_get_db
from app.core.dependencies import MedicalStaffUser
from app.repositories.medical_record_repository import MedicalRecordRepository
from app.schemas.medical_record import ChartNumber, MedicalRecordResponse, Symptoms
from app.services.medical_record_service import MedicalRecordService

router = APIRouter(prefix="/api/v1", tags=["medical-records"])


def get_medical_record_service(
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> MedicalRecordService:
    return MedicalRecordService(MedicalRecordRepository(db))


# REQ-MDR-001 진료기록 등록 (팀원 2)
# Form 필드와 파일을 Pydantic 모델 하나로 묶으면 파일 처리에서 오류가 나므로 각각 따로 받는다.
@router.post(
    "/medical-records",
    response_model=MedicalRecordResponse,
    status_code=status.HTTP_201_CREATED,
    summary="진료기록 등록 (X-Ray 이미지 포함)",
    responses={
        401: {"description": "인증 실패"},
        403: {"description": "의료진이 아님 (어드민 또는 의료 부서 스태프만 가능)"},
        404: {"description": "환자 없음"},
        409: {"description": "차트 넘버 중복"},
        413: {"description": "이미지 10MB 초과"},
        415: {"description": "JPG·PNG가 아닌 파일"},
        422: {"description": "필수 항목 누락, 길이·형식 오류"},
    },
)
async def create_medical_record(
    current_user: MedicalStaffUser,
    service: Annotated[MedicalRecordService, Depends(get_medical_record_service)],
    response: Response,
    patient_id: Annotated[int, Form(ge=1, description="환자 고유 ID")],
    chart_number: Annotated[ChartNumber, Form(description="진료 차트 넘버 (1~50자)")],
    symptoms: Annotated[Symptoms, Form(description="진료된 증상 (1~10,000자)")],
    xray_image: Annotated[UploadFile, File(description="흉부 X-Ray 이미지 (JPG·PNG, 10MB 이하)")],
):
    record = await service.create(current_user, patient_id, chart_number, symptoms, xray_image)
    response.headers["Location"] = f"/api/v1/medical-records/{record.id}"
    return record
