from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.databases import async_get_db
from app.repositories.patient_repository import PatientRepository
from app.services.patient_service import PatientService

# 환자 API 1~5와 진료기록 목록(7)을 이 라우터에 추가한다. (설계 문서 11절)
router = APIRouter(prefix="/api/v1/patients", tags=["patients"])


def get_patient_service(db: Annotated[AsyncSession, Depends(async_get_db)]) -> PatientService:
    return PatientService(PatientRepository(db))
