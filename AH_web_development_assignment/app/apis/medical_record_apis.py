from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Path, Request, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from starlette.datastructures import UploadFile as StarletteUploadFile

from app.core.db.databases import async_get_db
from app.core.dependencies import MedicalStaffUser, StaffUser
from app.repositories.medical_record_repository import MedicalRecordRepository
from app.schemas.medical_record import (
    ChartNumber,
    MedicalRecordListItem,
    MedicalRecordResponse,
    MedicalRecordUpdateRequest,
    Symptoms,
)
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


async def parse_update(request: Request):
    if request.headers.get("content-type", "").split(";", 1)[0].strip() != "multipart/form-data":
        raise HTTPException(422, "multipart/form-data로 전송해주세요.")
    form = await request.form()
    try:
        yield _parse_form(form)
    finally:
        await form.close()


def _parse_form(form):
    values = {}
    upload = None
    errors = []
    for key in form:
        entries = form.getlist(key)
        if key not in {"chart_number", "symptoms", "xray_image"} or len(entries) != 1:
            errors.append(dict(type="value_error", loc=("body", key), msg="허용되지 않거나 중복된 필드입니다.", input=None))
        elif key == "xray_image":
            if not isinstance(entries[0], StarletteUploadFile) or not entries[0].filename:
                errors.append(dict(type="value_error", loc=("body", key), msg="이미지 파일이어야 합니다.", input=None))
            else:
                upload = entries[0]
        else:
            values[key] = entries[0]
    if errors:
        raise RequestValidationError(errors)
    try:
        data = MedicalRecordUpdateRequest.model_validate(values)
    except ValidationError as exc:
        raise RequestValidationError([
            {**error, "loc": ("body", *error["loc"])} for error in exc.errors()
        ]) from exc
    return data, upload


@router.patch(
    "/medical-records/{record_id}", response_model=MedicalRecordResponse,
    openapi_extra={"requestBody": {"content": {"multipart/form-data": {"schema": {
        "type": "object", "additionalProperties": False,
        "properties": {
            "chart_number": {"type": "string", "maxLength": 50},
            "symptoms": {"type": "string", "maxLength": 10000},
            "xray_image": {"type": "string", "format": "binary"},
        },
    }}}}},
)
async def update_record(
    record_id: Annotated[int, Path(gt=0)],
    user: MedicalStaffUser,
    service: Annotated[MedicalRecordService, Depends(get_medical_record_service)],
    parsed: Annotated[tuple, Depends(parse_update)],
):
    data, upload = parsed
    return await service.update(record_id, data, upload, user.id)


@router.delete("/medical-records/{record_id}", status_code=204)
async def delete_record(
    record_id: Annotated[int, Path(gt=0)],
    user: MedicalStaffUser,
    service: Annotated[MedicalRecordService, Depends(get_medical_record_service)],
):
    await service.delete(record_id)
    return Response(status_code=204)

# ===== 조회 API (팀원 4) =====
PatientId = Annotated[int, Path(ge=1, description="환자 고유 ID")]
RecordId = Annotated[int, Path(ge=1, description="진료기록 ID")]

# 의료 이미지 응답 헤더 (5일차 설계 5-4, 7-2)
XRAY_RESPONSE_HEADERS = {
    "Content-Disposition": "inline",           # 다운로드가 아니라 화면에 표시
    "Cache-Control": "private, no-store",      # 브라우저·프록시에 의료 이미지 캐시 금지
    "X-Content-Type-Options": "nosniff",       # 내용을 추측해 다른 형식으로 실행하는 것 차단
}


# REQ-MDR-002 환자별 진료기록 목록 (팀원 4)
# 설계 11장은 patient_apis.py에 두기로 했지만, 진료기록 서비스와 함께 관리하고
# 환자 API 작업과 같은 파일을 동시에 고쳐 생기는 충돌을 피하려고 이 라우터에 둔다. 주소는 같다.
@router.get(
    "/patients/{patient_id}/medical-records",
    response_model=list[MedicalRecordListItem],
    summary="환자별 진료기록 목록 조회",
    responses={
        401: {"description": "인증 실패"},
        403: {"description": "대기자"},
        404: {"description": "환자 없음 (기록이 없으면 200 [])"},
    },
)
async def list_medical_records(
    patient_id: PatientId,
    current_user: StaffUser,
    service: Annotated[MedicalRecordService, Depends(get_medical_record_service)],
):
    return await service.list_by_patient(patient_id)


# REQ-MDR-003 진료기록 상세 (팀원 4)
@router.get(
    "/medical-records/{record_id}",
    response_model=MedicalRecordResponse,
    summary="진료기록 상세 조회",
    responses={
        401: {"description": "인증 실패"},
        403: {"description": "대기자"},
        404: {"description": "진료기록 없음"},
    },
)
async def get_medical_record(
    record_id: RecordId,
    current_user: StaffUser,
    service: Annotated[MedicalRecordService, Depends(get_medical_record_service)],
):
    return await service.get_detail(record_id)


# REQ-MDR-003 X-Ray 이미지 조회 (팀원 4) - 인증된 사용자만 (설계 D10)
@router.get(
    "/medical-records/{record_id}/xray-image",
    response_class=FileResponse,
    summary="X-Ray 이미지 조회",
    responses={
        200: {"description": "이미지 바이너리", "content": {"image/png": {}, "image/jpeg": {}}},
        401: {"description": "인증 실패"},
        403: {"description": "대기자"},
        404: {"description": "진료기록 없음, 또는 이미지 파일 없음"},
    },
)
async def get_xray_image(
    record_id: RecordId,
    current_user: StaffUser,
    service: Annotated[MedicalRecordService, Depends(get_medical_record_service)],
):
    path, media_type = await service.get_xray_file(record_id)
    return FileResponse(path, media_type=media_type, headers=XRAY_RESPONSE_HEADERS)
