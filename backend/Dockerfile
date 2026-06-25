FROM python:3.12-slim

WORKDIR /app

# psycopg2-binary는 휠로 설치되지만, 빌드 안정성 위해 최소 라이브러리만
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 업로드 폴더 보장 (StaticFiles가 시작 시 이 폴더를 필요로 함)
RUN mkdir -p uploads
