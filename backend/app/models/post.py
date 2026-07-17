from datetime import datetime
from sqlalchemy import String, Text, DateTime, ForeignKey, func, Index
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class Post(Base):
    __tablename__ = "posts"
    __table_args__ = (
        # 태그 필터(tags @> ARRAY[...])가 전체스캔 대신 인덱스를 타도록 GIN 인덱스
        Index("ix_posts_tags", "tags", postgresql_using="gin"),
        # 검색(ILIKE '%…%')용 trigram GIN 인덱스. 한국어는 to_tsvector가 형태소를
        # 몰라 풀텍스트가 안 먹으므로 pg_trgm으로 부분일치를 인덱스 스캔한다.
        # 주의: trigram이라 2글자 이하 검색어는 인덱스를 못 타고 순차 스캔이 된다.
        Index(
            "ix_posts_title_trgm",
            "title",
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
        ),
        Index(
            "ix_posts_content_trgm",
            "content",
            postgresql_using="gin",
            postgresql_ops={"content": "gin_trgm_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    # 커버(대표) 이미지 URL — 선택. /api/upload 로 올린 이미지 URL을 저장. 없으면 None
    cover_image: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # 태그(다중) — Postgres 텍스트 배열로 저장. 기본 빈 배열. 태그로 글 필터에 사용
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), server_default="{}")
    # 연재 이름 — 같은 값을 가진 글이 한 시리즈가 되고, 순서는 created_at.
    # 제목의 '#7' 같은 번호를 파싱하지 않는 이유: 제목을 고치면 순서가 깨지고,
    # 번호를 매기려면 글마다 손으로 붙여야 한다. 이름만 같으면 되게 두는 게 단순하다.
    series: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    # 작성자. 기존(로그인 전) 글은 owner 없음 → nullable
    owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    # 공개범위: 'public'(전체공개) | 'subscribers'(구독자공개) | 'private'(나만 보기)
    # 'subscribers'가 11자라 varchar(20)으로 둠. 기존 글은 public
    visibility: Mapped[str] = mapped_column(String(20), server_default="public")
    # server_default=func.now(): DB가 INSERT 시 현재 시각을 채움
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # onupdate: UPDATE 될 때마다 시각 자동 갱신
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
