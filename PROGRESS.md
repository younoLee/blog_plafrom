# 블로그 플랫폼 진행 기록

스택: FastAPI + PostgreSQL + React (Vite + TypeScript)

## 기능 목록
- [x] 글 작성/열람 (+ 수정/삭제, 상세 라우팅, 요약, 이미지, 댓글)
- [x] 구독
- [x] 새 글 알림 (SES)
- [x] 계정/로그인 + 글 공개범위(전체/일부)
- [x] 서비스 상태 페이지 (/status + 업타임 기록)
- [x] 인프라 AWS: EC2(backend+Postgres 컨테이너)/S3+CloudFront/Terraform/GitHub Actions CI·CD
- [~] AI 글 구조 생성 — 코드 완료, `ANTHROPIC_API_KEY` 넣고 e2e만 남음(건당 소액 사용량 과금)

### 보류 — 기술 과제가 아니라 사업/비용 결정 (2026-07-18 확정, 근거는 맨 아래 '로드맵 정리')
- 🚫 실결제 전환 — 토스 실결제는 **사업자등록이 필수**. 개인 포트폴리오 범위 밖이라 안 함. 샌드박스 결제 연동(승인검증→Pro 해금)은 이미 완성품 = 목적 달성.
- ⏸️ 커스텀 도메인 — 연 ~$18(도메인+Route53). CloudFront 도메인이 이미 HTTPS로 정상 동작 → 지금 쓸 돈 아님. 갖고 싶어지면 그때 결정.

## 재개 방법 (다음 세션)
```
sg docker -c "docker compose up -d db mailpit"          # 컨테이너(이미 떠있을 수 있음)
backend/.venv/bin/uvicorn app.main:app --app-dir backend --port 8000
cd frontend && npm run dev                               # :5173
```
데모 계정: kim@test.com / secret123 (공개+비공개글 소유), lee@test.com / pw12345

---

## 2026-06-21

- [완료] 프로젝트 폴더 구조 설정
  - backend/: FastAPI 앱 골격 (main.py, core/, models/, schemas/, routers/, services/)
  - frontend/: React 빈 폴더 구조 (src/components, pages, api, types)
  - docker-compose.yml: PostgreSQL + 백엔드 로컬 실행 환경
  - .gitignore: .env, node_modules 등 제외

- [완료] 백엔드 FastAPI 서버 실제 실행 확인
  - 시스템 python3에 pip 없음 → `backend/.venv` 가상환경 생성(ensurepip로 pip 자동 포함)
  - `.venv/bin/pip install -r requirements.txt` 로 의존성 설치 (fastapi, uvicorn, sqlalchemy 등)
  - uvicorn 기동 → `/health` 200 `{"status":"ok"}`, `/docs` 200 확인
  - 메모: main.py는 DB를 import 안 함 → Postgres 없이도 서버는 뜸(create_engine은 lazy)

- [완료] React 프론트엔드 초기화 (Vite + react-ts)
  - 기존 빈 폴더(api/components/pages/types) 보존 위해 임시폴더에 scaffold 후 frontend/로 병합
  - package.json name: blog-platform-frontend 로 변경
  - `npm install` + `npm run build` 통과 (tsc 타입체크 + vite build → dist/ 생성)

- [완료] 프론트-백엔드 연결 검증
  - App.tsx에 /health 호출(useEffect 최초 1회) → "백엔드 연결 상태: ok" 표시하는 최소 코드
  - 양쪽 서버 동시 기동: 프론트 :5173 (200), 백엔드 :8000
  - CORS 검증: Origin: localhost:5173 요청에 access-control-allow-origin 헤더 정상 응답 → 브라우저 fetch 성공 보장

- [완료] Docker(WSL 통합) 손봄
  - Docker Desktop은 Windows에 이미 설치돼 있었고, Ubuntu 배포판 WSL 통합이 꺼져 있던 게 원인
  - Docker Desktop GUI → Resources → WSL Integration → Ubuntu 토글 ON 후 동작
  - 남은 권한 이슈: 현재 셸이 docker 그룹 반영 전에 시작됨 → `sg docker -c "..."`로 우회, 영구 적용은 `wsl --shutdown` 후 재시작
  - `docker ps` 정상(컨테이너 목록 비어있음)

### 글 작성/열람 기능 (완료)
- [완료] Postgres 컨테이너 기동 (`sg docker -c "docker compose up -d db"`)
  - postgres:16-alpine, blog DB 존재, pg_isready accepting 확인
  - 백엔드 SQLAlchemy로 실제 연결 성공(PostgreSQL 16.14) — config.py 기본 URL 그대로 동작
- [완료] Post 모델 정의(app/models/post.py) + 테이블 생성(create_all)
  - posts: id(PK,자동증가), title(varchar200), content(text), created_at/updated_at(timestamptz, now()/onupdate)
  - 테이블 생성은 지금 create_all 방식. 스키마 복잡해지기 전 Alembic 도입 예정
- [완료] 글 CRUD API (schemas/post.py + routers/posts.py, main.py에 라우터 연결)
  - POST/GET목록/GET단건/PUT/DELETE 5종 curl로 전부 검증, 404/204 동작 확인
  - PUT 시 updated_at만 갱신·created_at 유지 확인
- [완료] 프론트 글 목록·작성 화면
  - types/post.ts, api/posts.ts(fetchPosts/createPost), App.tsx(작성 폼 + 목록)
  - npm run build 통과, 프론트가 쓰는 POST/GET 경로 CORS 포함 검증
  - 작성→목록 자동 갱신, created_at 표시

- [완료] 프론트 글 수정/삭제 UI
  - api/posts.ts에 updatePost/deletePost 추가
  - App.tsx: editingId 상태로 작성/수정 모드 전환, 글마다 수정·삭제 버튼, 수정 시 폼에 채우고 "수정 저장"/"취소"
  - 점검: build/lint OK, 작성→수정→삭제 API 경로 204/404까지 검증, 서버 에러 0
- [완료] Alembic 도입 (DB 스키마 버전 관리)
  - alembic init → env.py에 settings.database_url 주입 + target_metadata=Base.metadata 연결
  - 기존 create_all 테이블 drop 후 autogenerate로 초기 마이그레이션(create posts) 생성 → upgrade head 적용
  - alembic_version 테이블이 현재 버전(13f4b1ff2dc5) 추적, 앱 CRUD 정상 회귀 확인
  - 앞으로 스키마 변경은 모델 수정 → `alembic revision --autogenerate -m "..."` → `alembic upgrade head` 순서
### 구독 기능 (완료)
- [완료] 백엔드: Subscriber 모델(email unique+index) → Alembic 마이그레이션(ad25d4c8b1b3) → schema(EmailStr) + 라우터(POST 등록/GET 목록)
  - 중복 이메일 409, 형식 오류 422, alembic check "no new ops"(모델=DB 일치) 확인
  - email-validator 패키지 추가(requirements.txt)
- [완료] 프론트: api/subscribers.ts + App.tsx 구독 폼(이메일 입력→상태별 안내 메시지)
  - build/lint OK, 등록/중복/형식/목록/CORS/회귀 전부 통과, 테스트 데이터 정리
### 새 글 알림 기능 (완료)
- [완료] Mailpit 컨테이너(docker-compose, SMTP 1025 / 웹UI 8025)로 로컬 메일 캐처 구성
- [완료] config.py SMTP 설정(smtp_host/port, mail_from) — 로컬 Mailpit 기본값, 나중에 SES로 교체
- [완료] services/email.py: smtplib 발송 + notify_new_post(구독자 전원에게, 자체 DB 세션)
- [완료] create_post에 BackgroundTasks로 알림 연결 — 응답 후 백그라운드 발송
  - 검증: 구독자 2명→글 작성→Mailpit 2통 수신(제목/수신자 정확), 서버 에러 0, 테스트데이터 정리
### 글 상세 페이지 + 라우팅 (완료)
- [완료] react-router-dom 7.18 도입
- [완료] 화면 분리: App.tsx=라우터 설정만, pages/HomePage(구독·작성·목록, 제목→상세 링크), pages/PostDetailPage(/posts/:id 글 전문)
- [완료] api/posts.ts에 getPost(id) 추가(404 처리)
  - build/lint OK, / 와 /posts/:id 라우팅 동작, getPost 200 확인
### 글 요약(발췌) (완료)
- [완료] HomePage 목록에 본문 앞 100자 자동 발췌 표시(100자+ 시 …), 요약/제목 클릭→상세
  - DB 변경 없음(자동 발췌 방식), build/lint OK

### 추가 요청받은 기능 (순서대로 진행 예정)
- [완료] ① 글 요약
- [완료] ③ 댓글 — comments 테이블(post_id FK, ondelete CASCADE) + 마이그레이션(627870b1c2e4) + /posts/{id}/comments API(목록/작성) + 상세페이지 댓글목록·작성폼
  - 작성자 이름 직접입력(로그인 전), CASCADE(글 삭제→댓글 삭제) 검증, 404/422 확인, build/lint OK
- [완료] ② 이미지 업로드 (마크다운 방식)
  - 백엔드: POST /upload(이미지만, uuid 파일명, backend/uploads/ 저장) + StaticFiles로 /uploads/<파일> 서빙, config.public_base_url(나중에 S3/CloudFront로 교체), python-multipart 추가
  - 프론트: api/uploads.ts, HomePage 이미지 첨부 input→업로드 후 본문에 ![](url) 삽입, PostDetailPage react-markdown으로 본문 렌더링(이미지 표시)
  - 검증: PNG 업로드 URL→GET 200, txt 거부 400, e2e(업로드→글 삽입→상세 이미지) OK, build/lint OK
  - DB 변경 없음(이미지 URL은 본문 텍스트에 마크다운으로 들어감). uploads/는 .gitignore
### ④ 계정+공개범위 (완료)
- [완료] 4a 인증 백엔드: User 모델+마이그레이션(86ed6449b339), bcrypt 해싱, JWT(PyJWT), /auth/register·login·me, deps(get_current_user/_optional)
- [완료] 4c 글 owner_id+visibility 마이그레이션(d6c9c2009ad6) + 권한: 작성=로그인필수, 목록/상세=비공개는 본인만(404), 수정/삭제=소유자만(403)
- [완료] 4b 인증 프론트: api/auth.ts(토큰 localStorage), auth/auth-context.ts + AuthProvider, App을 AuthProvider로 감쌈, posts api에 authHeaders 첨부
- [완료] 4d 공개범위 UI: HomePage 로그인바(로그인/회원가입/로그아웃), 작성폼 로그인 게이팅, 공개범위 라디오, 비공개 🔒 뱃지, 본인 글만 수정/삭제 버튼; 상세페이지 비공개 뱃지
  - build/lint OK, alembic clean. 데모계정 kim@test.com/secret123(공개+비공개글 소유), lee@test.com/pw12345
- 추가 요청 4개 기능(①요약 ③댓글 ②이미지 ④계정+공개범위) 전부 완료

### 디자인/스타일링 (진행중)
- [완료] Tailwind CSS v4 도입(@tailwindcss/vite 플러그인, index.css에 @import "tailwindcss") + @tailwindcss/typography
  - 옛 Vite 데모 CSS(index.css/App.css) 제거, App 래퍼 max-w-2xl 컨테이너
  - HomePage 재디자인(헤더, 카드형 목록, 버튼/입력 스타일 통일, 🔒뱃지, line-clamp 요약)
  - PostDetailPage 재디자인(본문 prose 타이포그래피, 댓글 카드)
  - build/lint OK, 생성 CSS에 유틸/hover/prose 룰 확인
- [완료] 로그인/회원가입/글쓰기를 별도 페이지로 분리
  - pages/LoginPage(/login), RegisterPage(/register), WritePostPage(/new 작성 + /posts/:id/edit 수정)
  - HomePage: 인라인 폼 제거 → 헤더에 네비 버튼(로그아웃 시 로그인/회원가입, 로그인 시 글쓰기/로그아웃), 수정은 edit 페이지로 이동
  - 작업 후 navigate('/')로 홈 복귀, 글쓰기 페이지는 비로그인 시 /login으로 리다이렉트
  - build/lint OK, 라우트 6개(/, /login, /register, /new, /posts/:id, /posts/:id/edit) 서빙 확인
- [완료] 디자인 고급화: 공통 Layout(sticky 헤더+푸터, Outlet 중첩 라우트), Pretendard 폰트, indigo 테마, ui.ts 공통 토큰(btn/input/card), 흰 카드+그림자+hover 떠오름, 홈 히어로, 상세/로그인/가입/글쓰기 카드화
  - build/lint OK, 라우트 6개 200, Pretendard 로드 확인
- [완료] 다크모드: index.css @custom-variant dark(.dark 클래스 제어), theme.ts(getInitial/apply/useTheme, localStorage+OS설정), main.tsx 렌더 전 적용(깜빡임 방지), 헤더 🌙/☀️ 토글, ui.ts·Layout·전 페이지 dark: 변형(배경/텍스트/카드/입력/prose-invert)
  - build/lint OK, .dark 규칙 생성 확인
- [ ] 남은 디자인(선택): 모바일 반응형 추가 점검

### 글쓴이 구독 → 일부공개 글 열람 (완료)
- [완료] author_subscriptions 테이블(subscriber_id→author_id, unique, CASCADE) + 마이그레이션(f02bc00a3b57)
- [완료] /subscriptions API: GET(내 구독 author id목록)/POST(구독, 자기자신 400)/DELETE(해제)
- [완료] posts 권한 확장: 일부공개(private) = 작성자 본인 OR 그 작성자를 구독한 사람 (can_view + list 필터 + subscribed_author_ids)
- [완료] 프론트: api/subscriptions.ts, 상세페이지 "글쓴이 구독/구독중" 토글 버튼(로그인+남의 글일 때)
- 검증: 구독 전 404 → 구독 후 200 → 해제 후 404, 자기구독 400, 비로그인 404, build/lint OK
- 다음 할 일(미정): AI 글 구조 생성, 서비스 상태 페이지. (나중에 AWS: SES로 메일 교체)

## 2026-06-22

목표: 통합 랜딩(포털) + 상태정보 페이지. 구조는 "포털 분리형"으로 결정 — / = 통합 랜딩, /blog = 블로그, /status = 상태.

### 1단계 — 상태정보 페이지 (/status) [완료]
- [완료] 백엔드 /status 확장(main.py): 기존 backend+database에 **mail(SMTP 소켓 연결, Mailpit 1025)** + **stats(글 수/구독자 수, count 쿼리)** 추가
  - 점검 원칙: 실제로 안 도는 건 가짜로 안 넣음(외부/AWS는 나중에 진짜 붙을 때)
- [완료] 프론트: api/status.ts(fetchStatus + StatusInfo 타입), pages/StatusPage.tsx(서비스 3개 초록●/빨강● + 글/구독자 통계 + 새로고침 버튼 + 마지막 점검 시각), App.tsx에 /status 라우트
  - lint 주의: effect 안 동기 setState 금지 룰 → effect는 .then 패턴, 동기 setState는 새로고침 버튼(load) 쪽만
- 검증: build/lint OK. e2e — db+mailpit 띄우고 백엔드 기동 후 curl /status → `{backend:ok, database:ok, mail:ok, stats:{posts:4,subscribers:1}}` 확인

### 2단계 — 통합 랜딩 + 블로그 /blog 이동 [완료]
- [완료] pages/PortalPage.tsx: 카드 2개(📝 블로그→/blog, 📊 상태정보→/status)
- [완료] App.tsx 라우트 재배치: / = Portal, /blog = HomePage, /blog/new, /blog/posts/:id, /blog/posts/:id/edit, /status, /login, /register
- [완료] 링크/navigate 경로 수정:
  - HomePage 글/수정 링크 → /blog/posts/..., Layout 글쓰기 → /blog/new, PostDetail "목록으로" → /blog
  - WritePost 저장/취소 → /blog, Login·Register 성공 후 → /blog
  - "← 홈으로"(Login/Register/Write 좌상단) = to="/" 그대로 두니 자동으로 포털 가리킴
- 검증: 옛 경로 grep 0개, build/lint OK, dev 서버 부팅 에러 0, 라우트 5개(/, /blog, /status, /blog/posts/1, /login) 전부 200
- 결과: 통합사이트 완성 — 루트 진입 → 블로그/상태정보 갈라짐

### 3단계 — 업타임(uptime) 기록·표시 [완료]
- 업타임 % 정의: "돌고 있을 때 건강했나" = 정상 점검 / 전체 기록된 점검. 서버 꺼진 날 = 데이터 없음(회색)
  - 정직한 한계: 자기 자신 다운은 자기가 기록 못 함 → 진짜 다운 감지는 나중 AWS 외부 모니터(Lambda+크론)
- [완료] 백엔드:
  - 모델 status_checks(checked_at index, backend_ok/database_ok/mail_ok) + 마이그레이션(62118f8854d4)
  - app/services/status.py: run_checks(실시간 점검+통계) / record_check(1줄 저장) / start_recorder(60초마다 도는 데몬 스레드) / get_history(일별 집계)
  - main.py: lifespan에서 start_recorder() 시작, /status는 run_checks 사용, GET /status/history?days=N(1~90) 추가
  - "정상" 기준 = backend_ok AND database_ok AND mail_ok
- [완료] 프론트: api/status.ts fetchHistory + StatusPage 업타임 섹션(전체 % + 최근 30일 날짜별 막대 초록/노랑/빨강/회색 + 툴팁 + 범례)
- 검증: 마이그레이션 alembic check 통과, /status·/status/history 200, 기록 1→3줄 누적 확인, build/lint OK, 프론트 /status 200
- 메모: 기록은 서버 떠있는 동안만 쌓임 → 과거 날짜는 당분간 회색. status_checks 보존정책(오래된 행 정리)은 나중 고려
- [완료] 막대 서비스별 분리: get_history가 backend/database/mail 각각 일별 집계 반환({services:[{name,label,overall_uptime,days}], total_checks}), StatusPage는 UptimeRow로 3줄(라벨+% +막대). 검증: /status/history 서비스 3개 응답, build/lint OK
- 환경 메모: 백엔드 죽일 때 `pkill -f "uvicorn..."`는 명령줄 자기자신까지 매치돼 셸 자살(exit 144) → `fuser -k 8000/tcp`로 포트 기준 종료할 것

### 6단계 — AI 글 초안 생성 (Claude API) [코드 완료 / 키 대기]
- 거친 메모 → 정돈된 글 구조 마크다운(제목·소제목·불릿·초안)
- 결정: 모델은 env로 교체 가능(config.ai_model 기본 `claude-opus-4-8`, .env에서 `claude-haiku-4-5`로 저비용 전환 가능). 비용 유료(Opus ~$0.03~0.05/건, Haiku ~$0.005~0.01/건). 키는 아직 없음
- [완료] 백엔드: `anthropic==0.111.0` 설치(requirements 핀), config에 anthropic_api_key/ai_model 추가
  - app/services/ai.py: SYSTEM_PROMPT(마크다운만 출력 강제) + generate_draft(memo), 키 없으면 AIKeyMissingError
  - schemas/ai.py(memo max 5000=비용상한), routers/ai.py: POST /ai/draft, **로그인 필수(get_current_user)로 비용 보호**, 키없음→503·실패→502
  - main.py에 ai 라우터 연결. 공식 anthropic SDK, messages.create(max_tokens 4000, system+user)
- [완료] 프론트: api/ai.ts(generateDraft), WritePostPage에 "🤖 AI 초안" 박스(메모 textarea→생성→첫 `# 제목`은 제목칸, 나머지는 본문)
- 검증: 백엔드 부팅 OK, /ai/draft 비로그인 401·로그인+키없음 503(친절 메시지) 확인, build/lint OK
- 보안/비용: 키는 .env에만(.env·*.env gitignore 확인), 코드/커밋 금지. 실제 생성은 키 넣어야 동작
- **다음 세션 할 일**: 프로젝트 루트(`/home/es0764/blog-platform/.env`)에 `ANTHROPIC_API_KEY=sk-...` 넣고 백엔드 재기동 → 실제 초안 생성 e2e 테스트

### Docker 전체 컨테이너화 [완료] (2026-06-22)
목적: 수동 실행(venv/npm) 탈출 → `docker compose up` 한 줄로 전체 스택. AWS 배포 발판.
- 핵심 개념: 컨테이너 안 `localhost`는 자기 자신 → DB/메일은 **서비스 이름**(`db`, `mailpit`)으로 접속
- [완료] 1단계 백엔드: backend/.dockerignore(.venv·uploads·.env 제외), Dockerfile에 `mkdir uploads`, compose backend를 env_file→`environment`(DATABASE_URL=@db, SMTP_HOST=mailpit)로 교체, db `healthcheck`(pg_isready)+`depends_on: service_healthy`(기동 경합 방지), command에 `alembic upgrade head &&` (마이그레이션 자동)
- [완료] 2단계 프론트: 멀티스테이지 Dockerfile(node 빌드→nginx 서빙), nginx.conf SPA 폴백(try_files /index.html), .dockerignore(node_modules·dist), compose frontend 포트 `5173:80`(CORS origin 유지)
- 검증: `docker compose up -d --build` → 4컨테이너(db healthy/mailpit/backend/frontend) Up, 프론트 라우트 4개 200(SPA 폴백 OK), 백엔드 /status ok(데이터 posts:4 유지), CORS allow-origin 확인
- 메모: 프론트는 프로덕션 정적(핫리로드 X) → 수정 시 `docker compose up -d --build frontend`. 백엔드는 볼륨마운트+--reload라 코드수정 즉시 반영. 컨테이너 종료는 `docker compose down`(볼륨 유지) / 데이터까지 = `down -v`
- 다음(인프라): AWS 수동 배포(프론트 S3+CloudFront / 백엔드 컨테이너+RDS / 도메인·HTTPS) → Terraform → CI/CD

### AWS 배포 ① 프론트 S3 + CloudFront [완료] (2026-06-24)
계정: 신규(프리티어 12개월 이내) → 사실상 $0. 리전 서울(ap-northeast-2).
- [완료] vite.config.ts `build.assetsDir: ''` → dist 평평하게 출력(폴더 없이 파일만 → S3 업로드 간편). index.html이 /index-*.js, /index-*.css를 root에서 참조.
- [완료] S3 버킷 `blogplafromops`(비공개, 퍼블릭 액세스 차단 유지)에 dist 파일 업로드(평평, 파일 5개).
- [완료] CloudFront 배포(새 콘솔 마법사): WAF 끔(무료), 도메인 skip(기본 d*.cloudfront.net 사용), 원본=S3 버킷, "Allow private S3 bucket access (OAC) - Recommended" 선택 → 버킷 정책 자동 처리(수동 복붙 불필요).
- [완료] 기본 루트 객체 = index.html(설정에서 별도 입력 필요했음 — 마법사가 안 물어봄).
- [완료] 오류 페이지: 403 → /index.html → 200 (SPA 라우팅 폴백).
- 검증: CloudFront 도메인 접속 → 포털 화면 정상. (API는 백엔드 미배포라 아직 안 뜸 = 정상)
- 메모: WSL→S3 업로드는 콘솔 드래그(aws CLI 미설치). dist를 C:\Users\erert\Documents\blog-dist에 복사해서 드래그. 폴더 업로드가 잘 안 돼서 assetsDir 평평하게 바꿔 해결.
- 다음: 백엔드 EC2+RDS 배포 → 프론트 API 주소(현재 localhost:8000 하드코딩)를 백엔드 공개주소로 교체(빌드 시 env로) → 재배포. (aws CLI 설치 시 업로드/배포 훨씬 쉬워짐)

### AWS 배포 ② 백엔드 EC2 + RDS [진행 중] (2026-06-24)
계정: 181568979775, IAM 사용자 `IAM_cli`. 리전 서울. AWS CLI 설치됨(`~/.local/bin/aws`, PATH는 ~/.bashrc 등록).

**RDS (창고) — 생성됨/백업 중:**
- 식별자 `blog-db`, PostgreSQL, db.t3.micro, 단일 AZ, 20GB gp2, 스토리지 자동조정 끔
- 마스터 사용자 `postgres`, 비번=사용자만 앎(영문+숫자, 특수문자 없음) — .env DATABASE_URL에 들어감
- 퍼블릭 액세스 = 아니요(비공개), 보안그룹 `blog-db-sg`(default VPC), 자체관리 암호인증
- ⚠️⚠️ **초기 데이터베이스 이름 `blog`를 안 넣고 생성함** → `blog` DB 없음

**🔴 꼭 할 일 (까먹지 말 것):**
1. **EC2에서 RDS 접속 → `CREATE DATABASE blog;`** (초기 DB 이름 빠뜨려서. 1줄. EC2 뜨면 제일 먼저)
2. **RDS 보안그룹 `blog-db-sg`에 인바운드 규칙 추가**: 소스=EC2 보안그룹 `blog-ec2-sg`, 포트 5432 (창고 문을 주방한테만 열기)
3. **프론트 API 주소 교체**: 현재 모든 api/*.ts가 `const BASE='http://localhost:8000'` 하드코딩 → EC2 공개주소로 바꿔 재빌드 → S3 재업로드 → CloudFront 무효화(invalidation)
4. **백엔드 CORS**: main.py `allow_origins=["http://localhost:5173"]` → CloudFront 도메인 추가
5. **prod용 compose**: db·mailpit 컨테이너 빼고 backend만, DATABASE_URL=RDS엔드포인트, SMTP는 비활성/더미 (메일 알림은 나중에 SES)

**EC2 (주방) — 만드는 중 목표 설정:**
- 이름 `blog-backend`, AMI Amazon Linux 2023, t2.micro(프리티어), 스토리지 8GB
- 키페어 `blog-key.pem`(사용자 보관, SSH 접속용), 자동할당 퍼블릭 IP
- 보안그룹 `blog-ec2-sg`: SSH 22(내 IP) + TCP 8000(0.0.0.0/0, API)
- 만든 뒤: SSH 접속 → Docker 설치 → 위 "꼭 할 일" 1~5 처리 → 백엔드 컨테이너 실행

**비용 메모:** 신규 계정이라 12개월 프리티어 무료. 안 쓸 땐 EC2·RDS **중지(stop)**하면 과금 거의 0. 나중 Terraform 가면 destroy/apply로 내렸다 올리기. 콘솔 예상요금 숫자는 정가표시(프리티어 할인 미반영) — 실제 $0.

**[백엔드 LIVE 달성] (2026-06-24):**
- EC2: `i-06da19f44d1f38eff`, 퍼블릭 IP **15.164.102.25**, Amazon Linux 2023, Docker 25 + compose v5 + buildx v0.35 + nano 설치됨
- EC2 SG `sg-09ab4afd4472bb186`(launch-wizard-1): 22(내 IP), 8000(0.0.0.0/0). RDS SG `sg-04befe624e377b573`: 5432(EC2 SG에서만)
- RDS 엔드포인트 `blog-db.czk2i6usy011.ap-northeast-2.rds.amazonaws.com:5432`, **prod는 기본 `postgres` DB 사용**(별도 blog DB 안 만듦 — alembic이 테이블 생성). 마이그레이션 7개 전부 적용됨
- EC2 `~/blog/`: 백엔드 코드 + `docker-compose.prod.yml`(backend만, env_file, restart) + `.env`(DATABASE_URL→RDS postgres, 비번은 사용자가 nano로 입력, 나는 안 봄). SSH: `ssh -i ~/.ssh/blog-key.pem ec2-user@15.164.102.25`
- 검증: 인터넷에서 `http://15.164.102.25:8000/health`·`/status` → ok, database:ok(RDS연결). mail:down(prod 메일서버 없음, 나중 SES)
- 재배포(코드 수정 시): 로컬 backend tar→scp→EC2 `~/blog`, `sudo docker compose -f docker-compose.prod.yml up -d --build`

**🔴 다음 할 일 (프론트 연결 — 여기 HTTPS 함정 있음):**
1. ⚠️ **혼합 콘텐츠 문제**: 프론트(CloudFront)는 HTTPS인데 백엔드는 HTTP(`http://15.164.102.25:8000`) → 브라우저가 HTTPS페이지에서 HTTP API 호출을 **차단**함. 해결 필요:
   - (추천) CloudFront에 **두 번째 오리진(EC2)** 추가 + 경로 패턴(예 `/api/*`)을 EC2로 → 전부 같은 HTTPS 도메인 = CORS·혼합콘텐츠 동시 해결. 단 백엔드 라우트에 `/api` prefix 필요(또는 CloudFront에서 경로 재작성)
   - (대안) 도메인 사서 ACM 인증서 + 백엔드 앞단 HTTPS
2. 프론트 api/*.ts의 `BASE='http://localhost:8000'` → 백엔드 주소로 교체 후 재빌드 → S3 재업로드(`aws s3 sync`) → CloudFront 무효화(invalidation)
3. 백엔드 CORS `allow_origins`에 CloudFront 도메인 추가 (CloudFront 경유 same-origin이면 불필요)
- 로컬 docker compose(db+mailpit+backend+frontend)는 그대로 개발용으로 유지

### 🎉 AWS 풀스택 배포 완성 [완료] (2026-06-24)
**라이브 URL: https://d2j66m9udyg9yq.cloudfront.net (HTTPS, 전체 동작)**
```
브라우저 ──HTTPS──► CloudFront (d2j66m9udyg9yq.cloudfront.net, 배포ID E1438IL9CSVBS4)
   ├─ 기본동작(/, /blog, /status…)  → S3 (blogplafromops, OAC)          [정적 화면]
   ├─ /api/*   → EC2 오리진(ec2-backend, http-only :8000)               [백엔드 API]
   └─ /uploads/* → EC2 오리진                                            [이미지]
                          EC2(15.164.102.25) Docker 백엔드 → RDS(blog-db, postgres DB)
```
- **혼합콘텐츠+CORS 해결법**: 백엔드 라우트를 전부 `/api` 밑으로(main.py: include_router prefix='/api', /api/health·/api/status), CloudFront에 EC2 2번째 오리진 + behavior(/api/*=CachingDisabled+AllViewerExceptHostHeader, /uploads/*=CachingOptimized) 추가 → 전부 같은 HTTPS 도메인 = CORS 불필요, 혼합콘텐츠 없음
- 프론트: api/*.ts의 BASE를 `import.meta.env.VITE_API_BASE ?? 'http://localhost:8000/api'`로 통일. prod 빌드는 `VITE_API_BASE=https://d2j66m9udyg9yq.cloudfront.net/api npm run build`
- 재배포 흐름: 프론트 = 위 빌드 → `aws s3 sync dist/ s3://blogplafromops --delete` → `aws cloudfront create-invalidation --distribution-id E1438IL9CSVBS4 --paths "/*"`. 백엔드 = tar→scp→EC2 `~/blog`→`sudo docker compose -f docker-compose.prod.yml up -d --build`
- CloudFront 설정은 CLI로(get-distribution-config→python 수정→update-distribution --if-match ETag). 관리형 정책ID: CachingDisabled 4135ea2d.., CachingOptimized 658327ea.., AllViewerExceptHostHeader b689b0a8-53d0-40ab-baf2-68738e2966ac
- 검증: CloudFront 경유 /, /blog 200, /api/status database:ok, /api/posts []. (504는 백엔드 재시작 순간 일시적 캐시였음)

**남은 폴리시/주의:**
- ⚠️ EC2 퍼블릭 IP/DNS는 인스턴스 stop/start 시 바뀜 → CloudFront 오리진 깨짐. 안정화하려면 EIP(인스턴스에 붙이면 무료) 할당 후 오리진 도메인 교체
- mail:down (prod 메일서버 없음) → 나중 SES. /status에서 메일만 빨강
- 비용: EC2·RDS 안 쓸 땐 stop. 다음 단계 Terraform 가면 destroy/apply로 관리
- **다음 로드맵: Terraform(지금까지 한 인프라를 코드화) → GitHub Actions CI/CD(push→자동배포)**

### 🐛 디버깅: 이미지 업로드 실패(WAF) [해결] (2026-06-24)
- 증상: CloudFront 경유로 큰 이미지(>8KB) 업로드 시 "Unexpected token '<' ... not valid JSON". 작은 건 됨.
- 진단: EC2 직접은 200인데 CloudFront는 HTML(index.html). 헤더 `server: AmazonS3` + `x-cache: Error from cloudfront` → 403→/index.html 폴백. 크기로 좁힘(60B OK, 13KB 막힘) → WAF 의심.
- 원인: **CloudFront 생성 때 고른 "무료" 보안 = WAF(`CreatedByCloudFront-920ca6f5`) 활성화**. (내가 "무료=보안 끄기"로 잘못 안내했었음 — 실제론 무료 등급 WAF 켜기) CommonRuleSet의 **SizeRestrictions_BODY**(본문 8KB 초과 차단)에 이미지가 걸림.
- 해결: 플랜 구독 중이라 `update-distribution`으로 WebACL 분리 불가(`WebACLId=""` 거부). 대신 `aws wafv2 update-web-acl`로 CommonRuleSet에 **RuleActionOverride**(SizeRestrictions_BODY, CrossSiteScripting_BODY → **Count**) 적용. WAF 유지하며 큰 업로드만 허용.
- 검증: CloudFront 경유 13KB·1MB 업로드 200, 올린 이미지 GET 200(image/png). 
- 메모: 콘솔에서 끄려면 배포 보안탭 "Manage protections"인데 새 UI에서 못 찾음. 나중 Terraform 땐 WAF를 안 켜거나 업로드 경로 예외로 코드화.

## 2026-06-25

### 4단계 Terraform ① S3 버킷 import [완료]
- 목표: 손으로 만든 라이브 인프라를 Terraform 코드로 옮기기(버전관리·재현). 방식 = **import**(라이브 URL·글 데이터 유지), 한 번에 다 하지 않고 **가장 단순한 S3 버킷 하나**로 워크플로우 체득부터.
- Terraform 설치: 바이너리 **v1.15.7** → `~/.local/bin`(aws CLI와 같은 자리, sudo 불필요). zip은 curl로 받고 `unzip`이 없어서 외부 WSL 터미널에서 `sudo apt install -y unzip`으로 해결(`!` 세션은 sudo 비번 입력 불가). python `zipfile` 우회법도 가능.
- `terraform/` 폴더 신설:
  - `provider.tf`: aws provider `~> 5.0`, 리전 `ap-northeast-2`, 자격증명은 기존 aws configure(IAM_cli) 자동 사용
  - `s3.tf`: `aws_s3_bucket.frontend` = 실제 버킷 `blogplafromops`(본체만 선언)
- 워크플로우: `terraform init`(aws provider v5.100.0) → `terraform import aws_s3_bucket.frontend blogplafromops`(Import successful) → `terraform plan` = **No changes** → `fmt`/`validate` 통과
- 배운 것:
  - **import는 리소스 생성이 아님** — 이미 있는 걸 state에 등록만(비용 $0, 라이브 안 건드림, init/import/plan/validate 전부 읽기성)
  - `resource "타입" "별명"` 구조에서 별명(frontend)은 코드 내부 참조용, AWS엔 안 보임
  - S3 부속설정(퍼블릭차단/버킷정책 등)은 **별도 리소스** → 코드에 안 적으면 plan 차이로도 안 잡힘(관리 대상 아님)
  - **No changes = 코드가 실제와 1:1 일치**, import 성공의 증거
- state는 로컬(`terraform.tfstate`, gitignore됨). `.gitignore`에 Terraform 제외 이미 있어 시크릿 커밋 위험 없음

### 4단계 Terraform ② S3 부속 리소스 import [완료]
- S3는 버킷 본체와 부속 설정이 **각각 별도 리소스** → 따로 선언 + 따로 import
- `aws_s3_bucket_public_access_block.frontend`: 4개 불린 전부 true(모든 퍼블릭 차단) → import → No changes (추측 적중)
- `aws_s3_bucket_policy.frontend`: OAC 정책. **추측 금지**, 실제 정책을 `aws s3api get-bucket-policy`로 먼저 보고 `jsonencode`로 옮김
  - 정책 요지: Principal=cloudfront 서비스, Action=s3:GetObject, Condition ArnLike로 우리 배포(E1438IL9CSVBS4)만 허용 → import → No changes
  - `Resource = "${aws_s3_bucket.frontend.arn}/*"`로 버킷 ARN 참조(DRY). 계정·배포 ID는 아직 하드코딩(해당 리소스 import 전)
- 배운 것: 정책 같은 JSON은 실제 값을 조회해서 옮겨야 함(추측하면 plan 차이). aws provider는 정책을 의미 단위로 비교해 키 순서 차이는 무시. 이 버킷은 OAC 구성이라 website hosting/versioning 없음 → 본체+차단+정책 3개로 완전
- **S3 버킷 100% 코드화 완료** (plan No changes, fmt/validate 통과)

### 4단계 Terraform ③ CloudFront import [완료]
- 전략: 설정이 방대해서 추측 대신 `aws cloudfront get-distribution-config --id E1438IL9CSVBS4`로 전체 설정을 먼저 받아 1:1 코드화. CloudFront 관련은 `cloudfront.tf`로 분리
- ① `aws_cloudfront_origin_access_control.s3`(OAC) 먼저 import — 세부는 `get-origin-access-control`로 조회(sigv4/always/s3). import → No changes
- ② `aws_cloudfront_distribution.main` 본체 import:
  - 오리진 2개(S3+OAC 참조 / EC2 custom http-only:8000), default behavior(S3, CachingOptimized), `/api/*`(EC2, CachingDisabled+AllViewerExceptHostHeader), `/uploads/*`(EC2, CachingOptimized), 403→index.html 200, WAF web_acl_id, 기본 인증서
  - **첫 plan 차이 = 태그 하나뿐**(`Name=bplgplafrom`이 실제엔 있는데 코드에 없어서 삭제하려 함) → 코드에 tags 추가 → No changes
  - 걱정했던 S3 OAC 오리진 숨은 차이 없었음(21속성+8블록 전부 일치)
- 배운 것: 큰 리소스는 실제 설정을 통째로 받아 코드화 → import 후 plan 차이는 보통 **태그처럼 사소한 것 1~2개** → 그것만 코드에 채우면 수렴. import는 차이를 plan으로 잡아 코드를 실제에 맞춰가는 작업
- **CloudFront 100% 코드화 완료** (plan No changes, fmt/validate 통과)

### 4단계 Terraform ④ EC2 + 보안그룹 import [완료] (`ec2.tf`)
- 보안그룹 실제 규칙은 `aws ec2 describe-security-groups`로 조회 후 코드화
- `aws_security_group.ec2`(sg-09ab4afd4472bb186, 실제 GroupName=launch-wizard-1): inbound 8000(전체)·22(내 IP 211.108.159.167/32), egress 전체. **ingress description은 실제로 빈값** → 코드에서도 빼야 No changes(미리 맞춰 한 방)
- **발견**: DB용 SG가 별도 생성이 아니라 **VPC default 보안그룹**(sg-04befe624e377b573, GroupName=default)이었음 → `aws_security_group` 아니라 **`aws_default_security_group.default`** 전용 리소스로 import(삭제 아닌 관리만). 규칙: 5432(EC2 SG에서만, `security_groups=[aws_security_group.ec2.id]`)·self 전체·egress 전체
- `aws_instance.backend`(i-06da19f44d1f38eff): describe-instances로 핵심 조회 → ami `ami-0436b3a61a7a7e22a`, t2.micro, key `blog-key.pem`, subnet, EC2 SG, metadata_options(IMDSv2 http_tokens=required), root_block_device(delete_on_termination). **태그 `Name="blog-backend "`(끝 공백 포함)** 그대로 맞춤 → 핵심만 적었는데 한 방에 No changes(나머지 computed는 terraform 자동)
- 생략: 키페어(공개키 원문 필요, 인스턴스가 key_name 문자열로 참조하면 충분), EIP(없음)
- 배운 것: SG ingress description 빈값/태그 공백 같은 미세한 것까지 실제와 일치해야 함. default SG는 전용 리소스. EC2는 computed가 많아 핵심만 적어도 import가 채워줌
- 다음: RDS(blog-db) import

### 4단계 Terraform ⑤ RDS import [완료] (`rds.tf`)
- `aws rds describe-db-instances`로 설정 조회: postgres 16.12, db.t3.micro, 20GB gp2, 암호화 on, multi_az off, 비공개, DBName null(=postgres 기본 DB 사용), default 서브넷그룹/SG, 백업 1일
- **비번 처리**: password를 코드/state에 안 넣음. AWS가 비번을 조회로 안 돌려주기도 하고 평문 유출 위험 → `lifecycle { ignore_changes = [password] }`로 terraform이 비번을 안 건드리게. 콘솔 설정값 유지
- import → 첫 plan 차이 4개:
  - (실제 기능) `performance_insights_enabled`, `copy_tags_to_snapshot` 둘 다 실제 true인데 코드 기본 false → 코드를 true로(안 그러면 apply 시 기능 꺼짐)
  - (terraform 메타) `skip_final_snapshot`, `apply_immediately` → state값에 맞춰 noise 제거
  - 4개 코드에 명시 → No changes
- 배운 것: plan 차이엔 두 종류 — **실제 라이브 상태**(맞춰야 기능 안 꺼짐)와 **terraform 동작 플래그**(state값에 맞추면 사라지는 noise). 구분해서 다뤄야. 비번 같은 시크릿은 ignore_changes로 분리

### 🎉 4단계 Terraform — 라이브 인프라 100% 코드화 완료 (2026-06-25)
- 손으로 만든 AWS 인프라 전체를 import 방식으로 Terraform 코드화 (라이브/데이터 무손상, 비용 $0)
- `terraform/` 파일: provider.tf, s3.tf, cloudfront.tf, ec2.tf, rds.tf
- 관리 리소스 9개: aws_s3_bucket(+public_access_block, +policy), aws_cloudfront_origin_access_control, aws_cloudfront_distribution, aws_security_group, aws_default_security_group, aws_instance, aws_db_instance
- **전체 `terraform plan` = No changes** (코드 = 라이브 완전 일치), fmt/validate 통과
- state는 로컬(`terraform.tfstate`, gitignore). 시크릿(RDS 비번)은 코드에 없음
- import 핵심 패턴 체득: 실제 설정 조회(describe/get) → 코드화 → import → plan 차이 수렴(보통 태그·메타 등 사소한 것). destroy/replace 뜨면 멈춤
- 남은 폴리시(선택): ① 하드코딩된 IDS(계정·배포·subnet·ami 등)를 변수/참조로 정리 ② state를 S3 backend로 ③ 키페어 등 미관리 리소스
- **다음 로드맵: 5단계 GitHub Actions CI/CD (push→자동배포)**. 그 전에 git init(2단계 GitHub 연동 미완) 필요

### 2단계 GitHub 연동 [완료] (2026-06-25)
- 첫 커밋(c55222b)은 로컬에만 있었음 → GitHub 원격 저장소 만들어 push
- GitHub 웹에서 **빈 저장소** 생성(younoLee/blog_plafrom). README/.gitignore/license 전부 OFF — 이유: 로컬에 이미 커밋이 있어서 원격에 커밋이 생기면 역사 어긋나 push 충돌
- 연결: `git remote add origin https://github.com/younoLee/blog_plafrom.git` → `git branch -M main` → `git remote -v`로 확인(fetch/push 둘 다 origin)
- 인증: HTTPS는 비번 불가(2021 막힘) → **Fine-grained PAT**(저장소 1개+Contents read/write만, 최소권한) 발급. push는 토큰 프롬프트 때문에 `!`세션 말고 **외부 WSL 터미널**에서 실행(Username=younoLee, Password=토큰)
- 검증: `git ls-remote origin` = 로컬 HEAD와 원격 main 둘 다 c55222b로 일치 → push 성공
- 배운 것: commit은 로컬 스냅샷일 뿐 인터넷에 안 올라감 / remote=원격 주소 이름표(origin) / push=로컬커밋을 원격으로 밀어올림 / PAT 최소권한(IAM 최소권한 원칙과 동일)
- **다음 로드맵: 5단계 GitHub Actions CI/CD (push→자동배포)** — 이제 코드가 GitHub에 있으니 전제조건 충족

### 5단계 GitHub Actions CI/CD [완료] (2026-06-25)
- 목표: main에 push하면 프론트엔드가 자동 빌드→S3→CloudFront 무효화. 수동 배포 명령을 워크플로로 옮김. (백엔드 EC2 자동배포는 SSH라 복잡 → 별도/나중)
- ① 배포 전용 IAM 사용자 `github-actions-deploy`(콘솔접근X, 프로그램용) + 정책 `github-brench`(이름만 그럴뿐 내용 정확): S3 List/Get/Put/Delete on blogplafromops, cloudfront:CreateInvalidation on E1438IL9CSVBS4. 최소권한 — 루트/IAM_cli 키 안 씀. 액세스키 AKIASURS2YM7WKLL4SV3
- ② GitHub repo Secrets(Repository secrets)에 AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY 등록. 워크플로에서 ${{ secrets.* }}로 꺼냄, 로그엔 *** 마스킹
- ③ `.github/workflows/deploy.yml`: on push(main, paths=frontend/**·워크플로파일) + workflow_dispatch(수동버튼). 스텝7: checkout→setup-node(20,npm cache)→npm ci→build(VITE_API_BASE=라이브/api)→configure-aws-credentials@v4→s3 sync dist/ --delete→cloudfront create-invalidation /*
- 검증(교차): Actions 초록 + AWS 실측 — S3 index.html 등 방금 시각 갱신, CloudFront 무효화 I8ZLDNWIKQALWOMW02DPQTPH7R Completed
- 막혔던 것/배운 것:
  - 워크플로 파일 push는 PAT에 **workflow 권한** 필요(없으면 `refusing to allow a PAT to create/update workflow without workflow scope`) → fine-grained 토큰에 Workflows: Read&write 추가(토큰 재발급 불필요, 값 유지)
  - configure-aws-credentials `Could not load credentials from any providers` = Secret 이름 불일치로 빈 값 들어옴 → 이름 정확히 일치해야(대문자·언더스코어). Secret 삭제 후 재생성
  - **Re-run jobs를 실제로 눌러야** 새 Secret 반영됨. 옛 실행 로그를 새 결과로 착각하지 말 것
  - Node20 deprecation은 경고일 뿐(빌드는 정상). 나중에 setup-node 버전 올리면 사라짐
- 남은 선택: 백엔드 EC2 자동배포(SSH), Node 버전업, S3 backend state
- **다음 로드맵: 6단계 AI 글쓰기 도구(음성메모→글구조 / 커스텀 슬래시커맨드). 또는 AI 글초안 키 충전 e2e.**

### 프론트엔드 애플풍 리디자인 + CI/CD 첫 실전 배포 (2026-06-25)
- 계기: 외부 평가 "기능 형태는 있는데 프론트가 처참" → 구조/기능 유지한 채 **외관만** 애플 홈페이지풍으로 폴리시(타겟 폴리시 방식)
- 디자인 토큰(`ui.ts`): indigo 각진버튼 → **애플 블루(#0071e3) 알약버튼**, 둥근 카드, 은은한 그림자. `gradientText`(블루→퍼플→핑크, 흐름), `glow`(배경 번짐) 토큰 추가
- 전역(`index.css`): SF 우선 폰트스택 + 안티앨리어싱 + 자간조임, `::selection` 애플블루, `@keyframes gradient-pan`(흐르는 그라데이션)
- **이모지 전부 SVG로** — `components/icons.tsx`에 선아이콘 12종(currentColor·다크모드 자동). 📝🌙☀️✏️🔒📊🤖✨🖼🔄✔←→ 전수 교체. 헤더 로고는 favicon 브랜드마크(보라 그라데이션 SVG)로 통일
- 스크롤 리빌(`components/Reveal.tsx`): IntersectionObserver로 화면 진입 시 아래→위 페이드업. 포털/홈 카드·상세 본문에 적용
- 페이지별: 포털(대형 그라데이션 헤드라인 "기록하는 개발자"+오로라 3겹 글로우), 홈(그라데이션 "이야기"+글카드 스태거 리빌+hover 테두리), 로그인/회원가입(그라데이션 제목+글로우), 상태(그라데이션 제목+통계숫자 컬러), 글쓰기(그라데이션 제목), 상세(prose 링크 애플블루)
- 검증: `npm run build`(tsc+vite) 매 단계 통과, 이모지 전수검사 0
- **CI/CD 첫 실전**: commit(359dc8f)+push → GitHub Actions 자동 빌드→S3→무효화 초록 → 교차검증(S3 06:16 UTC 갱신, 무효화 Completed, 라이브 200). 손으로 s3 sync 안 침 = 5단계가 실제로 작동
- 한계: 더 끌어올리려면 실제 콘텐츠(글 썸네일·실제 글 다수)가 필요. 디자인만으론 여기까지

### 계정 권한제(가입 승인제) — 1단계 백엔드 권한 잠금 [완료] (2026-06-25)
- 문제의식: "아무나 가입하면 같은 블로그에 글 쓰는 공용 블로그"가 돼버림 → 개인 블로그 의도와 어긋남
- 결정한 모델: **가입은 누구나 가능하지만 가입 직후 `pending`(승인 대기) → 관리자가 승인해야 `writer`(글쓰기 가능)**. 읽기는 누구나. 관리자=`admin`
- 백엔드:
  - `users.role` 컬럼 추가(pending/writer/admin, server_default 'pending') → 마이그레이션 `1336504cc438`
  - `core/deps.py`: `require_writer`(writer·admin만, 아니면 403) + `require_admin`(admin만) 추가
  - 글 작성/수정/삭제(`posts.py`), 이미지 업로드(`uploads.py`, 원래 인증 자체가 없었음), AI 초안(`ai.py`)을 전부 `require_writer`로 잠금
  - **첫 관리자 부트스트랩**: `.env`의 `ADMIN_EMAIL`과 일치하는 이메일로 가입/로그인하면 자동 admin(수동 SQL 불필요). 비밀 아님
  - `schemas/user.py` UserRead에 `role` 포함(프론트가 권한 알게)
- 환경: 로컬 백엔드는 docker 컨테이너로 실행 중 → `.env`는 venv용, **docker는 compose `environment:`에도 `ADMIN_EMAIL` 넣어야 함**(둘 다 등록함). env 변경은 `docker compose up -d backend`로 컨테이너 재생성해야 반영
- 검증: curl e2e — 가입→role=pending, pending 글쓰기 403, DB로 writer 승격 후 201, 정리 완료. 브라우저에서 admin(es2646526@gmail.com) 가입→자동 admin→글쓰기 성공 확인
- 막혔던 것: docker 프론트엔드가 3일 전(2026-06-22) 빌드라 `/api` 경로 통일(06-24)·오늘 리디자인 반영 안 됨 → 옛 프론트가 `localhost:8000/auth/...`(/api 없음) 호출해 가입 실패 → `docker compose up -d --build frontend`로 재빌드 해결
- 다음: 2단계 관리자 승인 API(`/admin/users` 목록 + 승인/해제) → 3단계 프론트 권한 UI → 4단계 비번 재설정(이메일 링크)

### 계정 권한제 — 2단계 관리자 승인 API + 관리자 글 관리 [완료] (2026-06-25)
- `routers/admin.py` 신설(라우터 전체 `dependencies=[require_admin]` → admin 외 전부 403):
  - `GET /api/admin/users` 가입자 전원 목록(id·email·role)
  - `POST /api/admin/users/{id}/approve` pending→writer, `POST .../revoke` writer→pending
  - 관리자 계정 대상은 변경 거부(400) 가드
- 관리자 글 관리(`posts.py`): admin은 ① 모든 글 조회(`can_view`에 admin 예외) ② 목록에 비공개 포함(`list_posts` admin은 `true()` 조건=전체) ③ 남의 글 수정·삭제 가능(owner 체크에 `or user.role=='admin'`). `sqlalchemy.true()` 사용
- 검증: curl e2e(임시 admin/writer/대상자 계정) — 목록조회 200, approve→writer, revoke→pending, 비관리자 admin API 403, admin이 남 비공개글 조회 200·목록포함·수정 200·삭제 204. 전부 통과, 임시계정 정리
- 다음: 3단계 프론트 권한 UI(`/admin` 페이지 + pending 글쓰기 숨김 + admin 메뉴) → 4단계 비번 재설정

### 계정 권한제 — 3단계 프론트 권한 UI [완료] (2026-06-25)
- `api/auth.ts`: `User`에 `role` 필드 + `canWrite()` 헬퍼(writer·admin). `Role` 타입(pending/writer/admin)
- `api/admin.ts`(새): listUsers/approveUser/revokeUser (authHeaders 첨부)
- `pages/AdminPage.tsx`(새): 가입자 목록 + role 한글 뱃지(승인대기/글쓰기가능/관리자) + pending엔 "승인", writer엔 "승인 취소" 버튼. admin 아니면 `<Navigate to=/blog>`. 초기 로드는 .then 패턴(effect 동기 setState 룰 회피)
- `App.tsx`: `/admin` 라우트. `Layout.tsx`: admin만 "관리자" 메뉴, `canWrite`만 글쓰기 버튼(pending 숨김). `WritePostPage.tsx`: pending이 /blog/new 직접 접근 시 /blog로
- **버그/수정**: 업로드에 require_writer 걸었더니 `api/uploads.ts`가 토큰 미첨부라 업로드 실패(401) → authHeaders 첨부 + 401/403 메시지 추가. (`api/ai.ts`는 이미 토큰 보내고 있었음)
- 검증: npm run build(tsc+vite) + lint 통과, docker 프론트 재빌드 후 브라우저 e2e — admin "관리자"메뉴→/admin 목록, kim 승인→writer, kim 로그인 시 글쓰기 버튼 생김, lee(pending) 글쓰기 버튼 없음, 이미지 업로드 정상
- 환경 메모: 프론트 코드 바꾸면 `docker compose up -d --build frontend` + 브라우저 Ctrl+Shift+R(캐시)
- 추가: admin 글관리 UI — HomePage 수정·삭제 버튼을 본인 글뿐 아니라 `user.role==='admin'`이면 노출(백엔드는 이미 허용)
- 다음: 4단계 비번 재설정(이메일 링크 방식, Mailpit 재활용)

### 계정 권한제 — 블랙리스트(계정 차단/밴) [완료] (2026-06-25)
- 요청: 가입자를 차단하는 블랙리스트. 댓글이 로그인 기반이 아니라(이름 직접입력) **계정 차단(밴)** 방식으로 결정
- 설계: `role`에 `banned` 값 추가(문자열 칸이라 **마이그레이션 불필요**). 차단 해제 시 `pending`으로(재승인 필요)
- 백엔드: `auth.py` 로그인에서 banned 403, `deps.py` get_current_user에서 banned 403(이미 받은 토큰도 무효화) + get_current_user_optional은 banned를 None(비로그인) 취급. `admin.py`에 `POST /admin/users/{id}/ban`·`/unban`(admin 대상 차단 거부 가드)
- 프론트: `Role`에 banned, `api/admin.ts` banUser/unbanUser, AdminPage에 '차단됨' 빨강 뱃지 + pending/writer엔 '차단' 버튼, banned엔 '차단 해제' 버튼(ACTIONS 맵으로 핸들러 일반화)
- 검증: curl e2e — 차단→role=banned, 차단계정 로그인 403, 차단 전 받은 토큰 글쓰기 403, 해제→pending, 해제 후 로그인 200, 임시계정 정리. build/lint 통과 + 브라우저 확인
- 다음 결정: 가입 폭탄(봇 대량가입) 방어 = **이메일 인증**으로 결정(미인증=목록에 안 뜸·로그인 불가). CAPTCHA는 풀이농장/ML로 뚫려 만능 아님 → 개인블로그엔 이메일인증+가벼운 레이트리밋이면 충분. 4단계 비번재설정과 메일·토큰 인프라 공유 예정

### 권한제 체크포인트 커밋 (2026-06-25) — `d80002a`
- 1~3단계 + 관리자 글관리 + 블랙리스트를 한 커밋으로 저장(되돌릴 지점). admin 이메일은 docker-compose에서 `${ADMIN_EMAIL}`로 빼고 gitignore된 `.env`에서 주입(깃 미포함). push는 외부 터미널에서 나중에

### 이메일 인증 + 레이트 리밋 (봇 가입 폭탄 방어) [완료] (2026-06-25)
- **토큰·메일 토대**: `security.py`에 create/decode_email_token(purpose 'verify'/'reset', 만료 — 인증·비번재설정 공용), config에 `frontend_base_url`(메일 링크용, 로컬 5173/프로드 CloudFront). `services/email.py`에 send_verification_email
- **DB**: `users.email_verified` Boolean 추가 → 마이그레이션 `5284e000bf4e`. **기존 계정은 upgrade에서 `UPDATE ... SET email_verified=true`로 백필**(잠기지 않게). 신규 가입은 false로 시작
- **백엔드 흐름**: register=미인증 생성+확인메일(백그라운드, admin 이메일은 자동 인증+admin), `POST /auth/verify?token=`, 로그인은 미인증 403, 관리자 목록은 `email_verified=true`만(미인증 봇 제외)
- **레이트 리밋(slowapi)**: `core/ratelimit.py` Limiter + client_ip(X-Forwarded-For 우선 = CloudFront 뒤 진짜 IP). register 5/hour, login 10/minute, 초과 429. main.py에 limiter·핸들러 등록. requirements에 `slowapi==0.1.9` → **docker backend 재빌드 필요**(이미지에 패키지 설치)
- **프론트**: AuthProvider.register 자동로그인 제거, RegisterPage "메일 확인" 안내 화면, `pages/VerifyPage.tsx`(/verify?token= → 인증, setState는 .then/.catch로 lint 회피), App에 /verify, api/auth.ts verifyEmail + login 403(상세메시지)·429 처리
- 검증: curl e2e — 가입 미인증·확인메일 발송(Mailpit +1)·미인증 로그인 403·토큰 verify→인증·인증 후 로그인 200·가짜토큰 400, 레이트리밋 6연타 6번째 429. 브라우저 전체 흐름 OK
- 함정: slowapi 추가 후 docker backend가 import에러로 다운 → `docker compose up -d --build backend`로 재설치. 레이트리밋은 메모리 저장이라 테스트로 한도 소진 시 `docker compose restart backend`로 초기화
- 프로드 주의: prod는 아직 메일서버(SES) 없음 → CloudFront에선 인증메일 안 감 = 가입 막힘. SES 붙일 때 같이 적용

### 관리자 계정 삭제 [완료] (2026-06-25)
- `DELETE /api/admin/users/{id}`(admin만, admin 자기삭제 400): 글 먼저 삭제(posts.owner_id는 cascade 없음)→댓글은 posts FK CASCADE로, user 삭제→author_subscriptions는 users FK CASCADE로 자동 정리
- 프론트: api/admin.ts deleteUser, AdminPage 빨간 '삭제' 버튼(admin 외 전원) + window.confirm(글·댓글 영구삭제 경고) → 목록에서 제거
- 검증: curl e2e — 글+댓글 있는 계정 삭제 시 user/post/comment 전부 0(cascade), admin 자기삭제 400. build/lint 통과 + 브라우저 확인
- 다음: 4단계 비번 재설정(이메일 링크 — security.py 토큰 'reset' purpose·메일 인프라 그대로 재활용)

### 계정 권한제 — 4단계 비밀번호 재설정 (이메일 링크) [완료] (2026-06-25)
- 이미 만든 토큰(reset purpose, 만료 1h)·메일 인프라 재활용
- 백엔드(`auth.py`): `POST /auth/forgot-password`(이메일→재설정 링크 메일, 백그라운드) — **가입 여부 노출 안 하려고 없는 이메일도 동일 202**, 차단계정엔 미발송, 레이트 리밋 5/hour. `POST /auth/reset-password`(reset 토큰+새 비번→hashed_password 교체). `services/email.py` send_reset_email, 스키마 ForgotPasswordRequest/ResetPasswordRequest
- 프론트: `pages/ForgotPasswordPage`(/forgot, 이메일→"메일 확인"), `pages/ResetPasswordPage`(/reset?token=, 새 비번→완료), LoginPage에 "비밀번호를 잊었어?" 링크, App에 /forgot·/reset
- 검증: curl e2e — forgot 202+메일발송, 없는이메일 202(노출X), reset 토큰→비번교체, 새비번 200·옛비번 401, 가짜토큰 400. build/lint 통과 + 브라우저 전체 흐름 OK
- 🎉 **계정 시스템 전체 완성**: 가입 승인제 · 관리자(승인/해제/차단/삭제/모든글관리) · 이메일 인증 · 레이트 리밋 · 비번 재설정
- 남은 것: ① 이 작업들 GitHub push(로컬 4커밋 앞섬) ② 프로드 적용 보류 중(이메일 인증 때문에 SES 필요)

### ⚠️ 프로드 어긋남 발생 → 프론트 롤백으로 안정화 (2026-06-25)
- 사건: 계정기능 push(d98a778) 시 **CI/CD가 frontend/** 변경을 감지해 새 프론트를 프로드 S3에 자동배포** → 하지만 **백엔드는 수동배포라 옛버전 그대로** → 프로드가 "새 프론트 + 옛 백엔드"로 어긋남
  - 증상: 라이브에서 /auth/verify·/auth/forgot-password·/admin/users 전부 404(옛 백엔드엔 없음) → 회원가입·관리자·비번찾기 깨짐. 단 공개글 읽기·옛 로그인은 동작
- 조치: **프론트 롤백** — 커밋 359dc8f(계정기능 전, 애플리디자인 버전)를 `git worktree`로 꺼내 `VITE_API_BASE=프로드` 빌드 → `aws s3 sync --delete` → CloudFront 무효화(ICCL5E6KB8RH9QVFV0O3NOP6P9). 라이브 JS가 index-BN2XwMld.js로 복귀 확인, forgot-password 흔적 없음, /api/posts·/ 200
- **현재 상태**: 코드/기능은 GitHub·로컬에 안전(완성). **프로드 라이브 = 계정기능 전 버전으로 일관**(읽기 정상)
- 🔴 **다음에 프로드에 계정시스템 올리려면**(한 번에): ① EC2 백엔드 재배포(tar→scp→`docker compose -f docker-compose.prod.yml up -d --build`, prod compose 시작 시 alembic upgrade 자동 → role·email_verified 마이그레이션 적용) ② SES 셋업(이메일 인증/비번재설정 메일) + prod .env에 `FRONTEND_BASE_URL=CloudFront`, `ADMIN_EMAIL`, `SMTP_*`=SES ③ 그 다음 프론트 재배포(CI 또는 수동)
- 🔴 **CI/CD 함정**: deploy.yml이 frontend/** push마다 자동배포 → 백엔드+SES 준비 전에 frontend 또 push하면 프로드 다시 어긋남. 프로드 풀배포 전까진 frontend push 주의(또는 워크플로 일시중단 고려)

### 🎉 계정 시스템 AWS 프로드 풀 배포 완료 (2026-06-25)
- **SES 셋업**: SES 콘솔(서울 ap-northeast-2)에서 이메일 ID(es2646526@gmail.com) verify + SMTP 자격증명 생성(IAM `ses-smtp-user.20260625-184915`, username=AKIA…). 엔드포인트 `email-smtp.ap-northeast-2.amazonaws.com:587`(STARTTLS). ⚠️ 아직 **샌드박스** → verify된 수신자에게만 발송됨(공개가입 받으려면 production access 요청 필요)
- **코드**: `config`에 smtp_user/password/use_tls, `email.send_email`에 STARTTLS+login 분기(로컬 Mailpit은 평문 그대로). 커밋 f59dea3
- **백엔드 배포(EC2 15.164.102.25)**: 로컬 backend tar→scp→`~/blog` 추출, `.env`에 SMTP_*(SES)·MAIL_FROM·FRONTEND_BASE_URL(CloudFront)·ADMIN_EMAIL 추가(비번은 사용자가 nano로, 나는 안 봄), `sudo docker compose -f docker-compose.prod.yml up -d --build` → slowapi 설치 + **alembic이 role·email_verified 마이그레이션 RDS에 자동 적용**(로그 확인)
- **프론트 배포**: 최신(HEAD) `VITE_API_BASE=CloudFront/api` 빌드 → `aws s3 sync --delete` → 무효화(I1SBWZYI7HCAF3IXCZRJ9DENZG). 라이브 JS=index-Cl94fXKg.js
- 검증: 라이브 `/api/auth/verify` 400·`/forgot-password` 202·`/admin/users` 401(전부 살아남, 옛날엔 404), `/api/posts` 200, 포털 200, 프론트=백엔드 일치
- **프로드 관리자 만들기**: 라이브에서 es2646526@gmail.com으로 가입 → ADMIN_EMAIL이라 **자동 admin+자동 인증(메일 불필요)** → 바로 로그인 가능
- 이제 CI 함정 해소(백엔드가 최신이라 frontend push 자동배포돼도 일치). 남은 선택: SES 프로덕션 액세스(공개가입), 커밋들 GitHub push

### 보안: ADMIN_EMAIL 자동승격 부트스트랩 제거 (2026-06-25) — 커밋 4363542
- 라이브에서 es2646526@gmail.com 가입 → admin 됨(부트스트랩으로). **첫 관리자 생겼으니 부트스트랩 제거**(이메일 장악/비번재설정 악용 시 admin 탈취 위험)
- 제거: auth.py `_is_admin_email`·register admin특례·login 자동승격, config `admin_email`, docker-compose `ADMIN_EMAIL`. 이제 register는 전부 pending+미인증
- 기존 admin 계정(role=admin)은 DB에 남아있어 영향 없음(코드 제거해도 행은 유지)
- **앞으로 관리자 승격은 DB에서만**: `ssh ec2 → sudo docker compose -f docker-compose.prod.yml exec backend python` 또는 psql로 `UPDATE users SET role='admin' WHERE email='...'`
- 프로드 재배포(tar→scp→up --build) 완료, 배포코드 `_is_admin_email` 0개 확인, es2646526 admin 유지 확인. prod .env의 ADMIN_EMAIL은 이제 코드가 안 읽음(무해, 지워도 됨)
- 로컬/원격 git: 로컬 다수 커밋 앞섬 → 외부터미널 `git push origin main` 필요

### 🏁 오늘(2026-06-25) 마무리
- 한 일 요약: 계정 권한제(role pending/writer/admin/banned) → 관리자 승인·차단·삭제·모든글관리 → 이메일 인증 + 레이트 리밋 → 비번 재설정 → AWS 프로드 풀배포(SES 포함) → 보안 강화(ADMIN_EMAIL 부트스트랩 제거) → SES 프로덕션 액세스 신청
- 커밋: b6d9392, d80002a, 5358993, d98a778, f59dea3, 717d77e, 4363542, 1aa1714 (전부 GitHub push 완료)
- 개발일지 Word 생성: `scripts/make_devlog_20260625.py` → `블로그_개발일지_2026-06-25.docx` (WSL + Windows Documents 양쪽 저장)
- 대기 중: SES 프로덕션 액세스 심사(~24h). 승인되면 라이브에서 아무 이메일로나 공개 가입 가능

## 2026-06-26

### 🔴 보안: 프로드 SECRET_KEY 기본값 → 강력 랜덤으로 교체 [완료]
- 발견: 프로드 .env에 SECRET_KEY 없음 → config 기본값 `change-me-in-production`(코드에 공개) 사용 중 → **누구나 JWT 위조해 admin 탈취 가능**(치명적)
- 조치: EC2에서 `openssl rand -hex 32`로 생성(값은 화면에 안 남김) → ~/blog/.env에 SECRET_KEY 추가 → `docker compose -f docker-compose.prod.yml up -d --force-recreate`. 기존 토큰 전부 무효화(재로그인 필요), health 200 확인
- 보안 점검표 작성: 튼튼(bcrypt·HTTPS·ORM·서버측 권한·계정 비노출·글쓰기 승인제·SECRET_KEY) / 약함 우선순위(①기본키 재발방지 코드가드 ②비번 강도규칙 ③로컬 SECRET_KEY ④JWT 무효화 ⑤보안헤더·미인증정리)
- 다음 결정 대기: ①②③(쉬운 고가치) 또는 ④까지 하드닝할지

### 🔓→🔒 권한받은 침투 테스트(자기 사이트) + 2차 구멍 차단 [완료]
- 공격1: 공개 기본키로 admin(id3) JWT 위조 → 라이브 /auth/me·/admin/users **401 거부**(SECRET_KEY 교체 효과 입증). 이게 "10초 털이"의 정체(위조 토큰 admin화 + 비번재설정 토큰 위조로 임의계정 탈취까지 가능했음)
- 공격2: 무인증 /admin/users → 401(접근제어 정상)
- **공격3 발견🔴**: EC2가 `http://15.164.102.25:8000` 인터넷 직접 노출 — /docs·/openapi.json 200 = WAF·HTTPS 우회 + 평문 + API 지도 노출. 원인 SG 8000=0.0.0.0/0
- **조치**: `terraform/ec2.tf` 8000 ingress를 `0.0.0.0/0` → CloudFront 관리형 prefix list `pl-22a6434b`(com.amazonaws.global.cloudfront.origin-facing)로. plan=in-place 1변경/0파괴, apply 완료. 검증: 직접 IP:8000 전 경로 000(차단), CloudFront 경유 200(정상)
- mass-assignment 안전(UserCreate는 email/password만 → role/email_verified 주입 불가). 남은 default 시크릿 없음(DB·SMTP는 실값)
- 🔴 재발 위험: config.py secret_key 기본값 `change-me-in-production` 여전히 코드에 존재 → 다음 배포 때 .env 빠뜨리면 또 뚫림. 코드가 기본값 거부하게 가드 필요(미적용, 다음)

### 🔓→🔒 침투 테스트 2라운드 — 남용/DoS [완료] (커밋 1698b9a)
- 로컬 재현(안전): 댓글 도배(무인증·무제한 6/6) / 과대입력 500(제목250·author60 → DB제약 미검증 500 = "글 길게 쓰면 안 써짐"의 정체) / 본문 2MB 201(무제한) / 글 10연타 무제한 / 업로드 용량무제한(메모리·디스크 폭탄). 본문 XSS는 react-markdown 기본(rehype-raw 없음)이라 차단됨
- 수정: ① 스키마 길이검증(post 제목200·본문50k, comment author50·content2k) → 과대입력 500→422 ② 댓글 20/hour·글 30/hour 레이트리밋(slowapi, Request 인자) ③ 업로드 5MB 상한(read(MAX+1)로 메모리 보호, 413)
- 로컬 재공격 검증: 제목250→422, author60→422, 본문2MB→422, 업로드6MB→413, 댓글25연타→20통과 후 429. 프로드 재배포 후 과대댓글→422 확인
- 남은 권장: ①SECRET_KEY 기본값 코드가드(재발방지) ②비번 최소길이 ③JWT 만료단축/무효화 ④프론트 422/413/429 에러 메시지 친절화(UX)
- git: 로컬 다수 커밋 앞섬 → push 필요

### 🔒 보안 하드닝 4종 [완료] (커밋 1698b9a 다음 커밋)
- **① SECRET_KEY 가드**(main.py lifespan): 기본값/빈값/<16자면 서버 시작 거부(fail-closed) → .env 빠뜨린 채 배포돼도 조용히 안 위험해짐. 로컬 docker compose·루트 .env에 개발용 키 추가(비밀 아님), 프로드는 openssl 키(이미 설정)
- **② 비번 길이**: 가입/재설정 8~72자(RegisterRequest·ResetPasswordRequest Field), 로그인은 72자 상한(bcrypt 72바이트 초과 에러 방지). 프론트 가입 비번 8자 힌트
- **③ 토큰 무효화**: User.token_version 추가(마이그레이션 3e99ae1b58c1, 기존 0 백필). JWT에 ver 클레임, get_current_user(_optional)가 user.token_version과 비교→불일치 401/None. 비번 재설정·차단 시 token_version+1로 기존 세션 강제종료. 만료 24h→12h
- **④ 프론트 에러**: posts/comments 422(길이)·429(레이트), uploads 413(용량), register 422(이메일·비번) 친절 메시지
- 검증: 로컬 e2e(짧은비번 422, 재설정 후 옛 토큰 401, 새 비번 로그인 200) + 프로드 배포 후(위조토큰 401, 짧은비번 422, health 200=가드 통과, token_version 마이그레이션 로그). 프론트 빌드/lint 통과, 라이브 최신 반영
- **보안 점검 마무리**: SECRET_KEY(치명)·직접노출·남용/DoS·인증하드닝까지 전부 처리·라이브 적용. 남은 선택(낮음): 보안헤더(HSTS), 미인증 계정 자동정리, SES 프로덕션 액세스(대기중)
- git: 로컬 다수 커밋 앞섬 → 외부터미널 push 필요

### 🔒 보안 헤더 + 미인증 계정 자동정리 [완료]
- **보안 헤더**(`cloudfront.tf`): 3개 behavior(default S3·/api·/uploads)에 AWS Managed-SecurityHeadersPolicy(`67f7725c-...`) 부착 → terraform apply(in-place, 0파괴, 50s). 라이브 검증: HSTS(max-age=31536000)·x-content-type-options:nosniff·x-frame-options:SAMEORIGIN·referrer-policy·x-xss-protection 전부 SPA·API 양쪽에 적용됨
- **미인증 정리**(`services/cleanup.py`): 가입 후 24h 지나도 email_verified=false면 1시간 간격 데몬이 삭제(start_cleanup, main lifespan). 미인증은 로그인 불가→글·댓글 없음→안전 삭제(author_subscriptions는 FK CASCADE). 로컬 검증: 25h 미인증 삭제·최근 미인증/인증계정 유지. 프로드 배포·health 200
- **보안 작업 전부 종료** — 치명/중/낮음 항목 모두 처리·라이브 적용. 남은 건 SES 프로덕션 액세스 심사(대기) 뿐
- git: 로컬 다수 커밋 앞섬 → push 필요

### 🐛 이미지 업로드 영구화 + 메일 HTML화 [완료] (2026-06-26)
- **메일 클릭 문제**: 인증/재설정 메일이 순수 텍스트라 일부 클라이언트(네이버)가 링크 자동연결 안 함 → `services/email.py`를 HTML(클릭 버튼+전체 URL 병기)로. send_email에 html 파라미터, _action_html 헬퍼. (발신 도메인 불일치 "주소 다를 수 있음" 경고는 도메인 없을 때의 한계라 남을 수 있음)
- **이미지 다른 기기서 안 보임**: 원인 = 프로드 compose에 uploads 볼륨이 없어 이미지가 컨테이너 안에만 저장 → 오늘 보안 재배포(--build) 반복으로 매번 uploads 폴더 초기화됨(0개). URL은 정상(PUBLIC_BASE_URL=CloudFront)
  - 조치: docker-compose.prod.yml에 `volumes: ./uploads:/app/uploads` 추가 + `mkdir uploads` → 호스트 디스크 영구저장. 검증: 호스트 파일이 컨테이너에 보이고 --build 재빌드 후에도 생존. prod compose를 저장소에도 추가(이전엔 EC2에만)
  - ⚠️ 이미 사라진 기존 이미지는 복구 불가 → 재업로드 필요. 장기적으론 S3 업로드가 정석(인스턴스 교체에도 안전)
- SES: youno3249@gmail.com 발신ID 등록(verify 대기, 사용자가 메일 링크 클릭 필요). jinukkim0305@naver.com은 사용자 것 아님(프로드 계정 삭제함, SES ID는 남아있음)

### 🖼 이미지 업로드 S3 이전 [완료] (2026-06-26)
- 동기: 볼륨 방식은 재배포엔 안전하나 인스턴스 교체엔 취약 → S3로 영구화(정석)
- IAM: `aws iam create-role blog-ec2-role`(트러스트 ec2) + inline정책(s3:PutObject on `blogplafromops/uploads/*`) + 인스턴스 프로파일 `blog-ec2-profile` 생성·역할추가·EC2 연결. **CLI로 생성(Terraform 미관리 = 드리프트, 나중에 ec2.tf에 iam_instance_profile 반영 권장)**
- 백엔드: config s3_bucket/aws_region 추가, requirements boto3, uploads.py가 s3_bucket 있으면 boto3 put_object(키 없이 인스턴스 역할 IMDS 인증), 없으면 로컬 디스크. URL은 동일 `{public_base_url}/uploads/<name>`
- CloudFront(`cloudfront.tf`): `/uploads/*`→EC2 ordered behavior 제거 → 기본 S3 오리진이 이미지 서빙(객체키 `uploads/<name>`). apply in-place 0파괴
- prod .env: S3_BUCKET=blogplafromops, AWS_REGION=ap-northeast-2
- 검증: 컨테이너 boto3로 S3 put 성공(인스턴스 역할 작동) + CloudFront /uploads/_roletest.png 200·image/png. 테스트객체 삭제
- 결과: 새 업로드는 S3에 저장→CloudFront 서빙→인스턴스 교체에도 안전. (볼륨 마운트는 폴백으로 남겨둠, 무해)
- ②글쓰기: youno3249·jinukkim·ppap 모두 이미 writer 상태(사용자가 /admin서 승인했거나). ①SES youno3249 verified 완료

### 🐛 새로고침 로그인튕김 + 이미지삭제 함정 [완료] (2026-06-26)
- 새로고침 시 /login 튕김: WritePostPage 가드가 인증복구(fetchMe) loading 중 user=null을 보고 즉시 navigate('/login') → `if(loading)return`으로 보류하게 수정(AdminPage 패턴과 동일)
- ⚠️ 발견한 함정: 이미지를 프론트와 같은 버킷(blogplafromops/uploads/)에 넣었는데 프론트 배포가 `s3 sync --delete` → 다음 배포 때 업로드 이미지 전멸 위험. deploy.yml + 수동배포에 `--exclude "uploads/*"` 추가로 방지. (장기적으론 이미지 전용 버킷 분리가 더 깔끔)

### 🐛 글쓴이 구독 → 일부공개 열람 "안 됨" 진단·수정 [완료] (2026-06-26)
- 증상: 구독해도 일부공개 글 안 보임. 진단: author_subscriptions **0건**(구독이 실제로 안 됨) + 데이터상 admin(주인장)은 공개글이 없음(일부공개만)
- 근본원인: "글쓴이 구독" 버튼이 **글 상세에만** 있는데, 일부공개 글은 구독 전 못 열어(404) → 공개글 없는 작성자는 **구독 입구가 없어** 영영 구독 불가(막다른 길). 백엔드·구독로직 자체는 정상(로컬 e2e: 구독전 404→구독→200·목록반영)
- 해결(개인블로그형): `GET /api/blog-owner`(admin id 반환) + 홈에 **"이 블로그 구독"** 버튼 → 주인장 구독 → loadPosts로 일부공개 글 즉시 반영. 라벨 "일부공개(나만)"→"일부공개(구독자에게만)" 모순 수정. (메일구독=새글알림 / 블로그구독=일부공개열람, 둘 다 홈에)
- 검증: blog-owner 프로드 {id:3,es2646526}, build/lint 통과, 라이브 반영

### 🔒 보안검사 2차 (신규 기능 포함 전수) [완료] (2026-06-26)
- 권한받은 재점검(자동공격+코드리뷰). 기존 방어 전부 유지 확인:
  - SECRET_KEY 위조토큰→401, EC2 :8000 직접→차단(000), **IMDSv2 required**(SSRF로 인스턴스 역할키 탈취 방어 — 새 boto3 S3업로드 땜에 핵심), S3 퍼블릭차단 4종 true·익명GET 403, IAM 역할 최소권한(uploads/* PutObject만)
- 신규표면 점검: /api/subscriptions/detail 인증게이트(401), /api/blog-owner 공개(admin id·이름 노출=설계상 허용, 작성자는 공개), 업로드는 content-type 허용목록+nosniff+image/*서빙+서버 uuid키+IAM uploads/*스코프 → 스토어드XSS/임의키 쓰기 차단
- **발견·수정🟠**: 새 글 알림메일에 글 제목이 HTML 이스케이프 없이 들어감 → 악성 제목(`<img onerror>`)이 구독자 메일에 HTML 인젝션 가능 → `html.escape` 적용(로컬서 &lt;img 무력화 확인, 배포)
- 저위험/수용: blog-owner의 admin username 노출(블로그 작성자는 공개라 OK), POST /subscriptions 레이트리밋 없음(영향 적음), 업로드 매직바이트 미검증(allowlist+nosniff로 충분)
- 결론: 치명/고위험 0건. 발견된 1건(메일 인젝션) 수정 완료. 전반 양호

### 🔒 보안검사 3차 — 심층(IDOR·비용·인젝션) [완료] (2026-06-26)
- 깊게 판 영역: JWT(alg 고정 HS256·purpose 분리·exp), IDOR/접근제어, mass-assignment(role 주입 불가), SQLi(ORM), SSRF(없음+IMDSv2), CORS(Bearer라 무관), CSRF(헤더토큰이라 무관), 업로드 경로/매직바이트, 레이트리밋 공백, 정보노출, 에러 누출, 계정 enumeration, 전송
- **발견·수정**:
  - 🟠 **비공개 글 댓글 IDOR**: GET/POST /posts/{id}/comments가 can_view 미확인 → 글 못 봐도 댓글은 누구나 읽기/쓰기(글id 순번이라 전수 수집 가능). → posts.can_view 재사용해 볼 권한 있는 사람만(404). 프로드 검증: 비공개 8·9 댓글 404, 공개 2 댓글 200
  - 🟡 **/ai/draft 레이트리밋 없음**: writer가 AI 무한호출→비용폭탄 → 10/hour 추가
  - (2차에서) 알림메일 제목 HTML 인젝션 → html.escape
- 저위험/수용: 가입 시 409로 이메일 존재 노출(rate limit로 완화), 댓글 삭제(모더레이션) 엔드포인트 없음(스팸시 DB로), 비번재설정 토큰 1h내 재사용 가능, 업로드 매직바이트 미검증(allowlist+nosniff로 충분), CloudFront→EC2 오리진은 HTTP(AWS 내부망+오리진 잠금)
- 결론: 치명 0. 이번 심층검사로 IDOR 1건(중)·비용 1건 추가 수정. 잔여는 저위험·수용 가능 수준

### 🔒 보안검사 4차 — 토큰혼동·PII노출 [완료] (2026-06-26)
- **발견·수정**:
  - 🔴 **구독자 이메일 전수 노출**: GET /subscribers가 무인증 → 모든 구독자 이메일(PII) 공개. → require_admin. POST /subscribers는 레이트리밋 추가(남 이메일 무단등록 방지)
  - 🟠 **토큰 혼동**: verify/reset 토큰(이메일용)이 로그인 토큰으로 그대로 통함(/auth/me 200) → reset 링크 유출 시 계정 전체 접근. → decode_access_token이 purpose 있는 토큰 거부. 검증: verify토큰 /auth/me 401, 정상 로그인 200 유지, /auth/verify 정상
  - alg=none 위조 → 이미 거부됨(PyJWT algorithms 고정) 확인
- 프로드 라이브 검증: /subscribers 무인증 401
- 잔여 저위험: 구독 double opt-in 없음(레이트리밋만), 댓글 작성자명 사칭(익명 설계), CSP 헤더 없음(HSTS/nosniff/frame은 있음), 비번재설정 토큰 1h 재사용(단 이제 access로는 못 씀)

### 🔒 보안검사 5차 — 1회용토큰·댓글모더레이션·CSP시도 (2026-06-27)
- ① **비번재설정 토큰 1회용화** [완료/배포/검증]: reset 토큰에 token_version 임베드, 재설정 시 +1 → 같은 토큰 재사용 시 ver 불일치로 400. (1차 200·2차 400)
- ② **댓글 모더레이션** [완료/배포]: DELETE /posts/{id}/comments/{cid} (글 작성자·관리자만, 남 403·주인 204), 프론트 댓글 삭제 버튼(권한자에게만)
- ③ **CSP 헤더** [보류]: 커스텀 응답헤더 정책으로 CSP 넣으려다 **CloudFront Free 요금제가 커스텀 정책 거부**("Free pricing plan can't have Custom response headers policy"). 관리형 SecurityHeadersPolicy(HSTS·nosniff·frame·referrer·xss)는 유지. CSP는 플랜 업그레이드 또는 CloudFront Functions(viewer-response) 필요 → 보류. orphan 정책 삭제 정리, terraform No changes
  - 참고: 주 XSS 방어(react-markdown 기본=raw HTML 미렌더 + nosniff)는 이미 있음 → CSP는 추가 방어층(우선순위 낮음)

### 🤖 6단계 AI — 키 주입 + 모델 티어(A단계) [완료/로컬검증] (2026-06-27)
- **AI 초안 활성화**: ANTHROPIC_API_KEY를 .env(gitignore)에 넣고 docker-compose는 `${ANTHROPIC_API_KEY}` 참조만. 컨테이너에서 generate_draft 실제 Claude 호출 성공(opus-4-8, 마크다운 구조+플레이스홀더 정상)
- **A단계 — 모델 선택 + Claude 티어 골격**:
  - User에 `is_pro` 컬럼 추가(마이그레이션 a1b2c3d4e5f6)
  - 티어 게이팅: 일반 writer=Sonnet+Haiku(Opus만 잠금) / is_pro·admin=전부(3개). 기본=Sonnet. (Haiku는 저렴해서 누구나)
  - `GET /ai/models`(허용 모델만), `/ai/draft`에 model 파라미터+검증(미허용 403)
  - admin `POST /users/{id}/toggle-pro`(수동 유료 부여, 나중에 Stripe가 대체)
  - 프론트: 글쓰기 모델 드롭다운(허용된 것만), AdminPage 유료 뱃지+토글
  - 자가검증: 마이그레이션 적용, 티어로직 3종 확인, /ai/models 401, 소넷 생성 OK, 프론트 빌드 통과
- **다음**: B단계(BYOK — GPT·Gemini 자기키 암호화 저장+라우팅) → C단계(Stripe 결제→is_pro 자동)
- 미반영: 프론트 docker 재빌드(화면 확인용), git push, 프로드 배포(EC2 .env에 키)

### 🤖 6단계 AI — BYOK 멀티 프로바이더(B단계) [완료/로컬검증] (2026-06-27)
- **B1 백엔드**:
  - 새 테이블 `llm_credentials`(user_id, provider, encrypted_key) — 마이그레이션 b2c3d4e5f6a7
  - 사용자 키 Fernet 암호화 저장(`LLM_ENCRYPTION_KEY` .env, docker-compose 참조 추가). 복호화는 호출 순간만, 응답/로그 노출 금지
  - 의존성 추가: cryptography·openai·google-genai (백엔드 이미지 재빌드)
  - 모델 카탈로그에 provider 부착(claude/openai/gemini). `generate_draft` provider 분기: claude=서버키, openai/gemini=사용자키
  - 엔드포인트: GET/PUT/DELETE `/ai/keys/{provider}`(자기 키, 마스킹), `/ai/models`·`/ai/draft`가 BYOK 반영(키 있을 때만 노출/사용)
  - 자가검증: Fernet roundtrip OK, allowed_models가 키 유무로 GPT/Gemini 토글, 라우트 401
- **B2 프론트**: `/settings` 페이지(키 등록/교체/삭제, 등록여부만 표시), 네비 '설정' 링크(writer만), 글쓰기 드롭다운은 /ai/models로 자동 반영. 빌드 통과
- 미검증(키 필요): GPT/Gemini 실제 호출은 사용자 키 넣고 확인. 모델ID(gpt-4o/4o-mini, gemini-2.5-flash/pro)는 카탈로그에서 조정 가능
- **다음**: C단계(Stripe 결제 → is_pro 자동) 또는 프로드 배포

- **B 보강 — BYOK 커스텀 모델 직접입력**: 카탈로그에 없는 모델 ID도 사용 가능(BYOK 전용). DraftRequest에 provider 추가, /ai/draft가 커스텀 모델이면 provider+키등록 확인 후 호출. 프론트 글쓰기 드롭다운에 "직접 입력 — OpenAI/Gemini" 옵션 + 모델ID 입력칸. (하이엔드 사용자가 자기 계정 지원 최상위 모델 직접 지정)

- **B 보강2 — OpenAI 호환 범용(compatible)**: provider 'compatible' 추가. llm_credentials에 base_url 컬럼(마이그레이션 c3d4e5f6a7b8). OpenAI SDK에 base_url 주입 → Grok·DeepSeek·OpenRouter·Groq·로컬(Ollama) 등 OpenAI 호환 엔드포인트 전부 사용 가능(주소+키+모델ID). 설정 페이지에 'OpenAI 호환' 칸(주소+키), 글쓰기 직접입력 옵션은 등록키 기준(GET /ai/keys)으로 노출. 빌드·마이그레이션·import 검증 완료

- **B 보강3 — 비호환 제공자 Anthropic·Cohere 추가**: BYOK_PROVIDERS에 anthropic(자기 Claude 키, 서버키·티어와 별개로 Opus 등 직접)·cohere(command 모델). _claude에 api_key 오버라이드, _cohere 추가(cohere==5.13.3). 둘 다 base_url 없는 직접입력형 — 설정 페이지 항목 추가, 글쓰기 직접입력 옵션은 등록키 기준 자동 노출. 검증: import/분기/빌드 OK

## 2026-06-27 (이어서) — 다크모드·보안·공개범위·구독 관리

### 🎨 다크모드 드롭다운 [완료/배포]
- AI 모델 select 옵션 팝업이 다크모드에서 안 보이던 문제: `.dark` 클래스만 켜고 color-scheme는 light라 네이티브 팝업이 밝게 떴음 → `index.css`에 color-scheme를 테마와 동기화. 라이브 CSS 반영 확인
- 배운 것: 네이티브 폼 컨트롤(select 옵션·스크롤바)은 CSS가 아니라 color-scheme로 명암이 정해짐

### 🔒 BYOK SSRF 방어 [완료/로컬검증]
- compatible provider의 base_url을 서버가 그대로 호출 → 내부망·메타데이터(169.254.169.254) SSRF 가능했음. `validate_base_url`로 https만 허용 + 호스트가 푸는 모든 IP가 공인 대역이어야 통과(사설/loopback/링크로컬 차단). DraftRequest.model 길이 상한도 추가
- 한계: DNS rebinding은 못 막음 → 인프라(EC2 IMDSv2 강제)가 최종 방어선. SECRET_KEY는 main.py lifespan fail-closed로 이미 방어 중

### 👁 공개범위 3단계 [완료/로컬검증]
- 2단계(public/private, 사실상 '구독자공개')를 3단계로 분리: public(전체)·subscribers(구독자공개)·private(나만)
- 핵심 보안 수정: 예전엔 '구독'만 하면 비공개글이 보였음(누구나 회원가입→구독→열람). 이제 private은 작성자/관리자만, subscribers만 구독자 게이팅
- `posts.visibility` varchar(10)→(20) 마이그레이션 e4f5a6b7c8d9 + 기존 private→subscribers 자동 이관(의미 보존). PATCH `/posts/{id}/visibility`로 작성 후 변경. 프론트 작성 라디오 3개 + 상세 인라인 드롭다운
- can_view 진리표 12/12, 구독자 가시성 라이브 검증

### 🔔 구독 관리 [완료/로컬검증]
- 계정 구독을 전용 페이지 `/subscriptions`로 분리(계정 늘어도 안 난잡). GET `/subscriptions/authors`로 구독 가능 글쓴이 목록 → 계정별 토글 구독/해제
- 새 글 이메일 구독: 누구나 self-unsubscribe(POST `/subscribers/unsubscribe`, 존재 비노출) + 관리자 목록/삭제(DELETE `/subscribers/{id}`). 홈에선 이메일 폼 제거하고 링크만
- 라이브 검증: authors 목록·삭제 권한(admin 204/비admin 403)·이메일 등록/취소/재등록

- **다음**: 프론트 컨테이너 재빌드 후 화면 확인, 프로드 배포(EC2 `.env` 키·IMDSv2 강제 확인)

### 🔒 보안검사 6차 — 구독 더블옵트인(#3) [완료/로컬검증] (2026-06-27)
- 문제: POST `/subscribers`가 남의 이메일을 동의 없이 등록 → 그 사람에게 새 글 알림이 감(레이트리밋만 있었음). **SES 발신평판 악용**(원치 않는 메일→스팸신고→평판하락/계정정지) 위험.
- 해결 = **더블옵트인**: 등록 즉시 구독 X, '확인 메일'만 발송 → 본인이 링크 눌러 `confirmed=True`가 된 사람에게만 알림.
  - DB: `subscribers.confirmed` 컬럼(마이그레이션 **f5a6b7c8d9e0**). 기존 구독자는 `server_default=true`로 백필(정책 이전 가입자 유지) 후 서버기본값 제거 → 신규는 앱 기본 False
  - 백엔드: `POST /subscribers`는 신규/기존 구분 없이 **동일 메시지** 응답(구독여부 enumeration도 같이 제거), 미확인이면 확인메일(재)발송·확인된건 무발송. `POST /subscribers/confirm?token=`(purpose=subscribe JWT, `create_email_token` 재사용). **`notify_new_post`가 `confirmed=True`만 발송 = 핵심 방어선**
  - 프론트: 구독폼 메시지 '확인 메일 보냈어'로, `SubscribeConfirmPage`(`/subscribe/confirm`) 추가, 관리자 목록에 '확인 대기' 뱃지
- **곁다리 버그 수정**: `alembic/env.py`에 `llm_credential` 모델 import 누락 → autogenerate가 그 테이블(BYOK 키)을 drop하려 했음(데이터 유실 위험). 1줄 import 추가로 `alembic check` 완전 green 복구
- 자가검증(전부 PASS): 마이그레이션 백필 확인, e2e(구독→확인메일 토큰추출→confirm→confirmed 전환), `notify_new_post` 직접호출로 **confirmed만 수신/미확인 제외 PASS**, 잘못된 토큰 400·형식 422·무인증 목록 401, 빌드/lint green, 테스트데이터 정리
- **미반영**: git push, 프로드 배포(마이그레이션은 다음 배포 때 RDS 적용 — `docker compose -f docker-compose.prod.yml ... up`이 `alembic upgrade head` 수행)
- 남은 보안 잔여과제: #4 업로드 확장자/타입 정규화(라이브는 안전, 로컬만), #6 댓글 로그인 사용자 작성자 고정, #5 가입 enumeration(보류 검토)

### 🔒 보안검사 6차 (이어서) — 업로드(#4)·댓글 사칭(#6) [완료/로컬검증] (2026-06-27)
- **#4 업로드 — 클라 입력 신뢰 제거**: 예전엔 `file.content_type`(클라가 보냄)과 파일명 확장자를 그대로 믿어서 `.html`/`.svg`가 저장될 수 있었음(라이브는 S3 ContentType이 이미지라 실행은 안 됐지만 로컬 StaticFiles는 위험).
  - 해결: `_sniff_image`로 **매직바이트(파일 앞부분)로 실제 이미지 종류만 판별** → content_type·확장자 둘 다 거기서 도출. 사용자 파일명은 아예 안 씀(경로조작·실행확장자 차단). PNG/JPEG/GIF/WebP만 통과, 그 외(HTML·SVG 포함) 400.
  - 검증: sniff 단위테스트(6종), e2e — [공격] PNG내용+`evil.html`+`text/html` → `.png`로 정규화·`image/png` 서빙(무력화), [공격] HTML내용+`image/png` → 400, 무인증 401
- **#6 댓글 작성자 사칭**: 로그인해도 `author`가 자유입력이라 '남 이름'으로 댓글 가능했음.
  - 해결: **로그인 사용자는 author를 계정(이메일 로컬파트, 앱 전역 `email.split("@")[0]` 규칙)으로 강제** — 클라가 보낸 author 무시. 익명만 자유입력 유지(익명 댓글 설계상 불가피, 사회공학 범주). 프론트도 로그인 시 입력칸 숨기고 고정이름 표시.
  - 검증: 로그인 kim이 `author=admin` 시도 → DB에 `kim` 저장, 익명 `randomguy`는 그대로
- 빌드/lint green, 테스트 데이터 정리
- **미반영**: git push, 프로드 배포

### 🔒 보안검사 6차 (이어서) — 가입 enumeration(#5) [완료/로컬검증] (2026-06-27)
- 문제: `POST /auth/register`가 기존 이메일이면 409 "이미 가입된 이메일" → **계정 존재 여부 노출**. 로그인·비번찾기는 일부러 안 흘리는데 가입만 흘렸음(일관성 결여).
- 해결 = **응답 일반화**(forgot-password와 동일 패턴): 신규/기존 구분 없이 항상 `202 {"확인 메일을 보냈어..."}`. 실제 안내는 **메일로만**:
  - 신규 → 인증메일 / 기존+미인증 → 인증메일 재발송 / 기존+인증완료 → '이미 가입됨' 안내메일(`send_already_registered_email`)
- 프론트: 가입 성공화면이 이미 "메일을 확인해줘"(자동로그인 X)라 그대로 맞음 → `api/auth.ts`에서 409 처리 한 줄만 제거. UX 트레이드오프(즉시 '이미 가입' 피드백 사라짐)는 수용
- 검증: **신규 vs 기존인증 응답 바이트 단위 동일(PASS)**, 메일 분기 3종 확인(newreg 인증x2·kim 이미가입x1), DB 신규생성·기존무영향, 빌드/lint green, 정리 완료
- 한계(수용): 신규는 bcrypt 해싱이 있어 미세한 타이밍 차이는 남음(forgot-password와 동일 수준) — 경미해서 미대응
- **보안 잔여과제 #2~#6 전부 처리 완료** (#2 SSRF 기배포·#3 더블옵트인·#4 업로드·#5 가입·#6 댓글)
- **미반영**: git push, 프로드 배포

### 🔒 보안검사 7차 — AI 초안 강화 (A·B·C·D) [완료/로컬검증] (2026-06-27)
AI 초안 surface 전체 검토. 기본기(require_writer·키 Fernet 암호화·SSRF·티어 게이팅)는 이미 탄탄 → 추가 강화 4건:
- **A. 레이트리밋 우회(XFF 스푸핑) 차단** 🔴: `ratelimit.py client_ip`가 X-Forwarded-For **맨 앞**을 클라 IP로 써서, 클라가 맨 앞을 위조하면 요청마다 다른 IP인 척 → 모든 레이트리밋(=AI 비용캡 포함) 무력화 가능했음. CloudFront는 진짜 IP를 **맨 뒤**에 붙이므로 맨 뒤를 쓰게 수정. 단위검증(다중 XFF→맨뒤·XFF없음→peer) PASS
  - ⚠️ 인프라 보강 필요(너): EC2 SG의 8000을 **CloudFront에만 허용**해야 직접접근(:8000) 위조까지 막힘
- **B. LLM 호출 타임아웃** 🟠: compatible(사용자 지정 엔드포인트)이 응답을 끌어 워커를 묶는 DoS 방지. 모든 SDK 클라이언트에 timeout 60s + max_retries 1. anthropic/gemini/cohere 생성자 PASS
- **C. base_url SSRF 사용시점 재검증** 🟡: 저장 시점만 검증하던 걸 호출 직전 한 번 더 `validate_base_url`(DNS rebinding 창 축소). 최종 방어선은 IMDSv2
- **D. 유저별 일일 캡** 🟡: 서버키(Claude) 호출에 일일 상한(config `ai_daily_cap`=20, BYOK 제외). 새 테이블 `ai_usage`(마이그레이션 a6b7c8d9e0f1, env.py 등록), 서비스 count/increment_today(UTC), 라우터에서 호출 전 체크(429)·성공 후 증가. 캡 가득→429 단락(Claude 호출 전·비용 0) PASS
- 프론트: `api/ai.ts` 429에서 서버 detail surface(캡 메시지 노출, 레이트리밋은 기본문구 폴백)
- 검증: alembic check green, 무인증 401 게이트 유지, build/lint green, 테스트데이터 정리
- 🐛 **부수 발견→해결(기능버그)**: `openai==1.54.3` + `httpx 0.28.1` 불일치(`proxies` 인자) → OpenAI 클라이언트 생성 자체가 깨져 openai/compatible BYOK가 런타임 502였음. **`openai==1.55.3`으로 bump + 백엔드 이미지 재빌드** → OpenAI(+base_url·timeout) 생성 성공·타 SDK(anthropic/gemini/cohere) 회귀 없음·health 200 검증. BYOK openai/compatible 경로 복구
- **미반영**: git push, 프로드 배포(이미지 재배포 시 openai 1.55.3 반영 + RDS에 ai_usage 마이그레이션 적용), EC2 SG 8000을 CloudFront만 허용(A 인프라 보강)

### 🚀 프로드 배포 — 백엔드 (2026-06-27)
- 백엔드 EC2 재배포(tar→scp→`docker compose -f docker-compose.prod.yml up -d --build`). **프로드 RDS가 `3e99ae1b58c1`로 한참 뒤처져 있었음**(BYOK·공개범위3단계·is_pro 등 그간 미배포) → 이 배포가 head `a6b7c8d9e0f1`까지 **마이그레이션 6개 한 번에** 적용(is_pro·llm_credentials·base_url·visibility데이터이관·confirmed·ai_usage). 에러 0, 기존 데이터(글9·구독자2) 유지
- openai 1.55.3로 이미지 재빌드 반영. 검증: health 200·status ok·더블옵트인 응답 라이브·alembic current=head. 배포 테스트 구독자 정리 완료
- EC2 SG의 8000은 이미 CloudFront prefix list(pl-22a6434b)로만 열려 있음(직접접근 000 확인) → 보안검사 A의 인프라 짝 **이미 완료**였음
- **⚠️ 프론트는 아직 미배포**: `git push`(PAT 필요→사용자만 가능) → GitHub Actions가 프론트 자동배포. 그 전까지 프로드 프론트는 구버전이라 신규 구독 '확인 링크'(`/subscribe/confirm`)가 없음 → **다음에 `git push origin main` 1번이면 완성**
- 미반영: **git push(=프론트 배포)**, 로컬 .claude/settings.local.json(무관)

## 2026-06-28

### ✨ AI 초안 3종 보강 (코드출력 차단·월간 캡·남은횟수 UI) + 모바일 반응형 [완료/로컬검증]

**1. AI 초안 시스템 프롬프트 — 코드 출력 차단**
- `services/ai.py SYSTEM_PROMPT`에 규칙 추가: 코드블록(``` / ~~~)·인라인 코드·스크립트/명령어/설정 예시 생성 금지, 필요한 자리는 `[여기에 코드 예시를 직접 넣어주세요]` 플레이스홀더로만. 이 도구는 '글 구조 초안' 용도라 코드는 사람이 직접 넣게.
- 검증: 임포트 OK, 규칙 문자열 포함 확인

**2. 사용량 제한 추가 — 월간 캡 + 남은 횟수 UI**
- 월간 캡: config `ai_monthly_cap=200`(일일 캡 20과 별개 2차 방어선). **스키마/마이그레이션 불필요** — 기존 `ai_usage`(일별 count)를 이번 달 범위로 SUM(`ai_usage.count_month`, UTC 1일~오늘).
- 라우터: `create_draft`에서 claude일 때 일일+월간 둘 다 체크(초과 시 429). 신규 `GET /ai/usage` → `{daily_used,daily_cap,monthly_used,monthly_cap}`(서버키만, BYOK 무제한이라 제외).
- 프론트: `api/ai.ts fetchUsage()`, `WritePostPage`가 진입 시·생성 성공 후 사용량 조회 → 메모 박스 아래 "서버 모델 남은 횟수 · 오늘 N/20 · 이번 달 M/200"(소진 시 빨강) 표시.
- 검증: 백엔드 전체 임포트 OK(라우트 `/api/ai/usage` 등록 확인), 프론트 `npm run build`(tsc+vite) green

**3. 모바일 UI 반응형**
- 원인: 대부분 페이지는 이미 `sm:` 반응형인데 **헤더 nav만** 미처리 — 로그인 시 알약 버튼 5개+토글이 `flex-wrap` 없이 한 줄 → 좁은 화면 넘침.
- 수정: ① 공용 버튼 토큰(`ui.btnPrimary/btnGhost`) 패딩을 모바일 `px-3.5 py-2` / sm↑ `px-5 py-2.5`로(데스크탑 동일 유지) ② 헤더 컨테이너·nav에 `flex-wrap`+`gap-y-2`로 넘치면 다음 줄로 줄바꿈, 로고 `shrink-0`.
- 검증: `npm run build` green. **육안 확인 필요(너)**: 브라우저 devtools 반응형(375px)에서 로그인 상태 헤더가 깨지지 않고 줄바꿈되는지.

- **환경 메모**: 로컬 `backend/.venv`에 `cryptography` 누락돼 있어 설치함(requirements엔 이미 명시. 검증 위해 설치).
- **미반영**: git push, 프로드 배포

### 🚀 프로드 백엔드 재배포 (2026-06-28)
- 9e4e2f6(코드출력 차단·월간캡·남은횟수 UI·모바일) 백엔드만 EC2 재배포. tar(backend: app/alembic/alembic.ini/requirements/Dockerfile, .env·uploads 제외)→scp→`~/blog` 추출(코드만 덮어씀, `.env` 보존)→`sudo docker compose -f docker-compose.prod.yml up -d --build`(핵심 명령은 사용자가 실행, 규칙7).
- 마이그레이션 변경 없음 → RDS 무변경(시작 시 alembic upgrade head는 no-op). 검증: 컨테이너 재기동(Up~1m)·컨테이너 내 ai_monthly_cap 존재·`/api/ai/usage` 라우트 등록·라이브 health 200·신규 엔드포인트 무인증 401(도달 확인). 다운타임 거의 없음.
- ⚠️ 프론트는 여전히 미배포(git push 필요 → GitHub Actions 자동배포). 프로드 `~/blog/.env`에 ANTHROPIC_API_KEY 유무는 미확인(없으면 프로드 AI만 503, 배포 무관).

### 🔑 프로드 AI 활성화 + 라이브 e2e 검증 (2026-06-28)
- EC2 `~/blog/.env`에 `ANTHROPIC_API_KEY`(서버 Claude) + `LLM_ENCRYPTION_KEY`(BYOK 암호화) 둘 다 추가(사용자가 직접 nano, 값은 안 봄) → `up -d --force-recreate`로 반영. ⚠️ 혼동주의: 로컬 레포 루트 `.env`(개발용, 이미 키 있음)와 EC2 `~/blog/.env`(프로드, 별도)는 완전히 다른 파일. 처음에 로컬 루트만 건드려서 프로드엔 안 들어갔었음.
- 검증: 프로드 .env 형식 OK(sk-ant-…)·컨테이너가 두 키 읽음·컨테이너 내부 generate_draft 실호출 성공(522자, 코드블록 0개). 라이브 UI(admin es2646526)에서 글쓰기→초안 생성 → `ai_usage` 0→3 증가(일일 17/20·월간 197/200 남음) 서버측 확인. 남은횟수 UI·일일+월간 동시차감 라이브 동작 확인.
- `SECRET_KEY`(토큰 서명)는 프로드가 예전에 EC2에서 자체 생성한 값이라 로컬과 다름 → 건드리면 기존 로그인 전부 무효. AI 두 키만 추가.
- ✅ **이번 세션 작업 완결**: AI 코드출력 차단 + 월간캡 + 남은횟수 UI + 모바일 헤더 반응형 → 커밋 9e4e2f6 → 백엔드/프론트 프로드 배포 → 프로드 AI 키 활성화 → 라이브 e2e까지 전부 검증.

## 2026-06-29

### 🐛 AI 초안 "디스코드 검은화면" 버그 — 원인=지연, 해결=Haiku [완료/배포검증]
- 증상: 디스코드 인앱 브라우저에서 AI 초안 생성 시 전체 검은 화면+멈춤(새로고침 복구). 폰 크롬은 "기다리면 됨".
- 진단(가설→측정): 크래시 아님(크롬은 렌더 정상). **생성 latency가 문제** — 같은 메모로 Sonnet **47.2초**(2949토큰) 측정. 디스코드 웹뷰가 그 긴 요청을 못 버티고 뻗는 것(웹뷰 한계, JS에러 아님→ErrorBoundary로도 못 잡음).
- CloudFront 오리진 타임아웃은 **이미 60초**(state 확인) → 30초 컷 가설은 틀림. 크롬이 47초 기다려준 이유.
- 해결(완화): 기본 모델 **Sonnet→Haiku**(같은 메모 **16.0초**, 3배↑·비용↓, 품질 필요시 드롭다운 선택) + MAX_TOKENS 4000→2500 + generateDraft 90초 AbortController + ErrorBoundary(App 전체) + 글쓰기 화면 인앱브라우저 주의 안내. 커밋 e35ce99.
- 진짜 해결은 스트리밍(웹뷰가 '살아있음' 인식)이나 별도 큰 작업 → 나중. 당장은 Haiku 속도로 완화 + 디스코드는 "브라우저에서 열기" 권장.

### 🔧 terraform RDS engine_version 드리프트 [완료]
- 증상: `terraform apply` 에러. 원인: AWS 자동 마이너 업그레이드로 라이브 16.13인데 코드 16.12 → terraform이 다운그레이드 시도(불가)로 거부됨. AI버그와 무관한 기존 표류.
- 해결: 코드 16.13으로 맞추고 `lifecycle.ignore_changes`에 engine_version 추가(이후 자동 업그레이드 AWS 위임). `plan = No changes` 확인. 커밋 ae9bc64.

- **배포완료(2026-06-29)**: ① 프론트 git push→Actions 배포(번들 갱신·안내문구 반영) ② 백엔드 tar→scp→`up -d --build`(컨테이너 haiku/2500 반영). terraform은 No changes라 apply 안 함.
  - **라이브 검증**: CloudFront 경유 기본(Haiku) 초안 생성 **10.2초**(이전 47초)·HTTP 200·코드블록 0. 디스코드 웹뷰가 버틸 수준으로 단축. (최종 육안확인은 사용자가 디스코드에서)
  - ⚠️ 함정: 처음 "다했어"가 프론트 push만이라 백엔드는 안 올라가 있었음(컨테이너 23h·옛 sonnet/4000). 검증으로 잡아서 tar/scp→재빌드까지 마무리. 교훈: 배포 후 컨테이너 내부 값으로 반드시 확인.

### 🛡️ 자동번역 크래시 수정 + 전체 코드 감사 [완료/배포검증] (2026-06-30)

**1. 자동번역발 React insertBefore 크래시 (커밋 3c2d675)**
- 증상: 인앱 브라우저(번역 켜짐)에서 AI 초안 로딩→에러 전환 시 "insertBefore ... not a child"로 앱 전체 크래시.
- 원인: 번역기가 텍스트 노드를 `<font>`로 감싸 React 형제 재조정이 깨짐. ① fragment로 [아이콘+맨텍스트] 통째 토글, ② 조건부 형제 노드 생성/삭제가 취약.
- 수정: AI 버튼·StatusPage 새로고침·PostDetailPage 구독 버튼을 `[아이콘][<span>텍스트</span>]` 구조 고정 + AI 상태메시지 고정 컨테이너 + PostDetailPage 본문 ReactMarkdown 메모이즈(content 의존) + 전역 `translateGuard`(removeChild/insertBefore가 부모 불일치면 no-op). ErrorBoundary는 이전(e35ce99)에 추가됨.

**2. 프론트·백엔드 전체 감사 4건 (커밋 562ba26) — 치명/고위험 0**
- 프론트 fetchMe: 5xx에도 토큰 삭제→강제 로그아웃 → 401에서만 삭제
- 백엔드 register: 동시 가입 레이스 500 → IntegrityError 잡아 일반 응답(enumeration 보존)
- 백엔드 /api/status: 무인증+매호출 SMTP 2초 DoS → 30/minute 레이트리밋(라이브 429 검증)
- 백엔드 메일 Subject: 글 제목 개행 제거(헤더 인젝션 방어)
- 확인·수용: SSRF(validate_base_url) 견고, 마크다운 XSS 차단(react-markdown v10 raw 미렌더), IDOR/권한/enumeration/토큰버전 전부 양호, SECRET_KEY fail-closed

**3. ESLint 정리 (커밋 41420ff)**: preserve-caught-error(cause 보존) 2 + exhaustive-deps 1 → 0 problems

- **배포검증(2026-06-30)**: 프론트 git push→Actions(번들에 translateGuard DOM override 지문 확인), 백엔드 tar→scp→rebuild(IntegrityError·30/minute 반영). status 레이트리밋 CloudFront 경유 35회→30×200+5×429. terraform No changes(apply 없음). 4커밋 전부 라이브.

### 🛡️ 보안 침투점검 + 하드닝 스프린트 [완료/라이브검증] (2026-07-02)

트리거: "내 사이트 털어서 보안검사". 정적 감사(백엔드 2316줄+프론트+terraform+CI) + 비침투 라이브검증 + 의존성 CVE 스캔.

**감사 총평**: 원격 즉시악용 취약점 없음. 인증(bcrypt·JWT token_version·SECRET_KEY fail-closed)·SSRF방어·업로드 매직바이트·이메일 헤더인젝션·IDOR/enumeration·레이트리밋·프론트 XSS(react-markdown 기본차단) 이미 견고. 남아있던 것만 아래로 처리.

**1. multipart DoS 2건 (의존성) — 무인증 악용가능 → 패치·배포**
- CVE-2024-53981(python-multipart<0.0.18): 경계 파싱 per-byte+로그로 이벤트루프 정지. CVE-2024-47874(starlette<0.40.0): filename 없는 폼필드 무제한 버퍼링→OOM.
- 핵심: FastAPI가 `request.form()`(multipart 파싱)을 인증 의존성보다 **먼저** 실행 → `POST /api/upload`에 무토큰 악성 본문만으로 t2.micro DoS 가능(WAF SizeRestrictions는 Count라 통과). 코드리딩만이면 "writer 전용=저위험"으로 넘길 뻔한 걸 버전대조+파싱순서 확인으로 재평가.
- 수정: python-multipart 0.0.12→0.0.18, starlette 0.38.6→0.40.0. **함정**: fastapi 0.115.0이 실제로 starlette<0.39.0을 핀 → fastapi 0.115.14로 같이 올려 해결(pip check 통과). requirements.txt+main.py scp→docker rebuild.

**2. /api/status/history 레이트리밋**: 무인증+DB집계인데 리밋 없어 30/minute 추가(main.py).

**3. CSP 헤더 추가**
- Free 요금제가 커스텀 Response Headers Policy 거부 → CloudFront Function(terraform: csp-function.js + cloudfront.tf, 기본 동작에만 연결)으로 주입.
- 정책: script-src 'self'(빌드 index.html에 인라인 스크립트 0), style/font에 jsdelivr(Pretendard), img https:, connect 'self'. 롤아웃: report-only 배포→콘솔 위반 0건 확인→enforce 전환.

**4. CI OIDC 전환 + 노출 키 삭제 (원래의 #1+#3)**
- 발견: **공개 저장소** PROGRESS.md:351에 배포 IAM 액세스키 ID(AKIA…) 커밋됨(시크릿은 미유출=직접악용X). ec2.tf엔 SSH 허용 IP도 노출.
- 조치: 장기키 재발급 대신 **OIDC 전환**(iam-github-oidc.tf: OIDC 공급자 + 역할 github-actions-blog-deploy + 기존 github-brench 정책 부착; deploy.yml을 role-to-assume + permissions id-token:write로, 시크릿 키 제거). 배포 초록 확인 후 **노출 키 AKIA… 삭제**(유저 키 0개) → 유출 리스크 원천 제거.

**5. CloudFront→EC2 평문(http-only) — 보류(리스크 수용)**
- 오리진 TLS엔 신뢰된 인증서=커스텀 도메인 필수(self-signed·amazonaws.com 불가), 도메인 없음 + ALB는 비용함정 → 보류. 완화책: 8000이 CloudFront prefix-list 전용으로 잠김(직접접속 차단, 라이브 확인). 나중에 도메인 붙일 때 함께.

- **라이브검증(2026-07-02)**: DoS 재배포 후 /api/health·/api/status(backend·db·mail ok) 200; CSP `content-security-policy` enforce 헤더 확인; Actions "Deploy Frontend" success(OIDC, 역할 생성 직후 실행); IAM 키 목록 `[]`.
- **배운 것/함정**: SSH는 AL2023 기본유저 `ec2-user`(ubuntu 아님)·키 `~/.ssh/blog-key.pem`·EC2에 git 없어 배포는 scp. 공개 IaC/개발일지의 대가 = 키ID·SSH IP·계정ID·인프라식별자가 정찰지도가 됨.
- **남은 것**: #4(도메인+오리진TLS), PROGRESS.md:351의 (이미 죽은) 키ID·SSH IP 스크럽, GitHub Secrets의 옛 AWS 키 삭제.

### 🎨 블로그 프론트 리치화 + 본문크기 DoS 방어 [완료/라이브검증] (2026-07-04)

계기: "네이버 블로그 등에 비해 초라하다" → 실측 진단은 '디자인이 못생김'이 아니라 **'텍스트만 있고 비어 보임'**. 채우는 요소를 넣어 해결 + 그 김에 DoS 재점검.

**1. 글 커버 이미지 (백+프론트+마이그레이션)**
- 백엔드: `Post.cover_image`(nullable String500) + 스키마 3종 + 라우터. alembic autogenerate→upgrade(로컬), 프로드는 재빌드 시 `alembic upgrade head` 자동.
- 프론트: 글쓰기에 커버 업로드 칸(기존 `/upload` 재사용), 홈 카드 16:9 썸네일, 상세 2:1 커버. 커버 없으면 제목 이니셜+그라데이션 플레이스홀더로 그리드 안 휑하게.

**2. 홈 2단 레이아웃 (풍성하되 깔끔)**
- 프로필 사이드바(`Sidebar.tsx`): 이니셜 아바타+이름(blog-owner)+소개+구독버튼+글수+최근글 미니리스트.
- 본문 썸네일 2열 그리드(넓으면 3열). 발췌는 마크다운 벗겨(`postUtils.excerpt`), 읽기시간 표시.
- 반응형: 폰=세로스택 / md(768)+=사이드바 옆 / lg=글2열 / 데스크탑 폭 **1280px(max-w-7xl)**. "PC≠모바일" 확실히 구분.

**3. 글쓰기 꾸미기 (서식 툴바 + 미리보기)**
- 무거운 에디터 없이 마크다운을 선택/커서에 삽입: 굵게·기울임·제목·목록·인용·코드·링크·구분선. 미리보기는 글 상세와 같은 ReactMarkdown 재사용.
- 미리보기 중엔 서식버튼 숨김(그땐 편집칸이 없어 버튼이 죽으므로) → "보이면 무조건 먹음". wrap/linePrefix/insertAt 6종 단위검증 통과.

**4. 본문 크기 DoS 방어 (신규 발견→차단)**
- 발견(실측): 무인증 POST에 **7MB 본문 → 422**(본문을 다 버퍼링한 뒤 거부). 요청 크기 제한이 없어 **t2.micro OOM** 가능. 레이트리밋은 본문보다 늦게 돌아 못 막고, WAF는 업로드 위해 SizeRestrictions=Count라 안 막음.
- 조치(이중): ① 앱 미들웨어 — Content-Length>6MB면 버퍼링 전 413. ② **CloudFront Function**(viewer-request, `/api/*`) — 엣지에서 6MB 초과를 EC2 닿기 전에 413(`reqsize-function.js`). 업로드 5MB는 통과.
- 검증: **7MB→413**, 업로드 **64KB만 전송되고 끊김**(=엣지가 원본 전에 차단)·0.22s. 정상 health200·login401 안 깨짐.

- **라이브검증(2026-07-04)**: 프론트 Actions success + 번들 문자열 확인(사이드바·읽기시간·툴바·1280px). 백엔드 재빌드로 cover_image·미들웨어 반영(`/api/posts`에 cover_image, 7MB→413). terraform apply로 CSP·엣지함수·OIDC 반영.
- **배운 것/함정**: FastAPI가 본문(폼/JSON)을 인증·리밋보다 **먼저** 파싱→무인증 DoS 재평가 패턴. DoS는 작은 원본을 지키려면 **엣지에서** 막는 게 정답(CloudFront Function). alembic·앱은 레포 루트 CWD에서 실행해야 `.env`(SECRET_KEY) 로드. react-markdown 기본 새니타이즈라 커버/미리보기 XSS 없음.
- **남은 것(낮음)**: cover_image https 검증, `GET /api/status` SMTP를 백그라운드 캐시로, `GET /api/posts` 목록은 발췌만 반환.

### 🏷️ 코드 하이라이팅 + 태그/카테고리 [완료/라이브검증] (2026-07-11)

일주일 만에 복귀 — 어디까지 했는지 확인 후 "블로그 더 채우기(A)"를 이어감.

**1. 코드 하이라이팅**
- `react-markdown`에 `rehype-highlight` 연결(글 상세 + 글쓰기 미리보기). GitHub-dark 톤 hljs 색을 index.css에(prose 코드블록 배경이 라이트/다크 모두 어두워 하나로 통일).
- 검증: lowlight로 python(`def`→keyword)·bash·json 토큰 색 실동작 확인. 번들 gzip 128→181KB(highlight.js) — 급하면 언어 subset/코드분할로 축소 가능.

**2. 태그/카테고리 (백+프론트)**
- 백엔드: `Post.tags`(Postgres ARRAY(String), server_default '{}') + 스키마 검증(`_clean_tags`: 공백정리·중복제거·빈값제거·최대 10개×30자) + 라우터 `?tag=` 필터(`tags.contains([tag])`, **공개범위 조건과 AND**).
- 프론트: 글쓰기 태그 입력칸(칩 추가/삭제), 홈 카드 태그칩 + 사이드바 태그목록(개수순) + `?tag=` 필터 + "✕ 전체보기", 상세 태그칩.
- 커버 이미지는 이미 작성자 주도(글쓰기 커버 칸)라 새로 만들 것 없음 — 데모 3개만 내가 넣은 플레이스홀더.

**3. 태그 보안검사 + GIN 인덱스**
- SQLi 실측: `?tag=' OR '1'='1`·`'); DROP TABLE posts;--` → 전부 0개(전체 아님)·테이블 멀쩡 = **파라미터화 확인**. 권한우회 없음(필터가 공개범위와 AND). XSS 없음(React 이스케이프). 새 의존성 취약점 0.
- 성능: `tags`에 **GIN 인덱스**(`ix_posts_tags`, `USING gin`) → 태그 필터가 전체스캔 대신 인덱스 스캔. 마이그레이션 자동생성+적용, 프로드 확인.
- highlight.js ReDoS 소지: v11+ 이미 방어 + writer한정 + 클라이언트측 → **리스크 수용(코드 X)**.

- **라이브검증(2026-07-11)**: 프론트 Actions success + 번들에 '전체보기'. 백엔드 재빌드로 `/api/posts`에 tags 필드·`?tag=` 200·GIN 마이그레이션(백엔드 정상 기동=마이그레이션 성공). health·status ok.
- **배운 것**: SQLAlchemy ARRAY `.contains([x])`=`@> ARRAY[x]`(파라미터화). 태그 필터는 반드시 공개범위와 AND해야 IDOR 안 남. GIN 인덱스는 배열 필터를 인덱스 스캔으로. 모델 `__table_args__`에 Index 선언하면 autogenerate가 잡음.
- **남은 것(낮음)**: 진짜 글 콘텐츠 채우기, `GET /api/status` SMTP 캐시, 목록 발췌만 반환.

### ⚙️ 남은 DoS 마무리 + 관리자 인프라 대시보드 + WAF/비용 학습 [완료/라이브검증] (2026-07-12)

**1. status SMTP 캐시** — `/api/status`가 호출마다 SMTP 2초 연결하던 걸, 백그라운드 레코더(1분)가 갱신하는 `_latest` 캐시(`get_latest`)로 교체. 매 호출 SMTP 연결 제거(상태값 최대 1분 지연). TestClient 검증.

**2. 글 목록 발췌만 반환** — `GET /api/posts`가 매 호출 모든 글 본문 전체를 반환(증폭)하던 걸 `PostSummary`(excerpt+reading_minutes, content 없음)로. 서버에서 마크다운 벗긴 발췌+읽기시간 계산, 상세(PostRead)는 본문 유지. 프론트도 PostSummary 타입. 라이브: /api/posts에 content 없음 확인.

**3. 관리자 인프라 대시보드** — /admin 상단에 서버(EC2)+DB 실측 미터(CPU·메모리·디스크·부하 + DB 커넥션), 색(초록/노랑/빨강)·10초 폴링·관리자 전용. psutil(`services/infra.py`) + admin `/infra` 엔드포인트. AWS 권한 추가 불필요(CloudWatch 안 씀=무료). 무인증 401 검증.

**4. WAF 제거 시도 → 학습(원복)** — 비용 줄이려 WAF 떼려다 apply가 400(`pricing plan subscription must have a web ACL`). **CloudFront Free(flat-rate) 요금제**라 WAF가 번들 필수 = 사실상 무료였음(내 "$8/월" 추정 틀림). pay-as-you-go 전환은 오히려 과금 → 원복(web_acl_id 복구). apply 실패라 라이브 무변경.

- **비용 정리**: 프리티어 후 ~$33/월(RDS ~$21 + EC2 ~$12, CloudFront+WAF는 Free 요금제 번들 ~$0). 절약 레버 = 안 쓸 때 EC2·RDS 정지 / RDS를 EC2로 이전.
- **라이브검증(2026-07-12)**: /api/status·/api/posts(발췌)·health 정상, Actions success.
- **⏸️ 오늘 종료 시 EC2·RDS 정지**(비용절감). ⚠️ 재시작 시 EC2 IP/DNS 바뀌므로 **CloudFront 오리진(domain_name) 갱신 필요**(EIP 미사용). EC2=`i-06da19f44d1f38eff`, RDS=`blog-db`.
- **남은 것**: 진짜 콘텐츠 채우기, (선택) CloudWatch 확장, RDS→EC2 이전, 커스텀 도메인.

### 💳 고정 IP + 구독 UI 통합 + 토스 Pro 결제 [완료/라이브검증] (2026-07-15)

07-12의 "재시작 때마다 오리진 갱신" 숙제를 먼저 없애고, 구독 흐름을 정리한 뒤, 그 위에 실제 결제를 얹었다.

**1. EC2 고정 IP(EIP) — 07-12 숙제 해소** ⚠️ **2026-07-17에 되돌림 → 아래 07-17 항목 참고**
- `aws_eip.backend`를 인스턴스에 연결 → 정지/재시작해도 퍼블릭 IP·DNS 고정. CloudFront 오리진 `domain_name`을 하드코딩 대신 `aws_eip.backend.public_dns` 참조로 교체.
- **이제 EC2를 껐다 켜도 오리진 수동 갱신 불필요** = 비용절감(정지)의 유일한 마찰 제거.
- ❌ **당시 적은 "EIP는 붙어있는 동안 무료"는 틀림**(2024-02 이전 기준). 실제로는 ①모든 퍼블릭 IPv4가 시간당 $0.005 과금, ②EIP가 **정지된** 인스턴스에 붙어 있으면 과금 대상. 07-17에 정정.
  - ❌❌ **이때 덧붙인 "EC2 프리티어 12개월 월 750시간 무료라 지금은 $0"도 틀렸다** — 이 계정엔 12개월 프리티어가 아예 없다(크레딧 방식). IPv4는 그때도 실제로 과금 중이었다(7월 `PublicIPv4` $1.53). 아래 07-17 '크레딧' 항목에서 재정정.
- csp-function.js: 토스 결제창 SDK 허용(script/connect/frame/form-action에 `*.tosspayments.com`·`*.toss.im`).

**2. BYOK API 키 형식 검증** — 저장 전 `llm_keys.validate_api_key()`로 검사(실패 시 400). 공통: 공백·탭·개행, 제어문자·비ASCII 차단(통째 붙여넣기 사고 방지). 접두사는 **공개적으로 안정적인 것만** 강제(openai=`sk-`, anthropic=`sk-ant-`, gemini=`AIza`); compatible/cohere는 벤더별 형식이 제각각이라 공통 검증만. 잘못된 키가 Fernet 암호화 저장까지 가지 않음.

**3. 구독 UI를 한 카드로 통합** — '구독 관리'의 두 섹션을 **'구독' 한 카드(로그인 전용)**로 합침.
- 구독 이메일: 내 계정 이메일로 원클릭 구독. **로그인으로 소유가 증명되므로 더블옵트인 생략하고 즉시 confirmed** → 구독 직후 바로 알림 설정 가능(익명 뉴스레터 경로의 더블옵트인은 그대로 유지 = 방어선 안 뚫림).
- 새 글 알림: 글쓴이별 팔로우 토글, **구독 전에는 비활성(잠금)**. 백엔드 `GET/POST/DELETE /subscribers/me` 추가, DB 스키마 변경 없음.
- 함정: `/me` 라우트를 `/{subscriber_id}`보다 **앞에** 둬야 int 캡처와 충돌 안 남.

**4. 토스페이먼츠 Pro 구독 결제 (핵심)**
- 흐름: `/checkout`(서버 주문생성) → 토스 결제창 → 성공 리다이렉트 → `/confirm`(**서버가 토스 승인 API로 검증**) → `is_pro` on + `pro_until = now + PRO_DAYS`(기본 30일, 9,900원).
- 키 분리: 시크릿키는 서버 전용(.env), 클라이언트키는 공개라 `VITE_TOSS_CLIENT_KEY`(Actions Variables)로 주입. 기본값은 토스 공개 테스트 키(실제 청구 없음).
- 안전장치: **`PAYMENTS_REQUIRE_LIVE=true`면 `test_` 키로는 승인 거부** → '공짜 Pro' 사고 차단. 금액 위변조 방지(서버 주문금액과 일치 검사), 남의 주문 차단, 멱등 처리(중복 confirm).
- 만료: `pro_until` 지나면 요청 시 **lazy하게 is_pro 자동 해제**(`_expire_pro_if_due`, 별도 배치 없음). 상위 모델(Opus 4.8·Fable 5)은 is_pro/admin만. Fable 5 refusal(빈 content) 처리 추가.
- 마이그레이션 2개: `payments` 테이블 생성, `users.pro_until` 추가.

**5. 비공개·구독자공개 글 댓글 버그 [fix]** — `fetchComments`/`addComment`가 **Authorization 헤더를 안 보내** 익명 취급 → 댓글 엔드포인트의 `can_view`에서 비공개·구독자공개 글이 404. 글 본문은 `getPost`가 인증을 보내 떠서 **"글은 보이는데 댓글만 안 뜨는"** 증상이었다. 두 호출에 `authHeaders()` 추가.

- **라이브검증(2026-07-15)**: terraform apply로 EIP·오리진·CSP 반영. Actions "Deploy Frontend" success(a0389ac까지). /api/status·/api/posts 200, /api/payments/checkout 무인증 차단, /api/subscribers/me 무인증 401.
- **배운 것/함정**: 결제 검증은 **반드시 서버가 승인 API로** — 클라이언트 성공 리다이렉트는 신뢰 불가(금액·주문자 위변조). 로그인 사용자의 자기 이메일 구독은 소유증명이 이미 됐으니 더블옵트인이 불필요(익명 경로와 정책을 구분). FastAPI 라우트는 **선언 순서**가 매칭 순서(`/me` vs `/{id}`). 인증이 필요한 엔드포인트를 프론트에서 놓치면 **404로 보여 권한버그가 '데이터 없음'처럼 위장**된다.
- **⏸️ 종료 시 EC2·RDS 정지 완료**. ✅ EIP 덕에 **재시작해도 오리진 갱신 불필요**(07-12 경고 해소). EC2=`i-06da19f44d1f38eff`, RDS=`blog-db`. → **07-17에 EIP 제거로 이 항목 무효**, 오리진 갱신이 다시 필요해짐.
- **남은 것**: 진짜 콘텐츠 채우기, 실결제 전환 시 `PAYMENTS_REQUIRE_LIVE=true`+라이브 키 교체, (선택) CloudWatch 확장, RDS→EC2 이전, 커스텀 도메인.

### 🧹 개발일지 백필 + EIP 제거(오리진 주차로 dangling 차단) [완료/라이브검증] (2026-07-17)

이틀 만에 복귀 — "뭐 하려 했지?" 확인부터. 07-15 작업은 전부 커밋·배포됐는데 **문서화만 빠져 있었다**.

**1. 개발일지 백필 + 죽은 경로 수정**
- 07-15 PROGRESS 항목 작성 + 개발일지 생성. 그러다 **07-12 개발일지가 아예 없던 것**을 발견.
- 원인: `scripts/make_devlog_*.py`가 `/home/es0764/blog-platform`(현재는 `blog_plafrom`)과 `/mnt/c/Users/erert`(현재는 `USER`)에 저장 → **저장 단계에서 실패**. 두 경로 모두 존재하지 않음. 07-12 스크립트 경로 수정 후 재생성, 07-15 스크립트는 올바른 경로로 신규 작성.
- 이 환경엔 python-docx도 pip도 없어짐(옛 폴더의 venv와 함께 사라짐) → 스크래치패드에 venv 부트스트랩해서 생성. **다음에 일지 만들 땐 같은 부트스트랩 필요**.

**2. 정지 상태 점검** — EC2·RDS 둘 다 `stopped` 확인. Cost Explorer 실측 **이번 달 $0**. ❌ **여기 적은 "(전부 프리티어)"는 틀렸다** — 프리티어가 아니라 **크레딧이 상계**한 $0이었다(실사용액은 7월 $16.10). 아래 07-17 '크레딧' 항목에서 정정. ⚠️ **RDS는 정지 7일 후 자동 재시작**(AWS 정책) → 07-15 정지 기준 **~07-22에 스스로 올라옴**. 계속 꺼두려면 그때 재정지 필요.

**3. EIP 제거 + 오리진 주차 (핵심)**
- 07-15에 붙인 EIP를 제거. **동기는 비용이 아님**(❌ 근거로 적은 "프리티어 중 $0"은 틀림 — 실제로는 `PublicIPv4:IdleAddress`로 과금 중이었고 크레딧이 가리고 있었다. 결과적으로 제거가 비용에도 이득이었던 셈). 다만 제거하면서 **dangling origin** 위험이 드러남.
- **위험**: EIP를 놓으면 IP가 AWS 풀로 반납 → 다른 고객에게 배정 가능. 그런데 오리진은 `ec2-<IP>.compute.amazonaws.com` 형태고 이 이름은 **규칙상 항상 그 IP로 resolve**된다. 즉 EC2 정지 중 `/api/*` 요청이 **그 IP를 새로 받은 제3자에게 전달**된다(Authorization 헤더·로그인 토큰 포함). **07-15 이전 구성(하드코딩 dynamic IP)에도 있던 구멍** — EIP가 우연히 막고 있었을 뿐.
- **조치**: 오리진 주소를 `var.backend_origin_dns`로 분리(`terraform/variables.tf`). **비우면(기본값=정지 상태) 우리가 소유한 S3 도메인으로 '주차'** → 거기엔 8000 포트가 없어 연결 자체가 실패 = **fail closed**. 형식 validation으로 오타·IP 입력 차단.
- 부수 효과: EC2가 꺼져 있어도 apply가 되므로(주차 주소가 항상 유효) **EC2를 켜지 않고 EIP 제거를 끝냄**.
- **운영 절차(중요)**: EC2 켤 때 `terraform apply -var="backend_origin_dns=$(aws ec2 describe-instances --instance-ids i-06da19f44d1f38eff --query 'Reservations[0].Instances[0].PublicDnsName' --output text)"` / 끌 때 `terraform apply`(기본값 → 주차). **끌 때 주차를 빠뜨리면 위 구멍이 열린다.**

- **라이브검증(2026-07-17)**: apply = 1 destroyed(EIP) + 1 changed(CloudFront). `describe-addresses` **EIP 0개**, EC2 퍼블릭 IP `None`(stopped). 프론트 홈 **200** 정상. `/api/status`는 **504**(30s, 연결 3회 실패) = 주차가 fail closed로 동작.
- **배운 것**: 클라우드에서 IP를 놓는다는 건 **그 주소를 남에게 넘긴다**는 뜻 — 그걸 가리키는 설정(CDN 오리진, DNS 레코드)을 같이 정리 안 하면 dangling이 된다. `ec2-<IP>.compute.amazonaws.com`은 소유권과 무관하게 IP로 resolve되므로 "내 호스트명이니 안전"이 성립하지 않는다. 근본 해결은 **내가 소유한 도메인**(Route53) — 지금 남은 항목의 '커스텀 도메인'이 이 문제도 같이 푼다.
- **남은 것**: 진짜 콘텐츠 채우기, **RDS 자동 재시작(~07-22) 대응**, 커스텀 도메인(+오리진 TLS, dangling 근본해결), 실결제 전환, RDS→EC2 이전.

### 📚 개발일지 14편을 블로그 글로 발행 [완료/라이브검증] (2026-07-17)

07-04부터 세 번 연속 "남은 것"에만 있던 **'진짜 콘텐츠 채우기'를 해결**. 새로 쓸 필요가 없었다 — 쓸 콘텐츠가 이미 개발일지 14편으로 있었고, 그걸 "블로그 만들기 #1~#14" 연재로 옮겼다.

- `scripts/devlog_to_markdown.py`: docx → 마크다운. python-docx로 만든 문단 구조를 되돌린다(Heading→`##`, List Bullet→`-`, 🔎 비유/🛠 전문가 노트→인용문, `field()`→`**라벨** — 내용`). 표지 형식이 3종(06-21 옛 형식 / 06-22·06-24 중간 / 07-11+ 현재)이라 전부 처리. 제목·태그는 자동 추출 대신 `POSTS` 맵에 직접 지정 — 옛 3편엔 `주제:` 줄이 없고, 있는 편들도 제목으로 쓰기엔 너무 길다.
- `scripts/publish_devlogs.py`: **EC2 백엔드 컨테이너 안에서 실행**. RDS가 퍼블릭이 아니라 EC2에서만 닿고 컨테이너엔 이미 DB 자격증명이 있어 **계정 비밀번호 없이** 발행된다. `PostCreate`로 앱과 같은 검증을 태우고, `created_at`을 실제 작업일로 소급(API는 서버가 `now()`로 채워 소급 불가). **제목 기준 멱등** — 재실행하면 갱신만.
- **라이브검증(2026-07-17)**: 생성 14건. DB 전체 24개(기존 10 + 신규 14), public 21, `개발일지` 태그 14. `/api/posts`에 날짜(06-21~07-15)·태그 정상, 상세 본문 마크다운 온전.
- **부수 성과**: EIP 제거 후 **오리진 갱신 절차의 첫 실전 검증** — EC2가 새 주소(15.165.204.91)를 받았고 `terraform apply -var=...` 한 번으로 갱신돼 health 200. 절차가 동작함을 확인.
- **배운 것**: 콘텐츠가 없다고 생각했지만 이미 있었다 — 만드는 과정 자체가 콘텐츠. python은 스크립트가 있는 디렉터리를 `sys.path`에 넣지 cwd를 넣지 않는다(`-w /app`만으론 부족, `PYTHONPATH=/app` 필요).
- **남은 것(낮음)**: 커버 이미지 14편 (지금은 제목 이니셜 플레이스홀더).

### 🔍 글 검색(pg_trgm) + 목록 페이지네이션 [완료/라이브검증] (2026-07-17)

글이 24개가 됐는데 검색이 없었고(필터는 `?tag=` 하나), 목록은 `limit`도 `offset`도 없이 매번 전체를 반환했다. **07-12의 '본문 전체→발췌만'은 절반만 끝난 작업이었다** — 글 개수 자체가 무제한이라 응답이 계속 커진다.

**1. 검색** — 한국어는 `to_tsvector`가 형태소를 몰라 풀텍스트가 사실상 안 먹는다('블로그'로 '블로그를'이 안 잡힘) → **pg_trgm + ILIKE**, title·content에 `gin_trgm_ops` GIN 인덱스(마이그레이션 `e33a24b1fedd`). LIKE 메타문자(`%`·`_`·`\`) 이스케이프 — 안 하면 `q=%`가 전체매칭, `q=%%%%%`가 무거운 스캔. `q`는 min_length=2(1글자는 trigram 인덱스를 못 타 seq scan).

**2. 페이지네이션** — `limit`(기본 10, **상한 50**)·`offset`. 응답을 `{items,total,limit,offset}` 봉투로 변경.

**3. `GET /api/posts/meta` 신설** — 사이드바가 **전체 목록으로** 태그·글 수·최근글을 세고 있어서, 페이지로 끊으면 2쪽에서 "10개의 글"로 쪼그라든다 → 집계를 서버로 분리. 라우트는 **`/{post_id}`보다 위에** (아래면 'meta'를 int로 파싱하려다 422 — 07-15 `/subscribers/me`와 같은 함정).

**4. 공개범위 조건을 `visible_condition()`으로 추출** — 목록·검색·메타가 각자 만들면 한쪽만 고쳐져 비공개 글이 샌다. 필터는 전부 이 조건과 **AND**.

- **로컬검증(개발일지 14편 시드)**: 페이지 10+4, 한글검색 '토스'1·'검은 화면'2, 검색+태그 7. 방어: `q=%%`→0건, 1글자→422, `limit=999999`→422, `offset=-1`→422. **SQLi `' OR '1'='1`→전체가 아니라 그 문자열을 담은 1건**(하필 #12 SQL인젝션 편 😄 = 파라미터 바인딩 증거). 유출: 익명이 private·subscribers 검색시 0건, 관리자는 2건 / meta total 14 vs 16. `EXPLAIN`으로 trgm 인덱스 Bitmap Index Scan 확인.
- **배운 것/함정**: ⚠️ **마이그레이션 리비전 ID를 손으로 짓다 기존 `a1b2c3d4e5f6`(add_is_pro)과 충돌** → alembic "Cycle detected"로 백엔드 기동 거부. 로컬에서 안 돌렸으면 프로드가 죽었다. **반드시 `alembic revision`이 생성하게 할 것.** / SQLAlchemy는 연결 전 `_backslash_escapes=True`라 `ESCAPE '\\'`로 보이지만, 서버의 `standard_conforming_strings`를 보고 연결 시 고친다 = **컴파일 검증만으론 못 보는 것이 있다**.
- **⚠️ 배포 순서(중요)**: `git push` = **프론트만** 자동 배포. 프론트가 먼저 가면 새 프론트가 옛 백엔드의 없는 `/api/posts/meta`를 불러 **사이드바가 빈다**(목록은 배열 호환 처리해둬서 안 깨짐). → **백엔드 배포(재빌드=마이그레이션 자동) 먼저, 그다음 push.**
- **라이브검증(2026-07-17)**: 배포 완료. 페이지네이션 `offset=0`→10건·`offset=20`→1건(total 21). 한글검색 '토스'1·'검은 화면'2, 검색+태그(`q=블로그&tag=개발일지`) 14. 방어 4종 전부 로컬과 동일(`q=%%`→0건, 1글자·`limit=999999`·`offset=-1`→422). **SQLi `' OR '1'='1`→프로드에서도 1건**. 유출: 익명 `meta.total` 21 == `posts.total` 21(DB 24 중 public 21) = 비공개 안 샘.
- **남은 것**: UI 클릭 검증(브라우저 자동화 없어 눈으로).

### 📖 연재(시리즈) 네비 + 글 목차 [완료/라이브검증] (2026-07-17)

방금 올린 개발일지 14편이 연재인데 **#7에서 #8로 갈 길이 없었고**, 긴 글에 `##` 소제목이 많은데 목차가 없었다. 콘텐츠를 채우고 나니 비로소 보이는 구멍 — 글이 10개일 땐 없던 문제다.

**1. 연재 모델링** — `Post.series`(nullable varchar(100), 인덱스, 마이그레이션 `51cafb80733f`). 같은 값이면 한 시리즈, **순서는 `created_at`**.
- **제목의 '#7'을 파싱하지 않는 이유**: 제목을 고치면 순서가 깨지고, 번호를 손으로 붙여야 한다.
- **태그를 겸용하지 않는 이유**: 분류와 연재는 다른 개념이라 섞으면 '어떤 태그가 연재인가'를 또 정해야 한다.
- **빈 문자열은 None으로 정규화** — 안 그러면 `''`인 글끼리 '이름 없는 연재'로 묶인다.

**2. `GET /posts/{id}/series` → `SeriesNav | null`** — 목록은 **`visible_condition`으로 거른다**(안 그러면 남의 비공개 글 제목이 네비로 샌다). 그래서 `index`/`total`은 **'보는 사람 기준'**이다. 상한 100편. **상세 응답에 안 넣고 별도 엔드포인트로 둔 이유**: 연재 아닌 글이 대부분인데 매 상세 조회에 연재 질의를 얹을 이유가 없다.

**3. 목차** — `rehype-slug` 추가 → 렌더된 소제목에 id가 붙고 `#앵커`가 거기로 점프. Toc이 본문에서 `##`/`###` 추출(코드블록 안 `#` 제외, `**강조**` 제거, 중복 제목은 `-1`/`-2` = github-slugger와 같은 규칙). 소제목 2개 미만이면 안 그린다.

- **로컬검증**: 개발일지 14편 backfill → #1 prev=null, #8은 7/9 사이, #14 next=null. #3을 비공개로 돌리니 익명에겐 13편이 되고 #4의 이전 편이 #2로 이어짐(=제목 안 샘). 목차 id: 소제목 **171개를 실물 github-slugger와 대조해 불일치 0**.
- **라이브검증(2026-07-17)**: 배포 완료(백엔드 → push 순서 지킴). `/posts/25/series` = `블로그 만들기` **14편, index 14/14**, 첫 편(id 12) **index 1/14** = 경계 정상. 연재 아닌 글(id 11)은 **`null` + HTTP 200**. 프론트 번들(14:10:54, 커밋 14:03:46 이후)에 연재·목차 코드 포함 확인.
- **배운 것**: 순서의 근거를 **어디에 두느냐**가 설계다 — 제목(사람이 고침)·태그(용도가 겹침) 대신 전용 컬럼 + `created_at`을 고른 건 "무엇이 안 변하는가"를 고른 것. / 권한 필터를 네비에도 **똑같이** 태워야 한다: 목록에서 막고 네비에서 안 막으면 **제목만 새는 경로**가 생긴다.
- **남은 것**: 커버 이미지 14편(제목 이니셜 플레이스홀더), UI 클릭 검증.

### 🔌 발행 작업 후 정지 (주차 → 정지 순서 첫 적용) [완료/라이브검증] (2026-07-17)

개발일지 발행하느라 켠 EC2·RDS가 그대로 돌고 있었다. 07-15에 만든 운영 절차를 **끄는 방향으로 처음** 밟았다.

- **순서가 절차다**: `terraform apply`(기본값 → 주차) **먼저**, 그다음 정지. 반대로 하면 EC2가 멎어 IP가 반납된 뒤에도 오리진이 옛 `ec2-<IP>...`를 가리키는 **틈**이 생긴다 — 그 사이 `/api/*`는 그 IP를 새로 받은 제3자에게 간다. 절차 문서엔 "끌 때 주차"라고만 적혀 있었는데, **주차가 정지보다 먼저여야 한다**는 게 핵심이다.
- **라이브검증(2026-07-17)**: apply = 1 changed(오리진 → `blogplafromops.s3...`). 정지 후 EC2 `stopped`·PublicIp `null`, EIP **0개**. 프론트 홈 **200**, `/api/status` **504(30s)** = 주차가 fail closed로 동작(07-15 검증과 동일한 값).
- ⚠️ **EC2 IP가 또 바뀌었다**: 15.165.204.91 → **54.180.105.7**. 기록해둔 IP는 켤 때마다 무의미해진다 = **문서에 IP를 적지 말 것**, 절차의 `describe-instances` 한 줄이 유일한 출처다. (오리진은 이미 새 IP로 갱신돼 있어 dangling은 아니었다.)
- ⚠️ **RDS 자동 재시작**: **07-17 정지 기준 ~07-24에 스스로 올라온다**(7일 정책). 그때 재정지 필요 — 07-15 기준 ~07-22 메모는 이 정지로 갱신됨.
- **배운 것**: 절차를 문서로 적어두는 것과 **순서까지 적어두는 것**은 다르다. "끌 때 주차"는 두 가지로 읽히는데 그중 하나만 안전하다.

### 💸 "$0의 정체" — 프리티어가 아니라 크레딧이었다 + RDS 자동정지 Lambda [완료/라이브검증] (2026-07-17)

`~07-24 RDS 재시작 리마인더`를 걸려다 **6월부터 믿어온 비용 모델이 통째로 틀렸다는 걸 발견**했다. 리마인더가 필요한지 확인하려고 프리티어 한도를 조회한 게 시작이었다.

**1. 이 계정엔 12개월 프리티어가 없다.**
```
accountPlanType: PAID / accountPlanStatus: ACTIVE
aws freetier get-free-tier-usage → "Always Free" 4건(Glue·SQS·SNS·KMS)뿐. EC2·RDS 없음.
```
- **크레딧은 4개짜리 묶음이다** (전부 2027-06-24 만료):

  | 크레딧 | 금액 | 사용 | 남음 | 발급 |
  |---|---|---|---|---|
  | **AWS Free Tier** | $100 | **$24.90** | **$75.10** | 06-24 |
  | Explore: Cost budget | $20 | $0.00 | $20.00 | 06-24 |
  | Explore: Aurora/RDS | $20 | $0.00 | $20.00 | 06-24 |
  | Explore: Lambda web app | $20 | $0.00 | $20.00 | **07-17** |

- `$75.10 + $60 = $135.10` = **`accountPlanRemainingCredits`와 정확히 일치**. ❌ **"API가 잔액이 아니다"라고 적었던 건 틀렸다** — API는 **전체 크레딧 합계**로 정확했고, 합산 대상(Explore 크레딧 3개)을 몰랐을 뿐이다. 한 시간 만에 $115.10 → $135.10으로 오른 것도 실제였다: **자동정지 Lambda를 만든 게 "Explore AWS: Create a web app using AWS Lambda" 과제로 잡혀 $20이 발급**됐다(발급일 07-17). 월 $16 지키려 만든 Lambda가 $20을 벌었다.
- ⚠️ **$60은 쓸 수 있는지 미확인.** 세 Explore 크레딧이 전부 `$0.00 사용`이다 — RDS가 6~7월 내내 돌며 $12+ 썼는데도 "Create an Aurora or **RDS** database" 크레딧이 안 깎였다. **적용 대상 서비스가 제한돼 있을 가능성**(콘솔 '전체 서비스 목록 보기'로 확인 필요). **실제로 깎이는 건 $100짜리 Free Tier 하나뿐**이므로 계획은 **$75.10 기준**으로 세운다.
- `$24.90` 사용액은 저희 실측(6월 $7.72 + 7월 $16.10 = $23.82, + 07-17 검증 테스트분)과 맞는다 = 이 숫자는 믿을 수 있다.
- 06-21부터 청구서에 찍힌 **$0는 무료라서가 아니라 크레딧이 상계한 결과**였다. `RECORD_TYPE`으로 쪼개니 **Usage와 Credit이 정확히 같은 값으로 상쇄**되고 있었다 — 6월 $7.72, 7월(1~18일) **$16.10**. 이미 **$23.82를 태웠다**.
- **왜 못 봤나**: Cost Explorer를 서비스별 `UnblendedCost`로만 봤는데, 그 뷰는 Usage와 Credit이 netting돼서 전부 $0으로 보인다. **`RECORD_TYPE` 차원으로 나눠야 진짜 사용액이 보인다.** "청구서가 $0"과 "안 쓰고 있다"는 전혀 다른 말이다.

**2. 어디서 나가고 있었나 (7월 1~18일 실사용액 $16.10)** — 정지하면 멈추는 것과 계속 나가는 것이 갈린다.

| UsageType | 18일 | 정지하면 |
|---|---|---|
| `InstanceUsage:db.t3.micro` | $8.15 | 멈춤 |
| `BoxUsage:t2.micro` | $4.19 | 멈춤 |
| `PublicIPv4:InUse`+`Idle` | $1.53 | 멈춤 |
| `RDS:GP2-Storage` (20GB) | $1.31 | **계속** |
| `EBS:VolumeUsage.gp3` (20GB) | $0.91 | **계속** |

- **크레딧 수명 ($135.10 / 2027-06-24 만료 기준 — Explore $60 유효 확정, 07-18)** — **뭐가 먼저 바닥나는지가 사용 패턴에 따라 뒤바뀐다**:
  - **정지 유지**(월 ~$3.7, 스토리지만): 만료일까지 ~$42만 쓰고 **~$93이 남은 채 소멸**. → 제약은 **만료일**이지 잔액이 아니다.
  - **24/7 가동**(월 ~$32): **4.2개월 = ~2026-11-22에 소진**. → 제약은 **잔액**.
  - (07-18 콘솔 확인으로 Explore $60이 EC2·RDS에 적용됨을 확정 → $75.10 기준 2.3개월이 아니라 $135.10 기준 4.2개월이 계획값이 됐다.)
- 🔑 **크레딧은 use-it-or-lose-it이다.** 2027-06-24에 사라지므로 **안 쓰고 남기는 데 이득이 없다.** "아껴서 오래 버티기"는 목표가 아니다 — 어차피 소멸할 ~$93을 지키느라 블로그를 못 띄우면 손해다. 진짜 목표는 **낭비(아무도 안 쓰는데 도는 것)만 없애고, 쓸 거면 만료 전에 쓰는 것**.
- `PAID` 플랜이라 **크레딧이 0이 되거나 만료되는 순간 카드로 진짜 청구가 시작된다.** 만료 후엔 전부 꺼둬도 스토리지로 월 ~$3.7이 실청구된다(그게 바닥값).
- 07-12에 적어둔 "프리티어 후 ~$33/월" 추정은 금액은 맞았다. 틀린 건 **"프리티어 후"** — 이미 그 요금이 나가는 중이었다.

**3. 그래서 RDS 자동정지 Lambda** (`terraform/rds-autostop.tf`, `terraform/lambda/rds_autostop.py`)
- **판단 기준 = 'EC2가 stopped인가'**. RDS는 `publicly_accessible=false`라 EC2에서만 닿는다 → **EC2가 꺼진 채 도는 RDS는 정의상 아무도 못 쓴다** = 켤 이유가 없다. 태그 스위치나 유예시간이 필요 없다 — **EC2 상태가 곧 '쓰는 중인가'의 답**이라 사람이 뭘 기억 안 해도 작업 중엔 안 꺼진다. 과도상태(`pending`/`stopping`)엔 손대지 않는다(애매하면 아무것도 안 함).
- **EC2를 대상에서 뺀 이유**: EC2를 끄려면 오리진 주차(`terraform apply`)가 **먼저** 와야 하는데 Lambda는 terraform을 못 돌린다 → 주차 없이 IP만 반납되어 **dangling origin이 열린다**. 막으려던 구멍을 자동화가 여는 셈이라 EC2 정지는 사람 손에 남겼다.
- EventBridge Scheduler `rate(1 hour)` → Lambda. 쓰기 권한은 `rds:StopDBInstance` **이 DB 하나로만** 좁혔다(역할이 탈취돼도 blog-db를 끄는 것 외엔 못 함). 로그 그룹을 terraform이 명시 생성 + 14일 보관 — 안 그러면 Lambda가 자동 생성하면서 **무기한 보관**이 된다.
- **비용**: 월 ~730회. Lambda+Scheduler 정가로도 **월 $0.001 미만**. 지키는 건 **월 $16**.

- **라이브검증(2026-07-17)**: apply 7 added / 기존 리소스 변경 0. 세 경로를 실제로 태움 —
  ① 둘 다 stopped → `skip(rds_not_available)`.
  ② **EC2 running + RDS available → `skip(ec2_not_stopped)`, RDS는 available 유지** = 작업 중 안 끔(안전 경로).
  ③ **EC2 stopped + RDS available(=07-24 재현) → `stopped`, RDS가 실제로 `stopping`으로 전환** = 핵심 경로.
  ④ 스케줄러 자율 호출: 주기를 1분으로 임시 변경 → **사람이 부르지 않았는데 2회 실행** 확인(Scheduler→Lambda IAM 역할 검증) → `terraform apply`로 `rate(1 hour)` 복원(드리프트 감지·정정도 확인).
- **배운 것**: **"$0"을 근거로 삼을 땐 왜 $0인지를 물어야 한다.** 무료여서 $0인 것과 누가 대신 내줘서 $0인 것은 남은 시간이 다르다 — 전자는 무한, 후자는 $115.10/월$32 = 3.6개월이었다. 한 달을 "$0이니까 괜찮다"고 믿고 지냈다. / **검증 안 된 자동화는 없느니만 못하다** — 껐다고 믿게 만들기 때문이다. 그래서 Lambda를 직접 호출해보는 데서 멈추지 않고 **스케줄러가 스스로 부르는 것까지** 확인했다. 여기가 끊겨 있으면 조용히 아무 일도 안 일어난다.
- **남은 것**: **RDS→EC2 이전** — 기한이 **2027-06-24**(크레딧 만료 = 실청구 시작)로 확정됐다. 이전하면 만료 후 바닥값이 월 ~$3.7 → EBS만(~$1.6)로 떨어지고 RDS 인스턴스비($16)가 통째로 사라진다. 실결제 전환, 커스텀 도메인.
- **판단 보류**: 블로그를 언제 실제로 띄울지. 24/7이면 크레딧이 4.2개월(~11-22)이지만, 안 쓰면 ~$93은 그냥 소멸한다. **"켜두면 아깝다"가 아니라 "안 켜도 아깝다"**가 맞는 프레임.
- **확인함 (2026-07-18)**: Explore 크레딧 3개($60)의 **적용 대상 서비스 목록에 EC2·RDS 둘 다 있음** (콘솔 → Billing → Credits → '전체 서비스 목록 보기'). → **$60 유효 확정**, 24/7 수명 2.3 → **4.2개월(~11-22)**로 갱신(위 '크레딧 수명' 반영).
  - CLI 뒷받침: `ce get-cost-and-usage`(RECORD_TYPE=Credit, 서비스별)로 7월 크레딧이 실제 **RDS -$9.49 / EC2 Compute -$4.19 / VPC -$1.57 / EC2-Other -$0.93**에 붙어 Usage $16.19를 정확히 상계 중임을 확인. 단 CLI는 **4개 크레딧 풀 중 어느 것**인지는 구분 못 함(그래서 콘솔 목록이 결정적) — 6월부터 실제로 깎인 건 $100 Free Tier뿐이고 Explore $60은 그 소진 후 이어받는 예비분.
- **배운 것(추가)**: **숫자가 안 맞을 때 "이 소스는 틀렸다"고 결론내는 게 제일 위험하다.** API($135.10)와 콘솔($75)이 안 맞자 API를 불신했는데, 실제론 **둘 다 맞고 세는 대상이 달랐다**(합계 vs 개별 크레딧). 불일치는 보통 '누가 틀렸나'가 아니라 **'무엇을 세고 있나'**의 문제다.

### 🏗️ RDS → EC2 이전 (self-hosted Postgres 컨테이너) [완료/라이브검증] (2026-07-18)

가장 큰 비용 덩어리였던 **RDS(`db.t3.micro`, 월 ~$16)를 없애고** Postgres를 EC2 안 Docker 컨테이너로 옮겼다. 로컬 개발은 원래 `docker-compose.yml`에서 `db`(postgres:16-alpine)를 쓰고 있었으니, 프로덕션도 같은 패턴으로 통일한 것 — **backend 코드 변경 0, `DATABASE_URL`만 바뀐다.**

- **왜**: 크레딧 만료(2027-06-24 = 실청구 시작)가 확정된 상황에서 만료 후 바닥값을 낮추는 게 핵심. 이전으로 **월 $16(RDS 인스턴스비)이 통째로 사라지고**, 만료 후 바닥값이 **월 ~$3.7(RDS 스토리지 포함) → ~$1.6(EBS만)**로 떨어진다. 가동 중일 때도 RDS 사용액이 0이 된다.
- **아키텍처**: `CloudFront ─/api/*→ EC2(backend + db 컨테이너, 같은 compose 네트워크) → pgdata(EBS 볼륨)`. **db 포트는 호스트에 노출 안 함** — backend가 compose 네트워크로 `db:5432`에 접속하므로 VPC에 열린 DB 포트가 아예 없다(RDS보다도 단순·안전). 비번은 `.env`의 `DB_PASSWORD`로 compose가 치환(컨테이너 내부 전용, openssl 랜덤).
- **데이터 이전(라이브)**: EC2·RDS 둘 다 start → **수동 스냅샷 `blog-db-pre-migration-2026-07-18`(안전망)** → EC2에서 `postgres:16-alpine` 컨테이너로 RDS를 `pg_dump`(28214줄/1.3MB, 시크릿은 argv 아닌 env로 전달) → 새 db 컨테이너에 `psql` 복원 → backend를 새 `.env`로 `--force-recreate`. 복원 시 에러 0.
- **검증**: 이전 **전** RDS 기준값(posts 24, subscribers 4)을 먼저 떠두고 대조 —
  - db 컨테이너 직접: posts 24 / subscribers 4 / users 5 / comments 4 / payments 2 / **alembic=51cafb80733f(head)** = 전부 일치, 복원 완전.
  - 앱 레벨: backend `/api/status` → `database:ok, stats:{posts:24, subscribers:4}` = RDS 시절과 동일.
  - 메모리: postgres+backend 동시 구동에도 available 487MB(t2.micro 1GB) + **스왑 2GB 추가**(안전망). 여유 있음.
- **RDS·autostop Lambda 해체**: `rds.tf`·`rds-autostop.tf`·`lambda/rds_autostop.py` 삭제 + `ec2.tf` default SG의 5432 ingress 제거 → **`terraform plan`으로 destroy 범위가 RDS 1개 + autostop 세트 7개 + SG 규칙뿐**(EC2/CloudFront/S3 무손상)임을 육안 확인 후 apply(0 added / 1 changed / 8 destroyed). RDS는 `skip_final_snapshot=true`라 위 수동 스냅샷이 유일한 롤백 경로. **autostop Lambda는 존재 이유(정지 RDS의 7일 자동 부활 방지)가 RDS와 함께 사라져 은퇴** — 지켜야 할 게 없어졌다.
- **백업(내구성 대체)**: RDS 자동 일일 백업·PITR이 사라진 자리를 **일일 `pg_dump→S3` cron**으로 메꿈. `terraform/db-backup.tf` = 비공개 버킷 `blog-db-backups-181568979775`(30일 lifecycle) + EC2 **IAM 인스턴스 프로파일**(`s3:PutObject` 이 버킷 `/*`로만 한정 — autostop이 StopDBInstance 하나로 좁힌 것과 같은 원칙). EC2 root 크론(매일 18:00 UTC) + `/usr/local/bin/blog-db-backup.sh`. 즉시 1회 실행 → **S3에 `blog-2026-07-18-0322.sql.gz`(315KiB) 실제 생성 확인**. 백업은 **EC2가 켜진 동안만** 도는데, DB가 바뀌는 것도 EC2 켜졌을 때뿐이라 의미상 정확하다.
- **배운 것**: **"옮겼다"의 증거는 목적지에 데이터가 있는 게 아니라 출발지 값과 목적지 값이 같다는 것이다.** 그래서 지우기 전에 원본 카운트를 먼저 떠뒀다 — 이게 없으면 "24개 있네" 는 "원래 몇 개였지?"에 답을 못 한다. / **자동화는 이유가 사라지면 짐이 된다.** autostop Lambda는 잘 만들었지만 RDS가 없으면 지킬 대상이 없다 — 남겨두면 "왜 있지?"를 언젠가 다시 물어야 하는 코드일 뿐이라 같이 지웠다. / DB 포트를 아예 노출 안 하니 RDS 시절의 SG 5432 규칙·publicly_accessible 고민 자체가 사라졌다 — **가장 안전한 포트는 열지 않은 포트다.**
- **남은 것**: 스냅샷 `blog-db-pre-migration-2026-07-18`은 며칠 롤백 안전망으로 보관 후 삭제(스토리지 소액). (선택) CloudFront 경유 라이브 e2e는 이번엔 생략 — 이 이전이 바꾼 표면은 DB 연결뿐이고 그건 `/api/status`(database:ok)로 직접 검증됨, CloudFront→EC2 오리진 경로는 무변경. (커스텀 도메인·실결제 전환은 '남은 일'에서 제외 — 아래 '로드맵 정리' 참고.)

### 🧭 로드맵 정리: 커스텀 도메인·실결제 전환은 '제약 보류'로 확정 (2026-07-18)

06-24부터 거의 모든 일지의 "남은 것"에 붙어다니던 **커스텀 도메인**과 **실결제 전환**을 로드맵에서 내렸다. 둘 다 내가 코드로 풀 문제가 아니라 **사업/비용 결정**이라, "다음 할 일"에 남겨두면 영원히 미완료로 보일 뿐이다.

- **실결제 전환 — 못 하는 게 아니라 자격 밖이다.** 토스페이먼츠 실결제 계약은 **사업자등록번호가 필수**다. 개인 포트폴리오로는 넘을 수 없는 벽 = 돈이 아니라 자격의 문제. 하지만 이미 만든 **샌드박스 결제 연동(승인검증 → Pro 해금)이 그 자체로 완성품**이다. "결제 붙일 줄 안다"를 보여주는 목적은 달성됐고, 실사업자 전환은 블로그를 *장사*로 돌릴 때의 얘기다. → **안 한다(자격 제약).**
- **커스텀 도메인 — 안 하는 게 합리적이다.** 도메인 ~$12/년 + Route53 호스티드존 $6/년 ≈ **연 $18의 실청구**. 크레딧 아끼자고 RDS까지 들어낸 마당에 굳이 쓸 돈이 아니다. 게다가 `d2j66m9udyg9yq.cloudfront.net`이 **이미 HTTPS로 정상 동작**해 기능상 아쉬울 게 없다. (과거 일지의 'dangling origin 근본해결=커스텀 도메인'도, 지금은 오리진 주차로 fail-closed가 걸려 있어 급하지 않다.) → **보류(비용 결정). 원하면 그때 연 $18을 결정.**
- **배운 것**: **로드맵의 "남은 것"과 "안 하기로 한 것"은 다르다.** 안 할 일을 남은 일 칸에 두면 매번 "이거 왜 안 했지?"를 다시 묻게 된다. 제약(자격·비용)으로 막힌 건 미루는 게 아니라 **명시적으로 내려놓고 이유를 적어두는** 게 맞다 — 그래야 "남은 것"이 진짜 할 수 있는 일만 남는다.
- **그래서 실제로 남은(할 수 있는) 것**: AI 초안 e2e(키 충전), 테스트/CI 보강, 블로그에 진짜 글 쓰기.

### 🧪 테스트 + CI 보강 [완료/로컬 그린] (2026-07-18)

지금껏 검증이 전부 수동(curl·눈)이었다. 리팩터링이나 배포가 조용히 뭘 깨도 잡아줄 그물이 없었으니, **backend 통합 테스트 + PR 게이트 CI**를 깔았다.

- **왜 실제 Postgres인가(SQLite 아님)**: `posts.tags`가 `ARRAY(String)`이고 검색이 `pg_trgm`(GIN, `gin_trgm_ops`) 인덱스라 **SQLite로는 `create_all`조차 안 된다.** 그래서 테스트도 프로드와 같은 Postgres를 쓴다 — 로컬은 `blog_test` DB(dev `blog`과 분리 → 오염 없음), CI는 postgres 서비스 컨테이너. conftest가 `pg_trgm` 확장 생성 후 `Base.metadata.create_all`.
- **격리**: 테스트마다 커넥션 1개에 트랜잭션을 열고 끝나면 통째 롤백. 앱이 내부에서 `commit()`해도 `join_transaction_mode="create_savepoint"`로 savepoint에 잡혀 롤백되므로 테스트 간 오염이 없다. `get_db`를 이 세션으로 override, 리미터는 `limiter.enabled=False`(login 10/min 등이 반복 호출과 충돌하니까), lifespan은 일부러 안 돌림(백그라운드 스레드·SECRET_KEY 가드 회피 — TestClient를 `with` 없이 사용).
- **유저 시드**: 가입→이메일인증→승인 흐름을 매번 태우는 대신 `make_user(role=...)`로 DB에 직접 넣고 토큰은 `create_access_token`으로 발급 → **권한 로직 자체**를 곧장 겨냥.
- **스위트(29개, `backend/tests/`)**: health / auth(가입 202·짧은비번 422·오답 401·미인증 403·차단 403·성공 토큰·/me) / **posts 권한 매트릭스**(public·private·subscribers × 익명·남·본인·admin·구독자, 생성=writer 게이팅, 수정·삭제 소유자만 403) / comments(익명 자유이름 vs 로그인 이메일고정, 안 보이는 글 댓글 404) / subscriptions(구독·목록·자기구독 400·미존재 404·해제). 권한이 이 앱의 제일 복잡한 로직이라 거기에 집중했다.
- **CI(`.github/workflows/ci.yml`, deploy.yml과 분리 — '망가졌나'를 본다)**: push(main)·모든 PR에서 ① `backend-tests`(postgres 서비스 + `pip install -r requirements.txt -r requirements-dev.txt` + pytest) ② `frontend-build`(테스트 없으니 `npm run build`=tsc 타입체크를 게이트로). 테스트 전용 의존성은 `requirements-dev.txt`(pytest·httpx)로 분리 → 프로드 이미지 안 무겁게.
- **로컬 검증**: host에 `python3-venv`가 없어(ensurepip 부재) venv가 안 만들어짐 → **CI와 똑같이 `python:3.12-slim` 컨테이너 + `--network host`로 로컬 pg를 물려 pytest 실행 → 29 passed(6.7s).** 실행 방법이 곧 CI 재현이라 "내 машине선 되는데" 함정이 없다.
- **배운 것**: **테스트 DB 선택은 취향이 아니라 앱이 쓰는 DB 기능이 정한다.** ARRAY·trgm을 쓰는 순간 "빠른 SQLite"는 선택지에서 사라진다 — 억지로 맞추느니 프로드와 같은 Postgres를 CI 서비스로 띄우는 게 더 단순하고 진짜에 가깝다. / 테스트는 **행복경로가 아니라 거부 경로(401/403/404)**에 값이 있다 — 권한은 "되는 것"보다 "안 되는 것"이 깨지면 사고다.
- **[추가] 결제·AI 라우터 테스트(2026-07-18, 54개로 확대)**: 돈·비용을 켜는 로직이라 값어치가 높아 바로 이어 붙였다. 외부 호출은 목킹 seam으로 격리 — 결제는 `app.routers.payments.httpx.post`(토스 승인)를, AI는 `app.routers.ai.generate_draft`(LLM)를 monkeypatch.
  - 결제: checkout(비인증 401·관리자 400·이미Pro 400·pending주문 생성) / confirm(없는·남의 주문 404, **금액 위변조 400**, 토스 성공→is_pro, 거절→failed 400, 네트워크에러 502, **이미paid 멱등=토스 재호출 안 함**) / **라이브 가드(payments_require_live+테스트키 → checkout·confirm 둘 다 503 = 운영 '공짜 Pro' 차단)** / 해지.
  - AI: 비인증 401·pending 403 / 성공 시 마크다운+**일일 카운트 증가** / **티어 게이팅(일반 writer는 Opus 403, 유료는 200)** / **비용 캡(일일·월간 각각 429)** / 키없음 503·생성실패 502 / usage·models 조회. 캡·가드는 `settings` 속성 monkeypatch로 상한을 0으로 낮춰 검증.
  - 배운 것: 목킹은 **경계 하나**에만 걸면 된다 — 라우터가 import한 이름(`app.routers.X.함수`)을 갈아끼우면 그 아래 실제 SDK/HTTP는 안 건드리고도 라우터의 분기(거부·성공·예외)를 다 태울 수 있다. 돈/비용 로직은 "성공"보다 **막아야 할 것(위변조·중복·초과·테스트키)**이 안 막히면 사고라 거기에 무게를 뒀다.
- **[추가2] 보안 위험 라우터 테스트(2026-07-18, 77개로 확대)**: 코드를 훑어 "테스트 0인데 하필 권한이 세거나 공격면인 곳"을 찾아 메꿨다 — admin·uploads·auth 세션.
  - **admin**(최고권한): 라우터 전체 `require_admin`(일반 writer 403·비인증 401), 승인/취소, **관리자 계정 자기잠금 방지**(다른 admin에 approve·revoke·ban·delete 전부 400), **밴 즉시 기존 토큰 무효화**(ban→`token_version++`→옛 토큰 401), unban 상태검사, toggle-pro, 유저 삭제(글 동반 삭제), 미존재 404.
  - **uploads**(공격면): require_writer(401·403), 유효 PNG 200, **content-type을 image/png로 위조해도 내용이 HTML이면 매직바이트로 거부(400)**, 5MB 초과 413, 확장자는 파일명 아닌 내용에서 도출(.exe여도 .png 저장). 저장은 tmp로 돌려 실제 uploads/ 안 더럽힘.
  - **auth 보안속성**: 이메일 인증 흐름, **비번 재설정 → 기존 세션 무효화 + 새 비번 로그인**, **리셋 토큰 1회용**(재사용 400), **이메일 토큰을 Bearer로 못 씀**(purpose 박힌 토큰 401), verify 토큰을 reset에 쓰면 거부(purpose 불일치).
  - 배운 것: **커버리지 구멍은 균등하지 않다** — 빈 곳 중에서도 admin(권한)·upload(파일)·세션(토큰)처럼 깨지면 보안사고인 곳이 우선순위다. "성공"이 아니라 **막아야 할 것(권한상승·자기잠금·토큰혼용·위조파일)**이 안 막히는지를 겨냥했다.
- **[추가3] 남은 갭 4개 마저 채움(2026-07-18, 백엔드 90개 + 프론트 7개)**:
  - **subscribers**(더블옵트인): 확인메일 발송은 목킹(백그라운드 태스크가 SMTP 안 치게), 미확인 등록→confirm으로 확정, **unsubscribe enumeration 안전(등록 여부 무관 200)**, 로그인 본인구독(즉시 confirmed) 라이프사이클, **PII 목록은 admin만(writer 403)**.
  - **status/uptime 서비스**: 백그라운드 레코더 스레드에 의존 안 하고 순수 함수를 직접 — `run_checks`(형태·backend/database ok, mail은 환경차라 값 미검증), `get_latest`(캐시 반환 vs 콜드스타트 라이브), `get_history`(일수만큼 날짜 채움·서비스 3개·비율 0~1 구조).
  - **커버리지(pytest-cov)**: `--cov=app --cov-report=term-missing --cov-fail-under=70`. 현재 **77%** — 라우터는 대체로 높고(payments 96·subscribers 93·admin 90·subscriptions 90·post schema 86·uploads 84·auth 82), 낮은 곳은 외부 SDK 경로(ai/llm_keys 34%)·백그라운드(cleanup 44·infra 36)로 통합테스트가 못 닿는 자리. 목표는 100%가 아니라 **회귀로 70% 밑으로 떨어지면 CI 실패**.
  - **프론트 유닛테스트(vitest 4)**: `postUtils`의 순수 함수 `excerpt`(마크다운 벗기기·이미지 제거·링크 텍스트만·공백접기·max 절단+…)·`readingTime`(최소 1분·500자/분). `npm test` 스크립트 + CI `frontend` 잡에 스텝 추가(빌드만 게이트 → 테스트+빌드).
  - 최종: **백엔드 90 + 프론트 7 = 97개**, 라우터 9/9 커버, CI 두 잡(backend pytest+cov / frontend vitest+build) 게이트.
- **남은 것**: (선택) status 백그라운드 레코더 통합, ai/llm_keys BYOK 경로 테스트(외부 SDK 목킹 심화), 프론트 컴포넌트 테스트(jsdom). 우선순위 낮음 — 핵심 회귀 그물은 갖춰짐.

### 📄 저장소 정비: README · LICENSE · Dependabot (2026-07-18)

기능·인프라·테스트는 쌓였는데 **저장소를 열면 설명이 없어서** 그 노력이 안 보였다 —
방문자·채용담당자가 코드보다 먼저 보는 게 저장소 첫 화면이라, 그걸 채웠다.

- **README.md**: 소개 + 라이브 URL + CI 배지, 주요 기능, 기술 스택 표, **아키텍처 mermaid 다이어그램**(CloudFront→S3/EC2→Postgres 컨테이너→S3 백업), 로컬 실행(`docker compose up`), 테스트 실행법, 프로젝트 구조. 개발일지(PROGRESS.md)로 링크해 "왜 그렇게 만들었나"를 드러냄.
- **LICENSE**: MIT (공개 저장소 표준 — 없으면 "써도 되나?"가 모호).
- **.github/dependabot.yml**: pip(backend)·npm(frontend)·github-actions·terraform 4개 생태계 주간 점검, groups로 패치 묶어 알림 소음↓ → 의존성 보안 업데이트 자동화.
- **배운 것**: 코드가 좋아도 **읽는 사람의 진입점**이 없으면 없는 것과 같다. README는 기능 목록이 아니라 "이게 뭐고, 왜 이렇게 했고, 어떻게 돌리나"를 30초에 전달하는 문서다 — 이미 한 일(비용 최적화·RDS 이전·97개 테스트)을 보이게 만드는 게 새 기능만큼 값어치 있다.
