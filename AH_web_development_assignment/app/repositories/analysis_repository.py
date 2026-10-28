from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_analysis_result import AIAnalysisResult


class AnalysisRepository:
    """ai_analysis_results 테이블에 접근하는 DB 함수 모음 (6일차 설계 12-3)

    팀 규칙: 저장소는 commit하지 않는다. commit은 서비스가 담당한다.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_current(self, record_id: int, ai_model: str, model_version: str) -> AIAnalysisResult | None:
        """이 진료기록에 현재 모델로 저장된 결과 (⑫ 재사용 판단, 설계 4-1 처리 규칙 2)"""
        return await self.db.scalar(
            select(AIAnalysisResult).where(
                AIAnalysisResult.record_id == record_id,
                AIAnalysisResult.ai_model == ai_model,
                AIAnalysisResult.model_version == model_version,
            )
        )

    async def list_by_record(self, record_id: int) -> list[AIAnalysisResult]:
        """진료기록의 예측 결과를 최신순으로 조회한다 (⑬, 설계 4-2)

        UNIQUE (record_id, ai_model, model_version) 인덱스가 record_id 조회에 쓰인다.
        """
        result = await self.db.execute(
            select(AIAnalysisResult)
            .where(AIAnalysisResult.record_id == record_id)
            .order_by(AIAnalysisResult.created_at.desc(), AIAnalysisResult.id.desc())
        )
        return list(result.scalars().all())

    async def add(
        self,
        record_id: int,
        *,
        is_pneumonia: bool,
        confidence: float,
        ai_model: str,
        model_version: str,
        heatmap_url: str | None = None,
    ) -> AIAnalysisResult:
        """결과 1행을 세션에 추가하고 id를 받는다 (⑫ 저장, 설계 6-1 ⑩)

        같은 (record_id, ai_model, model_version)이 이미 있으면 flush에서 IntegrityError가 난다.
        서비스가 rollback 후 먼저 저장된 결과를 응답한다 (설계 D6).
        """
        result = AIAnalysisResult(
            record_id=record_id,
            is_pneumonia=is_pneumonia,
            # float를 그대로 넣으면 0.1 같은 값이 이진 오차를 가진 채 저장되므로 두 자리 Decimal로 바꾼다
            confidence=Decimal(str(round(confidence, 2))),
            heatmap_url=heatmap_url,
            ai_model=ai_model,
            model_version=model_version,
        )
        self.db.add(result)
        await self.db.flush()
        return result

    async def refresh(self, result: AIAnalysisResult) -> None:
        """commit 후 DB가 채운 값(created_at 등)을 다시 읽는다 (설계 6-1 ⑩, D13)

        응답을 만들며 만료된 속성에 접근하면 AsyncSession에서 MissingGreenlet이 날 수 있다.
        """
        await self.db.refresh(result)
