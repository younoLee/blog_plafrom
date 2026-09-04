# 공백 검사 — 2026-09-02 (워크플로 7갈래 + 갈래별 반박 검증)

08-11 공백 검사 이후 3주치를 다시 봤다. 갈래는 일곱: 운영·인프라·비용 / 보안 / 백엔드 /
프론트·제품 / 테스트·CI / 문서 드리프트 / 라이브 정적 사이트. 갈래마다 탐색 에이전트 하나가
최대 7건을 내고, 별도의 회의론자 에이전트가 파일:줄 또는 명령 출력으로 재확인했다.
확인 45건, 기각 1건, 검증 중 새로 눈에 띈 것 14건. 에이전트 15개, 도구 호출 370회.

**서버는 켜지 않았다.** 이 기계의 공인 IP가 SG의 SSH 대역과
다르고, 인스턴스 역할에 SSM 권한이 없고, 오리진은 주차 상태라 켜도 여기서 닿을 길이 없었다.
그래서 런타임(메모리·DB 통계·API 지연)은 못 봤다. 맨 아래 절에 모아 뒀다.
1·2번은 워크플로 밖에서 사람이 한 번 더 확인했다(describe-snapshots, main.py:265-341).


**관통 주제.** 세 갈래가 같은 곳을 가리켰다. 배운 뒤 "옆자리"를 안 쓸었다 — 푸시 예산은 걸었는데 메일은 안 걸고, 초대 토큰은 본문으로 옮겼는데 푸시 endpoint는 쿼리스트링이고, 게임데이 스냅샷은 뜨는 절차만 있고 지우는 절차가 없다. 그리고 "셋"·"27개"·"마지막"처럼 숫자를 박은 문장이 실물보다 먼저 낡았다. 서버가 꺼진 게 평상시인데, 그 상태를 앞단(CloudFront)·프론트 둘 다 기억하지 않아 방문자마다 30초·8초를 낸다.

## 지금 할 것 (새로 확인, 순위순)

**1. 본문 상한 6MB가 경로 무관이다 — high / S.** 이미지 업로드용 상한이 `/api/auth/login`·댓글·`forgot-password` 같은 무인증 JSON 경로에도 그대로라, JSON은 메모리에 통째로 쌓이고 slowapi는 파싱 뒤에 돈다. 연결 정원 500·backend 400m이면 5.9MB 연결 수십 개로 OOM 재시작이다. 증거: `backend/app/main.py:270,315-341`, `docker-compose.prod.yml:59,117`, `terraform/reqsize-function.js`(CL만), `terraform/waf.tf:67-70` count. 고침: 미들웨어와 엣지 함수 둘 다 `/api/upload`만 6MB, 나머지 512KB. `test_body_limit.py`에 login 1MB→413 추가. (CloudFront가 느린 본문을 그대로 흘리는지는 미실측.)

**2. 08-27 break-glass 스냅샷이 비암호화로 살아 있다 — high / S.** 옛 루트 볼륨 통째라 pgdata와 `.env` 21키가 다 들어 있고, 사본 모델("셋")·IR 유출자산 표·watch.sh 어디에도 없다. 07-27 것은 지웠는데 기록이 없어, 지우는 일이 사람 기억에 걸려 있다. 증거: `describe-snapshots` → snap-04ae9ee933923302a, Encrypted=false, 옛 볼륨 vol-0fcb…(현재는 vol-0bce…); `docs/dr-gameday-20260827.md:34` "떠 뒀다. 쓰지 않았다"; `scripts/env_escrow.sh:23`, `docs/incident-response.md:13-27`, `RECOVERY.md:56-63`. 고침: `delete-snapshot`(사용자 직접). 게임데이 런북 마지막 단계에 삭제, `scripts/watch.sh` 5절에 "자기 소유 스냅샷 0건 아니면 fail". (세 갈래가 같은 것을 지적.)

**3. 주차 상태 /api가 30초 뒤 504, 프론트는 그 사실을 안 기억한다 — medium / S.** 오리진 연결 시도 3×10초라 크롤러·맨 fetch(verify·forgot·reset·invite)는 30초 백지, SPA는 8초에 끊지만 /blog→글→뒤로가기·태그마다 8초를 다시 낸다. 증거: curl `/api/posts` → 504, 30.1s(재현); distribution-config ConnectionAttempts=3/Timeout=10; `terraform/cloudfront.tf:72-83`에 connection_* 없음; `frontend/src/api/http.ts:17`(8000ms, 기억 없음), `auth.ts:35,49,57,68,156` signal 없는 fetch; `HomePage.tsx:52-53,277`. 고침: origin에 `connection_attempts=1, connection_timeout=1` → 1초 504. `http.ts`에 마지막 ServerAsleepError 시각을 두고 60초 안 읽기는 즉시 거절. `http.ts:5-6` 주석의 "60초 read timeout" 진단도 틀렸으니 같이 고친다.

**4. DB 얹힌 인스턴스에 종료 보호가 없다 — medium / S.** delete_on_termination=true라 terminate = 마지막 정지 이후 전부 소실인데 막는 건 `stop_server.sh` 안 plan grep 하나뿐이다. 콘솔·-target 없는 apply·ami 교체·유출 키 전부 통과. 증거: `describe-instance-attribute disableApiTermination` → false; `terraform/ec2.tf:3-40`(없음), `:27-29`; `waf.tf:117-119`는 prevent_destroy 있음; `scripts/stop_server.sh:73-95`; `RECOVERY.md:67-69`. 고침: `disable_api_termination = true` + `lifecycle { prevent_destroy = true }`. 일부러 부술 때만 그 두 줄을 먼저 끈다.

**5. tfstate 버킷만 Object Lock·lifecycle이 없고 state에 ORIGIN_SECRET 평문 — medium / S.** 백업·감사 버킷은 COMPLIANCE 14일인데 state는 버저닝뿐이고, sensitive 변수도 state엔 평문이라 넷째 사본이 에스크로 밖에 있다. 222버전 무기한. 증거: `get-object-lock-configuration` → NotFound, lifecycle → NoSuch; `terraform/provider.tf:19-28`, `variables.tf:120-124`, `cloudfront.tf:89-93`, `db-backup.tf:63-69`, `RECOVERY.md:63`. 고침: `put-object-lock-configuration` COMPLIANCE 14일 + noncurrent 90일. RECOVERY §0 표에 "state = ORIGIN_SECRET 사본" 명시.

**6. 글 상세 댓글 칸이 절전·로딩 중에도 "댓글 (0)"과 활성 폼을 그린다 — medium / S.** 여기서 보내면 타임아웃 없는 apiFetch가 30초 뒤 실패하는데 문구는 `error && !asleep`에 걸려 안 보인다. 구독 토글도 같은 함정. 증거: `frontend/src/pages/PostDetailPage.tsx:498-558`(post 조건 밖), `:506`, `:179-198`, `:353`; `http.ts:97-99`. 고침: 섹션을 `post &&` 안으로, 폼 실패는 asleep 무관하게 폼 아래 표시.

**7. BYOK 키 라우트 HTTP 테스트 0개 — medium / S.** 서버가 대신 부르는 자격증명과 SSRF 입구인데 분기 5개(provider 400·NEEDS_BASE_URL·validate_api_key·base_url 검증·503)가 안 잠겼다. `ai.py:158-162`의 validate_base_url 배선을 지워도 초록. 증거: `backend/app/routers/ai.py:126-176`; grep `/ai/keys|validate_api_key|NEEDS_BASE_URL` tests → 0건; `test_ai.py:335`는 서비스 직접 호출. 고침: `test_llm_keys.py`에 PUT 정상·169.254 base_url 400·compatible without base_url 400·틀린 접두사 400·pending 403·DELETE→has_key False·키 없음 503.

**8. `/auth/forgot-password` 라우트 테스트 0개 — medium / S.** 존재 노출 방지·banned 제외·ver 결합 셋이 열려 있다. 증거: `backend/app/routers/auth.py:309-330`; grep forgot tests → 0건; `test_auth_security.py:34-86`은 토큰을 직접 만들어 reset만 호출. 고침: send_reset_email monkeypatch로 3케이스 + 토큰 재사용 400. `5/hour` IP 리밋이라 픽스처 확인 먼저.

**9. 결제 승인이 HTTP 200만 보고 status(DONE)를 안 읽는다 — medium / S (신뢰 0.6).** 가상계좌는 200 + WAITING_FOR_DEPOSIT이라 입금 전 Pro. 클라이언트키는 공개값이라 method 고정은 방어가 아니다. 지금은 require_live+테스트키로 503이라 잠재. 증거: `backend/app/routers/payments.py:121,145-152`(resp.json() 없음), `tests/test_payments.py:22` `status: DONE` 미사용. 고침: `status=='DONE' and totalAmount==amount and orderId==order_id`일 때만 paid.

**10. ROADMAP이 개강 뒤에도 방학 계획이고 세 곳이 자기모순 — medium / S.** 증거: `ROADMAP.md:6`(08-09) vs `:189`(08-28 결정); `:28,82,86`; `:61` vs `:105`; `:73` vs `terraform/ecs.tf:9-22` default ""; `:152` vs `backend/alembic/versions/e7f8a9b0c1d2_drop_subscribers.py`. 고침: 학기 기준으로 한 번 갱신, SAA 결과 기입.

**11. AMI가 09-17 deprecated인 6월판이고 OS 패치 절차 0건 — medium / M.** 재건마다 3개월 낡은 커널로 시작하고 deregister 날엔 시나리오 B 1단계가 첫 삽에서 실패한다. 증거: `terraform/ec2.tf:4`; `describe-images` DeprecationTime=2026-09-17; grep `dnf upgrade|dnf-automatic` → 0건; `RECOVERY.md:190-200`. 고침: `lifecycle { ignore_changes=[ami] }` + 분기별 ami 갱신, `stop_server.sh` 4-B에 `dnf -y upgrade --security`.

**12. SSH 키 사본이 PC 하나뿐, 런북에 "키를 잃었을 때"가 없다 — low / S.** 인스턴스 역할에 SSM 권한 없어 우회도 없다. 증거: `describe-key-pairs` 1개(06-24 콘솔); `list-role-policies blog-ec2-backup` → s3-put만; `terraform/ec2.tf:6`; `RECOVERY.md:56-63` 자산표에 키페어 없음; `scripts/env_escrow.sh:35`. 고침: env_escrow save가 pem도 SSM SecureString에, RECOVERY §0에 키페어 행.

**13. 배포 재빌드가 alembic upgrade를 도는데 직전 백업이 없다 — low / S.** 08-28은 drop 마이그레이션이었고 08-10엔 하루 덤프 4개(세션 중 쓰기 실재). 증거: `scripts/deploy_backend.sh` grep backup → 0건, `:150-153`; `docker-compose.prod.yml:117`; `RECOVERY.md:70-74`. 고침: 재빌드 안내 전에 `stop_server.sh` 2/6과 같은 백업 한 번, `--skip-backup` 옵션.

**14. Cost Anomaly Detection이 $100 절대 임계라 발동 불가, 저장소에 존재 자체가 없다 — low / S.** 증거: `ce get-anomaly-subscriptions` → ≥$100 AND ≥40%; 월 사용 $2~18; grep anomaly → 0건; `scripts/watch.sh:479-480` Budgets만. 고침: 임계 $5 또는 구독 삭제.

**15. 스킨 CSS `@import` 금지가 `@\69 mport`로 우회 — low / S.** jsdelivr `/gh/<아무 저장소>`를 style-src가 허용한다. 증거: `backend/app/schemas/user.py:112,118-125`; `tests/test_skin.py:77`; `terraform/csp-function.js:27`. 고침: 백슬래시 자체 금지 + 테스트.

**16. 구독 신청에 리밋·대상 역할 검사 없음 — low / S.** pending 계정이 아무 id에 알림 행을 만들고 404/201로 열거. 증거: `backend/app/routers/subscriptions.py:122-163`; grep limiter → 0건. 고침: `30/hour` + `role.in_(PUBLIC_BLOG_ROLES)`.

**17. 배운 자리 옆이 안 쓸린 백엔드 넷 — low / S·M.**
- `DELETE /api/push?endpoint=`가 기기 식별자를 액세스 로그에 남긴다(초대 토큰은 같은 이유로 본문으로 옮김). `backend/app/routers/push.py:106-131`, `frontend/src/api/push.ts:110`, `auth.py:143-147`. POST 본문으로.
- DataError 핸들러가 바인딩 값까지 찍는다. `backend/app/main.py:258`(`:179`는 exc.orig). `core/database.py` `hide_parameters=True` 한 줄.
- 업타임 레코더가 예외를 삼킨다. `backend/app/services/status.py:235-242` vs `cleanup.py:26-31`. logger.exception.
- 결제 confirm이 행 잠금·커넥션을 쥔 채 토스 15초 대기(M). `payments.py:87-96,111-117,152` vs `ai.py:383-385`. confirming 상태로 커밋 후 호출.

**18. 글·계정 삭제 때 S3 이미지가 영구 잔존 — low / M.** 참조 기록·delete_object·lifecycle 전부 없어 지운 글의 이미지가 무인증 공개로 남는다. 증거: `backend/app/routers/uploads.py:181-191`, `posts.py:556-567`, `admin.py:274-288`; grep delete_object → 0건; `terraform/iam-github-oidc.tf:108-112`. 고침: 주 1회 고아 객체 30일 유예 삭제 스크립트가 단순.

**19. 로그인 실패를 계정 단위로 세지 않는다 — low / M.** 분산 IP면 상한이 bcrypt 슬롯뿐. 증거: `backend/app/routers/auth.py:271,274-306`; `core/ratelimit.py:37-38`; `terraform/waf.tf` rate_based 0건. 고침: `login_failures` DB 카운터 15분/20회.

**20. CI가 안 보는 자리 셋 — low / S.**
- deploy.yml이 무효화에서 끝난다: `.github/workflows/deploy.yml` curl 0건; `scripts/watch.sh:719`는 S3 직접. 스탬프 `sha=$GITHUB_SHA`를 CloudFront로 12회 폴링.
- `check_publish_secrets.py`에 `--selftest` 없음: `:120-154` blocked 비면 0. 글투만 있다(`ci.yml:207-222`).
- `reqsize-function.js`만 `terraform/cf-functions.test.mjs`(`:24,:95`)에서 빠짐. 6291456 통과/6291457 413/헤더 없음 통과.

**21. 공유 카드·검색 노출 셋 — low / S·M.**
- og:title·JSON-LD headline에 " — 블로그 만들기"가 붙어 사이트명 두 번. `frontend/scripts/gen-static.mjs:423,434,440,891`; `head.ts:89-91`이 SPA에서 이미 피함. page()에 접미사 없는 제목 전달.
- `/@handle`이 useHead(description·canonical) 없음. `AuthorPage.tsx:163`; grep useHead pages → PostDetailPage만.
- 39편이 og-image.png 하나(M). `gen-static.mjs:426,436`, `scripts/gen_og_image.py:75`.

**22. 글쓰기에 붙여넣기·드롭 업로드 없음 — low / S.** uploadImage·insertAt은 있다. 증거: grep `onPaste|onDrop` → 0건; `WritePostPage.tsx:238-256`(끝에 붙임), `:299` insertAt. textarea에 onPaste/onDrop 연결.

**23. 문서가 실물보다 뒤처진 다섯 — low / S.**
- README:62·PROGRESS:1412 "terraform 밖은 셋": 실제는 키페어·SES 신원 4·예산 2·스냅샷·서브넷 하드코딩(`ec2.tf:7`). `cost-guardrail-drill-20260730.md:125`와 모순.
- 07-31에 없앤 구독 확인 링크가 현재 기능으로: `README.md:93`, `RECOVERY.md:356,360`, `docs/incident-response.md:191`, `backend/.env.example:27-31`. 반대 근거 `services/email.py:145`.
- `README.md:80` config.py:91은 payments_require_live(allow_signup은 :103); compose 두 곳 "27개"는 42개; `README.md:121` 워크플로 둘은 넷.
- `frontend/README.md` Vite 템플릿 원문 73줄.
- `docs/dr-gameday-20260727.md:28` 스냅샷 삭제 기록 없음(2번 뿌리).

**24. 정적 배포 잔가지 셋 — low / S.** sw.js `CACHE='docs-v1'` 고정이라 옛 번들 ~620KB가 기기마다 남는다(`frontend/public/sw.js:97,106,147-156`); HTTP/3 꺼짐 + 결정 기록 0(`cloudfront.tf:47`, Free 요금제 허용 미확인); 번들 469→526KB인데 CI 예산 없음(`vite.config.ts:8-23`).

## 이미 알려져 있었고 아직 열린 것

- **Pro lazy 만료 미테스트 — medium / S.** `backend/app/core/deps.py:12-17` 본문을 비워도 461개 초록. `gap-inspection-20260811.md:185`. `test_payments.py`에 만료·유지 한 쌍.
- **메일 팬아웃에 시간 예산 없음 — low / S.** `services/email.py:187-200` vs `push.py:53,306-316`(45초). `chaos-drill-20260827.md:311` 미검증 #8.
- **WAF rate-based 룰 없음 — low / M.** `terraform/waf.tf:25-110`; `gap-inspection-20260811.md:136`.
- **text-gray-400 대비·placeholder 전용 입력 6칸 — low / S.** `HomePage.tsx:237-249`, `PostDetailPage.tsx:528,546,548`, `WritePostPage.tsx:476,570,618,670`; 08-11 9번 잔여.
- **기존 업로드 2개 Cache-Control 없음 — low / S.** `head-object` CacheControl null; d904437 메시지. `s3 cp --metadata-directive REPLACE` 두 번(사용자 직접).
- **프론트 결제·인증 화면 테스트 0, e2e 없음 — low / M.** `ls pages/*.test.tsx` 4/19; `PaymentPage.tsx:13` test_ck 폴백. ROADMAP:149 전제(jsdom 도입 필요)는 이미 낡음.

## 미검증 후보

- `terraform/ec2.tf:27-29` root_block_device에 `encrypted=true` 없음 — 지금 암호화는 계정 기본값(terraform 밖) 덕.
- `auth.py:88` 주석 "token_version으로 옛 링크 무효화"가 거짓 — register가 ver를 안 넘긴다(`security.py:102`). 문서 결함.
- 컨테이너 로그 회전이 30MB가 아니라 10m(`docker-compose.prod.yml:35-38,67-70`) — 문서가 30MB라 적었는지 확인.
- 절전 중 /blog 태그·쪽 전환 시 정적 목록 위에 스켈레톤 8초 — `HomePage.tsx:277`에 `&& sleepList.length===0`.
- `test_admin.py:113-115`는 "안 꺼짐"만 단언 — 만료 방향 회귀는 못 잡음.
- `ec2.tf:7` subnet 하드코딩 vs `network.tf:20` data 소스.
- `sw.js:16-18` 주석의 회수 장치 ②(캐시 이름 올리기)에 절차·검사 없음 — 08-19 ①과 같은 유형.

## 깎은 것

- **verify가 ver를 안 본다·리밋 없음** — 리밋 제외는 문서화된 결정(`auth.py:332`), 공격 경로 없음(링크가 피해자 메일함으로만 감), 제안대로 ver 비교를 넣으면 재가입 후 모든 인증 링크가 400. 주석 부정확은 미검증 후보로.

## 서버를 켜야만 볼 수 있는 것

- backend 실메모리 사용량(400m 여유)과 1번의 느린 본문이 CloudFront를 통과하는지.
- DB 통계: 풀 점유·idle in transaction·인덱스 사용·pgdata 크기.
- 실제 /api 지연(status·history), 토스 가상계좌 confirm 응답 status(라이브키).
- notify_new_post의 SMTP hang 최악 벽시계(구독자 N명).
- OS 패치 상태(`dnf check-update`)·컨테이너 로그 실제 회전 크기.
- pytest 커버리지 실행(이 기계에 Postgres 없음 — 서버가 아니라 로컬 DB 문제).