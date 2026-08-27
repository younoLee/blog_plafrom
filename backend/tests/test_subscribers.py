"""이메일 뉴스레터 구독 — 2026-08-27에 테이블까지 완전히 제거됐다.

폐지 경위는 셋이다. 확인해도 후속 메일이 없는 막다른 길이었고, SES 샌드박스에서
조용히 사라졌고, 그러면서 방문자에겐 "확인 메일을 보냈어"라고 답하고 있었다.
2026-07-18에 글쓴이별 계정 구독(`author_subscriptions`)으로 일원화하면서 기능이
없어졌고, 07-31에 수집 라우트를 뗐고, 08-27에 남은 관리자 라우트와 테이블을 지웠다.

**여기서 못박는 것은 하나로 줄었다** — 임의의 주소로 메일을 쏘던 경로가 정말로
없어졌는가. 'SES 프로덕션 액세스가 필요 없다'는 판단이 이 사실 위에 서 있으므로,
되살아나면 그 판단도 같이 무너진다.

08-27에 없어진 것: 관리자용 `GET /api/subscribers`·`DELETE /api/subscribers/{id}`와
`subscribers` 테이블. 남긴 근거가 "쌓인 주소를 확인하고 지울 방법"이었는데 운영 DB를
세어보니 0행이었고, 쓰는 코드도 없어 늘어날 수도 없었다. 게다가 그 두 라우트를 부르는
화면이 아예 없어서 '만들어놨는데 못 쓰는' 상태였다.
"""

# 폐지된 경로 전부. 살아 있으면 임의 주소로 메일이 나가거나, 지워진 테이블을 건드려
# 500이 난다. 08-27에 관리자 경로 둘을 이 목록에 더했다.
RETIRED = [
    ("post", "/api/subscribers", {"json": {"email": "x@test.com"}}),
    ("post", "/api/subscribers/confirm?token=whatever", {}),
    ("post", "/api/subscribers/unsubscribe", {"json": {"email": "x@test.com"}}),
    ("get", "/api/subscribers/me", {}),
    ("post", "/api/subscribers/me", {}),
    ("delete", "/api/subscribers/me", {}),
    ("get", "/api/subscribers", {}),
    ("delete", "/api/subscribers/1", {}),
]


def test_retired_routes_never_succeed(client):
    """폐지된 경로는 어느 것도 성공해서는 안 된다.

    '404여야 한다'가 아니라 '성공하면 안 된다'로 적는다. 상태코드를 못박으면 라우팅의
    우연한 값을 계약으로 만들어버린다 — 예전에 `DELETE /subscribers/me`가 404가 아니라
    401이 되던 것이 그런 경우였다(관리자 라우트의 `{id}`와 모양이 같았다).
    중요한 건 옛 동작이 사라졌다는 것이다.
    """
    for method, path, kwargs in RETIRED:
        r = getattr(client, method)(path, **kwargs)
        assert not (200 <= r.status_code < 300), f"{method.upper()} {path} → {r.status_code}"


def test_public_subscribe_endpoint_is_gone(client):
    """`POST /api/subscribers`는 특히 확실히 없어야 한다.

    이 앱에서 **검증 안 된 임의 주소로 메일이 나가던 유일한 경로**였다.
    """
    r = client.post("/api/subscribers", json={"email": "stranger@test.com"})
    assert r.status_code in (404, 405)


def test_subscribe_confirm_email_sender_is_gone():
    """확인 메일 발송 함수 자체가 없어야 한다. 남아 있으면 누가 다시 부른다."""
    from app.services import email

    assert not hasattr(email, "send_subscribe_confirm_email")


def test_subscriber_model_is_gone():
    """모델이 남아 있으면 create_all 이 테이블을 되살린다.

    테스트는 `Base.metadata.create_all` 로 스키마를 만든다. 모델만 남기고 마이그레이션만
    지우면 **테스트에서는 테이블이 있고 운영에는 없는** 상태가 되는데, 그 차이는
    배포하고 나서야 드러난다. 그래서 모델의 부재를 여기서 못박는다.
    """
    import importlib

    try:
        importlib.import_module("app.models.subscriber")
    except ModuleNotFoundError:
        return
    raise AssertionError("app/models/subscriber.py 가 아직 있다 — create_all 이 테이블을 되살린다")
