from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.ratelimit import limiter
from app.models.user import User
from app.routers import (
    admin,
    ai,
    auth,
    comments,
    notifications,
    payments,
    posts,
    subscribers,
    subscriptions,
    uploads,
)
from app.services.cleanup import start_cleanup
from app.services.status import get_history, get_latest, start_recorder

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

# 요청 본문 크기 상한 (t2.micro 메모리 고갈 DoS 방지).
# Content-Length가 상한을 넘으면 본문을 메모리에 버퍼링하기 '전에' 413으로 끊는다
# (안 그러면 무인증 큰 요청 몇 개로 OOM 가능 — 실측 확인됨). 이미지 업로드(5MB)는 통과하도록 6MB.
# 엣지(WAF/CloudFront)에도 같은 상한을 두면 EC2에 닿기 전에 막혀 더 좋다.
MAX_BODY_BYTES = 6 * 1024 * 1024


@app.middleware("http")
async def limit_body_size(request: Request, call_next):
    cl = request.headers.get("content-length")
    if cl is not None:
        try:
            if int(cl) > MAX_BODY_BYTES:
                return JSONResponse(
                    {"detail": "요청 본문이 너무 큽니다 (최대 6MB)"}, status_code=413
                )
        except ValueError:
            pass
    return await call_next(request)


# 모든 API 라우트를 /api 아래로 (CloudFront가 /api/*를 EC2로 라우팅 → HTTPS 통일)
app.include_router(auth.router, prefix="/api")
app.include_router(posts.router, prefix="/api")
app.include_router(subscribers.router, prefix="/api")
app.include_router(comments.router, prefix="/api")
app.include_router(subscriptions.router, prefix="/api")
app.include_router(uploads.router, prefix="/api")
app.include_router(ai.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(payments.router, prefix="/api")
app.include_router(notifications.router, prefix="/api")

# 업로드된 이미지 파일 서빙: GET /uploads/<파일명> → uploads/ 폴더
# ⚠️ 이건 **로컬 개발용 폴백**이다. 운영에서는 S3_BUCKET이 설정돼 있어 이미지가 S3에
# 저장되고(routers/uploads.py), CloudFront의 /uploads/* 전용 동작은 2026-06-26에
# 제거돼 기본 S3 오리진이 직접 서빙한다 — 즉 운영 트래픽은 이 마운트를 타지 않는다.
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
@limiter.limit("30/minute")  # 무인증 남용 방지 (이제 캐시라 가볍지만 유지)
def status(request: Request):
    # 백그라운드가 1분마다 갱신한 캐시를 반환 (매 호출 라이브 점검·SMTP 연결 안 함)
    c = get_latest()
    return {
        "backend": "ok" if c["backend_ok"] else "down",
        "database": "ok" if c["database_ok"] else "down",
        "mail": "ok" if c["mail_ok"] else "down",
        "stats": {"posts": c["posts"], "subscribers": c["subscribers"]},
        "checked_at": datetime.now(UTC).isoformat(),
    }


@app.get("/api/status/history")
@limiter.limit("30/minute")  # 무인증 + 매 호출 DB 집계 쿼리 → 남용 시 DB 부하 방지
def status_history(request: Request, days: int = 30):
    # 최근 N일 일별 업타임 (업타임 페이지가 사용). 범위 1~90일로 제한
    days = max(1, min(days, 90))
    return get_history(days)
