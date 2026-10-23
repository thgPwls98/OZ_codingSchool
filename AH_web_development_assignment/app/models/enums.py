import enum

from sqlalchemy import Enum


# users, patients 테이블이 함께 사용하는 성별 Enum
class Gender(str, enum.Enum):
    MALE = "male"
    FEMALE = "female"


GENDER_ENUM = Enum(
    Gender,
    name="gender",
    values_callable=lambda enum_type: [member.value for member in enum_type],
)
