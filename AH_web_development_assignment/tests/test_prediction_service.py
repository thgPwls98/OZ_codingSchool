"""⑫ AI 폐렴 예측 서비스 테스트 (REQ-PRED-001, 6일차 설계 13절) — 3단계 C

실제 모델·결과 테이블 대신 가짜 예측 모듈과 가짜 결과 저장소를 주입한다.
진료기록·환자·X-Ray와 잠금 조회는 임시 SQLite로 실제 동작을 확인한다.
(SQLite는 FOR UPDATE를 무시하므로 "잠금 덕분에 막혔다"는 MySQL T28에서 따로 확인한다)

실행: uv run --with aiosqlite python -m unittest tests.test_prediction_service -v
"""

import asyncio
import sqlite3
from contextlib import closing
import sys
import tempfile
import threading
import unittest
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.models import MedicalRecord, Patient, User, XrayImage
from app.models.enums import Department, Gender, Role
from app.services import prediction_service
from app.services.prediction_service import PredictionService

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sqlite_db import create_test_db  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
SHOT = datetime(2026, 10, 28, 6, 0, 0)


@dataclass(frozen=True)
class FakePrediction:
    is_pneumonia: bool
    confidence: float
    pneumonia_probability: float
    heatmap: object = None


class FakePredictor:
    """worker.model 약속(설계 5-1절)을 흉내 낸다. 호출 횟수를 세고, 추론 중 동작을 끼워 넣을 수 있다."""

    MODEL_NAME = "fake-model"
    MODEL_VERSION = "v1"

    def __init__(self, result=None, error=None, loaded=True, during=None):
        self.result = result or FakePrediction(False, 87.0, 0.13)
        self.error = error
        self.loaded = loaded
        self.during = during  # 추론 도중에 실행할 함수 (이미지 교체·기록 삭제 흉내)
        self.calls = 0

    def is_loaded(self):
        return self.loaded

    def predict(self, image_path):
        self.calls += 1
        if self.during:
            self.during()
        if self.error:
            raise self.error
        return self.result


class FakeAnalysisRepository:
    """A가 만들 AnalysisRepository 대신 메모리에 저장한다 (get_current / add / refresh)"""

    def __init__(self, conflict_with=None):
        self.rows = []
        self.conflict_with = conflict_with  # add 시 동시 요청이 먼저 저장한 결과를 흉내

    async def get_current(self, record_id, ai_model, model_version):
        return next(
            (r for r in self.rows
             if (r.record_id, r.ai_model, r.model_version) == (record_id, ai_model, model_version)),
            None,
        )

    async def add(self, **fields):
        if self.conflict_with is not None:
            self.rows.append(self.conflict_with)
            raise IntegrityError("INSERT", {}, Exception("UNIQUE constraint failed"))
        row = SimpleNamespace(id=len(self.rows) + 1, **fields)
        self.rows.append(row)
        return row

    async def refresh(self, row):
        row.refreshed = True


class PredictionServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        tmp = Path(self.tmp.name)
        self.storage = tmp / "xray"
        for name, value in (("XRAY_STORAGE_DIR", tmp / "xray"), ("HEATMAP_STORAGE_DIR", tmp / "heatmap")):
            p = patch.object(settings, name, str(value))
            p.start()
            self.addCleanup(p.stop)
        prediction_service._inference_semaphore = None  # 테스트마다 새 이벤트 루프
        self.db_path = tmp / "test.db"
        self.engine, self.Session = asyncio.run(create_test_db(tmp))
        self.addCleanup(lambda: asyncio.run(self.engine.dispose()))
        asyncio.run(self._prepare())

    async def _prepare(self):
        async with self.Session() as db:
            db.add(User(id=1, email="doc@example.com", hashed_password="x", name="김의사",
                        phone_number="01011112222", gender=Gender.MALE,
                        department=Department.MEDICAL, role=Role.STAFF, is_active=True))
            db.add(Patient(id=1, name="김환자", age=45, gender=Gender.FEMALE, phone_number="01098765432"))
            db.add(MedicalRecord(id=1, patient_id=1, chart_number="CH-1", symptoms="기침"))
            db.add(XrayImage(id=10, record_id=1, uploader_id=1, image_url="1/a.png", shooting_datetime=SHOT))
            db.add(MedicalRecord(id=2, patient_id=1, chart_number="CH-2", symptoms="발열"))  # 이미지 행 없음
            await db.commit()
        (self.storage / "1").mkdir(parents=True)
        (self.storage / "1" / "a.png").write_bytes(PNG)

    def run_predict(self, record_id, predictor, analyses):
        async def go():
            async with self.Session() as db:
                return await PredictionService(db, predictor, analyses).predict(record_id)
        return asyncio.run(go())

    def assert_http(self, status, func, *args):
        with self.assertRaises(HTTPException) as ctx:
            func(*args)
        self.assertEqual(ctx.exception.status_code, status)
        return ctx.exception

    def sql(self, statement):
        """추론 도중 다른 사용자의 변경을 흉내 낸다 (스레드풀 안이라 별도 sqlite3 연결 사용)"""
        def run():
            with closing(sqlite3.connect(self.db_path)) as conn, conn:
                conn.execute(statement)
        return run

    # ---------- 성공 ----------
    def test_new_prediction_returns_created(self):  # T1, T16
        predictor, analyses = FakePredictor(), FakeAnalysisRepository()
        result, created = self.run_predict(1, predictor, analyses)
        self.assertTrue(created)
        self.assertEqual(predictor.calls, 1)
        self.assertEqual((result.record_id, result.is_pneumonia, result.confidence), (1, False, 87.0))
        self.assertEqual((result.ai_model, result.model_version, result.heatmap_url), ("fake-model", "v1", None))
        self.assertTrue(result.refreshed)  # commit 후 refresh (T29)

    def test_reuse_saved_result_without_inference(self):  # T2
        predictor, analyses = FakePredictor(), FakeAnalysisRepository()
        first, _ = self.run_predict(1, predictor, analyses)
        second, created = self.run_predict(1, predictor, analyses)
        self.assertFalse(created)
        self.assertIs(second, first)
        self.assertEqual(predictor.calls, 1)  # 두 번째는 추론하지 않음

    def test_new_model_version_predicts_again(self):  # T3
        analyses = FakeAnalysisRepository()
        self.run_predict(1, FakePredictor(), analyses)
        v2 = FakePredictor()
        v2.MODEL_VERSION = "v2"
        _, created = self.run_predict(1, v2, analyses)
        self.assertTrue(created)
        self.assertEqual(len(analyses.rows), 2)

    # ---------- 모델 상태 ----------
    def test_model_not_loaded(self):  # T9
        predictor = FakePredictor(loaded=False)
        self.assert_http(503, self.run_predict, 1, predictor, FakeAnalysisRepository())
        self.assertEqual(predictor.calls, 0)

    def test_saved_result_returned_even_if_model_not_loaded(self):  # T9 캐시 우선
        analyses = FakeAnalysisRepository()
        self.run_predict(1, FakePredictor(), analyses)
        _, created = self.run_predict(1, FakePredictor(loaded=False), analyses)
        self.assertFalse(created)

    def test_lazy_load_when_not_preloaded(self):  # AI_PRELOAD_MODEL=false: 첫 요청 때 로딩
        class LazyPredictor(FakePredictor):
            def ensure_loaded(self):
                self.loaded = True
                return True
        predictor = LazyPredictor(loaded=False)
        _, created = self.run_predict(1, predictor, FakeAnalysisRepository())
        self.assertTrue(created)
        self.assertEqual(predictor.calls, 1)

    def test_lazy_load_failure_is_503(self):  # 가중치 없음 등으로 로딩 실패
        class BrokenPredictor(FakePredictor):
            def ensure_loaded(self):
                return False
        predictor = BrokenPredictor(loaded=False)
        self.assert_http(503, self.run_predict, 1, predictor, FakeAnalysisRepository())
        self.assertEqual(predictor.calls, 0)

    # ---------- 입력 오류 ----------
    def test_missing_record(self):  # T6
        e = self.assert_http(404, self.run_predict, 999, FakePredictor(), FakeAnalysisRepository())
        self.assertEqual(e.detail, "진료기록을 찾을 수 없습니다.")

    def test_missing_image_row_or_file(self):  # T7
        self.assert_http(404, self.run_predict, 2, FakePredictor(), FakeAnalysisRepository())  # 이미지 행 없음
        (self.storage / "1" / "a.png").unlink()
        predictor = FakePredictor()
        e = self.assert_http(404, self.run_predict, 1, predictor, FakeAnalysisRepository())
        self.assertEqual(e.detail, "이미지 파일을 찾을 수 없습니다.")
        self.assertEqual(predictor.calls, 0)

    def test_image_path_outside_storage(self):  # T7
        self.sql("UPDATE xray_images SET image_url = '../../escape.png' WHERE id = 10")()
        e = self.assert_http(404, self.run_predict, 1, FakePredictor(), FakeAnalysisRepository())
        self.assertNotIn("escape", e.detail)

    # ---------- 추론 오류 ----------
    def test_invalid_image_is_422(self):  # T8
        analyses = FakeAnalysisRepository()
        self.assert_http(422, self.run_predict, 1, FakePredictor(error=ValueError("bad image")), analyses)
        self.assertEqual(analyses.rows, [])

    def test_model_error_is_500_without_details(self):  # T10
        analyses = FakeAnalysisRepository()
        e = self.assert_http(500, self.run_predict, 1, FakePredictor(error=RuntimeError("NaN /secret/path")), analyses)
        self.assertEqual(e.detail, "잠시 후 다시 시도해주세요.")
        self.assertEqual(analyses.rows, [])

    def test_out_of_range_confidence_is_500(self):
        predictor = FakePredictor(result=FakePrediction(True, 150.0, 0.9))
        self.assert_http(500, self.run_predict, 1, predictor, FakeAnalysisRepository())

    # ---------- 동시성 ----------
    def test_image_replaced_during_inference(self):  # T14, T29
        def during():
            with closing(sqlite3.connect(self.db_path)) as conn, conn:
                conn.execute("DELETE FROM xray_images WHERE id = 10")
                conn.execute("INSERT INTO xray_images (id, record_id, uploader_id, image_url, shooting_datetime) "
                             "VALUES (11, 1, 1, '1/b.png', '2026-10-28 07:00:00')")

        analyses = FakeAnalysisRepository()
        e = self.assert_http(409, self.run_predict, 1, FakePredictor(during=during), analyses)
        self.assertEqual(e.detail, "X-Ray 이미지가 변경되었습니다. 다시 시도해주세요.")
        self.assertEqual(analyses.rows, [])

    def test_record_deleted_during_inference(self):  # T15
        analyses = FakeAnalysisRepository()
        self.assert_http(404, self.run_predict, 1,
                         FakePredictor(during=self.sql("DELETE FROM medical_records WHERE id = 1")), analyses)
        self.assertEqual(analyses.rows, [])

    def test_concurrent_request_saved_first_returns_existing(self):  # T13
        first = SimpleNamespace(id=7, record_id=1, ai_model="fake-model", model_version="v1",
                                is_pneumonia=True, confidence=91.0, heatmap_url=None)
        result, created = self.run_predict(1, FakePredictor(), FakeAnalysisRepository(conflict_with=first))
        self.assertFalse(created)
        self.assertIs(result, first)

    def test_inference_runs_one_at_a_time(self):  # 동시 추론 수 제한 (설계 9절)
        active, peak, lock = 0, 0, threading.Lock()

        class SlowPredictor(FakePredictor):
            def predict(self, image_path):
                nonlocal active, peak
                with lock:
                    active += 1
                    peak = max(peak, active)
                threading.Event().wait(0.05)
                with lock:
                    active -= 1
                return super().predict(image_path)

        async def go():
            async def one(analyses):
                async with self.Session() as db:
                    return await PredictionService(db, SlowPredictor(), analyses).predict(1)
            await asyncio.gather(one(FakeAnalysisRepository()), one(FakeAnalysisRepository()))

        asyncio.run(go())
        self.assertEqual(peak, 1)

    # ---------- 히트맵 (Q1 결정 시 사용) ----------
    def test_heatmap_saved_and_discarded_on_conflict(self):  # T12
        from PIL import Image
        heat = FakePrediction(True, 91.0, 0.91, heatmap=Image.new("RGB", (4, 4)))
        result, _ = self.run_predict(1, FakePredictor(result=heat), FakeAnalysisRepository())
        saved = Path(settings.HEATMAP_STORAGE_DIR) / result.heatmap_url
        self.assertTrue(saved.is_file())
        self.assertTrue(result.heatmap_url.startswith("1/"))  # storage/heatmap/{patient_id}/

        def during():
            with closing(sqlite3.connect(self.db_path)) as conn, conn:
                conn.execute("DELETE FROM xray_images WHERE id = 10")
                conn.execute("INSERT INTO xray_images (id, record_id, uploader_id, image_url, shooting_datetime) "
                             "VALUES (12, 1, 1, '1/c.png', '2026-10-28 07:00:00')")
        before = set((Path(settings.HEATMAP_STORAGE_DIR) / "1").glob("*.png"))
        self.assert_http(409, self.run_predict, 1, FakePredictor(result=heat, during=during), FakeAnalysisRepository())
        after = set((Path(settings.HEATMAP_STORAGE_DIR) / "1").glob("*.png"))
        self.assertEqual(before, after)  # 409면 새로 만든 히트맵을 지운다


if __name__ == "__main__":
    unittest.main()
