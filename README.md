# 블로그 플랫폼

[![CI](https://github.com/younoLee/blog_plafrom/actions/workflows/ci.yml/badge.svg)](https://github.com/younoLee/blog_plafrom/actions/workflows/ci.yml)

글쓰기·구독·결제·AI 초안까지 갖춘 풀스택 블로그 플랫폼. 개인 학습 프로젝트로 시작해
**FastAPI + PostgreSQL + React**로 만들고, **AWS(EC2·CloudFront·S3)에 Terraform으로
코드화된 인프라**로 배포했다.

🔗 **라이브:** https://d2j66m9udyg9yq.cloudfront.net

> 💤 **서버는 평소 꺼져 있습니다.** 개인 프로젝트라 안 쓸 땐 EC2를 정지해 비용을 아끼는데,
> 그러면 글 목록이 안 뜹니다. 화면이 8초 안에 "절전 중"이라고 알려주니 고장은 아닙니다 —
> 오리진을 fail-closed로 주차해두는 것까지 의도된 운영 방식입니다.
> **글 내용은 서버 없이도 읽을 수 있습니다** → [`content/devlog/`](./content/devlog) (개발일지 16편)

> 이 프로젝트는 기능뿐 아니라 **왜 그렇게 만들었는지**를 개발일지로 남긴다 —
> 비용 구조 분석, RDS→EC2 이전, 보안 하드닝 결정 등. → [`PROGRESS.md`](./PROGRESS.md)

---

## 주요 기능

- **글**: 작성/수정/삭제, 마크다운 + 이미지 업로드, 공개범위(전체/구독자/비공개), 연재(시리즈), 태그, 검색(pg_trgm)
- **계정**: JWT 인증, 이메일 인증, 비밀번호 재설정, 역할(pending/writer/admin/banned), 세션 무효화
- **구독**: 글쓴이별 구독 **신청 → 글쓴이 승인** → 구독자 공개 글 열람. 승인 후 글쓴이별 알림 opt-in(이메일 SES + 인앱 알림)
- **댓글**: 로그인/익명, 공개범위 연동
- **AI 초안**: 메모 → 정돈된 글 구조 생성. Claude(서버 키, 티어 게이팅) + BYOK 5종(Anthropic/OpenAI/Gemini/Cohere/OpenAI호환). 시간당·일일·월간 캡, BYOK 키는 암호화 저장 + base_url SSRF 검증
- **Pro 구독**: 토스페이먼츠 결제(승인검증 → 상위 AI 모델 해금)
- **상태 페이지**: 백엔드/DB/메일 실시간 점검 + 일별 업타임 집계
- **관리자**: 사용자 승인/차단, 인프라 대시보드

## 기술 스택

| 영역 | 사용 기술 |
|---|---|
| **백엔드** | FastAPI, PostgreSQL, SQLAlchemy 2.0, Alembic, JWT(PyJWT), slowapi(레이트리밋), boto3(S3), Anthropic/OpenAI/Gemini SDK |
| **프론트엔드** | React 19, TypeScript, Vite, React Router, Tailwind CSS v4, react-markdown |
| **인프라** | AWS EC2(Docker), CloudFront + S3, SES, Terraform(IaC), GitHub Actions(CI/CD) |
| **테스트** | pytest(114) + 커버리지 70% 게이트, vitest(18), ruff 보안 규칙(SQLi 등) |

## 아키텍처

```mermaid
flowchart LR
    U[브라우저] -->|HTTPS| CF[CloudFront]
    CF -->|"/ · /blog · /status"| S3[(S3<br/>정적 프론트엔드)]
    CF -->|"/api/* · /uploads/*"| EC2[EC2<br/>FastAPI 컨테이너]
    EC2 --> PG[(PostgreSQL<br/>컨테이너 · EBS)]
    EC2 -. 일일 pg_dump .-> BK[(S3<br/>DB 백업)]
```

- 프론트엔드는 S3 정적 호스팅, `/api/*`는 CloudFront가 EC2로 라우팅 → **전부 같은 HTTPS 도메인**(CORS·혼합콘텐츠 없음)
- DB는 RDS가 아니라 **EC2 안 Postgres 컨테이너**(비용 최적화) + 일일 S3 백업 → 상세 배경은 [`PROGRESS.md`](./PROGRESS.md)
- 모든 AWS 리소스는 `terraform/`에 코드화(import 방식으로 라이브 인프라 1:1 반영)

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

**첫 사용:** 회원가입 → **Mailpit(:8025)에서 인증 메일 확인** → 링크로 이메일 인증 → 로그인.
(로컬은 실제 메일을 안 보내고 Mailpit이 전부 잡아준다.)

글쓰기 권한(writer)은 관리자 승인이 필요하다. 로컬에서 첫 계정을 admin으로 만들려면
DB에서 `role`을 `admin`으로 바꾸면 된다.

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
.github/        CI(ci.yml) + 프론트 배포(deploy.yml)
PROGRESS.md     개발일지 — 결정과 그 이유의 기록
```

## 라이선스

[MIT](./LICENSE)
