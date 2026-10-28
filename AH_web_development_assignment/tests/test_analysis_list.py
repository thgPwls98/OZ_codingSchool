"""REQ-PRED-002 ⑬ AI 예측 결과 목록 통합 테스트 (B 담당)

6일차 설계 13절 T17~T20과 권한(1-2절)을 임시 SQLite DB로 확인한다.
실행: uv run python -m unittest tests.test_analysis_list -v  (aiosqlite 필요)
"""

import asyncio
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.apis.analysis_apis import router
from app.core.db.databases import async_get_db
from app.core.dependencies import get_current_user
from app.models import AIAnalysisResult, MedicalRecord, Patient, User, XrayImage
from app.models.enums import Department, Gender, Role
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sqlite_db import create_test_db  # noqa: E402

BASE_TIME = datetime(2026, 10, 28, 6, 20, 0)  # DB에는 시간대 없는 UTC 값이 저장된다
RESPONSE_FIELDS = {
    "id", "record_id", "is_pneumonia", "confidence", "heatmap_url",
    "ai_model", "model_version", "created_at",
}


class AnalysisListTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine, self.Session = asyncio.run(create_test_db(Path(self.tmp.name)))
        asyncio.run(self._prepare_db())

        async def override_db():
            async with self.Session() as db:
                yield db

        self.app = FastAPI()
        self.app.include_router(router)
        self.app.dependency_overrides[async_get_db] = override_db
        self.login_as(self.users["development"])
        self.client = TestClient(self.app)

    def tearDown(self):
        asyncio.run(self.engine.dispose())
        self.tmp.cleanup()

    async def _prepare_db(self):
        async with self.Session() as db:
            def user(i, department, role):
                return User(
                    id=i, email=f"user{i}@example.com", hashed_password="x", name=f"사용자{i}",
                    phone_number=f"0103333000{i}", gender=Gender.FEMALE,
                    department=department, role=role, is_active=True,
                )

            self.users = {
                "medical": user(1, Department.MEDICAL, Role.STAFF),
                "development": user(2, Department.DEVELOPMENT, Role.STAFF),
                "research": user(3, Department.RESEARCH, Role.STAFF),
                "admin": user(4, Department.DEVELOPMENT, Role.ADMIN),
                "pending": user(5, Department.MEDICAL, Role.PENDING),
            }
            db.add_all(self.users.values())
            db.add(Patient(id=1, name="김환자", age=45, gender=Gender.FEMALE, phone_number="01098765432"))
            for record_id in (1, 2, 3):
                db.add(MedicalRecord(
                    id=record_id, patient_id=1, chart_number=f"CH-{record_id:03d}", symptoms="기침",
                    created_at=BASE_TIME,
                ))
                db.add(XrayImage(
                    id=record_id, record_id=record_id, uploader_id=1,
                    image_url=f"1/xray{record_id}.png", shooting_datetime=BASE_TIME,
                ))

            def result(i, record_id, minutes, *, version, is_pneumonia, confidence, heatmap=None):
                db.add(AIAnalysisResult(
                    id=i, record_id=record_id, is_pneumonia=is_pneumonia, confidence=Decimal(confidence),
                    heatmap_url=heatmap, ai_model="EfficientNet-B0", model_version=version,
                    created_at=BASE_TIME + timedelta(minutes=minutes),
                ))

            # 기록 1: 모델 버전 2개의 결과 (Q4: 이전 버전 결과도 목록에 남는다)
            result(12, 1, 0, version="v1", is_pneumonia=False, confidence="86.98")
            result(15, 1, 60, version="v2", is_pneumonia=True, confidence="93.41", heatmap="1/heat15.png")
            # 기록 2: 같은 시각에 저장된 결과 → id로 순서를 정한다
            result(20, 2, 0, version="v1", is_pneumonia=True, confidence="50.00")
            result(21, 2, 0, version="v2", is_pneumonia=False, confidence="100.00")
            # 기록 3: 결과 없음
            await db.commit()

    def login_as(self, user):
        self.app.dependency_overrides[get_current_user] = lambda: user

    def get(self, record_id):
        return self.client.get(f"/api/v1/medical-records/{record_id}/analyses")

    # ---------- 응답 ----------
    def test_list_newest_first_with_all_fields(self):  # T18
        res = self.get(1)
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertIsInstance(body, list)  # 화면이 analyses.map을 쓴다 (설계 1-4)
        self.assertEqual([r["id"] for r in body], [15, 12])  # 최신순
        for item in body:
            self.assertEqual(set(item), RESPONSE_FIELDS)
        newest, oldest = body
        self.assertEqual(newest["created_at"], "2026-10-28T07:20:00Z")  # UTC Z 표기
        self.assertEqual(oldest["created_at"], "2026-10-28T06:20:00Z")
        self.assertEqual((newest["model_version"], oldest["model_version"]), ("v2", "v1"))
        self.assertEqual(newest["ai_model"], "EfficientNet-B0")
        self.assertEqual((newest["is_pneumonia"], oldest["is_pneumonia"]), (True, False))

    def test_same_created_at_ordered_by_id_desc(self):
        self.assertEqual([r["id"] for r in self.get(2).json()], [21, 20])

    def test_confidence_is_json_number(self):  # T20
        by_id = {r["id"]: r for r in self.get(1).json() + self.get(2).json()}
        for analysis_id, expected in {12: 86.98, 15: 93.41, 20: 50.0, 21: 100.0}.items():
            with self.subTest(analysis_id=analysis_id):
                value = by_id[analysis_id]["confidence"]
                self.assertIsInstance(value, float)  # "86.98" 같은 문자열이 아니다 (D10)
                self.assertEqual(value, expected)

    def test_heatmap_url_is_api_path_or_null(self):
        res = self.get(1)
        by_id = {r["id"]: r for r in res.json()}
        self.assertEqual(by_id[15]["heatmap_url"], "/api/v1/medical-records/1/analyses/15/heatmap")
        self.assertIsNone(by_id[12]["heatmap_url"])
        self.assertNotIn("1/heat15.png", res.text)  # 실제 저장 경로는 노출하지 않는다

    def test_only_results_of_requested_record(self):
        record_ids = {r["record_id"] for r in self.get(2).json()}
        self.assertEqual(record_ids, {2})

    def test_empty_list_and_missing_record(self):  # T17, T19
        res = self.get(3)
        self.assertEqual((res.status_code, res.json()), (200, []))
        res = self.get(999)
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.json()["detail"], "진료기록을 찾을 수 없습니다.")

    def test_invalid_record_id(self):
        for record_id in ("0", "-1", "abc"):
            with self.subTest(record_id=record_id):
                self.assertEqual(self.get(record_id).status_code, 422)

    # ---------- 권한 (설계 1-2) ----------
    def test_all_departments_and_admin_allowed(self):  # T4와 같은 기준
        for name in ("medical", "development", "research", "admin"):
            with self.subTest(user=name):
                self.login_as(self.users[name])
                self.assertEqual(self.get(1).status_code, 200)

    def test_pending_forbidden(self):  # T19
        self.login_as(self.users["pending"])
        self.assertEqual(self.get(1).status_code, 403)

    def test_without_token_unauthorized(self):
        del self.app.dependency_overrides[get_current_user]
        self.assertEqual(self.get(1).status_code, 401)


if __name__ == "__main__":
    unittest.main()
