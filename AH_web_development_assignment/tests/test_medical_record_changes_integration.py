"""등록과 수정·삭제를 공통 DB/파일 서비스로 연결한 병합 검증."""
import asyncio
import unittest
from unittest.mock import patch

import test_medical_record_create as create_tests
from sqlalchemy import select

from app.core.config import settings
from app.models import AIAnalysisResult, FileCleanupJob, MedicalRecord, XrayImage


class MedicalRecordChangesIntegrationTests(unittest.TestCase):
    # 등록 테스트의 임시 DB·파일·로그인 준비를 공유한다. 등록 테스트 자체는 상속하지 않는다.
    setUp = create_tests.MedicalRecordCreateTests.setUp
    tearDown = create_tests.MedicalRecordCreateTests.tearDown
    _prepare_db = create_tests.MedicalRecordCreateTests._prepare_db
    login_as = create_tests.MedicalRecordCreateTests.login_as
    post = create_tests.MedicalRecordCreateTests.post
    stored_files = create_tests.MedicalRecordCreateTests.stored_files
    db_count = create_tests.MedicalRecordCreateTests.db_count

    def add_ai_result(self, record_id):
        heatmap = self.storage.parent / 'heatmap'
        self.heatmap_patch = patch.object(settings, 'HEATMAP_STORAGE_DIR', str(heatmap))
        self.heatmap_patch.start()
        self.addCleanup(self.heatmap_patch.stop)
        path = heatmap / '1' / 'result.png'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'heatmap')

        async def insert():
            async with self.Session() as db:
                db.add(AIAnalysisResult(record_id=record_id, is_pneumonia=False,
                                       confidence=90, heatmap_url='1/result.png', ai_model='test'))
                await db.commit()
        asyncio.run(insert())
        return path

    def test_text_update_preserves_image_and_ai_and_returns_utc(self):
        response = self.post()
        self.assertEqual(response.status_code, 201, response.text)
        record_id = response.json()['id']
        heatmap = self.add_ai_result(record_id)
        old_files = self.stored_files()
        response = self.client.patch(f'/api/v1/medical-records/{record_id}', files={'symptoms': (None, '  변경  ')})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['symptoms'], '변경')
        self.assertTrue(response.json()['created_at'].endswith('Z'))
        self.assertTrue(response.json()['updated_at'].endswith('Z'))
        self.assertEqual(self.stored_files(), old_files)
        self.assertTrue(heatmap.exists())
        self.assertEqual(self.db_count(AIAnalysisResult), 1)

    def test_replace_image_then_delete_cleans_db_and_both_storage_roots(self):
        record_id = self.post().json()['id']
        old_image = self.stored_files()[0]
        heatmap = self.add_ai_result(record_id)
        self.login_as(self.admin)
        response = self.client.patch(f'/api/v1/medical-records/{record_id}', files={
            'xray_image': ('replacement.jpg', create_tests.JPEG, 'image/jpeg'),
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['uploader_id'], self.admin.id)
        self.assertFalse(old_image.exists())
        self.assertFalse(heatmap.exists())
        self.assertEqual(self.db_count(AIAnalysisResult), 0)
        self.assertEqual(self.db_count(XrayImage), 1)
        response = self.client.delete(f'/api/v1/medical-records/{record_id}')
        self.assertEqual(response.status_code, 204, response.text)
        self.assertEqual(self.stored_files(), [])
        self.assertEqual(self.db_count(MedicalRecord), 0)
        self.assertEqual(self.db_count(XrayImage), 0)
        self.assertEqual(self.client.delete(f'/api/v1/medical-records/{record_id}').status_code, 404)

    def test_delete_failed_cleanup_then_retry(self):
        record_id = self.post().json()['id']
        with patch('app.services.file_cleanup_service.delete_stored_file', side_effect=PermissionError):
            response = self.client.delete(f'/api/v1/medical-records/{record_id}')
        self.assertEqual(response.status_code, 500, response.text)
        self.assertEqual(self.db_count(MedicalRecord), 0)
        self.assertEqual(len(self.stored_files()), 1)
        self.assertEqual(self.client.delete(f'/api/v1/medical-records/{record_id}').status_code, 204)
        self.assertEqual(self.stored_files(), [])

    def test_partial_upload_failure_records_job_and_returns_original_413(self):
        record_id = self.post().json()['id']
        with patch.object(settings, 'MAX_UPLOAD_SIZE', 8), patch(
            'app.core.file_storage.delete_xray_file', side_effect=PermissionError,
        ):
            response = self.client.patch(f'/api/v1/medical-records/{record_id}', files={
                'xray_image': ('replacement.png', create_tests.PNG, 'image/png'),
            })
        self.assertEqual(response.status_code, 413, response.text)
        self.assertEqual(self.db_count(MedicalRecord), 1)
        self.assertEqual(self.db_count(XrayImage), 1)
        self.assertEqual(self.db_count(FileCleanupJob), 1)
        self.assertEqual(len(self.stored_files()), 2)

        async def job():
            async with self.Session() as db:
                return (await db.scalars(select(FileCleanupJob))).one()
        cleanup_job = asyncio.run(job())
        self.assertEqual((cleanup_job.target_type, cleanup_job.target_id), ('medical_record', record_id))

    def test_duplicate_chart_number_does_not_replace_image(self):
        record_id = self.post(chart='C1').json()['id']
        self.post(chart='C2')
        files_before = set(self.stored_files())
        response = self.client.patch(f'/api/v1/medical-records/{record_id}', files={
            'chart_number': (None, 'C2'),
            'xray_image': ('replacement.png', create_tests.PNG, 'image/png'),
        })
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(set(self.stored_files()), files_before)
