"""REQ-MDR-001 진료기록 등록 통합 테스트 (5일차 설계 12장 T11~T14, T23 등)

실제 ORM·서비스·라우터를 임시 SQLite DB와 임시 저장 폴더로 실행한다.
실행: python -m unittest tests.test_medical_record_create -v  (aiosqlite 필요)
"""

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.apis.medical_record_apis import router
from app.core.config import settings
from app.core.db.databases import Base, async_get_db
from app.core.dependencies import get_current_user
from app.core.security import create_access_token, create_refresh_token
from app.models import FileCleanupJob, MedicalRecord, Patient, User, XrayImage
from app.models.enums import Department, Gender, Role
sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests 폴더의 도우미를 어떤 실행 방식으로도 불러오도록
from sqlite_db import create_test_db  # noqa: E402


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 100


class MedicalRecordCreateTests(unittest.TestCase):
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
        self.login_as(self.medical_staff)
        self.client = TestClient(self.app)

    def tearDown(self):
        asyncio.run(self.engine.dispose())
        self.tmp.cleanup()

    async def _prepare_db(self):
        async with self.Session() as db:
            def user(i, email, department, role):
                return User(
                    id=i, email=email, hashed_password="x", name=f"사용자{i}",
                    phone_number=f"0101111000{i}", gender=Gender.FEMALE,
                    department=department, role=role, is_active=True,
                )
            self.medical_staff = user(1, "med@example.com", Department.MEDICAL, Role.STAFF)
            self.dev_staff = user(2, "dev@example.com", Department.DEVELOPMENT, Role.STAFF)
            self.admin = user(3, "admin@example.com", Department.RESEARCH, Role.ADMIN)
            self.pending = user(4, "wait@example.com", Department.MEDICAL, Role.PENDING)
            db.add_all([self.medical_staff, self.dev_staff, self.admin, self.pending])
            db.add(Patient(id=1, name="김환자", age=45, gender=Gender.FEMALE, phone="01098765432"))
            await db.commit()

    def login_as(self, user):
        self.app.dependency_overrides[get_current_user] = lambda: user

    def post(self, chart="CH-001", image=PNG, filename="chest.png", patient_id=1, symptoms="기침과 발열"):
        data = {"patient_id": str(patient_id), "chart_number": chart, "symptoms": symptoms}
        files = {"xray_image": (filename, image, "image/png")} if image is not None else None
        return self.client.post("/api/v1/medical-records", data=data, files=files)

    def stored_files(self):
        return [p for p in self.storage.rglob("*") if p.is_file()] if self.storage.exists() else []

    def db_count(self, model):
        async def count():
            async with self.Session() as db:
                return len((await db.execute(select(model))).scalars().all())
        return asyncio.run(count())

    # ---- 성공 ----
    def test_T11_png_upload_creates_record_and_image(self):
        res = self.post(chart="  CH-001  ")
        self.assertEqual(res.status_code, 201, res.text)
        body = res.json()
        self.assertEqual(body["chart_number"], "CH-001")  # 앞뒤 공백 제거
        self.assertEqual(body["patient_id"], 1)
        self.assertEqual(body["xray_image_url"], f"/api/v1/medical-records/{body['id']}/xray-image")
        self.assertEqual(body["uploader_id"], 1)
        self.assertEqual(body["uploader_name"], "사용자1")
        self.assertIsNone(body["updated_at"])
        self.assertEqual(res.headers["location"], f"/api/v1/medical-records/{body['id']}")
        files = self.stored_files()
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].parent.name, "1")  # 환자별 폴더
        self.assertEqual(files[0].suffix, ".png")
        self.assertNotIn("chest", files[0].name)  # 원본 파일명 미사용 (UUID)
        self.assertNotIn(str(self.storage), res.text)  # 실제 저장 경로 미노출

    def test_jpeg_saved_with_detected_extension(self):
        res = self.post(image=JPEG, filename="chest.png")  # 확장자는 png지만 내용은 JPEG
        self.assertEqual(res.status_code, 201, res.text)
        self.assertEqual(self.stored_files()[0].suffix, ".jpg")

    def test_admin_of_other_department_can_create(self):
        self.login_as(self.admin)
        self.assertEqual(self.post().status_code, 201)

    # ---- 권한 ----
    def test_T2_development_staff_forbidden(self):
        self.login_as(self.dev_staff)
        res = self.post()
        self.assertEqual(res.status_code, 403)
        self.assertEqual(self.stored_files(), [])

    # ---- T21 실제 토큰 검증 (로그인 가짜 주입 없이) ----
    def test_T21_without_token_401(self):
        self.app.dependency_overrides.pop(get_current_user)
        res = self.post()
        self.assertEqual(res.status_code, 401)
        self.assertEqual(self.stored_files(), [])

    def test_T21_invalid_or_refresh_token_401(self):
        self.app.dependency_overrides.pop(get_current_user)
        for token in ("not-a-jwt", create_refresh_token(self.medical_staff.id)):
            with self.subTest(token=token[:10]):
                res = self.client.post(
                    "/api/v1/medical-records",
                    data={"patient_id": "1", "chart_number": "CH-T21", "symptoms": "기침"},
                    files={"xray_image": ("chest.png", PNG, "image/png")},
                    headers={"Authorization": f"Bearer {token}"},
                )
                self.assertEqual(res.status_code, 401)

    def test_real_access_token_medical_staff_201(self):
        self.app.dependency_overrides.pop(get_current_user)
        res = self.client.post(
            "/api/v1/medical-records",
            data={"patient_id": "1", "chart_number": "CH-TOKEN", "symptoms": "기침"},
            files={"xray_image": ("chest.png", PNG, "image/png")},
            headers={"Authorization": f"Bearer {create_access_token(self.medical_staff.id)}"},
        )
        self.assertEqual(res.status_code, 201, res.text)
        self.assertEqual(res.json()["uploader_name"], "사용자1")

    def test_pending_user_forbidden(self):
        self.login_as(self.pending)
        self.assertEqual(self.post().status_code, 403)

    # ---- 실패 ----
    def test_missing_patient_404(self):
        res = self.post(patient_id=999)
        self.assertEqual(res.status_code, 404)
        self.assertEqual(self.stored_files(), [])

    def test_T12_duplicate_chart_number_409(self):
        self.assertEqual(self.post().status_code, 201)
        res = self.post()
        self.assertEqual(res.status_code, 409)
        self.assertEqual(len(self.stored_files()), 1)

    def test_T13_pdf_415(self):
        res = self.post(image=b"%PDF-1.7 ...", filename="report.pdf")
        self.assertEqual(res.status_code, 415)
        self.assertEqual(self.stored_files(), [])

    def test_T14_text_renamed_png_415(self):
        res = self.post(image=b"hello, this is text", filename="chest.png")
        self.assertEqual(res.status_code, 415)

    def test_T13_over_10mb_413_and_no_file_left(self):
        res = self.post(image=PNG + b"\x00" * (10 * 1024 * 1024))
        self.assertEqual(res.status_code, 413)
        self.assertEqual(self.stored_files(), [])
        self.assertEqual(self.db_count(MedicalRecord), 0)

    def test_exactly_10mb_allowed(self):
        image = PNG + b"\x00" * (10 * 1024 * 1024 - len(PNG))
        self.assertEqual(self.post(image=image).status_code, 201)

    def test_missing_image_422(self):
        self.assertEqual(self.post(image=None).status_code, 422)

    def test_blank_symptoms_422(self):
        self.assertEqual(self.post(symptoms="   ").status_code, 422)

    def test_chart_number_over_50_422(self):
        self.assertEqual(self.post(chart="A" * 51).status_code, 422)

    def test_T23_db_unique_violation_409_and_file_removed(self):
        # 사전 확인을 통과한 뒤 DB에서 UNIQUE 위반이 나는 동시 요청 상황을 재현한다.
        self.assertEqual(self.post().status_code, 201)
        with patch(
            "app.repositories.medical_record_repository.MedicalRecordRepository.get_by_chart_number",
            return_value=None,
        ):
            res = self.post()
        self.assertEqual(res.status_code, 409)
        self.assertEqual(len(self.stored_files()), 1)  # 실패한 쪽 파일은 남지 않음
        self.assertEqual(self.db_count(MedicalRecord), 1)
        self.assertEqual(self.db_count(XrayImage), 1)
        self.assertEqual(self.db_count(FileCleanupJob), 0)

    def test_rollback_and_file_delete_failure_records_cleanup_job(self):
        # DB 저장이 실패한 뒤 새 파일 삭제까지 실패하면 정리 작업을 별도로 남긴다 (설계 6-4 ⑥)
        self.assertEqual(self.post().status_code, 201)
        with patch(
            "app.repositories.medical_record_repository.MedicalRecordRepository.get_by_chart_number",
            return_value=None,
        ), patch(
            "app.services.medical_record_service.delete_xray_file", side_effect=PermissionError
        ):
            res = self.post()
        self.assertEqual(res.status_code, 409)
        self.assertEqual(self.db_count(MedicalRecord), 1)
        self.assertEqual(self.db_count(FileCleanupJob), 1)
        self.assertEqual(len(self.stored_files()), 2)  # 남은 파일은 재처리로 지운다

    def test_oversize_upload_and_delete_failure_records_cleanup_job(self):
        # 리뷰 3번: 413 후 쓰던 파일 삭제까지 실패하면 정리 작업으로 추적한다.
        with patch("app.core.file_storage.delete_xray_file", side_effect=PermissionError):
            res = self.post(image=PNG + b"\x00" * (10 * 1024 * 1024))
        self.assertEqual(res.status_code, 413)  # 원래 오류는 그대로
        self.assertEqual(self.db_count(MedicalRecord), 0)
        left = self.stored_files()
        self.assertEqual(len(left), 1)

        async def jobs():
            async with self.Session() as db:
                return list((await db.execute(select(FileCleanupJob))).scalars().all())

        recorded = asyncio.run(jobs())
        self.assertEqual(len(recorded), 1)
        self.assertEqual((recorded[0].status, recorded[0].file_kind), ("pending", "xray"))
        self.assertEqual(self.storage / recorded[0].file_path, left[0])

    def test_patient_deleted_during_upload_404_and_file_removed(self):
        with patch(
            "app.repositories.medical_record_repository.MedicalRecordRepository.lock_patient",
            return_value=None,
        ):
            res = self.post()
        self.assertEqual(res.status_code, 404)
        self.assertEqual(self.stored_files(), [])
        self.assertEqual(self.db_count(MedicalRecord), 0)


if __name__ == "__main__":
    unittest.main()
