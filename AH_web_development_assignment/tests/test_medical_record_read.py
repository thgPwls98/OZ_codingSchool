"""REQ-MDR-002, 003 진료기록 목록·상세·X-Ray 이미지 조회 통합 테스트 (팀원 4)

5일차 설계 12장 T15~T20, T16-1, T26~T28을 임시 SQLite DB와 임시 저장 폴더로 확인한다.
실행: uv run python -m unittest tests.test_medical_record_read -v  (aiosqlite 필요)
"""

import asyncio
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.apis.medical_record_apis import router
from app.core.config import settings
from app.core.db.databases import async_get_db
from app.core.dependencies import get_current_user
from app.models import MedicalRecord, Patient, User, XrayImage
from app.models.enums import Department, Gender, Role
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sqlite_db import create_test_db  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
BASE_TIME = datetime(2026, 10, 27, 6, 0, 0)  # DB에는 시간대 없는 UTC 값이 저장된다


class MedicalRecordReadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        self.storage = tmp / "xray"
        storage_patch = patch.object(settings, "XRAY_STORAGE_DIR", str(self.storage))
        storage_patch.start()
        self.addCleanup(storage_patch.stop)

        self.engine, self.Session = asyncio.run(create_test_db(tmp))
        asyncio.run(self._prepare_db())

        async def override_db():
            async with self.Session() as db:
                yield db

        self.app = FastAPI()
        self.app.include_router(router)
        self.app.dependency_overrides[async_get_db] = override_db
        self.login_as(self.staff)
        self.client = TestClient(self.app)

    def tearDown(self):
        asyncio.run(self.engine.dispose())
        self.tmp.cleanup()

    async def _prepare_db(self):
        async with self.Session() as db:
            def user(i, email, department, role):
                return User(
                    id=i, email=email, hashed_password="x", name=f"사용자{i}",
                    phone_number=f"0102222000{i}", gender=Gender.MALE,
                    department=department, role=role, is_active=True,
                )
            # 조회는 부서와 무관하게 스태프 이상이면 가능하다 (설계 1-2)
            self.staff = user(1, "dev@example.com", Department.DEVELOPMENT, Role.STAFF)
            self.pending = user(2, "wait@example.com", Department.MEDICAL, Role.PENDING)
            db.add_all([self.staff, self.pending])
            db.add(Patient(id=1, name="김환자", age=45, gender=Gender.FEMALE, phone_number="01098765432"))
            db.add(Patient(id=2, name="기록없음", age=30, gender=Gender.MALE, phone_number="01055556666"))

            def record(i, symptoms, minutes, image_url, uploader_id=1):
                db.add(MedicalRecord(
                    id=i, patient_id=1, chart_number=f"CH-{i:03d}", symptoms=symptoms,
                    created_at=BASE_TIME + timedelta(minutes=minutes),
                ))
                db.add(XrayImage(
                    id=i, record_id=i, uploader_id=uploader_id, image_url=image_url,
                    shooting_datetime=BASE_TIME,
                ))

            record(1, "가" * 100, 0, "1/exact.png")             # 정확히 100자
            record(2, "나" * 101, 10, "1/over.png")             # 101자
            record(3, "기침과 발열", 20, "1/missing.png")         # 파일 없음
            record(4, "탈퇴한 업로더", 30, "../../escape.png", uploader_id=None)  # 저장 폴더 밖 경로
            await db.commit()

        (self.storage / "1").mkdir(parents=True)
        (self.storage / "1" / "exact.png").write_bytes(PNG)
        (self.storage / "1" / "over.png").write_bytes(PNG)

    def login_as(self, user):
        self.app.dependency_overrides[get_current_user] = lambda: user

    # ---------- ⑦ 목록 ----------
    def test_list_newest_first_with_symptoms_summary(self):
        res = self.client.get("/api/v1/patients/1/medical-records")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual([r["id"] for r in body], [4, 3, 2, 1])  # 최신순
        by_id = {r["id"]: r for r in body}
        self.assertEqual(by_id[1]["symptoms"], "가" * 100)        # T26 100자는 그대로
        self.assertEqual(by_id[2]["symptoms"], "나" * 100 + "…")  # T26 101자부터 생략
        self.assertEqual(set(by_id[1]), {"id", "chart_number", "symptoms", "created_at"})
        self.assertEqual(by_id[1]["created_at"], "2026-10-27T06:00:00Z")  # UTC Z 표기

    def test_list_empty_and_missing_patient(self):
        res = self.client.get("/api/v1/patients/2/medical-records")
        self.assertEqual((res.status_code, res.json()), (200, []))
        res = self.client.get("/api/v1/patients/999/medical-records")
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.json()["detail"], "환자를 찾을 수 없습니다.")

    # ---------- ⑧ 상세 ----------
    def test_detail_full_symptoms_and_uploader(self):  # T16
        res = self.client.get("/api/v1/medical-records/2")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["symptoms"], "나" * 101)  # 상세는 생략하지 않음
        self.assertEqual(body["patient_id"], 1)
        self.assertEqual(body["xray_image_url"], "/api/v1/medical-records/2/xray-image")
        self.assertEqual((body["uploader_id"], body["uploader_name"]), (1, "사용자1"))
        self.assertTrue(body["created_at"].endswith("Z"))
        self.assertNotIn("1/over.png", res.text)  # 실제 저장 경로 미노출

    def test_detail_withdrawn_uploader(self):  # T16-1
        body = self.client.get("/api/v1/medical-records/4").json()
        self.assertEqual((body["uploader_id"], body["uploader_name"]), (None, None))

    def test_detail_missing_record(self):
        res = self.client.get("/api/v1/medical-records/999")
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.json()["detail"], "진료기록을 찾을 수 없습니다.")

    # ---------- ⑨ 이미지 ----------
    def test_xray_image_bytes_and_security_headers(self):  # T17, T28
        res = self.client.get("/api/v1/medical-records/1/xray-image")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.content, PNG)
        self.assertEqual(res.headers["content-type"], "image/png")
        self.assertEqual(res.headers["x-content-type-options"], "nosniff")
        self.assertEqual(res.headers["cache-control"], "private, no-store")
        self.assertEqual(res.headers["content-disposition"], "inline")

    def test_xray_image_not_found_cases(self):
        cases = {
            999: "진료기록을 찾을 수 없습니다.",  # 기록 없음
            3: "이미지 파일을 찾을 수 없습니다.",    # 파일 없음
            4: "이미지 파일을 찾을 수 없습니다.",    # 저장 폴더 밖 경로 → 이유를 알려주지 않음
        }
        for record_id, detail in cases.items():
            with self.subTest(record_id=record_id):
                res = self.client.get(f"/api/v1/medical-records/{record_id}/xray-image")
                self.assertEqual(res.status_code, 404)
                self.assertEqual(res.json()["detail"], detail)

    # ---------- 권한 ----------
    def test_pending_user_forbidden(self):  # T19
        self.login_as(self.pending)
        for url in ("/api/v1/patients/1/medical-records",
                    "/api/v1/medical-records/1",
                    "/api/v1/medical-records/1/xray-image"):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_without_token_unauthorized(self):  # T18
        del self.app.dependency_overrides[get_current_user]
        res = self.client.get("/api/v1/medical-records/1/xray-image")
        self.assertEqual(res.status_code, 401)


if __name__ == "__main__":
    unittest.main()
