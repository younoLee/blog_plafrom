#!/usr/bin/env bash
# 복원 훈련: S3 백업을 별도 DB(restore_test)에 복원해 운영 DB와 대조하고 지운다.
#
# 왜 필요한가 — "백업이 있다"와 "복원된다"는 다른 말이다. 2026-07-20에 '매일 백업'이
# 한 번도 안 돌던 걸 발견했는데, 그건 산출물이 0건이라 눈에 띈 경우였다. 산출물이
# 쌓이고 있어도 복원이 안 되면 결과는 같다. 그래서 개수까지 맞춰본다.
#
# 왜 워크스테이션에서 도는가 (EC2가 아니라) —
#   EC2 인스턴스 프로파일은 이 버킷에 **s3:PutObject만** 갖고 있다(terraform/db-backup.tf).
#   일부러 그렇게 좁혔다: 웹서버가 탈취돼도 과거 백업 전체(비밀번호 해시 포함)를
#   읽어갈 수 없어야 한다. 그 대가로 EC2에서 `aws s3 cp`로 내려받으면 403이 난다
#   (2026-07-22 훈련에서 실제로 만났다). 복원은 운영자가 자기 자격증명으로 내려받아
#   서버로 올리는 흐름이 맞다 — 이 스크립트가 그 순서다.
#
# 운영 DB는 읽기만 한다. 쓰기는 전부 restore_test 안에서만 일어나고 끝나면 지운다.
#
# 사용:
#   scripts/restore_drill.sh              # 최신 백업으로
#   scripts/restore_drill.sh blog-2026-07-22-0230.sql.gz
#
# 선행조건: EC2가 running (aws ec2 start-instances 후). 오리진 주차는 안 풀어도 된다 —
# 훈련에 공개 사이트는 필요 없다.

set -euo pipefail

INSTANCE_ID=i-06da19f44d1f38eff
BUCKET=blog-db-backups-181568979775
SSH_KEY=~/.ssh/blog-key.pem
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }

state=$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].State.Name' --output text)
if [[ "$state" != "running" ]]; then
  echo "EC2가 '$state' 상태입니다. 먼저 켜세요:"
  echo "  aws ec2 start-instances --instance-ids $INSTANCE_ID"
  exit 1
fi
DNS=$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].PublicDnsName' --output text)

KEY=${1:-$(aws s3 ls "s3://$BUCKET/" | sort | tail -1 | awk '{print $4}')}

# ── 1. 내려받기 (운영자 자격증명) ────────────────────────────────────────────
say "1/3 백업 내려받기 — $KEY"
T0=$(date +%s%3N)
aws s3 cp "s3://$BUCKET/$KEY" "$STAGE/restore.sql.gz" --only-show-errors
gzip -t "$STAGE/restore.sql.gz"
echo "  gzip 무결성 OK ($(stat -c%s "$STAGE/restore.sql.gz") bytes)"

# ── 2. 서버로 올리기 ────────────────────────────────────────────────────────
say "2/3 EC2로 전송"
scp -q -o StrictHostKeyChecking=no -i "$SSH_KEY" \
  "$STAGE/restore.sql.gz" "ec2-user@$DNS:/tmp/restore.sql.gz"
T1=$(date +%s%3N)
echo "  내려받기+전송 $(( T1 - T0 ))ms"

# ── 3. 복원·대조·정리 (서버에서) ────────────────────────────────────────────
# 원격 스크립트를 stdin(`ssh 'bash -s' <<EOF`)으로 넘기면 안 된다 — 스크립트 안의
# 첫 `docker compose exec -T`가 stdin을 열어 **남은 스크립트를 삼켜버리고**, bash는
# EOF를 만나 조용히 종료코드 0으로 끝난다(2026-07-22에 겪음: 출력이 통째로 사라졌다).
# 파일로 올려서 실행하면 stdin이 비어 있어 이 충돌이 없다.
say "3/3 복원 → 대조 → 정리"
cat > "$STAGE/remote.sh" <<'REMOTE'
set -euo pipefail
cd /home/ec2-user/blog
DC="sudo docker compose -f docker-compose.prod.yml"
src() { $DC exec -T db psql -U postgres -d postgres      -tAc "$1"; }
dst() { $DC exec -T db psql -U postgres -d restore_test  -tAc "$1"; }
FAIL=0

$DC exec -T db psql -U postgres -d postgres -q -c "drop database if exists restore_test;" 2>/dev/null
$DC exec -T db psql -U postgres -d postgres -q -c "create database restore_test;"

T0=$(date +%s%3N)
gunzip -c /tmp/restore.sql.gz | $DC exec -T db psql -U postgres -d restore_test -q -v ON_ERROR_STOP=1 >/tmp/restore.log 2>&1
T1=$(date +%s%3N)
echo "  복원 $(( T1 - T0 ))ms"

echo "  --- 개수 대조 (운영 = 복원본) ---"
for t in users posts author_subscriptions comments notifications; do
  a=$(src "select count(*) from $t"); b=$(dst "select count(*) from $t")
  if [ "$a" = "$b" ]; then printf "  OK   %-22s %s\n" "$t" "$a"
  else printf "  FAIL %-22s 운영 %s / 복원 %s\n" "$t" "$a" "$b"; FAIL=1; fi
done
a=$(src "select count(*) from information_schema.tables where table_schema='public'")
b=$(dst "select count(*) from information_schema.tables where table_schema='public'")
[ "$a" = "$b" ] && printf "  OK   %-22s %s\n" "테이블 수" "$a" \
                || { printf "  FAIL 테이블 수 운영 %s / 복원 %s\n" "$a" "$b"; FAIL=1; }

# 시퀀스: 행만 복원되고 시퀀스가 안 따라오면 '읽기는 되는데 다음 INSERT가 충돌'하는
# 조용한 실패가 된다. 개수만 세면 절대 안 걸린다.
echo "  --- 시퀀스 ---"
for t in users posts comments; do
  last=$(dst "select last_value from pg_sequences where schemaname='public' and sequencename='${t}_id_seq'")
  maxid=$(dst "select coalesce(max(id),0) from $t")
  if [ -n "$last" ] && [ "$last" -ge "$maxid" ]; then printf "  OK   %-10s seq=%-6s >= max(id)=%s\n" "$t" "$last" "$maxid"
  else printf "  FAIL %-10s seq=%s < max(id)=%s → 다음 INSERT 충돌\n" "$t" "${last:-없음}" "$maxid"; FAIL=1; fi
done

# '행이 있다'가 아니라 '쓸 수 있다'까지 본다. RETURNING은 값 다음 줄에 커맨드 태그가
# 붙어 나오므로 head -1로 잘라야 한다(2026-07-22에 여기서 DELETE가 깨졌다).
echo "  --- 쓰기 가능 여부 ---"
newid=$(dst "insert into users (email, hashed_password, role, token_version, email_verified) values ('drill@test.local','x','user',0,false) returning id" | head -1)
dst "delete from users where id=$newid" >/dev/null
echo "  OK   INSERT/DELETE 성공 (새 id=$newid)"
ext=$(dst "select count(*) from pg_extension where extname='pg_trgm'")
[ "$ext" = "1" ] && echo "  OK   pg_trgm 확장 존재 (검색이 동작)" \
                 || { echo "  FAIL pg_trgm 없음 → 검색 깨짐"; FAIL=1; }

$DC exec -T db psql -U postgres -d postgres -q -c "drop database restore_test;"
rm -f /tmp/restore.sql.gz
echo "  정리 완료 — 남은 DB: $(src "select string_agg(datname,', ') from pg_database where datistemplate=false")"

[ $FAIL -eq 0 ] && echo "  == 전부 통과 ==" || { echo "  == 불일치 있음 =="; exit 1; }
REMOTE

scp -q -o StrictHostKeyChecking=no -i "$SSH_KEY" \
  "$STAGE/remote.sh" "ec2-user@$DNS:/tmp/restore_drill_remote.sh"
ssh -o StrictHostKeyChecking=no -i "$SSH_KEY" "ec2-user@$DNS" \
  'bash /tmp/restore_drill_remote.sh; rc=$?; rm -f /tmp/restore_drill_remote.sh; exit $rc'
