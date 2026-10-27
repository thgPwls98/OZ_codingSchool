"""진료기록 등록 처리 시간 측정 (NFR-MDR-001: 3초 이내)

조건: 임시 SQLite, 기존 진료기록 5,000건, 업로드 이미지 10MB(최대 크기), 순차 요청 5회.
TestClient 호출 시간(서버 처리 + 테스트 클라이언트 비용)을 잰다. 네트워크 전송 시간은 포함하지 않는다.
운영 MySQL·동시 부하에서의 결과를 보장하지는 않는다.

실행: python -m unittest tests.test_medical_record_performance -v
"""

import asyncio
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.apis.medical_record_apis import router
from app.core.config import settings
from app.core.db.databases import async_get_db
from app.core.dependencies import get_current_user
from app.models import MedicalRecord, Patient, User
from app.models.enums import Department, Gender, Role

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sqlite_db import create_test_db  # noqa: E402

LIMIT_SECONDS = 3.0
EXISTING_RECORDS = 5_000
RUNS = 5
IMAGE = b"\x89PNG\r\n\x1a\n" + b"\x00" * (10 * 1024 * 1024 - 8)  # 정확히 10MB


class MedicalRecordCreatePerformanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        p = patch.object(settings, "XRAY_STORAGE_DIR", str(tmp / "xray"))
        p.start()
        self.addCleanup(p.stop)
        self.engine, self.Session = asyncio.run(create_test_db(tmp))
        asyncio.run(self._seed())

        async def override_db():
            async with self.Session() as db:
                yield db

        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[async_get_db] = override_db
        app.dependency_overrides[get_current_user] = lambda: self.user
        self.client = TestClient(app)

    def tearDown(self):
        asyncio.run(self.engine.dispose())
        self.tmp.cleanup()

    async def _seed(self):
        async with self.Session() as db:
            self.user = User(
                id=1, email="med@example.com", hashed_password="x", name="의료진",
                phone_number="01011110001", gender=Gender.FEMALE,
                department=Department.MEDICAL, role=Role.STAFF, is_active=True,
            )
            db.add(self.user)
            db.add(Patient(id=1, name="김환자", age=45, gender=Gender.FEMALE, phone="01098765432"))
            db.add_all(
                MedicalRecord(patient_id=1, chart_number=f"OLD-{i:05d}", symptoms="기존 기록")
                for i in range(EXISTING_RECORDS)
            )
            await db.commit()

    def test_create_with_max_size_image_under_3_seconds(self):
        durations = []
        for i in range(RUNS):
            start = time.perf_counter()
            res = self.client.post(
                "/api/v1/medical-records",
                data={"patient_id": "1", "chart_number": f"PERF-{i}", "symptoms": "기침과 발열"},
                files={"xray_image": ("chest.png", IMAGE, "image/png")},
            )
            durations.append(time.perf_counter() - start)
            self.assertEqual(res.status_code, 201, res.text)

        print(
            f"\n[NFR-MDR-001] 진료기록 등록 {RUNS}회 (기존 {EXISTING_RECORDS}건, 이미지 10MB): "
            f"최대 {max(durations):.3f}초, 평균 {sum(durations) / RUNS:.3f}초"
        )
        self.assertLess(max(durations), LIMIT_SECONDS)


if __name__ == "__main__":
    unittest.main()
