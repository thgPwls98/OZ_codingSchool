"""⑫ AI 폐렴 예측 API 테스트 (REQ-PRED-001, 6일차 설계 13절) — 3단계 C

서비스 흐름은 test_prediction_service.py에서 확인했다. 여기서는 A가 만든 실제 결과 저장소·스키마와 연결해
상태 코드(201/200), Location 헤더, 응답 형식(confidence 숫자, created_at Z), 권한을 확인한다.
실제 모델 대신 가짜 예측 모듈을 주입한다.

실행: uv run --with aiosqlite python -m unittest tests.test_prediction_api -v
"""

import asyncio
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.apis.prediction_apis import get_predictor, router
from app.core.config import settings
from app.core.db.databases import async_get_db
from app.core.dependencies import get_current_user
from app.models import MedicalRecord, Patient, User, XrayImage
from app.models.enums import Department, Gender, Role
from app.services import prediction_service

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sqlite_db import create_test_db  # noqa: E402
from test_prediction_service import FakePrediction, FakePredictor  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
SHOT = datetime(2026, 10, 28, 6, 0, 0)
URL = "/api/v1/medical-records/{}/predict"


class PredictionApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        tmp = Path(self.tmp.name)
        self.storage = tmp / "xray"
        for name, value in (("XRAY_STORAGE_DIR", tmp / "xray"), ("HEATMAP_STORAGE_DIR", tmp / "heatmap")):
            p = patch.object(settings, name, str(value))
            p.start()
            self.addCleanup(p.stop)
        prediction_service._inference_semaphore = None
        self.engine, self.Session = asyncio.run(create_test_db(tmp))
        self.addCleanup(lambda: asyncio.run(self.engine.dispose()))
        asyncio.run(self._prepare())

        async def override_db():
            async with self.Session() as db:
                yield db

        self.predictor = FakePredictor(result=FakePrediction(True, 91.5, 0.915))
        self.app = FastAPI()
        self.app.include_router(router)
        self.app.dependency_overrides[async_get_db] = override_db
        self.app.dependency_overrides[get_predictor] = lambda: self.predictor
        self.login_as(self.users["medical"])
        self.client = TestClient(self.app)

    async def _prepare(self):
        def user(i, department, role):
            return User(id=i, email=f"u{i}@example.com", hashed_password="x", name=f"사용자{i}",
                        phone_number=f"0104444000{i}", gender=Gender.MALE,
                        department=department, role=role, is_active=True)

        self.users = {
            "medical": user(1, Department.MEDICAL, Role.STAFF),
            "development": user(2, Department.DEVELOPMENT, Role.STAFF),
            "research": user(3, Department.RESEARCH, Role.STAFF),
            "admin": user(4, Department.MEDICAL, Role.ADMIN),
            "pending": user(5, Department.MEDICAL, Role.PENDING),
        }
        async with self.Session() as db:
            db.add_all(self.users.values())
            db.add(Patient(id=1, name="김환자", age=45, gender=Gender.FEMALE, phone_number="01098765432"))
            for rid in (1, 2, 3, 4):
                db.add(MedicalRecord(id=rid, patient_id=1, chart_number=f"CH-{rid}", symptoms="기침"))
                db.add(XrayImage(id=rid, record_id=rid, uploader_id=1, image_url=f"1/{rid}.png", shooting_datetime=SHOT))
            await db.commit()
        (self.storage / "1").mkdir(parents=True)
        for rid in (1, 2, 3, 4):
            (self.storage / "1" / f"{rid}.png").write_bytes(PNG)

    def login_as(self, user):
        self.app.dependency_overrides[get_current_user] = lambda: user

    def test_new_prediction_201_with_location_and_format(self):  # T1, T16, T18, T20
        res = self.client.post(URL.format(1))
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.headers["location"], "/api/v1/medical-records/1/analyses")
        body = res.json()
        self.assertEqual(
            set(body),
            {"id", "record_id", "is_pneumonia", "confidence", "heatmap_url", "ai_model", "model_version", "created_at"},
        )
        self.assertEqual((body["record_id"], body["is_pneumonia"], body["heatmap_url"]), (1, True, None))
        self.assertIsInstance(body["confidence"], float)  # 문자열 "91.50"이 아님 (D10)
        self.assertEqual(body["confidence"], 91.5)
        self.assertEqual((body["ai_model"], body["model_version"]), ("fake-model", "v1"))
        self.assertTrue(body["created_at"].endswith("Z"))  # commit 후 refresh로 읽어 온 값 (T29)

    def test_second_request_reuses_with_200(self):  # T2
        first = self.client.post(URL.format(1)).json()
        res = self.client.post(URL.format(1))
        self.assertEqual(res.status_code, 200)
        self.assertNotIn("location", res.headers)
        self.assertEqual(res.json()["id"], first["id"])
        self.assertEqual(self.predictor.calls, 1)

    def test_all_staff_departments_and_admin_allowed(self):  # T4, T12
        for rid, role in zip((1, 2, 3, 4), ("medical", "development", "research", "admin")):
            with self.subTest(role=role):
                self.login_as(self.users[role])
                self.assertEqual(self.client.post(URL.format(rid)).status_code, 201)

    def test_pending_user_forbidden(self):  # T5
        self.login_as(self.users["pending"])
        self.assertEqual(self.client.post(URL.format(1)).status_code, 403)
        self.assertEqual(self.predictor.calls, 0)

    def test_no_token_unauthorized(self):  # T5
        del self.app.dependency_overrides[get_current_user]
        self.assertEqual(self.client.post(URL.format(1)).status_code, 401)

    def test_invalid_and_missing_record(self):  # T6
        self.assertEqual(self.client.post(URL.format(0)).status_code, 422)
        res = self.client.post(URL.format(999))
        self.assertEqual((res.status_code, res.json()), (404, {"detail": "진료기록을 찾을 수 없습니다."}))

    def test_model_not_loaded_503_json(self):  # T9
        self.predictor.loaded = False
        res = self.client.post(URL.format(1))
        self.assertEqual((res.status_code, res.json()), (503, {"detail": "AI 예측 기능을 사용할 수 없습니다."}))


if __name__ == "__main__":
    unittest.main()
