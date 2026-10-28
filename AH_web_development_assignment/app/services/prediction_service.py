"""⑫ AI 폐렴 예측 서비스 (REQ-PRED-001, 6일차 설계 4-1·6-1절) — 3단계 C

처리 순서 (설계 6-1절)
  1단계 읽기:  진료기록 확인 → 같은 모델 결과 재사용(200) → 모델 확인(503) → 최신 X-Ray 확인
              → 필요한 값을 변수로 꺼낸 뒤 읽기 트랜잭션 종료 (rollback)
  2단계 추론:  동시 추론 수 제한 안에서 스레드풀로 예측 (DB와 무관)
  3단계 저장:  환자 → 진료기록 잠금 → X-Ray 교체 여부 재확인(409) → 저장 → commit → refresh
              UNIQUE 위반(동시 요청이 먼저 저장)이면 먼저 저장된 결과를 200으로 돌려준다.

의존하는 이름 (설계 5-1절, 12-3절)
  - predictor (worker.model, 3단계 D): MODEL_NAME, MODEL_VERSION, is_loaded(), predict(path)
  - analyses (AnalysisRepository, 3단계 A): get_current(), add(), refresh()
"""

import asyncio
import logging
import uuid
from pathlib import Path
from typing import Any, Protocol

from fastapi import HTTPException, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.file_storage import FILE_KIND_HEATMAP, delete_stored_file, get_storage_root, resolve_xray_path
from app.repositories.medical_record_repository import MedicalRecordRepository
from app.repositories.patient_repository import PatientRepository

logger = logging.getLogger(__name__)

# 오류 메시지 (설계 2-4절)
RECORD_NOT_FOUND = "진료기록을 찾을 수 없습니다."
IMAGE_NOT_FOUND = "이미지 파일을 찾을 수 없습니다."
IMAGE_CHANGED = "X-Ray 이미지가 변경되었습니다. 다시 시도해주세요."
INVALID_IMAGE = "예측할 수 없는 이미지입니다."
MODEL_UNAVAILABLE = "AI 예측 기능을 사용할 수 없습니다."
TRY_AGAIN_LATER = "잠시 후 다시 시도해주세요."

# 동시에 실행할 추론 수 (설계 9절). 설정이 없으면 1
DEFAULT_MAX_CONCURRENT_PREDICTIONS = 1
_inference_semaphore: asyncio.Semaphore | None = None


def _inference_slot() -> asyncio.Semaphore:
    global _inference_semaphore
    if _inference_semaphore is None:
        limit = getattr(settings, "AI_MAX_CONCURRENT_PREDICTIONS", DEFAULT_MAX_CONCURRENT_PREDICTIONS)
        _inference_semaphore = asyncio.Semaphore(max(1, int(limit)))
    return _inference_semaphore


class Predictor(Protocol):
    """1단계 예측 모듈 약속 (설계 5-1절). worker.model 모듈이 이 모양을 따른다."""

    MODEL_NAME: str
    MODEL_VERSION: str

    def is_loaded(self) -> bool: ...

    def predict(self, image_path: Path) -> Any: ...


class PredictionService:
    """팀 규칙: commit·rollback은 서비스가 한다. 잠금 순서는 환자 → 진료기록."""

    def __init__(self, db: AsyncSession, predictor: Predictor, analyses, records=None, patients=None):
        self.db = db
        self.predictor = predictor
        self.analyses = analyses
        self.records = records if records is not None else MedicalRecordRepository(db)
        self.patients = patients if patients is not None else PatientRepository(db)

    async def predict(self, record_id: int) -> tuple[Any, bool]:
        """(결과, 새로 만들었는지)를 돌려준다. 새로 만들면 201, 재사용이면 200"""
        model_name = self.predictor.MODEL_NAME
        model_version = self.predictor.MODEL_VERSION

        # ── 1단계: 읽기 (잠금 없음) ──
        patient_id = await self.records.patient_id_for(record_id)
        if patient_id is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=RECORD_NOT_FOUND)

        # 캐시 확인을 모델 확인보다 먼저: 모델이 고장 나도 저장된 결과는 응답한다 (설계 6-1절)
        saved = await self.analyses.get_current(record_id, model_name, model_version)
        if saved is not None:
            return saved, False

        if not self.predictor.is_loaded() and not await self._try_load():
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=MODEL_UNAVAILABLE)

        image = await self.records.get_image(record_id)
        if image is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=IMAGE_NOT_FOUND)
        # rollback은 ORM 객체를 만료시킨다 → 이후 image.id에 접근하면 MissingGreenlet.
        # 필요한 값을 일반 변수로 먼저 꺼내고, 아래부터는 ORM 객체를 쓰지 않는다 (설계 6-1절 ⑤)
        image_id, image_url = image.id, image.image_url
        await self.db.rollback()  # 읽기 트랜잭션 종료: 추론 동안 DB 연결·스냅샷을 붙잡지 않는다

        path = self._resolve_image(image_id, image_url)

        # ── 2단계: 추론 (DB와 무관) ──
        prediction = await self._infer(record_id, path)
        heatmap_path = await self._save_heatmap(patient_id, getattr(prediction, "heatmap", None))

        # ── 3단계: 저장 (잠금) ──
        committed = False
        try:
            if await self.patients.lock(patient_id) is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=RECORD_NOT_FOUND)
            record = await self.records.lock(record_id)
            if record is None or record.patient_id != patient_id:  # 추론 중 삭제
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=RECORD_NOT_FOUND)

            # 진료기록을 잠근 상태에서 확인해야 확인과 저장 사이에 교체가 끼어들 수 없다
            latest = await self.records.get_image(record_id)
            if latest is None or latest.id != image_id:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=IMAGE_CHANGED)

            result = await self.analyses.add(
                record_id=record_id,
                is_pneumonia=prediction.is_pneumonia,
                confidence=prediction.confidence,
                heatmap_url=heatmap_path,
                ai_model=model_name,
                model_version=model_version,
            )
            await self.db.commit()
            committed = True
            # DB가 채운 created_at 등을 읽어 온다. 생략하면 응답 직렬화에서 MissingGreenlet이 날 수 있다.
            await self.analyses.refresh(result)
            return result, True
        except IntegrityError:
            # 같은 기록·같은 모델을 동시 요청이 먼저 저장했다 → 먼저 저장된 결과를 돌려준다 (설계 D6)
            await self.db.rollback()
            await self._discard_heatmap(heatmap_path)
            saved = await self.analyses.get_current(record_id, model_name, model_version)
            if saved is None:
                logger.error("예측 결과 저장 충돌 후 기존 결과 없음: record_id=%s", record_id)
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=TRY_AGAIN_LATER)
            return saved, False
        except HTTPException:
            if not committed:
                await self.db.rollback()
                await self._discard_heatmap(heatmap_path)
            raise
        except SQLAlchemyError as e:
            if not committed:
                await self.db.rollback()
                await self._discard_heatmap(heatmap_path)
            # commit 이후(refresh) 실패면 결과는 이미 저장됐으므로 히트맵을 지우지 않는다
            logger.error("예측 결과 저장 실패: record_id=%s, %s", record_id, type(e).__name__)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=TRY_AGAIN_LATER
            ) from e

    # ===== 내부 함수 =====

    async def _try_load(self) -> bool:
        """AI_PRELOAD_MODEL=false(지연 로딩)이거나 시작 시 로딩에 실패했을 때 지금 로딩을 시도한다.

        예측 모듈에 ensure_loaded()가 없으면 로딩할 수 없는 것으로 본다 (503).
        """
        ensure_loaded = getattr(self.predictor, "ensure_loaded", None)
        if ensure_loaded is None:
            return False
        return bool(await run_in_threadpool(ensure_loaded))

    def _resolve_image(self, image_id: int, image_url: str) -> Path:
        try:
            path = resolve_xray_path(image_url)
        except ValueError:
            # 저장 폴더 밖 경로: 이유를 숨기고 404, 로그에는 ID만 (설계 8절)
            logger.warning("저장 폴더 밖 X-Ray 경로로 예측 요청: xray_image_id=%s", image_id)
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=IMAGE_NOT_FOUND)
        if not path.is_file():
            logger.warning("예측할 X-Ray 파일 없음: xray_image_id=%s", image_id)
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=IMAGE_NOT_FOUND)
        return path

    async def _infer(self, record_id: int, path: Path):
        async with _inference_slot():  # 동시 추론 수 제한 (설계 9절)
            try:
                prediction = await run_in_threadpool(self.predictor.predict, path)
            except FileNotFoundError:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=IMAGE_NOT_FOUND)
            except ValueError:
                # 이미지가 아니거나 손상: 다시 시도해도 같은 결과 (설계 D9)
                raise HTTPException(status_code=422, detail=INVALID_IMAGE)
            except Exception as e:
                # 모델 오류(RuntimeError 등): 예외 내용·경로는 응답하지 않는다
                logger.error("AI 예측 실패: record_id=%s, %s", record_id, type(e).__name__)
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=TRY_AGAIN_LATER
                ) from e
        if not 0 <= float(prediction.confidence) <= 100:
            logger.error("AI 예측 결과 범위 오류: record_id=%s", record_id)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=TRY_AGAIN_LATER)
        return prediction

    async def _save_heatmap(self, patient_id: int, heatmap) -> str | None:
        """히트맵 Image를 storage/heatmap/{patient_id}/{uuid}.png로 저장하고 상대 경로를 돌려준다 (Q1 결정 전에는 None)"""
        if heatmap is None:
            return None
        relative_path = f"{patient_id}/{uuid.uuid4().hex}.png"
        target = get_storage_root(FILE_KIND_HEATMAP) / relative_path

        def _write():
            target.parent.mkdir(parents=True, exist_ok=True)
            heatmap.save(target, format="PNG")

        try:
            await run_in_threadpool(_write)
        except OSError as e:
            logger.error("히트맵 저장 실패: patient_id=%s", patient_id)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=TRY_AGAIN_LATER
            ) from e
        return relative_path

    async def _discard_heatmap(self, heatmap_path: str | None) -> None:
        if heatmap_path is None:
            return
        try:
            await delete_stored_file(FILE_KIND_HEATMAP, heatmap_path)
        except (OSError, ValueError):
            # 결과와 연결되지 않은 파일이 남는다. 로그로 남겨 운영자가 정리한다 (경로는 기록하지 않음)
            logger.error("저장하지 못한 예측의 히트맵 삭제 실패")
