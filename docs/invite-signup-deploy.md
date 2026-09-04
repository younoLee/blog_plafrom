# 배포 런북 — 초대제 가입 · Web Push (2026-08-07)

> **서버를 켜서 배포하는 절차 전반**에 쓴다. 초대제 배포에서 출발했지만
> 4-B(오리진 주차 해제)와 8(정지·백업)은 어떤 배포에나 해당한다.
>
> 대상 커밋: `f898890` 초대제 · `3dbe132` Web Push
> 명령은 **사용자가 실행한다(규칙7)**. 결과는 같이 읽는다.
>
> 공통 변수: EC2 = Name 태그 `blog-backend` (ID는 안 적는다 — 재건하면 바뀐다.
> 스크립트는 `scripts/lib/ec2.sh`로 스스로 찾는다) · 키 `~/.ssh/blog-key.pem` · 버킷 `blogplafromops`
> · 배포 `E1438IL9CSVBS4` · 프론트 `https://d2j66m9udyg9yq.cloudfront.net`
> · 새 마이그레이션 head `e5f6a7b8c9d0`

---

## 왜 순서가 강제되는가

이 커밋은 백엔드와 프론트를 **둘 다** 건드린다. 프론트가 먼저 나가면 아직 없는
API(`POST /api/auth/invite`)를 호출한다 — 2026-07-11에 실제로 겪은 사고고,
`.github/workflows/deploy.yml`의 '백엔드 동시 변경 게이트'가 그때 넣은 장치다.

~~그래서 `main`에 머지하면 **`Deploy Frontend`가 자동으로 돌다가 일부러 실패한다.**~~
**2026-08-11 정정** — 그 게이트는 그 push의 diff만 봐서, **다음 push는 백엔드가 여전히
미배포인데도 통과했다**(실제로 08-11에 그렇게 나갔다). 게이트를 고치는 대신
**푸시 자동 배포 자체를 없앴다.** 이제 `main`에 머지해도 프론트는 **안 나간다** —
백엔드를 먼저 올린 뒤 `workflow_dispatch`로 사람이 직접 돌린다(아래 6번).

---

## 0. 사전 확인 — 이미 끝냈다 (2026-08-07 실측)

| 확인 | 결과 |
|---|---|
| 라이브 번들의 토스 키 | `test_ck_D5GePWvyJnrK0W0k6q8gLzN97Eoq` → 리포 Variables 미설정. **로컬 빌드로 대체해도 결제가 테스트 모드로 조용히 되돌아가지 않는다** |
| 현재 라이브 번들 | `index-DkEB2fQ4.js` · 626,524 B (2026-08-04 기록과 바이트 일치) |
| 새 번들(워크플로와 같은 env로 빌드) | `index-DRcZWkAE.js` · 636,028 B · `index-BBzEbtlm.css` · 70,762 B |
| EC2 상태 | `stopped` |
| 검증용 고유 문자열 | `가입하고 시작하기` — 미니파이된 번들에 남아 있는 것까지 확인함(grep 1건) |

---

## 1. main에 머지

```bash
git checkout main
git merge --ff-only feat/invite-signup
git push origin main
```

→ ~~Actions에서 `Deploy Frontend`가 **빨간불**로 뜬다.~~
**2026-08-11 정정** — 이제 push에서는 `Deploy Frontend`가 **아예 트리거되지 않는다**
(자동 배포 폐지, `workflow_dispatch` 전용). 빨간불도 초록불도 없다 — 이 줄을 믿고
빨간불을 기다리면 여기서 멈춘다. 위 22~25줄이 폐지를 정정하면서 이 줄만 안 쓸렸다.
`CI`는 초록이어야 한다 — 빨갛다면 여기서 멈춘다.

## 2. 서버 켜기

### 2-A. 먼저 SSH 대역을 지금 IP로 (2026-09-04 추가)

**이 단계가 빠지면 인스턴스는 running인데 SSH가 안 붙는다.** 집 공인 IP가 고정이
아니라서 `ssh_cidr`이 시간이 지나면 어긋난다 — 09-02와 09-04 사이에 실제로 바뀌었다
(값은 여기 안 적는다. 아래 `checkip`으로 그때그때 읽는다). 09-04에 여기서 막혔고, 그때 이 문서에도
`RECOVERY.md`에도 이 단계가 없었다. 3절 배포도 4절 확인도 전부 SSH를 쓰므로
여기서 막히면 그 뒤가 통째로 멈춘다(`scripts/env_escrow.sh`도 마찬가지다 —
서버 `.env`를 SSH로 먼저 읽는다).

```bash
curl -s https://checkip.amazonaws.com          # 지금 내 공인 IP
```

나온 값이 `terraform/terraform.tfvars`의 `ssh_cidr`과 다르면 고치고 적용한다.
(tfvars는 gitignore다 — 공개 저장소에 거주지 IP를 안 박는 의도된 설계.
 근거는 `terraform/ec2.tf`의 ingress 주석)

```bash
sed -i 's#^ssh_cidr.*#ssh_cidr      = "<위에서 나온 IP>/32"#' terraform/terraform.tfvars
terraform -chdir=terraform apply -auto-approve -target=aws_security_group.ec2
```

> ⚠️ plan 에서 ingress 블록이 **통째로 다시 그려진다.** 22번 대역만 바뀌고
> 8000번(CloudFront 프리픽스 `pl-22a6434b`)은 그대로여야 한다 — 포트별로 확인할 것.
> 대상 `aws_security_group.ec2`는 실물 이름이 `launch-wizard-1`이라 콘솔에서 만든
> 비관리 자원처럼 보이지만 **terraform이 관리한다.** 드리프트가 아니다.

### 2-B. 켜기

```bash
# ID를 박지 않는다 — 재건하면 바뀐다(DR 결함 F5). 태그로 찾는다.
IID=$(aws ec2 describe-instances --filters "Name=tag:Name,Values=blog-backend" \
  "Name=instance-state-name,Values=pending,running,stopping,stopped" \
  --query 'Reservations[0].Instances[0].InstanceId' --output text)
echo "$IID"   # 비었거나 None이면 태그부터 확인할 것

aws ec2 start-instances --instance-ids "$IID"
aws ec2 wait instance-running --instance-ids "$IID"

# **'running'과 '들어갈 수 있다'는 다르다.** wait 가 끝나도 sshd 는 몇 초 더 걸리고,
# 2-A 를 빠뜨렸다면 여기서 비로소 드러난다. 실제로 붙는 것까지 확인하고 다음으로 간다.
DNS=$(aws ec2 describe-instances --instance-ids "$IID" \
  --query 'Reservations[0].Instances[0].PublicDnsName' --output text)
for i in $(seq 1 30); do
  ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 -o BatchMode=yes \
    -i ~/.ssh/blog-key.pem "ec2-user@$DNS" true 2>/dev/null && { echo "SSH OK"; break; }
  sleep 5
done
```

> 30회(약 150초) 안에 `SSH OK`가 안 나오면 거의 항상 2-A 를 빠뜨린 것이다.
> `curl -s https://checkip.amazonaws.com` 과 보안그룹의 22번 대역을 나란히 놓고 본다.

## 3. 백엔드 배포

```bash
scripts/deploy_backend.sh
```

스크립트가 코드를 묶어 EC2에 풀고 `.env` 지문을 앞뒤로 대조한 뒤(시크릿 보존 확인),
**재빌드 명령을 출력하고 멈춘다.** 그 명령을 직접 실행한다:

```bash
ssh -i ~/.ssh/blog-key.pem ec2-user@<DNS> \
  'cd ~/blog && sudo docker compose -f docker-compose.prod.yml up -d --build'
```

> ⚠️ 스크립트가 `PAYMENTS_REQUIRE_LIVE=true` 경고를 출력한다. 이번 변경과 무관한
> 기존 설정이고, 08-04 배포에서 이미 반영됐다면 달라지는 것은 없다.

## 4. 마이그레이션 확인

**마이그레이션은 따로 실행하지 않는다** — 프로드 compose의 command가
`alembic upgrade head && uvicorn …`이라 컨테이너 기동 시 자동 적용된다.

> ⚠️ **2026-08-10 정정 — '기동하면 붙는다'가 아니다.** `b8c9d0e1f2a3`이 몇 번을 켜도
> 안 붙었는데, 원인은 **그 마이그레이션 파일이 없는 이미지**였다(서버의 alembic은
> 그 리비전의 존재조차 몰랐다). 정확히는 **그 파일이 들어간 재빌드 뒤의 기동**에서
> 붙는다: `deploy_backend.sh`(코드 전송) → `up -d --build` → 그때 적용.

확인만 한다:

```bash
# healthy가 될 때까지 기다린다 (눈으로 보지 말고)
ssh -i ~/.ssh/blog-key.pem ec2-user@<DNS> 'for i in $(seq 1 40); do
    s=$(sudo docker inspect -f "{{.State.Health.Status}}" blog-backend-1 2>/dev/null); echo "  $s";
    [ "$s" = healthy ] && exit 0; [ "$s" = unhealthy ] && exit 1; sleep 5; done; exit 1'

# head가 e5f6a7b8c9d0 이어야 한다
ssh -i ~/.ssh/blog-key.pem ec2-user@<DNS> \
  'cd ~/blog && sudo docker compose -f docker-compose.prod.yml exec -T backend alembic current'
```

## 4-B. 오리진 주차 해제 — **빼먹으면 배포한 게 안 보인다**

서버를 끌 때 CloudFront의 `api-backend` 오리진은 EC2가 아니라 **S3를 가리키게
주차**된다(README의 "fail-closed로 주차"). EC2를 켜는 것만으로는 안 풀린다.
2026-08-07 배포에서 이 단계가 이 문서에 없어서, 백엔드가 `healthy`인데도
`/api/*`가 전부 504였다 — 증상만 보면 배포 실패로 보이지만 배포는 멀쩡했다.

```bash
# 1) 먼저 plan으로 '무엇이 바뀌는지' 확인한다. apply는 그 시점의 전체 플랜을
#    적용하므로, ec2.tf에 인스턴스 교체가 섞여 있으면 루트 볼륨과 함께 DB가 날아간다
#    (pgdata가 그 위에 있다). stop_server.sh가 같은 이유로 plan을 먼저 뽑는다.
terraform -chdir=terraform plan -out=/tmp/unpark.tfplan \
  -var="backend_origin_dns=$(aws ec2 describe-instances \
    --filters "Name=tag:Name,Values=blog-backend" "Name=instance-state-name,Values=running" \
    --query 'Reservations[0].Instances[0].PublicDnsName' --output text)"

# 2) 'Plan: 0 to add, 1 to change, 0 to destroy' 이고 바뀌는 게
#    aws_cloudfront_distribution.main 뿐인지 눈으로 확인한 뒤에만 적용한다.
#    ⚠️ -chdir을 빼면 저장소 루트에서 돌아 프로바이더 락을 못 찾는다.
terraform -chdir=terraform apply "/tmp/unpark.tfplan"

# 3) 전파 확인 (CloudFront 반영에 수십 초)
curl -s -o /dev/null -w '%{http_code}\n' https://d2j66m9udyg9yq.cloudfront.net/api/health
```

기대: `200`. 계속 504면 오리진이 아직 S3다:
```bash
aws cloudfront get-distribution-config --id E1438IL9CSVBS4 \
  --query 'DistributionConfig.Origins.Items[?Id==`api-backend`].DomainName' --output text
```

> 되돌리기는 `scripts/stop_server.sh`가 알아서 한다(1단계가 주차다). 배포 후
> 서버를 끄면 다시 주차되므로, **다음에 켤 때 이 단계를 또 해야 한다.**

## 5. 열린 가입이 여전히 닫혀 있는지 — **가장 중요한 확인**

초대제를 만들면서 열린 가입이 같이 열리면 07-28에 닫은 것이 조용히 되돌아간 것이고,
그건 SES 하드바운스 누적으로 이어진다. `ALLOW_SIGNUP`은 `.env.example`에 없고
코드 기본값이 `False`라 **프로드 `.env`에 그 키가 없어야 정상**이다.

```bash
# 키가 아예 없어야 한다(출력 없음 = 정상). 있으면 false인지 본다.
ssh -i ~/.ssh/blog-key.pem ec2-user@<DNS> 'sudo grep -i allow_signup /home/ec2-user/blog/.env'

# 실물로 확인 — 403이어야 한다
curl -s -X POST https://d2j66m9udyg9yq.cloudfront.net/api/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"walkin-check@example.com","password":"password123"}' -w '\n%{http_code}\n'
```

기대: `403` + `가입은 초대제로 운영돼. 초대 링크가 있으면 그 링크로 가입하면 돼.`

## 6. 프론트 배포 — **경로 A: Actions에서 직접 실행** (2026-08-07 확정)

저장소 → Actions → `Deploy Frontend` → **`Run workflow`** (브랜치 `main`).

- 이 환경엔 GitHub 자격증명이 없어 **대신 눌러줄 수 없다.** 사람이 눌러야 한다.
- **2026-08-11부터 이 경로가 유일한 경로다.** 푸시 자동 배포를 없애서 `Run workflow`를
  안 누르면 프론트는 영원히 안 나간다 — 개발일지를 올릴 때도 마찬가지다
  (정적 아카이브·RSS·sitemap이 이때 갱신된다).
- ~~옛 실패 실행의 `Re-run`은 안 된다 / 게이트는 workflow_dispatch에선 건너뛴다~~ —
  게이트가 사라졌으니 둘 다 무의미하다.

A로 가면 S3 업로드·무효화를 워크플로가 한다 — `--exclude "uploads/*"`가 워크플로에
박혀 있으므로 손으로 `aws s3 sync`를 칠 일이 없고, `--delete`가 업로드 이미지를
지울 위험을 사람 손에서 아예 뗀다. **A를 고른 실질적 이득이 이것이다.**

<details>
<summary>경로 B — Actions를 못 쓸 때만 (손으로 재현)</summary>

빌드는 이미 끝나 있다(`frontend/dist`).

```bash
cd frontend
# ⚠️ --delete가 사용자 업로드 이미지를 지울 수 있다. 프론트와 uploads/가 같은 버킷이다.
#    --exclude "uploads/*" 가 유일한 방어선 → 반드시 dryrun으로 delete 목록을 눈으로 볼 것.
aws s3 sync dist/ s3://blogplafromops --delete --exclude "uploads/*" --dryrun

# 위 출력에 uploads/ 가 하나도 없으면 실행
aws s3 sync dist/ s3://blogplafromops --delete --exclude "uploads/*"
aws cloudfront create-invalidation --distribution-id E1438IL9CSVBS4 --paths "/*"
```

경로 B로 가면 워크플로는 실패로 남는다. Actions만 보면 "프론트가 안 나갔다"로
읽히니, 배포 여부는 워크플로가 아니라 **라이브 번들**로 판단한다.
</details>

## 7. 스모크 — 실제로 한 명 들여본다

"설정했다"와 "동작한다"는 다르다(원칙 4). 초대를 진짜로 하나 발급해서 끝까지 돌린다.

```bash
# 7-1. 새 번들이 나갔나 (고유 문자열)
curl -s https://d2j66m9udyg9yq.cloudfront.net/ | grep -o '/index-[A-Za-z0-9_-]*\.js'
curl -s https://d2j66m9udyg9yq.cloudfront.net/index-DRcZWkAE.js | grep -c '가입하고 시작하기'
# 기대: 파일명이 index-DRcZWkAE.js, grep 결과 1 이상
```

> **경로 A를 골라서 생긴 공짜 검증 하나.** 위 파일명은 내가 로컬에서
> *워크플로와 같은 env*로 빌드해 나온 해시다. Actions가 만든 것이 같은
> `index-DRcZWkAE.js`면 두 빌드가 같은 물건이라는 뜻이고, 그건 곧
> **`vars.TOSS_CLIENT_KEY`가 여전히 미설정**이라는 확인이기도 하다
> (설정돼 있었다면 키 문자열이 바뀌어 해시가 달라진다).
>
> 해시가 다르면 배포가 잘못된 게 아니라 **전제가 바뀐 것**이다. 멈추고 확인한다:
> ```bash
> curl -s https://d2j66m9udyg9yq.cloudfront.net/<나온파일명> | grep -o '\(live\|test\)_ck_[A-Za-z0-9]*'
> ```
> `live_ck_`가 나오면 실결제 키가 들어간 것이고, 그건 이 배포와 무관한 별개 사건이다.
> (2026-08-04에도 로컬 재현과 워크플로 산출물이 바이트 단위로 같았다 — 등가성의 근거.)

7-2. 브라우저에서 관리자로 로그인 → `/admin` → **초대** 섹션에서 자기 주소로 발급
→ 링크 복사(**이 화면을 닫으면 다시 못 본다**).

7-3. 시크릿 창에서 그 링크를 연다. 확인할 것:
- 초대받은 주소가 **읽기 전용**으로 뜬다
- 비밀번호만 정하면 **확인 메일 없이** 바로 로그인된 상태가 된다
- 같은 링크를 다시 열면 "쓸 수 없는 초대 링크야"

7-4. 토큰 없이 `/register`를 열면 기존 "현재 초대제로 운영 중" 안내가 그대로여야 한다.

7-5. 관리자 목록에 **발급 · 가입 · 날짜**가 찍혔는지 본다(감사 기록).

7-6. 스모크로 만든 계정은 지운다 — `/admin` 가입자 관리에서 삭제.

## 8. 마무리

```bash
scripts/stop_server.sh   # 정지 직전 pg_dump → S3 (RPO = 마지막 정지 시점)
```

정지 전에 백업이 실제로 올라갔는지 스크립트 출력으로 확인한다.

---

## 롤백

**핵심: 마이그레이션을 되돌릴 필요가 없다.** 이번 변경은 `invites` **새 테이블 추가**뿐이고
기존 테이블은 건드리지 않았다. 옛 백엔드는 그 테이블의 존재를 모르므로 그냥 무시한다.
즉 **코드만 되돌리면 되고, DB는 그대로 둬도 안전하다.**

**`git checkout 50a61bc -- backend`을 쓰지 말 것.** 경로 체크아웃은 그 커밋에 있던
파일만 되돌리고 **새로 생긴 파일은 그대로 남긴다**(`app/models/invite.py`,
`app/schemas/invite.py`, 마이그레이션). 반쪽만 되돌아간 트리가 나간다.
되돌리기는 커밋 단위로 한다:

```bash
git revert --no-edit f898890      # 새 파일까지 함께 사라진다
git push origin main

# 백엔드
scripts/deploy_backend.sh          # 그리고 출력된 재빌드 명령 실행

# 프론트: 새 번들이 --delete로 지워졌으니 옛 번들을 다시 만들어 올린다
cd frontend
VITE_API_BASE=https://d2j66m9udyg9yq.cloudfront.net/api VITE_TOSS_CLIENT_KEY= npm ci && npm run build
aws s3 sync dist/ s3://blogplafromops --delete --exclude "uploads/*" --dryrun   # 먼저 dryrun
aws s3 sync dist/ s3://blogplafromops --delete --exclude "uploads/*"
aws cloudfront create-invalidation --distribution-id E1438IL9CSVBS4 --paths "/*"
```

> revert 후에도 `invites` 테이블은 DB에 남는다. 위에 적은 대로 그래도 안전하다 —
> 되돌린 백엔드는 그 테이블을 아예 모른다. 다시 배포할 때 마이그레이션이
> 이미 적용돼 있어 그냥 통과한다.

되돌린 뒤 라이브 번들이 `index-DkEB2fQ4.js`(626,524 B)로 돌아왔는지 확인한다.

**정말로 테이블까지 지워야 한다면** (초대 기록이 사라진다 — 누구를 들였는지 답할 수 없게 된다):

```bash
ssh -i ~/.ssh/blog-key.pem ec2-user@<DNS> \
  'cd ~/blog && sudo docker compose -f docker-compose.prod.yml exec -T backend alembic downgrade -1'
```

---

## 배포 후 남는 것

- **`watch.sh`는 안 바뀐다.** `SES_SANDBOX_EXPECTED=true`는 그대로 둔다 —
  초대제 가입은 샌드박스를 벗어나려는 게 아니라 **샌드박스 안에서 성립시키는** 것이다.
  (경위: `docs/ses-production-access.md`)
- **초대받은 사람이 알림 메일을 받으려면** 그 주소를 따로 SES에 등록해야 한다:
  `scripts/ses_verify_recipients.sh <주소>` → 상대가 AWS 확인 메일의 링크를 눌러야 완료.
  가입 자체는 이것 없이도 된다(그게 이 기능의 요점).
- **초대 링크는 메일로 보내지 않는다.** 발급 화면에서 복사해 직접 건넨다.
  받는 쪽이 예고 없는 AWS 메일을 피싱으로 의심할 일이 없고, 샌드박스와도 무관해진다.
- ~~남은 백로그: `users(lower(email))` 유니크 인덱스~~ → **2026-08-09 완료**
  (`uq_users_email_lower`, 마이그레이션 `b8c9d0e1f2a3`).
  미룬 이유가 "기존 데이터에 중복이 있으면 실패"였는데, 정지 직전 백업
  (`keep/latest.sql.gz`)의 users 3행에 대소문자 무시 중복이 **0건**임을 확인하고 올렸다.
  서버를 켤 필요가 없었다 — **백업이 곧 프로드 스키마·데이터의 사본**이라는 걸
  이때 처음 그 용도로 썼다.
  ⚠️ 이 마이그레이션은 **다음 컨테이너 기동 때 자동 적용된다**(프로드 compose의
  command가 `alembic upgrade head`). 중복이 있으면 기동이 실패하므로, 사전 점검을
  마이그레이션 안에 넣어 **어느 주소가 문제인지** 말하고 멈추게 했다.

---

## Web Push를 함께 배포할 때 (커밋 `3dbe132`)

푸시는 **VAPID 키가 없으면 통째로 꺼진다**(엔드포인트 503, 발송 무동작). 즉 키를
안 넣어도 배포는 안전하고, 넣는 순간 켜진다. 로컬 키를 프로드에 재사용하지 않는다.

```bash
# 1) 프로드용 키쌍 생성 (서버에서, 배포 후)
ssh -i ~/.ssh/blog-key.pem ec2-user@<DNS> \
  'cd ~/blog && sudo docker compose -f docker-compose.prod.yml exec -T backend \
     python scripts/gen_vapid_keys.py'

# 2) 출력된 3줄을 서버 .env에 추가 → 컨테이너 재시작
#    (VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY / VAPID_SUBJECT)

# 3) 짝이 맞는지 확인 — 어긋나면 구독은 되는데 발송만 조용히 실패한다
ssh -i ~/.ssh/blog-key.pem ec2-user@<DNS> \
  'cd ~/blog && sudo docker compose -f docker-compose.prod.yml exec -T backend \
     python scripts/gen_vapid_keys.py --check'

# 4) 공개키가 나오는지
curl -s https://d2j66m9udyg9yq.cloudfront.net/api/push/key
```

> **키를 한 번 정하면 바꾸지 않는다.** 공개키는 브라우저의 구독 정보에 박혀 있어서,
> 갈면 기존 구독이 전부 무효가 되고 발송이 조용히 실패한다. 갈아야 한다면
> `push_subscriptions`를 비우고 사용자에게 다시 켜달라고 해야 한다.
>
> compose 수정은 **필요 없다.** 프로드 백엔드는 `env_file: - .env`라 `.env`에 적힌
> 값이 그대로 환경변수가 된다(로컬 `docker-compose.yml`은 변수를 하나씩 나열하는
> 방식이라 거기엔 줄을 추가해야 했다 — 두 파일의 방식이 다르다).
