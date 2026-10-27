from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator

from app.models.medical_record import MedicalRecord
from app.models.xray_image import XrayImage
from app.schemas.common import UTCDateTime

# ===== 입력값 규칙 (5일차 설계 2-3) =====
# multipart Form 필드에도 그대로 쓸 수 있도록 Annotated 타입으로 정의한다.
ChartNumber = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
Symptoms = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10_000)]


# ===== 응답 =====
class MedicalRecordResponse(BaseModel):
    """진료기록 등록·상세·수정 응답 (5일차 설계 2-4)"""

    id: int
    patient_id: int
    chart_number: str
    symptoms: str
    xray_image_url: str
    uploader_id: int | None
    uploader_name: str | None
    created_at: UTCDateTime
    updated_at: UTCDateTime | None



class MedicalRecordListItem(BaseModel):
    """환자별 진료기록 목록의 한 줄 (5일차 설계 2-4, 5-2)"""

    id: int
    chart_number: str
    symptoms: str  # 100자 초과 시 앞 100자 + …
    created_at: UTCDateTime


SYMPTOMS_PREVIEW_LENGTH = 100


def summarize_symptoms(symptoms: str) -> str:
    """목록용 증상 요약 (설계 2-4 증상 생략 규칙)

    - 바이트가 아니라 글자 수 기준 (파이썬 str 길이 = 글자 수)
    - 정확히 100자면 그대로, 101자부터 앞 100자 + …
    - DB 원문은 바꾸지 않고 응답에서만 자른다.
    """
    if len(symptoms) <= SYMPTOMS_PREVIEW_LENGTH:
        return symptoms
    return symptoms[:SYMPTOMS_PREVIEW_LENGTH] + "…"


def to_medical_record_list_item(record: MedicalRecord) -> MedicalRecordListItem:
    return MedicalRecordListItem(
        id=record.id,
        chart_number=record.chart_number,
        symptoms=summarize_symptoms(record.symptoms),
        created_at=record.created_at,
    )


def xray_image_url(record_id: int) -> str:
    """이미지 조회 API 경로. 실제 저장 경로는 응답에 노출하지 않는다 (설계 7-2)"""
    return f"/api/v1/medical-records/{record_id}/xray-image"


def to_medical_record_response(
    record: MedicalRecord, image: XrayImage, uploader_name: str | None
) -> MedicalRecordResponse:
    """진료기록과 X-Ray 이미지 1장을 응답 형태로 바꾼다 (진료기록 1건 = 이미지 1장, D15)

    업로더가 탈퇴하면 uploader_id가 NULL이 되므로 uploader_name도 None으로 맞춘다.
    """
    return MedicalRecordResponse(
        id=record.id,
        patient_id=record.patient_id,
        chart_number=record.chart_number,
        symptoms=record.symptoms,
        xray_image_url=xray_image_url(record.id),
        uploader_id=image.uploader_id,
        uploader_name=uploader_name if image.uploader_id is not None else None,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


class MedicalRecordUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chart_number: str | None = None
    symptoms: str | None = None

    @field_validator("chart_number", "symptoms", mode="before")
    @classmethod
    def validate_text(cls, value, info):
        limit = 50 if info.field_name == "chart_number" else 10_000
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= limit:
            raise ValueError(f"공백 제거 후 1~{limit}자 문자열이어야 합니다.")
        return value.strip()
