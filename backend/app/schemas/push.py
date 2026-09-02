from pydantic import BaseModel, Field

from app.schemas.base import SafeModel


class PushKey(BaseModel):
    """브라우저가 구독에 쓸 VAPID 공개키(base64url). 비밀이 아니다."""

    public_key: str


class PushStatus(BaseModel):
    """알림 상태 — 서버가 푸시를 지원하는지, 이 계정이 몇 대에서 받는지."""

    enabled: bool
    devices: int


class PushSubscribe(SafeModel):
    """브라우저의 `pushManager.subscribe()` 결과를 그대로 받는다.

    길이 상한을 두는 이유: 이 값들은 클라이언트가 주는 문자열이고 DB에 그대로
    들어간다. endpoint는 벤더마다 달라 넉넉히 잡되(FCM은 200자 안팎), 무한정
    받아 저장하지는 않는다. p256dh는 65바이트, auth는 16바이트를 base64url로
    인코딩한 값이라 실제로는 각각 88자·24자 근처다.
    """

    endpoint: str = Field(min_length=10, max_length=2000)
    p256dh: str = Field(min_length=10, max_length=255)
    auth: str = Field(min_length=10, max_length=255)


class PushUnsubscribe(SafeModel):
    """해제 대상. endpoint를 주면 그 기기만, 없으면(null) 이 계정의 전 기기.

    상한은 형제인 PushSubscribe.endpoint와 같은 값이다. SafeModel을 타므로
    NUL·고아 서로게이트가 여기서 자동으로 422가 된다. 구경로(DELETE /api/push)가
    has_nul을 손으로 부르던 자리를 스키마가 대신한다.

    2026-09-02에 생겼다. 그전엔 해제 대상이 쿼리스트링이라 기기 식별자가 액세스
    로그에 남았다(초대 토큰을 본문으로 옮긴 것과 같은 이유).
    """

    endpoint: str | None = Field(default=None, max_length=2000)
