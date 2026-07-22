# --- 1단계: 빌드 (node로 정적 파일 dist/ 생성) ---
FROM node:20-alpine AS build
WORKDIR /app
# lockfile까지 먼저 복사 → npm ci 레이어 캐시 활용 (코드만 바뀌면 재설치 안 함)
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build          # tsc 타입체크 + vite build → /app/dist

# --- 2단계: 서빙 (nginx가 dist를 정적 호스팅) ---
FROM nginx:alpine
# 빌드 단계의 결과물만 가져옴 (node/소스코드는 최종 이미지에 없음 → 가벼움)
COPY --from=build /app/dist /usr/share/nginx/html
# SPA 라우팅용 nginx 설정 교체
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
