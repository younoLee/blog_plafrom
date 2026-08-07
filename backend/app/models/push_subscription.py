from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PushSubscription(Base):
    """브라우저 푸시 구독 — '어느 기기로 알림을 받을지'.

    **AuthorSubscription.notify와 역할이 다르다.** 그쪽은 "이 글쓴이의 새 글 알림을
    받겠다"는 *의사*고, 이건 "그 알림을 이 기기로 보내라"는 *경로*다. 한 사람이
    노트북·폰에서 각각 구독하면 행이 둘 생기고, 알림 의사는 여전히 하나다.
    그래서 기존 플래그를 건드리지 않고 채널만 하나 붙일 수 있었다.

    왜 이 채널을 붙였나 — 이메일 알림이 사실상 안 닿는다. 발신 도메인이 없어
    (MAIL_FROM이 gmail.com) SPF·DKIM 정렬이 깨지고, 받는 쪽이 스팸함으로 보낸다.
    SES 프로덕션 액세스를 받아냈어도 그 문제는 그대로였을 것이다(원인이 다르다).
    푸시는 SES를 아예 안 거치므로 그 사슬에서 벗어난다.

    저장하는 값은 브라우저가 `pushManager.subscribe()`로 돌려주는 것 그대로다:
      endpoint  푸시 서비스 URL(브라우저 벤더마다 다름). 이게 사실상의 기기 식별자다
      p256dh    구독자 공개키 — 페이로드 암호화에 쓴다
      auth      인증 시크릿 — 같은 용도

    **endpoint를 unique로 둔다.** 같은 브라우저가 다시 구독하면 벤더가 같은
    endpoint를 돌려주는데, 그때 행이 쌓이면 알림이 중복 발송된다. 재구독은
    '새로 만들기'가 아니라 '주인 갱신'으로 처리한다(routers/push.py).

    구독은 사용자가 끄지 않아도 **서버가 죽었다고 알려준다** — 발송 시 404/410이
    오면 그 구독은 영구히 무효다(브라우저 데이터 삭제·앱 제거 등). 그때 지운다."""

    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # 푸시 서비스 URL. 길이 제한이 표준에 없어 Text로 둔다(FCM은 200자 안팎이지만
    # 벤더가 바꿔도 잘리지 않게). unique 인덱스는 마이그레이션에서 md5 해시가 아니라
    # 전체 값에 건다 — Postgres 인덱스 상한(약 2700B)보다 훨씬 짧아 문제없다.
    # index=True를 빼면 SQLAlchemy가 유니크 '제약'(pg_constraint)을 내는데,
    # 마이그레이션은 유니크 '인덱스'를 낸다 → autogenerate가 영구 드리프트를 본다.
    # 초대 테이블에서 같은 실수를 하고 고쳤는데 여기서 되풀이했다(2026-08-07 검사).
    endpoint: Mapped[str] = mapped_column(Text, unique=True, index=True)
    p256dh: Mapped[str] = mapped_column(String(255))
    auth: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
