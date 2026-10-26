"""update users department/role enums and required columns

- department: radiology/administration -> research/medical/development
- role: admin/doctor/user -> pending/staff/admin (기본값 pending)
- email, hashed_password, name, phone_number: NOT NULL
- xray_images.uploader_id: NULL 허용 + ON DELETE SET NULL
  (회원 탈퇴 시 X-Ray 기록은 보존하고 업로더만 비운다, 설계 문서 12-4절)

기존 행에 새 Enum에 없는 값(radiology, doctor 등)이 남아 있으면 실패한다.
기존 데이터의 매핑을 결정한 뒤 해당 행을 정리하고 실행한다.

Revision ID: 7c1e2a9d4b10
Revises: 38b51983c575
Create Date: 2026-10-26 16:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "7c1e2a9d4b10"
down_revision: Union[str, Sequence[str], None] = "38b51983c575"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_DEPARTMENT = sa.Enum("radiology", "administration", name="department")
NEW_DEPARTMENT = sa.Enum("research", "medical", "development", name="department")
OLD_ROLE = sa.Enum("admin", "doctor", "user", name="role")
NEW_ROLE = sa.Enum("pending", "staff", "admin", name="role")


def _set_required(nullable: bool) -> None:
    op.alter_column("users", "email", existing_type=sa.String(length=255), nullable=nullable)
    op.alter_column("users", "hashed_password", existing_type=sa.String(length=255), nullable=nullable)
    op.alter_column("users", "name", existing_type=sa.String(length=20), nullable=nullable)
    op.alter_column("users", "phone_number", existing_type=sa.String(length=20), nullable=nullable)


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(
        "users", "department", existing_type=OLD_DEPARTMENT, type_=NEW_DEPARTMENT, existing_nullable=False
    )
    op.alter_column(
        "users",
        "role",
        existing_type=OLD_ROLE,
        type_=NEW_ROLE,
        existing_nullable=False,
        server_default="pending",
    )
    _set_required(nullable=False)

    # 회원 탈퇴 시 X-Ray 기록은 보존하고 업로더만 비운다 (설계 문서 12-4)
    op.drop_constraint("xray_images_ibfk_2", "xray_images", type_="foreignkey")
    op.alter_column(
        "xray_images",
        "uploader_id",
        existing_type=sa.Integer(),
        nullable=True,
        existing_comment="업로드한 의료진 ID",
    )
    op.create_foreign_key(
        "fk_xray_images_uploader_id_users",
        "xray_images",
        "users",
        ["uploader_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Downgrade schema."""
    # uploader_id가 NULL인 행(탈퇴한 사용자)이 있으면 NOT NULL로 되돌릴 수 없다.
    op.drop_constraint("fk_xray_images_uploader_id_users", "xray_images", type_="foreignkey")
    op.alter_column(
        "xray_images",
        "uploader_id",
        existing_type=sa.Integer(),
        nullable=False,
        existing_comment="업로드한 의료진 ID",
    )
    op.create_foreign_key("xray_images_ibfk_2", "xray_images", "users", ["uploader_id"], ["id"])

    _set_required(nullable=True)
    op.alter_column(
        "users",
        "role",
        existing_type=NEW_ROLE,
        type_=OLD_ROLE,
        existing_nullable=False,
        server_default=None,
    )
    op.alter_column(
        "users", "department", existing_type=NEW_DEPARTMENT, type_=OLD_DEPARTMENT, existing_nullable=False
    )
