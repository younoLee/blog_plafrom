# 재해 복구 런북

"백업이 복원된다"와 "서비스가 돌아온다"는 다른 명제다. `scripts/restore_drill.sh`는
앞엣것만 증명한다 — 같은 서버, 이미 떠 있는 Postgres, 곁가지 DB에 복원하는 훈련이라
**서버가 통째로 없어진 상황**은 다루지 않는다. 이 문서가 그 경로다.

> ✅ **시나리오 B를 2026-07-22에 처음부터 끝까지 실제로 밟았다.** 운영은 건드리지 않고
> 임시 인스턴스(`t2.micro`, 전용 보안그룹)를 띄워 맨바닥에서 재건한 뒤 지웠다.
> 실제 운영 백업으로 **글 27건·유저 5명**이 복원되고, `/api/status`·`/api/posts`가 200,
> 복원된 글이 API로 그대로 나오는 것까지 확인했다. `alembic upgrade head`는 no-op이었다.
>
> **그 과정에서 이 문서의 버그를 둘 찾아 고쳤다** — 종이 위에서는 안 보였던 것들이다:
>
> 1. **buildx가 없어서 빌드가 아예 안 됐다.** 맨바닥 AL2023에는 buildx 0.12.1만 있고,
>    최신 compose가 `compose build requires buildx 0.17.0 or later`로 거부한다.
>    → 2단계에 buildx 설치를 추가했다(운영과 같은 v0.35.0).
> 2. **`.dockerignore`를 안 올려서 앱이 죽었고, 시크릿이 이미지에 구워졌다.** 이게 더
>    나쁘다. 3단계 tar에 `.dockerignore`가 빠져 있으면 `COPY . .`가 **`.env`를 이미지
>    안에 굽는다**. 그러면 pydantic이 dotenv의 여분 키(`DB_PASSWORD`·`ADMIN_EMAIL` —
>    `Settings`에 없는 필드다)를 `extra_forbidden`으로 거부해 백엔드가 재시작 루프에
>    빠진다. 운영은 예전 배포 때 올라간 `.dockerignore`가 이미 있어서 멀쩡했고,
>    **새 인스턴스에서만** 터진다. → 3단계 tar에 `.dockerignore`를 넣었다.
>
> 남은 미검증은 없다. 다만 위 두 개처럼 **문서가 맞는지는 밟아봐야만 안다**는 게
> 이번의 교훈이라, 인프라를 크게 바꾸면 다시 한 번 돌려보는 게 좋다.

## 0. 무엇이 어디에 있나

| 자산 | 사는 곳 | 잃으면 | 사본 |
|---|---|---|---|
| DB | EC2 루트 볼륨의 `pgdata` 볼륨 | 글·계정·결제 전부 | S3 `blog-db-backups-181568979775` |
| 업로드 이미지 | S3 `blogplafromops/uploads/` | 글 속 이미지 깨짐 | 같은 백업 버킷 `uploads/` 미러 + 버킷 버저닝 |
| 시크릿(`.env`) | EC2 `~/blog/.env` (600) | **BYOK 키 영구 복구 불가** | ① 이 PC `~/.blog-secrets/prod.env` ② SSM SecureString `/blog/prod/env` — 둘 다 `scripts/env_escrow.sh save`가 함께 갱신 |
| 코드 | 이 저장소 | — | GitHub |
| 인프라 | `terraform/` | — | 저장소 |
| terraform state | S3 `blog-tfstate-181568979775` (**terraform 관리 밖**, 버저닝 켜짐) | 시나리오 B의 1단계부터 못 밟는다 | 버킷 버저닝뿐 |

두 가지를 특히 기억할 것:

- **EC2를 terminate하면 DB도 같이 사라진다.** `ec2.tf`의 `root_block_device`가
  `delete_on_termination = true`이고 `pgdata`는 그 루트 볼륨 위에 있다. stop은
  안전하지만 terminate는 되돌릴 수 없다.
- **RPO는 '하루'가 아니라 '마지막 정지 시점'이다.** 백업은 cron이 아니라
  `scripts/stop_server.sh`가 돌 때만 뜬다(옛 cron은 그 시각에 서버가 꺼져 있어
  한 번도 안 돌았다, 2026-07-20). 서버를 켜둔 채 사고가 나면 켜 있던 동안의
  변경은 백업에 없다.

## 시나리오 A — DB만 깨졌다 (인스턴스는 살아 있음)

실수로 지웠거나 데이터가 망가진 경우. 가장 흔하고 가장 쉽다.

```bash
# 1) 어떤 백업을 쓸지 고르고, 그게 진짜 쓸 수 있는지 먼저 확인한다
aws s3 ls s3://blog-db-backups-181568979775/ | grep blog-
scripts/restore_drill.sh blog-2026-07-22-0230.sql.gz   # 훈련으로 검증(운영 무영향)

# 2) 덤프를 서버에 다시 올린다.
#    ⚠️ 1단계 훈련은 끝나면서 서버의 /tmp/restore.sql.gz를 지운다(뒷정리가 그 설계다).
#    그래서 여기서 다시 올려야 한다 — 안 그러면 아래 gunzip이 "No such file"로 죽는다.
aws s3 cp s3://blog-db-backups-181568979775/blog-2026-07-22-0230.sql.gz /tmp/restore.sql.gz
scp -i ~/.ssh/blog-key.pem /tmp/restore.sql.gz ec2-user@<DNS>:/tmp/restore.sql.gz

# 3) 서버에서 실제 DB에 덮어쓴다 ⚠️ 현재 데이터가 사라진다
#    (백엔드를 먼저 내려야 한다 — 연결이 남아 있으면 drop database가 막힌다)
ssh -i ~/.ssh/blog-key.pem ec2-user@<DNS>
cd /home/ec2-user/blog
sudo docker compose -f docker-compose.prod.yml stop backend
sudo docker compose -f docker-compose.prod.yml exec -T db \
  psql -U postgres -d template1 -c "drop database postgres;" -c "create database postgres;"
gunzip -c /tmp/restore.sql.gz | sudo docker compose -f docker-compose.prod.yml \
  exec -T db psql -U postgres -d postgres -v ON_ERROR_STOP=1
sudo docker compose -f docker-compose.prod.yml start backend
```

훈련을 먼저 돌리는 게 핵심이다. 훈련이 통과한 백업만 운영에 덮어쓴다.

## 시나리오 B — 인스턴스/볼륨을 잃었다

**순서가 중요하다. 백엔드를 먼저 띄우면 안 된다** — `docker-compose.prod.yml`의
backend는 뜰 때 `alembic upgrade head`를 돌려 빈 스키마를 만들어 버린다. 그 위에
덤프를 부으면 `ERROR: relation "ai_hourly_usage" already exists`로 **복원이 중단되고
빈 DB가 남는다**(2026-07-22에 실제로 재현). 사고 한복판에서 이걸 만나면 "복원했는데
글이 하나도 없다"로 보여서 백업을 의심하게 되는데, 백업은 멀쩡하고 순서가 틀린 것이다.
DB만 띄우고 → 복원하고 → 백엔드를 띄운다.

```bash
# 0) terraform.tfvars를 먼저 만든다 — gitignore돼 있어 새 클론에는 없다.
#    없으면 apply가 "No value for required variable"로 **실패한다**(의도적 fail-closed:
#    SSH 허용 대역이 조용히 넓어지는 것보다 낫다).
cat > terraform/terraform.tfvars <<'TFVARS'
ssh_cidr = "<지금 내 공인 IP>/32"   # curl -s https://checkip.amazonaws.com
TFVARS

# 1) 인스턴스 재생성 (terraform이 관리한다)
terraform -chdir=terraform apply

# ⚠️ 새 인스턴스는 ID가 다르다. 옛 ID(i-06da19f44d1f38eff)로 조회하면
#    InvalidInstanceID.NotFound가 난다. 태그로 찾아 쓰고, 그 다음에 스크립트에 박힌
#    ID들을 새 값으로 바꿔야 한다 — 안 바꾸면 정지 절차도 훈련도 옛 인스턴스를 본다.
#      scripts/stop_server.sh, scripts/restore_drill.sh, scripts/env_escrow.sh,
#      terraform/variables.tf 주석
IID=$(aws ec2 describe-instances --filters "Name=tag:Name,Values=blog-backend " \
  "Name=instance-state-name,Values=running" \
  --query 'Reservations[0].Instances[0].InstanceId' --output text)
DNS=$(aws ec2 describe-instances --instance-ids "$IID" \
  --query 'Reservations[0].Instances[0].PublicDnsName' --output text)
echo "새 인스턴스 ID: $IID  ← 위 파일들의 INSTANCE_ID를 이 값으로 교체할 것"

# 2) 부트스트랩 — user_data가 없어서 AMI는 맨바닥이다. 손으로 깔아야 한다.
ssh -i ~/.ssh/blog-key.pem ec2-user@$DNS
sudo dnf install -y docker
sudo systemctl enable --now docker
sudo mkdir -p /usr/local/lib/docker/cli-plugins && \
  sudo curl -sSL -o /usr/local/lib/docker/cli-plugins/docker-compose \
  https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 && \
  sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
# buildx도 깔아야 한다. AMI에 딸려오는 건 0.12.1인데 요즘 compose는 0.17 이상을 요구해
# `compose build requires buildx 0.17.0 or later`로 빌드가 시작조차 안 된다.
# 버전은 운영과 맞춘다(2026-07-22 기준 v0.35.0).
sudo curl -sSL -o /usr/local/lib/docker/cli-plugins/docker-buildx \
  https://github.com/docker/buildx/releases/download/v0.35.0/buildx-v0.35.0.linux-amd64
sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-buildx
mkdir -p ~/blog/uploads

# 3) 코드와 compose 파일 올리기 (평소 배포와 같은 모양)
#    ⚠️ `.dockerignore`를 반드시 같이 넣는다. 이게 빠지면 빌드 컨텍스트의 `.env`가
#    `COPY . .`로 이미지에 구워지고(시크릿 유출), 게다가 pydantic이 dotenv의 여분 키를
#    extra_forbidden으로 거부해 백엔드가 재시작 루프에 빠진다. 운영은 이미 파일이
#    있어서 안 겪지만 새 인스턴스는 반드시 겪는다.
#    로컬에서:
tar czf /tmp/backend.tgz -C backend .dockerignore app alembic alembic.ini requirements.txt Dockerfile
scp -i ~/.ssh/blog-key.pem /tmp/backend.tgz docker-compose.prod.yml ec2-user@$DNS:~/blog/
ssh -i ~/.ssh/blog-key.pem ec2-user@$DNS 'cd ~/blog && tar xzf backend.tgz && rm backend.tgz'

# 4) 시크릿 복원 — 에스크로 사본에서. 이게 없으면 여기서 막힌다.
scp -i ~/.ssh/blog-key.pem ~/.blog-secrets/prod.env ec2-user@$DNS:~/blog/.env
ssh -i ~/.ssh/blog-key.pem ec2-user@$DNS 'chmod 600 ~/blog/.env'

# 이 PC까지 잃었다면 SSM 사본에서(계정이 살아 있는 한 여기 있다):
#   aws ssm get-parameter --name /blog/prod/env --with-decryption \
#     --query Parameter.Value --output text > /tmp/prod.env

# 5) DB만 먼저 띄운다
ssh -i ~/.ssh/blog-key.pem ec2-user@$DNS \
  'cd ~/blog && sudo docker compose -f docker-compose.prod.yml up -d db'

# 6) 백업 내려받아 복원 (운영자 자격증명으로 — EC2엔 읽기 권한이 없다)
aws s3 cp s3://blog-db-backups-181568979775/keep/latest.sql.gz /tmp/restore.sql.gz
scp -i ~/.ssh/blog-key.pem /tmp/restore.sql.gz ec2-user@$DNS:/tmp/
ssh -i ~/.ssh/blog-key.pem ec2-user@$DNS \
  'cd ~/blog && gunzip -c /tmp/restore.sql.gz | sudo docker compose -f docker-compose.prod.yml \
     exec -T db psql -U postgres -d postgres -v ON_ERROR_STOP=1'

# 7) 이제 백엔드 (alembic은 이미 head라 no-op이 된다)
ssh -i ~/.ssh/blog-key.pem ec2-user@$DNS \
  'cd ~/blog && sudo docker compose -f docker-compose.prod.yml up -d --build backend'

# 8) 오리진을 새 주소로 (주차 해제)
terraform -chdir=terraform apply -var="backend_origin_dns=$DNS"

# 9) 확인
curl -s https://d2j66m9udyg9yq.cloudfront.net/api/status
```

이미지는 S3에 있으므로 이 경로에서 따로 할 일이 없다 — 2026-06-26에 EC2 디스크에서
옮긴 덕이다. 다만 `.env`가 없으면 5번 이후가 전부 막힌다는 점이 이 절차의 급소다.

## 시나리오 C — 업로드 이미지를 잃었다

이미지는 프론트와 같은 버킷에 산다. 배포가 `s3 sync --delete`라, `--exclude
"uploads/*"`를 빠뜨린 sync 한 번이면 통째로 지워진다. 두 가지 복구 경로가 있다.

```bash
# (가장 쉬움) 백업 버킷의 미러에서 되돌리기 — 정지 절차가 매번 갱신해 둔다
aws s3 sync s3://blog-db-backups-181568979775/uploads/ s3://blogplafromops/uploads/

# (또는) 버저닝으로 삭제 표식만 걷어내기 — 미러보다 최신까지 복구된다
aws s3api list-object-versions --bucket blogplafromops --prefix uploads/ \
  --query 'DeleteMarkers[?IsLatest].[Key,VersionId]' --output text \
| while read -r key vid; do
    # 지울 게 없으면 --output text가 "None"을 뱉는다. 그대로 넘기면 엉뚱한 호출이 된다.
    [ -n "$key" ] && [ "$key" != "None" ] || continue
    aws s3api delete-object --bucket blogplafromops --key "$key" --version-id "$vid"
  done
```

복구했으면 `scripts/restore_drill.sh`를 돌린다 — 글이 참조하는 이미지가 전부 실제로
있는지 대조하는 단계가 들어 있다.

## 시나리오 D — 시크릿을 잃었다

`.env`가 사라졌고 에스크로 사본도 없을 때. 항목마다 결과가 다르다.

| 잃은 값 | 결과 | 복구 |
|---|---|---|
| `LLM_ENCRYPTION_KEY` | `llm_credentials`의 BYOK 키를 **영원히 못 푼다** | 사본에서 복원(이 PC 또는 SSM). 셋 다 잃었으면 없음 — 해당 행을 지우고 사용자에게 재입력 요청 |
| `SECRET_KEY` | 세션뿐 아니라 **발송 대기 중인 이메일 인증·비번재설정·구독확인 링크까지** 전부 무효 | 새 값 생성. 세션은 재로그인, 링크는 재발송. 미인증 계정은 24h 뒤 자동 삭제되므로 재가입 안내 필요 |
| `DB_PASSWORD` | 컨테이너가 새로 뜨면 초기화됨 | 새 값으로 재설정 |
| `ANTHROPIC_API_KEY` / 토스 키 | 해당 기능 정지 | 각 콘솔에서 재발급 |

`LLM_ENCRYPTION_KEY`만 성격이 다르다 — 나머지는 새로 만들면 되지만 이건 **데이터를
푸는 열쇠**라 잃으면 데이터가 같이 죽는다. 그래서 `scripts/env_escrow.sh save`가
있고, 키를 교체할 때 옛 사본을 지우지 않는다(옛 암호문은 옛 키로만 풀린다).

## 정기 점검

```bash
scripts/restore_drill.sh      # 복원되는지 + 이미지·사본·시크릿까지
scripts/env_escrow.sh check   # .env 사본(PC·SSM)이 서버와 같은지
scripts/watch.sh              # 매시 자동으로도 돌지만 수동 확인도 가능
```

시크릿 사본은 셋이다 — 서버 원본 · 이 PC · SSM SecureString(`/blog/prod/env`,
Standard 티어라 무료). PC만 잃어도, 서버만 잃어도, 둘을 동시에 잃어도 복구된다.
**다만 AWS 계정 자체를 잃으면 이 PC 사본만 남는다** — 그래서 비밀번호 관리자에
한 벌 더 넣는 일은 여전히 사람이 해야 한다(자동화할 수 없다).

훈련의 합격/불합격은 **구조 검사**(테이블 집합·인덱스·제약·시퀀스·alembic 버전·확장·
쓰기 가능·BYOK 복호화)로만 판정한다. 나머지는 표시만 하고 불합격시키지 않는다:

- `DRIFT` — 행 수 차이. 백업 이후 쓰기가 있으면 정상이다.
- `WARN` — 참조 이미지 누락, 사본 부족 등. **백업의 결함이 아니라 데이터/운영 상태**라
  여기서 불합격시키면 옛 글 하나 때문에 훈련이 영구 빨간불이 된다. 영구 빨간불은
  아무도 안 보는 신호와 같아서, 정작 진짜 실패를 놓치게 된다.
