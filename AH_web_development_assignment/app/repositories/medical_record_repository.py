from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.medical_record import MedicalRecord
from app.models.patient import Patient
from app.models.xray_image import XrayImage


class MedicalRecordRepository:
    """medical_records, xray_images 테이블에 접근하는 DB 함수 모음.

    팀 규칙: 저장소는 commit·rollback하지 않는다. 서비스가 DB 변경과 파일 정리 작업을 함께 commit한다.
    잠금 순서는 항상 환자(PatientRepository.lock) → 진료기록(lock)이다 (5일차 설계 6-4 ①).
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_patient(self, patient_id: int) -> Patient | None:
        return await self.db.get(Patient, patient_id)

    async def lock(self, record_id: int) -> MedicalRecord | None:
        """진료기록 행을 잠근다 (SELECT ... FOR UPDATE). 반드시 환자를 먼저 잠근 뒤 호출한다.

        진료기록 수정·삭제(⑩⑪)와 환자 삭제(⑤)에서 공통으로 쓴다.
        """
        result = await self.db.execute(
            select(MedicalRecord).where(MedicalRecord.id == record_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_by_chart_number(self, chart_number: str) -> MedicalRecord | None:
        result = await self.db.execute(
            select(MedicalRecord).where(MedicalRecord.chart_number == chart_number)
        )
        return result.scalar_one_or_none()

    async def add_with_image(self, record: MedicalRecord, image: XrayImage) -> None:
        """진료기록 1행과 X-Ray 이미지 1행을 세션에 추가한다 (commit은 서비스, 설계 6-1 ⑤)"""
        self.db.add(record)
        await self.db.flush()  # record.id를 먼저 받아 이미지에 연결한다.
        image.record_id = record.id
        self.db.add(image)
        await self.db.flush()
