#!/usr/bin/env bash
# 복원 훈련: S3 백업을 별도 DB(restore_test)에 복원해 운영과 대조하고 지운다.
#
# 왜 필요한가 — "백업이 있다"와 "복원된다"는 다른 말이다. 2026-07-20에 '매일 백업'이
# 한 번도 안 돌던 걸 발견했는데, 그건 산출물이 0건이라 눈에 띈 경우였다. 산출물이
# 쌓이고 있어도 복원이 안 되면 결과는 같다.
#
# 무엇을 보는가 — 검사를 성격에 따라 둘로 나눈다. 섞으면 둘 다 못 믿게 된다.
#
#   ① 구조 검사 (여기서 틀리면 FAIL). 백업 시점과 무관하게 항상 참이어야 하는 것들:
#      테이블 집합 · 인덱스/제약 수 · 시퀀스 · alembic 버전 · 확장 · 쓰기 가능 여부 ·
#      BYOK 복호화. 이건 시간이 지나도 안 흔들리므로 합격/불합격의 척도로 쓸 수 있다.
#
#   ② 데이터 대조 (여기서 어긋나도 FAIL이 아니다). 행 수는 '정지 시점 스냅샷'과
#      '현재 운영'을 비교하는 것이라 백업 이후 쓰기가 있으면 정상인데도 어긋난다.
#      예전 버전은 이걸 FAIL로 처리해서, 훈련이 초록불이려면 아무도 글을 안 써야
#      한다는 이상한 상태였다. 지금은 방향으로 분류하고 '백업에 없는 구간'을 보여준다.
#        복원본 < 운영 = 백업 이후 쓰기(예상됨) / 복원본 > 운영 = 삭제 아니면 이상
#
#   ③ DB 바깥. 덤프가 완벽해도 서비스가 안 돌아오는 경우를 따로 본다:
#      복원된 글이 참조하는 업로드 이미지가 S3에 실제로 있는지, 백업 저장소에
#      '만료되지 않는 사본'이 있는지. DB만 보면 이 둘은 영원히 안 보인다.
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
#   scripts/restore_drill.sh                          # 최신 백업으로
#   scripts/restore_drill.sh blog-2026-07-22-0230.sql.gz
#   scripts/restore_drill.sh keep/latest.sql.gz       # 만료 안 되는 사본으로
#
# 선행조건: EC2가 running (aws ec2 start-instances 후). 오리진 주차는 안 풀어도 된다 —
# 훈련에 공개 사이트는 필요 없다.

set -euo pipefail

INSTANCE_ID=i-06da19f44d1f38eff
BUCKET=blog-db-backups-181568979775
IMAGE_BUCKET=blogplafromops
SSH_KEY=~/.ssh/blog-key.pem
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT

# 참조 이미지를 몇 개까지 실제로 확인할지. 전부 도는 대신 상한을 두되,
# 잘렸으면 반드시 그 사실을 출력한다(조용히 자르면 '다 봤다'로 읽힌다).
IMG_CHECK_MAX=40

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

# 기본값은 '가장 최근 날짜별 덤프'.
# `aws s3 ls | tail -1`로 고르면 안 된다 — 버킷에 keep/·uploads/ 접두사가 생긴 뒤로
# 그 목록엔 "PRE keep/" 같은 줄이 섞여서 엉뚱한 걸 집는다. 접두사로 걸러서 고른다.
KEY=${1:-$(aws s3api list-objects-v2 --bucket "$BUCKET" --prefix "blog-" \
  --query 'sort_by(Contents,&LastModified)[-1].Key' --output text)}
if [ -z "$KEY" ] || [ "$KEY" = "None" ]; then
  echo "백업이 하나도 없습니다: s3://$BUCKET/" >&2
  exit 1
fi

# ── 1. 내려받기 (운영자 자격증명) ────────────────────────────────────────────
say "1/4 백업 내려받기 — $KEY"
T0=$(date +%s%3N)
aws s3 cp "s3://$BUCKET/$KEY" "$STAGE/restore.sql.gz" --only-show-errors
gzip -t "$STAGE/restore.sql.gz"
echo "  gzip 무결성 OK ($(stat -c%s "$STAGE/restore.sql.gz") bytes)"

# gzip이 통과해도 덤프가 잘렸을 수 있다 — pg_dump가 중간에 죽어도 gzip은 받은 데까지
# 정상적으로 마무리하기 때문이다. 완료 표식이 유일한 증거다. 여기서 걸러내면
# 복원에 몇 분 쓰기 전에 끝난다. (`| grep -q`는 EPIPE로 앞 단계를 죽이므로 안 쓴다)
trailer=$(gzip -dc "$STAGE/restore.sql.gz" | tail -5)
case "$trailer" in
  *"PostgreSQL database dump complete"*) echo "  덤프 완료 표식 OK (잘리지 않음)" ;;
  *) echo "  ❌ 덤프 끝에 완료 표식이 없습니다 = 잘린 백업입니다. 중단합니다." >&2; exit 1 ;;
esac

# ── 2. 서버로 올리기 ────────────────────────────────────────────────────────
say "2/4 EC2로 전송"
scp -q -o StrictHostKeyChecking=no -i "$SSH_KEY" \
  "$STAGE/restore.sql.gz" "ec2-user@$DNS:/tmp/restore.sql.gz"
T1=$(date +%s%3N)
echo "  내려받기+전송 $(( T1 - T0 ))ms"

# ── 3. 복원·대조·정리 (서버에서) ────────────────────────────────────────────
# 원격 스크립트를 stdin(`ssh 'bash -s' <<EOF`)으로 넘기면 안 된다 — 스크립트 안의
# 첫 `docker compose exec -T`가 stdin을 열어 **남은 스크립트를 삼켜버리고**, bash는
# EOF를 만나 조용히 종료코드 0으로 끝난다(2026-07-22에 겪음: 출력이 통째로 사라졌다).
# 파일로 올려서 실행하면 stdin이 비어 있어 이 충돌이 없다.
say "3/4 복원 → 대조 → 정리"
cat > "$STAGE/remote.sh" <<'REMOTE'
set -euo pipefail
cd /home/ec2-user/blog
DC="sudo docker compose -f docker-compose.prod.yml"
src() { $DC exec -T db psql -U postgres -d postgres      -tAc "$1"; }
dst() { $DC exec -T db psql -U postgres -d restore_test  -tAc "$1"; }
FAIL=0
DRIFT=0

# 무슨 일이 있어도 restore_test를 남기지 않는다.
# 예전엔 trap이 없어서, 중간에 죽으면 훈련용 DB가 운영 서버에 그대로 남았다
# (2026-07-22에 실제로 발생 — `head -1`의 EPIPE로 스크립트가 중간에 끝났다).
# 복원이 실패했을 때 로그를 보여주는 것도 여기서 한다. 예전엔 로그를 남기기만 하고
# 정작 실패하면 아무것도 안 보여준 채 죽어서, 원인을 알 방법이 없었다.
cleanup() {
  rc=$?
  if [ "$rc" -ne 0 ] && [ -s /tmp/restore.log ]; then
    echo "  --- 복원 로그 끝 30줄 (실패 원인) ---"
    tail -30 /tmp/restore.log
  fi
  $DC exec -T db psql -U postgres -d postgres -q \
    -c "drop database if exists restore_test;" >/dev/null 2>&1 || true
  rm -f /tmp/restore.sql.gz /tmp/restore.log \
        /tmp/drill_tables /tmp/drill_tables.dst /tmp/drill_serials
  exit "$rc"
}
trap cleanup EXIT

$DC exec -T db psql -U postgres -d postgres -q -c "drop database if exists restore_test;" 2>/dev/null
$DC exec -T db psql -U postgres -d postgres -q -c "create database restore_test;"

T0=$(date +%s%3N)
gunzip -c /tmp/restore.sql.gz | $DC exec -T db psql -U postgres -d restore_test -q -v ON_ERROR_STOP=1 >/tmp/restore.log 2>&1
T1=$(date +%s%3N)
echo "  복원 $(( T1 - T0 ))ms"

# ════════════ ① 구조 검사 — 여기서 틀리면 FAIL ════════════

echo "  --- 스키마 버전 ---"
# 이게 다르면 앱이 그 DB 위에서 못 뜬다(alembic upgrade head가 어긋난다).
# 행 수가 전부 맞아도 서비스는 안 돌아오므로, 개수 대조로는 절대 못 잡는 종류다.
va=$(src "select version_num from alembic_version")
vb=$(dst "select version_num from alembic_version")
if [ "$va" = "$vb" ]; then
  printf "  OK   %-22s %s\n" "alembic_version" "$va"
else
  printf "  FAIL %-22s 운영 %s / 복원 %s → 앱이 이 DB 위에서 안 뜬다\n" "alembic_version" "$va" "$vb"
  FAIL=1
fi

echo "  --- 스키마 구조 ---"
# 테이블 '수'만 세면 A가 빠지고 B가 생긴 경우를 통과시킨다 → 이름 집합으로 비교한다.
# comm은 '같은 정렬 기준'을 전제하므로 SQL의 ORDER BY에 맡기지 않고 LC_ALL=C로 다시
# 정렬한다. DB 콜레이션(en_US 등)은 밑줄 같은 구두점을 무시해서 바이트 순서와 다르고,
# 그러면 실제로는 같은 집합인데 comm이 차이가 있다고 말한다.
src "select table_name from information_schema.tables where table_schema='public' and table_type='BASE TABLE'" | LC_ALL=C sort > /tmp/drill_tables
dst "select table_name from information_schema.tables where table_schema='public' and table_type='BASE TABLE'" | LC_ALL=C sort > /tmp/drill_tables.dst
# comm도 같은 로케일로 돌려야 한다 — 파일만 LC_ALL=C로 정렬하고 comm은 호출자 로케일로
# 두면 정렬 기준이 어긋나 차이 목록이 엉뚱하게 나온다.
only_src=$(LC_ALL=C comm -23 /tmp/drill_tables /tmp/drill_tables.dst | tr '\n' ' ')
only_dst=$(LC_ALL=C comm -13 /tmp/drill_tables /tmp/drill_tables.dst | tr '\n' ' ')
rm -f /tmp/drill_tables.dst
if [ -z "$only_src" ] && [ -z "$only_dst" ]; then
  printf "  OK   %-22s %s개 전부 일치\n" "테이블 집합" "$(wc -l < /tmp/drill_tables)"
else
  [ -n "$only_src" ] && printf "  FAIL 복원본에 없는 테이블: %s\n" "$only_src"
  [ -n "$only_dst" ] && printf "  FAIL 복원본에만 있는 테이블: %s\n" "$only_dst"
  FAIL=1
fi

# 인덱스가 빠진 복원본은 '되긴 되는데 느린' 상태라 개수 대조로는 안 걸린다.
# 제약(FK/UNIQUE)이 빠지면 무결성이 조용히 깨진다. 둘 다 구조라 시점과 무관하다.
for what in "인덱스:select count(*) from pg_indexes where schemaname='public'" \
            "제약:select count(*) from information_schema.table_constraints where constraint_schema='public'"; do
  label=${what%%:*}; q=${what#*:}
  a=$(src "$q"); b=$(dst "$q")
  if [ "$a" = "$b" ]; then printf "  OK   %-22s %s\n" "$label 수" "$a"
  else printf "  FAIL %-22s 운영 %s / 복원 %s\n" "$label 수" "$a" "$b"; FAIL=1; fi
done

# 확장도 이름 집합으로 본다. pg_trgm이 없으면 검색이 깨지는데, 예전엔 pg_trgm '하나만'
# 확인해서 다른 확장이 빠지는 건 못 봤다.
ea=$(src "select coalesce(string_agg(extname,',' order by extname),'') from pg_extension")
eb=$(dst "select coalesce(string_agg(extname,',' order by extname),'') from pg_extension")
if [ "$ea" = "$eb" ]; then printf "  OK   %-22s %s\n" "확장" "$ea"
else printf "  FAIL %-22s 운영 [%s] / 복원 [%s]\n" "확장" "$ea" "$eb"; FAIL=1; fi

# 시퀀스: 행만 복원되고 시퀀스가 안 따라오면 '읽기는 되는데 다음 INSERT가 충돌'하는
# 조용한 실패가 된다. 개수만 세면 절대 안 걸린다.
# 예전엔 users/posts/comments 셋만 하드코딩이라, 나머지 8개는 훈련이 영원히 안 봤다.
# 이제 nextval 기본값을 가진 컬럼을 런타임에 전부 찾아 돈다.
echo "  --- 시퀀스 (전수) ---"
dst "select table_name||'|'||column_name from information_schema.columns where table_schema='public' and column_default like 'nextval(%' order by 1" > /tmp/drill_serials
# 파일을 `while read`로 돌리면 안 된다 — 루프 몸통의 `docker compose exec -T`가
# 루프의 stdin(=이 파일)을 삼켜 목록이 잘린다. mapfile은 루프 전에 다 읽는다.
mapfile -t SERIALS < /tmp/drill_serials
seq_ok=0
seq_bad=0
for row in "${SERIALS[@]}"; do
  [ -n "$row" ] || continue
  t=${row%%|*}; c=${row#*|}
  sq=$(dst "select pg_get_serial_sequence('\"$t\"','$c')")
  [ -n "$sq" ] || continue
  last=$(dst "select last_value from $sq")
  maxid=$(dst "select coalesce(max(\"$c\"),0) from \"$t\"")
  if [ -n "$last" ] && [ "$last" -ge "$maxid" ]; then
    seq_ok=$((seq_ok+1))
  else
    printf "  FAIL %-22s seq=%s < max(%s)=%s → 다음 INSERT 충돌\n" "$t" "${last:-없음}" "$c" "$maxid"
    seq_bad=$((seq_bad+1)); FAIL=1
  fi
done
if [ "$seq_ok" -eq "${#SERIALS[@]}" ]; then
  printf "  OK   %-22s %s개 전부 max(id) 이상\n" "시퀀스" "$seq_ok"
elif [ "$seq_bad" -gt 0 ]; then
  printf "  --   %-22s %s/%s개 정상(위 FAIL 참고)\n" "시퀀스" "$seq_ok" "${#SERIALS[@]}"
else
  # 소유 시퀀스를 못 찾아 건너뛴 것뿐이라 FAIL이 아니다. 예전엔 이 경우에도
  # "위 FAIL 참고"라고 찍어서, 위에 FAIL이 없는데 실패한 것처럼 보였다.
  printf "  --   %-22s %s/%s개 확인(나머지는 소유 시퀀스 없음 — 정상)\n" "시퀀스" "$seq_ok" "${#SERIALS[@]}"
fi

# '행이 있다'가 아니라 '쓸 수 있다'까지 본다. RETURNING은 값 다음 줄에 커맨드 태그가
# 붙어 나오므로 첫 줄만 잘라 쓴다(2026-07-22에 여기서 DELETE가 깨졌다).
#
# 자를 때 `| head -1`을 쓰면 안 된다 — head가 첫 줄만 읽고 파이프를 닫으면 psql은 남은
# 태그를 쓰다 EPIPE로 죽고, pipefail이 그걸 실패로 잡아 set -e가 스크립트를 여기서
# 끝낸다. 그러면 아래 DELETE도 drop database도 못 돌아 restore_test가 통째로 남는다.
# psql이 두 줄을 한 번의 write로 내보내면 통과하고 아니면 죽는 버퍼링 타이밍 문제라
# 어떤 날은 되고 어떤 날은 안 된다(2026-07-22 두 번째 훈련에서 실제로 걸렸다).
# 파이프 없이 셸 확장으로 자르면 psql이 끝까지 쓰고 정상 종료한다.
echo "  --- 쓰기 가능 여부 ---"
newid=$(dst "insert into users (email, hashed_password, role, token_version, email_verified) values ('drill@test.local','x','user',0,false) returning id")
newid=${newid%%$'\n'*}
dst "delete from users where id=$newid" >/dev/null
echo "  OK   INSERT/DELETE 성공 (새 id=$newid)"

# BYOK 카나리아 — 복원된 암호문을 '지금 서버가 들고 있는 키'로 실제로 풀어본다.
# 이게 왜 필요한가: LLM_ENCRYPTION_KEY는 .env에만 있고 어떤 백업에도 없다. 키가
# 바뀌거나 사라지면 llm_credentials는 행 수까지 완벽히 복원돼도 **영원히 못 푼다**.
# 행을 세는 검사로는 원리적으로 안 보이는 손실이라 직접 복호화해 보는 수밖에 없다.
# 평문은 출력하지 않는다 — 성공/실패만 본다.
echo "  --- BYOK 복호화 (키와 데이터가 맞는지) ---"
enc=$(dst "select encrypted_key from llm_credentials order by id limit 1")
if [ -z "$enc" ]; then
  echo "  --   저장된 BYOK 자격증명이 없어 생략(검사할 암호문 자체가 없음)"
# 판정 토큰은 서로의 부분문자열이 되면 안 된다. 예전엔 OK/NOKEY/MISMATCH를 썼는데
# **"NOKEY"가 `*OK*`에 매치돼** 키가 아예 없는 경우를 "통과"로 찍었다(2026-07-22 코드검사에서
# 발견). 하필 이 카나리아가 존재하는 유일한 이유가 그 경우다. 겹치지 않는 토큰을 쓴다.
elif res=$($DC exec -T backend python -c '
import os, sys
from cryptography.fernet import Fernet
k = os.environ.get("LLM_ENCRYPTION_KEY", "")
if not k:
    print("RESULT=NO_KEY"); raise SystemExit(0)
try:
    Fernet(k.encode()).decrypt(sys.argv[1].encode())
    print("RESULT=DECRYPTED")
except Exception:
    print("RESULT=BAD_KEY")
' "$enc" 2>&1); then
  case "$res" in
    *RESULT=DECRYPTED*) echo "  OK   복원된 암호문이 현재 키로 풀린다" ;;
    *RESULT=NO_KEY*)    echo "  FAIL 서버에 LLM_ENCRYPTION_KEY가 없다 → BYOK 키 전부 복구 불가"; FAIL=1 ;;
    *RESULT=BAD_KEY*)   echo "  FAIL 현재 키로 복호화 실패 → 키가 바뀌었다. 옛 키를 찾아야 한다"; FAIL=1 ;;
    *)                  echo "  FAIL 카나리아 검사 결과를 해석 못 함: $res"; FAIL=1 ;;
  esac
else
  echo "  FAIL 카나리아 검사를 실행하지 못함(backend 컨테이너 확인): $res"
  FAIL=1
fi

# ════════════ ② 데이터 대조 — 어긋나도 FAIL이 아니다 ════════════
# 백업은 '뜬 시점'의 스냅샷이고 운영은 '지금'이다. 그 사이에 쓰기가 있으면 어긋나는
# 게 정상이다. 그래서 방향으로 나누고, 얼마만큼의 시간이 백업에 안 담겼는지 보여준다.
echo "  --- 행 수 (운영 = 지금 / 복원 = 백업 시점) ---"
mapfile -t TABLES < /tmp/drill_tables
for t in "${TABLES[@]}"; do
  [ -n "$t" ] || continue
  [ "$t" = "alembic_version" ] && continue
  a=$(src "select count(*) from \"$t\"")
  b=$(dst "select count(*) from \"$t\"")
  if [ "$a" = "$b" ]; then
    printf "  OK    %-22s %s\n" "$t" "$a"
    continue
  fi
  # 시각 컬럼이 있으면 '백업에 안 담긴 구간'을 실제 시각으로 보여준다.
  tscol=$(src "select column_name from information_schema.columns where table_schema='public' and table_name='$t' and column_name in ('created_at','checked_at') order by column_name limit 1")
  if [ "$b" -lt "$a" ]; then
    detail=""
    if [ -n "$tscol" ]; then
      cut=$(dst "select coalesce(max($tscol)::text,'') from \"$t\"")
      if [ -n "$cut" ]; then
        first=$(src "select coalesce(min($tscol)::text,'-') from \"$t\" where $tscol > '$cut'")
        detail=" — 백업에 없는 구간 시작 $first"
      fi
    fi
    printf "  DRIFT %-22s 운영 %s / 복원 %s (백업 이후 +%s행)%s\n" "$t" "$a" "$b" "$((a-b))" "$detail"
    DRIFT=1
  else
    # 복원본이 더 많다 = 백업 이후 '삭제'가 있었거나(정리 작업 등) 진짜 이상.
    # 둘을 개수만으로는 못 가르므로 판단 재료를 같이 준다.
    printf "  CHECK %-22s 운영 %s / 복원 %s (복원본이 %s행 많음 — 백업 이후 삭제이거나 이상)\n" \
      "$t" "$a" "$b" "$((b-a))"
    DRIFT=1
  fi
done

# ════════════ ③ DB 바깥 — 이미지 참조 목록 ════════════
# 복원된 글이 가리키는 업로드 이미지 파일명을 뽑아 워크스테이션으로 넘긴다.
# 실제 S3 존재 확인은 이쪽에서 못 한다 — EC2엔 그 버킷 읽기 권한이 없다(의도적).
# 그래서 목록만 내보내고, 판정은 자격증명이 있는 워크스테이션이 한다.
# regexp_matches는 SETOF text[]라 FROM 절에서 LATERAL로 펼치고, 컬럼 이름을 명시적으로
# 붙여야 한다(`as m(parts)`). 별칭만 주면 m이 '행 전체'를 가리켜 m[1] 첨자가 안 먹는다.
IMG_SQL="from (select content as s from posts union all select cover_image from posts where cover_image is not null) x, lateral regexp_matches(x.s, '/uploads/([A-Za-z0-9._-]+)', 'g') as m(parts)"
img_total=$(dst "select count(distinct parts[1]) $IMG_SQL")
echo "  --- 글이 참조하는 이미지: ${img_total}개 ---"
dst "select distinct parts[1] $IMG_SQL order by 1" | sed -n 's/^\(..*\)$/  IMG \1/p'

$DC exec -T db psql -U postgres -d postgres -q -c "drop database restore_test;"
rm -f /tmp/restore.sql.gz /tmp/restore.log /tmp/drill_tables /tmp/drill_serials
echo "  정리 완료 — 남은 DB: $(src "select string_agg(datname,', ' order by datname) from pg_database where datistemplate=false")"

if [ $FAIL -eq 0 ]; then
  if [ $DRIFT -eq 0 ]; then
    echo "  == 구조 전부 통과, 데이터도 백업 시점과 동일 =="
  else
    echo "  == 구조 전부 통과 (데이터 차이는 백업 이후 변경 — 위 DRIFT/CHECK 줄 참고) =="
  fi
else
  echo "  == 구조 검사 실패 — 이 백업으로는 서비스가 그대로 돌아오지 않는다 =="
  exit 1
fi
REMOTE

scp -q -o StrictHostKeyChecking=no -i "$SSH_KEY" \
  "$STAGE/remote.sh" "ec2-user@$DNS:/tmp/restore_drill_remote.sh"

# 출력은 그대로 보여주되(tee), 이미지 목록을 뽑아 쓰려고 파일로도 남긴다.
# ssh가 실패해도 아래 ④를 돌려야 하므로 rc를 받아두고 마지막에 반영한다.
rc=0
ssh -o StrictHostKeyChecking=no -i "$SSH_KEY" "ec2-user@$DNS" \
  'bash /tmp/restore_drill_remote.sh; rc=$?; rm -f /tmp/restore_drill_remote.sh; exit $rc' \
  | tee "$STAGE/remote.out" || rc=$?

# ── 4. DB 바깥 검증 (워크스테이션 자격증명으로) ─────────────────────────────
say "4/4 DB 바깥 — 이미지와 백업 저장소"

# ④-1 복원된 글이 참조하는 이미지가 실제로 S3에 있는가.
# DB만 완벽히 복원돼도 이 파일들이 없으면 글은 깨진 이미지로 뜬다. 이미지는 덤프에
# 안 들어가고, 하필 프론트 배포와 같은 버킷(`s3 sync --delete`의 사정권)에 산다.
mapfile -t IMGS < <(sed -n 's/^  IMG \(..*\)$/\1/p' "$STAGE/remote.out")
if [ "$rc" -ne 0 ] && ! grep -q '참조하는 이미지' "$STAGE/remote.out"; then
  # 원격이 목록을 뱉기 전에 죽었다. 이걸 "이미지 없음"으로 찍으면 확인을 못 한 것을
  # 확인해서 문제없는 것처럼 읽힌다 — 초록 문구를 섞지 않는다.
  echo "  --   원격 단계가 목록을 내기 전에 끝나 이미지 확인을 못 했습니다"
elif [ "${#IMGS[@]}" -eq 0 ]; then
  echo "  --   참조된 이미지가 없습니다(확인할 것 없음)"
else
  checked=0; missing=0
  for name in "${IMGS[@]}"; do
    [ -n "$name" ] || continue
    if [ "$checked" -ge "$IMG_CHECK_MAX" ]; then break; fi
    checked=$((checked+1))
    if ! aws s3api head-object --bucket "$IMAGE_BUCKET" --key "uploads/$name" >/dev/null 2>&1; then
      echo "  WARN 이미지 없음: s3://$IMAGE_BUCKET/uploads/$name"
      missing=$((missing+1))
    fi
  done
  if [ "$missing" -eq 0 ]; then
    echo "  OK   참조 이미지 $checked개 모두 S3에 존재"
  else
    # 불합격시키지 않는 이유: 이건 백업/복원의 결함이 아니라 '이미 깨져 있는 글'이다.
    # (지금 라이브에서도 똑같이 깨져 보인다.) 여기서 FAIL을 내면 옛 글 하나 때문에
    # 훈련이 영구 빨간불이 되고, 영구 빨간불은 아무도 안 보는 신호와 같다.
    # 고치는 방법은 그 글을 정리하거나 이미지를 다시 올리는 것이지 백업을 바꾸는 게 아니다.
    echo "  WARN 참조 이미지 $checked개 중 $missing개가 없습니다 → 그 글은 지금도 이미지가 깨져 있습니다"
    echo "       (백업 결함이 아니라 데이터 문제 — 해당 글을 정리하거나 이미지를 재업로드하세요)"
  fi
  # 상한 때문에 덜 봤으면 반드시 말한다. 조용히 자르면 '전부 확인했다'로 읽힌다.
  if [ "${#IMGS[@]}" -gt "$IMG_CHECK_MAX" ]; then
    echo "  --   참조 ${#IMGS[@]}개 중 앞 $IMG_CHECK_MAX개만 확인했습니다(IMG_CHECK_MAX)"
  fi
fi

# ④-2 이미지 사본이 백업 버킷에도 있는가(원본 버킷 사고와 무관한 두 번째 사본).
# `aws s3 ls`는 일치하는 객체가 없으면 **종료코드 1**이라, 그냥 파이프로 받으면
# pipefail이 그걸 실패로 잡아 스크립트가 여기서 죽는다. 없는 것도 정상 결과다.
srcn=$( { aws s3 ls "s3://$IMAGE_BUCKET/uploads/" --recursive || true; } | wc -l)
dstn=$( { aws s3 ls "s3://$BUCKET/uploads/" --recursive || true; } | wc -l)
if [ "$dstn" -ge "$srcn" ] && [ "$srcn" -gt 0 ]; then
  echo "  OK   이미지 사본 $dstn개 (원본 $srcn개) — s3://$BUCKET/uploads/"
elif [ "$srcn" -eq 0 ]; then
  echo "  --   원본 버킷에 이미지가 없습니다"
else
  echo "  WARN 이미지 사본이 부족합니다 (원본 $srcn / 사본 $dstn). 정지 절차가 미러합니다:"
  echo "       aws s3 sync s3://$IMAGE_BUCKET/uploads/ s3://$BUCKET/uploads/"
fi

# ④-3 만료되지 않는 사본이 있는가.
# 날짜별 덤프는 180일 뒤 lifecycle이 지운다. 백업이 '서버를 끌 때만' 도는 구조라,
# 오래 손을 놓으면 마지막 백업이 만료돼 0개가 되는 구간이 생길 수 있다.
if keep=$(aws s3api head-object --bucket "$BUCKET" --key "keep/latest.sql.gz" \
            --query 'LastModified' --output text 2>/dev/null); then
  echo "  OK   만료 안 되는 사본 있음 — keep/latest.sql.gz ($keep)"
else
  echo "  WARN keep/latest.sql.gz 가 없습니다. 다음 정지 절차가 만들어 둡니다:"
  echo "       (또는 지금: aws s3 cp s3://$BUCKET/$KEY s3://$BUCKET/keep/latest.sql.gz)"
fi

# ④-4 시크릿 사본. DB가 완벽해도 .env가 없으면 서비스는 못 뜬다.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"$SCRIPT_DIR/env_escrow.sh" check || true

say "훈련 종료"
exit "$rc"
