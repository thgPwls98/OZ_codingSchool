"""환자 등록(REQ-PTNT-001)·목록(REQ-PTNT-002) 통합 검증 (실제 앱·인증, 임시 SQLite)."""
import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import BigInteger, DefaultClause, Integer, MetaData, event, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app import models  # noqa: F401  모든 모델을 메타데이터에 등록
from app.core.db.databases import Base, async_get_db
from app.core.security import create_access_token
from app.main import app
from app.models.user import User
from app.schemas.patient import PatientCreateRequest
from app.services.patient_service import PatientService

# (id, 권한, 부서)
USERS = {
    "medical_staff": (1, "staff", "medical"),
    "dev_staff": (2, "staff", "development"),
    "pending": (3, "pending", "medical"),
    "admin": (4, "admin", "research"),
}
PATIENT = {"name": "김환자", "age": 45, "gender": "female", "phone_number": "01098765432"}


class PatientCreateListTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(
            "sqlite+aiosqlite:///" + str(Path(self.temp.name) / "test.db"), poolclass=NullPool
        )

        @event.listens_for(self.engine.sync_engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

        def create_schema(sync_conn):
            metadata = MetaData()
            for table in Base.metadata.sorted_tables:
                copied = table.to_metadata(metadata)
                for column in copied.columns:
                    # SQLite는 INTEGER 기본키만 자동 증가한다 (MySQL의 BIGINT AUTO_INCREMENT 대체)
                    if column.primary_key and isinstance(column.type, BigInteger):
                        column.type = Integer()
                    if column.server_default is not None and "current_timestamp(0)" in str(column.server_default.arg):
                        column.server_default = DefaultClause(text("CURRENT_TIMESTAMP"))
            metadata.create_all(sync_conn)

        async def init():
            async with self.engine.begin() as conn:
                await conn.run_sync(create_schema)
            async with self.sessions() as db:
                for user_id, role, department in USERS.values():
                    db.add(User(id=user_id, email=f"u{user_id}@example.com", hashed_password="h", name=f"사용자{user_id}",
                                phone_number=f"0100000000{user_id}", gender="male", department=department, role=role))
                await db.commit()

        asyncio.run(init())

        async def db():
            async with self.sessions() as session:
                yield session

        app.dependency_overrides[async_get_db] = db
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()
        asyncio.run(self.engine.dispose())
        self.temp.cleanup()

    def request(self, method, user=None, **kwargs):
        headers = {"Authorization": f"Bearer {create_access_token(USERS[user][0])}"} if user else {}
        start = time.perf_counter()
        response = self.client.request(method, "/api/v1/patients", headers=headers, **kwargs)
        # NFR-PTNT-001: 3초 이내 응답
        self.assertLess(time.perf_counter() - start, 3)
        return response

    def create(self, user="medical_staff", **change):
        return self.request("POST", user, json={**PATIENT, **change})

    def search(self, user="dev_staff", **params):
        response = self.request("GET", user, params=params)
        self.assertEqual(response.status_code, 200)
        return [patient["name"] for patient in response.json()]

    def test_create_patient(self):
        # T1 의료 부서 스태프, 어드민은 등록 가능
        response = self.create()
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual({k: body[k] for k in PATIENT}, PATIENT)
        self.assertTrue(body["created_at"].endswith("Z"))
        self.assertIsNone(body["updated_at"])
        # T29 Location 헤더
        self.assertEqual(response.headers["location"], f"/api/v1/patients/{body['id']}")
        self.assertEqual(self.create("admin", phone_number="01011112222").status_code, 201)

    def test_create_permission(self):
        # T2 개발 부서 스태프, T3 대기자는 403, 토큰 없으면 401
        self.assertEqual(self.create("dev_staff").status_code, 403)
        self.assertEqual(self.create("pending").status_code, 403)
        self.assertEqual(self.create(None).status_code, 401)
        self.assertEqual(self.search("medical_staff"), [])

    def test_create_validation(self):
        # T4 나이 범위·연락처 형식, 정의되지 않은 필드
        for change in ({"age": 200}, {"phone_number": "0101234"}, {"gender": "unknown"}, {"name": "  "}, {"role": "admin"}):
            with self.subTest(change=change):
                self.assertEqual(self.create(**change).status_code, 422)

    def test_list_filters(self):
        for name, age, gender, phone in [("김철수", 35, "male", "01011110001"), ("김영희", 42, "female", "01011110002"),
                                         ("이영희", 28, "female", "01011110003"), ("박100%", 60, "male", "01011110004")]:
            self.assertEqual(self.create(name=name, age=age, gender=gender, phone_number=phone).status_code, 201)

        # 전체 조회는 최근 등록순
        self.assertEqual(self.search(), ["박100%", "이영희", "김영희", "김철수"])
        # T5 이름 + 성별 + 나이 범위 조합
        self.assertEqual(self.search(name="김", gender="female", min_age=30, max_age=50), ["김영희"])
        self.assertEqual(self.search(name="영희"), ["이영희", "김영희"])
        self.assertEqual(self.search(min_age=42, max_age=42), ["김영희"])
        # T22 %는 와일드카드가 아닌 일반 문자로 검색
        self.assertEqual(self.search(name="%"), ["박100%"])
        self.assertEqual(self.search(name="_"), [])
        # 공백만 입력하면 검색 조건 없음
        self.assertEqual(len(self.search(name="   ")), 4)

    def test_list_validation_and_permission(self):
        # T6 최소 나이 > 최대 나이, 잘못된 값은 422
        for params in ({"min_age": 50, "max_age": 30}, {"gender": "unknown"}, {"min_age": "abc"}, {"max_age": 151}):
            with self.subTest(params=params):
                self.assertEqual(self.request("GET", "dev_staff", params=params).status_code, 422)
        # 대기자 403, 토큰 없으면 401
        self.assertEqual(self.request("GET", "pending").status_code, 403)
        self.assertEqual(self.request("GET").status_code, 401)


class CreateFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_db_failure_rolls_back_and_returns_500(self):
        """저장소는 commit하지 않고, 서비스가 commit 실패 시 롤백 후 500을 낸다 (설계 7-5)"""
        repository = AsyncMock()
        repository.db.commit.side_effect = SQLAlchemyError("database failure")
        with self.assertRaises(HTTPException) as error:
            await PatientService(repository).create_patient(PatientCreateRequest(**PATIENT))
        self.assertEqual((error.exception.status_code, error.exception.detail), (500, "잠시 후 다시 시도해주세요."))
        repository.add.assert_awaited_once()
        repository.db.rollback.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
