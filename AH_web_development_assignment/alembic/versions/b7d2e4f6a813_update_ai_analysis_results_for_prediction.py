"""update ai_analysis_results for pneumonia prediction api

6일차 설계 7절
- heatmap_url NULL 허용: 히트맵은 선택사항이다 (D4)
- model_version 추가: 같은 이름으로 가중치·threshold가 바뀌어도 구분한다 (D5)
- UNIQUE (record_id, ai_model, model_version): 같은 기록·같은 모델 결과 중복 방지 (D6)
- CHECK confidence 0~100

파일 정리 작업 마이그레이션(a3f5c9d21e07) 다음에 이어서 실행한다.

Revision ID: b7d2e4f6a813
Revises: a3f5c9d21e07
Create Date: 2026-10-28 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b7d2e4f6a813"
down_revision: Union[str, Sequence[str], None] = "a3f5c9d21e07"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 0. 사전 검사. MySQL의 DDL은 실행 즉시 반영되어 롤백되지 않으므로,
    #    UNIQUE·CHECK 생성에서 실패해 일부만 적용되지 않도록 변경 전에 모두 확인한다.
    #    기존 행은 모두 model_version = v1이 되므로 (record_id, ai_model)로 중복을 본다.
    bind = op.get_bind()
    duplicate_count = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM (SELECT record_id, ai_model FROM ai_analysis_results "
            "GROUP BY record_id, ai_model HAVING COUNT(*) > 1) AS duplicates"
        )
    ).scalar_one()
    invalid_confidence_count = bind.execute(
        sa.text("SELECT COUNT(*) FROM ai_analysis_results WHERE confidence NOT BETWEEN 0 AND 100")
    ).scalar_one()
    if duplicate_count or invalid_confidence_count:
        raise RuntimeError(
            f"같은 진료기록·같은 모델 결과가 여러 개인 경우 {duplicate_count}건, "
            f"confidence가 0~100 밖인 결과 {invalid_confidence_count}건이 있습니다. "
            "개발 DB의 테스트 행을 정리한 뒤 다시 실행하세요."
        )

    op.alter_column(
        "ai_analysis_results",
        "heatmap_url",
        existing_type=sa.String(length=255),
        existing_nullable=False,
        nullable=True,
        existing_comment="히트맵 이미지 경로",
        comment="히트맵 이미지 상대 경로",
    )
    # 기존 행은 v1로 채우고, 이후에는 기본값 없이 애플리케이션이 항상 넣는다
    op.add_column(
        "ai_analysis_results",
        sa.Column("model_version", sa.String(length=20), nullable=False, server_default="v1", comment="모델 버전"),
    )
    op.alter_column(
        "ai_analysis_results",
        "model_version",
        existing_type=sa.String(length=20),
        existing_nullable=False,
        server_default=None,
        existing_comment="모델 버전",
    )
    # 같은 (record_id, ai_model) 행이 이미 여러 개 있으면 실패한다. 적용 전 확인 (설계 7절)
    op.create_unique_constraint(
        "uq_ai_analysis_results_record_model",
        "ai_analysis_results",
        ["record_id", "ai_model", "model_version"],
    )
    op.create_check_constraint(
        "ck_ai_analysis_results_confidence_range",
        "ai_analysis_results",
        "confidence BETWEEN 0 AND 100",
    )
    # 이전 downgrade가 만든 record_id 단독 인덱스가 남아 있으면 지운다.
    # UNIQUE의 맨 앞이 record_id라 외래키 인덱스를 대신하고, 남겨 두면 다음 downgrade가 같은 이름으로 실패한다
    indexes = sa.inspect(bind).get_indexes("ai_analysis_results")
    if any(index["name"] == "ix_ai_analysis_results_record_id" for index in indexes):
        op.drop_index("ix_ai_analysis_results_record_id", table_name="ai_analysis_results")


def downgrade() -> None:
    # 히트맵 없는 행(NULL)이 있으면 NOT NULL로 되돌릴 수 없다. 임의 값으로 채우지 않고 중단한다
    null_heatmap_count = op.get_bind().execute(
        sa.text("SELECT COUNT(*) FROM ai_analysis_results WHERE heatmap_url IS NULL")
    ).scalar_one()
    if null_heatmap_count:
        raise RuntimeError(
            f"히트맵이 없는 예측 결과 {null_heatmap_count}건이 있어 되돌릴 수 없습니다. 먼저 정리하세요."
        )

    op.drop_constraint("ck_ai_analysis_results_confidence_range", "ai_analysis_results", type_="check")
    # MySQL은 외래키(record_id)가 쓰는 인덱스를 지울 수 없으므로, 지우기 전에 record_id 단독 인덱스를 만든다
    op.create_index("ix_ai_analysis_results_record_id", "ai_analysis_results", ["record_id"])
    op.drop_constraint("uq_ai_analysis_results_record_model", "ai_analysis_results", type_="unique")
    op.drop_column("ai_analysis_results", "model_version")
    op.alter_column(
        "ai_analysis_results",
        "heatmap_url",
        existing_type=sa.String(length=255),
        existing_nullable=True,
        nullable=False,
        existing_comment="히트맵 이미지 상대 경로",
        comment="히트맵 이미지 경로",
    )
