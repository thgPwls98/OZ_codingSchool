from importlib.util import find_spec
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import UploadFile as StarletteUploadFile

from app.core.db.databases import async_get_db
from app.core.dependencies import CurrentUser
from app.models.enums import Department, Role
from app.repositories.medical_record_repository import MedicalRecordRepository
from app.schemas.medical_record import MedicalRecordResponse, MedicalRecordUpdateRequest
from app.services.medical_record_service import MedicalRecordService

router = APIRouter(prefix="/api/v1/medical-records", tags=["Medical records"])


async def require_medical_staff(current_user: CurrentUser):
    # 공통 MedicalStaffUser 병합 시 이 의존성을 공통 의존성으로 교체한다.
    if current_user.role != Role.ADMIN and not (
        current_user.role == Role.STAFF and current_user.department == Department.MEDICAL
    ):
        raise HTTPException(403, "의료진만 등록할 수 있습니다.")
    return current_user


async def get_medical_record_service(
    db: Annotated[AsyncSession, Depends(async_get_db)],
    medical_user: Annotated[object, Depends(require_medical_staff)],
):
    # 공통 기반은 별도 PR 담당. import를 요청 시점으로 두어 기존 API 구동을 유지한다.
    required = (
        "app.core.file_storage", "app.repositories.patient_repository",
        "app.services.file_cleanup_service",
    )
    if any(find_spec(name) is None for name in required):
        raise HTTPException(503, "공통 기반 준비 후 사용할 수 있습니다.")
    from app.core import file_storage
    from app.repositories.patient_repository import PatientRepository
    from app.services.file_cleanup_service import (
        TARGET_MEDICAL_RECORD, FileCleanupService, cleanup_incomplete_error,
    )

    return MedicalRecordService(
        MedicalRecordRepository(db), PatientRepository(db), file_storage, FileCleanupService(db),
        cleanup_error=cleanup_incomplete_error, target_type=TARGET_MEDICAL_RECORD
    )


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
    "/{record_id}", response_model=MedicalRecordResponse,
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
    user: Annotated[object, Depends(require_medical_staff)],
    service: Annotated[MedicalRecordService, Depends(get_medical_record_service)],
    parsed: Annotated[tuple, Depends(parse_update)],
):
    data, upload = parsed
    return await service.update(record_id, data, upload, user.id)


@router.delete("/{record_id}", status_code=204)
async def delete_record(
    record_id: Annotated[int, Path(gt=0)],
    user: Annotated[object, Depends(require_medical_staff)],
    service: Annotated[MedicalRecordService, Depends(get_medical_record_service)],
):
    await service.delete(record_id)
    return Response(status_code=204)
