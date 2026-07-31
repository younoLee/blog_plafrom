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

- SES 콘솔 → Account dashboard → **Request production access**, 또는
- Support Center → 케이스 `178238423300607` → **Reply**

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

## 붙여넣을 본문 (2026-07-31판)

> ⚠️ 아래 `[N]` 두 곳은 **서버를 켜서 실제 숫자로 바꾼 뒤** 제출할 것.
> 지어내면 이 문서 전체의 신뢰가 무너진다.

```
Personal technical blog with a single author, at https://d2j66m9udyg9yq.cloudfront.net. We send transactional email only. No marketing, no bulk mail, no newsletters, and no purchased, rented or imported lists.

Who can receive mail from us, and why that set is closed:

Public registration is disabled. The registration endpoint returns HTTP 403 unless an explicit server setting enables it, and that setting is off by default and off in production. Accounts are created only by the site owner, using a command line script, for people the owner invites. There is no form anywhere on the site that accepts an email address from an anonymous visitor. We removed our newsletter subscription feature entirely on 2026-07-31, including the endpoint that accepted addresses, so no third party can cause us to send mail to any address.

The practical consequence is that every recipient of every message we send is an account holder that the owner personally invited.

Messages we send and what triggers each:

1. Account verification. Sent when the owner creates an invited account, so the recipient can confirm the address and set up access. Any account still unverified after 24 hours is deleted automatically by a background job.

2. Password reset link. Sent only on explicit request from the login page. Single use, expires in one hour, and invalidated as soon as it is used.

3. New post notification. Sent only to account holders who subscribed to a specific author and then explicitly turned notifications on for that author. Both the subscription and the notification toggle are off by default, require the author's approval, and can be turned off at any time from the account portal.

Volume: [N] registered accounts and [N] account holders with new post notifications enabled. Steady state is under 50 messages per month. We are not asking for a large sending quota, only for removal of the sandbox restriction.

Why we need production access: in the sandbox we can only deliver to three verified addresses. When the owner invites someone, that person cannot receive their verification message or reset their password unless we first add their personal address as a verified identity inside our AWS account and ask them to click an Amazon confirmation email. That is an unreasonable thing to ask of an invited reader, and it is the only reason we are applying.

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

1. 서버를 켠다 → `[N]` 두 개를 실제 숫자로 바꾼다
   - 등록 계정 수: `select count(*) from users;`
   - 알림 켠 사람 수: `select count(distinct subscriber_id) from author_subscriptions where approved and notify;`
2. **프로드 `.env`에 `ALLOW_SIGNUP`이 없는지 확인한다.** 배포 설정(compose·스크립트·워크플로)
   어디에도 없는 건 확인했지만, 서버의 `.env`는 꺼져 있어 못 읽었다. 거기 켜져 있으면
   "공개 가입이 없다"는 사유서의 **첫 문단이 통째로 거짓**이 된다.
   `docker compose -f docker-compose.prod.yml exec backend python -c \
    "from app.core.config import settings; print(settings.allow_signup)"` → `False`여야 한다.
3. 위 근거 표를 다시 훑는다 (코드가 또 바뀌었을 수 있다)
4. 콘솔에서 제출 (API 불가)

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
