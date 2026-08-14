"""개발일지 마크다운을 블로그 글로 발행. EC2의 백엔드 컨테이너 안에서 실행한다.

컨테이너 안에서 도는 이유: DB(같은 호스트의 Postgres 컨테이너)는 호스트에 포트를
노출하지 않아 compose 네트워크 안에서만 닿고, 컨테이너엔 이미
DB 자격증명(.env)과 앱 모델이 있다. 덕분에 계정 비밀번호 없이 발행할 수 있다.

created_at을 실제 작업일로 소급하는 것도 여기서 한다. API(POST /api/posts)는
created_at을 서버가 now()로 채워서 소급이 불가능하다.

멱등: 같은 제목의 글이 이미 있으면 내용을 갱신만 한다(재실행해도 중복 생성 없음).

알림: **새로 만든 글에만** 인앱·메일·푸시 알림을 보낸다(2026-08-14 추가). 갱신에는
안 보낸다 — 오타 하나 고칠 때마다 구독자에게 옛 글 알림이 울리면 안 된다.
그전까지 이 스크립트는 `POST /api/posts`를 거치지 않아 알림이 **한 번도 안 나갔다.**
개발일지가 이 블로그의 거의 모든 글인데, 전부 조용히 올라가고 있었다.

실행 (EC2에 ssh로 들어가서, ~/blog 에서):
  # ① 호스트 /tmp → 컨테이너 /tmp. 둘은 다른 파일시스템이라 scp만으론 안 들어간다.
  docker compose -f docker-compose.prod.yml cp /tmp/publish_devlogs.py backend:/tmp/publish_devlogs.py
  docker compose -f docker-compose.prod.yml cp /tmp/devlog_posts.json  backend:/tmp/devlog_posts.json
  # ② PYTHONPATH=/app 이 필요하다 — python이 스크립트를 실행할 땐 sys.path[0]이
  #    '스크립트가 있는 디렉터리'(=/tmp)라서, WORKDIR이 /app이어도 app 모듈을 못 찾는다
  #    (ModuleNotFoundError: No module named 'app'). 2026-07-22에 걸렸다.
  docker compose -f docker-compose.prod.yml exec -T -e PYTHONPATH=/app backend \
      python /tmp/publish_devlogs.py /tmp/devlog_posts.json

payload(devlog_posts.json) 형식 — 항목당:
  date "2026-07-20" / title / content(마크다운, H1 제외) / tags(리스트) / series(선택)
"""

import json
import sys
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.author_subscription import AuthorSubscription
from app.models.notification import Notification
from app.models.post import Post
from app.models.user import User
from app.schemas.post import PostCreate
from app.services.email import notify_new_post
from app.services.push import notify_new_post_push


def main() -> None:
    payload_path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/devlog_posts.json"
    with open(payload_path, encoding="utf-8") as f:
        posts = json.load(f)

    db = SessionLocal()
    try:
        owner = db.scalar(select(User).where(User.role == "admin").order_by(User.id))
        if owner is None:
            sys.exit("admin 계정을 찾지 못했습니다. 글 소유자를 정할 수 없습니다.")
        print(f"소유자: id={owner.id} {owner.email}")

        created = updated = 0
        new_posts: list[Post] = []  # 알림은 **새로 만든 글에만** 보낸다(아래)
        for item in posts:
            # 앱과 같은 검증을 태워서 API로 올린 것과 동일한 결과가 되게 한다
            # (제목·본문 길이, 태그 정리/개수 제한).
            body = PostCreate(
                title=item["title"],
                content=item["content"],
                tags=item["tags"],
                visibility="public",
            )
            # 개발일지 날짜(KST 자정) → UTC. 연재 순서가 날짜로 드러나게 한다.
            written = datetime.fromisoformat(item["date"] + "T09:00:00+09:00").astimezone(
                timezone.utc
            )

            # 연재 묶음. PostCreate에 없는 필드라 여기서 직접 넣는다 — 빠뜨리면 글은
            # 보이지만 연재 네비(/posts/{id}/series)가 null이 된다(2026-07-20에 겪음).
            series = item.get("series", "블로그 만들기")

            existing = db.scalar(select(Post).where(Post.title == body.title))
            if existing:
                existing.content = body.content
                existing.tags = body.tags
                existing.visibility = body.visibility
                existing.owner_id = owner.id
                existing.created_at = written
                existing.series = series
                updated += 1
                print(f"  갱신  {item['date']}  {body.title}")
            else:
                fresh = Post(
                    title=body.title,
                    content=body.content,
                    tags=body.tags,
                    visibility=body.visibility,
                    owner_id=owner.id,
                    series=series,
                    created_at=written,
                    updated_at=written,
                )
                db.add(fresh)
                new_posts.append(fresh)
                created += 1
                print(f"  생성  {item['date']}  {body.title}")

        db.commit()

        # ── 알림 ──────────────────────────────────────────────────────────────
        # **새로 만든 글에만** 보낸다. 갱신에도 보내면 오타 하나 고칠 때마다 구독자
        # 편지함과 잠금화면이 옛 글로 울린다 — 실제로 2026-08-14에 오타 수정으로
        # 세 편을 재발행했는데, 그때 이 코드가 있었다면 세 통이 나갔을 것이다.
        #
        # 왜 이 코드가 여기 필요한가 (2026-08-14 신고: "글쓰기 알림이 안 간다"):
        # 이 스크립트는 `POST /api/posts`를 **거치지 않고 DB에 직접 쓴다.** 그래서
        # 라우터에 있는 알림 발송(인앱·메일·푸시)이 한 번도 안 돌았다. 개발일지가
        # 이 블로그의 거의 모든 글인데, 그 글들이 전부 알림 없이 올라가고 있었다.
        # 알림 기능은 만들어져 있었고 검사도 통과했다 — **호출되는 자리만 없었다.**
        #
        # 라우터(routers/posts.py)와 같은 조건을 쓴다: 공개·구독자공개 글만,
        # 승인된 구독자 중 notify를 켠 사람에게만.
        for post in new_posts:
            if post.visibility not in ("public", "subscribers"):
                continue
            uids = db.scalars(
                select(AuthorSubscription.subscriber_id).where(
                    AuthorSubscription.author_id == post.owner_id,
                    AuthorSubscription.approved.is_(True),
                    AuthorSubscription.notify.is_(True),
                )
            ).all()
            for uid in uids:
                db.add(Notification(user_id=uid, post_id=post.id))
            if uids:
                db.commit()
            # 메일·푸시는 각각 따로 감싼다 — 한쪽이 죽어도 다른 쪽은 나가야 한다
            # (라우터가 BackgroundTask 둘로 나눠 건 것과 같은 이유). 그리고 알림
            # 실패가 **발행 자체를 실패시키면 안 된다** — 글은 이미 커밋됐다.
            for label, fn in (("메일", notify_new_post), ("푸시", notify_new_post_push)):
                try:
                    fn(post.id, post.title, post.owner_id)
                except Exception as e:  # noqa: BLE001 - 알림 실패로 발행을 되돌리지 않는다
                    print(f"  ⚠️ {label} 알림 실패({post.title[:20]}): {type(e).__name__}: {e}")
            print(f"  알림  대상 {len(uids)}명  {post.title}")
        print(f"\n완료: 생성 {created}건, 갱신 {updated}건")
    finally:
        db.close()


if __name__ == "__main__":
    main()
