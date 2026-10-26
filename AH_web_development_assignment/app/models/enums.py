import enum

from sqlalchemy import Enum


def _enum_values(enum_type: type[enum.Enum]) -> list[str]:
    return [member.value for member in enum_type]


# users, patients 테이블이 함께 사용하는 성별 Enum
class Gender(str, enum.Enum):
    MALE = "male"
    FEMALE = "female"


# 사용자 부서 (연구 / 의료 / 개발)
class Department(str, enum.Enum):
    RESEARCH = "research"
    MEDICAL = "medical"
    DEVELOPMENT = "development"


# 사용자 권한 (대기자 / 스태프 / 어드민)
class Role(str, enum.Enum):
    PENDING = "pending"
    STAFF = "staff"
    ADMIN = "admin"


GENDER_ENUM = Enum(Gender, name="gender", values_callable=_enum_values)
DEPARTMENT_ENUM = Enum(Department, name="department", values_callable=_enum_values)
ROLE_ENUM = Enum(Role, name="role", values_callable=_enum_values)
