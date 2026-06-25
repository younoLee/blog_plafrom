from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.core.ratelimit import limiter
from app.routers import posts, subscribers, comments, uploads, auth, subscriptions, ai, admin
from app.services.status import run_checks, get_history, start_recorder


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 앱 기동 시 1분 간격 자가 점검 기록 시작 (업타임 집계용)
    start_recorder()
    yield


app = FastAPI(title="Blog Platform API", lifespan=lifespan)

# 레이트 리밋: 한도 초과 시 429 응답 (가입/로그인 폭주 방어)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite 개발 서버
    allow_methods=["*"],
    allow_headers=["*"],
)


# 모든 API 라우트를 /api 아래로 (CloudFront가 /api/*를 EC2로 라우팅 → HTTPS 통일)
app.include_router(auth.router, prefix="/api")
app.include_router(posts.router, prefix="/api")
app.include_router(subscribers.router, prefix="/api")
app.include_router(comments.router, prefix="/api")
app.include_router(subscriptions.router, prefix="/api")
app.include_router(uploads.router, prefix="/api")
app.include_router(ai.router, prefix="/api")
app.include_router(admin.router, prefix="/api")

# 업로드된 이미지 파일 서빙: GET /uploads/<파일명> → uploads/ 폴더
# (이미지 URL은 public_base_url 기준. CloudFront에서 /uploads/* 도 EC2로 넘김)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")


@app.get("/api/health")
def health_check():
    return {"status": "ok"}


@app.get("/api/status")
def status():
    # 지금 이 순간 상태 (상태 페이지가 사용)
    c = run_checks()
    return {
        "backend": "ok" if c["backend_ok"] else "down",
        "database": "ok" if c["database_ok"] else "down",
        "mail": "ok" if c["mail_ok"] else "down",
        "stats": {"posts": c["posts"], "subscribers": c["subscribers"]},
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/status/history")
def status_history(days: int = 30):
    # 최근 N일 일별 업타임 (업타임 페이지가 사용). 범위 1~90일로 제한
    days = max(1, min(days, 90))
    return get_history(days)
