"""오리진 공유 시크릿 미들웨어.

막는 것: 공격자가 자기 CloudFront 배포로 우리 오리진을 직접 때려 WAF·CSP를 우회하는 것.
오리진 SG는 'CloudFront 엣지 전체'를 받으므로 SG만으로는 우리 배포와 남의 배포를
구분할 수 없다. 이 헤더가 '우리 배포를 거쳐 왔다'는 유일한 증거다.

여기서 지켜야 할 성질이 셋이다. 셋 다 한 번씩 실제로 틀릴 수 있는 것들이라 테스트로 굳힌다:
  ① 설정이 비면 통과(fail open) — 아니면 켜는 순서를 틀린 순간 사이트가 전부 403이 된다
  ② /api/health는 예외 — 아니면 도커·ALB 헬스체크가 죽어 컨테이너가 영원히 unhealthy
  ③ 값이 틀리면 403 — 이게 기능 본체
"""

import pytest

from app.core.config import settings

SECRET = "s" * 40


@pytest.fixture
def enforced():
    """미들웨어를 켠 상태로 만든다(테스트가 끝나면 원래대로)."""
    before = settings.origin_secret
    settings.origin_secret = SECRET
    yield
    settings.origin_secret = before


@pytest.fixture
def disabled():
    """미들웨어를 끈 상태로 만든다.

    ambient 설정에 기대지 않고 명시적으로 비운다 — 개발자 로컬 backend/.env에
    ORIGIN_SECRET이 들어 있으면 pydantic Settings가 그걸 읽어서, '기본값이 빈 문자열'을
    전제한 테스트가 그 사람 기기에서만 깨진다. 테스트가 환경에 따라 갈리는 병은
    이 저장소가 이미 CI 빨간불로 한 번 앓았다.
    """
    before = settings.origin_secret
    settings.origin_secret = ""
    yield
    settings.origin_secret = before


def test_off_lets_everything_through(client, disabled):
    # 설정이 비면 헤더가 없어도 통과해야 한다. 이 fail open이 없으면
    # CloudFront보다 백엔드를 먼저 켰을 때 사이트 전체가 403이 된다.
    assert client.get("/api/status").status_code == 200


def test_correct_secret_passes(client, enforced):
    r = client.get("/api/status", headers={"X-Origin-Secret": SECRET})
    assert r.status_code == 200


def test_missing_secret_is_forbidden(client, enforced):
    r = client.get("/api/status")
    assert r.status_code == 403


def test_wrong_secret_is_forbidden(client, enforced):
    r = client.get("/api/status", headers={"X-Origin-Secret": "x" * 40})
    assert r.status_code == 403


def test_header_name_is_case_insensitive(client, enforced):
    # CloudFront가 실제로 어떤 대소문자로 보낼지에 의존하면 안 된다(HTTP 헤더는 대소문자 무시).
    r = client.get("/api/status", headers={"x-origin-secret": SECRET})
    assert r.status_code == 200


def test_health_is_exempt(client, enforced):
    # 도커 헬스체크(127.0.0.1)와 ALB 대상그룹 헬스체크는 CloudFront를 안 거친다.
    # 여기서 403이 나면 컨테이너가 영원히 unhealthy가 되어 배포 자체가 멈춘다.
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_prefix_of_secret_is_rejected(client, enforced):
    # 상수시간 비교라도 '앞부분만 맞으면 통과'하면 의미가 없다.
    r = client.get("/api/status", headers={"X-Origin-Secret": SECRET[:-1]})
    assert r.status_code == 403


def test_blocks_writes_too(client, enforced):
    # GET만 막고 POST가 새면 우회 차단이 아니다.
    r = client.post("/api/auth/login", json={"email": "a@b.c", "password": "x"})
    assert r.status_code == 403


def test_non_ascii_header_is_forbidden_not_crash(client, enforced):
    # Starlette은 헤더를 latin-1로 디코드한다. 이 바이트를 str 그대로
    # secrets.compare_digest에 넘기면 "comparing strings with non-ASCII characters is
    # not supported" TypeError가 나서, 차단 장치가 403 대신 500으로 스스로 죽는다.
    # 우회는 아니지만 검사가 터지는 건 기대 동작이 아니다 — bytes로 비교해 막는다.
    #
    # 헤더 값을 **bytes로** 넣는다. str로 주면 httpx가 보내기 전에 ascii 인코딩으로
    # 거부해서(UnicodeEncodeError) 서버 코드에 닿지도 못한다 — 클라이언트 라이브러리의
    # 예의를 테스트하는 꼴이 된다. 실제 공격자는 소켓에 바이트를 그대로 쓴다.
    r = client.get("/api/status", headers={"X-Origin-Secret": b"s\xe9" + b"s" * 38})
    assert r.status_code == 403
