from decimal import Decimal

from pydantic import BaseModel, field_serializer

from app.models.ai_analysis_result import AIAnalysisResult
from app.schemas.common import UTCDateTime


# ===== 응답 =====
class AnalysisResultResponse(BaseModel):
    """AI 폐렴 예측 결과 (⑫ 예측·⑬ 목록 공통, 6일차 설계 2-2)"""

    id: int
    record_id: int
    is_pneumonia: bool
    confidence: Decimal  # 판정한 클래스의 확률 (%)
    heatmap_url: str | None  # 히트맵 조회 API 경로. 히트맵이 없으면 None
    ai_model: str
    model_version: str
    created_at: UTCDateTime

    @field_serializer("confidence")
    def _confidence(self, value: Decimal) -> float:
        # Decimal은 JSON 문자열("83.28")로 나가므로 숫자로 바꾼다 (설계 D10)
        return float(round(value, 2))


def heatmap_api_path(record_id: int, analysis_id: int) -> str:
    """히트맵 조회 API 경로 (⑭). 파일 위치는 응답하지 않는다 (설계 2-1, D15)"""
    return f"/api/v1/medical-records/{record_id}/analyses/{analysis_id}/heatmap"


def to_analysis_response(result: AIAnalysisResult) -> AnalysisResultResponse:
    """DB의 상대 경로(heatmap_url)를 조회 API 경로로 바꿔 응답을 만든다"""
    return AnalysisResultResponse(
        id=result.id,
        record_id=result.record_id,
        is_pneumonia=result.is_pneumonia,
        confidence=result.confidence,
        heatmap_url=heatmap_api_path(result.record_id, result.id) if result.heatmap_url else None,
        ai_model=result.ai_model,
        model_version=result.model_version,
        created_at=result.created_at,
    )
