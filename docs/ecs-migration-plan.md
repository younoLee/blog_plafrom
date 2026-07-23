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

### Stage 4 — ECS 클러스터 + 태스크 + 서비스 + ALB (💸 ALB ~$16/mo + Fargate 시작)
- 클러스터(Fargate). **태스크 정의**: ECR 이미지, 시크릿은 **SSM**(이미 SecureString 사본 있음)에서.
  **Task 역할**(S3 업로드 — 지금 EC2 역할과 동일 권한) / **실행 역할**(ECR pull·로그) 분리.
- **ALB + 타깃그룹 + 헬스체크 `/api/health`**(이미 존재). ← ROADMAP이 "시간 먹는 구간"으로 콕 집은 곳.
  리스너 구성. 로그 → CloudWatch.
- 서비스 desired 1~2, 롤링 배포.
- ⏪ 서비스 desired=0. CloudFront는 컷오버 전까지 옛 EC2를 계속 봄.

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
