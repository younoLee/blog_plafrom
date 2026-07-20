#!/bin/bash
# EC2에서 실행: 로컬 Postgres 컨테이너를 pg_dump → gzip → S3에 업로드.
# 인증은 EC2 인스턴스 프로파일(blog-ec2-backup) — 키를 서버에 두지 않는다.
# 권한은 이 버킷 PutObject로만 좁혀져 있다(terraform/db-backup.tf).
#
# 직접 부를 일은 거의 없다. 정지 절차(scripts/stop_server.sh 1단계)가 이 파일을
# 서버로 올린 뒤 실행한다 — 저장소가 원본이고 서버 사본은 매번 덮어써진다.
# 그래야 인스턴스를 새로 만들어도 백업 능력이 조용히 사라지지 않는다.
#
# 왜 '끄기 직전'인가: DB가 바뀌는 건 EC2가 켜진 동안뿐이고, 끄면 다음에 켤 때까지
# 사본을 만들 기회가 없다. 옛날엔 cron(매일 KST 03시)이었는데 그 시각엔 서버가
# 늘 꺼져 있어 한 번도 안 돌았다(2026-07-20 발견) → cron 제거, 정지 절차로 이전.
set -euo pipefail

BUCKET=blog-db-backups-181568979775
STAMP=$(date -u +%F-%H%M)

cd /home/ec2-user/blog
docker compose -f docker-compose.prod.yml exec -T db pg_dump -U postgres postgres \
  | gzip \
  | aws s3 cp - "s3://${BUCKET}/blog-${STAMP}.sql.gz"
