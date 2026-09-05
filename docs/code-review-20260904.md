# 코드 검사 2026-09-04 — 품질·기능 공백

7갈래 병렬 탐색 + 갈래마다 **반박 검증**(다른 에이전트가 실제 파일을 열어 기각을 시도)으로
돌렸다. 검증을 통과한 것만 아래 본문에 싣고, 떨어진 것은 사유와 함께 맨 뒤에 남긴다 —
"무엇을 봤는데 아니었나"가 다음 사람에게는 발견만큼 쓸모 있기 때문이다.

판정 규칙은 **거짓 양성이 거짓 음성보다 비싸다**로 잡았다. 확신이 없으면 기각이다.
사람이 목록을 보고 시간을 쓰는데, 그 시간이 헛되면 다음부터 목록 자체를 안 본다.

## 이 문서를 읽는 법

- `HIGH` = 데이터 손실·보안·**사용자에게 잘못된 사실을 보여줌**·돈
- `MEDIUM` = 특정 조건에서 오동작
- `LOW` = 품질·유지보수. 안 고쳐도 지금 당장 무엇이 깨지진 않는다

각 항목의 **검증**은 반박자가 남긴 판정이다. 괄호 안은 확신도.

> ⚠️ 이 문서에 시험용 IP를 적을 때는 마지막 옥텟을 `N`으로 둔다.
> `check_publish_secrets.py`가 저장소 전체 마크다운을 보므로, 온전한 IP를 적으면
> 이 문서 때문에 CI가 빨개진다. (그 검사가 못 잡는 형태를 다루는 문서라 더 그렇다)

---

## 전체 요약

| 부 | 갈래 | 탐색 | 생존 | 기각 |
|---|---|---|---|---|
| 1부 | 백엔드 정확성 · 프론트 정확성 · 운영 · 기능 공백 | 41 | 34 | 7 |
| 2부 | 백엔드 보안 · 백엔드 품질/테스트 · 프론트 품질/접근성 | 31 | 30 | 1 |
| **합계** | **7갈래** | **72** | **64** | **8** |

심각도(생존 기준): 🔴 HIGH 1 · 🟠 MEDIUM 18 · 🟡 LOW 45.

**가장 자주 나온 모양은 "검사·주석이 자기 대상을 못 본다"였다.** OPS-1(시크릿 검사가
IP의 흔한 누출 형태를 통과), BQ-10(alembic check 가 server_default 드리프트를 못 보는데
주석은 본다고 적혀 있음), BQ-6(NUL 가드 '전수 목록'에 series 누락), SEC-04·SEC-05(주석이
코드와 정면으로 다름)가 전부 같은 부류다. 이 저장소가 스스로 여러 번 이름 붙인
'검사인 척하는 검사'가 이번에도 최다 유형이다.

---

## 1부 — 정확성·운영·기능 공백 (4갈래)

탐색 41건 → **생존 34건 · 기각 7건**  (high 1 · medium 9 · low 24)


## 🔴 HIGH — 1건

### OPS-1 · 발행물 시크릿 검사가 `user@IP`·`http://IP`·`KEY=IP` 꼴의 공인 IP를 통과시킨다

> ✅ **2026-09-05에 고쳤다.** 예외를 "앞 글자가 영숫자·`.`이거나 앞이 `==`로 끝날 때"로
> 좁히고, `SELFTEST_HITS`에 통과하던 네 형태를 전부 넣었다. 되돌리면 자가검증이 그 넷에서
> 실패하는 것까지 확인했다. 좁힌 뒤 저장소 전체를 다시 훑어 신규 히트는 0건이다.
> 아래 본문은 발견 당시의 기록으로 그대로 둔다.

`scripts/check_publish_secrets.py:129` — 운영(스크립트·terraform·CI) · security

버전 문자열 오탐을 줄이려는 `_VERSIONISH` 예외(:91)가 IP 바로 앞 글자가 `@ / = :` 이면 검사를 건너뛴다. 터미널 출력에서 IP가 가장 흔하게 나타나는 모양이 정확히 그 셋이라, 이 검사가 막겠다고 선언한 집 공인 IP·EC2 IP가 그 형태로 실리면 CI는 '실제 값 0건'으로 초록이다. 자가검증(:154)은 공백 앞 형태 하나만 넣어서 이 구멍을 못 본다.

**근거** scratchpad에 7줄을 만들어 `python3 scripts/check_publish_secrets.py <파일>`로 실측: `ssh -i key.pem ec2-user@198.18.0.N`, `curl http://198.18.0.N:8000/api/status`, `PUBLIC_IP=198.18.0.N`, `host=198.18.0.N` 넷은 통과, `PublicIp: 198.18.0.N`·`"PublicIpAddress": "198.18.0.N"`·`접속 주소는 198.18.0.N 이었다` 셋만 차단(3건). :91 `_VERSIONISH = re.compile(r"[A-Za-z=/@:._-]$")`, :129 `if m.start() and _VERSIONISH.search(line[m.start() - 1]): continue`. ci.yml:225-229는 이 스크립트를 저장소 전체 마크다운에 돌리고 통과를 '실제 값 0건'이라는 사실로 적는다.

**고침** 버전 예외는 앞 글자가 영숫자·`.`·`_`·`-`일 때(`pretendard==1.2.3.4`, `python3.12.4.1`)만 두고 `@ / = :`는 예외에서 뺀다. 필요하면 '앞 글자가 `=`이고 그 앞 낱말이 버전 키워드(`==`, `v`)'만 따로 허용. SELFTEST_HITS에 `ssh user@198.18.0.N`, `http://198.18.0.N/`, `HOST=198.18.0.N` 세 줄을 넣어 자가검증이 이 형태를 지키게 한다. 수정 뒤 `git ls-files '*.md'` 전체를 다시 돌려 새로 걸리는 건수를 센다.

**검증** (high) scratchpad 파일로 실측했더니 `ssh ec2-user@198.18.0.N`·`curl http://198.18.0.N:8000`·`PUBLIC_IP=198.18.0.N`·`host=198.18.0.N` 네 줄이 전부 통과하고 공백 앞 형태 3건만 잡혔으며, check_publish_secrets.py:91의 `_VERSIONISH=[A-Za-z=/@:._-]$`와 :129의 continue가 근거대로 실재하고 ci.yml:226-229가 이 결과를 '실제 값 0건'이라는 사실 주장으로 쓰고 있다.


## 🟠 MEDIUM — 9건

### BE-1 · 푸시 발송 결과 ok가 HTTP 4xx/5xx 응답도 '성공'으로 센다

> ✅ **2026-09-05에 고쳤다.** `PushFailed` 예외를 만들어 4xx·5xx 거절을 성공과 갈랐고,
> 발송 기록에 `failed` 를 담아 관리자 화면이 '실패 N대'를 그린다. 시도 전부가 실패면
> 서버 쪽(VAPID 키 불일치)을 보라는 안내도 붙였다. 테스트 2개로 잠갔다.

`backend/app/services/push.py:573` — 백엔드 정확성 · correctness

send_push는 404/410만 PushGone으로 던지고 그 외 4xx/5xx는 로그만 남기고 정상 반환한다. _deliver는 예외가 없으면 ok += 1 하므로 401·403·400·413·429·5xx 전부가 성공으로 집계되고, 관리자 화면이 그 값을 'N대 성공'(초록)으로 보여준다.

**근거** push.py:440-448 — `if res.status_code in (404, 410): raise PushGone` / `if res.status_code >= 400: logger.warning(...)` 후 return None. push.py:571-573 — `send_push(...)` 다음 줄에서 `ok += 1`. 553-555 주석은 '시도와 성공을 가른다 … 벤더가 무응답이면 실제 수신은 0대'라고 하지만 가른 것은 예외(타임아웃)뿐이다. frontend/src/pages/AdminPage.tsx:551-556 — `ok < tried`일 때만 빨강, 아니면 `{ok}대 성공` 초록. 시나리오: VAPID 키 불일치·서비스워커 키 교체 → 전 기기 401/403 → 대시보드는 '3대 중 3대 성공'. 이 화면의 존재 이유('지금 알림이 나가고 있나', 302-313 주석)가 정확히 이 경우인데 거짓 초록이 뜬다.

**고침** send_push가 2xx일 때만 True를 돌려주거나(또는 PushFailed 예외를 던지고) _deliver에서 그때만 ok += 1. _last_delivery에 failed 카운트를 따로 담아 화면이 '실패 N대'를 그리게 한다. tests/test_push.py에 401 응답 케이스 추가.

**검증** (high) 줄 번호는 밀렸지만(실제 194-201·310-313·324-327) 인용 코드가 전부 실재하고, send_push가 404/410 외 4xx/5xx에 로그만 남기고 None을 반환해 _deliver의 ok가 증가하는 것을 확인했으며 AdminPage.tsx:551-556이 그 값을 초록 'N대 성공'으로 그리는 것도 그대로였다 — tests/test_push.py의 flaky 케이스가 예외로만 실패를 흉내내 이 갈래가 아예 안 덮인 것까지 확인해 살린다(다만 오작동은 푸시가 이미 깨진 조건에서 관리자 화면만 속이므로 medium).

### BE-2 · 구독 신청 취소·거절 후에도 '구독 신청' 알림이 남아 빈 화면으로 안내한다

> ✅ **2026-09-05에 고쳤다.** `_drop_request_notification()`(user_id·actor_id·post_id IS NULL
> 셋을 다 맞춘 delete)을 취소·거절·**승인** 세 자리에서 같은 트랜잭션에 부른다. 승인은
> 이 보고서가 지목하지 않았지만 남는 줄은 같다 — 승인된 뒤에도 `my_requests`는
> approved=false 만 주므로 그 알림을 누르면 화면이 똑같이 비어 있다. 시험 5개로 잠갔고,
> 되돌리면 다섯이 전부 실패하는 것까지 확인했다.

`backend/app/routers/subscriptions.py:209` — 백엔드 정확성 · correctness

subscribe가 만든 Notification(post_id NULL, actor_id=신청자)은 author_subscriptions와 FK가 없어서, 신청자가 취소(DELETE /subscriptions/{author_id})하거나 글쓴이가 거절하면 구독 행만 지워지고 알림은 안 읽음 상태로 남는다. 취소→재신청을 반복하면 같은 사람의 알림이 계속 쌓인다.

**근거** subscriptions.py:184 `db.add(Notification(user_id=data.author_id, actor_id=user.id))`. subscriptions.py:200-211 unsubscribe·263-274 reject_request는 `db.delete(sub)`만 한다. models/notification.py:143-145 actor_id는 users FK(CASCADE)이지 구독 행과 무관. frontend/src/components/NotificationBell.tsx:143 — post_id가 null이면 '눌러서 승인하거나 거절할 수 있어'를 띄우고 구독 페이지로 보내는데, my_requests(subscriptions.py:220-232)는 approved=false 행만 주므로 목록이 비어 있다. 종 배지 unread(notifications.py:302-314)는 post_id IS NULL 알림을 면제하므로 이 행이 배지 숫자에도 계속 들어간다. 댓글 알림은 같은 문제를 FK CASCADE로 막았다(notification.py:146-150 주석 '종에는 남아 있는데 눌러도 아무 데도 안 가는 줄').

**고침** unsubscribe·reject_request에서 `delete(Notification).where(user_id==author_id, actor_id==subscriber_id, post_id.is_(None))`를 같은 트랜잭션에 넣는다. 또는 subscribe에서 같은 (user_id, actor_id, post_id NULL) 미읽음 알림이 있으면 새로 만들지 않는다.

**검증** (high) subscriptions.py:184가 만든 post_id NULL 알림을 unsubscribe(201-211)·reject_request(264-274)가 지우지 않고 models/notification.py에 author_subscriptions 쪽 FK가 없으며 notifications.py:131이 post_id IS NULL을 unread에 포함하는 것을 확인했다 — 같은 파일 42-43행이 '안 지우면 종에는 남아 있는데 눌러도 아무 데도 안 가는 줄'이라며 댓글 알림엔 CASCADE를 건 바로 그 결함이 구독 신청 알림에만 남아 있다.

### FE-1 · http.ts가 호출부의 AbortSignal을 덮어써 AI 초안 90초 안전장치가 죽어 있다

> ✅ **2026-09-05에 고쳤다.** `request()` 가 호출부 signal 을 함께 듣게 하고, **우리 상한이
> 끊은 것과 호출부가 끊은 것을 갈랐다**. 호출부의 abort 는 그대로 올려보내므로 `ai.ts` 의
> AbortError 분기가 살아났고, `ServerAsleepError` 는 '네트워크 문제' 문구로 덮지 않고
> 그대로 던진다. 테스트 3개로 잠갔다.

`frontend/src/api/http.ts:121` — 프론트 정확성 · correctness

request()가 `{ ...init, signal: ac.signal }`로 caller의 signal을 자기 것으로 바꾼다. apiFetch는 timeoutMs=null이라 그 signal은 영영 abort되지 않는다. ai.ts generateDraft가 넘기는 90초 타이머(ai.ts:79,86)는 연결되지 않은 컨트롤러를 abort할 뿐이다.

**근거** http.ts:121 `fetch(url, { ...init, signal: ac.signal })`. ai.ts:82-86은 `signal: ctrl.signal`을 apiFetch에 넘기고 :79에서 90초 뒤 `ctrl.abort()`. 덮어써지므로 fetch는 취소되지 않는다. 또 http.ts:135-137이 AbortError를 ServerAsleepError로 바꾸므로 ai.ts:90의 AbortError 분기는 도달 불가이고, 절전 예외는 :92 '네트워크 문제로 초안 생성에 실패했어'로 잘못 안내된다(WritePostPage aiError로 그대로 표시). ai.ts:76 주석 '90초 안전장치'와 실제 동작이 다르다.

**고침** request()에서 caller signal이 있으면 함께 듣는다(AbortSignal.any 또는 init.signal.addEventListener('abort', () => ac.abort())). ai.ts catch에서 ServerAsleepError는 그대로 다시 던진다.

**검증** (high) http.ts:121 `fetch(url, { ...init, signal: ac.signal })`가 호출부 signal을 실제로 덮어쓰는 것을 확인했고, ai.ts:78-86의 90초 컨트롤러는 fetch에 연결되지 않아 주석이 약속한 안전장치가 죽어 있으며 :90의 AbortError 분기도 도달 불가다.

### FE-2 · AI 초안이 60초를 넘겨 504가 오면 앱 전체가 60초간 '절전'으로 잠긴다

> ✅ **2026-09-05에 고쳤다.** 5xx 를 상태코드만으로 절전이라 하지 않는다. 응답이 JSON 이면
> 앱이 대답한 것이라 절전이 아니고, 5초를 넘겨 온 5xx 는 오리진이 살아서 붙잡고 있었다는
> 뜻이라 기억하지 않는다(주차된 오리진은 1초 남짓에 실패한다). 테스트 4개로 잠갔다.
>
> 이 자리를 고치다 **보고서에 없던 것**을 하나 더 찾았다. `isAsleepStatus` 가 503 도 접는
> 바람에, 백엔드가 내는 서로 다른 503 셋을 구분해 안내하려고 08-11 에 넣은 `ai.ts` 의
> 코드가 09-02 이후 **도달 불가**였다. 사용자는 'BYOK 키를 다시 등록해줘' 대신 '서버가
> 절전 중이야'를 보고 있었다. 같은 고침으로 살아났다.

`frontend/src/api/http.ts:122` — 프론트 정확성 · correctness

CloudFront origin_read_timeout(60초)에 걸린 AI 초안 요청의 504를 request()가 절전으로 기억한다. 이후 60초 동안 글 저장·업로드를 포함한 모든 요청이 서버에 가지 않고 즉시 '서버가 절전 중이야'로 거절된다. 서버는 켜져 있고 사용자는 방금 그 서버와 대화한 상태다.

**근거** http.ts:122-125 `isAsleepStatus(504)`면 `asleepAt = Date.now()` 후 throw. :117은 knownAsleep()이면 **보내지도 않고** throw(60초, :60). ai.ts:82 generateDraft는 같은 request()를 탄다. WritePostPage.tsx:516은 '생성에 길면 1분쯤 걸려'라고 안내하고, terraform/cloudfront.tf:134 `origin_read_timeout = 60`, alb.tf:19도 'AI 초안 생성이 최대 60초'라 적어 60초 초과가 예정된 경로다. 초안이 60초를 넘긴 직후 '글 작성'을 누르면 handleSubmit(:433-436)의 createPost가 http.ts:117에서 바로 거절된다.

**고침** AI 초안처럼 오래 걸리는 쓰기 요청은 504를 절전 판정에서 제외한다(request에 옵션을 두거나 ai.ts에서 forgetAsleep() 후 별도 문구). 또는 절전 판정을 GET/짧은 타임아웃 요청에만 적용한다.

**검증** (high) http.ts:122-125가 504를 무조건 절전으로 기억하고 :117이 60초간 쓰기까지 안 보내고 거절하는데, cloudfront.tf origin_read_timeout=60·alb.tf 주석·WritePostPage의 '길면 1분' 안내가 60초 초과를 예정된 경로로 두고 있어 서버가 깬 상태에서 글 저장이 '절전 중'으로 막힌다.

### FE-3 · session.ts가 localStorage를 무방비로 읽어 저장소 차단 브라우저에서 익명 읽기까지 실패한다

> ✅ **2026-09-05에 고쳤다.** `getToken`·`setToken`·`clearToken` 셋을 try/catch로 감쌌다
> (skin.ts `cached()`와 같은 방식). 실패는 '토큰 없음'으로 접으므로 저장소가 막힌
> 브라우저에서도 익명 조회는 그대로 나간다. 저장소가 던지는 상황을 만든 테스트 3개로 잠갔다.

`frontend/src/api/session.ts:18` — 프론트 정확성 · correctness

이 저장소는 localStorage 접근 자체가 throw할 수 있다고 전제하고(http.ts:55, WritePostPage:59, skin.ts:55) 다른 곳은 전부 try/catch로 감쌌지만 getToken/authHeaders는 안 감쌌다. 토큰이 필요 없는 목록 조회도 authHeaders()를 부르므로 그 브라우저에서는 글 목록이 SecurityError 문구의 빨간 에러가 된다.

**근거** session.ts:17-19 `return localStorage.getItem(TOKEN_KEY)` try/catch 없음. :30-33 authHeaders()가 그걸 부른다. posts.ts:34 fetchPosts는 익명이어도 `headers: authHeaders()`를 만든다 → throw → HomePage.tsx:73-78 catch가 `e.message`(브라우저의 영문 SecurityError 문구)를 화면에 그린다. AuthProvider.tsx:16-20의 부팅 fetchMe도 getToken(auth.ts:193)에서 던져 unhandled rejection이 된다. 반면 skin.ts:88-96, WritePostPage.tsx:61-89는 같은 API를 try/catch로 감싼다.

**고침** getToken/setToken/clearToken을 try/catch로 감싸고 실패 시 null/no-op으로 처리한다(skin.ts cached()와 같은 방식).

**검증** (medium) session.ts:17-19 getToken/authHeaders만 try/catch가 없고 posts.ts:34가 익명 조회에도 그걸 부르는 게 맞으며, 같은 저장소가 skin.ts cached()·WritePostPage readDraft에서 'localStorage 접근 자체가 throw한다'를 전제로 감싸고 있어 예외가 아니라 누락이다.

### FE-5 · 구독 화면이 조회 실패·절전 때 '구독할 수 있는 다른 글쓴이가 아직 없어'라는 거짓 사실을 보여준다

> ✅ **2026-09-05에 고쳤다.** `fetchAuthors`가 `!ok`에서 던지고(`failWith`), 화면은
> `authors: SubscribedAuthor[] | null`로 '아직 모른다'를 따로 들고 절전·실패를 갈라
> 안내한다. 첫 화면 테스트(`SubscriptionsPage.test.tsx`) 4개로 잠갔고, 되돌리면
> 500 갈래가 실패하는 것까지 확인했다.

`frontend/src/pages/SubscriptionsPage.tsx:154` — 프론트 정확성 · correctness

fetchAuthors는 !res.ok면 []를 주고 페이지도 catch에서 []로 접는다. loaded/asleep 구분이 없어 서버가 꺼져 있거나 401·5xx면 빈 배열과 '아직 없어'가 사실처럼 뜬다. Layout에는 전역 절전 안내가 없어 이 문장만 남는다. HomePage·AdminPage는 같은 문제를 loaded 플래그로 막았다고 주석에 적어뒀는데 이 화면만 없다.

**근거** SubscriptionsPage.tsx:38 `fetchAuthors().then(setAuthors).catch(() => setAuthors([]))`, :154-157 `authors.length === 0` → '구독할 수 있는 다른 글쓴이가 아직 없어.'. subscriptions.ts:70-74 fetchAuthors는 `if (!res.ok) return []`. 같은 파일 :66-69 주석이 '1분을 기다린 끝에 거짓 사실을 보는 셈'이라 적고 타임아웃만 8초로 줄였다 — 거짓 문장 자체는 그대로다. Layout.tsx에는 sessionEnded 배너(:123)만 있고 AsleepNotice가 없다. HomePage.tsx:40-45 주석은 '0개는 사실 주장이다'라며 loaded를 둔다.

**고침** authors를 `null | SubscribedAuthor[]`로 두고 실패·절전을 상태로 받아 안내한다(HomePage의 loaded/asleep 방식). fetchAuthors는 !ok에서 throw하거나 asleep을 구분해 돌려준다.

**검증** (high) subscriptions.ts fetchAuthors가 !ok에서 []를 주고 SubscriptionsPage:38이 catch로도 []를 넣어 :154의 '구독할 수 있는 다른 글쓴이가 아직 없어'가 실패 상태에서 사실처럼 뜨는 게 맞고, 같은 파일 주석이 '거짓 사실'이라 적고도 타임아웃만 줄여 문장 자체는 남아 있다.

### FE-6 · PostDetailPage 구독 여부·댓글 갱신 응답에 취소 플래그가 없어 다른 글의 상태가 덮인다

> ✅ **2026-09-05에 고쳤다.** 구독 여부 effect에 `alive` 플래그와 cleanup을 넣고, 댓글
> 작성·삭제 뒤의 재조회는 `shownPostId` ref와 요청 시점의 postId를 비교한 뒤에만
> setState한다. 같은 파일이 본문·댓글 첫 조회에 이미 세워둔 규칙을 세 자리에 마저 적용한 것이다.

`frontend/src/pages/PostDetailPage.tsx:191` — 프론트 정확성 · correctness

본문·댓글 첫 조회는 alive 플래그로 늦은 응답을 버리지만, 구독 여부 effect와 댓글 작성·삭제 후 재조회는 그대로 setState한다. A 글에서 B 글로 넘어간 뒤 A의 응답이 오면 B 화면에 A 작성자의 구독 상태나 A의 댓글 목록이 그려진다. 쓰기 요청은 타임아웃이 없어 겹칠 시간이 넉넉하다.

**근거** PostDetailPage.tsx:189-194 `fetchMySubscriptions().then((ids) => setSubscribed(ids.includes(post.owner_id!)))` — cleanup 없음, closure의 post는 A. :135가 리셋에서 subscribed=false를 넣지만 늦은 응답이 그 뒤에 다시 true로 만든다(주석이 막으려던 '남의 글에 구독중 ✓'). :219-221 handleAddComment `setComments(await fetchComments(postId))`, :247-248 handleDeleteComment도 같다 — postId는 A로 고정된 채 B 화면에 set. :151-155 주석이 '렌더 중 리셋은 in-flight 요청을 취소하지 못한다 — 둘 다 필요하다'고 스스로 적어둔 규칙이 이 세 곳엔 빠져 있다.

**고침** 구독 effect에 alive 플래그와 cleanup을 넣고, 댓글 갱신 후 setComments 전에 현재 postId와 요청 postId를 비교한다(또는 요청 seq).

**검증** (medium) PostDetailPage:189-194 구독 effect와 :219·:247 댓글 재조회에 alive/postId 검사가 없는 것을 확인했고, 같은 파일 :148-152 주석이 '렌더 중 리셋은 in-flight 요청을 취소하지 못한다 — 둘 다 필요하다'는 규칙을 스스로 적어 둔 자리라 누락이 맞다(다만 글쓴이가 다를 때만 눈에 보인다).

### FE-7 · 수정 모드에서 늦게 온 getPost 응답이 복구한 초안·입력 중인 내용을 덮어쓴다

> ✅ **2026-09-05에 고쳤다.** `alive` 취소 플래그와 `formTouched` 를 넣어, 사용자가
> '이어서 쓰기'를 눌렀거나 입력칸을 건드린 뒤에는 늦게 온 응답이 폼을 덮지 않는다.
> 가드를 빼면 새 테스트가 실패하는 것까지 확인했다.

`frontend/src/pages/WritePostPage.tsx:220` — 프론트 정확성 · correctness

복구 배너는 마운트 즉시 뜨고 getPost는 차가운 서버에서 8초까지 걸린다. 그 사이 '이어서 쓰기'를 누르거나 타이핑하면, 응답 도착 시 setTitle/setContent가 서버 본문으로 통째로 갈아끼운다. 언마운트 가드도 없다.

**근거** WritePostPage.tsx:218-239 effect가 getPost 후 조건 없이 setTitle(p.title), setContent(p.content) 등 6개 필드를 덮고 serverSnapshot을 세운다(alive/dirty 검사 없음). :122 recovered는 마운트 시 동기 읽기라 배너가 먼저 뜬다. :475-486 '이어서 쓰기'가 상태를 채우고 serverSnapshot=null로 두는데, 이후 도착한 응답이 그걸 무효화한다. 덮인 뒤 snapshot===serverSnapshot이라 자동보관(:170-181)도 안 돈다 — 화면에서는 소리 없이 사라진다.

**고침** 응답 도착 시 dirty 또는 serverSnapshot===null(복구 적용됨)이면 덮지 않고 안내만 한다. alive 플래그로 언마운트 후 setState를 막는다.

**검증** (medium) WritePostPage:218-238의 getPost 응답이 dirty·serverSnapshot=null 검사 없이 6개 필드를 덮고 alive 가드도 없으며, 복구 배너는 :122에서 동기로 먼저 뜨고 getPost는 8초까지 걸릴 수 있어 '이어서 쓰기'를 누른 내용이 화면에서 소리 없이 서버 본문으로 되돌아간다.

### OPS-3 · 감시 7절(프론트 최신 여부)이 content/about.md·content/infra.json 변경을 못 본다

> ✅ **2026-09-05에 고쳤다.** pathspec 을 `content/devlog/` 에서 `content/` 로 넓혔다.
> 하위 파일을 하나씩 적는 한 새 파일이 생길 때마다 같은 구멍이 다시 열리기 때문이다.
> 실제 히스토리로 확인했다 — `fc3d36c`(infra.json 단독)와 `1151d4d`(about.md 단독)가
> 옛 규칙에서 0, 새 규칙에서 1로 잡힌다.

`scripts/watch.sh:839` — 운영(스크립트·terraform·CI) · ops

'배포 스탬프 커밋 ↔ HEAD 사이에 dist에 영향을 주는 변경이 있는가'를 `frontend/ content/devlog/`만으로 센다. 그런데 정적 빌드는 content/about.md(→/about.html·/about.md)와 content/infra.json(→/infra.html)도 읽는다. 이 둘만 고친 커밋은 산출물이 바뀌는데도 '✅ 프론트 최신 (그 뒤 프론트 변경 없음)'으로 찍힌다 — 이 절이 잡겠다고 적은 '안 눌러서 옛것이 뜬다'가 그대로 남는다.

**근거** watch.sh:839-841 `behind=$(git rev-list --count "$deployed..HEAD" -- frontend/ content/devlog/ ':!frontend/**/*.test.ts' ':!frontend/**/*.test.tsx' ':!frontend/*.md' ...)`; :849-851 git log도 같은 경로. gen-static.mjs:778 `join(SRC,'..','about.md')`, :1051 `content/infra.json`. `git log --oneline -5 -- content/about.md content/infra.json`에 fc3d36c(인프라 스냅샷 재측정), f8a839c 등 실제로 이 파일만 건드린 커밋이 있다.

**고침** pathspec에 `content/about.md content/infra.json`을 추가한다(:839-841과 :849-851 두 곳 모두). 산출물 입력 경로가 gen-static.mjs 한 곳에서 정해지므로, 그 목록을 주석으로 서로 참조하게 적어 한쪽만 늘어나는 것을 막는다.

**검증** (high) watch.sh:838-840·848-850의 pathspec이 `frontend/ content/devlog/`뿐인데 gen-static.mjs:778의 content/about.md와 :1051의 content/infra.json도 산출물 입력이고, 실제로 fc3d36c(infra.json 단독)·1151d4d(about.md 단독) 커밋이 히스토리에 있어 그 상태에서 감시가 '✅ 프론트 최신'이라는 거짓 사실을 찍는다.


## 🟡 LOW — 24건

### BE-3 · 글 작성이 두 트랜잭션이라 알림 커밋 실패 시 글은 남고 재시도하면 중복 글이 된다

> ✅ **2026-09-05에 고쳤다.** `db.flush()` 로 id 만 받아 알림을 같은 세션에 담고 커밋을
> 한 번만 한다. 실패하면 글도 알림도 없으므로 재시도가 중복을 만들지 않는다.

`backend/app/routers/posts.py:476` — 백엔드 정확성 · correctness

create_post는 글을 먼저 commit(460)하고 구독자 알림을 따로 commit(476)한다. 두 번째 commit이 실패하면(DB 순단→OperationalError 503, 풀 고갈→503) 글은 이미 저장됐는데 클라이언트는 실패 응답을 받고, 재시도하면 같은 글이 두 번 만들어진다. 첫 글의 인앱 알림·백그라운드 메일/푸시는 등록되지 않는다.

**근거** posts.py:459-461 `db.add(post); db.commit(); db.refresh(post)` → 465-476 notify_uids 조회 후 `for uid: db.add(Notification(...))` / `if notify_uids: db.commit()`. 472 주석 '요청 트랜잭션에서 확실히 저장'이라 적혀 있으나 실제로는 별도 트랜잭션이다. 478·483의 background.add_task는 476 예외 시 실행되지 않는다. main.py:163-212 핸들러는 OperationalError·PoolTimeoutError를 503으로 바꿔 프론트가 '다시 시도' 안내를 낸다 — 재시도가 곧 중복 작성이다.

**고침** `db.add(post); db.flush()`로 id만 받고 Notification들을 같은 세션에 add한 뒤 commit 한 번. 그 다음 refresh·백그라운드 등록.

**검증** (medium) posts.py:459-461과 476이 실제로 두 커밋으로 갈려 있고 둘째 커밋 실패 시 글만 남는 것은 맞으나(주석 472의 '요청 트랜잭션'은 백그라운드 대비 표현이지 단일 트랜잭션 주장은 아니다), 창이 SELECT+INSERT 몇 밀리초라 실제로는 첫 커밋이 먼저 실패할 가능성이 훨씬 크고 결과도 지울 수 있는 중복 글 하나라 low로 내린다.

### BE-4 · 댓글 작성도 댓글 commit과 알림 commit이 분리돼 같은 중복·유실 모양이다

> ✅ **2026-09-05에 고쳤다.** BE-3 과 같은 모양으로 한 커밋에 모았다. '누구에게 알릴
> 것인가'를 bool 이 아니라 `notify_owner_id: int | None` 로 들고 가서, 커밋을 사이에 둔
> 두 번째 분기에서도 타입이 좁혀진 채 남는다(mypy 가 잡아준 자리다).

`backend/app/routers/comments.py:154` — 백엔드 정확성 · correctness

create_comment는 댓글을 commit(140)한 뒤 글쓴이 알림을 따로 commit(154)한다. 두 번째 commit 실패 시 댓글은 저장됐지만 5xx가 나가고, 익명 사용자가 다시 누르면 같은 댓글이 두 개가 된다. 알림·푸시(158)는 첫 댓글에 대해 만들어지지 않는다.

**근거** comments.py:139-141 `db.add(comment); db.commit(); db.refresh(comment)` → 149-154 `db.add(Notification(... comment_id=comment.id)); db.commit()`. 150 주석 '요청 트랜잭션에서 확실히 저장(새 글 알림과 같은 방침)' — BE-3과 같은 오해. 익명 댓글은 IP당 20/시간(105)이라 재시도 여지가 충분하고, 중복 댓글을 지울 수 있는 사람은 글쓴이·관리자뿐이다(166-181).

**고침** BE-3과 같다: flush로 comment.id를 얻고 Notification을 같은 세션에 add한 뒤 commit 한 번.

**검증** (medium) comments.py:139-141과 149-154가 인용대로 두 커밋이고 삭제 권한이 글쓴이·관리자뿐인 것(166-180)도 맞아 BE-3과 같은 원자성 결함이 실재하나, 재현 창이 극히 좁고 피해가 중복 댓글 한 건이라 medium은 과하다.

### BE-5 · 공백만 든 검색어가 min_length를 통과해 ILIKE '%%' 전체 스캔이 된다

> ✅ **2026-09-05에 고쳤다.** 핸들러 초입에서 `q` 를 strip 해 정규화하고 2자 미만이면
> 검색 필터를 걸지 않는다. 시험 둘로 잠갔다 — 공백만이면 전체 목록과 같고, 앞뒤 공백은
> 털어서 검색한다.

`backend/app/routers/posts.py:274` — 백엔드 정확성 · correctness

q의 min_length=2는 strip 전 길이를 세고, 필터는 `q.strip()`을 쓴다. `?q=%20%20`은 검증을 통과하고 `if q:`도 참이라 패턴이 '%%'가 되어 title·content ILIKE가 전 행에 걸린다 — _like_escape 주석이 막으려던 '와일드카드만 보내 인덱스를 못 타는 무거운 스캔'이 공백으로 그대로 재현된다.

**근거** posts.py:210 `Query(None, min_length=2, max_length=100)`; 271 `if q:`; 274 `pattern = f"%{_like_escape(q.strip())}%"` → strip 결과가 빈 문자열이면 '%%'. 196-202 _like_escape 주석: "q='%'가 전체 매칭이 되고 … 인덱스를 못 타 무거운 스캔이 된다". 무인증 60/분(207)으로 반복 가능. 결과 자체는 '전체 목록'이라 틀리진 않지만 content trigram 인덱스를 못 타는 스캔이 매 요청 돈다.

**고침** 핸들러 초입에서 `q = q.strip() if q else None`으로 정규화하고 2자 미만이면 필터를 무시하거나 422를 낸다.

**검증** (medium) posts.py:210의 min_length=2가 strip 전 길이를 세고 271-274가 q.strip()으로 패턴을 만들어 '  ' 두 칸이 검증을 통과해 ILIKE '%%'가 되는 것을 확인했고 _like_escape 주석(196-201)이 막으려던 바로 그 무거운 스캔이라, 결과 자체는 틀리지 않으므로 low가 맞다.

### BE-6 · 업타임 '전체 N회 점검'이 표에 안 그려지는 하루치 점검까지 합산한다

> ✅ **2026-09-05에 고쳤다.** `date_list` 에 있는 날짜의 total 만 합산한다. 표 안과 표 밖
> (today-days)에 각각 한 줄씩 심어 두고 머리글 숫자와 각 줄 합계가 같은지 보는 시험을
> 붙였고, 되돌리면 그 시험이 실패하는 것까지 확인했다.

`backend/app/services/status.py:357` — 백엔드 정확성 · correctness

since는 '지금 - days일'이라 today-days 날짜의 일부(현재 시각 이후)가 집계에 들어오는데, date_list는 today-(days-1)부터 시작해 그 날은 어느 줄에도 안 그려진다. total_checks는 by_date 전체를 합치므로 화면의 '전체 N회'가 각 줄의 checks 합보다 최대 1,439회 크다.

**근거** status.py:305 `since = datetime.now(UTC) - timedelta(days=days)`; 325 `date_list = [(today - timedelta(days=i)) for i in range(days-1, -1, -1)]` → days개; 357 `total_checks = sum(rec['total'] for rec in by_date.values())` — date_list와 무관하게 전부 합산. frontend/src/pages/StatusPage.tsx:202 '전체 {total_checks}회 점검'. 예: days=30, 지금 UTC 00:01이면 today-30 날짜의 1,439회가 표에는 없고 합계에는 있다.

**고침** since를 date_list[0]의 00:00 UTC로 잡거나, total_checks를 date_list에 있는 날짜의 total만 합산한다.

**검증** (high) since=now-days(305)와 date_list=today-(days-1)부터(326)가 실제로 어긋나고 total_checks(357)만 by_date 전체를 합산해 StatusPage.tsx:202의 '전체 N회 점검'이 각 줄 합계보다 최대 하루치 크지만, 서비스별 uptime은 date_list만 쓰므로 틀리는 건 머리글 숫자 하나뿐이다.

### BE-7 · set_notify: commit 뒤 sub 속성 재로드가 같은 창에서 500이 될 수 있다

> ✅ **2026-09-05에 고쳤다.** 커밋 전에 `approved, notify` 를 지역변수로 떠두고 응답을
> 그 값으로 만든다. 바로 아래 author=None 방어가 막으려던 것과 같은 창인데 그보다 먼저
> 터지던 자리였다.

`backend/app/routers/subscriptions.py:105` — 백엔드 정확성 · correctness

db.commit()으로 sub가 expire되고, 응답에서 sub.approved·sub.notify를 읽을 때 SELECT가 다시 나간다. 그 사이 글쓴이 삭제(CASCADE로 구독 행 삭제)가 끼면 ObjectDeletedError로 500이다. 바로 위 주석이 같은 창을 근거로 author None을 방어했는데 sub는 방어하지 않았다.

**근거** subscriptions.py:95-96 `sub.notify = data.notify; db.commit()` → 97 `author = db.get(User, author_id)` → 100-104 주석 '위에서 sub을 읽고 commit한 뒤라 그 사이 삭제가 끼면 None … 방어는 한 글자다' → 105-106 `sub.approved`, `sub.notify` (expire_on_commit 기본값이라 재조회). 같은 창, 같은 삭제, 다른 결과.

**고침** commit 전에 `approved, notify = sub.approved, data.notify`로 값을 잡아두고 응답은 그 지역변수로 만든다.

**검증** (medium) core/database.py:83의 sessionmaker가 expire_on_commit 기본값이라 commit(96) 뒤 sub.approved(105)가 재조회를 일으키는 것이 맞고, 그 사이 글쓴이 삭제가 끼면 100-104 주석이 방어한 author=None보다 먼저 ObjectDeletedError가 나 그 방어가 무용지물이 되는 지적이 정확하다 — 다만 관리자만 만들 수 있는 매우 좁은 창이라 low.

### FE-10 · 서비스워커 회수 스위치가 SPA만 쓰는 기기에서는 영영 확인되지 않는다

`frontend/public/sw.js:155` — 프론트 정확성 · ops

maybeCheckKillSwitch()는 network-first 분기에서만 불린다. `/`, `/blog/...`(network-only)와 해시 자산(cache-first)은 그 전에 return하므로 정적 .html을 한 번도 안 여는 기기는 activate 이후 /sw-kill.json을 다시 읽지 않는다. 주석의 '모든 기기가 10분 안에'와 어긋나고, 테스트도 .html 이동만 잰다.

**근거** sw.js:138 `if (route === 'network-only') return`, :140-152 cache-first 분기 return, :155 maybeCheckKillSwitch()는 그 아래. :87 `/`·`/index.html`은 network-only. :30 주석 '모든 기기가 **10분 안에** … 등록해제한다'. sw.test.ts:306-309 등 회수 테스트는 전부 `/devlog.html`·`/lessons.html`·`/rss.xml`로만 handle한다.

**고침** maybeCheckKillSwitch()를 fetch 핸들러 맨 앞(GET 판정 직후)으로 올리고, network-only 경로 이동에서도 확인되는 테스트를 추가한다.

**검증** (high) sw.js:138의 network-only return과 :140-152 cache-first return이 :155 maybeCheckKillSwitch()보다 앞에 있어 `/`·SPA 경로(그 밖=network-only)만 도는 기기는 .html을 열기 전까지 회수 스위치를 안 읽는 게 맞고, :30 주석의 '모든 기기가 10분 안에'와 어긋난다.

### FE-11 · 글 작성 버튼이 제목·본문이 비면 아무 말 없이 무시된다

`frontend/src/pages/WritePostPage.tsx:419` — 프론트 정확성 · quality

handleSubmit이 빈 제목/본문에서 조용히 return한다. 버튼은 활성 상태라 눌러도 아무 일이 없고 error도 안 뜬다. 댓글 폼(PostDetailPage:621)은 disabled로 이유를 보여준다.

**근거** WritePostPage.tsx:419 `if (!title.trim() || !content.trim()) return`, :796 submit 버튼은 `disabled={saving}`만. 서버 422 문구(posts.ts:103 '빈칸은 안 돼')는 여기까지 못 온다.

**고침** 버튼을 `disabled={saving || !title.trim() || !content.trim()}`로 하거나 return 전에 setError('제목과 본문을 적어줘').

**검증** (high) WritePostPage:419의 조용한 return을 확인했고 제목·본문 input에 required도 없으며 :796 버튼은 disabled={saving}뿐이라, 같은 저장소의 댓글 폼(PostDetailPage:622 `disabled={posting || !text.trim()}`)과 달리 이유 없이 아무 일도 안 일어난다.

### FE-12 · AI 가드 섹션은 조회 실패 시 섹션째 사라져 '없음'과 '못 불러옴'이 구분되지 않는다

`frontend/src/pages/AdminPage.tsx:128` — 프론트 정확성 · quality

바로 아래 AiUsageSection은 실패를 '지금은 못 불러왔어'로 말하는데 AiGuardSection은 failed면 null을 그린다. 주석이 '비어 있음 자체가 정보다'라고 하지만, 관리자는 섹션이 없는 것을 정상으로 읽는다.

**근거** AdminPage.tsx:122-128 `.catch(() => setFailed(true))` 후 `if (failed || !data) return null`. :178-189 AiUsageSection은 failed일 때 안내 문단을 그린다. :116 주석 '비어 있음 자체가 정보다'.

**고침** AiUsageSection과 같은 실패 문단을 그린다.

**검증** (medium) AdminPage:128 `if (failed || !data) return null`과 :178-186 AiUsageSection의 실패 문단 차이를 확인했고 :116 주석은 '항목이 비어 있음'에 대한 말이라 실패 경로를 정당화하지 않지만, 서버 정지 때는 사용자 목록 error와 AI 사용량 문구가 이미 신호를 주므로 이 엔드포인트만 실패할 때에 한정된 작은 결함이다.

### FE-14 · 비밀번호 찾기·재설정 폼에 진행 중 가드가 없어 연타가 시간당 리밋을 소모한다

`frontend/src/pages/ForgotPasswordPage.tsx:15` — 프론트 정확성 · quality

LoginPage는 busy로 '자기가 만든 429'를 막았다고 적어뒀는데 같은 모양의 두 폼은 busy도 disabled도 없다. forgot은 5/hour, reset은 20/hour라 연타 몇 번이면 정당한 요청이 429가 된다.

**근거** ForgotPasswordPage.tsx:15-24 handleSubmit에 busy 없음, :47 버튼 disabled 없음. ResetPasswordPage.tsx:16-25, :49 동일. backend auth.py:430 `@limiter.limit("5/hour")`, :459 `"20/hour"`. LoginPage.tsx:16-18 주석과 :22 `if (busy) return`이 선례.

**고침** 두 폼에 busy 상태 + `if (busy) return` + 버튼 disabled/aria-busy를 넣는다.

**검증** (high) ForgotPasswordPage:15-24·:47과 ResetPasswordPage:16-25·:49에 busy도 disabled도 없는 것을 확인했고 backend auth.py:430 5/hour·:459 20/hour 리밋과 LoginPage:16-22의 '자기가 만든 429를 막는다'는 선례가 그대로 있어, 연타가 메일 발송과 리밋을 헛되이 소모한다.

### FE-8 · 관리자 유료 토글이 더블클릭에 두 번 나가 원상복귀된다

`frontend/src/pages/AdminPage.tsx:477` — 프론트 정확성 · correctness

handle()에 진행 중 가드가 없고 버튼도 disabled되지 않는다. toggle-pro는 멱등이 아니라서 빠르게 두 번 누르면 부여→회수가 되어 화면은 잠깐 '유료(Opus)'였다가 원래대로 돌아간다. 관리자는 눌렀는데 안 된 것으로 본다.

**근거** AdminPage.tsx:477-484 `async function handle(id, action)` — busy 상태 없음, 마지막 응답으로 setUsers. :638-640 '유료 부여/회수' 버튼에 disabled 없음. admin.ts:715-722 toggleProUser는 POST /toggle-pro(토글). 같은 파일 InviteSection(:282,:348)은 busy로 막는다.

**고침** 행별 busy(Set<number>)를 두고 진행 중이면 return + 버튼 disabled. 토글 대신 명시적 set(pro=true/false)로 바꾸면 더 안전하다.

**검증** (medium) AdminPage:477의 handle()에 busy 가드가 없고 :636 유료 버튼도 disabled가 없으며 backend admin.py:259-264 toggle_pro가 `user.is_pro = not user.is_pro`인 진짜 토글이라 두 번 나가면 원상복귀되는 건 맞지만, 마지막 응답으로 화면이 실제 상태를 그리므로 잘못된 값이 남지는 않는다(evidence의 admin.ts:715는 201줄짜리 파일이라 오기, 실제는 :54).

### FE-9 · PaymentPage의 '결제 완료!' 문구는 켜질 경로가 없다

`frontend/src/pages/PaymentPage.tsx:84` — 프론트 정확성 · quality

done 상태를 true로 만드는 코드가 없다. setDone(false)만 해지 뒤에 한 번 불린다. 결제 성공은 리다이렉트로 PaymentSuccessPage가 맡으므로 이 분기는 죽은 UI다.

**근거** PaymentPage.tsx:26 `const [done, setDone] = useState(false)`, :84 `setDone(false)`가 유일한 호출. :145-149 `{done && !error && (...결제 완료!...)}`. grep 결과 setDone(true) 없음.

**고침** done 상태와 문구를 지운다(성공 안내는 PaymentSuccessPage가 이미 한다).

**검증** (high) PaymentPage:26·84·145를 직접 확인해 setDone(true)가 파일 어디에도 없고 :145 '결제 완료!' 블록이 켜질 경로가 없는 죽은 UI가 맞다.

### GAP-10 · 결제·인증 화면 테스트 0개, 브라우저 e2e 없음 (알려진 미완 재보고)

`docs/gap-inspection-20260902.md:88` — 기능 공백 · feature-gap

09-02 검사가 이미 적은 항목. 지금도 pages 19개 중 test 는 6개이고 Payment·Login·Register·Forgot·Reset·Verify 화면은 테스트가 없다. e2e 도구는 저장소에 없다.

**근거** ls frontend/src/pages/*.test.tsx → 6개(Author·Home·Portal·PostDetail·Status·WritePost), 페이지 19개. 결제·인증 6 화면 전부 없음. frontend/package.json 과 .github/workflows/ci.yml 에 playwright·cypress·e2e 문자열 0건. docs/gap-inspection-20260902.md:88 이 같은 내용을 low 로 적어뒀다(그때 4/19 → 지금 6/19).

**고침** PaymentPage(confirm 성공·실패·503 절전)와 LoginPage(잠금·401 전역 처리)부터 vitest 로 잡는다. e2e 는 docker compose 스택 위에 playwright 한 시나리오(초대 가입 → 글 작성 → 댓글)만 둬도 회귀를 잡는다.

**검증** (high) pages 19개 중 test 6개(Author·Home·Portal·PostDetail·Status·WritePost)이고 결제·인증 6화면에 테스트가 없으며 e2e 도구도 없는 건 실측으로 맞지만, docs/gap-inspection-20260902.md:88 이 이미 low 로 추적 중인 항목의 재보고라 새 정보는 4/19→6/19 라는 숫자 갱신뿐이다.

### GAP-2 · 관리자 조치(차단·승인취소·계정삭제·Pro 토글)에 감사 기록이 한 줄도 없다

`backend/app/routers/admin.py:274` — 기능 공백 · feature-gap

되돌릴 수 없는 계정 삭제(글·댓글 CASCADE)와 차단·Pro 부여가 누가 언제 했는지 남지 않는다. 초대는 '감사 기록'이라며 지우지 않는데 같은 화면의 나머지 조치는 아무 흔적이 없다.

**근거** backend/app/routers/admin.py 에 logging import 가 없다(grep 'logg' → 0건). delete_user(274-288행)는 Post 를 지우고 user 를 지우며 로그·기록 테이블 쓰기가 없다. ban_user(222)·revoke_user(210)·toggle_pro(259)도 같다. 반면 list_invites docstring(298-310행)은 "'누구를 언제 들였나'가 초대제에서는 감사 기록이다. 지워버리면 그 답을 영영 못 한다"고 적어 기록의 필요를 스스로 인정한다. CloudTrail(PROGRESS.md:1443)은 AWS API 호출만 남기고 앱 안 조치는 못 본다.

**고침** admin_actions 테이블(actor_id, target_user_id, action, at) 하나를 두고 다섯 라우트에서 같은 트랜잭션에 한 줄씩 쓴다. 최소한 logger.info(actor, action, target) 라도 남긴다. 관리자 화면에 최근 조치 목록을 붙이면 초대 목록과 같은 모양이 된다.

**검증** (high) admin.py 전체에 logging import 도 기록 테이블도 없고 delete_user(274)·ban(222)·revoke(210)·toggle_pro(259) 어디에도 흔적이 안 남는 건 사실이나, 관리자 계정이 사실상 1명이라 '누가'는 자명하고 uvicorn 액세스 로그에 경로·시각은 남으므로 운영·유지보수 등급이다.

### GAP-3 · 구독 승인이 나도 신청자는 알림을 못 받는다 — 신청 알림만 있고 승인 알림은 없다

`backend/app/routers/subscriptions.py:252` — 기능 공백 · feature-gap

신청 → 승인 흐름에서 신청은 글쓴이에게 알림을 만들지만 승인은 신청자에게 아무 신호도 안 준다. 신청자는 '승인 대기중'을 언제까지 봐야 하는지 모른다.

**근거** subscribe(subscriptions.py:184행)는 db.add(Notification(user_id=data.author_id, actor_id=user.id)) 로 글쓴이에게 알린다. 그 주석(163-176행)은 "신호가 안 가서 승인이 안 나고 구독자공개 글이 영영 안 열렸다"고 같은 부류의 결함을 설명한다. 그런데 approve_request(252-260행)는 sub.approved = True 와 commit 뿐이고 Notification 삽입이 없다. backend/app/routers/notifications.py:37-38 의 종류 판정도 새 글·새 댓글·구독 신청뿐이라 '승인됨'을 그릴 자리가 없다. frontend/src/pages/SubscriptionsPage.tsx:193 은 신청자에게 '승인 대기중'만 보여준다.

**고침** approve_request 에서 Notification(user_id=subscriber_id, actor_id=author_id, kind='approved') 를 같은 트랜잭션에 넣고, notifications.py 판정과 프론트 알림 문구에 한 종류를 더한다. 푸시도 notify_new_comment_push 와 같은 모양으로 백그라운드에 건다.

**검증** (high) approve_request(subscriptions.py:251-260)는 sub.approved=True 와 commit 뿐이고 services/email.py·push.py 어디에도 승인 알림 경로가 없어 신청 알림(184행)과 비대칭인 건 확인했지만, 신청자가 구독 화면을 다시 열면 '✓ 구독 중'으로 상태를 볼 수 있어 흐름이 막히지는 않는다.

### GAP-4 · 글쓴이가 승인된 구독자를 보거나 강제 해지할 화면이 없다 — API 만 있다

`frontend/src/pages/SubscriptionsPage.tsx:40` — 기능 공백 · feature-gap

DELETE /subscriptions/requests/{id} 는 승인된 구독자도 끊지만 화면은 승인 대기만 보여준다. 구독자공개 글을 누가 보고 있는지, 그 사람을 내보낼지는 psql 없이 못 한다.

**근거** backend/app/routers/subscriptions.py:264-275 reject_request 주석: "승인된 구독자에게도 동작한다 = 강제 해지. 화면('받은 구독 신청')은 pending 만 보여주므로 승인된 관계가 여기로 오는 건 의도한 조작일 때뿐이다." 그런데 승인된 목록을 주는 라우트가 없다 — my_requests(220-235행)는 approved.is_(False) 만 조회하고, GET /subscriptions/detail(51행)·/authors(110행)는 구독하는 쪽(subscriber) 시점이다. 프론트 SubscriptionsPage.tsx:40 은 fetchRequests() 만 부르고 frontend/src/api/subscriptions.ts 에 '내 구독자 목록' 호출이 없다.

**고침** GET /subscriptions/subscribers (author=나, approved=True) 를 추가하고 SubscriptionsPage 에 '내 구독자' 절과 '해지' 버튼을 둔다. 백엔드 강제 해지는 이미 있으니 화면만 붙이면 된다.

**검증** (high) my_requests(221)는 approved.is_(False)만 조회하고 /detail(52)·/authors(111)은 구독하는 쪽 시점이며 api/subscriptions.ts 에도 구독자 목록 호출이 없어 글쓴이가 승인된 구독자를 보거나 지목해 끊을 화면이 정말 없지만, 강제 해지는 reject_request 주석이 '의도한 조작일 때만'이라 적어둔 예외 경로라 운영 편의 등급이다.

### GAP-5 · 회원이 자기 댓글을 지우거나 고칠 수 없다 — 삭제는 글쓴이·관리자만

`backend/app/routers/comments.py:166` — 기능 공백 · feature-gap

로그인 회원이 단 댓글을 본인이 지울 수 없고 수정 라우트도 없다. 오타나 실수로 쓴 댓글이 남의 손(글쓴이·관리자)에만 맡겨진다.

**근거** comments.py 라우트는 GET(60)·POST(104)·DELETE(166) 셋뿐이고 PUT/PATCH 가 없다. delete_comment(166-180행)는 `post.owner_id != user.id and user.role != "admin"` 이면 403 — comment.user_id 와 요청자를 비교하는 분기가 없다. 프론트 PostDetailPage.tsx:230-231 canModerate 도 같은 조건이라 회원 본인 댓글에 삭제 버튼이 안 뜬다(578행). 댓글은 user_id 를 저장하므로(comments.py:139) 본인 판정 재료는 이미 있다.

**고침** delete_comment 조건에 `comment.user_id == user.id` 를 더하고 canModerate 옆에 isMine 을 두어 본인 댓글에도 삭제를 보인다. 수정은 PATCH /{comment_id} (본인만, content 만) 로 붙인다.

**검증** (high) comments.py 에 PUT/PATCH 가 없고 delete_comment(179행)의 조건이 `post.owner_id != user.id and user.role != "admin"` 뿐이라 comment.user_id(135행에 저장 중) 를 아예 안 보며, test_comments.py 의 삭제 인가 5건도 본인 삭제를 다루지 않아 '의도적'이라는 근거는 코드·문서·테스트 어디에도 없다.

### GAP-6 · 계정 자진 삭제·데이터 내보내기가 없다 — 지우는 건 관리자만 할 수 있다

`backend/app/routers/auth.py:486` — 기능 공백 · feature-gap

사용자가 자기 계정을 없애거나 자기 글·댓글을 내려받을 방법이 없다. 삭제는 관리자 DELETE /admin/users/{id} 뿐이고 요청 경로도 화면에 없다.

**근거** auth.py 의 /me 계열은 GET(486)·PATCH 표시명(491)·PATCH 핸들(518)·logout(562)뿐이고 DELETE /me 가 없다. 삭제 라우트는 admin.py:274 delete_user 하나. 내보내기는 backend/app/routers 전체와 frontend/src/api 전체에 export 성 호출이 없다(grep '내보내|export' → 코드 0건; docs 도 0건). SettingsPage.tsx 는 표시명·핸들·BYOK 키뿐이다(4-6·72·87행). 문서에 '일부러 안 둔다'는 결정이 없다.

**고침** DELETE /auth/me (비밀번호 재확인, admin 은 거부, admin.py delete_user 와 같은 정리) 와 GET /auth/me/export (내 글·댓글 JSON) 를 두고 SettingsPage 하단에 붙인다.

**검증** (medium) auth.py 의 /me 계열에 DELETE 가 없고 라우터·프론트 전체에 내보내기 호출도 없는 건 확인했으나, 가입 자체가 관리자 발급 초대로만 되는 5인 규모라 삭제도 관리자 경로인 것이 비대칭이라 보기 어렵고 실질 영향은 작다.

### GAP-7 · 결제 내역·영수증을 사용자도 관리자도 볼 수 없고, 해지가 남은 기간을 즉시 없앤다는 안내가 없다

`backend/app/routers/payments.py:329` — 기능 공백 · feature-gap

payments 표에 기록은 쌓이지만 읽는 라우트가 없다. 결제 뒤 사용자는 언제 얼마를 냈는지 확인할 곳이 없고, 해지 버튼은 남은 유료 일수를 버린다는 말을 안 한다. 실결제가 보류(ROADMAP)라 low.

**근거** payments.py 라우트는 checkout(61)·confirm(234)·unsubscribe(329) 셋. GET 이 없다. backend/app/models/payment.py 에 receipt url 컬럼이 없고(grep receipt → 0건) 토스 응답의 영수증 주소를 버린다. admin.py 에도 결제 조회가 없다. unsubscribe(336행 주석 "환불은 별도. 데모라 상태만 토글")는 pro_until 을 즉시 None 으로 만들고, PaymentPage.tsx:78 확인창은 "상위 AI 모델이 다시 잠겨"만 말하고 남은 일수(115-121행에서 이미 계산해 표시 중)를 언급하지 않는다. checkout 은 is_pro 면 400(73행)이라 만료 전 갱신도 못 한다.

**고침** GET /payments/me (order_id, amount, status, paid_at) 와 관리자용 GET /admin/payments 를 두고, confirm 응답의 receipt.url 을 저장한다. 해지 확인창에 '남은 N일이 바로 사라진다'를 넣고, 만료 7일 전부터 재결제를 허용한다.

**검증** (medium) payments.py 라우트는 checkout·confirm·unsubscribe 셋뿐이고 models/payment.py 에 receipt 컬럼이 없으며 해지 확인창(PaymentPage.tsx:78)이 115-121행에서 이미 계산해 보여주는 잔여 일수를 언급하지 않는 건 사실이지만, ROADMAP:188 로 실결제가 보류고 프로드는 payments_require_live 가 테스트키 결제를 503으로 막아 실제 돈이 걸리지 않는다.

### GAP-9 · 이메일 주소를 바꿀 방법이 없다

`backend/app/schemas/user.py:86` — 기능 공백 · feature-gap

로그인 ID 이자 재설정 메일 수신처인 이메일을 사용자가 못 바꾼다. 초대 때 관리자가 고른 주소가 영구다.

**근거** backend/app/schemas/user.py 의 Update 스키마는 DisplayNameUpdate(86)·SkinUpdate(134)·SlotsUpdate(160)·HandleUpdate(190)뿐이고 EmailUpdate 가 없다. auth.py /me 계열(486-562행)에 email 을 받는 라우트가 없다. admin.py 에도 주소 변경이 없다. 초대는 관리자가 주소를 고른다(admin.py:330-340, README '가입' 절).

**고침** PATCH /auth/me/email (비밀번호 재확인 + 새 주소로 확인 링크, SES 샌드박스라 주인 검증 주소만 실제 도달) 을 두거나, 관리자 화면에서 주소를 바꾸는 라우트를 둔다. 후자가 샌드박스 제약과 맞는다.

**검증** (medium) schemas/user.py 의 Update 계열이 DisplayName·Skin·Slots·Handle 넷뿐이고 auth.py·admin.py 어디에도 이메일을 받는 변경 라우트가 없는 건 확인했으며(SettingsPage:92 의 '주소 변경'은 핸들이다) 관련 결정 문서도 없지만, 초대제라 관리자가 주소를 고르는 구조와 SES 검증 절차상 실질 영향은 작다.

### OPS-2 · 배포의 '정적 산출물 확인'이 about.html·about.md·infra.html을 안 세어, 원본이 빠져도 초록이고 `--delete`가 라이브에서 지운다

> ✅ **2026-09-05에 고쳤다.** 목록에 `about.html about.md infra.html devlog-filter.js` 넷을
> 더했다. 보고서가 제안한 'manifest' 쪽은 **일부러 안 갔다** — manifest 는 생성기가 쓴 것을
> 적으므로 조용히 건너뛴 파일은 manifest 에도 없다. 검사가 자기 대상에게 대상을 물어보는
> 모양이 되어 지금보다 약해진다. 그 이유를 워크플로 주석에 남겼다.

`.github/workflows/deploy.yml:78` — 운영(스크립트·terraform·CI) · ops

gen-static.mjs는 content/about.md가 비면 about.html·about.md 생성을 건너뛰고(frontend/scripts/gen-static.mjs:1470 `if (aboutRaw)`), content/infra.json이 없으면 infra.html을 건너뛴다(:1052 `if (existsSync(infraPath))`). 이 스텝은 그 '조용한 건너뛰기'를 막으려고 만든 자리인데(:67-70 주석) 대상 목록에 이 셋이 없다. 빠진 채 배포되면 `aws s3 sync --delete`(:208)가 S3의 about.md·about.html·infra.html을 지우고, 앱의 /about 화면은 /about.md를 fetch하므로(gen-static.mjs:1428-1445 주석) 그 화면이 깨진 채 배포는 초록이다.

**근거** deploy.yml:78 목록: `rss.xml sitemap.xml robots.txt devlog.html devlog-index.json og-image.png lessons.html lessons-filter.js devlog-search.json favicon.ico log.html keywords.html map.html` — about.html·about.md·infra.html·devlog-filter.js 없음. `ls frontend/dist`에는 about.html, about.md, infra.html, devlog-filter.js가 실재. gen-static.mjs:1051-1052 `const infraPath = join(HERE,'..','..','content','infra.json'); if (existsSync(infraPath)) {`, :1470 `if (aboutRaw) { writeFileSync(join(OUT,'about.md'), aboutRaw)`.

**고침** :78의 for 목록에 `about.html about.md infra.html devlog-filter.js`를 더한다. 더 근본적으로는 gen-static.mjs가 산출물 목록(manifest)을 내고 이 스텝이 그 목록 전체를 `-s`로 확인하게 해서, 페이지를 새로 만들 때마다 여기 목록을 손으로 늘리는 구조를 없앤다.

**검증** (high) deploy.yml:78 목록에 about.html·about.md·infra.html이 없는 것이 맞고 gen-static.mjs:1439 `if (aboutRaw)`(빈 파일이면 falsy)·:1051 `existsSync(infraPath)`가 조용히 건너뛰므로 `s3 sync --delete`가 지우고 AboutPage.tsx:35의 `fetch('/about.md')`가 깨지지만, 트리거가 '원본 파일을 지우거나 비우는' 경우뿐이고 손실이 정적 페이지 한 장이라 medium은 과하다.

### OPS-4 · 캐시 계층 확인이 '`-`가 든 첫 .js 키' 하나만 보고, 그 선택이 해시 패턴과 무관하다

> ✅ **2026-09-05에 고쳤다.** 위 `s3 cp` 와 같은 규칙(`-` + 8자 + .js/.css)으로 해시 자산을
> 전부 뽑아 각각 `head-object` 로 확인하고, 안 붙은 것을 모아 한 번에 보고한다.
> **0개면 실패다** — 대상 없는 통과는 이 저장소가 이미 세 번 당한 모양이다.
> 지금 dist 로 정규식을 실측하니 해시 자산 셋만 뽑히고 `devlog-filter.js`·`sw.js` 는 빠진다.

`.github/workflows/deploy.yml:286` — 운영(스크립트·terraform·CI) · ops

immutable이 실제로 붙었는지를 `Contents[?ends_with(Key,'.js')] | [?contains(Key,'-')] | [0].Key`로 고른 객체 하나로 판정한다. 지금 그 객체는 `PaymentPage-BkTzxQ0F.js`인데, 대문자 P가 소문자 키보다 앞에 오는 우연 때문이다. cp가 쓰는 패턴은 `*-????????.js`(:280)인데 검사는 그 패턴을 안 쓴다. PaymentPage 청크가 없어지거나 소문자 이름이 되면 `[0]`은 해시 없는 `devlog-filter.js`가 되어 must-revalidate가 정상인데도 매 배포 빨간불이 된다(영구 오탐 → 검사 무시). 반대로 해시 자산 여러 개 중 일부만 안 붙어도 하나만 보므로 통과한다.

**근거** deploy.yml:286-290. `ls frontend/dist`: `PaymentPage-BkTzxQ0F.js`, `devlog-filter.js`, `index-CKJckvY0.js`, `lessons-filter.js`, `sw.js` — S3 바이너리 정렬에서 'P'(0x50) < 'd'(0x64) < 'i'. `devlog-filter.js`·`lessons-filter.js`는 `-` 뒤가 6자라 :280의 `*-????????.js`에 안 걸리고 :78 목록의 상시 파일이다.

**고침** 키 목록을 받아 cp와 같은 규칙으로 고른다: `aws s3api list-objects-v2 --query "Contents[?ends_with(Key,'.js') || ends_with(Key,'.css')].Key" --output text | tr '\t' '\n' | grep -E -- '-[A-Za-z0-9_]{8}\.(js|css)$'` 로 해시 자산 전부를 뽑아 각각 head-object로 `immutable`을 확인하고, 0개면 '대상 없음'으로 실패시킨다.

**검증** (high) deploy.yml:286-287의 `[?contains(Key,'-')] | [0].Key`가 실재하고 vite assetsDir='' 때문에 dist 자산이 버킷 루트에 놓여 정렬상 `PaymentPage-BkTzxQ0F.js`가 우연히 첫 키가 되는 것이 맞으며 :280의 `*-????????.js` 패턴과 검사 기준이 다르지만, 결과는 캐시 헤더 검사의 오탐·부분 통과라 배포·데이터에는 영향이 없다.

### OPS-5 · 런북 드리프트 G·H-3가 부분 문자열로 매치해, 다른 키 이름이 검사를 대신 통과시킨다

> ✅ **2026-09-05에 고쳤다.** 둘 다 낱말 경계로 바꿨다. 실측으로 확인했다 —
> `TOSS_SECRET_KEY` 만 있는 파일에서 옛 규칙은 `SECRET_KEY` 를 '있다'고 했고 새 규칙은
> 없다고 한다. H-3 은 `-d postgres_test` 한 줄을 옛 규칙이 0건, 새 규칙이 1건으로 잡는다.

`scripts/check_runbook_drift.sh:277` — 운영(스크립트·terraform·CI) · quality

G는 `grep -q "$k" RECOVERY.md`라 `SECRET_KEY`는 `TOSS_SECRET_KEY`(이 스크립트가 :304에서 '아직 실재하지 않는 키'로 분류한 것)로, `SMTP_USER`는 `SMTP_USERNAME`으로, `S3_BUCKET`은 `S3_BUCKET_NAME`으로 충족된다. 런북에서 SECRET_KEY 줄만 지워도 TOSS_SECRET_KEY가 남아 있으면 초록이다. H-3(:369)도 `grep -v -- "-d $PROD_DB"`라 `-d postgres_test`를 운영 DB로 읽는다.

**근거** :277 `grep -q "$k" "$ROOT/RECOVERY.md" || miss_keys=...`. 실측 `grep -c SECRET_KEY RECOVERY.md`=3, `grep -cw SECRET_KEY`=2 — 한 건은 다른 키 안의 부분 문자열이다. :369 `wrongdb=$(grep -nE 'psql .* -d [A-Za-z0-9_]+' "$IR" | grep -v -- "-d $PROD_DB" || true)`.

**고침** G: `grep -qE "(^|[^A-Za-z0-9_])${k}([^A-Za-z0-9_]|$)"` (또는 `grep -qw`). H-3: `grep -vE -- "-d ${PROD_DB}([^A-Za-z0-9_]|$)"`.

**검증** (high) check_runbook_drift.sh:277이 `grep -q "$k"` 부분 매치라 RECOVERY.md에서 SECRET_KEY 행을 지워도 377행의 TOSS_SECRET_KEY가 남아 통과함을 `grep -c`=3 / `grep -cw`=2로 확인했고 :369의 `grep -v -- "-d postgres"`도 `-d postgres_test`를 걸러버리지만, 지금 당장 오작동 중인 건 아니고 검사 견고성 문제다.

### OPS-7 · 런북 드리프트 D의 `grep -r terraform/`이 로컬에서 .terraform/(868MB 프로바이더)까지 훑는다

> ✅ **2026-09-05에 고쳤다.** `--include='*.tf' --include='*.tfvars.example' --include='*.md'
> --exclude-dir=.terraform` 로 좁혔다. 전체 검사 시간이 로컬에서 **1.1초**가 됐다.

`scripts/check_runbook_drift.sh:206` — 운영(스크립트·terraform·CI) · quality

박힌 인스턴스 ID를 찾는 grep이 `"$ROOT"/terraform/`를 재귀로 돌아 `.terraform/providers/…` 바이너리와 gitignore된 terraform.tfvars까지 읽는다. CI에서는 init 전이라 없지만, 로컬 실행은 매번 수백 MB를 스캔하고, 바이너리 안에서 우연히 `i-0`+16hex가 맞으면 오탐 한 줄이 원문 그대로 출력된다.

**근거** :206 `stale=$(grep -rnE '(^|[^[:alnum:]-])i-0[0-9a-f]{16}' "$ROOT"/terraform/ "$ROOT"/RECOVERY.md 2>/dev/null || true)`. `du -sh terraform/.terraform` = 868M, `ls terraform/.terraform` = providers, terraform.tfstate.

**고침** `grep -rnE --include='*.tf' --include='*.md' --exclude-dir=.terraform …` 또는 `"$TF_DIR"/*.tf`로 대상을 명시한다.

**검증** (high) check_runbook_drift.sh:206의 `grep -rnE ... "$ROOT"/terraform/`가 실재하고 `du -sh terraform/.terraform`=868M, 실제 `/usr/bin/grep`으로 같은 명령을 돌리니 7.4초가 걸려 로컬 실행마다 프로바이더 바이너리와 gitignore된 tfvars까지 훑는 것이 확인됐다(다만 바이너리 매치는 원문이 아니라 'Binary file matches'로 나온다).

### OPS-8 · 이메일 허용 규칙의 `noreply` 부분 매치가 주소 전체(실도메인 포함)를 통과시킨다

> ✅ **2026-09-05에 고쳤다.** `@users\.noreply\.github\.com$` 로 도메인까지 고정했다.
> SELFTEST_HITS 에 두 형태(도메인이 실값인 것 · 로컬파트에만 noreply 가 섞인 것)를,
> MISSES 에 깃허브 커밋 주소를 넣었다. 좁히자마자 **이 보고서 자신이 걸렸다** —
> OPS-8 절이 예시로 적어둔 주소 셋이 그대로 검사에 잡혀서 예약값 표기로 바꿨다.

`scripts/check_publish_secrets.py:74` — 운영(스크립트·terraform·CI) · security

`_EMAIL_OK`에 `|noreply|users\.noreply`가 있어 `noreply@<실제 회사 도메인>`이나 `x-noreply-y@<실도메인>`처럼 문자열 어디에든 noreply가 들어가면 통째로 허용된다. 의도는 GitHub의 `users.noreply.github.com`인데 규칙은 도메인을 보지 않는다. 발신 전용 주소라도 도메인은 실운영 값이다.

**근거** :67-77 `_EMAIL_OK = re.compile(r"@(example\.(com|org|net)|x\.com|b\.com)" r"|\.(test|example|invalid|local|localhost)$" r"|@test\.com" r"|noreply|users\.noreply" r"|^[.…*]+@", re.I)`; :121 `if v in ALLOW or ok.search(v): continue`.

**고침** `noreply`는 `@users\.noreply\.github\.com$`처럼 도메인까지 고정하고, 다른 발신 전용 주소는 ALLOW에 이유와 함께 한 줄씩 적게 한다. SELFTEST_HITS에 `noreply@<가짜도메인>` 형태를 넣는다.

**검증** (high) check_publish_secrets.py:74의 `|noreply|users\.noreply`가 도메인을 보지 않는 부분 매치라 실측에서 `noreply@<실도메인>`과 `x-noreply-y@<실도메인>` 두 줄이 모두 통과했고, 의도(GitHub users.noreply)와 규칙의 범위가 어긋나는 것이 맞다.


## 기각된 것 — 7건

반박 검증에서 떨어진 것들이다. 근거 줄이 실제와 다르거나, 주석에 의도적 결정으로 적혀 있거나, 다른 계층이 이미 막고 있었다.

- **BE-8** 새 댓글 푸시 제목에 익명 자유입력 이름이 그대로 잠금화면으로 나간다
  - 기각 사유: 근거 줄이 전부 틀렸고(push.py 619·648 → 실제 373-374·402, schemas/comment.py 203 → 실제 10), 실체도 '본문 2000자를 뺀 판단이 이름 50자에는 왜 안 왔나'라는 정도 문제인데 그 이름은 어차피 댓글 목록에 그대로 나가고 comments.py:124-127이 '이름을 막는 쪽으로 고치지 말 것'을 이유와 함께 못 박아 둔 영역이라, 제안한 고침도 본인 말대로 docstring 한 줄로 끝날 수 있는 문서 격차에 가깝다.
- **BE-9** 태그 검증이 30자 초과·11번째 이후 태그를 422 없이 조용히 버린다
  - 기각 사유: 핵심 근거인 '15행이 422가 방침이라고 적어뒀다'가 오독이다 — 14-15행 주석은 TITLE_MAX·CONTENT_MAX(제목·본문) 이야기이고 태그는 30행이 '아래 검증에서 공백정리·빈값제거·중복제거·개수/길이 제한'이라며 조용한 정리를 그대로 문서화해 뒀으며, 개수 초과는 WritePostPage.tsx:410·430의 tags.length<10·slice(0,10)이 이미 프론트에서 막는다.
- **GAP-1** 로그인 상태에서 비밀번호를 바꿀 길이 없다 — 재설정 메일은 샌드박스라 주인 외엔 안 닿는데 화면은 "보냈어"
  - 기각 사유: 인증 상태 비번 변경 라우트가 없는 건 맞지만 핵심 전제인 '초대 writer는 재설정 메일을 못 받는다'가 틀렸다 — docs/ses-production-access.md:19-38 이 '남은 메일은 전부 등록된 계정 주소로 가고 그 주소들은 SES 검증돼 있다, 새 수신자는 ses_verify_recipients.sh 로 등록한다'를 확정 사항으로 못 박았고(finding 이 인용한 :357 은 '실행하지 말 것'이라 명시된 2026-07-31 폐기 사유서 본문이다), AdminPage.tsx:361-372 는 초대 발급 시 recipient_verified===false 면 '나중에 비밀번호 재설정 메일이 안 닿아'와 실행할 스크립트를 화면에 직접 띄운다.
- **GAP-8** RSS·sitemap 이 content/devlog 마크다운만 싣는다 — DB 에 쓴 글(다른 writer 포함)은 피드가 없다
  - 기각 사유: RSS 가 마크다운만 싣는 건 문서화된 결정이다 — 1452-1456행 주석이 '서버가 꺼져 있어도 동작하는 성질을 그대로 이어받는다'고 적었고 1401-1411행이 'EC2를 평소 꺼두므로 API 가 아니라 여기서 목록을 낸다'를 근거로 세웠으며, 1488-1490행의 sitemap SPA 제외 사유(꺼진 서버로 크롤러를 보내지 않는다)가 DB 글 링크에도 그대로 적용되고 제안한 fix(배포 때 /api/posts 조회)는 그 전제와 정면으로 충돌한다.
- **OPS-6** 서브넷·VPC·프리픽스리스트·CloudFront 배포 ID가 여러 파일에 박혀 있고, 드리프트 검사 D는 인스턴스 ID만 본다
  - 기각 사유: 박힌 ID 자체는 실재하나 근거 줄번호가 전부 파일 밖이고(ec2.tf는 179줄인데 :291, network.tf는 107줄인데 :875, ecs-oneshot.sh는 64줄인데 :79, s3.tf는 126줄인데 :300-306, traffic_report.sh는 107줄인데 :271-278), 특히 traffic_report.sh는 '조용히 exit 0'이 아니라 "이건 방문 0이 아니라 못 읽었다일 수 있다 · 배포 ID가 ${DIST_ID}가 맞는지"를 명시 출력하는 의도된 처리라 근거가 어긋난다.
- **FE-4** refreshUser가 일시 오류에 user를 null로 만들어 유효한 세션을 로그인 화면으로 튕긴다
  - 기각 사유: auth.ts fetchMe 주석이 '절전이든 네트워크 오류든 토큰은 지우지 않고 비로그인으로 그린다, 새로고침에 복구된다'고 null 처리 계약을 의도로 명시해 뒀고, 재현 조건도 방금 성공한 쓰기 직후의 조회만 흔들리는 매우 좁은 창이라 기각한다.
- **FE-13** VerifyPage가 StrictMode 이중 실행에 verifyEmail을 두 번 보내 성공을 '인증 실패'로 덮을 수 있다
  - 기각 사유: backend auth.py:233-256 verify_email은 email_verified=True만 세우고 token_version을 올리지 않아 같은 토큰의 두 번째 호출도 200이므로, '첫 요청이 토큰을 소각해 두 번째가 400이 되고 ok가 fail로 덮인다'는 근거(auth.py:253)가 실제 코드와 다르다.

---

## 2부 — 보안 · 백엔드 품질/테스트 · 프론트 품질/접근성 (3갈래)

탐색 31건 → **생존 30건 · 기각 1건**  (high 0 · medium 9 · low 21)


### 🟠 MEDIUM — 9건

#### BQ-10 · alembic check는 server_default 드리프트를 못 본다 — conftest 주석은 본다고 적혀 있다

> ✅ **2026-09-05에 고쳤다.** `alembic/env.py`의 온라인·오프라인 양쪽 `context.configure`에
> `compare_server_default=True`를 줬다. 켜자마자 **실제 드리프트가 둘 나왔다** —
> `ai_hourly_usage.count`·`ai_guard_violation.count`는 마이그레이션이 `server_default='0'`으로
> 만드는데 모델은 파이썬 `default=0`만 들고 있었다(그래서 create_all로 만드는 테스트 DB에는
> 그 기본값이 없었다). 모델을 표에 맞추는 쪽으로 정렬해 노이즈 0으로 만든 뒤 게이트로 세웠고,
> 빈 DB에 `upgrade head` → `alembic check`까지 로컬에서 재현했다. conftest의 '기본값은 CI가
> 본다'는 문장은 이제 사실이다(그 자리에 경위를 적어뒀다).

`backend/alembic/env.py:85` — 백엔드 품질·테스트 · quality

모델↔마이그레이션 게이트가 컬럼 기본값 차이를 검사하지 않는데, 그 사각을 메운다고 지목된 CI 잡이 실제로는 같은 것을 안 본다.

**근거** alembic/env.py:85-87의 `context.configure(connection=connection, target_metadata=target_metadata)`에는 `compare_server_default`가 없다. alembic의 기본값은 compare_type=True, **compare_server_default=False**이므로, .github/workflows/ci.yml:81의 `alembic check` 잡은 타입·nullable·컬럼 유무는 잡지만 server_default 차이는 diff로 보지 않는다. 그런데 tests/conftest.py:80-83은 `_assert_schema_fresh`가 안 보는 것을 나열하면서 "컬럼의 타입·nullable·**기본값**, 유니크/체크 제약, 외래키 … 그건 이 파일의 몫이 아니다(CI의 '빈 DB에 upgrade head' 잡이 그걸 본다)"고 적었다. 세 항목 중 '기본값'은 그 잡도 안 본다. 구체적 실패: 누가 `AuthorSubscription.approved`의 server_default를 "false"→"true"로 바꾸고 마이그레이션을 안 만들면, 테스트 DB는 create_all(모델값)로 만들어져 초록이고 alembic check도 no diff이며, 프로드 DB만 옛 기본값을 유지한다 — 앱을 안 거치는 경로(psql·복원 훈련)로 들어온 행에서 두 환경이 갈린다.

**고침** alembic/env.py의 run_migrations_online(과 offline)의 context.configure에 `compare_server_default=True`를 준다. 노이즈가 나면(now() 표기 차이 등) 한 번 0으로 정리한 뒤 게이트로 세우는 이 저장소의 mypy/ruff 방침을 그대로 따른다. 그리고 conftest.py:80-83에서 '기본값'을 빼거나, 위 옵션을 켠 뒤에만 그 문장을 남긴다.

**검증** (medium) alembic/env.py:84-87 의 context.configure 에 compare_server_default 가 없어(저장소 전체 grep 0건) alembic 기본값 False 로 돌고, 그런데 conftest.py:80-83 은 '기본값'을 CI 잡이 본다고 적어 뒀으며 ci.yml:76-81 의 두 잡(upgrade head / alembic check) 어느 쪽도 server_default 차이를 보지 않는다.

#### BQ-2 · 레이트리밋 키를 만드는 X-Forwarded-For 분기가 테스트 0건

> ✅ **2026-09-05에 고쳤다.** `tests/test_ratelimit_key.py` 7개로 XFF 분기를 덮었다 —
> 1홉·2홉·위조된 맨 앞 값·항목이 홉보다 적을 때·공백 섞인 값·헤더 없음·빈 헤더.
> 보고서가 예시로 든 한 글자 회귀(`parts[-idx]` → `parts[idx - 1]`)를 실제로 넣어
> 셋이 빨개지는 것까지 확인했다. 코드는 안 고쳤다 — 분기는 옳았고 없던 것은 그것을 지키는 장치다.

`backend/app/core/ratelimit.py:21` — 백엔드 품질·테스트 · test-gap

모든 IP 레이트리밋의 키를 정하는 client_ip()의 XFF 파싱·홉 계산이 한 번도 실행된 적이 없다.

**근거** coverage 데이터에서 app/core/ratelimit.py 미커버 라인이 21-27, 즉 `if xff:` 안쪽 전부다(파싱, `idx = min(settings.trusted_proxy_hops, len(parts))`, `return parts[-idx]`). tests/ 전체에 `X-Forwarded-For`·`client_ip`·`trusted_proxy_hops` 문자열이 0건이다(grep 실측). 이 함수는 limiter의 key_func(ratelimit.py:32)이라 login 10/분·register 5/시간·댓글 20/시간·AI 10/시간이 전부 여기에 얹혀 있고, 함수 주석 자신이 "홉 수가 틀리면 모든 IP 제한이 엣지 IP를 키로 잡아 무력화된다"고 적어놨다. 인덱스를 `parts[-idx]`에서 `parts[idx-1]`로 바꾸는 한 글자 회귀(=클라가 위조한 맨 앞 값을 키로 쓰는 상태)가 나도 CI는 초록이고, 밖에서는 아무 신호도 없다 — 방어가 사라진 것이 조용하다.

**고침** tests에 client_ip() 단위 테스트를 추가한다: hops=1일 때 `"203.0.113.1, 203.0.113.2"` → `203.0.113.2`, hops=2일 때 같은 값 → `203.0.113.1`, 항목이 홉 수보다 적을 때 parts[0], 헤더 없음일 때 get_remote_address 폴백, 공백·빈 항목 섞인 값. Request는 starlette의 Headers만 있으면 되므로 통합 테스트 없이 만들 수 있다.

**검증** (high) ratelimit.py:19-28 의 XFF 분기가 실재하고 tests/ 에 X-Forwarded-For·client_ip·trusted_proxy_hops 문자열이 0건이라, 모든 IP 리밋의 키를 정하는 `parts[-idx]` 한 줄이 회귀해도 CI 가 초록인 것이 맞다.

#### BQ-4 · 토스가 5xx를 줄 때의 '거절 아님' 처리가 테스트 0건 (돈 경로)

> ✅ **2026-09-05에 고쳤다.** 게이트웨이 5xx 갈래에 시험 다섯 개를 붙였다 —
> 500·502·503 각각에 대해 (a) 응답이 502 이고 (b) 장부가 `confirming` 으로 남고
> (c) Pro 가 안 켜지는지, 그리고 문구가 '거절'이 아니라 재시도를 가리키는지.
> 중복 승인 뒤 주문조회마저 실패하는 경우(payments.py:215-217, 역시 미커버였다)도
> 같이 잠갔다. 코드는 안 고쳤다 — 분기는 이미 옳았고 없던 것은 그것을 지키는 장치다.

`backend/app/routers/payments.py:189` — 백엔드 품질·테스트 · test-gap

결제사 HTTP 5xx → 502 + status를 failed로 굳히지 않는 경로가 한 번도 실행되지 않는다. 형제인 네트워크 오류 경로는 테스트가 있다.

**근거** coverage에서 app/routers/payments.py 미커버 라인에 190이 있다 — `if resp.status_code >= 500:` 안의 `raise _ApprovalRejected(..., status_code=502)`(payments.py:189-192)다. 바로 위 주석 185-188이 "게이트웨이가 아픈데 사용자는 '내 카드가 거절됐다'를 본다", "5xx는 '거절'이 아니라 '모름'"이라고 2026-08-26 훈련 결론을 적어놨다. 그런데 tests/test_payments.py(490줄)의 502 단언은 :271(본문이 {} 인 경우)과 :379 test_confirm_network_error_502(`httpx.ConnectError`)뿐이고, `toss.configure(status_code=500|503, ...)` 케이스가 없다. 같은 파일의 `_fetch_payment_by_order` 실패 갈래(payments.py:213-214, 217)도 미커버다. 즉 5xx 분기를 지우거나 `>= 500`을 `> 500`으로 바꿔도 테스트는 초록이고, 그러면 payments.status가 failed로 굳어 '돈은 나갔는데 Pro는 안 열린' 상태가 다시 만들어진다.

**고침** test_payments.py에 `toss.configure(status_code=503, body={})`로 confirm을 부른 뒤 (a) 응답 502, (b) `_payment(db, order_id).status == "confirming"`(failed 아님), (c) is_pro False를 단언하는 테스트를 추가한다. `_fetch_payment_by_order`가 비200을 받는 경우(payments.py:215-217)도 같은 방식으로 잠근다.

**검증** (high) payments.py:189-192 의 `resp.status_code >= 500` → 502(failed 로 안 굳힘) 갈래에 대해 test_payments.py 의 toss.configure 호출은 status_code 가 200·400 뿐이고 5xx 케이스가 없어(:264,:313,:338,:360), 08-26 훈련이 고친 '5xx 는 거절이 아니라 모름' 원칙이 돈 경로에서 무방비다.

#### FQ-2 · AI 초안 상자에 존재하지 않는 Tailwind 클래스 `p-5/[0.07]` — 안쪽 여백이 0이다

> ✅ **2026-09-05에 고쳤다.** `p-5`로 바꿨다. 배경 농도는 같은 줄의 `bg-accent/[0.05]`가
> 이미 정하고 있어 건드리지 않았다. 고친 뒤 빌드에서 CSS 산출물이 **바이트까지 그대로**인 것이
> 진단(그 클래스는 CSS를 하나도 만들지 않았다)의 확인이다.

`frontend/src/pages/WritePostPage.tsx:505` — 프론트 품질·접근성 · quality

`p-5/[0.07]`은 Tailwind가 만들어내지 못하는 클래스라 CSS가 없고, 그 결과 글쓰기 화면의 'AI로 초안 잡기' 상자가 패딩 없이 테두리에 내용이 붙어 그려진다.

**근거** WritePostPage.tsx:505가 `className="mb-6 rounded-2xl border border-accent/15 bg-accent/[0.05] p-5/[0.07]"`이다. 슬래시 수정자는 색 유틸의 불투명도용이라 padding에는 안 붙는다. 빌드 산출물 frontend/dist/index-O63ouJC4.css를 확인하면 `.p-5{padding:calc(var(--spacing) * 5)}` 규칙만 있고 `p-5\/`로 시작하는 선택자는 0건이다. 이 요소는 `p-5` 단독 클래스를 갖고 있지 않으므로 아이콘·설명문·메모 textarea·모델 드롭다운·생성 버튼이 전부 테두리에 맞닿는다. 같은 화면의 다른 상자들(:455 `p-8`, :697 `p-1.5`)과 비교하면 이 상자만 어긋난다.

**고침** `p-5/[0.07]`을 `p-5`로 고친다. 배경 농도를 조절하려던 것이면 `bg-accent/[0.07]`로 옮긴다(같은 줄에 이미 `bg-accent/[0.05]`가 있다).

**검증** (high) WritePostPage.tsx:505에 `p-5/[0.07]`이 실재하고 빌드 산출물 dist/index-O63ouJC4.css에는 `.p-5{padding:...}`만 있을 뿐 `p-5\/` 선택자가 0건이라 그 상자만 패딩이 없다.

#### FQ-3 · 공개범위 라디오 3개에 name이 없어 키보드 화살표로 못 고르고 그룹으로 안 읽힌다

> ✅ **2026-09-05에 고쳤다.** 셋에 `name="visibility"`를 주고 바깥 div를 `<fieldset>` +
> `<legend className="sr-only">공개범위</legend>`로 바꿨다. 보이는 '공개범위:' 글자는
> `aria-hidden`으로 남겨 화면은 그대로다.

`frontend/src/pages/WritePostPage.tsx:785` — 프론트 품질·접근성 · quality

전체공개·구독자공개·비공개 라디오가 name 속성 없이 각각 독립된 라디오라, 방향키 이동이 안 되고 화면낭독기가 '3개 중 1개'로 묶어 읽지 못한다.

**근거** WritePostPage.tsx:785·788·791이 모두 `<input type="radio" checked={...} onChange={...} />`뿐이고 name이 없다. 브라우저는 name이 같은 것들만 한 라디오 그룹으로 묶으므로, 키보드 사용자가 '전체공개'에 포커스를 두고 ↓를 눌러도 아무 일이 없고 세 칸이 각각 별도 탭 정류장이 된다(정상 라디오 그룹은 탭 정류장 1개 + 화살표 이동). 화면낭독기도 '라디오 버튼, 1 중 1'로 셋을 따로 읽는다. 묶는 요소도 없다 — :783의 `<span>공개범위:</span>`는 fieldset/legend가 아니라서 그룹 이름으로 전달되지 않는다. 같은 파일이 다른 칸에는 aria-label을 꼬박꼬박 달아둔 것과 대비된다(:630 제목, :684 태그 추가, :738 본문).

**고침** 세 input에 `name="visibility"`를 주고, 바깥 div를 `<fieldset>` + `<legend>공개범위</legend>`로 바꾼다(또는 div에 role="radiogroup" aria-label="공개범위").

**검증** (high) WritePostPage.tsx:785·788·791의 라디오 셋 다 name이 없고 :783은 fieldset/legend가 아닌 span이라 그룹 이동·그룹 낭독이 실제로 안 된다(의도라는 주석도 없다).

#### FQ-4 · placeholder만 있고 라벨이 없는 입력칸 12개 — '09-02 정리'가 이 화면들에 안 닿았다

> ✅ **2026-09-05에 고쳤다.** 열거된 칸 전부에 `aria-label`을 달았다. 제공자마다 반복되는
> base URL·API 키 칸은 `` `${p.name} API 키` `` 처럼 이름을 넣어 다섯을 구분한다.
> 로그인·재설정·초대가입 칸에는 `autoComplete`(email·current-password·new-password)도 붙였다.

`frontend/src/pages/SettingsPage.tsx:146` — 프론트 품질·접근성 · quality

저장소가 두 곳에 'placeholder는 라벨이 아니다'라고 규약을 적어두고 aria-label을 달았는데, 설정·로그인·비밀번호·초대 화면의 입력칸은 여전히 placeholder뿐이라 화면낭독기가 칸 이름을 못 읽는다.

**근거** 규약과 그 근거는 PostDetailPage.tsx:600-601과 WritePostPage.tsx:530-532에 적혀 있다("placeholder 는 라벨이 아니다 — 입력을 시작하면 사라지고, 화면낭독기는 칸 이름을 못 읽는다 … (2026-08-11 검사 9번의 잔여 6칸, 09-02 정리)"). 남아 있는 칸: SettingsPage.tsx:146(표시명, placeholder가 '예: 유노'라 낭독기가 칸 이름 대신 이 예시를 읽는다), :174(블로그 주소, placeholder 'yuno'), :239(base URL), :249(API 키 — PROVIDERS 5개마다 반복되어 실제로는 같은 이름의 칸 5개), LoginPage.tsx:43·44, ForgotPasswordPage.tsx:46, ResetPasswordPage.tsx:48, RegisterPage.tsx:113, AdminPage.tsx:336(초대할 이메일)·344(역할 select), SkinEditor.tsx:238(직접 쓰는 CSS textarea — :181의 h3 '직접 쓰기'와 htmlFor로 안 이어져 있다). SlotEditor.tsx:200-221은 같은 화면에서 htmlFor/id로 제대로 묶어놨다.

**고침** 각 칸에 aria-label을 달거나(같은 파일들이 이미 쓰는 방식) SlotEditor처럼 label htmlFor+id로 잇는다. API 키 칸은 `aria-label={`${p.name} API 키`}`처럼 provider 이름을 넣어 5개를 구분한다. 겸사겸사 LoginPage.tsx:43-44에 autoComplete="email"/"current-password", ResetPasswordPage.tsx:48에 "new-password"를 붙인다.

**검증** (high) SettingsPage에는 aria-label이 한 개도 없고(:147·175·244·254가 전부 ui.input+placeholder뿐), LoginPage:43·44, ForgotPasswordPage:46, ResetPasswordPage:48, RegisterPage:113, AdminPage:336·344도 라벨이 없어 같은 파일들의 규약 주석과 어긋난다.

#### FQ-5 · 오류 문구 절반이 role="alert" 없이 조용히 나타난다

> ✅ **2026-09-05에 고쳤다.** 열거된 오류 `<p>` 10곳에 `role="alert"`를, 성공 문구 5곳에
> `role="status"`를 달았다. 이제 이 저장소의 오류 줄 중 낭독기에 안 읽히는 것은 없다.

`frontend/src/pages/ForgotPasswordPage.tsx:48` — 프론트 품질·접근성 · quality

LoginPage가 주석까지 달아 세운 '오류는 낭독기에도 읽혀야 한다'는 규칙이 같은 종류의 오류 줄 10곳에 안 적용돼, 화면낭독기 사용자에게는 실패가 아무 일도 안 일어난 것으로 보인다.

**근거** 규칙은 LoginPage.tsx:48-49에 있다 — "에러는 스크린리더에도 읽혀야 한다 — 조용히 나타나면 안 보이는 사용자에겐 아무 일도 안 일어난 것이다"라는 주석과 `<p role="alert">`. PostDetailPage(:381·386·474·557·628), WritePostPage(:821·827), HomePage:209, AuthorPage:223도 지킨다. 안 지키는 곳: ForgotPasswordPage.tsx:48, ResetPasswordPage.tsx:50, RegisterPage.tsx:124(초대 가입 실패), SubscriptionsPage.tsx:108, SettingsPage.tsx:214, AdminPage.tsx:389(초대 발급 실패)·582, SkinEditor.tsx:270, SlotEditor.tsx:275, PushToggle.tsx:133, PaymentPage.tsx:144. 전부 조건부로 삽입되는 <p>라 aria-live 영역이 아니고, 삽입 시점에 읽히지 않는다.

**고침** 열거한 <p>에 role="alert"를 단다. 성공 문구(SettingsPage.tsx:209, SubscriptionsPage.tsx:102, SkinEditor.tsx:264)는 role="status"가 맞다.

**검증** (high) role="alert"는 HomePage:209·AuthorPage:223·LoginPage:49·WritePostPage:821·827·PostDetailPage 5곳뿐이고 ForgotPasswordPage:48·ResetPasswordPage:50·RegisterPage:124·SettingsPage:214·SkinEditor:270·SlotEditor:275 등은 맨 <p>라 낭독기에 안 읽힌다.

#### FQ-6 · AdminPage 초대 링크 복사만 CopyButton을 안 쓰고 navigator.clipboard를 맨손으로 부른다

> ✅ **2026-09-05에 고쳤다.** `<CopyButton value={issued.url} label="복사" />`로 바꾸고
> 지역 `copied` 상태를 지웠다. 비보안 컨텍스트에서는 execCommand 폴백이 돌고, 실패하면
> '복사됨'을 띄우지 않는다(CopyButton이 이미 잠가둔 동작).

`frontend/src/pages/AdminPage.tsx:380` — 프론트 품질·접근성 · quality

보안 컨텍스트가 아니거나 권한이 거부되면 TypeError·미처리 rejection으로 끝나고 버튼이 아무 반응도 안 하는데, 이 링크는 '다시 볼 수 없다'고 화면이 스스로 말하는 1회용 토큰이다.

**근거** AdminPage.tsx:380이 `onClick={() => navigator.clipboard.writeText(issued.url).then(() => setCopied(true))}`다. catch도 폴백도 없다. CopyButton.tsx:26-46은 바로 이 문제를 위해 만들어졌고 주석에 "navigator.clipboard는 **보안 컨텍스트에서만** 있다(https·localhost). 그 밖에서는 undefined라 그냥 부르면 TypeError로 죽는다 — 조용히 아무 일도 안 일어나는 버튼이 된다"라고 적혀 있으며 execCommand 폴백과 실패 시 '복사됨'을 안 띄우는 처리까지 들어 있다. AdminPage 경로에서는 http로 접근한 로컬/사내 주소나 권한 거부 시 예외가 핸들러 밖으로 던져지고 :383의 라벨이 '복사'에 머문다. 바로 위 :358이 "지금 복사해둬, 다시 볼 수 없어"라고 적혀 있어 실패가 특히 비싸다.

**고침** 이 버튼을 `<CopyButton value={issued.url} label="복사" copiedLabel="복사됨" className={ui.btnGhost} />`로 바꾸고 지역 `copied` 상태(:280·303)를 지운다.

**검증** (high) AdminPage.tsx:380이 catch·폴백 없이 navigator.clipboard.writeText를 직접 부르고, 같은 저장소 CopyButton.tsx:26-52가 바로 그 실패(비보안 컨텍스트·권한 거부)를 위해 만들어져 있는데 1회용 초대 토큰 화면만 안 쓴다.

#### SEC-01 · /api/upload 의 6MB 본문 상한이 인증보다 먼저 걸린다 — 무인증 chunked 요청이 미들웨어 메모리에 6MB씩 쌓인다

> ✅ **2026-09-05에 일부 고쳤다.** 큰 상한을 '인증 헤더가 붙은 요청'에만 준다. 무인증
> 요청은 앱까지 가지도 못하고 413이다(미들웨어만 따로 태워 확인: `called=False`).
>
> ⚠️ **헤더 위조까지 막지는 못한다.** `Authorization: Bearer x` 한 줄이면 다시 6MB
> 후보가 된다. 없어진 것은 '아무것도 안 붙이고 던지는' 경로이고, 진짜 상한은 chunked
> 갈래가 본문을 메모리 리스트가 아니라 디스크로 흘려보낼 때 생긴다. 그건 업로드
> 경로를 다시 쓰는 일이라 이번에 하지 않았다 — **남은 숙제로 둔다.**

`backend/app/main.py:394` — 백엔드 보안 · security

09-02에 본문 상한을 경로별로 쪼개 무인증 JSON 경로는 512KB로 좁혔지만, 예외로 남긴 /api/upload 는 인증 없이도 6MB를 받는다. Content-Length 없는(chunked) 요청이면 그 6MB가 미들웨어의 파이썬 리스트에 통째로 버퍼링된 뒤에야 401/403이 난다.

**근거** main.py:308-310 이 UPLOAD_PATH="/api/upload" 하나만 MAX_UPLOAD_BODY_BYTES=6MB로 예외 처리하고, main.py:353-364 의 _limit_for 는 ASGI scope 의 path 만 본다 — 라우팅·인증 전이라 요청자가 누구인지 알 수 없다. main.py:394-408 은 CL이 없으면 상한(=여기선 6MB)까지 `buffered: list[dict]` 에 담아두고, 넘을 때만 끊는다. 즉 5.9MB chunked POST는 전부 프로세스 메모리에 들어온다. 그 뒤에야 앱이 불리는데, .venv/lib/python3*/site-packages/fastapi/routing.py:430(`body = await request.form()`)이 :481(`solve_dependencies`)보다 먼저라 uploads.py:81-84 의 require_writer 는 본문을 다 받은 뒤에 돈다. uploads.py:67 의 @limiter.limit("30/hour")도 엔드포인트 함수 안이라 401/403 경로에서는 아예 실행되지 않는다 — 무인증 요청에는 어떤 한도도 안 걸린다. 앞단도 못 막는다: main.py:336-339 가 적어둔 대로 CloudFront Function(terraform/reqsize-function.js)은 Content-Length만 보고 WAF의 SizeRestrictions_BODY 는 Count다. main.py:283-284 가 스스로 계산해둔 OOM 산수(연결 정원 500 · backend 400m · 5.9MB 연결 수십 개)가 이 한 경로에 그대로 살아 있다. 유일한 앞 관문인 require_origin_secret(main.py:440-468)은 CloudFront를 거치기만 하면 통과한다.

**고침** 인증 전에는 업로드 경로에도 6MB를 주지 않는다. 두 갈래 중 하나: ① _limit_for 가 6MB를 주는 조건에 Authorization 헤더 존재를 더한다(없으면 512KB) — 어차피 없는 요청은 401이다. ② chunked 갈래에서 버퍼를 메모리 리스트가 아니라 SpooledTemporaryFile 로 받아 상한만큼의 메모리 노출을 없앤다. 어느 쪽이든 test_body_limit.py 에 '무인증 chunked 6MB → 401/413, 메모리 버퍼 없음' 케이스를 추가한다.

**검증** (medium) main.py:308-310·353-364·394-408 이 실제로 그렇고 FastAPI routing.py:430(form) 이 :481(solve_dependencies) 앞이라 무인증 chunked 요청이 6MB를 미들웨어 리스트에 담은 뒤에야 401이 나며, 앞단(CL만 보는 엣지 함수·Count WAF·라우트 안의 30/hour)이 이 갈래를 못 막는다.


### 🟡 LOW — 21건

#### BQ-1 · 태그 기능 전체가 테스트 0건 — 정규화·필터·집계 어디도 안 덮인다

`backend/app/schemas/post.py:80` — 백엔드 품질·테스트 · test-gap

글 생성 테스트가 단 한 번도 비어있지 않은 tags를 보내지 않아, 태그 정규화·태그 필터·사이드바 태그 집계가 전부 미검증이다.

**근거** tests/ 전체에서 tags가 나오는 곳은 conftest.py:3(주석), test_push.py:575(푸시 tag), test_posts.py:291의 `"tags":[]` 뿐이다(grep 실측). 실제 커버리지도 같은 말을 한다 — `coverage report --show-missing`에서 app/schemas/post.py의 미커버 라인이 80-84, 즉 `_clean_tags`(schemas/post.py:75-85)의 for 루프 **본문 전체**다. 그래서 공백정리·빈값제거·중복제거·TAG_MAX_COUNT(10) 절삭·TAG_MAX_LEN(30) 초과 드롭이 한 줄도 실행된 적이 없다. 같은 이유로 routers/posts.py:263-265의 `Post.tags.contains([tag])` 필터와 posts_meta의 unnest 집계(posts.py:333-340)도 항상 빈 태그 위에서만 돌았다 — `?tag=`를 부르는 유일한 테스트는 test_nul_guard.py:28의 NUL 케이스다. 태그 초과분은 422가 아니라 **조용히 잘린다**(schemas/post.py:83-84): 글쓴이가 태그 12개를 넣으면 10개만 저장되는데 이를 잡는 테스트가 없다. 덤으로 routers/posts.py:214의 `tag: str | None = Query(None, max_length=50)`은 바로 위 주석이 "조회 쪽도 같은 크기로 맞춘다"고 적었지만 스키마 상한은 30이라 값이 어긋나 있다.

**고침** test_posts.py에 (a) 태그 있는 글 생성 → `?tag=` 필터가 그 글만 주는지, (b) `[" a ", "a", "", "x"*31]` 입력이 `["a"]`로 정규화되는지, (c) 태그 11개를 보내면 10개로 잘리는지(그 동작을 유지할지 422로 바꿀지 결정), (d) `/api/posts/meta`의 tags 집계가 개수를 맞게 세는지를 추가한다. 함께 posts.py:214의 max_length를 TAG_MAX_LEN(30)로 맞추거나 주석을 사실대로 고친다.

**검증** (high) tests/ 전체에서 비어있지 않은 tags 가 한 번도 안 들어가고(test_posts.py:291 이 `"tags":[]` 뿐), schemas/post.py:75-85 의 _clean_tags 루프·posts.py:265 태그필터·posts.py:334 unnest 집계가 전부 빈 태그 위에서만 돈 것이 맞다 — 다만 '조용히 잘린다'는 부분은 schemas/post.py:30 주석과 docs/code-review-20260904.md:452-453(BE-9 기각)이 이미 의도된 동작으로 못박아 뒀으므로 그 하위주장은 빼고 테스트 공백만 남는다.

#### BQ-11 · '블로그 주인' 조회가 세 파일에 각각 복사돼 있다

> ✅ **2026-09-05에 고쳤다.** `app/core/display.py` 에 `site_owner(db)` 를 두고 세 곳이
> 그것만 부른다(main.blog_owner · comments._site_owner_id · skin._owner). display_name
> 폴백이 라우터 넷에 복제돼 있어 이 파일이 생겼던 것과 같은 자리, 같은 이유다.

`backend/app/routers/skin.py:57` — 백엔드 품질·테스트 · quality

role=admin 중 최소 id를 고르는 같은 쿼리가 세 곳에 손으로 적혀 있고, 세 곳 모두 주석으로 '같은 규칙'이라고만 약속하고 있다.

**근거** 동일 규칙이 세 벌이다 — app/main.py:527 `db.scalar(select(User).where(User.role == "admin").order_by(User.id))`, app/routers/comments.py:43 `_site_owner_id`의 `select(User.id).where(User.role == "admin").order_by(User.id)`, app/routers/skin.py:57 `_owner`의 같은 쿼리. 세 곳 다 주석으로 서로를 가리키며 '같은 규칙'이라고 적는데(skin.py:56, comments.py:40-42), 강제하는 것은 아무것도 없다. 이 저장소는 정확히 같은 이유로 이미 두 번 공용 모듈을 만들었다: display_name 폴백이 라우터 넷에 복사돼 있어 app/core/display.py를 만들었고(display.py 상단 주석), 'banned' 철자가 흩어져 models/user.py:129의 BANNED_ROLE로 모았다. 회수 규칙이 실제로 바뀐 전례도 있다 — 2026-08-19에 공개 읽기 경로가 PUBLIC_BLOG_ROLES를 보도록 고쳤는데(models/user.py:110-121), 이 세 곳은 여전히 `role == "admin"` 문자열을 직접 본다. 다음에 '차단된 admin은 주인이 아니다' 같은 변경이 오면 세 곳 중 한 곳만 고쳐져 화면마다 주인 배지가 갈린다.

**고침** app/core/display.py 옆(또는 models/user.py)에 `site_owner(db) -> User | None` 하나를 두고 main.blog_owner·comments._site_owner_id·skin._owner가 그것만 부르게 한다. comments는 id만 필요하므로 `.id`를 읽으면 된다(행이 3개짜리 테이블이라 컬럼 하나를 아끼는 이득은 없다).

**검증** (medium) main.py:527·comments.py:41·skin.py:56-57 에 같은 '주인' 쿼리가 세 벌로 실재하고 강제 장치는 서로를 가리키는 주석뿐이며 이 저장소엔 display.py·BANNED_ROLE 이라는 통합 전례가 있다 — 다만 'PUBLIC_BLOG_ROLES 변경 때 세 곳이 안 고쳐졌다'는 논거는 빗나갔다(주인은 admin 단수가 규칙이라 그 상수를 쓸 자리가 아니다).

#### BQ-12 · 죽은 함수 _reading_minutes

> ✅ **2026-09-05에 지웠다.** 호출부가 없다는 것을 다시 grep 으로 확인하고 두 줄을 뺐다.

`backend/app/routers/posts.py:50` — 백엔드 품질·테스트 · quality

호출부가 하나도 없는 래퍼 함수가 남아 있다.

**근거** app/routers/posts.py:50-51의 `_reading_minutes(md)`는 `_reading_minutes_of(len(md))`를 부르는 래퍼인데, app/·tests/·scripts/ 전체에서 이 이름이 나오는 곳은 정의(50)와 자기 본문(51)뿐이다(grep 실측). 실제 사용처인 `_summary`(posts.py:183)는 `_reading_minutes_of(clen)`을 부른다 — 2026-08-31에 목록 조회가 본문 전체 대신 `func.length(Post.content)`를 읽도록 바뀌면서(posts.py:58-84 주석) 문자열을 받는 쪽이 쓸모없어졌고 그때 안 지워진 것이다. ruff는 모듈 전역 함수의 미사용을 기본 규칙으로 잡지 않아 린트도 통과한다. 남겨두면 '읽기시간 계산은 두 군데'라는 인상을 주고, 나중에 한쪽만 고치면(분당 500자 상수 변경 등) 목록과 어긋난다.

**고침** posts.py:50-51을 삭제한다. 문자열에서 바로 재는 입구를 남기고 싶으면 `_reading_minutes_of` 하나만 두고 호출부가 `len()`을 넘긴다.

**검증** (high) posts.py:50-51 의 _reading_minutes 는 app/·tests/·scripts/ 전체 grep 에서 정의 두 줄 말고 호출부가 없고 실사용은 posts.py:183 의 _reading_minutes_of(clen) 뿐이라, 2026-08-31 컬럼 최적화 때 남은 죽은 래퍼가 맞다.

#### BQ-3 · AI 업스트림 5xx→503 갈래가 테스트 0건 — 쌍둥이 함수만 테스트가 있다

`backend/app/routers/ai.py:95` — 백엔드 품질·테스트 · test-gap

_upstream_sick()이 True를 반환하는 경로와 그로 인한 503 응답이 한 번도 실행되지 않아, 2026-08-27 훈련이 고친 안내 문구가 회귀해도 초록이다.

**근거** coverage에서 app/routers/ai.py 미커버 라인에 95(=`_upstream_sick`의 `return True`)와 431-432(=`logger.warning("AI 업스트림 장애")` + 503 raise)가 들어 있다. 반면 짝인 `_upstream_unreachable`은 tests/test_degradation.py:93-128에 단위 테스트가 4개 있다(그래서 ai.py:57-58은 커버됨). test_ai.py 887줄에도 벤더 5xx 주입 케이스가 없다 — grep 결과 503 단언은 test_ai.py:100(키 미설정)과 :341(복호화 실패)뿐이다. ai.py:428-430 주석이 "2026-08-27 훈련에서 BYOK 3종에 503을 주입했더니 전부 502 + '키/모델명 확인'이 나갔다"고 적어둔 그 사고인데, 회귀 테스트만 안 붙었다. `_VENDOR_SICK_CODES` 목록이나 status_code 탐색(ai.py:90-93)이 깨지면 사용자는 벤더가 아픈 상황에서 다시 "키/모델명 확인"(=자기 키를 의심)을 보게 되고 CI는 통과한다.

**고침** test_ai.py의 fake_generate에 `status_code=503`을 가진 예외(또는 `.response.status_code`를 가진 객체)를 실어 던지게 하고 `/api/ai/draft`가 503 + "일시적으로 응답하지 못했어"를 주는지 잠근다. 410(gone)은 여전히 502여야 한다는 반대 케이스도 함께 넣는다(_VENDOR_SICK_CODES에 410을 안 넣은 결정을 지킨다).

**검증** (high) test_ai.py 의 예외 주입은 fixture(:10-30)가 `.fail(exc)` 로 넣는 `ValueError("upstream 500")`(:104)뿐이라 status_code 가 없어 ai.py:95 의 _upstream_sick 이 True 를 낼 경로가 없고, 짝인 _upstream_unreachable 만 test_degradation.py:100-128 에 단위테스트가 있다.

#### BQ-5 · 커넥션 풀 고갈(503) 예외 핸들러가 테스트 0건

`backend/app/main.py:209` — 백엔드 품질·테스트 · test-gap

PoolTimeoutError → 503 JSON 핸들러가 한 번도 실행되지 않아, 주석이 경고한 세 가지 함정으로 되돌아가도 CI가 초록이다.

**근거** coverage에서 app/main.py 미커버 라인에 209-210이 있다 — `db_pool_exhausted` 핸들러(main.py:187-214)의 본문(logger.warning + JSONResponse)이다. tests/test_degradation.py는 OperationalError만 주입하고(:29-30), 풀 고갈은 주입하지 않는다. 그런데 main.py:191-208 주석은 이 자리를 '실측으로 재현했다(pool_size=1에 동시 요청 → 500 text/plain)'고 적고, 되돌아갈 수 있는 세 가지 방식까지 구체적으로 나열해뒀다(핸들러 재사용 시 `exc.orig` AttributeError, 튜플 키 등록은 영원히 매치 안 됨, SQLAlchemyError로 넓히면 안 됨). 셋 다 **테스트가 없으면 조용히 통과하는** 변경이다. 실제로 튜플 키로 합치면 등록은 성공하고 테스트는 초록이며 프로드만 500 text/plain으로 돌아간다.

**고침** test_degradation.py에 db_down과 같은 모양으로 `get_db`가 `sqlalchemy.exc.TimeoutError`를 던지는 픽스처를 추가하고, `/api/posts`가 503 + application/json + `Retry-After: 5`를 주는지 잠근다(문구가 db_unavailable의 것과 다르다는 것도 함께 단언하면 핸들러 병합 회귀까지 막힌다).

**검증** (high) main.py:187-214 의 db_pool_exhausted 핸들러에 대해 test_degradation.py 는 OperationalError 만 주입하고(:29-34) sqlalchemy TimeoutError 를 넣는 곳이 없어, 주석 191-208 이 나열한 세 가지 회귀(특히 튜플 키 등록)가 전부 조용히 통과한다.

#### BQ-6 · NUL 가드 전수 목록에 series가 빠졌다 — 파일이 막겠다던 바로 그 모양의 4번째

> ✅ **2026-09-05에 고쳤다.** CASES 에 `?series=` 한 줄을 더했고, 인증이 필요해 그 파일
> 범위 밖인 `DELETE /api/push?endpoint=` 에도 같은 단언을 test_push.py 에 붙였다.

`backend/tests/test_nul_guard.py:25` — 백엔드 품질·테스트 · test-gap

posts.list_posts가 NUL을 막는 파라미터는 q·tag·author·series 넷인데, '무인증 입구를 전부 훑는다'고 선언한 CASES 목록에는 series만 없다.

**근거** app/routers/posts.py:244가 `has_nul(q, tag, author, series)`로 넷을 검사한다(series는 2026-08-27에 추가, 같은 줄 주석 241-243이 '이 줄을 안 고치면 그 주석이 네 번째로 맞는 말이 된다'고 적어놨다). 그런데 tests/test_nul_guard.py:25-36의 CASES에는 `?q=`, `?tag=`, `?author=`, `/api/skin?handle=`, `/api/authors/{h}` 다섯만 있고 `?series=`가 없다. 파일 docstring(:14-16)은 "문자열을 받는 무인증 입구를 **전부** 훑는다. 새 파라미터가 생기면 이 목록에 한 줄을 더하는 것으로 끝나야 한다"고 선언한다 — 선언과 목록이 어긋나 있다. 지금은 코드 쪽이 맞아서 증상이 없지만, has_nul 인자에서 series를 떨어뜨리는 회귀가 나면 `?series=a%00b`가 무인증 500 text/plain으로 돌아오고 이 파일은 초록이다(이 파일이 존재하는 유일한 이유가 그 사고다).

**고침** CASES에 `(f"/api/posts?series={NUL}", 422)` 한 줄을 추가한다. 인증이 필요해 이 파일의 범위 밖인 `DELETE /api/push?endpoint=`(routers/push.py:171, coverage 미커버)도 test_push.py에 같은 단언을 하나 붙여둔다.

**검증** (high) posts.py:244 는 `has_nul(q, tag, author, series)` 로 넷을 막는데 test_nul_guard.py:26-36 의 CASES 에는 series 가 없고, 같은 파일 docstring(:14-17)이 '무인증 입구를 전부 훑는다'고 선언해 선언과 목록이 실제로 어긋나 있다.

#### BQ-7 · GET /api/admin/ai-usage 전체가 테스트 0건

`backend/app/routers/admin.py:111` — 백엔드 품질·테스트 · test-gap

AI 비용을 사람이 볼 수 있는 유일한 화면의 백엔드가 통째로 미검증이다 — 집계 쿼리 셋과 캡 표기가 전부 미실행.

**근거** coverage에서 app/routers/admin.py 미커버 라인이 111-147, 즉 `ai_usage_summary`(admin.py:97-180) 본문 전체다. tests/ 전체에서 `/api/admin/ai-usage` 문자열이 0건이다(엔드포인트 grep 실측 — `/api/admin/ai-guard`는 test_admin_observability.py에 5건 있는데 그 형제만 안 쓸렸다). 미검증인 것: 최근 14일 추이 집계(`AiUsage.day >= since` group_by), 이번 달 상위 사용자(`month_start = day.replace(day=1)` + User inner join), `count_today_all_users`/`tokens_today_all_users`와 캡의 짝. 이 화면은 자기 docstring(:101-105)이 "Anthropic 청구는 AWS 밖이라 watch.sh가 보는 AWS Budgets가 원리적으로 못 본다 — 이 숫자를 안 보면 다음 명세서까지 아무도 모른다"고 적은 자리다. 집계가 틀린 숫자를 내놔도(예: inner join 때문에 삭제된 계정의 사용량이 top에서 통째로 빠지는 것) 잡을 장치가 없다.

**고침** test_admin_observability.py에 AiUsage 행을 며칠치 시드하고 (a) 비관리자 401/403, (b) today.calls/tokens가 시드 합과 같은지, (c) daily가 14일 창 밖의 행을 빼는지, (d) top_users_month가 이번 달 1일 경계를 지키고 이메일을 안 흘리는지를 단언한다.

**검증** (high) admin.py:97-180 의 ai_usage_summary 를 부르는 테스트가 tests/ 에 0건이고(형제인 /api/admin/ai-guard 는 test_admin_observability.py 에 5건), 14일 추이·이번 달 top_users 집계가 통째로 미검증인 것이 맞다 — 다만 비관리자 차단은 admin.py:24 의 라우터 레벨 require_admin 이 이미 잡고 다른 테스트가 그 경로를 덮으므로 fix 의 (a)는 불필요하다.

#### BQ-8 · services/ses_status.py는 커버리지 13% — 전 스위트가 함수째 대체한다

`backend/app/services/ses_status.py:29` — 백엔드 품질·테스트 · test-gap

'모름(None)'과 '미검증(False)'을 가르는 실제 로직이 한 줄도 실행되지 않는다. 그 구분을 검증한다는 테스트들은 함수를 lambda로 갈아끼운 것이라 계약만 확인한다.

**근거** coverage: app/services/ses_status.py 30문장 중 26문장 미커버(13%), 미커버 범위가 29-75로 `recipient_status` 본문 전부다. 원인은 tests/conftest.py:231-249의 autouse 픽스처 `no_ses`가 `admin_router.recipient_status`를 통째로 lambda로 바꾸기 때문이고(네트워크 차단이라 그 자체는 옳다), test_invites.py:69-121의 세 테스트도 전부 라우터 쪽 이름을 lambda/boom으로 대체한다. 그래서 실제로 미검증인 것: `ProductionAccessEnabled`가 False일 때 sandbox=True로 뒤집는 것(:50), sandbox=False면 verified를 안 보고 즉시 반환하는 것(:57-58), `NotFoundException`만 verified=False로 확정하고 다른 ClientError는 None으로 남기는 것(:63-69). 이 파일 docstring이 "'확인 못 함'을 '문제 있음'으로 바꿔 경고하면 늑대 소년이 된다"고 적은 규칙이 정작 그 규칙을 구현한 코드에서만 검증되지 않는다.

**고침** `boto3.client`를 가짜 sesv2로 monkeypatch하는 단위 테스트를 tests/test_ses_status.py로 따로 만든다(라우터를 안 거치므로 no_ses와 충돌하지 않는다): get_account 성공/권한오류, ProductionAccessEnabled True/False, get_email_identity의 NotFoundException vs AccessDenied 네 갈래를 각각 잠근다.

**검증** (high) conftest.py:231-249 의 autouse no_ses 가 admin 라우터의 이름을 lambda 로 갈아끼우고 test_invites.py 도 같은 자리를 대체해, services/ses_status.py:29-75 의 sandbox 뒤집기·프로덕션 조기반환·NotFoundException 만 False 로 확정하는 세 갈래가 실제로 한 번도 실행되지 않는다.

#### BQ-9 · 한 번도 호출된 적 없는 라우트 셋

> ✅ **2026-09-05에 고쳤다.** 셋 다 덮었다 — `/subscriptions/authors` 는 역할 필터와
> '자기 자신 제외'를, 그리고 **그 목록과 POST /subscriptions 의 404 판정이 같은 규칙인지**를
> 함께 본다. `/skin/me` 는 주인과 다른 writer 가 각각 저장한 뒤 자기 것이 오는지(그리고
> 사이트 스킨은 여전히 주인 것인지)를 본다. `/status/history` 는 days 클램프 양쪽 끝을 본다.

`backend/app/routers/subscriptions.py:115` — 백엔드 품질·테스트 · test-gap

GET /api/subscriptions/authors · GET /api/skin/me · GET /api/status/history 세 엔드포인트가 테스트에서 단 한 번도 불리지 않는다.

**근거** coverage 미커버 라인이 각각 app/routers/subscriptions.py 115-120(`subscribable_authors` 본문 전체), app/routers/skin.py 143(`get_my_skin`의 `return _out(me)`), app/main.py 613-614(`status_history` 본문 전체)다. tests/ 엔드포인트 grep에서도 `/api/subscriptions/authors`·`/api/skin/me`·`/api/status/history` 문자열이 0건이다. 셋 다 규칙이 얽혀 있는 자리다 — subscribable_authors는 `PUBLIC_BLOG_ROLES`와 '자기 자신 제외'를 지켜야 POST /subscriptions의 404 판정(subscriptions.py:156-162)과 목록이 일치하고, get_my_skin은 docstring(:136-138)이 "그건 사이트 스킨이라, 편집기가 남의 CSS로 채워지고 저장하면 자기 스킨이 남의 것 사본이 된다"는 실제 사고를 막는 자리이며, status_history는 days 클램프(1~90)를 거쳐 get_history를 부른다(get_history 자체만 test_status.py:32-51이 직접 본다).

**고침** 각각 한 개씩만 있어도 충분하다: (a) writer/pending/banned를 섞어 시드하고 /subscriptions/authors가 writer·admin만, 자기 자신은 빼고 주는지, (b) 주인과 다른 writer의 CSS를 각각 저장한 뒤 그 writer가 /skin/me를 부르면 자기 것이 오는지(주인 것이 아니라), (c) /api/status/history?days=999가 90일로 잘리고 days=0이 1로 올라가는지.

**검증** (high) tests/ 에 /api/subscriptions/authors·/api/skin/me·/api/status/history 문자열이 각각 0건이고(grep 종료코드 1로 확인), status_history(main.py:611-615)의 1~90 클램프는 라우터 밖의 get_history 단위테스트(test_status.py:32-51)로는 안 덮인다.

#### FQ-1 · 공용 입력칸 토큰의 placeholder 대비가 AA 미만 — 09-02에 검색창 한 곳만 고쳤다

`frontend/src/ui.ts:14` — 프론트 품질·접근성 · quality

ui.input의 placeholder가 밝은 모드 gray-400(약 2.5:1), 어두운 모드 gray-500(약 3.8:1)이라 앱의 거의 모든 폼이 WCAG AA(4.5:1)에 미달한다.

**근거** ui.ts:14가 `placeholder:text-gray-400 ... dark:placeholder:text-gray-500`이다. gray-400(#9ca3af)을 밝은 바탕(index.css:39 --color-canvas #fbfaf8)에 얹으면 대비가 약 2.5:1, 어두운 모드의 gray-500(#6b7280)은 dark:bg-white/5 위에서 약 3.8:1로 둘 다 4.5:1 미만이다. 이 토큰을 쓰는 곳: LoginPage.tsx:43-44(이메일·비밀번호), ResetPasswordPage.tsx:48, SettingsPage.tsx:146·174·239·249(표시명·주소·base URL·API 키), WritePostPage.tsx:533·628·682·735, PostDetailPage.tsx:602·610(댓글 이름·내용), SkinEditor.tsx:238, SlotEditor.tsx:220, AdminPage.tsx:336. 반면 HomePage.tsx:232-234에는 "`text-gray-400` 은 흰 배경에서 3:1 아래라 WCAG AA(4.5:1)에 못 미친다 … (2026-08-11 검사 9번의 잔여, 09-02 정리)"는 주석과 함께 HomePage.tsx:222의 손으로 쓴 검색창만 `placeholder:text-gray-500 dark:placeholder:text-gray-400`로 고쳐져 있다. 즉 정리 대상이 공용 토큰이 아니라 사본 하나였다.

**고침** ui.ts:14를 `placeholder:text-gray-500 dark:placeholder:text-gray-400`로 바꾼다(HomePage.tsx:222와 같은 값). 그러면 사본 두 곳(HomePage.tsx:222, AuthorPage.tsx:235)은 특수 클래스를 지우고 ui.input을 쓰게 정리할 수 있다.

**검증** (high) ui.ts:14가 실제로 `placeholder:text-gray-400 ... dark:placeholder:text-gray-500`이고, HomePage.tsx:231-233 주석과 :222만 gray-500/dark:gray-400으로 고쳐져 있어 공용 토큰은 그대로라는 지적이 사실이다.

#### FQ-10 · 관리·설정·구독 화면에 테스트가 0건이다

`frontend/src/pages/AdminPage.tsx:487` — 프론트 품질·접근성 · test-gap

프론트에서 되돌릴 수 없는 동작(계정 영구 삭제·차단·초대 취소·구독 해지·API 키 삭제)을 쥔 세 화면에 테스트 파일이 없다.

**근거** src/pages에 있는 테스트는 AuthorPage·HomePage·PortalPage·PostDetailPage·StatusPage·WritePostPage 6개뿐이다. AdminPage.test.tsx·SettingsPage.test.tsx·SubscriptionsPage.test.tsx는 존재하지 않는다. 잠기지 않은 분기: AdminPage.tsx:487 handleDelete의 확인창(취소하면 요청이 안 나가야 한다), :423 `loaded && !error && invites.length === 0` — 주석이 "못 불러온 상태에서 '아직 발급한 초대가 없어'라고 단언하게 된다"고 밝힌 조건, :505 infraStale 배너, :90 inviteState의 '사용됨이 만료보다 먼저'라는 순서 규칙(주석 :88-89가 중요하다고 못박았지만 검증이 없다). SubscriptionsPage.tsx:55의 '승인된 구독만 확인창'도 마찬가지다. 같은 성격의 규칙을 다른 화면에서는 테스트가 잠그고 있다(HomePage.test.tsx가 절전 폴백을, StatusPage.test.tsx가 분모 표시를).

**고침** 최소 세 가지를 잠근다 — ① inviteState의 사용됨/만료 우선순위(순수 함수라 export만 하면 된다), ② 확인창 취소 시 deleteUser/unsubscribeAuthor가 안 불린다, ③ 목록 조회 실패 시 '없어' 문구가 안 뜬다. 기존 테스트들의 createRoot+act 방식을 그대로 쓴다.

**검증** (high) pages의 테스트는 AuthorPage·HomePage·PortalPage·PostDetailPage·StatusPage·WritePostPage 6개뿐이고 AdminPage(:88-89 inviteState 순서 규칙, :423 빈 목록 단언, :488 확인창)·SettingsPage·SubscriptionsPage(:55)는 잠겨 있지 않다.

#### FQ-11 · 공용 컴포넌트 중 두 곳의 회귀 방지 장치가 테스트로 안 잠겨 있다

`frontend/src/components/PostRow.tsx:137` — 프론트 품질·접근성 · test-gap

PostRow의 삭제 확인창과 NotificationBell의 Esc·포커스 복귀는 둘 다 '빠져 있어서 사고가 났다'고 주석에 적힌 장치인데, 테스트가 없어 다음에 빠져도 CI가 못 잡는다.

**근거** src/components의 테스트는 CopyButton·SkinEditor·SlotEditor·Toc 4개뿐이다. PostRow.test.tsx는 없는데, PostRow.tsx:16-21은 "호출부는 둘인데 둘 다 확인 없이 바로 지우고 있었다 … '수정' 바로 옆의 오터치 한 번이 영구 삭제였다"며 확인창을 이 파일로 옮긴 이유를 적어두고 :137에 window.confirm을 둔다. 확인을 취소했을 때 onDelete가 안 불리는지 검증하는 테스트가 없다. NotificationBell.test.tsx도 없는데, NotificationBell.tsx:37-40은 "닫는 경로가 mousedown 하나뿐이라 키보드만 쓰는 사람은 … 닫을 수 없었다(2026-08-11 공백검사)"라며 Escape 처리(:46-51)와 버튼 포커스 복귀(:49), 그리고 늦은 폴링 응답이 배지를 되살리지 못하게 하는 readAtRef(:20-23)를 넣었다. 셋 다 검증이 없다. Layout.tsx:20-25의 '본문 바로가기' 링크와 Sidebar.tsx:68-77의 '집계를 못 받으면 숫자를 말하지 않는다'도 같은 처지다.

**고침** PostRow: window.confirm을 false로 스텁해 onDelete가 안 불리는 것과 true일 때 불리는 것 두 케이스. NotificationBell: 열린 상태에서 keydown Escape를 보내 드롭다운이 닫히고 종 버튼이 document.activeElement가 되는지. 둘 다 기존 테스트들의 createRoot+act 패턴으로 충분하다.

**검증** (high) components 테스트는 CopyButton·SkinEditor·SlotEditor·Toc 4개뿐이고, PostRow.tsx:137의 confirm과 NotificationBell.tsx:44-51의 Escape·포커스 복귀·readAtRef는 주석이 '빠져서 사고가 났다'고 적은 장치인데 검증이 없다.

#### FQ-7 · 밝은 모드 대비가 낮은 text-gray-400이 5곳 남았다

`frontend/src/pages/AuthorPage.tsx:235` — 프론트 품질·접근성 · quality

HomePage가 대비 문제로 고친 것과 같은 마크업이 AuthorPage 등에 gray-400 그대로 남아, 밝은 모드에서 약 2.5:1로 보인다.

**근거** AuthorPage.tsx:235의 검색창은 HomePage.tsx:222를 복사한 것인데 `placeholder:text-gray-400`이 그대로다(HomePage 쪽은 :232-234 주석과 함께 gray-500으로 올렸다). 같은 파일 :256의 '✕ 전체보기'는 `text-gray-400 transition hover:text-gray-600`이라 밝은 모드에 dark 보정도 없다 — HomePage의 같은 링크(:241·246·252)는 `text-gray-500`이다. 그 밖에 SettingsPage.tsx:173('/@' 접두 글자), PaymentPage.tsx:107('/ 월'), Toc.tsx:147(고정 목차의 '목차' 제목), SlotEditor.tsx:238(`text-gray-400 dark:text-gray-500` — 두 모드 다 미달)이 남아 있다. gray-400(#9ca3af)은 밝은 바탕(#fbfaf8)에서 약 2.5:1이다.

**고침** 밝은 모드는 text-gray-500, 어두운 모드는 dark:text-gray-400으로 통일한다(HomePage.tsx:222·241의 형태). 순수 장식이 아닌 글자에는 gray-400을 단독으로 쓰지 않는다.

**검증** (high) AuthorPage:235·256, SettingsPage:173, PaymentPage:107, Toc:147, SlotEditor:238에 dark 보정 없는(또는 두 모드 다 미달인) text-gray-400이 실재하고 HomePage는 같은 자리를 gray-500으로 올려둬 기준이 이미 저장소 안에 있다.

#### FQ-8 · 탭 제목·설명을 20개 라우트 중 4개만 설정한다

`frontend/src/useDocumentTitle.ts:5` — 프론트 품질·접근성 · quality

useDocumentTitle/useHead를 쓰는 화면이 NotFound·PostDetail·About·Author 넷뿐이라, /blog·/settings·/admin·/subscriptions·/login 등은 탭 제목·북마크가 전부 '블로그 만들기'로 같다.

**근거** 저장소 전체에서 useDocumentTitle/useHead 호출은 NotFoundPage.tsx:17, PostDetailPage.tsx:319, AboutPage.tsx:29, AuthorPage.tsx:175 넷뿐이다(head.ts·useDocumentTitle.ts 정의부와 테스트 제외). 그런데 useDocumentTitle.ts:5의 주석은 "SPA라 라우트가 바뀌어도 <title>이 그대로라 탭·북마크·검색결과가 전부 똑같이 보이던 걸 고침"이라고 적고 있다 — App.tsx:46-93의 나머지 16개 라우트에서는 그 고침이 아직 안 일어났다. 탭을 여러 개 띄우면 /blog·/settings·/blog/new이 구분되지 않고, 북마크 이름도 같다.

**고침** 각 페이지 최상단에 useDocumentTitle('글')·('설정')·('관리자')·('구독')·('로그인')·('새 글 쓰기') 등을 한 줄씩 넣는다. head.ts의 되돌리기 로직은 이미 화면 이탈 시 기본값 복구를 처리한다.

**검증** (high) useDocumentTitle/useHead 호출은 NotFoundPage:17·PostDetailPage:319·AboutPage:29·AuthorPage:175 넷뿐인데 App.tsx의 라우트는 20개라, /blog·/settings·/admin 등은 탭 제목이 구분되지 않는다.

#### FQ-9 · HomePage와 AuthorPage가 목록 화면을 통째로 복제해 두고 계속 갈라진다

`frontend/src/pages/AuthorPage.tsx:301` — 프론트 품질·접근성 · quality

검색 폼·updateParams·요청 순번 가드·쪽 이동 nav가 두 파일에 복제돼 있고, 지금도 '쪽을 넘기면 맨 위로 올린다'가 AuthorPage에만 없어 2쪽이 목록 끝에서 시작한다.

**근거** 복제 쌍: updateParams(HomePage.tsx:119-126 ↔ AuthorPage.tsx:55-62), 검색 제출 가드(HomePage.tsx:128-138 ↔ AuthorPage.tsx:79-90), reqSeq(HomePage.tsx:50 ↔ AuthorPage.tsx:101), 쪽 이동 nav(HomePage.tsx:373-395 ↔ AuthorPage.tsx:301-323). 갈라진 이력이 주석에 세 번 남아 있다 — AuthorPage.tsx:49-54(병합 안 해서 필터가 풀리던 것), :68-71(입력칸 동기화가 이 화면에만 없었던 것), :134-135("HomePage.tsx:58-64 에 있던 것을 그대로 옮겼다 … 그 함수가 쓰는 되돌리기는 안 옮겼다"). 아직 남은 차이: HomePage.tsx:140-143의 goToPage는 `window.scrollTo({top:0})`를 하는데 AuthorPage.tsx:306·317은 updateParams만 불러, `/@handle`에서 '다음'을 누르면 새 목록이 그려져도 스크롤이 화면 맨 아래에 남는다. 또 HomePage는 1쪽에서 page 파라미터를 지우고 AuthorPage는 `?page=1`을 남긴다.

**고침** 당장은 AuthorPage.tsx:306·317을 HomePage의 goToPage와 같은 헬퍼로 바꾼다. 근본적으로는 검색 폼·쪽 이동·updateParams를 components/의 공용 조각으로 빼서 PostRow가 이미 한 것(마크업 계약 한 곳)을 목록 화면 로직에도 적용한다.

**검증** (high) HomePage.tsx:139-142 goToPage는 scrollTo와 1쪽 page 제거를 하는데 AuthorPage.tsx:306·317은 updateParams({page:String(...)})만 불러 스크롤 복귀가 없고 ?page=1이 남는 차이가 실재한다.

#### SEC-02 · PUT /api/ai/keys/{provider} 가 DB 커넥션을 쥔 채 시간 상한 없는 getaddrinfo 를 돈다 — 리밋도 없다

> ✅ **2026-09-05에 고쳤다.** 셋 다 했다 — ① `@limiter.limit("20/hour")` + `request`,
> ② 검증 직전 `db.commit()` 으로 커넥션 반납(만료 대비해 `uid` 를 먼저 떠둔다),
> ③ `services/llm_keys._resolve` 가 getaddrinfo 를 데몬 스레드에 맡기고 3초에 포기한다.
> 시험 둘: 등록된 한도가 실제로 걸려 있는지, 그리고 응답 없는 resolver 를 심어 5초 안에
> 거절하는지(상한이 죽으면 30초를 기다린다).

`backend/app/routers/ai.py:141` — 백엔드 보안 · security

이 저장소가 ai.py·uploads.py 두 곳에서 '느린 외부 호출 앞에 커밋해 커넥션을 놓는다'고 실측까지 적어 고친 그 패턴의 세 번째 자리다. set_key 는 커밋 없이 SSRF 검증용 DNS 조회를 하고, 그 라우트에는 레이트리밋이 없다.

**근거** ai.py:141-168 의 set_key 에는 @limiter.limit 도 `request: Request` 인자도 없다(같은 파일 :335 의 create_draft 는 10/hour 를 건다). 의존성 require_writer → get_current_user(core/deps.py:32-43)가 `db.get(User, ...)` 로 트랜잭션을 열고 커밋하지 않으므로(만료 케이스 외) 커넥션은 체크아웃 상태다. 그 상태로 ai.py:159-163 이 llm_keys.validate_base_url 을 부르고, services/llm_keys.py:132-139 의 socket.getaddrinfo 에는 타임아웃 인자가 없다 — 블랙홀 DNS를 가리키는 호스트명이면 glibc resolver 기본값(timeout×attempts×nameserver)만큼 수십 초 블록된다. 라우터 핸들러가 전부 sync `def` 라 이건 anyio 스레드풀(정원 40, core/database.py:12-13) 한 칸 + 커넥션 풀(pool_size=10+overflow=10, pool_timeout=5, core/database.py:73-82) 한 칸을 동시에 묶는다. 승인된 writer 한 명이 `{"key":"sk-...","base_url":"https://<느린호스트>/v1"}` 를 20번 동시에 보내면 풀이 차고, 무관한 요청이 5초 뒤 503(main.py:187-214)으로 떨어진다. ai.py:362-385 와 uploads.py:114-120 이 각각 벤더 호출·S3 호출 앞에서 정확히 이 이유로 db.commit() 을 넣어뒀는데(실측 checkedout 1→0 까지 적혀 있다) BYOK 키 등록 경로만 안 쓸렸다.

**고침** ① set_key 에 `request: Request` + @limiter.limit(넉넉히, 예: 20/hour)를 건다 — 키 등록은 자주 하는 동작이 아니다. ② validate_base_url 호출 직전에 db.commit() 으로 커넥션을 놓는다(ai.py:385·uploads.py:120 과 같은 근거 주석을 단다). ③ getaddrinfo 자체에 상한이 없으므로 별도 스레드+타임아웃으로 감싸거나, 최소한 이 두 가지로 동시 점유 수를 묶는다.

**검증** (medium) ai.py:141-168 에 limiter도 request도 없고 llm_keys.py 의 getaddrinfo 에 타임아웃이 없어 커넥션을 쥔 채 블록되는 건 사실이나, 승인된 writer 만 부를 수 있어 영향이 create_draft(:385)·uploads(:120)가 고친 무인증 경로만큼 크지 않다.

#### SEC-03 · InviteOut 의 이메일 세 필드가 EmailStr — UserRead 가 '한 행이 목록 전체를 죽인다'며 걷어낸 그 실패 모드를 되살렸다

> ✅ **2026-09-05에 고쳤다.** 세 필드를 `str` 로 내렸고 `InvitePreview.email` 도 같이
> 내렸다(같은 규칙의 네 번째 자리였다). 레거시 행을 심어 초대 목록이 200 을 내는지 보는
> 시험을 붙였고, 되돌리면 ValidationError 로 실패하는 것까지 확인했다.

`backend/app/schemas/invite.py:34` — 백엔드 보안 · quality

출구 스키마에서 EmailStr 을 쓰면 DB에 형식이 어긋난 행 하나로 응답 검증이 터져 목록 전체가 500이 된다. schemas/user.py 가 그 이유로 UserRead.email 을 str 로 내렸는데, 08-07에 생긴 InviteOut 은 users.email 을 먹는 두 필드에 EmailStr 을 그대로 썼다.

**근거** schemas/invite.py:26,34,35 — `email: EmailStr`, `created_by_email: EmailStr | None`, `used_by_email: EmailStr | None`. 뒤 둘은 routers/admin.py:314-327 에서 users 테이블의 email 컬럼을 outerjoin 으로 그대로 실어온다. 같은 저장소의 schemas/user.py:43-52 는 정반대로 적어뒀다: "여기가 EmailStr이면 DB에 형식이 어긋난 행이 하나만 있어도 GET /admin/users 가 응답 검증에서 터져 목록 전체가 500이 된다... 2026-08-11 동적 분석에서 실제로 재현했다 — a@test.local(예약 TLD) 한 행 때문에 500". 실측으로 확인: pydantic EmailStr 은 지금도 a@test.local 을 "special-use or reserved name" 으로 거절한다. 지금은 입구가 좁혀져 있어(backend/scripts/create_user.py:93-97 이 같은 검증기를 돌린다) 즉시 터지지는 않지만, 그 가드가 생기기 전에 만들어진 계정이나 psql 로 넣은 행이 하나라도 있으면 GET /api/admin/invites 가 통째로 500이고, 초대 감사기록(admin.py:300-307 이 '누구를 언제 들였나'의 유일한 답이라고 적은 화면)을 볼 방법이 psql 뿐이 된다. UserRead 쪽은 str 로 고쳐 두었으므로 /admin/users 는 멀쩡히 뜬다 — 두 화면이 갈린다.

**고침** InviteOut 의 세 필드를 `str`/`str | None` 로 내린다(형식 강제는 입구인 InviteCreate.email 의 EmailStr 과 create_user.py 가 이미 한다). schemas/user.py:43-52 와 같은 근거 주석을 한 줄 남겨 다음 스키마가 또 EmailStr 로 돌아가지 않게 한다.

**검증** (medium) invite.py:26,34,35 의 EmailStr 과 user.py:43-52 의 정반대 근거 주석이 실제로 확인되고 EmailStr 이 지금도 a@test.local 을 거부함을 실행해 확인했으나, 입구(create_user.py:93-97·InviteCreate)가 다 막혀 있어 psql 로 넣은 레거시 행이 있어야만 터진다.

#### SEC-04 · 차단된 계정은 자기 블로그 주소를 못 내린다 — update_my_handle 주석이 '차단된 사람도 지울 수 있다'고 적은 것과 반대

> ✅ **2026-09-05에 고쳤다(②안).** banned 를 통과시키는 ①안은 성립하지 않는다 —
> ban 이 `token_version` 을 올려 토큰을 죽이므로 **부를 주체가 없다.** 그래서 주석을
> 사실로 고치고(‘여기서 되살아난 건 승인취소뿐이다’) 관리자 쪽에 회수 경로를 만들었다:
> `POST /api/admin/users/{id}/release-handle`. 화면에도 붙였다 — API 만 두면 이 저장소가
> GAP-4 로 지적한 '만들어져 있는데 연결이 없는' 모양이 하나 더 는다.

`backend/app/routers/auth.py:544` — 백엔드 보안 · correctness

의존성이 get_current_user 라 banned 는 함수 본문에 들어오기 전에 403이다. 그래서 08-19에 되살렸다는 '나가는 문'이 revoke(pending)에만 열렸고 ban 에는 안 열렸다. handle 은 유니크라 그 주소는 영구히 점유된 채 아무도 못 쓴다.

**근거** routers/auth.py:521-523 은 "의존성이 get_current_user 인 건 **지우기를 살리기 위해서다**", :544-548 은 "08-19 오전에 이 함수를 통째로 require_writer 로 좁혔더니 **차단·승인취소된** 사람이 자기 주소를 내릴 방법이 사라졌다... **자기 것을 자기가 못 지우는 상태**는 그것대로 잘못이다 — 주소는 다른 사람이 이어 쓸 수 있어야 하고" 라고 적는다. 그런데 core/deps.py:39-40 의 get_current_user 가 `if user.role == BANNED_ROLE: raise HTTPException(403)` 이라 banned 는 :549 의 분기까지 도달하지 못한다 — 지우기든 만들기든 전부 403이다. 되살아난 건 승인취소(pending)뿐이다. 결과: models/user.py:40-43 의 uq_users_handle_lower 때문에 차단된 계정의 handle 은 계속 예약돼 있고, auth.py:553-557 이 다른 사람에게 409를 준다. 관리자에게도 남의 handle 을 비우는 라우트가 없어(routers/admin.py 전수) 해소 경로는 계정 삭제(admin.py:274-288)뿐이다.

**고침** 둘 중 하나. ① update_my_handle 을 banned 도 통과시키되(전용 의존성 또는 get_current_user_optional + 자체 판정) 빈 값=삭제만 허용한다. ② 그게 과하면 주석을 사실로 고치고(‘승인취소는 되고 차단은 안 된다’), admin 쪽에 handle 회수 경로를 하나 만든다. 지금은 코드와 주석이 정면으로 다르다.

**검증** (high) auth.py:521-523·544-548 주석이 '차단된 사람도 지울 수 있다'고 적었는데 deps.py 의 get_current_user 가 BANNED_ROLE 을 403으로 먼저 끊어 :549 분기에 못 닿는다 — 코드와 주석이 정면으로 다르다.

#### SEC-05 · config.py 의 origin_secret 주석에 '403이 200+HTML로 보인다'가 남아 있다 — 08-10 보안검사가 '셋을 함께 고쳤다'고 적은 그 거짓

> ✅ **2026-09-05에 고쳤다.** 그 문장을 사실로 바꾸고(밖에서도 403 이다) 왜 이 한 벌만
> 남았는지를 그 자리에 적었다. RECOVERY.md·variables.tf 는 이미 과거형으로 고쳐져 있다.

`backend/app/core/config.py:120` — 백엔드 보안 · ops

07-28에 제거된 CloudFront custom_error_response 를 전제로 한 서술이 네 번째 사본으로 남았다. 게다가 '이유는 main.py 미들웨어 주석 참고'라고 가리키는데, 그 주석은 정반대(밖에서도 403으로 보인다)를 말한다.

**근거** core/config.py:118-120 — "순서를 뒤집으면 /api/*가 통째로 막힌다(밖에서는 403이 아니라 200+HTML로 보인다. 이유는 main.py 미들웨어 주석 참고)." 지목된 main.py:451-455 는 "⚠️ 이 403은 밖에서도 403으로 보인다. (2026-08-10 정정) 예전엔 여기에 ... 적혀 있었는데, 그 블록은 2026-07-28에 제거됐다 ... 같은 거짓이 RECOVERY.md·variables.tf 에도 있어서 셋을 함께 고쳤다" 이다. 실제로 RECOVERY.md:143 과 terraform/variables.tf:116 은 과거형으로 고쳐져 있고(‘…라고 적혀 있었는데 그 블록은 제거됐다’), 저장소 전체에서 현재형으로 남은 사본은 config.py:120 하나다. docs/security-review-20260810.md:179-183 이 이 부류를 "런북이 재해 중에 없는 증상을 찾게 만들었다 … RTO 42분 중 20분이 문서가 틀린 자리"로 분류해 둔 바로 그것이다. origin_secret 을 켜다 막혔을 때 사람이 제일 먼저 여는 파일이 이 설정 파일이라 영향이 작지 않다.

**고침** config.py:120 의 괄호를 main.py:451-455 와 같은 문장으로 바꾼다(‘밖에서도 403으로 보인다’). 겸사겸사 '넷이었다'를 기록으로 남겨 다음 사본이 또 안 생기게 한다.

**검증** (high) config.py:120 만 현재형으로 '200+HTML'이 남아 있고 RECOVERY.md:142-145·variables.tf:115-117 은 과거형으로 고쳐져 있음을 전수 grep 으로 확인했다 — 게다가 참조하라는 main.py:451-455 가 정반대를 말한다.

#### SEC-06 · approve/revoke/toggle-pro 가 banned 계정에도 그대로 먹어 차단이 조용히 풀린다 — unban_user 만 상태 전이를 검사한다

> ✅ **2026-09-05에 고쳤다.** `_reject_banned()` 를 셋에 걸어 해제를 unban 한 문으로 모았다.
> 시험 넷 — approve·revoke·toggle-pro 가 각각 400 이고 역할·is_pro 가 그대로인지, 그리고
> **unban 뒤에는 approve 가 다시 먹는지**(정책이 막힌 게 아니라 한 문으로 모인 것인지).

`backend/app/routers/admin.py:198` — 백엔드 보안 · security

unban_user 는 '차단된 계정이 아니야' 400 으로 전이를 지키는데, approve_user 는 banned → writer 를 한 번에 만든다. '차단 해제는 pending 으로 되돌려 재승인을 받는다'는 이 파일의 정책이 옆 라우트로 우회된다.

**근거** routers/admin.py:198-207 approve_user 와 :210-219 revoke_user 는 `if user.role == "admin"` 만 보고 곧바로 role 을 writer/pending 으로 덮는다 — 대상이 BANNED_ROLE 인지는 안 본다. 반면 :247-256 unban_user 는 `if user.role != BANNED_ROLE: raise 400` 으로 전이를 명시적으로 지키고, :249 주석이 "차단 해제: pending 으로 되돌림(재승인 필요)" 라고 정책을 선언한다. 즉 banned 계정에 approve 를 한 번 누르면 재승인 단계를 건너뛰고 곧장 writer 가 된다. :259-271 toggle_pro 도 banned 에게 is_pro 를 켠다. 회수 판정이 전부 '읽는 쪽이 role 을 본다'(models/user.py:110-121, services/push.py·email.py)에 걸려 있어서, role 이 바뀌는 순간 블로그·알림·글쓰기가 전부 되살아난다. 감사 기록도 없다(admin 라우터에 로깅 0건).

**고침** approve_user·revoke_user·toggle_pro 에 `if user.role == BANNED_ROLE: raise HTTPException(400, "차단된 계정이야. 먼저 차단을 풀어줘")` 를 넣어 해제를 unban_user 한 곳으로 모은다. tests/test_admin.py 에 'banned 에 approve → 400' 한 쌍을 추가한다.

**검증** (medium) admin.py:198-219 는 admin 여부만 보고 :247-256 unban_user 만 전이를 지키는 게 맞지만, 관리자 전용이고 프론트(AdminPage.tsx:612-635)가 banned 행에 승인 버튼을 안 그려서 목록이 낡았을 때만 눌리는 좁은 경로다.

#### SEC-07 · POST /auth/verify 가 인증 토큰을 쿼리스트링으로 받는다 — 초대 토큰·푸시 endpoint 를 본문으로 옮긴 규칙의 마지막 미청소 입구

> ✅ **2026-09-05에 고쳤다.** `VerifyEmailRequest`(SafeModel + max_length=200)를 만들어
> 본문으로 받고 프론트 `verifyEmail` 도 같이 옮겼다. 구경로는 **안 남겼다** — push 쪽과
> 달리 이 경로는 allow_signup=False 라 발급되는 토큰이 0 이고, 캐시된 옛 번들이 부를 일도
> 없다. 시험 셋: 본문이면 200, 쿼리스트링이면 422, 위조 토큰이면 400.

`backend/app/routers/auth.py:233` — 백엔드 보안 · security

`token: str` 은 FastAPI 에서 쿼리 파라미터다. 이 저장소는 같은 성질의 값(초대 토큰·기기 endpoint)을 두 번에 걸쳐 '읽기여도 POST 본문'으로 옮기며 그 근거를 길게 적어뒀는데, 이메일 인증 토큰만 남았다. 현재는 allow_signup=False 라 토큰 발급 자체가 없어 도달 불가다.

**근거** routers/auth.py:233-234 `@router.post("/verify") def verify_email(token: str, ...)` — Body/Field 지정이 없으므로 스칼라는 쿼리 파라미터로 잡힌다(POST /api/auth/verify?token=eyJ...). 같은 파일 :159-162 는 초대 미리보기를 POST 로 만든 이유를 "uvicorn 액세스 로그는 쿼리스트링까지 찍는다 … 실측: GET /api/auth/invite?token=... 이 로그 라인에 그대로 나온다" 로 적었고, schemas/invite.py:51-55 는 "reset-password 가 같은 이유로 이미 본문을 쓴다" 고 못박는다. routers/push.py:106-121 은 09-02에 같은 판단으로 endpoint 를 본문으로 옮겼다. 그 셋이 세운 규칙에 verify 만 안 맞는다. 이 토큰은 24시간짜리이고 통과하면 email_verified=True 가 된다(auth.py:254). 다만 발급처는 register 안 두 곳뿐이고 register 는 core/config.py:103 의 allow_signup 기본 False 로 :49-53 에서 403이라, 지금 설정에서는 로그에 남을 토큰 자체가 생기지 않는다 — 가입을 여는 날 바로 열리는 잠재 구멍이다.

**고침** InviteToken 과 같은 모양의 본문 스키마(SafeModel + max_length)를 하나 만들어 verify 도 본문으로 받는다. 프론트 호출부를 같이 고치고, 구경로가 필요하면 push.py:149-167 처럼 deprecated 로 남겨 액세스 로그에서 0건이 된 뒤 지운다.

**검증** (medium) auth.py:233-234 의 token 이 쿼리 파라미터인 건 맞고 초대·푸시가 세운 규칙에 어긋나지만, 발급처가 register 둘뿐이고 allow_signup 기본 False(:49-53)라 현재 설정에서는 로그에 남을 토큰 자체가 생기지 않는 잠재 항목이다.


### 기각 — 1건

- **FQ-12** '구독'이라는 한 단어가 서로 다른 두 기능을 가리킨다
  - 기각 사유: Layout.tsx:66·68-73에서 '구독'과 'Pro/Pro ✓'가 나란히 놓여 결제 입구가 따로 구분되고 각 화면 제목도 'Pro 구독'과 '구독'으로 갈라져 있어, 오동작이 아니라 용어 취향에 가깝다.

---

## 이번 검사에서 배운 것

세션 한도에 두 번 걸렸다. 7갈래를 한 번에 돌리면 서브에이전트 토큰이 150만을 넘는다.
탐색 결과를 **파일로 굳혀두고** 검증을 따로 돌리는 구조로 바꾸니 검증은 40만으로 끝났다
(탐색이 비싸고 검증은 싸다). 다음에 같은 검사를 할 때는 처음부터 그렇게 쪼갠다.
