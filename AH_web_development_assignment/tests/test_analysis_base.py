"""AI 폐렴 예측 공통 기반 검증: DB 제약, 저장소, 응답 스키마 (6일차 설계 2-2, 7절, 임시 SQLite)

6일차 설계 13장 T11, T18, T20, T26과 UNIQUE 중복 방지(T13의 DB 부분)를 확인한다.
실행: uv run python -m unittest tests.test_analysis_base -v  (aiosqlite 필요)
"""

import json
import sys
import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import AIAnalysisResult, MedicalRecord, Patient
from app.repositories.analysis_repository import AnalysisRepository
from app.schemas.analysis import to_analysis_response

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sqlite_db import create_test_db  # noqa: E402

MODEL = "efficientnet_b0_5fold"


class AnalysisRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine, self.sessions = await create_test_db(Path(self.temp.name))
        async with self.sessions() as db:
            db.add(Patient(id=1, name="김환자", age=45, gender="female", phone_number="01098765432"))
            await db.flush()
            db.add(MedicalRecord(id=1, patient_id=1, chart_number="C1", symptoms="기침"))
            db.add(MedicalRecord(id=2, patient_id=1, chart_number="C2", symptoms="발열"))
            await db.commit()

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.temp.cleanup()

    async def add(self, db, record_id=1, version="v1", **fields):
        values = dict(is_pneumonia=False, confidence=83.28, ai_model=MODEL, model_version=version)
        return await AnalysisRepository(db).add(record_id, **{**values, **fields})

    async def test_add_and_get_current(self):
        async with self.sessions() as db:
            saved = await self.add(db)
            await db.commit()
            self.assertIsNotNone(saved.id)

        async with self.sessions() as db:
            repository = AnalysisRepository(db)
            found = await repository.get_current(1, MODEL, "v1")
            self.assertEqual(found.id, saved.id)
            # 버전·모델·진료기록이 하나라도 다르면 재사용하지 않는다 (설계 D5)
            self.assertIsNone(await repository.get_current(1, MODEL, "v2"))
            self.assertIsNone(await repository.get_current(1, "other_model", "v1"))
            self.assertIsNone(await repository.get_current(2, MODEL, "v1"))

    async def test_add_with_keywords_then_refresh_after_commit(self):
        # C의 사용 방식: 키워드로 add → commit → refresh → 응답 변환 (설계 6-1 ⑩)
        async with self.sessions() as db:
            repository = AnalysisRepository(db)
            saved = await repository.add(record_id=1, is_pneumonia=True, confidence=93.41, heatmap_url=None,
                                         ai_model=MODEL, model_version="v1")
            await db.commit()
            await repository.refresh(saved)
            body = json.loads(to_analysis_response(saved).model_dump_json())
            self.assertEqual(body["confidence"], 93.41)
            self.assertTrue(body["created_at"].endswith("Z"))

    async def test_confidence_saved_as_two_digit_decimal(self):
        async with self.sessions() as db:
            await self.add(db, confidence=83.27999999)
            await db.commit()
        async with self.sessions() as db:
            self.assertEqual(await db.scalar(select(AIAnalysisResult.confidence)), Decimal("83.28"))

    async def test_heatmap_is_optional(self):
        # T11 히트맵 없는 결과도 저장된다 (설계 D4)
        async with self.sessions() as db:
            await self.add(db)
            await db.commit()
        async with self.sessions() as db:
            self.assertIsNone(await db.scalar(select(AIAnalysisResult.heatmap_url)))

    async def test_duplicate_record_model_version_rejected(self):
        # 같은 진료기록·같은 모델 버전은 1건만 (설계 D6). 서비스는 이 오류로 동시 요청을 감지한다
        async with self.sessions() as db:
            await self.add(db)
            await db.commit()
        async with self.sessions() as db:
            with self.assertRaises(IntegrityError):
                await self.add(db)
            await db.rollback()
            # 버전이 다르거나 다른 진료기록이면 저장된다 (설계 4-1 처리 규칙 4)
            await self.add(db, version="v2")
            await self.add(db, record_id=2)
            await db.commit()

    async def test_confidence_out_of_range_rejected(self):
        # T26 CHECK 제약 (confidence 0~100)
        for confidence in (101, -1):
            async with self.sessions() as db:
                with self.subTest(confidence=confidence), self.assertRaises(IntegrityError):
                    await self.add(db, confidence=confidence)
                await db.rollback()

    async def test_list_by_record_newest_first(self):
        async with self.sessions() as db:
            db.add_all([
                AIAnalysisResult(id=10, record_id=1, is_pneumonia=False, confidence=Decimal("83.28"),
                                 ai_model=MODEL, model_version="v1", created_at=datetime(2026, 10, 28, 6, 0)),
                AIAnalysisResult(id=11, record_id=1, is_pneumonia=True, confidence=Decimal("93.41"),
                                 ai_model=MODEL, model_version="v2", created_at=datetime(2026, 10, 29, 2, 0)),
                AIAnalysisResult(id=12, record_id=2, is_pneumonia=True, confidence=Decimal("70.00"),
                                 ai_model=MODEL, model_version="v1", created_at=datetime(2026, 10, 30, 0, 0)),
            ])
            await db.commit()
        async with self.sessions() as db:
            repository = AnalysisRepository(db)
            # T18 최신순, 다른 진료기록 결과는 섞이지 않는다
            self.assertEqual([r.id for r in await repository.list_by_record(1)], [11, 10])
            self.assertEqual(await repository.list_by_record(999), [])

    async def test_results_deleted_with_record(self):
        # 진료기록 삭제 시 결과도 삭제 (ON DELETE CASCADE, 5일차 문서 D4)
        async with self.sessions() as db:
            await self.add(db)
            await db.commit()
        async with self.sessions() as db:
            await db.delete(await db.get(MedicalRecord, 1))
            await db.commit()
        async with self.sessions() as db:
            self.assertIsNone(await db.scalar(select(AIAnalysisResult.id)))


class AnalysisResponseTests(unittest.TestCase):
    def make_result(self, heatmap_url=None):
        return AIAnalysisResult(id=12, record_id=1, is_pneumonia=False, confidence=Decimal("83.28"),
                                heatmap_url=heatmap_url, ai_model=MODEL, model_version="v1",
                                created_at=datetime(2026, 10, 28, 6, 20))

    def test_response_json(self):
        body = json.loads(to_analysis_response(self.make_result()).model_dump_json())
        self.assertEqual(body, {
            "id": 12,
            "record_id": 1,
            "is_pneumonia": False,
            "confidence": 83.28,  # T20 문자열이 아니라 숫자
            "heatmap_url": None,
            "ai_model": MODEL,
            "model_version": "v1",
            "created_at": "2026-10-28T06:20:00Z",
        })

    def test_heatmap_path_becomes_api_path(self):
        # DB의 상대 경로(파일 위치)는 응답하지 않는다 (설계 2-1, D15)
        response = to_analysis_response(self.make_result(heatmap_url="1/abc.png"))
        self.assertEqual(response.heatmap_url, "/api/v1/medical-records/1/analyses/12/heatmap")


if __name__ == "__main__":
    unittest.main()
