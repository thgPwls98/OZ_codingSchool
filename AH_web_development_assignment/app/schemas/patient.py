from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from app.models.enums import Gender
from app.schemas.common import UTCDateTime
from app.schemas.user import PhoneNumber

# ===== 공통 타입 (설계 문서 2-3) =====
PatientName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=30)]
Age = Annotated[int, Field(ge=0, le=150)]


# ===== 요청 =====
# REQ-PTNT-001 환자 등록
class PatientCreateRequest(BaseModel):
    # 정의되지 않은 필드가 들어오면 422로 거부한다.
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "name": "김환자",
                "age": 45,
                "gender": "female",
                "phone_number": "01098765432",
            }
        },
    )

    name: PatientName
    age: Age
    gender: Gender
    phone_number: PhoneNumber


# REQ-PTNT-002 환자 목록 (쿼리 파라미터)
class PatientSearchParams(BaseModel):
    """`Annotated[PatientSearchParams, Query()]`로 받아야 검증 오류가 422가 된다.
    (`Depends()`로 받으면 model_validator 오류가 500이 된다)
    """

    name: Annotated[str | None, Field(max_length=30)] = None
    gender: Gender | None = None
    min_age: Age | None = None
    max_age: Age | None = None

    # 공백만 입력한 검색어는 검색 조건 없음으로 처리한다.
    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @model_validator(mode="after")
    def check_age_range(self) -> "PatientSearchParams":
        if self.min_age is not None and self.max_age is not None and self.min_age > self.max_age:
            raise ValueError("최소 나이는 최대 나이보다 클 수 없습니다.")
        return self


# REQ-PTNT-004 환자 수정 (이름·연락처만 부분 수정)
class PatientUpdateRequest(BaseModel):
    # 나이·성별 등 수정할 수 없는 필드가 들어오면 422로 거부한다.
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"example": {"name": "김환자", "phone_number": "01011112222"}},
    )

    name: PatientName | None = None
    phone_number: PhoneNumber | None = None

    # 생략한 필드는 유지하고, null을 직접 보낸 경우만 거부한다. (설계 문서 2-3)
    @field_validator("name", "phone_number", mode="before")
    @classmethod
    def reject_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("null은 입력할 수 없습니다.")
        return value


# ===== 응답 (공통 PatientResponse) =====
class PatientResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    age: int
    gender: Gender
    phone_number: str
    created_at: UTCDateTime
    updated_at: UTCDateTime | None
