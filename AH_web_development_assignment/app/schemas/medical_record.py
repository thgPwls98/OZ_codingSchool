from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


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


class MedicalRecordResponse(BaseModel):
    id: int
    patient_id: int
    chart_number: str
    symptoms: str
    xray_image_url: str
    uploader_id: int | None
    uploader_name: str | None
    created_at: datetime
    updated_at: datetime | None
