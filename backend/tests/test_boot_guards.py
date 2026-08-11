"""기동 가드 — "한 줄이 빠지면 조용히 위험해지는" 조합에서 서버가 아예 안 뜨는가.

main.py의 lifespan에는 가드가 넷 있는데 **여태 테스트가 하나도 없었다**(2026-08-11).
그게 특히 나쁜 이유: 이 가드들이 막는 사고는 전부 *조용한* 사고다. 가드가 실수로
지워지거나 조건이 뒤집혀도 테스트는 초록이고, 프로덕션은 멀쩡해 **보인다**.
가드 자체가 "조용한 실패를 시끄럽게 만드는 장치"인데 그 장치가 조용히 사라질 수 있었다.

여기서는 lifespan을 직접 돌린다(TestClient를 쓰면 conftest가 이미 띄운 앱과 얽힌다).
`prod` 픽스처는 프로덕션 표식(PUBLIC_BASE_URL이 https)을 세운 정상 상태이고, 각 테스트는
거기서 **한 줄만** 망가뜨린다 — 실제 사고가 늘 그 모양이었기 때문이다.
"""

import asyncio

import pytest

from app.core.config import settings
from app.main import lifespan


@pytest.fixture(autouse=True)
def no_background_threads(monkeypatch):
    """가드를 다 통과하면 lifespan이 데몬 스레드 둘(자가점검·정리)을 띄운다.

    테스트 DB에 1분마다 점검 행을 쓰고 미인증 계정을 지우는 물건이라, 여기서 진짜로
    돌리면 다른 테스트에 새는 부작용이 된다. 가드만 보는 게 목적이므로 막는다.
    """
    monkeypatch.setattr("app.main.start_recorder", lambda: None)
    monkeypatch.setattr("app.main.start_cleanup", lambda: None)


def boot() -> None:
    """lifespan을 진입까지만 돌린다. 가드는 전부 yield 앞에 있다."""

    async def run() -> None:
        async with lifespan(None):  # type: ignore[arg-type]
            pass

    asyncio.run(run())


@pytest.fixture
def prod(monkeypatch):
    """가드를 전부 통과하는 '정상 프로덕션' 설정. 테스트가 여기서 한 줄만 깬다."""
    monkeypatch.setattr(settings, "secret_key", "x" * 32)
    monkeypatch.setattr(settings, "origin_secret", "a" * 64)
    monkeypatch.setattr(settings, "public_base_url", "https://example.cloudfront.net")
    monkeypatch.setattr(settings, "s3_bucket", "some-bucket")
    monkeypatch.setattr(settings, "payments_require_live", True)
    return settings


def test_healthy_prod_config_boots(prod):
    """먼저 '정상이면 뜬다'를 잠근다.

    이게 없으면 나머지 테스트가 전부 가짜일 수 있다 — 아무 이유로나 죽어도
    `pytest.raises(RuntimeError)`는 통과하기 때문이다.
    """
    boot()


@pytest.mark.parametrize("bad", ["", "change-me-in-production", "short"])
def test_weak_secret_key_refuses_to_boot(prod, monkeypatch, bad):
    monkeypatch.setattr(settings, "secret_key", bad)
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        boot()


def test_non_ascii_origin_secret_refuses_to_boot(prod, monkeypatch):
    """비ASCII면 헤더 비교의 인코딩이 갈려 **어떤 요청도 못 통과한다** — 로그엔 단서가 없다."""
    monkeypatch.setattr(settings, "origin_secret", "비밀" * 20)
    with pytest.raises(RuntimeError, match="ASCII"):
        boot()


def test_empty_origin_secret_refuses_to_boot_in_prod(prod, monkeypatch):
    """빈 ORIGIN_SECRET은 `"".isascii()`가 True라 **위 ASCII 검사를 그냥 통과한다.**

    통과하면 미들웨어가 fail open이라 사이트는 200으로 멀쩡하고, watch.sh의 403 단서도
    안 뜬다(막히는 게 아니라 다 통과하니까). 즉 '엣지 우회 차단이 꺼진 채 도는' 상태가
    영원히 조용하다. 그래서 프로드에서는 기동을 막는다(2026-08-11).
    """
    monkeypatch.setattr(settings, "origin_secret", "")
    with pytest.raises(RuntimeError, match="ORIGIN_SECRET"):
        boot()


def test_empty_origin_secret_is_fine_locally(prod, monkeypatch):
    """로컬(http)에서는 빈 값이 정상이다 — 안 그러면 개발이 안 돌고,

    켤 때 'CloudFront에 헤더 먼저 → 그 다음 .env' 순서도 성립하지 않는다.
    프로드 전용 가드라는 걸 잠근다."""
    monkeypatch.setattr(settings, "public_base_url", "http://localhost:8000")
    monkeypatch.setattr(settings, "origin_secret", "")
    monkeypatch.setattr(settings, "s3_bucket", "")  # 로컬은 디스크 저장이 정상
    monkeypatch.setattr(settings, "payments_require_live", False)
    boot()


def test_prod_without_s3_bucket_refuses_to_boot(prod, monkeypatch):
    """S3_BUCKET이 비면 업로드가 **예외 없이** 컨테이너 디스크로 떨어진다.

    글쓴이는 200을 보고, 그 URL은 404이며, 컨테이너를 갈면 사라진다.
    watch.sh도 못 잡는다(원본/사본 개수 비교라 '원본이 안 늘어남'은 신호가 아니다).
    """
    monkeypatch.setattr(settings, "s3_bucket", "")
    with pytest.raises(RuntimeError, match="S3_BUCKET"):
        boot()


def test_prod_without_payments_live_guard_refuses_to_boot(prod, monkeypatch):
    """PAYMENTS_REQUIRE_LIVE가 꺼져 있으면 **코드 기본값인 토스 테스트 키**로 승인이 붙는다.

    = .env에서 한 줄이 빠지면 공짜 Pro. 요청 시점 검사(_guard_live)는 이 값이 True일
    때만 도니까, 그 검사 자신이 사라지는 경우를 못 본다.
    """
    monkeypatch.setattr(settings, "payments_require_live", False)
    with pytest.raises(RuntimeError, match="PAYMENTS_REQUIRE_LIVE"):
        boot()
