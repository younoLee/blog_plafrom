"""add trgm search indexes

Revision ID: e33a24b1fedd
Revises: fd4126c0deb5
Create Date: 2026-07-17 03:40:59.377483

한국어는 to_tsvector가 형태소를 몰라 풀텍스트 검색이 사실상 안 먹는다
('블로그'로 검색해도 '블로그를'이 안 잡힘). 그래서 pg_trgm 확장 + GIN 인덱스로
ILIKE '%…%' 부분일치를 인덱스 스캔한다.

주의: trigram이라 2글자 이하 검색어는 인덱스를 못 타고 순차 스캔이 된다
(라우터에서 q의 min_length=2로 1글자는 막아둠).
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'e33a24b1fedd'
down_revision: Union[str, None] = 'fd4126c0deb5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # pg_trgm은 Postgres 기본 배포에 포함된 확장. RDS도 rds_superuser로 설치 가능.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_index(
        "ix_posts_title_trgm",
        "posts",
        ["title"],
        postgresql_using="gin",
        postgresql_ops={"title": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_posts_content_trgm",
        "posts",
        ["content"],
        postgresql_using="gin",
        postgresql_ops={"content": "gin_trgm_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_posts_content_trgm", table_name="posts")
    op.drop_index("ix_posts_title_trgm", table_name="posts")
    # 확장은 남긴다 — 다른 곳에서 쓸 수 있고, 지우면 의존 인덱스가 있을 때 실패한다.
