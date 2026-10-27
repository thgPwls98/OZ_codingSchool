"""통합 테스트용 임시 SQLite DB (aiosqlite 필요)

MySQL 전용 설정 두 가지를 테스트에서만 SQLite에 맞춘다.
- BIGINT PK 자동 증가: SQLite는 INTEGER PRIMARY KEY만 자동 증가하므로 INTEGER로 만든다.
- current_timestamp(0) 기본값: SQLite가 이해하지 못하므로 뺀다 (값은 ORM default로 채워짐).
"""

from pathlib import Path

from sqlalchemy import BigInteger, event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

from app.core.db.databases import Base
import app.models  # noqa: F401  모든 모델을 메타데이터에 등록


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(type_, compiler, **kw):
    return "INTEGER"


def _drop_mysql_only_defaults() -> None:
    for table in Base.metadata.tables.values():
        for column in table.columns:
            default = column.server_default
            if default is not None and "current_timestamp" in str(getattr(default, "arg", "")):
                column.server_default = None


async def create_test_db(directory: Path):
    """임시 폴더에 DB를 만들고 (engine, session_factory)를 돌려준다."""
    _drop_mysql_only_defaults()
    engine = create_async_engine(f"sqlite+aiosqlite:///{directory / 'test.db'}")

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)
