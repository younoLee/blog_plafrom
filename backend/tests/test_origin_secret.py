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


def test_off_by_default_lets_everything_through(client):
    # 기본값(빈 문자열)에서는 헤더가 없어도 통과해야 한다. 이 fail open이 없으면
    # CloudFront보다 백엔드를 먼저 켰을 때 사이트 전체가 403이 된다.
    assert settings.origin_secret == ""
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
