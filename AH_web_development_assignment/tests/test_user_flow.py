"""실제 ORM·서비스·인증을 사용하는 USER API 통합 검증 (임시 SQLite)."""
import asyncio
import tempfile
import time
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
from fastapi.testclient import TestClient
from sqlalchemy import event, MetaData, DefaultClause, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from app import models
from app.main import app
from app.core.config import settings
from app.core.db.databases import Base, async_get_db
from app.core.security import decode_token, verify_password
from app.models.user import User
from app.models.xray_image import XrayImage
from app.models.patient import Patient
from app.models.medical_record import MedicalRecord
from app.models.ai_analysis_result import AIAnalysisResult


class UserFlowTests(unittest.TestCase):
    timings = []

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine('sqlite+aiosqlite:///' + str(Path(self.temp.name) / 'test.db'), poolclass=NullPool)
        @event.listens_for(self.engine.sync_engine, 'connect')
        def foreign_keys(connection, _):
            connection.execute('PRAGMA foreign_keys=ON')
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async def init():
            async with self.engine.begin() as conn:
                def create_schema(sync_conn):
                    metadata = MetaData()
                    for table in Base.metadata.sorted_tables:
                        copied = table.to_metadata(metadata)
                        for column in copied.columns:
                            if column.server_default is not None and 'current_timestamp(0)' in str(column.server_default.arg):
                                column.server_default = DefaultClause(text('CURRENT_TIMESTAMP'))
                    metadata.create_all(sync_conn)
                await conn.run_sync(create_schema)
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

    def request(self, method, path, **kwargs):
        start = time.perf_counter()
        response = self.client.request(method, '/api/v1/' + path, **kwargs)
        elapsed = time.perf_counter() - start
        self.timings.append(elapsed)
        self.assertLess(elapsed, 3)
        return response

    def signup(self, email='hong@example.com', phone='01012345678', **extra):
        return self.request('POST', 'users/signup', json=dict(email=email, password='Example123!', name='홍길동', department='medical', gender='male', phone_number=phone, **extra))

    def login(self, password='Example123!'):
        return self.request('POST', 'users/login', files={'username': (None, ' HONG@example.com '), 'password': (None, password)})

    def test_signup_validation_and_hash(self):
        self.assertEqual(self.signup(role='admin').status_code, 422)
        response = self.signup(' HONG@example.com ')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['role'], 'pending')
        self.assertTrue(response.json()['is_active'])
        self.assertNotIn('hashed_password', response.json())
        self.assertNotIn('set-cookie', response.headers)
        self.assertEqual(self.signup().status_code, 409)
        self.assertEqual(self.signup('other@example.com').status_code, 409)
        async def check():
            async with self.sessions() as db:
                user = await db.get(User, 1)
                self.assertEqual(user.email, 'hong@example.com')
                self.assertTrue(verify_password('Example123!', user.hashed_password))
        asyncio.run(check())

    def test_full_account_lifecycle(self):
        self.signup()
        self.assertEqual(self.login('Wrong123!').status_code, 401)
        login = self.login()
        self.assertEqual(login.status_code, 200)
        self.assertEqual(login.headers['cache-control'], 'no-store')
        self.assertIn('HttpOnly', login.headers['set-cookie'])
        self.assertEqual(login.json()['expires_in'], 1800)
        auth = {'Authorization': 'Bearer ' + login.json()['access_token']}
        refresh_cookie = self.client.cookies.get('refresh_token')
        self.assertEqual(self.request('GET', 'users/me', headers=auth).status_code, 200)
        self.assertEqual(self.request('GET', 'admin/users', headers=auth).status_code, 403)
        refreshed = self.request('POST', 'users/refresh')
        self.assertEqual(refreshed.status_code, 200)
        self.assertNotIn('set-cookie', refreshed.headers)
        for body, code in [({}, 400), ({'department': None}, 422), ({'role': 'admin'}, 422), ({'phone_number': 'bad'}, 422), ({'department': 'research'}, 200)]:
            self.assertEqual(self.request('PATCH', 'users/me', headers=auth, json=body).status_code, code)
        for old, new, code in [('wrong', 'Changed456!', 400), ('Example123!', 'Example123!', 400), ('Example123!', 'weak', 422), ('Example123!', 'Changed456!', 204)]:
            response = self.request('PATCH', 'users/me/password', headers=auth, json={'current_password': old, 'new_password': new})
            self.assertEqual(response.status_code, code)
        self.assertIn('Max-Age=0', response.headers['set-cookie'])
        self.assertEqual(self.login().status_code, 401)
        self.assertEqual(self.login('Changed456!').status_code, 200)
        async def add_records():
            async with self.sessions() as db:
                db.add(Patient(id=1, name='환자', age=30, gender='male', phone_number='01099999999'))
                await db.flush()
                db.add(MedicalRecord(id=1, patient_id=1, chart_number='C1', symptoms='기침'))
                await db.flush()
                db.add(XrayImage(id=1, record_id=1, uploader_id=1, image_url='/media/preserved.png', shooting_datetime=datetime.now()))
                db.add(AIAnalysisResult(id=1, record_id=1, is_pneumonia=False, confidence=90, heatmap_url='/media/heat.png', ai_model='test', model_version='v1'))
                await db.commit()
        asyncio.run(add_records())
        response = self.request('DELETE', 'users/me', headers=auth)
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b'')
        async def check_deleted():
            async with self.sessions() as db:
                self.assertIsNone(await db.get(User, 1))
                image = await db.get(XrayImage, 1)
                self.assertIsNone(image.uploader_id)
                self.assertEqual(image.image_url, '/media/preserved.png')
                for model in (Patient, MedicalRecord, AIAnalysisResult):
                    self.assertIsNotNone(await db.get(model, 1))
        asyncio.run(check_deleted())
        self.assertEqual(self.request('GET', 'users/me', headers=auth).status_code, 401)
        self.client.cookies.set('refresh_token', refresh_cookie)
        self.assertEqual(self.request('POST', 'users/refresh').status_code, 401)
        self.assertEqual(self.request('POST', 'users/logout').status_code, 204)
        self.assertEqual(self.request('POST', 'users/logout').status_code, 204)

    def test_live_permissions_and_inactive_accounts(self):
        self.signup()
        token = self.login().json()['access_token']
        auth = {'Authorization': 'Bearer ' + token}
        async def update(**values):
            async with self.sessions() as db:
                user = await db.get(User, 1)
                for key, value in values.items():
                    setattr(user, key, value)
                await db.commit()
        asyncio.run(update(role='admin'))
        self.signup('other@example.com', '01022222222')
        self.assertEqual(self.request('PATCH', 'users/me', headers=auth, json={'phone_number': '01022222222'}).status_code, 409)
        self.assertEqual(self.request('PATCH', 'users/me', headers=auth, json={'phone_number': '01012345678'}).status_code, 200)
        response = self.request('GET', 'admin/users?query=홍&department=medical', headers=auth)
        self.assertEqual(len(response.json()), 2)
        self.assertEqual(self.request('GET', 'admin/users?query=absent', headers=auth).json(), [])
        self.assertEqual(self.request('PATCH', 'admin/users/role', headers=auth, json={'user_id': 2, 'new_role': 'staff'}).status_code, 200)
        asyncio.run(update(role='pending'))
        self.assertEqual(self.request('GET', 'admin/users', headers=auth).status_code, 403)
        asyncio.run(update(is_active=False))
        self.assertEqual(self.login().status_code, 403)
        self.assertEqual(self.request('GET', 'users/me', headers=auth).status_code, 403)
        self.assertEqual(self.request('POST', 'users/refresh').status_code, 403)

    def test_origin_and_invalid_tokens(self):
        self.assertEqual(self.request('POST', 'users/logout', headers={'Origin': 'https://evil.example'}).status_code, 403)
        self.assertEqual(self.request('POST', 'users/logout', headers={'Origin': 'http://testserver'}).status_code, 204)
        self.assertEqual(self.request('POST', 'users/logout', headers={'Origin': 'null'}).status_code, 403)
        now = datetime.now(UTC)
        payload = dict(user_id=1, token_type='access', iat=now, exp=now + timedelta(minutes=30))
        for field in payload:
            bad = {key: value for key, value in payload.items() if key != field}
            self.assertIsNone(decode_token(jwt.encode(bad, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM), 'access'))
        for changes in ({'exp': now - timedelta(seconds=1)}, {'token_type': 'refresh'}, {'user_id': True}, {'user_id': 0}):
            self.assertIsNone(decode_token(jwt.encode(payload | changes, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM), 'access'))
        self.assertIsNone(decode_token(jwt.encode(payload, 'other-key-' * 8, algorithm=settings.JWT_ALGORITHM), 'access'))
        response = self.request('POST', 'users/refresh')
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers['www-authenticate'], 'Bearer')

    @classmethod
    def tearDownClass(cls):
        print(f'USER API timings: SQLite, max 2 users, concurrency 1, 1 X-ray; requests={len(cls.timings)}, max={max(cls.timings, default=0):.3f}s')
