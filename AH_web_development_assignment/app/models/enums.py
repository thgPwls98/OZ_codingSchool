import enum


# users, patients 테이블이 함께 사용하는 성별 Enum
# ⚠️ 값은 dbdiagram의 `Enum gender { ... }` 정의와 맞춰주세요.
class Gender(str, enum.Enum):
    MALE = "MALE"
    FEMALE = "FEMALE"
