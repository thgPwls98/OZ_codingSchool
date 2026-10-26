from pydantic import BaseModel, ConfigDict


class UserResponse(BaseModel):
    """공통 사용자 응답 (설계 문서 1-3)

    비밀번호·해시·리프레시 토큰은 절대 포함하지 않는다.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    name: str
    department: str
    gender: str
    phone_number: str
    role: str
    is_active: bool
