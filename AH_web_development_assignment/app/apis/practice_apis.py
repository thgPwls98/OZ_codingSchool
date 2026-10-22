import re

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

user_list = [
    {
        "id": 1,
        "name": "홍길동",
        "age": 24,
        "email": "gildong24@example.com",
        "password": "Password1234!!",
    },
    {
        "id": 2,
        "name": "장문복",
        "age": 21,
        "email": "moonluck12@example.com",
        "password": "Check1321!",
    },
    {
        "id": 3,
        "name": "임우진",
        "age": 31,
        "email": "limousine33@example.com",
        "password": "lwsPAssword12@",
    },
]

router = APIRouter(prefix="/practice_api")

class UserResponse(BaseModel):
    id: int
    name: str
    age: int
    email: str


class CreateUserRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=10)
    age: int = Field(..., ge=14)
    email: str = Field(..., max_length=30)
    password: str = Field(..., min_length=8, max_length=20)


class UpdateUserRequest(BaseModel):
    age: int | None = Field(default=None, ge=14)
    email: str | None = Field(default=None, max_length=30)



 # ===== 검증 함수 (③ 회원 추가, ④ 회원 수정에서 사용) =====
def check_email(email: str) -> None:
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(status_code=422, detail="올바른 이메일을 입력하세요.")


def check_password(password: str) -> None:
    if (
        not re.search(r"[a-z]", password)
        or not re.search(r"[A-Z]", password)
        or not re.search(r"[^A-Za-z0-9]", password)
    ):
        raise HTTPException(
            status_code=422,
            detail="비밀번호에 대문자, 소문자, 특수문자를 포함하세요.",
        )


# ===== 공통 함수 (② 조회, ④ 수정, ⑤ 삭제에서 사용) =====
def find_user(user_id: int) -> dict:
    for user in user_list:
        if user["id"] == user_id:
            return user

    raise HTTPException(status_code=404, detail="회원을 찾을 수 없습니다.")


# ===== API =====
# 각자 자기 번호 주석 바로 아래에만 코드를 붙여주세요.

# ① 모든 회원 목록 조회


# ② 특정 회원 조회


# ③ 회원 추가


# ④ 회원 정보 수정


# ⑤ 회원 삭제
    password: str | None = Field(default=None, min_length=8, max_length=20)
