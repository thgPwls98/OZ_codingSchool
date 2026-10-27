from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.patient import Patient


class PatientRepository:
    """patients 테이블에 접근하는 DB 함수 모음.

    API 담당자가 필요한 함수를 이 클래스에 추가한다. (설계 문서 11절)
    팀 규칙: 저장소는 commit·rollback하지 않는다. 서비스가 DB 변경과 파일 정리 작업을 함께 commit한다.
    잠금 순서는 항상 환자 → 진료기록이다 (5일차 설계 6-4 ①).
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, patient_id: int) -> Patient | None:
        return await self.db.get(Patient, patient_id)

    async def lock(self, patient_id: int) -> Patient | None:
        """환자 행을 잠근다 (SELECT ... FOR UPDATE). 트랜잭션이 끝날 때까지 같은 환자의 등록·수정·삭제와 직렬화된다.

        환자 삭제(⑤), 진료기록 등록·수정·삭제(⑥⑩⑪)에서 진료기록보다 먼저 호출한다.
        """
        result = await self.db.execute(
            select(Patient).where(Patient.id == patient_id).with_for_update()
        )
        return result.scalar_one_or_none()
