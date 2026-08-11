# 공백 검사 — 2026-08-11 (서브에이전트 5갈래)

08-10 심층검사가 "병목·부정적인 것"을 훑었으므로, 이번엔 축을 **"없는 것"** 으로 바꿨다.
다섯 갈래: 테스트 공백 · 프론트 사용자 공백 · 운영 공백 · 보안 공백 · 문서↔실제.

**모든 항목은 파일:줄로 재확인한 것만 남겼다.** 에이전트가 냈지만 실물과 대조해 깎은 것은
맨 아래 「깎은 것」에 이유와 함께 적었다.

---

## 관통 주제

> **이 저장소의 장치들은 "없음"과 "못 봤음"을 못 가른다. 그리고 그 둘을 가르라고
> 적어둔 교훈이, 정작 같은 파일의 다른 절에는 안 쓸렸다.**

08-10의 주제("고친 자리 옆에 안 쓸린 입구")의 다음 단계다. 그때는 *수정*이 안 쓸렸고,
이번엔 **교훈이 자기 파일 안에서 안 쓸렸다.**

| 배운 자리(근거가 코드에 있음) | 안 쓸린 입구 |
|---|---|
| `watch.sh` 4개 절이 "종료코드를 봐야 한다"를 구현 | 같은 파일 백업 점검 2곳(`:157`·`:178`)은 여전히 안 본다 |
| `watch.sh:186-190` 이미지 점검이 '못 읽음'을 가름 | 바로 아래 `:205`가 **'원본 0개'를 ✅로 찍는다** |
| `ci.yml:112-114` "glob은 하위 디렉터리를 안 본다 → find로 바꿨다" | 바로 **위** `:106`의 문법 검사는 여전히 glob |
| `check_runbook_drift.sh:141-144`가 옛 D 검사를 반박 | 같은 파일 `:23-27` 헤더는 그 옛 절차를 현재 규칙으로 서술 |
| `PROGRESS.md:704`가 AI 기능 라이브 검증을 기록 | 같은 파일 `:12`는 아직 "e2e만 남음" |

---

## 🔴 1. 업로드 이미지 2개가 07-30에 삭제됐고, 12일간 감시가 초록이었다

```
uploads/9376c2ae4c1b496d88a7eff2d466b90d.jpg  삭제표식 2026-07-30T05:03:17Z  (원본 23,500 B 생존)
uploads/d4ace8e56ee34faeb8af035e5b27939b.png  삭제표식 2026-07-30T05:03:18Z  (원본 1,726,680 B 생존)
```

현재 `s3://blogplafromops/uploads/` 객체 **0개**, 백업 미러 **2개**, EC2 로컬 `~/blog/uploads/` **0개**.

**왜 안 잡혔나** — `scripts/watch.sh:205-206`:

```bash
elif [ "$src_n" -eq 0 ]; then
  ok "업로드 이미지 없음(확인할 것 없음)"
```

`RECOVERY.md:238-241`이 **시나리오 C(업로드 이미지를 잃었다)** 로 정의한 바로 그 상태를
감시는 ✅로 보고한다. 통과 조건이 `dst >= src`인데, **사본(2)이 원본(0)보다 많다는 것
자체가 원본 삭제의 신호**다. `restore_drill.sh:440-441`도 같은 모양으로 정보 처리한다.
약 280회 실행이 전부 초록.

삭제 시각 14:03 KST는 `--delete`를 동반한 수동 `aws s3 sync`와 같은 모양이다.
배포 워크플로에는 `--exclude "uploads/*"`가 있고 배포 역할에는 `NeverTouchUploads` Deny가
있지만, **개발 PC의 IAM 유저(IAM_cli)로 친 sync는 그 둘 다 안 걸린다.**
`cloudtrail.tf:152-153`이 S3 데이터 이벤트를 (비용 근거로) 끄고 있어 **주체는 규명 불가**다.

**복구 시한은 없다** — 버킷 lifecycle의 `NoncurrentVersionExpiration`은 `index` 접두사
전용이라(`expire-old-spa-bundles`) `uploads/`는 만료 대상이 아니다. 삭제 표식만 지우면
되살아난다. 현재 그 이미지를 참조하는 글은 없어 화면 피해는 0이다.

**고칠 것**: `src_n == 0 && dst_n > 0`을 `fail`로. "없음"이 아니라 "사라짐"이다.

---

## 🟠 장치가 스스로를 못 지키는 것

### 2. `watch.sh` 백업 점검 2곳만 종료코드를 안 본다
`scripts/watch.sh:157-160`·`:178-181` — `2>/dev/null` 뒤 빈 문자열을 "백업이 하나도 없다"는
**사실 주장**으로 바꾼다. 같은 파일이 다른 4개 절(이미지 `:186`, SES `:226`, CloudTrail `:254`,
예산 `:330`)에서 정확히 이걸 금지하고, 예산 절에는 "python3 실패가 '예산이 0개다'라는
거짓 사실로 보고됐다"는 실제 사례까지 적혀 있다. **다섯 중 넷만 쓸렸다.**

### 3. 감시 자신에게 하트비트가 없다
`.github/workflows/watch.yml:14-15`가 스스로 "GitHub은 60일간 커밋이 없는 저장소의
스케줄 워크플로를 자동으로 멈춘다"고 적는다. 그런데 알림 경로는 `watch.sh:24-28`이
명시하듯 **'Actions 실패 메일' 하나뿐**이다 → 워크플로가 멈추면 실패 메일도 안 온다.
**완전한 침묵이 정상과 구분되지 않는다.** OIDC 역할 삭제·Actions 비활성도 같은 침묵을 만든다.

`watch.sh:311-316`은 스스로를 "감시를 감시하는 자리"라 부르며 예산 알림의 생존을 확인한다.
정작 자기 생존을 확인하는 것은 없다.

### 4. 재건 런북의 tfvars가 알림 전달 경로를 지운다
`RECOVERY.md:137-140`의 히어독에 `ssh_cidr`·`origin_secret` 둘뿐 — **`alert_email`이 없다.**
그런데 `terraform/alerts.tf:98`이 `count = var.alert_email != "" ? 1 : 0`이다
→ 값이 비면 SNS 이메일 구독이 **destroy** 된다.

두 안전장치가 각각 이 자리를 비껴간다:
- `check_runbook_drift.sh:50-105`(검사 A)는 **기본값 없는 변수만** 런북에 요구한다.
  `alert_email`은 기본값 `""`이 있어(`alerts.tf:18`) 구조적으로 검사 밖.
- `stop_server.sh:77-95`의 `park_origin`은 -target 없는 전체 apply이고, 플랜 가드는
  `^  # aws_instance\.`만 본다(`:87`) → 구독 destroy는 통과한다.

즉 **런북대로 재건한 뒤 첫 정지 절차를 돌리면 알림 경로가 사라진다.**

### 5. 에스크로 점검 결과가 어떤 종료코드에도 안 들어간다
`stop_server.sh:237`·`restore_drill.sh:460` — 둘 다 `env_escrow.sh check || true`.
그리고 `watch.sh`에는 에스크로 점검이 **아예 없다**(러너에 `~/.blog-secrets`가 없어 구조상 불가).
→ 이 저장소에서 가장 복구 불가능한 값(`LLM_ENCRYPTION_KEY`)의 사본 일치는
**자동 감시 0건**이고, 사람이 훈련 출력을 눈으로 읽을 때만 드러난다.

### 6. `blog-app-secrets` — 어느 절차도 모르는 넷째 시크릿 사본
`terraform/ecs.tf:50-53`의 `aws_secretsmanager_secret "app"`은 `enable_ecs` 게이트 **밖**이다.
ECS는 07-24에 tear down했는데 이건 남았고, AWSCURRENT 버전이 **값을 가진 채** 18일째다.
`RECOVERY.md:60`과 `env_escrow.sh:23-27`은 사본이 **셋**(서버·PC·SSM)이라고 못박는다.
07-27 IR 훈련이 `SECRET_KEY`를 교체했으므로 이 사본은 **옛 SECRET_KEY + 현재도 유효한
LLM_ENCRYPTION_KEY**를 들고 있을 가능성이 크다 — IR 회고가 남긴 `.env.preIR` 교훈과 같은 모양.

곁들여: 30일 무료체험이 끝나는 08-23쯤부터 월 $0.40이 조용히 붙는다.

### 7. 서버가 꺼져 있으면 감시가 HTTP 요청을 한 번도 안 한다
`watch.sh:96-97`이 `state != running`이면 `ok`로 끝내고, 유일한 curl(`:108`)이 그 분기 안에 있다.
이 서버는 "안 쓸 때 정지"가 기본이라 **대부분의 시간 동안 공개 사이트를 안 찌른다.**
정적 아카이브·RSS·sitemap(유입을 만들려고 만든 것)은 EC2와 무관하게 살아 있어야 하는데,
그 확인은 `stop_server.sh:288`의 **끌 때 한 번**뿐이다. 관측된 정지 간격 최대 5일.

---

## 🟠 코드 결함

### 8. `posts.py:242` — 주석이 거짓이라 연재 101편째부터 500
```python
# 이 글이 목록에 없을 수는 없다(위에서 can_view 통과 = visible_condition도 통과).
pos = ids.index(post.id)
```
근거가 가시성만 보는데 바로 위 쿼리에 `.limit(SERIES_ITEMS_MAX)`(=100, `:30`)가 걸려 있고
정렬이 `created_at` 오름차순이다. → `ValueError`가 새고 `main.py`의 핸들러는 DB 계열만 잡으므로
**500 text/plain**. 07-28·07-31·08-10에 세 번 없앤 그 모양이다. (현재 연재 26편, 74편 여유)

### 9. 로그인이 단락 평가라 계정 존재가 시간축으로 샌다
`auth.py:255` `if user is None or not verify_password(...)` — 미가입 주소는 bcrypt를 아예 안 돌고
즉시 401, 가입된 주소는 cost 12 해시를 돌고 401. **바로 윗줄 주석이 보장한다고 적은 것이 깨진다.**
`register`(`:50`)·`forgot-password`(`:275`)가 응답을 맞춰 막아둔 열거를 로그인이 무효화한다.
초대제라 계정이 희소해 그 답의 값이 크다.

### 10. `/api/posts/meta`와 `/api/blog-owner`만 리밋이 없다
`posts.py:177`의 meta는 요청당 쿼리 3개(COUNT·`unnest(tags)` GROUP BY·최근 5개)인데
20줄 위 `list_posts`(`:135`)의 `@limiter.limit("60/minute")`가 없다. `/api/*`는 CloudFront
`CachingDisabled`라 전량 오리진까지 오고 WAF에 rate-based 룰이 없다.
`main.py:337`의 `/api/blog-owner`도 리밋 없이 관리자 내부 id를 무제한으로 준다.

### 11. `remark-gfm`이 없어 앱과 정적 아카이브가 다르게 렌더된다
`PostDetailPage.tsx:125`는 `rehypePlugins={[rehypeSlug]}`뿐이고 `package.json`에 `remark-gfm`이
없다(react-markdown v6+는 GFM 미포함). 정적 아카이브는 `marked`라 GFM을 지원한다.
**같은 원문이 두 렌더러를 타는데** 표·취소선·체크박스가 앱에서만 원문 그대로 보인다.
라이브 확인: id **18**·**36**에 `~~`가 있다.

### 12. AI 비용 캡이 '횟수' 기준이고 전역 상한·차단 스위치가 없다
캡은 전부 `user_id` 단위(`config.py:56,58`)이고 서비스 전체 합계를 세는 코드가 없다.
**토큰을 세는 코드가 0곳**인데 `ai.py:167,214-224`에서 `max_tokens`가 모델별로 2500~8000이라
Haiku 20회와 상위 모델 20회가 캡에서 동일하게 취급된다. `ai.py:347-349`는 업스트림 실패 시
슬롯을 환불하므로 **55초 타임아웃으로 끊긴 경우 토큰은 태우고 캡은 안 센다.**
Anthropic 청구는 AWS 밖이라 Budgets 2개가 원리적으로 못 본다 → **다음 명세서까지 최대 한 달.**

### 13. `cleanup.py`가 실패를 로그 한 줄 없이 삼킨다
`cleanup.py:38-40,71-73` — `except Exception: db.rollback(); return 0`. 로그가 없다.
`email.py:31-56`이 "조용한 실패를 읽을 수 있는 실패로 바꾼다"고 해놓은 것과 정면으로 어긋난다.
덤으로 `users.id`를 참조하는 FK 6개 중 `posts.owner_id`만 `ondelete`가 없다(`models/post.py:44-46`).

---

## 🟠 테스트 공백

**손대지 않은 라우트·서비스** (전부 `grep` 0건 확인)

| 대상 | 무엇이 안 잠겨 있나 |
|---|---|
| `DELETE …/comments/{id}` (`comments.py:105-121`) | 권한 가드가 `:117` 한 줄. 이게 `or`가 되면 **아무 로그인 사용자가 남의 글 댓글을 지운다.** 이 라우트만 `_viewable_post_or_404`가 아니라 `get_post_or_404`를 써서 404/403이 갈리는 것도 잠겨 있지 않다 |
| `cleanup.py` 전체 | 이 저장소의 **유일한 대량 DELETE**. `<`가 `>`가 되면 방금 가입한 계정만 지우고, `.is_(False)`가 빠지면 24시간 지난 **모든 계정**을 지운다. 계정 생성 경로가 초대뿐이라 복구가 수작업 |
| `/ai/keys` · `validate_base_url` | **SSRF 방어**(https 강제 + DNS 해석 후 공인 IP 검사, `llm_keys.py:87-132`). `:114-117`의 포트 `ValueError`는 08-10 보안검사가 실측 재현해 고친 자리인데 **회귀 테스트가 없다** |
| `/api/admin/infra` | 라우터 레벨 `require_admin`이 이 경로로는 확인 안 됨(효과는 작다 — 스모크 1개면 충분) |

**이름이 약속을 안 지키는 테스트 3개** (전부 코드로 확인)

- `test_payments.py:131` `test_confirm_toss_rejection_marks_failed` — **`Payment.status`를 한 번도 안 읽는다.**
  `payments.py:121`의 `p.status = "failed"`를 지워도 초록. 이웃 `:145`(502)·`:158`(멱등)·`:100`(금액 위변조)도 같은 모양
- `test_admin.py:88` `test_delete_user_removes_their_posts` — 글을 안 본다. 유저가 404가 되는 것만 확인
- `test_admin.py:79` `test_toggle_pro` — `make_user(is_pro=False)`로 시작해 `pro_until`이 NULL이라,
  **`admin.py:108-111`의 버그 수정 두 줄을 지워도 통과한다.** 그 주석이 기록한 사고
  ("관리자 수동 부여가 조용히 무효화됐다")를 지키는 테스트가 아니다

**주석으로만 지켜지는 불변식**

- `uploads.py:52-64` — "`async def`로 되돌리지 마라"(되돌리면 요청 1개로 API가 112.3초 정지).
  지금 이걸 지키는 건 주석뿐. `assert not inspect.iscoroutinefunction(uploads.upload_image)` **한 줄**이면 잠긴다
- `uploads.py:119-127`의 `Config(connect_timeout=5, read_timeout=20, retries=2)` — `test_degradation.py:75`가
  `boto3.client`를 통째로 갈아끼워 인자를 안 본다. 저 숫자가 112초의 원인이었다
- `deps.py:12-17` `_expire_pro_if_due`(lazy expiration) — 죽으면 **결제 1회로 Pro가 영구 유지**된다

**프론트가 백엔드의 구분을 뭉갠다**

- `api/ai.ts:102` — 백엔드의 서로 다른 503 **세 가지**(서버 키 없음 / BYOK 복호화 실패 / 업스트림 도달 실패)를
  "AI 기능이 아직 설정 안 됐어" **한 문장**으로 덮는다. `test_ai.py:337`이 "다시 등록" 문구를 확인하지만
  그 문자열은 화면에 도달하지 않는다
- `api/uploads.ts:15-18` — 503·429 분기가 없어 둘 다 `업로드 실패`. `uploads.py:139`의 주석은
  "프론트의 isAsleepStatus가 받는다"고 적었지만 `uploadImage`는 `fetchWithTimeout`을 안 쓴다 → **거짓**
- `WritePostPage.tsx:71-87` — `fetchAiModels`/`fetchKeys`/`fetchUsage`가 전부 `.catch(() => {})`.
  한 번 실패하면 `models.length > 0` 게이트(`:283`)로 **모델 드롭다운이 통째로 사라지고**
  `generateDraft(memo, undefined)`가 서버 기본값으로 돈다 → **돈 낸 Pro 사용자가 상위 모델을 못 고르는데 화면에 에러가 없다**

---

## 🟡 프론트 — 사용자가 겪는 공백

이 사이트는 `/api/*`가 504인 상태가 **평상시**다. 그 관점에서:

1. **`HomePage.tsx:186`** — `posts=[]`·`asleep=false`로 시작해, 응답이 오거나 8초 타임아웃이
   끝날 때까지 첫 화면에 `아직 글이 없어. 첫 글을 써봐!` + `0개`가 **확정적으로** 떠 있다.
   로딩 상태가 없다. (`AdminPage.tsx:63`은 같은 문제를 `loaded` 플래그로 막아뒀다 — 정작 가장 많이 보는 화면에만 없다)
2. **`PostDetailPage.tsx:36-45`** — `postId`가 바뀔 때 `post`/`comments`/`series`를 초기화하지 않는다
   → 연재 '다음 편'을 누르면 새 글이 올 때까지 **이전 글의 본문·댓글·목차가 그대로** 보인다.
   절전(504)도 여기선 빨간 에러로 나온다(`:140`) — HomePage는 노란 안내로 구분해뒀다
3. **`SubscriptionsPage.tsx:38-40`** — 세 요청 전부 `.catch(() => setX([]))`. 그중 `fetchAuthors`는
   `fetchWithTimeout`이 아니라 맨 `fetch`(`api/subscriptions.ts:67`)라 8초 규칙 밖이다.
   → 서버가 꺼져 있으면 "구독할 사람이 아무도 없는 페이지"로 보인다
4. **`LoginPage.tsx`** — `busy`·`disabled`·스피너가 없고 `login()`도 맨 `fetch`(타임아웃 없음).
   느릴 때 다시 누르면 `429 로그인 시도가 너무 많아`를 만난다 — 자기가 만든 상황인 걸 알 수 없다.
   덤으로 `AuthProvider.tsx:18-21`: 로그인 성공 후 `fetchMe()`가 실패하면 토큰은 저장됐는데
   `user`가 null → **성공했는데 실패한 것처럼 보인다**
5. **`WritePostPage.tsx:218-233,492`** — 제출에 busy가 없고 버튼이 disabled가 안 되며
   `createPost`도 맨 `fetch` → **느릴 때 두세 번 누르면 같은 글이 여러 개 생성된다**.
   (같은 페이지의 AI 초안만 제대로 돼 있다 — disabled·스피너·90초 타임아웃)
6. **`AdminPage.tsx:224-234`** — 10초 폴링의 `.catch(() => {})`. 실패해도 마지막 성공값이 남아
   **서버가 꺼진 뒤에도 CPU 12%·메모리 40%가 초록으로 떠 있다.** 서버를 껐다 켜는 게 이 프로젝트의
   운영 방식이라 정확히 그 순간에 틀린다
7. **SEO** — 글 상세가 바꾸는 건 `document.title` 하나뿐(`useDocumentTitle.ts:9`)이고
   `og:*`·`canonical`은 `index.html:13-25`의 사이트 고정값 → **모든 글이 같은 공유 카드**로 뜬다.
   JSON-LD 0건. `gen-static.mjs:238`이 `/blog/posts/*`를 sitemap에서 (타당하게) 제외하므로
   **정적 아카이브에 없는 글은 검색에 영원히 0**이다
8. **`gen-static.mjs:57-72`** — meta description 생성이 불릿 기호를 지우고 줄바꿈까지 지워
   **28편 중 9편에서 두 항목이 구분자 없이 이어붙는다**(예: `…배포·스모크까지 끝 공개 데모 계정을 폐지했다…`)
9. **접근성** — `NotificationBell.tsx:31-35`는 닫는 경로가 `mousedown` 하나뿐(**Escape 없음**),
   `aria-expanded`/`aria-haspopup` 없음 · `text-gray-400`이 배경 위에서 **2.33:1**(AA 4.5:1 미달)인데
   글 개수·작성일 같은 정보에 쓰인다(95회) · `prefers-reduced-motion` 대응 **0건**
   (`index.css:52-55`는 제목마다 6초 주기로 영원히 움직인다)
10. **`AdminPage.tsx:299,312`** — writer 행의 버튼 4개가 `shrink-0`인데 `flex-wrap`이 없어
    360~390px에서 가로 스크롤이 생긴다. 같은 파일 초대 폼(`:115`)엔 `flex-wrap`이 있다

---

## 🟡 문서 ↔ 실제

### 높음

| # | 문서가 말하는 것 | 실제 | 믿고 행동하면 |
|---|---|---|---|
| A | `README.md:77` — "첫 사용: 회원가입 → Mailpit에서 인증" | `config.py:91` `allow_signup: bool = False` + `auth.py:45` 403. `ALLOW_SIGNUP` 키가 compose·env 예제 어디에도 없다. 실제 경로 `backend/scripts/create_user.py`는 **README에 언급 0건** | 새로 클론한 사람이 **계정을 하나도 못 만든다.** 공개 저장소의 정문이라 대외 노출이 가장 크다 |
| B | `docs/incident-response.md:78` — "GuardDuty 없음, **CloudWatch 알람 0개.** 실시간으로 보는 눈이 없다" | `alerts.tf:122` `ec2_status_check` 알람 + 토픽·구독·`watch.sh:383`의 6-B 전달 확인 | 사고 한복판에서 **알람 이력과 SNS 경로를 아예 안 뒤진다** |
| C | `docs/ecs-migration-plan.md:230-242` 단계별 apply 절차 | `enable_ecs` 언급 **0건**인데 `rds.tf:12`·`alb.tf:11`·`ecs.tf:77` 등이 전부 `count = var.enable_ecs ? 1 : 0` | `-target=aws_db_instance.main`이 count=0을 가리켜 **RDS를 안 만들고 exit 0** → "1단계 성공"으로 읽힌다 |

### 중상

- **`ci.yml:106`** — 문법 검사가 아직 `for f in scripts/*.sh`(9개, `scripts/lib/ec2.sh` 제외).
  바로 아래 shellcheck(`:123`)만 `find`로 바뀌었는데, `:112-114` 주석은 **"구멍을 닫았다"** 고 적는다.
  5개 스크립트의 공통 입구에 문법 오류가 들어가도 **CI가 초록**
- **`check_runbook_drift.sh:23-27`** — 헤더가 "INSTANCE_ID가 전부 같은가 / 5곳을 손으로 고쳐야 한다"는
  **폐기된 절차**를 현재 규칙으로 서술. 같은 파일 `:141-144`와 `RECOVERY.md:149-151`이 반박한다.
  07-27 게임데이가 "RTO 42분 중 20분이 문서가 틀린 자리"라고 결론 낸 그 부류
- **`docs/restore-drill-20260810.md:79-83`** — "미결: `b8c9d0e1f2a3`이 운영에 없다"가 그날 저녁 닫혔다.
  (오늘 실측: 운영 `alembic current` = `d0e1f2a3b4c5 (head)`)
- **`PROGRESS.md` 상단 '현재 상태' 25줄** — 읽는 사람이 가장 먼저 보는데 네 군데가 낡았다:
  `:12` AI 기능 "e2e만 남음"(같은 파일 `:704`가 라이브 검증을 기록) · `:21` `backend/.venv`(**존재하지 않음**) ·
  `:24` 데모 계정 2개(08-07 `8d3fd62`로 삭제) · `:16` 도메인 "갖고 싶어지면 그때"(`ROADMAP.md:155` **"안 산다·다시 꺼내지 말 것"**)
- **`README.md:61`** — "모든 AWS 리소스는 terraform에 코드화". `aws_ssm_parameter`·`aws_iam_user` **0건**,
  tfstate 버킷은 backend 설정일 뿐 관리 리소스가 아니다. `RECOVERY.md:63`과 `PROGRESS.md:1405`는 맞게 적혀 있다 —
  **셋 중 README만 틀렸다**

### 발행된 공개 글 (고치려면 재발행 필요)

- **`content/devlog/2026-07-11.md:70`** — "하이라이팅은 클라이언트에서: 독자 브라우저가 코드에 색을 칠한다".
  `rehype-highlight`·`highlight.js`가 `package.json`에 **없고**, 08-10 심층검사가 근거를 남겼다 —
  코드펜스 260개가 전부 언어 태그 없음, `language-*` 클래스 **0건**.
  **처음부터 사실이 아니었다.** 이 저장소 원칙("설정했다 ≠ 동작한다")의 교과서적 사례가 공개 글에 있다
- **`2026-06-21.md:46`** — 시제 없는 "권한 규칙은 다음과 같다" 선언인데 셋 중 둘이 거짓:
  `posts.py:95` 관리자는 `return true()`로 남의 비공개 글을 전부 보고, 수정·삭제도 소유자 전용이 아니며,
  공개범위도 `subscribers` 포함 3종이다
- **`2026-07-15.md:83`** — "백엔드가 계정명으로 고정해 **사칭을 막는다**". `comments.py:77-82`가 정면으로 반박한다 —
  "이 고정만으로는 사칭이 안 막힌다 … 2026-08-10에 무인증으로 재현했다". **이미 뚫린 것으로 판명난 방어를 방어라고 설명**하고 있다

### 낮음 — 깨진 참조

`.gitleaks.toml:79`(→ 실제 `config.py:71`) · `docs/ses-production-access.md:239`(→ 실제 `auth.py:45-49`) ·
개발일지 편수 3곳 불일치(`README.md:17` 24편 / `deploy.yml:98` 25개 / 실제 **28**) ·
`create_user.py:6`이 08-07에 없앤 '체험 계정 버튼'을 위해 `--demo`를 설명(공개된 비밀번호의 writer 계정을 되살릴 유인) ·
`deploy_backend.sh:53` "계정은 create_user.py로만 만든다"(초대 소각 경로 `auth.py:153`이 또 있다)

---

## ⚪ 깎은 것 — 에이전트가 냈지만 실물과 안 맞거나 과대평가된 것

- **"비공개 글 이미지가 무인증으로 열린다"** — 구조상 사실이지만(`/uploads/*`는 S3 오리진이 인증 없이 서빙)
  **현재 노출된 이미지가 0건**이다(1번 항목 때문에 버킷이 비었다). 이미지 기능을 다시 쓰기 시작할 때 재론할 것
- **인가 우회·IDOR·권한 상승** — 전 엔드포인트 매트릭스를 떠서 **한 건도 없었다.** 목록 필터(`visible_condition`)와
  단건 가드(`can_view`)가 admin/소유자/구독자/익명 네 경우 모두 일치하고, `owner_id`가 NULL인 레거시 글에서도
  SQL의 NULL 전파와 파이썬 비교가 같은 답을 낸다. `role`을 토큰에 안 담고 매 요청 DB에서 읽는 구조도 유지
- **세션·토큰** — 비번 재설정·차단·스크립트 갱신이 전부 `token_version`을 올려 기존 JWT를 즉시 죽인다.
  재설정 토큰은 `ver` 스냅샷으로 1회용이고, 로그인 토큰↔이메일 토큰은 `purpose` 클레임으로 양방향 차단. 깨끗함
- **입력 신뢰 경계** — LIKE는 `_like_escape`+`ESCAPE`, 파일명은 통째 폐기하고 매직바이트로 판별,
  메일 Subject 개행 제거, 리다이렉트 파라미터 자체가 없음, `dangerouslySetInnerHTML` 0건. 깨끗함
- **`2026-06-24.md:55`의 "API 8000(누구나)"** — 지금은 CloudFront prefix list뿐이지만 **잠근 건 07-02**고
  그 글은 06-24자다 → **그 당시 사실**이므로 정정 대상 아님
- **`infra.py` 커버리지 채우기 — 하지 말 것.** `gather_infra()`는 psutil 값을 dict로 옮기는 게 전부라
  목킹 테스트는 psutil을 다시 구현하는 셈이고, 실제로 깨질 것(컨테이너에서 호스트 값이 나오는가)은 원리상 못 잡는다.
  **라우터 레벨 스모크 1개**(admin 200 / writer 403)로 끝낼 것
- **`SYSTEM_TEMPLATE` 문구 assert 추가 — 하지 말 것.** 이미 8개가 있고, 프롬프트는 이 저장소에서 가장 자주
  고치는 산문이다. 실제 방어는 기계 판정(`validate_draft`·`verbatim_leak`·캐너리)이 하고 그쪽은 잘 덮여 있다

---

## ✅ 같은 날 손댄 것 (커밋 `eb4e354`)

우선순위 1~9번을 처리했다. 실측: ruff 통과 · pytest **292 passed**(268→292) ·
커버리지 **84.63% → 86.36%** · eslint 0 · vitest 18 · 번들 469.73 kB(변화 없음) ·
런북 드리프트 초록.

| 항목 | 결과 |
|---|---|
| 삭제된 이미지 2개 | **복구 완료** — 삭제 표식 제거, CloudFront 200 실측 |
| `watch.sh:205` | `src==0 && dst>0` → **fail** + 복구 명령 안내 |
| `watch.sh:157,178` | 호출 실패와 0건을 가름(같은 파일 4곳과 통일) |
| `posts.py` 연재 500 | None 폴백 + 회귀 테스트. **폴백을 빼면 `ValueError: 56 is not in list`로 재현됨을 증명** |
| 테스트 0건 3곳 | `test_llm_keys.py`(SSRF 15개)·`test_cleanup.py`(2개)·댓글 삭제 인가(5개) 신설 |
| 주석뿐이던 불변식 | `upload_image`가 `def`인지 · toggle-pro의 낡은 `pro_until` |
| 이름값 못 하던 테스트 | 결제 실패가 `Payment.status`를 실제로 읽게 |
| `ci.yml:106` | glob → find (9개 → **10개**, `scripts/lib/ec2.sh` 포함) |
| README·RECOVERY·IR·ECS 런북·PROGRESS 상단 | 원문 자리에서 `<ins>` 정정 |

**remark-gfm은 안 넣었다.** 실측하니 GFM을 쓰는 발행 글이 **0건**이고(`~~`로 걸린
2건은 본문에 적힌 코드펜스 기호였다 — 최초 보고가 틀렸다) 넣으면 gzip **+11.2 KB**다.
대신 `gen-static.mjs`에 빌드 가드를 뒀다. 첫 판이 코드펜스 안의 인용을 물어 오탐을
냈고(이 저장소가 반복 지적한 그 병) 코드블록을 걷어내 다시 증명했다.

**안 한 것** — 프론트 사용자 공백 10건(로딩 상태·OG 태그·접근성·모바일),
`blog-app-secrets` 정리, AI 토큰 캡, 감시 하트비트, `cleanup.py` 로깅.

---

## 우선순위

| 순위 | 항목 | 비용 | 근거 |
|---|---|---|---|
| 1 | 삭제된 이미지 2개 복구 + `watch.sh:205` `src_n==0 && dst_n>0` → fail | 10분 | 데이터 손실이 실제로 났고 감시가 12일간 못 봤다 |
| 2 | `watch.sh:157,178` 종료코드 확인 | 10분 | 같은 파일 4곳이 이미 이 패턴이다 |
| 3 | `posts.py:242` 폴백 + 회귀 테스트 | 20분 | 500 text/plain, 세 번 없앤 모양 |
| 4 | 테스트 3개(`uploads` def 1줄 · `pro_until` · 결제 status 단언 2줄) | 30분 | 전부 기존 픽스처로 됨. 사고 기록이 코드에 있는데 안 잠겨 있다 |
| 5 | `README.md:77` 첫 사용 절차 | 10분 | 공개 저장소의 정문이 막혀 있다 |
| 6 | `RECOVERY.md:137` tfvars에 `alert_email` 추가 | 5분 | 런북대로 하면 알림이 사라진다 |
| 7 | `ci.yml:106` glob → find | 2분 | 주석이 "닫았다"고 적은 구멍 |
| 8 | 댓글 삭제 · `cleanup` · SSRF 테스트 | 1~2시간 | 인가·데이터손실·SSRF |
| 9 | `incident-response.md:78` · `PROGRESS.md` 상단 · `ecs-migration-plan.md` 정정 | 30분 | **원문 자리에서** `<ins>` 방식으로 |
| 10 | `remark-gfm` 추가 · 프론트 로딩 상태 · OG 태그 | 반나절 | 사용자가 실제로 겪는 것 |

**정정 방식은 `PROGRESS.md:1405`와 `ROADMAP.md:52-58`이 이미 정한 대로** — 원문 자리에
`<ins>(날짜 — 정정)</ins>`. 밑에 새 줄을 붙이는 것으로는 낡은 줄이 안 죽는다.
