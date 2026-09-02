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
# connect_args — 2026-08-27 카오스 훈련(`db hang`)에서 처음 실측한 뒤 넣었다.
#
# **무엇을 쟀나.** 08-26 회차까지 DB 주입은 `docker stop` 하나뿐이라 잰 것이 전부
# '거부'였다(3.81초). 커널이 RST를 주므로 상한이 저절로 생긴다. 08-27에 `docker pause`로
# '연결은 받고 대답을 안 한다'를 재현했더니 `GET /api/posts`가 **120초·240초 둘 다
# 응답 0바이트**로 끝났다(`time_connect` 0.0002초 — TCP는 즉시 붙는다).
# 즉 이 자리에 상한이 **없었다.**
#
# 그래서 사고 모양이 뒤집혀 있었다: 먼저 온 20명은 안내조차 없이 무한 대기하고(code=000),
# 정원이 찬 뒤 21번째부터는 pool_timeout=5 덕에 4.6초에 깔끔한 503+JSON을 받는다.
# 늦게 온 사람이 더 나은 대접을 받는다.
#
# **무엇을 고치고 무엇을 못 고치는가 — 이 구분이 이 주석의 핵심이다.**
#   · connect_timeout: **새 커넥션**에만 걸린다. 풀이 비었거나 갈릴 때가 여기다.
#   · keepalives: 상대가 **ACK 자체를 멈춘** 경우(호스트 사망·네트워크 블랙홀)를 끊는다.
#   · 둘 다 **못 끊는 경우가 있다** — 프로세스만 얼고 커널은 살아 있는 서버.
#     `docker pause`가 정확히 그것이고, 훈련이 잰 240초가 그 경우다. 커널이 SELECT 1을
#     받아 ACK 해주므로 keepalive도 정상이고, 이미 열린 커넥션의 읽기에는 libpq에
#     상한 자체가 없다. RDS 페일오버는 보통 연결을 끊어주므로 현실에서는 위 둘이 잡지만,
#     **"이제 DB hang에 상한이 생겼다"고 적으면 그건 거짓말이다.**
#     남은 자리는 요청 단위 데드라인(미들웨어)이고, 그건 발행 경로 전체의 경계를
#     건드리는 변경이라 여기서 하지 않는다.
#
# 숫자의 근거 — connect 5초는 uploads.py의 S3 `connect_timeout=5`와 같은 앵커다.
# 이 DB는 같은 호스트에 얹혀 있어(RDS는 2026-07-18에 비용으로 제거) 정상이면 밀리초다.
# keepalive 5+5×3 = 약 20초는 CloudFront 오리진 read timeout 60초 안에 두 번 들어간다.
_CONNECT_ARGS = {
    "connect_timeout": 5,
    "keepalives": 1,
    "keepalives_idle": 5,
    "keepalives_interval": 5,
    "keepalives_count": 3,
}

# hide_parameters — **로그에 사용자 입력이 남지 않게 한다**(2026-09-02).
# SQLAlchemy는 예외를 문자열로 만들 때 실행한 SQL과 **바인딩 값**을 함께 붙인다.
# main.py의 DataError 핸들러가 `logger.warning("DB가 값을 거절: %s", exc)`로 예외를
# 통째로 찍고 있었으므로, 그 값(이메일·댓글/글 본문 등 사용자가 보낸 원문)이 그대로
# 컨테이너 로그에 남았다. 같은 파일의 db_unavailable이 `exc.orig`만 찍는 것이 같은
# 함정을 이미 한 번 피한 자리인데, 바로 옆 핸들러가 안 쓸려 있었다.
# 핸들러마다 무엇을 찍을지 고르는 대신 엔진에서 한 번 막는다 — 예외를 문자열로 만드는
# 자리는 앞으로도 또 생기고(로깅·트레이스백), 그때마다 다시 새기 때문이다.
# 진단은 안 잃는다: SQL 문과 예외 종류·DB 메시지는 그대로 남고 값 자리만 가려진다.
#
# **범위 주의**: 이건 이 엔진에만 걸린다. services/status.py의 `_probe_engine`은 별도지만
# 거기서 도는 건 파라미터 없는 `SELECT 1`뿐이라 남을 값이 없다. tests/conftest.py도
# 자기 엔진을 따로 만든다 — 테스트에서 이 옵션을 확인할 수 없다는 뜻이라 적어둔다.
engine = create_engine(
    settings.database_url,
    hide_parameters=True,
    pool_pre_ping=True,
    pool_recycle=300,
    pool_size=10,
    max_overflow=10,
    pool_timeout=5,
    connect_args=_CONNECT_ARGS,
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
