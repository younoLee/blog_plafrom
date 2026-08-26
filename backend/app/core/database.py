from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings

# pool_pre_ping: RDS는 유휴 커넥션·페일오버·유지보수로 커넥션을 끊는다. 이게 없으면
# 죽은 커넥션을 재사용하다 첫 쿼리가 "server closed the connection unexpectedly" 500을
# 낸다(로컬 Postgres에선 거의 안 겪지만 RDS에선 흔하다). 매 체크아웃마다 가볍게 ping해서
# 죽었으면 조용히 새로 뚫는다. pool_recycle은 오래 산 커넥션을 주기적으로 갈아 같은 문제를 예방.
# pool_size·max_overflow를 명시하는 이유 — 2026-08-26 부하검사에서 잰 비대칭.
# 안 적으면 SQLAlchemy 기본값이 pool_size=5 + max_overflow=10 = 동시 커넥션 15다.
# 반대편은 40이다: 라우터 핸들러 65개가 전부 sync `def`라(async def 0건) 모든 요청이 anyio 스레드풀을
# 거치는데 그 정원이 40이다(부하 중 컨테이너 PIDs가 정확히 그 수까지 오르는 것으로 확인).
#
# **스레드 40 > 커넥션 15**라 DB를 타는 경로에 동시 40건이 들어오면 25건이 커넥션을 못 잡고
# pool_timeout(기본 30초)을 통째로 기다린 뒤 503이 된다. 기다리는 동안 스레드 칸도 하나씩
# 붙들고 있으므로, 느려지는 게 아니라 30초짜리 벽이 생긴다.
#
# 정원을 40까지 올려 맞추지는 않는다. 운영은 vCPU 1개에 Postgres가 같은 호스트에 얹혀
# 있어(RDS는 2026-07-18에 비용으로 제거) 커넥션을 늘리면 Postgres 쪽이 먼저 죽는다.
# 그래서 20(10+10)으로 조금만 올리고, **남는 간극은 기다림을 짧게 만들어 덮는다** —
# pool_timeout 30초 → 5초. 스레드 40 > 커넥션 20인 상태는 그대로지만, 못 잡은 요청이
# 스레드를 30초가 아니라 5초만 붙들고 503으로 떨어져 곧 돌려준다.
# 느린 실패보다 빠른 실패가 낫다. 진짜 해소는 커넥션이 아니라 워커 수 쪽에 있다
# (docker-compose.prod.yml의 uvicorn에 --workers가 없어 워커가 1개다).
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_recycle=300,
    pool_size=10,
    max_overflow=10,
    pool_timeout=5,
)
SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
