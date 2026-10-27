from sqlalchemy import event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from typing import AsyncGenerator
from app.core.config import settings


DATABASE_PREFIX = "mysql+asyncmy://"
DATABASE_URI = f"{settings.DB_USER}:{settings.DB_PASSWORD}@{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}"
DATABASE_URL = f"{DATABASE_PREFIX}{DATABASE_URI}"

# 비동기 엔진 생성
async_engine = create_async_engine(DATABASE_URL, echo=False, future=True)


# DB 세션 시간대를 UTC로 통일한다. (설계 문서 2-1)
# server_default(current_timestamp)로 채워지는 값도 UTC로 저장된다.
@event.listens_for(async_engine.sync_engine, "connect")
def set_utc_time_zone(dbapi_connection, _):
    cursor = dbapi_connection.cursor()
    cursor.execute("SET time_zone = '+00:00'")
    cursor.close()

# 비동기 세션 팩토리 생성
AsyncSessionLocal = async_sessionmaker(bind=async_engine, autoflush=False, expire_on_commit=False)
# 모델 베이스 생성
Base = declarative_base()

# 세션 생성 함수
async def async_get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as db:
        yield db
