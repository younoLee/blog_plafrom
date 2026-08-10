FROM python:3.12-slim

WORKDIR /app

# psycopg2-binary는 휠로 설치되지만, 빌드 안정성 위해 최소 라이브러리만
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 업로드 폴더 보장 (StaticFiles가 시작 시 이 폴더를 필요로 함)
RUN mkdir -p uploads

# **root로 돌지 않는다.** 2026-08-10 보안검사: python:3.12-slim 기본이 root라
# 앱에서 RCE가 나면 곧 컨테이너 root였고, 호스트에서 마운트되는 ./uploads와
# `COPY . .` 결과물(=앱 코드 전체)에 그대로 쓸 수 있었다 — 코드 덮어쓰기까지 자유였다.
# uid를 고정하는 이유: 호스트 바인드 마운트(docker-compose.prod.yml의 ./uploads)의
# 소유자가 재빌드마다 흔들리면 안 된다. 10001은 AL2023의 일반 사용자 대역 밖이라
# 호스트 계정과 겹치지 않는다.
#
# uploads만 소유권을 넘긴다 — 앱 코드는 root 소유 그대로 두어 **읽기만** 가능하게 한다
# (프로세스가 자기 코드를 못 고치는 게 요점이다). 운영 업로드는 어차피 S3로 가고
# 이 폴더는 폴백이라(compose 주석 참고) 쓰기 대상이 여기 하나뿐이다.
RUN useradd --system --uid 10001 --create-home appuser \
    && chown -R appuser:appuser /app/uploads
USER appuser
