import enum


# users, patients 테이블이 함께 사용하는 성별 Enum

class Gender(str, enum.Enum):
    MALE = "male"
    FEMALE = "female"
