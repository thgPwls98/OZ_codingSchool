import re
from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    EmailStr,
    Field,
)

from app.models.enums import Department, Gender, Role


# ===== 공통 검증 함수 (회원가입 / 비밀번호 변경 / 정보 수정에서 재사용) =====
def normalize_email(value: object) -> object:
    """앞뒤 공백을 제거하고 소문자로 바꾼다."""
    if isinstance(value, str):
        return value.strip().lower()
    return value


# 프런트엔드(static/apis.js)가 이 문구를 그대로 인식해서 보여주므로 바꾸지 않는다.
PASSWORD_RULE_MESSAGE = "비밀번호는 대소문자, 특수문자, 숫자를 각 1개씩 포함한 8자리 이상이어야 합니다."


def validate_password(value: str) -> str:
    """8~64자, 영문 대문자·소문자·숫자·특수문자 각 1개 이상, 공백 불허."""
    if re.search(r"\s", value):
        raise ValueError("비밀번호에 공백을 사용할 수 없습니다.")
    if len(value) > 64:
        raise ValueError("비밀번호는 64자 이하여야 합니다.")
    if not (
        len(value) >= 8
        and re.search(r"[A-Z]", value)
        and re.search(r"[a-z]", value)
        and re.search(r"[0-9]", value)
        and re.search(r"[^A-Za-z0-9]", value)
    ):
        raise ValueError(PASSWORD_RULE_MESSAGE)
    return value


def validate_name(value: str) -> str:
    """앞뒤 공백 제거 후 2~20자."""
    value = value.strip()
    if not 2 <= len(value) <= 20:
        raise ValueError("이름은 2~20자로 입력하세요.")
    return value


def validate_phone_number(value: str) -> str:
    """010으로 시작하는 숫자 11자리 (하이픈 없음)."""
    if not re.fullmatch(r"010\d{8}", value):
        raise ValueError("휴대폰 번호는 010으로 시작하는 숫자 11자리로 입력하세요.")
    return value


# 다른 팀원도 import해서 쓸 수 있는 타입
Email = Annotated[EmailStr, BeforeValidator(normalize_email), Field(max_length=255)]
Password = Annotated[
    str,
    AfterValidator(validate_password),
    Field(description="8~64자, 영문 대문자·소문자·숫자·특수문자 각 1개 이상"),
]
Name = Annotated[str, AfterValidator(validate_name), Field(description="2~20자")]
PhoneNumber = Annotated[
    str,
    AfterValidator(validate_phone_number),
    Field(description="010으로 시작하는 숫자 11자리 (하이픈 없음)", examples=["01012345678"]),
]


# ===== 요청 =====
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
