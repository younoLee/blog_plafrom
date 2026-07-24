# ECS Stage 6 — 증명 실측 증거 (2026-07-24)

> 개발일지 재료. ECS 마이그레이션을 실제로 라이브 배포·컷오버하고, 오케스트레이션 3대 특성을
> 실측으로 증명한 기록. 모든 수치는 그날 CLI 실측값. (인프라는 증명 후 tear down)

## 배포한 것 (라이브)
CloudFront → ALB → ECS Fargate(2태스크) → RDS Postgres 16.14. 순서:
1. ECR 이미지: 로컬 도커 빌드→push, 태그 `2e8d3d47…`(git SHA, IMMUTABLE)
2. RDS(db.t4g.micro, publicly_accessible=false, 관리형 비번). 스키마는 **일회성 ECS run-task**로
   `alembic upgrade head` — 27개 마이그레이션 + pg_trgm 확장 + GIN/created_at 인덱스.
3. 데모계정: run-task로 `create_user.py demo@example.com --demo`(id=1, writer).
4. ECS 서비스(desired 2, healthy) + ALB + CPU 타깃트래킹 오토스케일(2~4).
5. 컷오버: `api_backend=ecs` → CloudFront /api/* 오리진을 주차(S3)→ALB(:80)로.
6. 스모크: `/api/status` → `{"database":"ok", ...}` (Fargate→RDS 연결 확인), `/api/posts` 200.

## 증명 3/3 (프로버 = 0.5초마다 /api/posts 상태코드 기록)

### ① 태스크 강제 종료 → ECS 자동 복구
- `aws ecs stop-task`로 실행 태스크 1개 kill(13:27경).
- 이벤트: 드레인 → 타깃 deregister → **대체 태스크 자동 시작** → register → steady state.
- 살아남은 태스크는 내내 유지, 복구 ~90초. running 2/2로 회복.
- **가용성: 프로버 ~400요청 중 비-200 12건 — 전부 429(앱 레이트리밋, 전환 순간), 5xx(다운) 0건.**
  → "태스크를 죽여도 사람 개입 없이 무중단 복구."

### ② 무중단 롤링 배포
- `aws ecs update-service --force-new-deployment`.
- PRIMARY(새) 태스크가 2개 healthy 될 때까지 ACTIVE(옛) 2개 유지 → 최대 4개 겹침(max 200%) →
  새 것 healthy 후 옛 것 드레인. (min 100% / max 200% + 배포 서킷브레이커)
- **가용성: 배포 구간(13:35:28~13:37:40) 프로버 229요청 전부 200, 비-200 0, 5xx 0건.**
  → "배포 내내 229/229 = 200. 새 태스크 healthy 확인 후에만 옛 것 드레인."

### ③ 오토스케일 (CPU 타깃 트래킹, 2~4)
- **부하 실측:** health 엔드포인트에 60워커×5분 = **16,807 요청(~56 req/s)을 보냈는데도 CPU 최고 ~10%.**
  → 0.25vCPU 태스크를 단일 랩탑 + CDN + 가벼운 엔드포인트로 60%까지 태우는 건 비현실적(정직한 관찰).
- 그래서 **메커니즘을 실증**: CPU 타깃을 60%→1%로 낮춰 같은 경로(지표>타깃 → CloudWatch 알람 →
  스케일링 정책 → 태스크 증설)를 발동. 이후 60% 복원 → scale-in까지 자동으로 왕복.
- **스케일링 활동(실측):**
  ```
  13:46:52  Successful  Setting desired count to 4.  (AlarmHigh ALARM → policy blog-backend-cpu60)
  13:50:37  Successful  Setting desired count to 3.  (AlarmLow  ALARM → scale-in)
  13:56:37  Successful  Setting desired count to 2.  (AlarmLow  ALARM → scale-in, baseline 복귀)
  ```
  desired 2→4(증설, running 2→3→4 healthy) → 60% 복원 후 4→3→2(축소). **왕복 완결.**
  → "지표가 타깃을 넘으면 자동 증설, 빠지면 자동 축소. scale-out은 빠르고 scale-in은 flapping 방지로 보수적."

## 그날 배운 것 (개발일지 후크)
- **alembic × configparser × RDS 비번:** RDS 자동생성 비번의 특수문자를 URL 인코딩하니 `%3E` 등이
  생겼고, `alembic/env.py`가 그 URL을 configparser로 넘겨 `%`를 보간문법으로 오해해 터졌다
  (`invalid interpolation syntax`). 서빙(SQLAlchemy 직접)은 멀쩡했다. → run-task 실행기가 alembic일
  때만 `%`→`%%` 이중화로 우회. 정식 수정은 `env.py`에서 `.replace("%","%%")`(미적용, 잠재버그로 남김).
- **RDS가 프라이빗이라 랩탑에서 직접 복원 불가** → 덤프 복원 대신 run-task로 스키마 생성 + 데모 시드
  (오케스트레이션 증명이 목적이라 실데이터 이관은 생략).
- **레이트리밋이 실제 클라 IP 기준으로 동작** — 앞서 고친 `trusted_proxy_hops=2`(CloudFront→ALB→task
  2홉) 덕에 엣지 IP가 아니라 진짜 클라 IP로 키가 잡혔다. 단일 IP 폭주가 자기 자신을 429로 제한.
- **"세우고→증명하고→정리"** — 상시 운영은 EC2 on/off로 idle $0, 오케스트레이션은 크레딧으로
  기간한정 증명 후 tear down. 실비용 ~$1 미만/한나절. 비용을 의식한 아키텍처 결정 자체가 재료.

## 콘솔 스크린샷 위치 (포트폴리오)
- ECS → Clusters/blog → Services/blog-backend → **Events**(복구·롤링·스케일 트리거), **Health and metrics**(CPU 그래프).
- 스케일링 활동은 위 CLI 텍스트로 보존(콘솔 뷰 부실).
