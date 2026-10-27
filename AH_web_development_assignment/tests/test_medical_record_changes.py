import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.apis.medical_record_apis import get_medical_record_service, router
from app.core.dependencies import get_current_user
from app.models.enums import Department, Role
from app.schemas.medical_record import MedicalRecordUpdateRequest
from app.services.medical_record_service import MedicalRecordService


class MedicalRecordApiTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(router)
        self.user = SimpleNamespace(id=4, role=Role.STAFF, department=Department.MEDICAL)
        self.service = AsyncMock()
        self.service.update.return_value = dict(
            id=1, patient_id=2, chart_number="C1", symptoms="증상", xray_image_url="/api/v1/medical-records/1/xray-image",
            uploader_id=None, uploader_name=None, created_at=datetime(2026, 10, 27), updated_at=None,
        )
        app.dependency_overrides[get_current_user] = lambda: self.user
        app.dependency_overrides[get_medical_record_service] = lambda: self.service
        self.client = TestClient(app)

    def test_trim_and_omitted_fields(self):
        response = self.client.patch('/api/v1/medical-records/1', files={'symptoms': (None, '  변경  ')})
        self.assertEqual(response.status_code, 200)
        data = self.service.update.call_args.args[1]
        self.assertEqual(data.model_dump(exclude_unset=True), {'symptoms': '변경'})
        self.assertIsNone(self.service.update.call_args.args[2])

    def test_reject_empty_extra_duplicate_and_long_fields(self):
        for files in (
            {'symptoms': (None, ' ')}, {'chart_number': (None, 'x' * 51)},
            {'patient_id': (None, '3')}, {'symptoms': (None, 'x' * 10001)},
            [('symptoms', (None, 'a')), ('symptoms', (None, 'b'))],
        ):
            response = self.client.patch('/api/v1/medical-records/1', files=files)
            self.assertEqual(response.status_code, 422, response.text)
        self.service.update.assert_not_awaited()

    def test_authorization(self):
        for role, department in ((Role.PENDING, Department.MEDICAL), (Role.STAFF, Department.RESEARCH)):
            self.user.role, self.user.department = role, department
            self.assertEqual(self.client.delete('/api/v1/medical-records/1').status_code, 403)
        self.service.delete.assert_not_awaited()

    def test_admin_can_delete_without_body(self):
        self.user.role, self.user.department = Role.ADMIN, Department.DEVELOPMENT
        response = self.client.delete('/api/v1/medical-records/1')
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b'')


class MedicalRecordServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.events = []
        self.db = AsyncMock()
        self.db.add = Mock()
        self.repository = AsyncMock()
        self.repository.db = self.db
        self.record = SimpleNamespace(id=1, patient_id=2, chart_number='C1', symptoms='old')
        self.repository.patient_id_for.return_value = 2
        self.repository.lock.return_value = self.record
        self.repository.chart_exists.return_value = False
        self.repository.file_paths.return_value = [('xray', 'old.png'), ('heatmap', 'heatmap.png')]
        self.repository.response.return_value = {'id': 1}
        self.patients, self.storage, self.cleanup = AsyncMock(), AsyncMock(), AsyncMock()
        self.storage.save_xray_image.return_value = 'new.png'
        self.storage.FILE_KIND_XRAY = "xray"
        self.cleanup.resume.return_value = None
        self.cleanup.enqueue = Mock(return_value=["job"])
        self.cleanup.run.return_value = True
        self.service = MedicalRecordService(self.repository, self.patients, self.storage, self.cleanup)

    async def test_text_only_preserves_images_and_ai(self):
        await self.service.update(1, MedicalRecordUpdateRequest(symptoms='new'), None, 4)
        self.assertEqual(self.record.symptoms, 'new')
        self.repository.remove_image_data.assert_not_awaited()
        self.cleanup.enqueue.assert_not_called()
        self.db.commit.assert_awaited_once()

    async def test_replacement_orders_locks_enqueue_commit_cleanup(self):
        async def patient_lock(*args):
            self.events.append('patient')
            return object()
        async def record_lock(*args):
            self.events.append('record')
            return self.record
        def enqueue(*args):
            self.events.append('enqueue')
            return ['job']
        async def commit():
            self.events.append('commit')
        async def run(*args):
            self.events.append('run')
            return True
        self.patients.lock.side_effect = patient_lock
        self.repository.lock.side_effect = record_lock
        self.cleanup.enqueue.side_effect = enqueue
        self.db.commit.side_effect = commit
        self.cleanup.run.side_effect = run
        await self.service.update(1, MedicalRecordUpdateRequest(), object(), 4)
        self.assertEqual(self.events, ['patient', 'record', 'enqueue', 'commit', 'run'])
        self.repository.remove_image_data.assert_awaited_once_with(1)
        image = self.db.add.call_args.args[0]
        self.assertEqual((image.image_url, image.uploader_id), ('new.png', 4))

    async def test_commit_conflict_rolls_back_and_removes_new_file(self):
        self.db.commit.side_effect = IntegrityError('insert', {}, Exception("Duplicate entry for key chart_number"))
        with self.assertRaises(HTTPException) as caught:
            await self.service.update(1, MedicalRecordUpdateRequest(), object(), 4)
        self.assertEqual(caught.exception.status_code, 409)
        self.db.rollback.assert_awaited_once()
        self.storage.delete_xray_file.assert_awaited_once_with('new.png')
        self.cleanup.run.assert_not_awaited()

    async def test_failed_new_file_cleanup_is_persisted_after_rollback(self):
        self.db.commit.side_effect = [IntegrityError('insert', {}, Exception('other constraint')), None]
        self.storage.delete_xray_file.side_effect = OSError('disk')
        with self.assertRaises(HTTPException) as caught:
            await self.service.update(1, MedicalRecordUpdateRequest(), object(), 4)
        self.assertEqual(caught.exception.status_code, 500)
        self.cleanup.enqueue.assert_called_with('medical_record', 1, [('xray', 'new.png')])
        self.assertEqual(self.db.commit.await_count, 2)

    async def test_cleanup_job_commit_failure_returns_safe_500(self):
        self.db.commit.side_effect = SQLAlchemyError('internal database details')
        self.storage.delete_xray_file.side_effect = OSError('disk')
        with self.assertRaises(HTTPException) as caught:
            await self.service.update(1, MedicalRecordUpdateRequest(), object(), 4)
        self.assertEqual(caught.exception.status_code, 500)
        self.assertEqual(caught.exception.detail, '잠시 후 다시 시도해주세요.')
        self.assertEqual(self.db.rollback.await_count, 2)

    async def test_partial_upload_cleanup_commit_failure_returns_safe_500(self):
        from app.core.file_storage import OrphanedUploadError
        self.storage.save_xray_image.side_effect = OrphanedUploadError(
            HTTPException(413, 'too large'), 'partial.png'
        )
        self.db.commit.side_effect = SQLAlchemyError('internal database details')
        with self.assertRaises(HTTPException) as caught:
            await self.service.update(1, MedicalRecordUpdateRequest(), object(), 4)
        self.assertEqual(caught.exception.status_code, 500)
        self.assertEqual(caught.exception.detail, '잠시 후 다시 시도해주세요.')
        self.assertEqual(self.db.rollback.await_count, 2)

    async def test_post_commit_cleanup_failure_does_not_remove_new_image(self):
        self.cleanup.run.side_effect = OSError('disk')
        with self.assertRaises(HTTPException) as caught:
            await self.service.update(1, MedicalRecordUpdateRequest(), object(), 4)
        self.assertEqual(caught.exception.status_code, 500)
        self.db.commit.assert_awaited_once()
        self.storage.delete_xray_file.assert_not_awaited()

    async def test_delete_retries_pending_cleanup_for_missing_record(self):
        self.cleanup.resume.return_value = True
        self.repository.patient_id_for.return_value = None
        await self.service.delete(1)
        self.cleanup.resume.assert_awaited_once_with('medical_record', 1)
        self.cleanup.run.assert_not_awaited()
        self.db.delete.assert_not_awaited()

    async def test_cleanup_false_after_commit_returns_500(self):
        self.cleanup.run.return_value = False
        with self.assertRaises(HTTPException) as caught:
            await self.service.update(1, MedicalRecordUpdateRequest(), object(), 4)
        self.assertEqual(caught.exception.status_code, 500)
        self.db.commit.assert_awaited_once()
        self.db.rollback.assert_not_awaited()
        self.storage.delete_xray_file.assert_not_awaited()
        self.cleanup.run.assert_awaited_once_with(['job'])
        self.cleanup.enqueue.assert_called_once_with(
            'medical_record', 1, [('xray', 'old.png'), ('heatmap', 'heatmap.png')]
        )

    async def test_delete_resume_false_stops_deletion(self):
        self.cleanup.resume.return_value = False
        with self.assertRaises(HTTPException) as caught:
            await self.service.delete(1)
        self.assertEqual(caught.exception.status_code, 500)
        self.db.delete.assert_not_awaited()
        self.repository.lock.assert_not_awaited()

    async def test_delete_resume_true_with_existing_record_continues(self):
        self.cleanup.resume.return_value = True
        await self.service.delete(1)
        self.db.delete.assert_awaited_once_with(self.record)
        self.cleanup.enqueue.assert_called_once_with(
            'medical_record', 1, [('xray', 'old.png'), ('heatmap', 'heatmap.png')]
        )
        self.db.commit.assert_awaited_once()
        self.cleanup.run.assert_awaited_once_with(['job'])

    async def test_delete_missing_record_without_pending_returns_404(self):
        self.repository.patient_id_for.return_value = None
        with self.assertRaises(HTTPException) as caught:
            await self.service.delete(1)
        self.assertEqual(caught.exception.status_code, 404)
        self.db.commit.assert_not_awaited()

    async def test_no_updates_is_400(self):
        with self.assertRaises(HTTPException) as caught:
            await self.service.update(1, MedicalRecordUpdateRequest(), None, 4)
        self.assertEqual(caught.exception.status_code, 400)

    async def test_same_chart_is_allowed(self):
        await self.service.update(1, MedicalRecordUpdateRequest(chart_number='C1'), None, 4)
        self.repository.chart_exists.assert_awaited_once_with('C1', 1)
        self.db.commit.assert_awaited_once()


class MedicalRecordRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_cleanup_paths_use_current_locking_reads_on_mysql(self):
        from sqlalchemy.dialects import mysql
        from app.repositories.medical_record_repository import MedicalRecordRepository
        db = AsyncMock()
        db.scalars.side_effect = [['1/image.png'], ['1/heatmap.png']]
        paths = await MedicalRecordRepository(db).file_paths(1)
        self.assertEqual(paths, [('xray', '1/image.png'), ('heatmap', '1/heatmap.png')])
        for call in db.scalars.await_args_list:
            sql = str(call.args[0].compile(dialect=mysql.dialect()))
            self.assertIn('FOR UPDATE', sql)

    async def test_sqlite_queries_collect_and_remove_image_and_ai_data(self):
        from sqlalchemy import DefaultClause, MetaData, event, insert, select, text
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
        from app.core.db.databases import Base
        from app.models.patient import Patient
        from app.models.medical_record import MedicalRecord
        from app.models.xray_image import XrayImage
        from app.models.ai_analysis_result import AIAnalysisResult
        from app.repositories.medical_record_repository import MedicalRecordRepository

        engine = create_async_engine('sqlite+aiosqlite:///:memory:')

        @event.listens_for(engine.sync_engine, 'connect')
        def enable_foreign_keys(connection, _):
            connection.execute('PRAGMA foreign_keys=ON')

        try:
            async with engine.begin() as connection:
                def create_schema(sync_connection):
                    metadata = MetaData()
                    for table in Base.metadata.sorted_tables:
                        copied = table.to_metadata(metadata)
                        for column in copied.columns:
                            if column.server_default is not None and 'current_timestamp(0)' in str(column.server_default.arg):
                                column.server_default = DefaultClause(text('CURRENT_TIMESTAMP'))
                    metadata.create_all(sync_connection)
                await connection.run_sync(create_schema)
                await connection.execute(insert(Patient).values(
                    id=2, name='테스트', age=30, gender='female', phone_number='01012345678',
                ))
                await connection.execute(insert(MedicalRecord), [
                    dict(id=1, patient_id=2, chart_number='C1', symptoms='원문'),
                    dict(id=3, patient_id=2, chart_number='C3', symptoms='다른 기록'),
                ])
                await connection.execute(insert(XrayImage).values(
                    id=1, record_id=1, uploader_id=None, image_url='old.png',
                    shooting_datetime=datetime(2026, 10, 27),
                ))
                await connection.execute(insert(AIAnalysisResult).values(
                    id=1, record_id=1, is_pneumonia=False, confidence=90,
                    heatmap_url='heatmap.png', ai_model='test',
                ))
            async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                repository = MedicalRecordRepository(db)
                self.assertEqual(await repository.patient_id_for(1), 2)
                self.assertIsNone(await repository.lock(999))
                self.assertFalse(await repository.chart_exists('C1', 1))
                self.assertTrue(await repository.chart_exists('C3', 1))
                self.assertEqual(set(await repository.file_paths(1)), {('xray', 'old.png'), ('heatmap', 'heatmap.png')})
                response = await repository.response(1)
                self.assertIsNone(response['uploader_id'])
                self.assertIsNone(response['uploader_name'])
                await repository.remove_image_data(1)
                self.assertIsNone(await db.scalar(select(XrayImage.id)))
                self.assertIsNone(await db.scalar(select(AIAnalysisResult.id)))
                await db.rollback()
                self.assertEqual(set(await repository.file_paths(1)), {('xray', 'old.png'), ('heatmap', 'heatmap.png')})
        finally:
            await engine.dispose()


if __name__ == '__main__':
    unittest.main()
