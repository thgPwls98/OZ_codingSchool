"""create file_cleanup_jobs table

5일차 설계 6-4, D18: 커밋 후 지워야 할 파일을 1개 1행으로 기록한다.
삭제된 자원을 가리키므로 외래키를 두지 않는다.

팀원 1의 환자 테이블 마이그레이션(a3f5c8e21d47) 다음에 이어서 실행한다.

Revision ID: a3f5c9d21e07
Revises: a3f5c8e21d47
Create Date: 2026-10-27 17:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a3f5c9d21e07"
down_revision: Union[str, Sequence[str], None] = "a3f5c8e21d47"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "file_cleanup_jobs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("target_type", sa.String(length=30), nullable=False),
        sa.Column("target_id", sa.BigInteger(), nullable=False),
        sa.Column("file_kind", sa.String(length=20), nullable=False),
        sa.Column("file_path", sa.String(length=2048), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.SmallInteger(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("current_timestamp(0)"),
            nullable=True,
        ),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_file_cleanup_jobs_status_next_attempt_at",
        "file_cleanup_jobs",
        ["status", "next_attempt_at"],
    )
    op.create_index(
        "ix_file_cleanup_jobs_target", "file_cleanup_jobs", ["target_type", "target_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_file_cleanup_jobs_target", table_name="file_cleanup_jobs")
    op.drop_index("ix_file_cleanup_jobs_status_next_attempt_at", table_name="file_cleanup_jobs")
    op.drop_table("file_cleanup_jobs")
