# 재해 복구 런북

"백업이 복원된다"와 "서비스가 돌아온다"는 다른 명제다. `scripts/restore_drill.sh`는
앞엣것만 증명한다 — 같은 서버, 이미 떠 있는 Postgres, 곁가지 DB에 복원하는 훈련이라
정작 **서버가 통째로 없어진 상황**은 한 번도 밟아본 적이 없다. 이 문서가 그 경로다.

> ⚠️ 아래 시나리오 B(인스턴스 유실)는 **실제로 수행해 검증한 적이 없다**. 필요한 재료가
> 다 있는지 확인해 쓴 절차이고, 진짜 사고 때 처음 밟으면 막히는 데가 나올 수 있다.
> 한가할 때 한 번 끝까지 해보는 게 이 문서의 다음 할 일이다.

## 0. 무엇이 어디에 있나

| 자산 | 사는 곳 | 잃으면 | 사본 |
|---|---|---|---|
| DB | EC2 루트 볼륨의 `pgdata` 볼륨 | 글·계정·결제 전부 | S3 `blog-db-backups-181568979775` |
| 업로드 이미지 | S3 `blogplafromops/uploads/` | 글 속 이미지 깨짐 | 같은 백업 버킷 `uploads/` 미러 + 버킷 버저닝 |
| 시크릿(`.env`) | EC2 `~/blog/.env` | **BYOK 키 영구 복구 불가** | `~/.blog-secrets/prod.env` (`scripts/env_escrow.sh`) |
| 코드 | 이 저장소 | — | GitHub |
| 인프라 | `terraform/` | — | 저장소 + `terraform.tfstate` |

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

# 2) 서버에서 실제 DB에 덮어쓴다 ⚠️ 현재 데이터가 사라진다
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
덤프를 부으면 "이미 존재한다"로 충돌한다. DB만 띄우고 → 복원하고 → 백엔드를 띄운다.

```bash
# 1) 인스턴스 재생성 (terraform이 관리한다)
terraform -chdir=terraform apply
DNS=$(aws ec2 describe-instances --instance-ids i-06da19f44d1f38eff \
  --query 'Reservations[0].Instances[0].PublicDnsName' --output text)

# 2) 부트스트랩 — user_data가 없어서 AMI는 맨바닥이다. 손으로 깔아야 한다.
ssh -i ~/.ssh/blog-key.pem ec2-user@$DNS
sudo dnf install -y docker
sudo systemctl enable --now docker
sudo mkdir -p /usr/local/lib/docker/cli-plugins && \
  sudo curl -sSL -o /usr/local/lib/docker/cli-plugins/docker-compose \
  https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 && \
  sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
mkdir -p ~/blog/uploads

# 3) 코드와 compose 파일 올리기 (평소 배포와 같은 모양)
#    로컬에서:
tar czf /tmp/backend.tgz -C backend app alembic alembic.ini requirements.txt Dockerfile
scp -i ~/.ssh/blog-key.pem /tmp/backend.tgz docker-compose.prod.yml ec2-user@$DNS:~/blog/
ssh -i ~/.ssh/blog-key.pem ec2-user@$DNS 'cd ~/blog && tar xzf backend.tgz && rm backend.tgz'

# 4) 시크릿 복원 — 에스크로 사본에서. 이게 없으면 여기서 막힌다.
scp -i ~/.ssh/blog-key.pem ~/.blog-secrets/prod.env ec2-user@$DNS:~/blog/.env

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
    aws s3api delete-object --bucket blogplafromops --key "$key" --version-id "$vid"
  done
```

복구했으면 `scripts/restore_drill.sh`를 돌린다 — 글이 참조하는 이미지가 전부 실제로
있는지 대조하는 단계가 들어 있다.

## 시나리오 D — 시크릿을 잃었다

`.env`가 사라졌고 에스크로 사본도 없을 때. 항목마다 결과가 다르다.

| 잃은 값 | 결과 | 복구 |
|---|---|---|
| `LLM_ENCRYPTION_KEY` | `llm_credentials`의 BYOK 키를 **영원히 못 푼다** | 없음. 해당 행을 지우고 사용자에게 재입력 요청 |
| `SECRET_KEY` | 발급된 모든 세션 토큰 무효 | 새 값 생성. 사용자는 다시 로그인하면 됨 |
| `DB_PASSWORD` | 컨테이너가 새로 뜨면 초기화됨 | 새 값으로 재설정 |
| `ANTHROPIC_API_KEY` / 토스 키 | 해당 기능 정지 | 각 콘솔에서 재발급 |

`LLM_ENCRYPTION_KEY`만 성격이 다르다 — 나머지는 새로 만들면 되지만 이건 **데이터를
푸는 열쇠**라 잃으면 데이터가 같이 죽는다. 그래서 `scripts/env_escrow.sh save`가
있고, 키를 교체할 때 옛 사본을 지우지 않는다(옛 암호문은 옛 키로만 풀린다).

## 정기 점검

```bash
scripts/restore_drill.sh      # 복원되는지 + 이미지·사본·시크릿까지
scripts/env_escrow.sh check   # .env 사본이 서버와 같은지
```

훈련의 합격/불합격은 **구조 검사**(테이블 집합·인덱스·시퀀스·alembic 버전·확장·
쓰기 가능·BYOK 복호화)로만 판정한다. 행 수 차이는 백업 이후 쓰기가 있으면 정상이라
`DRIFT`로 표시만 하고 불합격시키지 않는다.
