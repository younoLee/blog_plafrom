# 블로그 플랫폼

[![CI](https://github.com/younoLee/blog_plafrom/actions/workflows/ci.yml/badge.svg)](https://github.com/younoLee/blog_plafrom/actions/workflows/ci.yml)

글쓰기·구독·결제·AI 초안까지 갖춘 풀스택 블로그 플랫폼. 개인 학습 프로젝트로 시작해
**FastAPI + PostgreSQL + React**로 만들고, **AWS(EC2·CloudFront·S3)에 Terraform으로
코드화된 인프라**로 배포했다.

🔗 **라이브:** https://d2j66m9udyg9yq.cloudfront.net

> 💤 **서버는 평소 꺼져 있습니다.** 개인 프로젝트라 안 쓸 땐 EC2를 정지해 비용을 아끼는데,
> 그러면 글 목록이 안 뜹니다. 화면이 8초 안에 "절전 중"이라고 알려주니 고장은 아닙니다 —
> 오리진을 fail-closed로 주차해두는 것까지 의도된 운영 방식입니다.
> **글 내용은 서버 없이도 읽을 수 있습니다** — 웹에서도 그렇습니다:
> [개발일지 아카이브](https://d2j66m9udyg9yq.cloudfront.net/devlog.html) ·
> [RSS](https://d2j66m9udyg9yq.cloudfront.net/rss.xml) ·
> 저장소에서는 [`content/devlog/`](./content/devlog) (개발일지 42편).
> 이 셋은 S3에서 정적으로 나가므로 EC2가 꺼져 있어도 열립니다.

> 이 프로젝트는 기능뿐 아니라 **왜 그렇게 만들었는지**를 개발일지로 남긴다 —
> 비용 구조 분석, RDS→EC2 이전, 보안 하드닝 결정 등. → [`PROGRESS.md`](./PROGRESS.md)

---

## 주요 기능

- **글**: 작성/수정/삭제, 마크다운 + 이미지 업로드, 공개범위(전체/구독자/비공개), 연재(시리즈), 태그, 검색(pg_trgm)
- **계정**: JWT 인증, 이메일 인증, 비밀번호 재설정, 역할(pending/writer/admin/banned), 세션 무효화
- **가입**: 열린 가입은 닫혀 있고 **관리자 발급 1회용 초대 링크**로만 들어온다. 토큰은 해시로만 저장(원문은 발급 응답 1회), 소각은 조건부 UPDATE로 원자적. 초대는 주소를 관리자가 고르므로 확인 메일 단계가 없다 — 그래서 **SES 샌드박스에서도 가입이 성립한다**
- **구독**: 글쓴이별 구독 **신청 → 글쓴이 승인** → 구독자 공개 글 열람. 승인 후 글쓴이별 알림 opt-in(이메일 SES + 인앱 알림)
- **댓글**: 로그인/익명, 공개범위 연동
- **AI 초안**: 메모 → 정돈된 글 구조 생성. Claude(서버 키, 티어 게이팅) + BYOK 5종(Anthropic/OpenAI/Gemini/Cohere/OpenAI호환). 시간당·일일·월간 캡, BYOK 키는 암호화 저장 + base_url SSRF 검증
- **Pro 구독**: 토스페이먼츠 결제(승인검증 → 상위 AI 모델 해금)
- **알림**: 인앱 + **Web Push**(VAPID). 홈화면에 설치하면 iOS에서도 뜬다. 메일은 발신 도메인이 없어 스팸함으로 가므로 실제로 닿는 건 푸시 쪽
- **상태 페이지**: 백엔드/DB/메일 실시간 점검 + 일별 업타임 집계
- **관리자**: 사용자 승인/차단, 인프라 대시보드

## 기술 스택

| 영역 | 사용 기술 |
|---|---|
| **백엔드** | FastAPI, PostgreSQL, SQLAlchemy 2.0, Alembic, JWT(PyJWT), slowapi(레이트리밋), boto3(S3), Anthropic/OpenAI/Gemini SDK |
| **프론트엔드** | React 19, TypeScript, Vite, React Router, Tailwind CSS v4, react-markdown |
| **인프라** | AWS EC2(Docker), CloudFront + S3, SES, Terraform(IaC), GitHub Actions(CI/CD) |
| **테스트** | pytest + 커버리지 70% 게이트, vitest, ruff 보안 규칙(SQLi 등) |  <!-- 개수는 박지 않는다: 2026-08-11에 244로 낡아 있었고 실제는 290+였다 -->

## 아키텍처

```mermaid
flowchart LR
    U[브라우저] -->|HTTPS| CF[CloudFront]
    CF -->|"/ · /blog · /status"| S3[(S3<br/>정적 프론트엔드)]
    CF -->|"/api/*"| EC2[EC2<br/>FastAPI 컨테이너]
    CF -->|"/uploads/*"| S3
    EC2 --> PG[(PostgreSQL<br/>컨테이너 · EBS)]
    EC2 -. 정지 직전 pg_dump .-> BK[(S3<br/>DB 백업)]
```

- 프론트엔드는 S3 정적 호스팅, `/api/*`는 CloudFront가 EC2로 라우팅 → **전부 같은 HTTPS 도메인**(CORS·혼합콘텐츠 없음)
- DB는 RDS가 아니라 **EC2 안 Postgres 컨테이너**(비용 최적화). 백업은 `pg_dump` → S3인데 **일일 cron이 아니라 '서버를 끌 때'** 돈다 — 이 서버는 필요할 때만 켜므로 cron 시각엔 늘 꺼져 있었고 2026-07-20까지 한 번도 실행되지 않았다. RPO는 '하루'가 아니라 **'마지막 정지 시점'**이다. 복구 절차는 [`RECOVERY.md`](./RECOVERY.md), 상세 배경은 [`PROGRESS.md`](./PROGRESS.md)
- AWS 리소스 대부분을 `terraform/`에 코드화(import 방식으로 라이브 인프라 1:1 반영).
  밖에 남은 것은 바로 아래에 목록으로 둔다.

### terraform 밖에 있는 것 (2026-09-04 조회)

**개수는 적지 않는다.** 예전에 "콘솔 생성 마지막 리소스"라고 못 박았다가 WAF가 빠져 있었고,
그때 배운 것이 개수를 적어두면 그 자리를 다시 안 본다는 것이었는데 같은 실수를 또 했다
(`PROGRESS.md:1412`). 그래서 숫자 대신 목록과 확인 날짜, 다시 세는 명령을 둔다.

| 코드 밖 | 확인한 값 |
|---|---|
| tfstate 버킷 | `blog-tfstate-181568979775` (자기 자신을 담는 곳) |
| SSM 파라미터 | `/blog/prod/env` · `/blog/prod/ssh-key` (둘 다 SecureString). 열쇠 쪽은 2026-09-04에 처음 넣었다 — 그전까지 개인키 사본은 이 PC 하나뿐이었다 |
| IAM 유저 | `IAM_cli`, `ses-smtp-user.20260625-184915`, `youno` |
| EC2 키페어 | `blog-key.pem`. `ec2.tf:28`이 이름으로 참조만 하고 리소스로는 안 갖는다 |
| SES 검증 신원 | 개인 메일 주소들이라 여기 안 적는다. `aws ses list-identities`로 본다 |
| AWS Budgets | `My Monthly Cost Budget`($10/월) · `My Zero-Spend Budget`($1/월) |
| EBS 스냅샷 | **0건**(이 운영의 정상 상태). 2026-08-27 게임데이의 break-glass 사본은 09-02에 지웠고, 이제 `scripts/watch.sh` 5-B가 하나라도 남으면 실패한다 |

즉 `terraform plan`이 조용해도 이것들의 콘솔 변경은 안 잡힌다. 아래를 돌려 결과가 위 표와
다르면 표를 고치고 제목의 날짜를 갱신한다.

```bash
aws s3api list-buckets --query 'Buckets[].Name'
aws ssm describe-parameters --query 'Parameters[].Name'
aws iam list-users --query 'Users[].UserName'
aws ec2 describe-key-pairs --query 'KeyPairs[].KeyName'
aws ses list-identities
aws budgets describe-budgets --account-id 181568979775 --query 'Budgets[].BudgetName'
aws ec2 describe-snapshots --owner-ids self --query 'Snapshots[].SnapshotId'
```

코드 안에 있으면서도 드리프트가 안 잡히는 자리가 하나 더 있다. `ec2.tf:29`가 서브넷을
`subnet-04bf4b4e44fe4defe`로 박아 쓴다. `network.tf:20`에 `data.aws_subnets.default`가
있는데도 그렇고, 그 서브넷이 사라지면 재건 1단계가 첫 삽에서 죽는다.
자산이 어디 사는지는 [`RECOVERY.md`](./RECOVERY.md)의 0장이 함께 본다.

## 로컬에서 실행하기

전체 스택(DB·메일·백엔드·프론트)을 Docker로 한 번에 띄운다.

```bash
docker compose up -d --build
```

| 서비스 | 주소 |
|---|---|
| 프론트엔드 | http://localhost:5173 |
| 백엔드 API 문서 | http://localhost:8000/docs |
| Mailpit(메일 확인) | http://localhost:8025 |

**첫 사용:** 회원가입 화면은 **닫혀 있다.** `allow_signup`의 기본값이 `False`라
(`backend/app/core/config.py:103`) `POST /api/auth/register`가 403을 준다. 이 블로그는
2026-08-07부터 초대제이고, 그 기본값은 로컬에도 그대로 적용된다.

첫 계정은 스크립트로 만든다:

```bash
docker compose exec backend python scripts/create_user.py you@example.com --role admin
# 비밀번호를 생략하면 안전한 랜덤 값을 만들어 출력한다. --password 로 직접 줄 수도 있다.
```

이 경로가 유일하게 열려 있다 — 화면의 회원가입을 따라가면 403에서 막힌다.
스크립트는 가입 라우터를 안 거치므로 `email_verified=True`로 바로 로그인된다(인증메일 불필요).

만든 뒤 로그인하면 된다. 메일이 필요한 흐름(가입 인증, 비밀번호 재설정, 새 글 알림)은
로컬에서 실제로 발송되지 않고 Mailpit(:8025)이 전부 잡아준다. 구독 확인 메일은 없다.
이메일 확인 단계는 2026-07-31 뉴스레터 폐지 때 코드에서 사라졌고(`backend/app/services/email.py`의 폐지 주석),
지금 구독은 신청을 글쓴이가 승인하는 흐름이다.

글쓰기 권한(writer)은 관리자 승인이 필요하다 — 위처럼 `--role admin`으로 만든 계정이면 바로 쓸 수 있다.

## 테스트

```bash
# 백엔드 (실제 Postgres 필요 — 위 docker compose로 이미 떠 있음)
cd backend
pip install -r requirements.txt -r requirements-dev.txt
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/blog_test \
SECRET_KEY=test-secret-key-0123456789abcdef pytest

# 프론트엔드
cd frontend
npm ci && npm test
```

CI(GitHub Actions)가 push·PR마다 백엔드 테스트(+커버리지 70% 게이트)와 프론트
유닛테스트·빌드를 자동 실행한다.

## 프로젝트 구조

```
backend/       FastAPI 앱 (routers/ models/ schemas/ services/ core/) + alembic 마이그레이션 + tests/
frontend/      React 앱 (pages/ components/ api/ auth/)
terraform/     AWS 인프라 코드 (EC2·CloudFront·S3·IAM·백업)
.github/        워크플로: ci.yml(검사) · deploy.yml(프론트 배포) · build-backend.yml(백엔드 이미지) · watch.yml(예약 감시)
PROGRESS.md     개발일지 — 결정과 그 이유의 기록
```

## 라이선스

[MIT](./LICENSE)
