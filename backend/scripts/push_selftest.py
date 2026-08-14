"""등록된 기기로 **테스트 알림 한 통**을 보낸다. 프로드 컨테이너 안에서 실행한다.

왜 이 스크립트가 필요한가 — 2026-08-09에 Web Push를 배포했는데 "브라우저 실물 왕복
미확인"이 그때부터 계속 열린 채였다. 확인이 안 된 이유는 **트리거가 하나뿐**이기
때문이다: 알림은 `POST /api/posts`(공개 글 생성)에서만 나간다. 그래서 실물 확인을
하려면 공개 블로그에 시험용 글을 올렸다가 지워야 했고, 그게 매번 미뤄졌다.

이 스크립트는 발송 경로만 그대로 태운다 — VAPID 서명 → 벤더 푸시 서비스 → 서비스
워커 → 화면. 글을 만들지 않는다.

⚠️ **무엇을 증명하고 무엇을 증명하지 않는가.**
  증명한다: 키·암호화·서명·엔드포인트 허용목록·서비스워커·알림 표시(사람이 봄).
  증명 못 한다: '새 글이 나면 누구에게 가는가'라는 **대상 선정**(AuthorSubscription의
  approved·notify 조건). 그건 pytest가 잡는 부분이고, 이 스크립트는 그 뒤의 배관이다.
  둘을 섞어 "푸시 전부 확인됨"이라고 적으면 그 기록이 나중에 거짓말이 된다.

사용 (EC2에서):
  cd ~/blog && sudo docker compose -f docker-compose.prod.yml exec -T backend \
      python scripts/push_selftest.py you@example.com

인자를 안 주면 등록된 구독 전부의 소유자 목록만 보여주고 끝낸다(오발송 방지).
"""

import sys

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.push_subscription import PushSubscription
from app.models.user import User
from app.services.push import PushGone, send_push


def main() -> None:
    email = sys.argv[1] if len(sys.argv) > 1 else None

    db = SessionLocal()
    try:
        rows = db.execute(
            select(PushSubscription, User)
            .join(User, User.id == PushSubscription.user_id)
            .order_by(PushSubscription.id)
        ).all()

        if not rows:
            print("등록된 푸시 구독이 0건입니다.")
            print("  브라우저에서 로그인 → 알림 켜기를 먼저 하세요(iOS는 홈 화면에 추가한 PWA여야 합니다).")
            return

        if email is None:
            print(f"등록된 구독 {len(rows)}건 — 보낼 대상을 인자로 지정하세요:")
            for sub, user in rows:
                # 엔드포인트는 그 자체가 기기 식별자라 통째로 찍지 않는다(services/push.py와 같은 규칙).
                host = sub.endpoint.split("/")[2] if "//" in sub.endpoint else "?"
                print(f"  - {user.email}  ({host}, id={sub.id})")
            return

        targets = [(s, u) for s, u in rows if u.email == email]
        if not targets:
            sys.exit(f"{email} 의 구독이 없습니다.")

        sent = gone = failed = 0
        for sub, user in targets:
            host = sub.endpoint.split("/")[2] if "//" in sub.endpoint else "?"
            try:
                send_push(
                    sub.endpoint,
                    sub.p256dh,
                    sub.auth,
                    {
                        "title": "알림 배선 점검",
                        # 한글을 넣는 이유: 암호화 경로가 바이트 길이를 잘못 다루면
                        # ASCII로는 통과하고 한글에서만 깨진다(멀티바이트).
                        "body": "이 알림이 보이면 실물 왕복이 확인된 것입니다.",
                        "url": "/",
                    },
                )
                sent += 1
                print(f"  보냄 → {user.email} ({host}, id={sub.id})")
            except PushGone as e:
                # 여기서 지우지 않는다 — 점검이 데이터를 바꾸면 '점검했더니 사라졌다'가 된다.
                # 실제 발송 경로(notify_new_post_push)는 이 예외를 받아 행을 지운다.
                gone += 1
                print(f"  만료 → {user.email} ({host}, id={sub.id}): {e}")
            except Exception as e:  # noqa: BLE001 - 점검 스크립트라 원인을 그대로 보여준다
                failed += 1
                print(f"  실패 → {user.email} ({host}, id={sub.id}): {type(e).__name__}: {e}")

        print(f"\n보냄 {sent} · 만료 {gone} · 실패 {failed}")
        if sent:
            print("⚠️ '보냄'은 푸시 서비스가 받았다는 뜻입니다. **화면에 떴는지는 사람이 봐야** 끝입니다.")
        if failed or gone:
            sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
