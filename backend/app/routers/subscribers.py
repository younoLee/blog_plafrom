"""이메일 뉴스레터 구독 — **2026-07-31에 폐지됨. 남은 건 관리자용 정리 수단뿐이다.**

왜 폐지했나. 2026-07-18에 '전역 뉴스레터'를 없애고 **글쓴이별 계정 구독**
(`author_subscriptions` + `notify`)으로 일원화했다. 그때 화면과 발송 쪽은 갈아탔는데
**수집 쪽(이 라우터)을 안 뗐다.** 그래서 07-31 심층검사에서 이런 상태가 드러났다:

  · `POST /api/subscribers`가 살아 있어 임의의 주소로 확인 메일을 쐈다
  · 그런데 `Subscriber` 테이블을 **발송에 쓰는 코드가 없다** — 확인을 눌러도 그 뒤가 없다
  · 게다가 SES는 샌드박스라 검증된 3개 주소 외에는 554로 거부되는데, 발송이
    BackgroundTask라 방문자에겐 **200 "확인 메일을 보냈어"**가 그대로 나갔다
    (실측: 메일 서버를 죽여놓고 호출 → HTTP 200, 로그엔 처리 안 된 트레이스백만)

즉 '아무 데도 닿지 않는 확인 메일을, 닿았다고 말하면서' 보내고 있었다. 그리고 그게
이 앱에서 **검증 안 된 임의 주소로 메일이 나가는 유일한 경로**였다 — 가입은 초대제로
닫혀 있고(config.allow_signup=False), 나머지 메일은 전부 등록된 계정 주소로만 간다.
이 라우터를 떼면서 SES 프로덕션 액세스가 없어도 되는 상태가 됐다.

**관리자 목록·삭제만 남긴다.** 운영 DB에 이미 쌓인 구독자 주소는 개인정보라, 폐지했다고
조회 수단까지 없애면 남은 것을 확인하고 지울 방법이 사라진다. 테이블과 데이터는
여기서 건드리지 않는다(되돌릴 수 없는 일이라 별도 판단).

지운 것: POST "" (구독 신청) · POST /confirm · POST /unsubscribe · GET·POST·DELETE /me
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_admin
from app.models.subscriber import Subscriber
from app.models.user import User
from app.schemas.subscriber import SubscriberRead

router = APIRouter(prefix="/subscribers", tags=["subscribers"])


@router.get("", response_model=list[SubscriberRead])
def list_subscribers(
    db: Session = Depends(get_db), admin: User = Depends(require_admin)
):
    # 구독자 이메일 목록은 관리자만 (예전엔 무인증 노출 = PII 유출)
    return db.scalars(select(Subscriber).order_by(Subscriber.created_at.desc())).all()


@router.delete("/{subscriber_id}", status_code=204)
def remove_subscriber(
    subscriber_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    # 이메일 구독자 삭제는 관리자만 (PII 목록 관리)
    sub = db.get(Subscriber, subscriber_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="구독자를 찾을 수 없음")
    db.delete(sub)
    db.commit()
