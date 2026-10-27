"""환자 API 공통 기반 검증: 스키마 검증 규칙, UTC 응답, 연쇄 삭제 (임시 SQLite)."""
import asyncio
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from pydantic import ValidationError
from sqlalchemy import BigInteger, DefaultClause, Integer, MetaData, event, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app import models  # noqa: F401  모든 모델을 메타데이터에 등록
from app.core.db.databases import Base
from app.models.ai_analysis_result import AIAnalysisResult
from app.models.medical_record import MedicalRecord
from app.models.patient import Patient
from app.models.user import User
from app.models.xray_image import XrayImage
from app.schemas.patient import (
    PatientCreateRequest,
    PatientResponse,
    PatientSearchParams,
    PatientUpdateRequest,
)

VALID_PATIENT = {"name": "김환자", "age": 45, "gender": "female", "phone_number": "01098765432"}


class PatientSchemaTests(unittest.TestCase):
    def test_create_request(self):
        self.assertEqual(PatientCreateRequest(**{**VALID_PATIENT, "name": "  김환자  "}).name, "김환자")
        # T4 나이 범위·연락처 형식, 빈 이름, 정의되지 않은 필드, 성별 누락
        for change in ({"age": 200}, {"age": -1}, {"phone_number": "0101234"}, {"phone_number": "010-1234-5678"},
                       {"name": "   "}, {"name": "가" * 31}, {"role": "admin"}):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                PatientCreateRequest(**{**VALID_PATIENT, **change})
        with self.assertRaises(ValidationError):
            PatientCreateRequest(**{k: v for k, v in VALID_PATIENT.items() if k != "gender"})

    def test_search_params(self):
        self.assertIsNone(PatientSearchParams(name="   ").name)
        self.assertEqual(PatientSearchParams(min_age=30, max_age=30).min_age, 30)
        # T6 최소 나이 > 최대 나이
        with self.assertRaises(ValidationError):
            PatientSearchParams(min_age=50, max_age=30)
        with self.assertRaises(ValidationError):
            PatientSearchParams(gender="unknown")

    def test_update_request(self):
        self.assertEqual(PatientUpdateRequest().model_dump(exclude_unset=True), {})
        self.assertEqual(PatientUpdateRequest(name="이환자").model_dump(exclude_unset=True), {"name": "이환자"})
        # T9 수정 불가 필드, T9-1 null 값
        for body in ({"age": 50}, {"gender": "male"}, {"name": None}, {"phone_number": None}, {"name": " "}):
            with self.subTest(body=body), self.assertRaises(ValidationError):
                PatientUpdateRequest(**body)

    def test_response_uses_utc_z(self):
        patient = SimpleNamespace(**VALID_PATIENT, id=1, created_at=datetime(2026, 10, 27, 6, 0), updated_at=None)
        data = PatientResponse.model_validate(patient).model_dump(mode="json")
        self.assertEqual(data["created_at"], "2026-10-27T06:00:00Z")
        self.assertIsNone(data["updated_at"])


class CascadeDeleteTests(unittest.TestCase):
    """T25 SQLite(PRAGMA foreign_keys=ON)에서 환자 삭제 시 자식 행까지 삭제된다."""

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

        asyncio.run(init())

    def tearDown(self):
        asyncio.run(self.engine.dispose())
        self.temp.cleanup()

    def test_delete_patient_cascades_to_records_images_and_results(self):
        async def scenario():
            async with self.sessions() as db:
                db.add(User(id=1, email="d@example.com", hashed_password="h", name="의사",
                            phone_number="01000000000", gender="male", department="medical", role="staff"))
                db.add(Patient(id=1, **VALID_PATIENT))
                db.add(Patient(id=2, name="다른환자", age=30, gender="male", phone_number="01011112222"))
                await db.flush()
                db.add(MedicalRecord(id=1, patient_id=1, chart_number="C1", symptoms="기침"))
                db.add(MedicalRecord(id=2, patient_id=2, chart_number="C2", symptoms="발열"))
                await db.flush()
                db.add(XrayImage(id=1, record_id=1, uploader_id=1, image_url="a.png", shooting_datetime=datetime.now()))
                db.add(AIAnalysisResult(id=1, record_id=1, is_pneumonia=False, confidence=90,
                                        heatmap_url="h.png", ai_model="test"))
                await db.commit()

            async with self.sessions() as db:
                patient = await db.get(Patient, 1)
                # 관계를 불러온 상태에서도 ORM이 자식 행을 건드리지 않아야 한다 (passive_deletes)
                await db.refresh(patient, ["medical_records"])
                await db.delete(patient)
                await db.commit()

            async with self.sessions() as db:
                self.assertIsNone(await db.get(Patient, 1))
                for model in (MedicalRecord, XrayImage, AIAnalysisResult):
                    self.assertEqual((await db.execute(select(model).where(model.id == 1))).all(), [])
                # 다른 환자와 회원은 영향 없음
                self.assertIsNotNone(await db.get(MedicalRecord, 2))
                self.assertIsNotNone(await db.get(User, 1))

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
