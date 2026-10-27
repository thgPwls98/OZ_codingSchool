from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.file_storage import FILE_KIND_HEATMAP, FILE_KIND_XRAY
from app.models.ai_analysis_result import AIAnalysisResult
from app.models.medical_record import MedicalRecord
from app.models.patient import Patient
from app.models.xray_image import XrayImage
from app.schemas.patient import PatientSearchParams


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

    # ===== 환자 등록·목록 (팀원 1) =====
    async def add(self, patient: Patient) -> Patient:
        """환자를 세션에 추가하고 id를 받는다 (commit은 서비스)"""
        self.db.add(patient)
        await self.db.flush()
        return patient

    async def search(self, params: PatientSearchParams) -> list[Patient]:
        """모든 조건을 AND로 결합하고 최근 등록순으로 반환한다. (설계 문서 4-2)"""
        statement = select(Patient)
        if params.name:
            # 검색어의 %와 _도 와일드카드가 아닌 일반 문자로 검색한다.
            statement = statement.where(Patient.name.contains(params.name, autoescape=True))
        if params.gender is not None:
            statement = statement.where(Patient.gender == params.gender)
        if params.min_age is not None:
            statement = statement.where(Patient.age >= params.min_age)
        if params.max_age is not None:
            statement = statement.where(Patient.age <= params.max_age)
        result = await self.db.execute(statement.order_by(Patient.id.desc()))
        return list(result.scalars().all())

    # ===== 환자 상세·수정·삭제 (팀원 3) =====
    async def file_paths(self, patient_id: int) -> list[tuple[str, str]]:
        """환자 삭제 전에 지울 파일 목록을 모은다. 반드시 lock() 이후에 호출한다. (설계 6-3 ②)

        반환: [(file_kind, 상대 경로), ...]  X-Ray 이미지와 AI 히트맵을 모두 포함하고 중복은 뺀다.
        """
        xray_paths = await self.db.scalars(
            select(XrayImage.image_url)
            .join(MedicalRecord, XrayImage.record_id == MedicalRecord.id)
            .where(MedicalRecord.patient_id == patient_id)
        )
        heatmap_paths = await self.db.scalars(
            select(AIAnalysisResult.heatmap_url)
            .join(MedicalRecord, AIAnalysisResult.record_id == MedicalRecord.id)
            .where(MedicalRecord.patient_id == patient_id)
        )
        files = [(FILE_KIND_XRAY, path) for path in xray_paths if path]
        files += [(FILE_KIND_HEATMAP, path) for path in heatmap_paths if path]
        return list(dict.fromkeys(files))

    async def delete(self, patient: Patient) -> None:
        """환자 행을 지운다. 진료기록·X-Ray·AI 결과는 DB의 ON DELETE CASCADE로 함께 삭제된다. (commit은 서비스)"""
        await self.db.delete(patient)
        await self.db.flush()
