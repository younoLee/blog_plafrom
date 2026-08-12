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
