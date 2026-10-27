from sqlalchemy.ext.asyncio import AsyncSession

from app.models.patient import Patient


class PatientRepository:
    """patients 테이블에 접근하는 DB 함수 모음.

    API 담당자가 필요한 함수를 이 클래스에 추가한다. (설계 문서 11절)
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, patient_id: int) -> Patient | None:
        return await self.db.get(Patient, patient_id)
