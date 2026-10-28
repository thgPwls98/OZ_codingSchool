"""AI 예측 결과 조회 API (6일차 설계 3절 ⑬, REQ-PRED-002)

⑫ 예측 실행(POST /predict)은 파일 충돌을 막기 위해 prediction_apis.py(C 담당)에 따로 둔다.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.databases import async_get_db
from app.core.dependencies import StaffUser
from app.repositories.analysis_repository import AnalysisRepository
from app.repositories.medical_record_repository import MedicalRecordRepository
from app.schemas.analysis import AnalysisResultResponse
from app.services.analysis_service import AnalysisService

router = APIRouter(prefix="/api/v1", tags=["ai-analysis"])

RecordId = Annotated[int, Path(ge=1, description="진료기록 ID")]


def get_analysis_service(
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> AnalysisService:
    return AnalysisService(MedicalRecordRepository(db), AnalysisRepository(db))


# REQ-PRED-002 ⑬ 예측 결과 목록
# 경로·배열 응답은 프론트엔드(static/apis.js getAnalyses, pages.js renderRecordDetail)가 이미 정해 두었다 (설계 1-4, D1, D16).
# 권한: 정의서의 행위자는 의료·개발·연구 부서인데 Department Enum이 이 세 값뿐이므로 StaffUser를 그대로 쓴다 (설계 1-2).
@router.get(
    "/medical-records/{record_id}/analyses",
    response_model=list[AnalysisResultResponse],
    summary="AI 폐렴 예측 결과 목록 조회",
    responses={
        401: {"description": "인증 실패"},
        403: {"description": "대기자·비활성 계정"},
        404: {"description": "진료기록 없음 (결과가 없으면 200 [])"},
    },
)
async def list_analyses(
    record_id: RecordId,
    current_user: StaffUser,
    service: Annotated[AnalysisService, Depends(get_analysis_service)],
):
    return await service.list_by_record(record_id)
