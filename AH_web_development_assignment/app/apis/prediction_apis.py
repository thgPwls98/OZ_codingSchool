"""⑫ AI 폐렴 예측 API (REQ-PRED-001, 6일차 설계 4-1절) — 3단계 C

⑬ 결과 목록(B)과 파일이 겹치지 않도록 별도 라우터로 둔다. 주소는 설계·프론트 계약 그대로다.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.databases import async_get_db
from app.core.dependencies import StaffUser
from app.repositories.analysis_repository import AnalysisRepository  # 3단계 A
from app.schemas.analysis import AnalysisResultResponse, to_analysis_response  # 3단계 A
from app.services.prediction_service import PredictionService

router = APIRouter(prefix="/api/v1", tags=["ai-analyses"])

RecordId = Annotated[int, Path(ge=1, description="진료기록 ID")]


def get_predictor():
    """1단계 예측 모듈(worker.model)을 돌려준다. 테스트에서는 가짜 모듈로 바꿔 끼운다.

    torch를 앱 import 시점이 아니라 처음 필요할 때 불러오도록 함수 안에서 import한다.
    """
    from worker import model

    return model


def get_prediction_service(
    db: Annotated[AsyncSession, Depends(async_get_db)],
    predictor: Annotated[object, Depends(get_predictor)],
) -> PredictionService:
    return PredictionService(db, predictor, AnalysisRepository(db))


# REQ-PRED-001 AI 폐렴 예측
@router.post(
    "/medical-records/{record_id}/predict",
    response_model=AnalysisResultResponse,
    status_code=status.HTTP_201_CREATED,
    summary="AI 폐렴 예측 (같은 모델 결과가 있으면 재사용)",
    responses={
        200: {"description": "같은 진료기록·같은 모델 결과가 있어 추론 없이 재사용", "model": AnalysisResultResponse},
        401: {"description": "인증 실패"},
        403: {"description": "대기자·비활성 계정"},
        404: {"description": "진료기록 또는 X-Ray 이미지 없음"},
        409: {"description": "추론하는 사이 X-Ray가 교체됨"},
        422: {"description": "record_id 형식 오류, 이미지로 읽히지 않는 파일"},
        500: {"description": "추론·저장 실패"},
        503: {"description": "AI 모델이 메모리에 없음"},
    },
)
async def predict_pneumonia(
    record_id: RecordId,
    response: Response,
    _: StaffUser,
    service: Annotated[PredictionService, Depends(get_prediction_service)],
):
    result, created = await service.predict(record_id)
    if created:
        response.headers["Location"] = f"/api/v1/medical-records/{record_id}/analyses"
    else:
        response.status_code = status.HTTP_200_OK  # 재사용 (설계 D7)
    return to_analysis_response(result)
