"""SES 수신자 상태 조회 (2026-09-04 검사 BQ-8 신설).

이 파일이 없던 동안 `services/ses_status.py` 의 커버리지는 **13%** 였다. 전 스위트가
conftest 의 `no_ses` 픽스처로 이 함수를 통째로 대체하기 때문이다 — 라우터 시험이
아무리 많아도 이 안쪽 갈래는 한 번도 안 돈다.

여기서 잠그는 것은 **'모른다'와 '아니다'를 안 섞는 것**이다. 이 모듈의 머리말이
그렇게 적혀 있다: 권한이 없거나 자격증명이 없으면 None(모름)이고, 화면은 그때
아무 말도 하지 않는다. 그 둘을 섞으면 늑대 소년이 되어 진짜 경고까지 무시된다.

라우터를 안 거치므로 no_ses 와 충돌하지 않는다(그 픽스처는 라우터가 부르는 이름을
갈아끼운다). 여기서는 boto3.client 를 가짜로 바꿔 함수 안쪽을 직접 돈다.
"""

import boto3
import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

from app.services.ses_status import recipient_status


class FakeSES:
    def __init__(self, *, account=None, account_exc=None, identity=None, identity_exc=None):
        self._account = account or {}
        self._account_exc = account_exc
        self._identity = identity or {}
        self._identity_exc = identity_exc
        self.identity_calls: list[str] = []

    def get_account(self):
        if self._account_exc:
            raise self._account_exc
        return self._account

    def get_email_identity(self, EmailIdentity: str):  # noqa: N803 - boto3 인자 이름
        self.identity_calls.append(EmailIdentity)
        if self._identity_exc:
            raise self._identity_exc
        return self._identity


def _client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}}, "GetEmailIdentity")


@pytest.fixture
def fake_ses(monkeypatch):
    """boto3.client('sesv2', ...) 를 가짜로 바꾼다. 반환된 상자에 원하는 응답을 담는다."""
    box: dict[str, FakeSES] = {}

    def _client(name, **kw):
        assert name == "sesv2"
        return box["ses"]

    monkeypatch.setattr(boto3, "client", _client)

    def _set(**kw) -> FakeSES:
        box["ses"] = FakeSES(**kw)
        return box["ses"]

    return _set


def test_샌드박스에서_검증된_주소(fake_ses):
    ses = fake_ses(
        account={"ProductionAccessEnabled": False},
        identity={"VerifiedForSendingStatus": True},
    )
    assert recipient_status("a@example.com") == {"sandbox": True, "verified": True}
    assert ses.identity_calls == ["a@example.com"]


def test_등록조차_안_된_주소는_확실한_미검증이다(fake_ses):
    """NotFoundException 은 '모름'이 아니라 '아니다'다 — 이 둘을 가르는 게 이 모듈의 요점."""
    fake_ses(
        account={"ProductionAccessEnabled": False},
        identity_exc=_client_error("NotFoundException"),
    )
    assert recipient_status("nobody@example.com") == {"sandbox": True, "verified": False}


def test_권한이_없으면_모름으로_남는다(fake_ses):
    """AccessDenied 를 '미검증'으로 접으면 멀쩡한 주소에 경고가 뜬다."""
    fake_ses(
        account={"ProductionAccessEnabled": False},
        identity_exc=_client_error("AccessDeniedException"),
    )
    assert recipient_status("a@example.com") == {"sandbox": True, "verified": None}


def test_계정_상태를_못_읽으면_둘_다_모름이다(fake_ses):
    fake_ses(account_exc=_client_error("AccessDeniedException"))
    assert recipient_status("a@example.com") == {"sandbox": None, "verified": None}


def test_네트워크_실패도_모름이다(fake_ses):
    """BotoCoreError 갈래. 여기서 던지면 초대 발급 응답이 통째로 죽는다 —
    그 응답에만 원문 토큰이 실리므로 링크를 다시 볼 방법이 없어진다."""
    fake_ses(account_exc=EndpointConnectionError(endpoint_url="https://email.example"))
    assert recipient_status("a@example.com") == {"sandbox": None, "verified": None}


def test_프로덕션_액세스면_주소를_안_물어본다(fake_ses):
    """샌드박스가 아니면 아무 주소로나 보낼 수 있으므로 검증 여부는 의미가 없다.
    괜히 물어보면 권한 오류 로그만 쌓이고 응답도 그만큼 느려진다."""
    ses = fake_ses(account={"ProductionAccessEnabled": True})
    assert recipient_status("a@example.com") == {"sandbox": False, "verified": None}
    assert ses.identity_calls == []


def test_주소_상태_네트워크_실패도_모름이다(fake_ses):
    fake_ses(
        account={"ProductionAccessEnabled": False},
        identity_exc=EndpointConnectionError(endpoint_url="https://email.example"),
    )
    assert recipient_status("a@example.com") == {"sandbox": True, "verified": None}


def test_예상_못_한_예외도_발급을_막지_않는다(monkeypatch):
    """boto3 미설치·설정 오류 같은 것. 여기서 던지면 초대 발급 자체가 죽는다."""

    def boom(*a, **kw):
        raise RuntimeError("boto3가 이상하다")

    monkeypatch.setattr(boto3, "client", boom)
    assert recipient_status("a@example.com") == {"sandbox": None, "verified": None}
