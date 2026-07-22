"""개발일지 마크다운을 블로그 글로 발행. EC2의 백엔드 컨테이너 안에서 실행한다.

컨테이너 안에서 도는 이유: RDS는 퍼블릭 접근이 아니라 EC2에서만 닿고, 컨테이너엔 이미
DB 자격증명(.env)과 앱 모델이 있다. 덕분에 계정 비밀번호 없이 발행할 수 있다.

created_at을 실제 작업일로 소급하는 것도 여기서 한다. API(POST /api/posts)는
created_at을 서버가 now()로 채워서 소급이 불가능하다.

멱등: 같은 제목의 글이 이미 있으면 내용을 갱신만 한다(재실행해도 중복 생성 없음).

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
from app.models.post import Post
from app.models.user import User
from app.schemas.post import PostCreate


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
                db.add(
                    Post(
                        title=body.title,
                        content=body.content,
                        tags=body.tags,
                        visibility=body.visibility,
                        owner_id=owner.id,
                        series=series,
                        created_at=written,
                        updated_at=written,
                    )
                )
                created += 1
                print(f"  생성  {item['date']}  {body.title}")

        db.commit()
        print(f"\n완료: 생성 {created}건, 갱신 {updated}건")
    finally:
        db.close()


if __name__ == "__main__":
    main()
