import re
from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    field_validator,
)

from app.models.enums import Department, Gender, Role


# ===== 공통 검증 함수 (회원가입 / 비밀번호 변경 / 정보 수정에서 재사용) =====
def normalize_email(value: object) -> object:
    """앞뒤 공백을 제거하고 소문자로 바꾼다."""
    if isinstance(value, str):
        return value.strip().lower()
    return value


def validate_password(value: str) -> str:
    """영문 대문자·소문자·숫자·특수문자 각 1개 이상, 공백 불허."""
    if re.search(r"\s", value):
        raise ValueError("비밀번호에 공백을 사용할 수 없습니다.")
    if not (
        re.search(r"[A-Z]", value)
        and re.search(r"[a-z]", value)
        and re.search(r"[0-9]", value)
        and re.search(r"[^A-Za-z0-9]", value)
    ):
        raise ValueError("비밀번호는 영문 대문자, 소문자, 숫자, 특수문자를 각각 1개 이상 포함해야 합니다.")
    return value


# 다른 팀원도 import해서 쓸 수 있는 타입
Email = Annotated[EmailStr, BeforeValidator(normalize_email), Field(max_length=255)]
Password = Annotated[str, Field(min_length=8, max_length=64), AfterValidator(validate_password)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=20)]
PhoneNumber = Annotated[
    str,
    Field(pattern=r"^010\d{8}$", description="010으로 시작하는 숫자 11자리 (하이픈 없음)"),
]


# ===== 요청 =====
class RoleChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: int = Field(ge=1)
    new_role: Role


class SignupRequest(BaseModel):
    # role, is_active 등 정의되지 않은 필드가 들어오면 422로 거부한다.
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "email": "hong@example.com",
                "password": "Example123!",
                "name": "홍길동",
                "department": "medical",
                "gender": "male",
                "phone_number": "01012345678",
            }
        },
    )

    email: Email
    password: Password
    name: Name
    department: Department
    gender: Gender
    phone_number: PhoneNumber


# REQ-USER-007 내 정보 수정 (부서·휴대폰 번호만 부분 수정)
class UpdateMeRequest(BaseModel):
    # 이메일·이름·권한 등 수정할 수 없는 필드가 들어오면 422로 거부한다.
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"example": {"department": "research"}},
    )

    department: Department | None = None
    phone_number: PhoneNumber | None = None

    # 생략한 필드는 유지하고, null을 직접 보낸 경우만 거부한다.
    # (기본값 None에는 검증 함수가 실행되지 않는다.)
    @field_validator("department", "phone_number", mode="before")
    @classmethod
    def reject_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("null은 입력할 수 없습니다.")
        return value


# REQ-USER-008 비밀번호 변경
class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "current_password": "Example123!",
                "new_password": "Changed456!",
            }
        },
    )

    current_password: str = Field(min_length=1)
    new_password: Password


# ===== 응답 (공통 UserResponse) =====
class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    name: str
    department: Department
    gender: Gender
    phone_number: str
    role: Role
    is_active: bool
