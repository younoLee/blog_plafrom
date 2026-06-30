from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.ratelimit import limiter
from app.models.user import User
from app.routers import posts, subscribers, comments, uploads, auth, subscriptions, ai, admin
from app.services.status import run_checks, get_history, start_recorder
from app.services.cleanup import start_cleanup

# 절대 운영에서 쓰면 안 되는 기본 SECRET_KEY (코드에 공개돼 있어 토큰 위조 가능)
_INSECURE_SECRET = "change-me-in-production"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 보안 가드: SECRET_KEY가 기본값이거나 너무 약하면 서버를 아예 띄우지 않음(fail-closed).
    # 이게 없으면 .env에 키를 빠뜨린 채 배포돼도 조용히 위험해짐(실제로 한 번 그랬음).
    if settings.secret_key in ("", _INSECURE_SECRET) or len(settings.secret_key) < 16:
        raise RuntimeError(
            "SECRET_KEY가 없거나 너무 약함. .env에 강력한 임의값을 설정해줘 "
            "(예: openssl rand -hex 32)."
        )
    # 앱 기동 시 1분 간격 자가 점검 기록 시작 (업타임 집계용)
    start_recorder()
    # 미인증 계정 1시간 간격 자동 정리 시작
    start_cleanup()
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


@app.get("/api/blog-owner")
def blog_owner(db: Session = Depends(get_db)):
    # 이 블로그의 주인(관리자). 프론트의 '이 블로그 구독' 버튼이 이 id를 구독함.
    owner = db.scalar(select(User).where(User.role == "admin").order_by(User.id))
    if owner is None:
        return {"id": None, "name": None}
    return {"id": owner.id, "name": owner.email.split("@")[0]}


@app.get("/api/status")
@limiter.limit("30/minute")  # 무인증 + 매 호출 SMTP 소켓(최대 2초) → 남용 시 워커 점유 방지
def status(request: Request):
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
