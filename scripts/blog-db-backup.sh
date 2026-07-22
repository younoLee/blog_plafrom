#!/bin/bash
# EC2에서 실행: 로컬 Postgres 컨테이너를 pg_dump → gzip → 검증 → S3에 업로드.
# 인증은 EC2 인스턴스 프로파일(blog-ec2-backup) — 키를 서버에 두지 않는다.
# 권한은 이 버킷 `blog-*` PutObject로만 좁혀져 있다(terraform/db-backup.tf).
#
# 직접 부를 일은 거의 없다. 정지 절차(scripts/stop_server.sh)가 이 파일을
# 서버로 올린 뒤 실행한다 — 저장소가 원본이고 서버 사본은 매번 덮어써진다.
# 그래야 인스턴스를 새로 만들어도 백업 능력이 조용히 사라지지 않는다.
#
# 왜 '끄기 직전'인가: DB가 바뀌는 건 EC2가 켜진 동안뿐이고, 끄면 다음에 켤 때까지
# 사본을 만들 기회가 없다. 옛날엔 cron(매일 KST 03시)이었는데 그 시각엔 서버가
# 늘 꺼져 있어 한 번도 안 돌았다(2026-07-20 발견) → cron 제거, 정지 절차로 이전.
#
# 왜 스트리밍(`pg_dump | gzip | aws s3 cp -`)을 그만뒀나 —
#   그 모양으론 **올리기 전에 검사할 방법이 없다**. 그리고 pg_dump가 중간에 죽어도
#   gzip은 자기가 받은 데까지 정상적으로 마무리하므로 `gzip -t`는 통과한다. 즉
#   '잘린 덤프'가 무결한 파일처럼 S3에 올라가고, 복원 훈련을 돌리기 전까지 아무도
#   모른다. 몇 MB짜리라 /tmp에 한 번 떨군 뒤 세 가지를 확인하고 올리는 편이 낫다.
set -euo pipefail

BUCKET=blog-db-backups-181568979775
STAMP=$(date -u +%F-%H%M)
KEY="blog-${STAMP}.sql.gz"
OUT="/tmp/${KEY}"

# 정상 덤프는 스키마만 해도 수십 KB다. 이 밑이면 뭔가 크게 잘못된 것.
# (운영 대비 '상대적인' 크기 급감은 여기서 못 본다 — 버킷 목록을 읽을 권한이
#  일부러 없기 때문. 그 비교는 운영자 자격증명이 있는 stop_server.sh가 한다.)
MIN_BYTES=4096

cd /home/ec2-user/blog
trap 'rm -f "$OUT"' EXIT

docker compose -f docker-compose.prod.yml exec -T db pg_dump -U postgres postgres \
  | gzip > "$OUT"

# ── 검증 3종 (올리기 전에) ──────────────────────────────────────────────────
gzip -t "$OUT"

size=$(stat -c%s "$OUT")
if [ "$size" -lt "$MIN_BYTES" ]; then
  echo "❌ 덤프가 너무 작다(${size}B < ${MIN_BYTES}B) — 올리지 않는다." >&2
  exit 1
fi

# pg_dump는 성공했을 때만 끝에 완료 표식을 남긴다. 이게 '잘렸는지'의 유일한 증거다.
#
# `| grep -q`로 받으면 안 된다 — grep이 첫 매치에서 파이프를 닫으면 앞 단계가
# EPIPE로 죽고 pipefail이 그걸 실패로 잡는다(restore_drill.sh가 `head -1`로
# 똑같이 당했다, 2026-07-22). 명령 치환은 입력을 끝까지 읽으므로 그 충돌이 없다.
trailer=$(gzip -dc "$OUT" | tail -5)
case "$trailer" in
  *"PostgreSQL database dump complete"*) ;;
  *)
    echo "❌ 덤프 끝에 완료 표식이 없다 = 중간에 잘렸다. 올리지 않는다." >&2
    exit 1
    ;;
esac

# ── 업로드 ──────────────────────────────────────────────────────────────────
aws s3 cp "$OUT" "s3://${BUCKET}/${KEY}"

# 호출자(stop_server.sh)가 파싱한다 — 방금 만든 객체를 이름으로 다시 확인하려고.
echo "BACKUP_KEY=${KEY}"
echo "BACKUP_BYTES=${size}"
