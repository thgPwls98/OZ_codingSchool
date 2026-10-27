"""운영 데이터를 변경하지 않고 USER API에 필요한 DB 스키마를 확인한다."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import inspect, text
from app.core.db.databases import async_engine


def check(connection):
    inspector = inspect(connection)
    columns = {column['name']: column for column in inspector.get_columns('users')}
    for name in ('email', 'hashed_password', 'name', 'phone_number'):
        assert not columns[name]['nullable'], f'users.{name} must be NOT NULL'
    for name, expected in [('department', {'research', 'medical', 'development'}), ('role', {'pending', 'staff', 'admin'})]:
        assert set(columns[name]['type'].enums) == expected, f'users.{name} enum mismatch'
    images = {column['name']: column for column in inspector.get_columns('xray_images')}
    assert images['uploader_id']['nullable'], 'uploader_id must allow NULL'
    assert any(fk['constrained_columns'] == ['uploader_id'] and fk['referred_table'] == 'users' and fk.get('options', {}).get('ondelete', '').upper() == 'SET NULL' for fk in inspector.get_foreign_keys('xray_images')), 'uploader_id requires ON DELETE SET NULL'
    versions = connection.execute(text('SELECT version_num FROM alembic_version')).scalars().all()
    print(f'USER schema OK; Alembic revisions: {versions}')


async def main():
    try:
        async with async_engine.connect() as connection:
            await connection.run_sync(check)
    finally:
        await async_engine.dispose()


if __name__ == '__main__':
    asyncio.run(main())
