from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings

# pool_pre_ping: RDS는 유휴 커넥션·페일오버·유지보수로 커넥션을 끊는다. 이게 없으면
# 죽은 커넥션을 재사용하다 첫 쿼리가 "server closed the connection unexpectedly" 500을
# 낸다(로컬 Postgres에선 거의 안 겪지만 RDS에선 흔하다). 매 체크아웃마다 가볍게 ping해서
# 죽었으면 조용히 새로 뚫는다. pool_recycle은 오래 산 커넥션을 주기적으로 갈아 같은 문제를 예방.
engine = create_engine(settings.database_url, pool_pre_ping=True, pool_recycle=300)
SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
