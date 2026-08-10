from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Comment(Base):
    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    # 어떤 글의 댓글인지. ondelete CASCADE: 글이 지워지면 그 댓글들도 같이 삭제
    post_id: Mapped[int] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"), index=True
    )
    # 작성자 계정. **NULL이 '익명'이라는 뜻이고 그게 이 컬럼의 전부다.**
    # 계정이 지워지면 SET NULL = 익명으로 남는다(대화를 지우지 않는다).
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # 화면에 보이는 이름. 회원은 서버가 덮어쓰고 익명만 자유 입력이다(routers/comments.py).
    # 즉 이건 신원이 아니라 표시값이다 — **여기로 회원 여부를 판단하지 말 것.**
    # 익명이 회원과 같은 문자열을 칠 수 있고, 실제로 그렇게 관리자 사칭 댓글이 달렸다
    # (2026-08-10 무인증 재현).
    author: Mapped[str] = mapped_column(String(50))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    @property
    def is_member(self) -> bool:
        """로그인 계정으로 쓴 댓글인가. 응답 스키마(CommentRead)가 이걸 읽는다.

        **컬럼으로 저장하지 않고 파생시킨다.** 저장하면 user_id와 어긋날 수 있는 두 번째
        진실이 생기고, 어긋나는 쪽이 하필 화면의 배지다.
        라우터가 아니라 여기 두는 이유: 목록 조회가 ORM 행을 그대로 돌려주고 Pydantic이
        from_attributes로 읽으므로, 모델에 있어야 조회 경로가 한 줄도 안 바뀐다.
        relationship이 아니라 순수 파이썬 property라 lazy 로딩도 안 붙는다
        (이 저장소의 무-relationship 방침 유지).
        """
        return self.user_id is not None
