"""AI 예측 결과 조회 서비스 (6일차 설계 4-2, REQ-PRED-002)

⑬ 예측 결과 목록만 담당한다. ⑫ 예측 실행은 prediction_service.py(C 담당)가 따로 맡는다.
목록 조회는 추론하지 않으므로 모델 로드 여부와 무관하게 동작한다.
"""

from fastapi import HTTPException, status

from app.repositories.analysis_repository import AnalysisRepository
from app.repositories.medical_record_repository import MedicalRecordRepository
from app.schemas.analysis import AnalysisResultResponse, to_analysis_response

RECORD_NOT_FOUND = "진료기록을 찾을 수 없습니다."


class AnalysisService:
    def __init__(self, records: MedicalRecordRepository, analyses: AnalysisRepository):
        self.records = records
        self.analyses = analyses

    async def list_by_record(self, record_id: int) -> list[AnalysisResultResponse]:
        """진료기록의 예측 결과를 최신순으로 돌려준다.

        - 진료기록이 없으면 404
        - 결과가 없으면 빈 배열 (화면이 "저장된 예측 결과가 없습니다."를 표시한다, 설계 1-4)
        - 범위는 현재 진료기록의 결과다. 환자 단위 목록은 F8 (설계 1-5, Q7)
        """
        if not await self.records.exists(record_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=RECORD_NOT_FOUND)
        results = await self.analyses.list_by_record(record_id)
        return [to_analysis_response(result) for result in results]
