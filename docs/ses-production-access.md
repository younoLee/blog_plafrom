# SES 프로덕션 액세스 — 재신청

## 상태 (2026-07-31 실측)

| | |
|---|---|
| `ProductionAccessEnabled` | `false` (샌드박스) |
| 이전 심사 | `DENIED` · CaseId `178238423300607` |
| 발송 한도 | 24시간 200통 · 초당 1통 |
| 검증된 수신 주소 | 3개 (전부 `VerifiedForSendingStatus: true`) |
| 억제 목록 | `BOUNCE` · `COMPLAINT` 활성 · 등록된 주소 0건 |
| 집행 상태 | `HEALTHY` |

⚠️ `list-email-identities`의 요약 필드는 검증 여부를 `None`으로 준다. 그걸 '미검증'으로
읽으면 안 된다 — 참값은 `get-email-identity`의 `VerifiedForSendingStatus`다.

**API로는 재제출할 수 없다.** `sesv2 put-account-details`는 심사 이력이 있으면
`ConflictException`을 낸다. AWS Support API는 유료 플랜 전용이다. → 콘솔에서 사람이 해야 한다.

## 제출 절차 (콘솔)

### ⚠️ 먼저: 리전을 반드시 확인한다

프로덕션 액세스는 **리전별**이다. 콘솔 우측 상단이 **서울(ap-northeast-2)**인지 보고 시작한다.
다른 리전에서 신청하면 승인돼도 이 앱은 그대로 샌드박스다 — 그리고 그 사실을
한동안 모른다(`watch.sh`는 서울만 본다).

### ❌ 막힌 경로 두 개 (2026-07-31에 실제로 확인함)

두 번 헛걸음하지 않도록 안 되는 것부터 적는다.

| 경로 | 결과 |
|---|---|
| SES 콘솔 → Account dashboard → **Request production access** | **막힘.** 이 버튼은 `PutAccountDetails`를 부르는데, 심사 이력이 있으면 **`ConflictException`**이다. API로 직접 쳐서 확인했다 |
| Support Center → 케이스 `178238423300607` → **Reply** | **막힘.** 케이스가 닫혀 있어 회신 버튼이 없다 |
| `aws support` CLI로 케이스 조회·회신 | **막힘.** `SubscriptionRequiredException` — Support API는 유료 플랜 전용 |

계정에는 아직 **07-22의 옛 245자 사유서**가 그대로 들어 있다(`get-account`의
`Details.UseCaseDescription`). 즉 그동안 새 신청이 접수된 적은 한 번도 없다.

### ✅ 되는 경로 — 새 지원 케이스 (Service limit increase)

**Basic(무료) 플랜에서도 '한도 증가' 케이스는 열 수 있다.** 유료가 필요한 건 기술지원이다.

1. AWS Support Center → **Create case**
2. 유형: **Service limit increase** (Technical support 아님 — 그건 유료다)
3. 항목을 이렇게 채운다:

| 항목 | 넣을 값 |
|---|---|
| **Limit type** | `SES Sending Limits` |
| **Mail Type** | `Transactional` |
| **Website URL** | `https://d2j66m9udyg9yq.cloudfront.net` |
| AWS 서비스 약관·AUP 준수 확인 | **Yes** |
| **Region** | `Asia Pacific (Seoul)` ← 반드시. 리전별이다 |
| **Limit** | `Desired Daily Sending Quota` |
| **New limit value** | `200` (현재값 그대로. 한도를 올리려는 게 아니라 **샌드박스 해제**가 목적이라는 걸 본문에 적는다) |
| **Use case description** | 아래 '붙여넣을 본문' **전체** (첫 문단이 재신청 사유를 밝힌다) |
| Contact language | English |

4. **Submit**

보통 24시간 안에 케이스에 답이 달린다.

### 제출 뒤

- 보통 **24시간 안에** 답이 온다(케이스에 회신 형태).
- 결과 확인은 콘솔 말고 이걸로도 된다:
  `aws sesv2 get-account --region ap-northeast-2 --query '{Prod:ProductionAccessEnabled,Review:Details.ReviewDetails}'`
- **승인되면** `scripts/watch.sh`의 `SES_SANDBOX_EXPECTED=true` → `false`로 바꾼다(아래 '승인된 뒤 할 일').
- **거부되면** 아래 '거부되면' 절대로. 사유를 읽고 그 지점만 회신한다.

## 승인 전까지의 다리

`scripts/ses_verify_recipients.sh`로 계정 주소를 검증 ID로 등록하면 **샌드박스인 채로도**
그 주소들에는 메일이 닿는다. 심사를 기다리지 않아도 되고, 신청에 아무 해도 없다.
다만 주소 주인이 AWS 확인 메일을 눌러야 하므로 초대할 때마다 붙는 마찰이 있다 —
프로덕션 액세스를 받으려는 이유가 정확히 그 마찰을 없애는 것이다.

## 왜 사유서를 새로 쓰는가

2026-07-22판(맨 아래 부록)은 **논거 두 개가 더 이상 사실이 아니다.**

| 옛 사유서의 주장 | 지금 |
|---|---|
| "방문자가 가입 폼을 제출하면 인증 메일을 보낸다" | 07-28에 초대제로 닫힘 (`allow_signup=False` → 403) |
| "뉴스레터 더블 옵트인으로 수신 동의를 받는다" | 07-31에 폐지 — 공개 수집 엔드포인트 자체가 없어짐 |

그대로 내면 AWS에 사실과 다른 진술을 하는 것이고, 두 번째 거부를 부르기 좋다.

**바뀐 사실이 오히려 유리하다.** 공개 가입이 없고 목록 메일이 0이면 바운스·불만 노출이
구조적으로 거의 없다 — 심사가 보려는 게 바로 그것이다. 07-22에는 "누구나 가입할 수 있게
해달라"는 이야기였는데, 지금은 "초대한 사람에게만 보낸다"는 이야기다.

## 실측한 계정 현황 (2026-07-31 · 프로덕션 직접 확인)

서버를 켜서 프로덕션 DB에서 직접 셌고, 쓰레기 계정 2개(`test@test.com`·`ppap@gmail.com`)를
지운 뒤의 값이다.

| 이메일 | 역할 | SES 검증 |
|---|---|---|
| es2646526@gmail.com | admin | ✅ |
| jinukkim0305@naver.com | writer | ✅ |
| youno3249@gmail.com | writer | ✅ |
| demo@example.com | writer | 데모 계정 (도메인상 검증 불가·불필요) |

- 계정 **4개**, 전부 `email_verified`
- **새 글 알림을 켠 사람: 0명** (승인된 계정 구독 2건이지만 notify는 전부 off)
- 글 21개
- 폐지된 뉴스레터 테이블 잔존 행 **4개(PII)** — 사유서와 무관하지만 정리 대상.
  아직 안 지웠다(요청 범위 밖이라 판단).

### ✅ `ALLOW_SIGNUP` 확인 완료 (2026-07-31)

프로덕션에서 직접 검증했다. 두 방향 모두 확인:

- `/home/ec2-user/blog/.env`에 `ALLOW_SIGNUP` **0건** → 기본값 `False`가 적용된다
- 실행 중 백엔드가 보는 값: `allow_signup = False`
- **오리진 시크릿을 붙인 실제 가입 요청** → `403 {"detail":"가입은 현재 초대제로 운영됩니다..."}`

⚠️ 함정: 시크릿 **없이** 부르면 같은 403이지만 `{"detail":"Forbidden"}`이다 —
그건 오리진 시크릿 미들웨어가 막은 것이지 가입 게이트가 아니다. 처음에 그걸로
'확인했다'고 할 뻔했다. 상태코드가 같아도 **이유가 다르면 증명이 아니다.**

### ⚠️ 이 숫자가 신청 논거를 바꾼다

**실제 사람 3명이 전부 이미 SES 검증돼 있다.** 즉 지금 이 순간 메일을 못 받는 사람은 없다.
그래서 "지금 막혀 있다"로 쓸 수 없고, **"앞으로 초대할 때 마찰이 생긴다"**로 써야 한다.
그건 사실이지만 약한 논거다 — AWS가 "그럼 그때 검증하면 되지 않나"라고 답할 수 있고,
그 반박이 맞다. 아래 본문은 그 약함을 숨기지 않고 쓴 것이다. 과장해서 통과시키면
나중에 그 한 줄 때문에 전체를 의심받는다.

**신청 전에 쓰레기 계정 2개를 지우면** 문장이 깨끗해지고(6개 → 4개) 사실도 더 정확해진다.
관리자 화면에서 지울 수 있다(서버 필요).

## 붙여넣을 본문 (2026-07-31판 · 실측 반영)

```
We are asking for the sending sandbox to be removed for this account in the Asia Pacific (Seoul) region. We are not asking for a higher sending quota; the current 200 messages per day is far more than we need, and we have left the requested value unchanged for that reason.

This is a second request. An earlier one was denied under case 178238423300607. That request was two sentences long and did not explain how we obtain recipients or handle bounces, so the denial was reasonable. Rather than resubmit it, we have written this from scratch, and in the meantime we also changed the application itself to remove the parts that carried the most risk. Those changes are described below and can be verified against the live site.

Personal technical blog with a single author, at https://d2j66m9udyg9yq.cloudfront.net. We send transactional email only. No marketing, no bulk mail, no newsletters, and no purchased, rented or imported lists.

Who can receive mail from us, and why that set is closed:

Public registration is disabled. The registration endpoint returns HTTP 403 unless an explicit server setting enables it, and that setting is off by default and off in production. Accounts are created only by the site owner, using a command line script, for people the owner invites. There is no form anywhere on the site that accepts an email address from an anonymous visitor. We removed our newsletter subscription feature entirely on 2026-07-31, including the endpoint that accepted addresses, so no third party can cause us to send mail to any address.

The practical consequence is that every recipient of every message we send is an account holder that the owner created by hand.

Messages we send and what triggers each:

1. Account verification. Sent when the owner creates an invited account, so the recipient can confirm the address. Any account still unverified after 24 hours is deleted automatically by a background job.

2. Password reset link. Sent only on explicit request from the login page. Single use, expires in one hour, and invalidated as soon as it is used.

3. New post notification. Sent only to account holders who subscribed to a specific author and then explicitly turned notifications on for that author. Both the subscription and the notification toggle are off by default and require the author's approval, and either can be turned off at any time from the account portal.

Current scale, so you can see exactly how small this is: 4 registered accounts. Three belong to real people, the owner and two invited writers. The fourth is a shared read-only demo account we publish so that visitors can look around the interface without registering. Nobody currently has new post notifications enabled. Steady state is well under 50 messages per month. We are not asking for a large sending quota, only for removal of the sandbox restriction.

Why we are asking: we are not currently blocked, and we want to be straightforward about that. We work around the sandbox by adding each invited person's address as a verified identity inside our own AWS account, and all three current users are verified that way. The problem is what that costs each new person: before they can receive the verification message for the account we created for them, they must first find and click an Amazon confirmation email for an AWS account they have no relationship with. It is confusing, it arrives before any message from us, and it puts a step we cannot support in front of every future invitation. We would like invitations to work the way they should, where the owner creates the account and the person receives exactly one message, from us.

Abuse prevention already in place: registration is rate limited to 5 requests per hour per IP, password reset email to 5 per hour per IP, and login to 10 per minute per IP. AWS WAF sits in front of the API with the AWS managed IP reputation list, core rule set, and known bad inputs rule groups attached in blocking mode.

Bounce and complaint handling: the account level suppression list is enabled for both BOUNCE and COMPLAINT, so SES suppresses addresses that hard bounce or complain and we never retry them. Because there is no public sign up and no mailing list, our bounce exposure is limited to a typo made by the owner when inviting someone, and such an account is removed automatically by the 24 hour cleanup described above.
```

## 본문에 쓴 사실의 근거

| 주장 | 근거 | 확인 |
|---|---|---|
| 공개 가입이 403 | `app/core/config.py` `allow_signup: bool = False` · `app/routers/auth.py:40` | 코드 |
| 프로덕션에도 꺼져 있음 | 배포 설정 어디에도 `ALLOW_SIGNUP` 없음(기본값 적용) | grep |
| 계정은 스크립트로만 생성 | `backend/scripts/create_user.py` | 코드 |
| 뉴스레터 엔드포인트 제거 | `app/routers/subscribers.py` (공개 라우트 4종 삭제, 관리자용만 잔존) | 코드 · 회귀 테스트 |
| 임의 주소 발송 경로 0 | `tests/test_subscribers.py::test_public_subscribe_endpoint_is_gone` | 테스트 |
| 미인증 계정 24시간 뒤 자동 삭제 | `app/services/cleanup.py` `UNVERIFIED_TTL_HOURS = 24` | 코드 |
| 새 글 알림은 승인+명시적 on일 때만 | `app/services/email.py notify_new_post` (`approved` AND `notify`) | 코드 |
| 재설정 토큰 1회용·1시간 | `app/routers/auth.py` (`expire_hours=1`, `token_version` 스냅샷) | 코드 |
| 레이트리밋 5/h · 5/h · 10/min | `app/routers/auth.py` 데코레이터 | 코드 |
| WAF 관리형 3종 차단 모드 | Web ACL `CreatedByCloudFront-920ca6f5`, 3개 그룹 `OverrideAction: None` | AWS |
| 바운스·불만 억제 목록 활성 | `sesv2 get-account` → `SuppressedReasons: [BOUNCE, COMPLAINT]` | AWS |

**정직 주의 — WAF.** 관리형 3종은 그룹 수준에서 차단 모드가 맞지만, CommonRuleSet 안의
`SizeRestrictions_BODY`·`CrossSiteScripting_BODY` 2개는 **Count**로 내려가 있다.
그래서 본문은 "세 그룹이 차단 모드로 붙어 있다"까지만 말하고 "모든 규칙이 차단한다"고는
쓰지 않았다. 과장하면 나중에 그 한 줄 때문에 전체를 의심받는다.

## 제출 전 체크리스트

1. ~~프로드 `.env`의 `ALLOW_SIGNUP` 확인~~ → **2026-07-31 완료.** 위 절 참고.
2. ~~쓰레기 계정 2개 삭제~~ → **2026-07-31 완료.** 본문 숫자도 4로 갱신됨.
3. ~~폐지된 뉴스레터 잔존 행 4개 삭제~~ → **2026-07-31 완료** (4행 삭제, 0건 확인).
4. ~~백엔드 재빌드~~ → **2026-07-31 완료·검증됨.** 아래 참고.
5. 근거 표를 다시 훑는다 (코드가 또 바뀌었을 수 있다)
6. **콘솔에서 제출** — 이제 이것만 남았다.

### ✅ 4번: 배포 전엔 사유서가 거짓이었다 (해결됨)

뉴스레터 폐지는 커밋만 되고 프로덕션에는 안 들어가 있었다. 재빌드 **전** 실측:

```
POST /api/subscribers  (오리진 시크릿 포함)  →  200 {"message":"확인 메일을 보냈어..."}
```

사유서 본문의 *"We removed our newsletter subscription feature entirely on 2026-07-31,
including the endpoint that accepted addresses"*가 그 상태에서는 거짓이었다. 그리고
**AWS가 직접 부딪혀 확인할 수 있는 종류의 거짓**이다.

재빌드 **후** 같은 검사 (이미지 빌드 `2026-07-31T06:57Z` · healthy · alembic `c1d2e3f4a5b6` head):

```
POST /api/subscribers          → 405
POST /api/subscribers/confirm  → 405
POST /api/subscribers/unsubscribe → 405
GET  /api/subscribers/me       → 405
GET  /api/status               → 200  {"stats":{"posts":21,"subscribers":2}}
```

404가 아니라 405인 이유: 관리자용 `GET /subscribers`·`DELETE /subscribers/{id}`가 같은
경로에 남아 있어 경로는 매치되고 메서드가 없다. 회귀 테스트가 상태코드를 못박지 않고
'성공하지 않는다'로 쓰인 이유가 이것이다(`test_retired_routes_never_succeed`).

`subscribers: 2`도 확인 지점이다 — 폐지된 테이블은 0건이므로, 2가 나온다는 건
**계정 구독 인원을 세는 새 쿼리가 돌고 있다**는 뜻이다(옛 코드면 0이 나왔을 것이다).

본문의 숫자는 전부 프로덕션 실측값이라 손댈 곳 없다.

## 거부되면 (두 번째 거부 대비)

**아무것도 안 깨진다.** 거부 = 지금 상태 그대로이고, 지금 상태는 이미 다뤄져 있다
(`ses_verify_recipients.sh`로 계정 주소를 검증하면 메일이 닿는다). **신청에 아무것도
걸지 않았다** — 다리를 먼저 놓고 신청하는 순서였던 이유가 이것이다.

잃는 것은 하나뿐이다: **초대할 때마다 그 사람이 AWS 확인 메일을 눌러야 하는 마찰.**
초대제 블로그에 사람이 몇 안 되면 견딜 만한 비용이다.

### 거부 사유별 대응

| 사유 | 대응 |
|---|---|
| "use case가 불분명" | 이번 사유서가 이미 그걸 겨냥했다. 답변에 빠진 구체값(계정 수·트리거)을 보태 재답변 |
| **"검증된 ID로 충분해 보인다"** | **가장 그럴듯한 거부 사유다.** 7명짜리 초대제 블로그면 AWS가 이렇게 볼 만하다. 반박은 초대 마찰 하나뿐이고 약하다 → **받아들이고 ID 검증으로 간다** |
| "바운스 처리 정보 부족" | suppression list(BOUNCE·COMPLAINT) + 미인증 24시간 자동 삭제를 더 구체적으로 |
| 계정 이력·활동량 | 할 게 없다. 시간이 지난 뒤 재시도 |

같은 내용을 그대로 다시 내지 말 것 — 반복 제출은 자동 거부된다. **거부 사유를 읽고
그 지점만** 답한다.

### 그래도 임의 주소 발송이 필요해지면

1. **Web Push로 새 글 알림을 옮긴다** ([[webpush-next-task]] / `docs`에 없으면 다음 작업 메모 참고).
   그러면 남는 메일은 비번 재설정 + 계정 인증뿐이고 **둘 다 초대한 사람에게만** 간다 →
   검증 ID로 영구히 충분해진다. **이게 SES 판돈 자체를 줄이는 가장 좋은 수다.**
2. 다른 발송 제공자(Resend·Brevo·Mailgun 무료 티어)로 갈아탄다.
   **갈아타기가 싼 이유**: 이 앱의 메일은 `app/services/email.py`의 `send_email()` **한 함수**를
   통과한다. 거기만 바꾸면 된다. 다만 어느 제공자든 자체 심사가 있고 시크릿이 하나 는다.

## 승인된 뒤 할 일

- `scripts/watch.sh`의 `SES_SANDBOX_EXPECTED=true` → `false`.
  **안 바꾸면 감시가 거꾸로 본다** — 샌드박스를 정상으로 알고 있어서, 프로덕션이 된 뒤에
  다시 샌드박스로 떨어져도(집행 조치 등) 아무 말도 안 한다.
- 검증 ID는 그대로 둬도 무해하다(프로덕션에서는 수신 제한이 없어 의미만 사라진다).

---

## 부록: 2026-07-22 옛 사유서 (참고용 — 제출 금지)

첫 제출 사유서가 **245자 2문장**이었다("Personal tech blog. Transactional emails only:
email verification on signup and password reset for registered users. Low volume.
We handle bounces and complaints, no marketing or bulk email."). AWS는 수신자 확보 방식·
바운스 처리·발송량을 **구체적으로** 안 적으면 반려한다. 그래서 07-22에 2,575자로 다시 썼는데,
그 판이 위에서 말한 이유로 사실이 아니게 됐다. 형식(무엇을 얼마나 구체적으로 쓰는가)은
여전히 참고할 만하다.

```
Personal technical blog with a single author, at https://d2j66m9udyg9yq.cloudfront.net. We send transactional email only. No marketing, no bulk mail, no purchased, rented or imported lists. Every address is entered by its own owner on our site.

Messages we send and what triggers each:

1. Signup verification. Sent only when a visitor submits our registration form with their own address. The account cannot log in until the link is clicked, and any account still unverified after 24 hours is deleted automatically by a background job (UNVERIFIED_TTL_HOURS = 24). We therefore never keep, reuse or re-mail an address that did not confirm.

2. Password reset link. Sent only on explicit request from the login page, single use and time limited.

3. Newsletter confirmation and new-post notification. Double opt-in: submitting the form stores the address with confirmed = false and sends exactly one confirmation link. Nothing further is ever sent unless the recipient clicks it. Unsubscribe is available without logging in (POST /api/subscribers/unsubscribe) and as a one-click toggle in the account portal.

Volume: this is a hobby blog with 5 registered users and 4 confirmed newsletter subscribers. Steady state is under 50 messages per month. A realistic peak, if a post circulates widely, is a few hundred per month. We are not asking for a large quota, only for removal of the sandbox restriction.

Why we need production access: in the sandbox we can only deliver to three verified addresses. A real visitor can complete our registration form and receive a success response, but the verification message is never delivered, so they can never activate the account and it is deleted 24 hours later. The signup and password reset features are effectively unusable for anyone other than the site owner.

Abuse prevention already in place: signup is rate limited to 5 requests per hour per IP, password reset email to 5 per hour per IP, and login to 10 per minute per IP. AWS WAF sits in front of the API with the AWS managed IP reputation list, core rule set, and known bad inputs rule groups in blocking mode.

Bounce and complaint handling: the account level suppression list is enabled for both BOUNCE and COMPLAINT, so SES suppresses addresses that hard bounce or complain and we never retry them. Because every recipient confirms their own address before receiving anything beyond the single confirmation message, our bounce exposure is limited to typos in self entered addresses, and those accounts are removed automatically by the 24 hour cleanup described above.
```
