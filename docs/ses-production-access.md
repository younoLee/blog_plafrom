# SES 프로덕션 액세스 — 재신청 사유서

2026-07-22 확인: 첫 신청이 **거부**됐다(`ReviewDetails.Status = DENIED`, CaseId `178238423300607`).
그 사실을 아무도 몰랐고, 그동안 제3자는 가입해도 인증 메일을 받지 못했다
(샌드박스는 검증된 3개 주소로만 발송된다).

**API로는 재제출할 수 없다.** `sesv2 put-account-details`는 심사 이력이 있으면
`ConflictException`을 낸다. AWS Support API는 유료 플랜 전용이라 CLI로도 못 연다.
→ 콘솔에서 사람이 해야 한다.

## 어디서

- SES 콘솔 → Account dashboard → **Request production access**, 또는
- Support Center → 케이스 `178238423300607` → **Reply**

## 왜 거부됐을 것 같은가

첫 제출 사유서가 **245자 2문장**이었다("Personal tech blog. Transactional emails only:
email verification on signup and password reset for registered users. Low volume.
We handle bounces and complaints, no marketing or bulk email."). AWS는 수신자 확보 방식·
바운스 처리·발송량을 **구체적으로** 안 적으면 반려한다. 아래는 실제 구현을 확인해
사실만으로 다시 쓴 것이다(2,575자).

## 붙여넣을 본문

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

## 본문에 쓴 사실의 근거 (전부 코드에서 확인함)

| 주장 | 근거 |
|---|---|
| 미인증 계정 24시간 뒤 자동 삭제 | `backend/app/services/cleanup.py:18` `UNVERIFIED_TTL_HOURS = 24` |
| 뉴스레터 더블 옵트인 | `backend/app/routers/subscribers.py:39` `confirmed=False`로 저장 후 확인 링크 발송 |
| 로그인 없이 구독 해지 가능 | `backend/app/routers/subscribers.py:70` `POST /unsubscribe` |
| 가입 5회/시간, 비번재설정 메일 5회/시간, 로그인 10회/분 | `backend/app/routers/auth.py:36,93,109` |
| WAF 관리형 룰 3종 차단 모드 | Web ACL `CreatedByCloudFront-920ca6f5`, `OverrideAction: None` |
| 바운스·불만 억제 목록 활성 | 계정 수준 suppression list = `BOUNCE`, `COMPLAINT` |
| 유저 5명 / 확인된 구독자 4명 | 운영 DB 실측 |

## 승인된 뒤 할 일

`scripts/watch.sh`(또는 감시 워크플로)가 `ProductionAccessEnabled`를 보고 있으므로,
승인되면 그 검사는 자동으로 초록이 된다. 별도 조치는 없다.
