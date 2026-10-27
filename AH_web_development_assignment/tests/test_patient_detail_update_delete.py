"""REQ-PTNT-003~005 환자 상세·수정·삭제 통합 테스트 (팀원 3 담당분)

5일차 설계 12장 T7~T10, T9-1, T25와 12-1 보강 항목(파일 정리 실패 후 DELETE 재요청)을
임시 SQLite DB와 임시 저장 폴더로 확인한다.
실행: uv run --with aiosqlite python -m unittest tests.test_patient_detail_update_delete -v
"""

import asyncio
import sys
import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from app.apis.patient_apis import router
from app.core.config import settings
from app.core.db.databases import async_get_db
from app.core.dependencies import get_current_user
from app.models import MedicalRecord, Patient, User, XrayImage
from app.models.ai_analysis_result import AIAnalysisResult
from app.models.enums import Department, Gender, Role
from app.models.file_cleanup_job import FileCleanupJob
from app.repositories.patient_repository import PatientRepository
from app.services.file_cleanup_service import FileCleanupService
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sqlite_db import create_test_db  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
SHOT = datetime(2026, 10, 27, 6, 0, 0)


class PatientDetailUpdateDeleteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        self.xray = tmp / "xray"
        self.heatmap = tmp / "heatmap"
        for name, path in (("XRAY_STORAGE_DIR", self.xray), ("HEATMAP_STORAGE_DIR", self.heatmap)):
            p = patch.object(settings, name, str(path))
            p.start()
            self.addCleanup(p.stop)

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
            def user(i, department, role):
                return User(
                    id=i, email=f"u{i}@example.com", hashed_password="x", name=f"사용자{i}",
                    phone_number=f"0103333000{i}", gender=Gender.MALE,
                    department=department, role=role, is_active=True,
                )
            # 상세·수정·삭제는 부서와 무관하게 스태프 이상이면 가능하다 (설계 3장)
            self.staff = user(1, Department.DEVELOPMENT, Role.STAFF)
            self.pending = user(2, Department.MEDICAL, Role.PENDING)
            db.add_all([self.staff, self.pending])
            db.add(Patient(id=1, name="김환자", age=45, gender=Gender.FEMALE, phone_number="01098765432"))
            db.add(Patient(id=2, name="이웃환자", age=30, gender=Gender.MALE, phone_number="01055556666"))
            # 환자 1: 진료기록 2건 + X-Ray 2장 + AI 결과 1건 / 환자 2: 진료기록 1건 (삭제되면 안 됨)
            for rid, pid in ((1, 1), (2, 1), (3, 2)):
                db.add(MedicalRecord(id=rid, patient_id=pid, chart_number=f"CH-{rid}", symptoms="기침"))
                db.add(XrayImage(id=rid, record_id=rid, uploader_id=1, image_url=f"{pid}/r{rid}.png",
                                 shooting_datetime=SHOT))
            db.add(AIAnalysisResult(id=1, record_id=1, is_pneumonia=True, confidence=Decimal("91.50"),
                                    heatmap_url="1/h1.png", ai_model="test"))
            await db.commit()

        for rel in ("1/r1.png", "1/r2.png", "2/r3.png"):
            (self.xray / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.xray / rel).write_bytes(PNG)
        (self.heatmap / "1").mkdir(parents=True)
        (self.heatmap / "1" / "h1.png").write_bytes(PNG)

    def login_as(self, user):
        self.app.dependency_overrides[get_current_user] = lambda: user

    def count(self, model, *where):
        async def run():
            async with self.Session() as db:
                return await db.scalar(select(func.count()).select_from(model).where(*where))
        return asyncio.run(run())

    # ---------- ③ 상세 ----------
    def test_detail(self):
        res = self.client.get("/api/v1/patients/1")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual((body["id"], body["name"], body["age"], body["gender"]), (1, "김환자", 45, "female"))
        self.assertEqual(body["phone_number"], "01098765432")
        self.assertTrue(body["created_at"].endswith("Z"))

    def test_detail_missing_patient(self):  # T7
        res = self.client.get("/api/v1/patients/999")
        self.assertEqual((res.status_code, res.json()["detail"]), (404, "환자를 찾을 수 없습니다."))

    # ---------- ④ 수정 ----------
    def test_update_name_only(self):  # T8
        res = self.client.patch("/api/v1/patients/1", json={"name": "  김수정  "})
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["name"], "김수정")              # 앞뒤 공백 제거
        self.assertEqual(body["phone_number"], "01098765432")  # 보내지 않은 필드는 유지
        self.assertIsNotNone(body["updated_at"])
        self.assertTrue(body["updated_at"].endswith("Z"))

    def test_update_phone_number(self):
        res = self.client.patch("/api/v1/patients/1", json={"phone_number": "01011112222"})
        self.assertEqual((res.status_code, res.json()["phone_number"]), (200, "01011112222"))

    def test_update_rejects_invalid_requests(self):
        cases = [
            ({"age": 50}, 422),                    # T9 수정 불가 필드
            ({"gender": "male"}, 422),
            ({"name": None}, 422),                 # T9-1 null은 500이 아니라 422
            ({"phone_number": None}, 422),
            ({"name": "   "}, 422),                # 공백만
            ({"phone_number": "0101234"}, 422),    # 연락처 형식
            ({}, 400),                             # 빈 객체
        ]
        for body, expected in cases:
            with self.subTest(body=body):
                self.assertEqual(self.client.patch("/api/v1/patients/1", json=body).status_code, expected)
        self.assertEqual(self.client.get("/api/v1/patients/1").json()["name"], "김환자")  # 그대로

    def test_update_empty_body_message_and_missing_patient(self):
        res = self.client.patch("/api/v1/patients/1", json={})
        self.assertEqual(res.json()["detail"], "수정할 항목을 하나 이상 입력하세요.")
        res = self.client.patch("/api/v1/patients/999", json={"name": "누구"})
        self.assertEqual(res.status_code, 404)

    # ---------- ⑤ 삭제 ----------
    def test_delete_cascades_rows_and_files(self):  # T10, T25
        res = self.client.delete("/api/v1/patients/1")
        self.assertEqual((res.status_code, res.content), (204, b""))

        self.assertEqual(self.count(Patient, Patient.id == 1), 0)
        self.assertEqual(self.count(MedicalRecord, MedicalRecord.patient_id == 1), 0)
        self.assertEqual(self.count(XrayImage, XrayImage.record_id.in_([1, 2])), 0)
        self.assertEqual(self.count(AIAnalysisResult), 0)
        self.assertFalse((self.xray / "1").exists())     # 환자 폴더까지 정리
        self.assertFalse((self.heatmap / "1").exists())  # 히트맵도 삭제
        # 다른 환자의 데이터·파일은 그대로
        self.assertEqual(self.count(MedicalRecord, MedicalRecord.patient_id == 2), 1)
        self.assertTrue((self.xray / "2" / "r3.png").exists())
        # 정리 작업은 완료 상태, 경로는 지워진다 (설계 6-4 ⑥)
        self.assertEqual(self.count(FileCleanupJob, FileCleanupJob.status != "done"), 0)
        self.assertEqual(self.count(FileCleanupJob, FileCleanupJob.file_path.is_not(None)), 0)

        self.assertEqual(self.client.delete("/api/v1/patients/1").status_code, 404)  # 다시 지우면 404

    def test_delete_patient_without_records(self):
        async def add():
            async with self.Session() as db:
                db.add(Patient(id=3, name="기록없음", age=20, gender=Gender.MALE, phone_number="01077778888"))
                await db.commit()
        asyncio.run(add())
        self.assertEqual(self.client.delete("/api/v1/patients/3").status_code, 204)

    def test_delete_missing_patient(self):
        res = self.client.delete("/api/v1/patients/999")
        self.assertEqual((res.status_code, res.json()["detail"]), (404, "환자를 찾을 수 없습니다."))

    def test_delete_file_failure_then_retry(self):  # 12-1 커밋 후 파일 삭제 실패 → DELETE 재요청
        with patch("app.services.file_cleanup_service.delete_stored_file", side_effect=OSError("busy")):
            res = self.client.delete("/api/v1/patients/1")
        self.assertEqual(res.status_code, 500)
        self.assertEqual(res.json()["detail"], "파일 정리가 완료되지 않았습니다. 상태를 다시 조회해주세요.")
        self.assertNotIn("r1.png", res.text)                     # 경로 미노출
        self.assertEqual(self.count(Patient, Patient.id == 1), 0)  # DB 삭제는 이미 완료
        self.assertTrue((self.xray / "1" / "r1.png").exists())     # 파일은 남아 있고
        self.assertEqual(self.count(FileCleanupJob, FileCleanupJob.status == "pending"), 3)  # 작업 보존

        res = self.client.delete("/api/v1/patients/1")  # 재요청: 남은 작업을 이어서 정리
        self.assertEqual(res.status_code, 204)
        self.assertFalse((self.xray / "1").exists())
        self.assertFalse((self.heatmap / "1").exists())
        self.assertEqual(self.client.delete("/api/v1/patients/1").status_code, 404)  # 작업도 없으면 404

    def test_delete_cleanup_state_save_failure_returns_json(self):  # 리뷰 P2
        db_error = OperationalError("UPDATE file_cleanup_jobs", {}, Exception("db down"))
        with patch.object(FileCleanupService, "run", side_effect=db_error):
            res = self.client.delete("/api/v1/patients/1")
        self.assertEqual(res.status_code, 500)
        self.assertEqual(res.json()["detail"], "파일 정리가 완료되지 않았습니다. 상태를 다시 조회해주세요.")
        self.assertEqual(self.count(Patient, Patient.id == 1), 0)                              # DB 삭제는 완료
        self.assertEqual(self.count(FileCleanupJob, FileCleanupJob.status == "pending"), 3)   # 작업은 보존
        self.assertEqual(self.client.delete("/api/v1/patients/1").status_code, 204)          # 재요청으로 마무리
        self.assertFalse((self.xray / "1").exists())

    def test_delete_resume_failure_returns_json(self):  # 리뷰 P2
        db_error = OperationalError("SELECT file_cleanup_jobs", {}, Exception("db down"))
        with patch.object(FileCleanupService, "resume", side_effect=db_error):
            res = self.client.delete("/api/v1/patients/1")
        self.assertEqual(res.status_code, 500)
        self.assertEqual(res.json()["detail"], "파일 정리가 완료되지 않았습니다. 상태를 다시 조회해주세요.")
        self.assertEqual(self.count(Patient, Patient.id == 1), 0)

    def test_file_paths_use_locking_read(self):  # 리뷰 P1: 잠금 읽기(FOR UPDATE)로 최신 경로를 수집
        statements = []

        async def run():
            async with self.Session() as db:
                original = db.scalars

                async def spy(statement, *args, **kwargs):
                    statements.append(statement)
                    return await original(statement, *args, **kwargs)

                db.scalars = spy
                return await PatientRepository(db).file_paths(1)

        files = asyncio.run(run())
        self.assertEqual(len(statements), 2)
        self.assertTrue(all(stmt._for_update_arg is not None for stmt in statements))
        self.assertEqual(sorted(files), [("heatmap", "1/h1.png"), ("xray", "1/r1.png"), ("xray", "1/r2.png")])

    # ---------- 권한 ----------
    def test_pending_user_forbidden(self):
        self.login_as(self.pending)
        for method, body in (("get", None), ("patch", {"name": "x"}), ("delete", None)):
            with self.subTest(method=method):
                kwargs = {"json": body} if body else {}
                res = getattr(self.client, method)("/api/v1/patients/1", **kwargs)
                self.assertEqual(res.status_code, 403)
        self.assertEqual(self.count(Patient, Patient.id == 1), 1)  # 삭제되지 않음

    def test_invalid_patient_id(self):
        self.assertEqual(self.client.get("/api/v1/patients/0").status_code, 422)


if __name__ == "__main__":
    unittest.main()
