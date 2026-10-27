"""update patient tables for patient api

- patients.phone -> phone_number (이름만 변경, 기존 연락처 유지) (D19)
- patients.gender: NOT NULL
- patients.age: CHECK (age BETWEEN 0 AND 150), 인덱스 추가
- medical_records(patient_id, created_at) 복합 인덱스 추가
- 진료기록·X-Ray·AI 결과 외래키: ON DELETE CASCADE (D4)

자동 생성본은 phone 컬럼을 삭제하고 phone_number를 새로 만들어 기존 연락처가 사라지므로
이름 변경(alter_column)으로 직접 작성했다. (설계 문서 10-1)
xray_images.uploader_id의 ON DELETE SET NULL은 그대로 둔다 (4일차 회원 탈퇴 정책).

Revision ID: a3f5c8e21d47
Revises: 7c1e2a9d4b10
Create Date: 2026-10-27 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a3f5c8e21d47"
down_revision: Union[str, Sequence[str], None] = "7c1e2a9d4b10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

GENDER = sa.Enum("male", "female", name="gender")

# (테이블, 컬럼, 참조 테이블, 기존 외래키 이름, 새 외래키 이름)
# 기존 이름은 초기 마이그레이션에서 MySQL이 자동으로 붙인 이름이다.
CASCADE_FOREIGN_KEYS = [
    ("medical_records", "patient_id", "patients", "medical_records_ibfk_1", "fk_medical_records_patient_id_patients"),
    ("xray_images", "record_id", "medical_records", "xray_images_ibfk_1", "fk_xray_images_record_id_medical_records"),
    ("ai_analysis_results", "record_id", "medical_records", "ai_analysis_results_ibfk_1", "fk_ai_analysis_results_record_id_medical_records"),
]


def upgrade() -> None:
    """Upgrade schema."""
    # 0. 사전 검사. MySQL의 DDL은 실행 즉시 반영되어 롤백되지 않으므로,
    #    중간에 실패해 일부만 적용되지 않도록 변경 전에 모두 확인한다.
    #    NULL 성별·범위 밖 나이는 임의 값으로 고치지 않고 중단한다.
    bind = op.get_bind()
    null_gender_count = bind.execute(
        sa.text("SELECT COUNT(*) FROM patients WHERE gender IS NULL")
    ).scalar_one()
    invalid_age_count = bind.execute(
        sa.text("SELECT COUNT(*) FROM patients WHERE age NOT BETWEEN 0 AND 150")
    ).scalar_one()
    if null_gender_count or invalid_age_count:
        raise RuntimeError(
            f"성별이 비어 있는 환자 {null_gender_count}명, 나이가 0~150 밖인 환자 {invalid_age_count}명이 있습니다. "
            "팀이 정한 값으로 고친 뒤 다시 실행하세요."
        )

    # 1. 연락처 컬럼 이름 변경 (데이터 유지)
    op.alter_column(
        "patients",
        "phone",
        new_column_name="phone_number",
        existing_type=sa.String(length=11),
        existing_nullable=False,
    )

    # 2. 성별 필수
    op.alter_column("patients", "gender", existing_type=GENDER, nullable=False)

    # 3. 나이 범위 제약과 인덱스
    op.create_check_constraint("ck_patients_age_range", "patients", "age BETWEEN 0 AND 150")
    op.create_index("ix_patients_age", "patients", ["age"], unique=False)
    op.create_index(
        "ix_medical_records_patient_id_created_at",
        "medical_records",
        ["patient_id", "created_at"],
        unique=False,
    )

    # 4. 연쇄 삭제
    for table, column, referred, old_name, new_name in CASCADE_FOREIGN_KEYS:
        op.drop_constraint(old_name, table, type_="foreignkey")
        op.create_foreign_key(new_name, table, referred, [column], ["id"], ondelete="CASCADE")


def downgrade() -> None:
    """Downgrade schema."""
    # 복합 인덱스가 생기면 MySQL은 patient_id 단독 인덱스를 지우고 외래키에 복합 인덱스를 쓴다.
    # 외래키가 남아 있으면 이 인덱스를 지울 수 없으므로 외래키 → 인덱스 → 외래키 재생성 순서로 되돌린다.
    for table, _, _, _, new_name in CASCADE_FOREIGN_KEYS:
        op.drop_constraint(new_name, table, type_="foreignkey")

    op.drop_index("ix_medical_records_patient_id_created_at", table_name="medical_records")
    op.drop_index("ix_patients_age", table_name="patients")

    for table, column, referred, old_name, _ in CASCADE_FOREIGN_KEYS:
        op.create_foreign_key(old_name, table, referred, [column], ["id"])

    op.drop_constraint("ck_patients_age_range", "patients", type_="check")

    op.alter_column("patients", "gender", existing_type=GENDER, nullable=True)
    op.alter_column(
        "patients",
        "phone_number",
        new_column_name="phone",
        existing_type=sa.String(length=11),
        existing_nullable=False,
    )
