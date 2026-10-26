from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher


# ===== 비밀번호 해싱 (팀원 1) =====
# 회원가입(1번), 로그인(2번), 비밀번호 변경(4번)에서 사용한다.
# 비밀번호 전용 해시 알고리즘인 Argon2를 사용한다.
password_hash = PasswordHash((Argon2Hasher(),))


def hash_password(plain_password: str) -> str:
    """비밀번호 원문을 Argon2 해시 문자열로 변환한다. (DB의 hashed_password에 저장)"""
    return password_hash.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """입력한 비밀번호가 저장된 해시와 일치하는지 확인한다."""
    return password_hash.verify(plain_password, hashed_password)
