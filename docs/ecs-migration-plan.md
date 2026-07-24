# ECS 마이그레이션 계획 (초안)

> ROADMAP "방학의 본체". 목표는 "컨테이너를 오케스트레이션으로 옮겨 운영해봤다"를
> **증거와 함께** 갖는 것. 완성이 아니라 **증명**이 목적이다 — 세우고, 굴려보고,
> 스크린샷·일지로 남기고, 크레딧을 지키기 위해 정리한다.
>
> _작성: 2026-07-24 · 상태: **결정 확정, 착수 대기**_
>
> **확정(2026-07-24):** D1=**Fargate** · D2=**RDS db.t4g.micro Single-AZ** · D3=**세우고→증명하고→정리**(1~2개월, 크레딧 ~$60~70).

---

## 0. 지금 구조 (베이스라인)

| 층 | 현재 | 비용 모델 |
|---|---|---|
| 프론트 | S3 `blogplafromops` + CloudFront `E1438IL9CSVBS4` (OAC·무료 WAF·CSP/reqsize 함수) | 항상 켜짐, 사실상 $0 |
| 백엔드 | **단일 EC2 t2.micro** (`i-06da19f44d1f38eff`)에서 docker compose (FastAPI + Postgres 컨테이너) | **필요할 때만 켜고 끔 → idle $0** |
| DB | 같은 EC2 호스트의 **Postgres 컨테이너**(pgdata=EBS). pg_dump→S3 백업(정지 절차) | EBS 스토리지만 |
| 네트워킹 | 기존 VPC `vpc-0326229237c590a90`, 퍼블릭 서브넷 1개, EIP 없음(퍼블릭 DNS 매번 바뀜) | — |
| 오리진 경로 | CloudFront `/api/*` → EC2 퍼블릭 DNS(HTTP :8000). 끄면 S3 도메인으로 **주차 = fail closed** | — |
| 배포 | 프론트=GitHub Actions OIDC 자동. 백엔드=`deploy_backend.sh`(tar→scp→`up --build`) 수동 | — |
| 시크릿 | EC2 `.env` + **SSM SecureString 사본** 이미 있음 | — |
| IaC | terraform, 원격 state(S3). CI(`ci.yml`)=pytest+lint 게이트 | — |

**ECS가 깨뜨리는 두 가지 (이 계획의 전제):**
1. **비용 모델.** ALB는 월 ~$16 **고정**이라 "안 쓸 때 끈다"가 안 통한다. → 그래서 이건
   상시 운영 대체가 아니라 **크레딧(2027-06-24 만료)으로 굴리는 기간 한정 데모**로 간다.
2. **상태(DB).** Fargate 태스크는 휘발성이라 지금처럼 호스트에 Postgres를 얹을 수 없다.
   → DB를 어디에 둘지가 **가장 큰 결정**(아래 D2).

---

## 결정 (2026-07-24 확정 — 근거 보존)

### D1 — 실행 타입: **Fargate** ✅
- **Fargate(추천):** 호스트 없음, 패치·SSH 없음. "서버리스 컨테이너"라는 서사가 제일 강하고
  SAA 범위(태스크/실행 역할 분리)와 잘 맞음. 대신 ALB 필수.
- ECS-on-EC2: 지금 t2.micro에 태스크를 얹는 형태. 더 싸지만 호스트를 계속 관리 → "오케스트레이션으로
  옮겼다" 서사가 약해짐.
- → **Fargate 권장.**

### D2 — 데이터베이스: **RDS db.t4g.micro Single-AZ** ✅ (가장 큰 갈림길이었음)
| 안 | 내용 | 비용 | 서사 | 위험 |
|---|---|---|---|---|
| **(a) RDS** `db.t4g.micro` Single-AZ (추천) | 관리형 Postgres | ~$13/mo(크레딧) | 제일 정석·SAA 직결(Multi-AZ·백업·PITR) | 전에 비용으로 �뺐던 걸 되돌림(단, 크레딧 안) |
| (b) Fargate + EFS | Postgres 태스크에 EFS 볼륨 | EFS 소액 | "$0 관리형 없이" 유지 | 상태 단일태스크=취약, 안티패턴 방어 부담 |
| (c) 하이브리드 | DB는 EC2에 두고 앱만 Fargate | EC2 on/off 유지 | 혼합 | 서사·구성이 어중간 |
- → **(a) RDS 권장.** "오케스트레이션 아키텍처에선 관리형 DB, 단독 EC2 빌드에선 $0 컨테이너화 —
  트레이드오프는 이렇다"는 **대조 자체가 면접 재료**다. 기존 `restore_drill.sh`로 데이터 이관도 매끄럽다.

### D3 — 수명 모델: **세우고 → 증명하고 → 정리** ✅
- ALB+Fargate+RDS ≈ **월 $30~35**. 1~2개월 데모 = 크레딧 ~$60~70. 크레딧 만료 전이라 감당 가능.
- **build → prove → document → tear down** (ROADMAP 권장 그대로). 상시 운영은 EC2 on/off 모델로 유지.
- 정리 후에도 terraform 코드·스크린샷·개발일지는 남는다 = 자산.

---

## 단계 (각 단계 = 세션 하나 크기. 💸=여기서 과금 시작, ⏪=롤백 지점)

### Stage 0 — 설계 확정 & 준비 (무비용)
- D1·D2·D3 확정. ECR 리포지토리 생성(스토리지 소액). 크레딧 잔액 확인.
- terraform에 새 파일 골격(`ecs.tf`·`alb.tf`·`network.tf`·`rds.tf`)만 잡기.

### Stage 1 — 이미지 파이프라인 (런타임 무비용) — **작성 완료 2026-07-24**
- **발견: 이미지 개조 불필요.** 앱 config가 이미 pydantic-settings로 완전 env 주도라
  (`database_url`·`smtp_*`·시크릿 전부 환경변수) Fargate 태스크가 env/Secrets만 주입하면 된다.
  Dockerfile도 ENTRYPOINT가 없어 command 오버라이드가 되므로 **마이그레이션은 Stage 4에서
  같은 이미지에 command만 바꾼 원샷 태스크(`alembic upgrade head`)**로 돌린다(서빙 태스크마다
  돌리면 다중 태스크 레이스 → 분리).
- 작성한 것:
  - `terraform/ecr.tf` — ECR 리포 `blog-backend`. 태그 **IMMUTABLE**(=git SHA, 재현가능),
    push 스캔, 최근 10개만 보관 lifecycle.
  - `terraform/iam-github-oidc.tf` — 기존 OIDC 역할에 `ecr-push-backend` 인라인 정책
    (GetAuthorizationToken은 `*`, 레이어/PutImage는 리포 ARN으로 한정).
  - `.github/workflows/build-backend.yml` — 수동(workflow_dispatch) build→push. **서비스 배포는
    안 함**(규칙7). 태그=git SHA. 검증: `terraform fmt/validate` 통과, YAML 파싱 OK.
- 남은 실행(사용자): `terraform apply`로 ECR 리포+IAM 생성 → Actions에서 build-backend 수동 실행.
  여기까지 과금은 ECR 스토리지 소액뿐.
- ⏪ 아직 라이브 없음. 이미지가 ECR에 쌓이기만 함.

### Stage 2 — 네트워킹 베이스라인 — **작성 완료 2026-07-24** (`network.tf`)
- **조사 결과 대폭 단순화.** 현재는 **기본(default) VPC** `172.31.0.0/16`이고 **4개 AZ 모두
  퍼블릭 서브넷이 이미 존재**(2a/2b/2c/2d, 각 /20) + IGW 붙어 있음.
  → ALB가 요구하는 2개 AZ가 그대로 충족 → **새 서브넷 안 만든다**(계획 초안의 "AZ 추가"는 불필요였음).
- **NAT($32/mo) 회피 결정:** 태스크를 **퍼블릭 서브넷 + 퍼블릭IP**로 두면 IGW로 ECR/로그/S3에
  직접 나가 NAT가 필요 없다. VPC 인터페이스 엔드포인트도 소규모엔 시간요금이 NAT보다 비싸 안 씀.
  노출은 SG로 차단(태스크 인바운드는 ALB만). 트레이드오프는 코드 주석에 명시(면접 재료).
- **3단 SG 작성:** `alb`(80 ← CloudFront prefix list `pl-22a6434b`) → `task`(8000 ← ALB SG만)
  → `rds`(5432 ← Task SG만). 데이터소스로 기본 VPC·서브넷 참조(ALB/RDS 서브넷그룹이 Stage 3~4에서 재사용).
- 검증: `terraform fmt/validate` 통과. 남은 실행(사용자): `terraform apply`(SG 3개 생성, 무비용).

### Stage 3 — RDS — **terraform 작성 완료 2026-07-24** (`rds.tf`) · apply=💸 첫 과금
- RDS Postgres 16 `db.t4g.micro` Single-AZ, `publicly_accessible=false`, SG는 Task에서만.
  gp3 20GB(암호화), 관리형 자동백업 7일(RDS 핵심 이점·SAA 소재).
- **마스터 비번은 `manage_master_user_password=true`** → RDS가 Secrets Manager에 만들어 관리.
  tfvars·state에 비번이 안 남는다. Stage 4 태스크 정의가 그 시크릿 ARN에서 password를 주입.
- `db_name="blog"`. ⚠️ **이관 시 확인:** 현재 프로드 compose는 `POSTGRES_DB=postgres`라
  실제 DB 이름/`DATABASE_URL` 경로를 확인해 dump를 이 `blog`로 적재할지 정한다.
- 데이터 이관: 현재 EC2에서 `pg_dump` → RDS로 restore(**`restore_drill.sh` 도구 재사용**).
  ← 복원 훈련에 쏟은 작업이 여기서 값을 한다(일지 연결점).
- 검증: `terraform fmt/validate` 통과.
- 남은 실행(사용자): `terraform apply`(💸 RDS 생성, ~$13/mo 시작) → 데이터 이관.
- ⏪ RDS destroy(skip_final_snapshot·deletion_protection off라 매끄럽게). 원본은 EC2 EBS + S3 덤프에 그대로.

### Stage 4 — ECS 클러스터 + 태스크 + 서비스 + ALB — **terraform 작성 완료 2026-07-24** (`ecs.tf`·`alb.tf`) · apply=💸 ALB ~$16 + Fargate
- `alb.tf`: ALB(인터넷-facing, SG로 CloudFront만) + 타깃그룹(target_type=**ip**, Fargate라서) +
  **헬스체크 `/api/health`**(matcher 200) + HTTP:80 리스너. 출력 `alb_dns_name`(컷오버용).
- `ecs.tf`:
  - **역할 2분리**: 실행역할(ECR pull·로그·시크릿읽기 관리형+한정) / 태스크역할(S3 `uploads/*` PutObject만 — EC2 역할과 동일 미러링).
  - **시크릿 주입**: DB_PASSWORD는 **RDS 관리 시크릿**의 `password` 키에서, 앱 비밀값(SECRET_KEY·
    ANTHROPIC_API_KEY·LLM_ENCRYPTION_KEY·TOSS_SECRET_KEY)은 새 Secrets Manager `blog-app-secrets`에서.
    **값은 코드/state에 안 넣는다 — 사용자가 채운다**(아래).
  - **DATABASE_URL 조립**: 앱은 통짜 URL 하나만 받는데 관리시크릿은 password만 준다 → 컨테이너
    command에서 python으로 **URL 인코딩**해 조립(비번 특수문자 안전). 더미값 검증 통과
    (`p@ss:w/rd#1` → `p%40ss%3Aw%2Frd%231`). 이미지 변경 없음.
  - 서비스: 퍼블릭 서브넷 + 퍼블릭IP(NAT 회피), task SG로 인바운드 차단, 롤링(min100/max200)=무중단.
  - `var.backend_image_tag`(=git SHA): ECR 태그가 IMMUTABLE이라 latest가 없다 → apply 시 지정.
- 검증: `terraform fmt/validate` 통과 + DATABASE_URL 셸 로직 실측 통과.
- **마이그레이션**(원샷): 같은 태스크 정의에 command만 바꿔 run-task(`overrides`로 `alembic upgrade head`).
- **남은 실행(사용자, 순서):** ① `blog-app-secrets`에 프로드 .env 비밀값 채우기(안 채우면 태스크 시작 실패=설정≠동작)
  ② SMTP 등 비밀 아닌 env를 프로드 .env와 대조 ③ 이미지 push(build-backend) 후 SHA로 apply
  ④ 마이그레이션 run-task ⑤ 서비스 healthy 확인.
- ⏪ 서비스 desired=0. CloudFront는 컷오버 전까지 옛 EC2를 계속 봄.

### Stage 4.5 — 심층검사: 부하·오류 내성 (2026-07-24, apply 전)
"문법 통과 ≠ 동작"이라 apply 전에 실제 코드와 대조해 부하·장애 경로를 팠다.

**고친 것 (실제 결함):**
1. **`pool_pre_ping=True` + `pool_recycle=300`** (`database.py`) — 없던 것. RDS는 유휴/페일오버로
   커넥션을 끊는데, 그러면 죽은 커넥션 재사용 시 첫 쿼리가 500("server closed the connection").
   로컬 Postgres에선 안 겪던 게 RDS로 옮기면 바로 터진다. **가장 중요한 수정.**
2. **ALB `idle_timeout=120`** — 기본 60초. AI 초안이 최대 60초라 경계에서 504로 끊길 위험.
3. **ECS `desired_count=2`(다중 AZ HA) + `health_check_grace_period=60` + 배포 서킷브레이커(rollback)**
   — 단일 태스크는 장애 시 다운. 2개로 AZ 분산. 나쁜 이미지/빠뜨린 시크릿으로 crash-loop 시
   무한재시도 대신 직전 안정본으로 자동 롤백.
4. **오토스케일 2~4, CPU 60% 타깃** — 부하 급증 시 자동 증설(scale-out 1분/ scale-in 5분).
5. **RDS `engine_version` 16→16.14 핀** — 가용버전 실조회 후 고정(drift 방지).

**확인하고 남겨둔 것 (수정 안 함, 근거 있음):**
- **백그라운드 스케줄러 다중 실행** = 저위험. `cleanup`은 멱등(이미 지운 행 삭제=무해),
  `recorder`는 태스크당 분당 1행이라 과다표본이지만 업타임 '비율'은 보존. 영구 다중인스턴스라면
  전용 스케줄러 태스크(EventBridge)로 외부화가 정석 — 데모 범위 밖(면접 소재로 남김).
- **`/api/health`는 DB 미점검** — liveness 전용이라 DB 느려도 플랩 안 함(의도). 대신 DB 다운을
  ALB가 감지 못함(태스크는 healthy로 남아 500을 냄). deep check는 별도 경로가 필요 — 보류.
- **Fargate 256/512 + 단일 uvicorn worker** — 데모엔 충분. 부하시험서 CPU 포화면 512/1024 또는
  워커/태스크 수로 튜닝(오토스케일이 1차 완충).
- **slowapi 인메모리 레이트리밋은 태스크별**(태스크 수만큼 곱해짐). 비용/보안 핵심인 AI 캡은
  DB 기반이라 전역 유지 → 실질 위험 없음.

### Stage 5 — 컷오버 (트래픽 전환)
- CloudFront `/api/*` 오리진을 EC2 퍼블릭 DNS → **ALB DNS**로. 자신 붙을 때까지 EC2를 롤백용으로 유지.
- **오리진 HTTPS는 보류(정정).** CloudFront→ALB를 HTTPS로 하려면 ALB에 오리진 도메인과 맞는
  ACM 인증서가 필요한데, ALB 기본 DNS(`*.elb.amazonaws.com`)엔 공개 ACM을 못 발급한다 →
  **커스텀 도메인이 필요**(ROADMAP에서 비용으로 보류한 그것). 따라서 컷오버 후에도 CloudFront→ALB는
  현재(EC2 http:8000)와 같은 평문 수준이다. "평문 오리진" 항목은 커스텀 도메인 결정과 함께 남는다.
  (더 나은 길: CloudFront **VPC origins**로 내부 ALB를 두면 오리진이 인터넷을 안 타지만, 별도 작업.)
- ⏪ CloudFront 오리진을 EC2로 되돌리면 즉시 원복.

### Stage 6 — 증명 (면접 골드 — 이게 진짜 목적)
- 캡처·로그로 남길 것: **무중단 롤링 배포** / **태스크 강제 종료 → ECS 자동 대체** /
  **오토스케일**(CPU 타깃 트래킹으로 부하 시 스케일아웃) / **ALB 헬스체크가 unhealthy 태스크 축출** /
  CloudWatch 지표·로그.
- 개발일지 작성. "오케스트레이션" 서사가 증거를 얻는 지점.

### Stage 7 — 정리 / 비용 통제
- 크레딧 예산 보고 계속 굴릴지 결정, 아니면 ALB·Fargate·RDS **tear down** 후 CloudFront를 EC2
  on/off로 원복. **terraform 코드·스크린샷·일지는 보존.**

---

## 가로지르는 원칙
- **전부 terraform.** 이 저장소가 반복해 당한 "콘솔 드리프트"를 되풀이하지 않는다(예: `blog-ec2-role`
  CLI 생성이 사고를 냈던 것). 새 리소스는 처음부터 코드로.
- **시크릿은 SSM 경유** 태스크 정의 secrets로. 이미지에 굽지 않는다.
- **SAA 겹침**(병행 학습): VPC·서브넷·AZ / ALB·타깃그룹·헬스체크 / ECS·Fargate /
  IAM 태스크역할 vs 실행역할 / 오토스케일 / RDS. 안 겹치는 시험범위만 따로.

## 열린 질문
- D2에서 RDS로 가면 "왜 전에 뺐던 RDS를 다시?"에 대한 답을 일지에 명시(= 크레딧 데모 vs 상시 $0 운영).
- 컷오버를 blue/green(옛 EC2 유지)으로 며칠 병행할지, 바로 자를지.
- 오토스케일 부하 생성을 뭘로 할지(k6·hey 등) — 증명 Stage에서 필요.
