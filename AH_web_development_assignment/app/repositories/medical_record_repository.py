from sqlalchemy import delete, select
from app.core.file_storage import FILE_KIND_HEATMAP, FILE_KIND_XRAY
from app.models.patient import Patient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.ai_analysis_result import AIAnalysisResult
from app.models.medical_record import MedicalRecord
from app.models.xray_image import XrayImage


class MedicalRecordRepository:
    """commit은 호출한 서비스가 담당한다."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def patient_id_for(self, record_id: int) -> int | None:
        return await self.db.scalar(select(MedicalRecord.patient_id).where(MedicalRecord.id == record_id))

    async def lock(self, record_id: int) -> MedicalRecord | None:
        return await self.db.scalar(select(MedicalRecord).where(
            MedicalRecord.id == record_id
        ).with_for_update().execution_options(populate_existing=True))

    async def chart_exists(self, chart_number: str, record_id: int) -> bool:
        return await self.db.scalar(select(MedicalRecord.id).where(
            MedicalRecord.chart_number == chart_number, MedicalRecord.id != record_id
        )) is not None

    async def file_paths(self, record_id: int) -> list[tuple[str, str]]:
        """공통 FILE_KIND_XRAY/FILE_KIND_HEATMAP 값과 종류별 상대 경로를 반환한다."""
        # 부모 잠금 이전 조회의 스냅샷 대신, 잠금 획득 후 최신 경로를 수집한다.
        images = await self.db.scalars(select(XrayImage.image_url).where(XrayImage.record_id == record_id).with_for_update())
        heatmaps = await self.db.scalars(select(AIAnalysisResult.heatmap_url).where(AIAnalysisResult.record_id == record_id).with_for_update())
        return list(dict.fromkeys(
            [(FILE_KIND_XRAY, path) for path in images if path]
            + [(FILE_KIND_HEATMAP, path) for path in heatmaps if path]
        ))

    async def remove_image_data(self, record_id: int) -> None:
        await self.db.execute(delete(AIAnalysisResult).where(AIAnalysisResult.record_id == record_id))
        await self.db.execute(delete(XrayImage).where(XrayImage.record_id == record_id))

    async def response(self, record_id: int) -> dict:
        record = await self.db.scalar(select(MedicalRecord).where(MedicalRecord.id == record_id))
        image = await self.db.scalar(select(XrayImage).where(XrayImage.record_id == record_id).options(
            selectinload(XrayImage.uploader)
        ).order_by(XrayImage.id.desc()))
        return dict(id=record.id, patient_id=record.patient_id, chart_number=record.chart_number,
                    symptoms=record.symptoms, created_at=record.created_at, updated_at=record.updated_at,
                    xray_image_url=f"/api/v1/medical-records/{record.id}/xray-image",
                    uploader_id=image.uploader_id if image else None,
                    uploader_name=image.uploader.name if image and image.uploader else None)

    async def get_patient(self, patient_id: int) -> Patient | None:
        return await self.db.get(Patient, patient_id)

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
