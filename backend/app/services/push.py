"""Web Push 발송 — VAPID(RFC 8292) 서명 + aes128gcm(RFC 8188) 암호화.

**왜 pywebpush를 안 쓰나** — pywebpush는 이 파일이 쓰는 바로 그 두 라이브러리
(py_vapid, http_ece)를 감싼 것이다. 즉 '틀리면 조용히 깨지는' 부분(서명·암호화)은
어느 쪽이든 같은 코드가 처리하고, 감싸개가 더 해주는 건 헤더 조립과 POST뿐이다.
그 대가가 aiohttp 생태계 11개 패키지라 직접 조립하기로 했다. 여기서 우리가 쓴
코드는 전부 검토 가능한 것들이고, 암호화가 맞게 배선됐는지는 테스트에서
'암호화 → 복호화' 왕복으로 실제로 재본다(tests/test_push.py).

**Vapid01이 아니라 Vapid02를 쓴다.** 01은 draft 시절 형식(`Authorization: WebPush …`)
이고 02가 RFC 8292(`Authorization: vapid t=…,k=…`)다. Apple의 Web Push가 후자를
요구하므로, iOS를 포기하지 않으려면 02여야 한다.
"""
import base64
import json
import logging
import os
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from urllib.parse import urlparse

import http_ece
import httpx
from cryptography.hazmat.primitives.asymmetric import ec
from py_vapid import Vapid02
from sqlalchemy import Row, delete, select

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.author_subscription import AuthorSubscription
from app.models.push_subscription import PushSubscription
from app.models.user import BANNED_ROLE, User

logger = logging.getLogger(__name__)

# 발송 루프 전체의 시간 예산(초). 기기 하나가 아니라 **루프 전체**에 거는 상한이다.
#
# 왜 필요한가 — 2026-08-26 카오스 훈련 실측. 푸시 서비스가 무응답(hang)이면 기기마다
# httpx timeout 10초를 꽉 채우고 직렬로 돌아 벽시계가 **기기수 × 10초**가 된다
# (기기 3대에 28.75초 실측). 그동안 이 루프는 anyio 스레드 한 칸을 쥐고, 더 나쁘게는
# **요청의 DB 세션이 살아 있어** 커넥션 한 칸이 `idle in transaction`으로 묶인다
# (동시 4건이 커넥션 4개를 24초 넘게 잡는 것을 실측했다).
#
# 풀이 20이라(core/database.py) **스레드 40보다 커넥션이 먼저 마른다** — 동시 20건이면
# DB를 타는 모든 요청이 pool_timeout 5초 뒤에 503이 된다. 구독자 기기가 늘수록
# 최악 시간이 선형으로 늘어나므로 기기 수에 상한을 두는 것으로는 못 막는다.
# 루프 전체에 데드라인을 걸어야 **기기 수와 무관하게** 붙드는 시간이 유한해진다.
#
# 45초의 근거: 정상 발송은 기기당 1초 미만이라 수십 대까지 여유가 있고, 장애 시에는
# 4~5대에서 끊긴다(기기당 10초). 못 보낸 알림은 다음 발행 때 다시 기회가 있지만
# 커넥션이 마르면 사이트 전체가 멈춘다 — 그 비대칭이 이 값을 정한다.
DELIVER_BUDGET_SECONDS = 45


# 마지막 발송의 결과. **프로세스 메모리다.**
#
# **왜 화면에 내놓는가 (2026-08-27)** — 아래 루프가 시도·성공·버려진 기기 수를 정확히
# 세는데(08-27에 tried/ok 를 가른 자리), 그 숫자가 **로그에만** 남는다. 로그는 EC2 안에
# 있고 이 서버는 대부분 꺼져 있어서, "알림이 안 왔다"는 말이 나왔을 때 확인하려면
# 서버를 켜고 SSH 로 들어가야 한다. 08-26 훈련이 찾은 '앞 5대만 계속 받는' 불공정도
# 로그를 사람이 읽어야만 보였다.
#
# **왜 테이블이 아닌가** — 발행마다 한 줄씩 쌓으면 보존 기간과 정리를 정해야 하고,
# 그건 이 값이 주는 것보다 비싸다. 여기서 답해야 할 질문은 "지금 알림이 나가고 있나"
# 하나이고, 그건 마지막 한 건이면 된다. status.py 가 점검 결과를 같은 방식으로
# 프로세스 메모리에 두는 것과 같은 판단이다.
#
# **한계를 그대로 적어둔다**: 재시작하면 사라지고, 워커가 여럿이면 워커마다 다르다
# (지금 uvicorn 워커는 1개다). 화면도 이걸 '마지막 발송'이라고만 말하고 통계라고
# 말하지 않는다.
_last_delivery: dict | None = None


def last_delivery() -> dict | None:
    """마지막 새 글 알림 발송의 결과. 아직 없으면 None."""
    return _last_delivery

# 푸시 서비스가 수신자를 못 만났을 때 메시지를 얼마나 붙들고 있을지(초).
# 새 글 알림은 하루가 지나면 알림으로서 의미가 옅어지므로 24시간.
TTL_SECONDS = 24 * 60 * 60

# VAPID JWT 유효기간. 표준 상한은 24시간이고, 짧을수록 유출 시 노출이 줄지만
# 발송 때마다 새로 서명하므로 길 이유가 없다.
_JWT_TTL_SECONDS = 12 * 60 * 60


# 알려진 푸시 서비스 호스트. 점으로 시작하면 서브도메인 접미사 매칭.
#
# **왜 허용목록인가** — send_push는 클라이언트가 등록한 URL로 서버가 POST한다.
# 검사가 없으면 인증된 사용자가 내부 주소(10.x, 127.0.0.1, 169.254.169.254,
# 컨테이너 이름)를 등록해 **VPC 안에서 우리 서버가 대신 요청하게** 만들 수 있다(SSRF).
# 일반적인 SSRF와 달리 여기선 정당한 목적지 집합이 작고 공개돼 있고 잘 안 바뀐다 —
# 그럴 땐 사설 IP 차단(DNS 리바인딩에 취약)보다 허용목록이 확실하다.
# httpx는 리다이렉트를 따라가지 않으므로(기본값) 우회 경로도 없다.
# 새 브라우저가 나오면 여기 한 줄 추가한다.
ALLOWED_PUSH_HOSTS = (
    "fcm.googleapis.com",  # Chrome · Edge · Android
    "android.googleapis.com",  # 구형 FCM
    "updates.push.services.mozilla.com",  # Firefox
    "web.push.apple.com",  # Safari · iOS
    ".push.services.mozilla.com",  # Mozilla 서브도메인
    ".notify.windows.com",  # Windows · 구형 Edge
)


def is_allowed_endpoint(endpoint: str) -> bool:
    """푸시 서비스로 알려진 https 주소인가.

    등록 시점(routers/push.py)과 발송 시점(send_push) **양쪽에서** 부른다.
    등록만 막으면 이 검사가 생기기 전에 저장된 행이 그대로 발송된다."""
    try:
        parts = urlparse(endpoint)
    except ValueError:
        return False
    if parts.scheme != "https" or not parts.hostname:
        return False
    host = parts.hostname.lower()
    return any(
        host == h if not h.startswith(".") else host.endswith(h)
        for h in ALLOWED_PUSH_HOSTS
    )


class PushGone(Exception):
    """구독이 영구히 무효(404/410) — 지워야 한다는 신호.

    일시적 실패(5xx·타임아웃)와 반드시 구분한다. 섞으면 푸시 서비스가 잠깐
    흔들릴 때 멀쩡한 구독을 전부 지워버린다."""


class PushFailed(Exception):
    """벤더가 4xx·5xx로 거절했다 — 이 기기는 **못 받았다**.

    ⚠️ **2026-09-05까지 이 예외가 없었다.** `send_push` 가 404/410 외의 4xx·5xx를
    로그만 남기고 정상 반환해서, 호출부의 `ok += 1` 이 그대로 돌았다. 그래서
    VAPID 키가 어긋나 전 기기가 401을 받는 상황에서도 관리자 화면이 "3대 중 3대
    성공"이라는 **초록 거짓말**을 했다. 그 화면의 존재 이유가 정확히 '지금 알림이
    나가고 있나'인데, 안 나갈 때 초록이면 화면이 없는 것만 못하다.

    바로 위 `_deliver` 의 주석이 "시도와 성공을 가른다"고 적어둔 그 구분이 실제로는
    예외가 난 경우에만 서 있었다 — 08-27에 그 자리를 고치면서 예외 갈래만 봤고
    '거절당했지만 예외는 아닌' 갈래가 남았다(2026-09-04 검사 BE-1).

    PushGone 과 다른 이유: 이건 지우면 안 된다. 401은 서버 키 문제이고 429·5xx는
    벤더 사정이라, 구독은 멀쩡한데 이번에 못 보낸 것뿐이다."""


def _b64url_decode(value: str) -> bytes:
    """브라우저가 주는 키는 패딩 없는 base64url이다 — 붙여서 디코드한다."""
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _encrypt(payload: bytes, p256dh: str, auth: str) -> bytes:
    """구독자 공개키로 페이로드를 봉인한다(aes128gcm).

    발송할 때마다 **일회용 키쌍(ephemeral)을 새로 만든다.** 재사용하면 같은 키로
    암호화된 메시지가 쌓여 분석 대상이 되고, 무엇보다 aes128gcm은 (키, salt) 조합이
    겹치면 안 된다. salt는 http_ece가 알아서 만들고 암호문 머리에 넣어준다."""
    return http_ece.encrypt(
        payload,
        private_key=ec.generate_private_key(ec.SECP256R1()),
        dh=_b64url_decode(p256dh),
        auth_secret=_b64url_decode(auth),
        version="aes128gcm",
    )


def _vapid_headers(endpoint: str) -> dict[str, str]:
    """이 endpoint의 푸시 서비스를 수신자로 지정한 서명 헤더.

    `aud`는 **엔드포인트 전체가 아니라 오리진**이어야 한다(RFC 8292). 경로까지 넣으면
    푸시 서비스가 401로 거절한다 — 눈으로는 잘 안 보이는 실수라 여기서 잘라둔다."""
    parts = urlparse(endpoint)
    vapid = Vapid02.from_string(private_key=settings.vapid_private_key)
    return vapid.sign(
        {
            "aud": f"{parts.scheme}://{parts.netloc}",
            "sub": settings.vapid_subject,
            "exp": int(time.time()) + _JWT_TTL_SECONDS,
        }
    )


def send_push(endpoint: str, p256dh: str, auth: str, data: dict) -> None:
    """구독 하나에 알림을 보낸다.

    실패는 두 갈래다:
      - 404/410 → 구독이 영구 무효 → `PushGone` (호출부가 지운다)
      - 그 외 4xx·5xx → 이번에 못 보냈다 → `PushFailed` (호출부가 실패로 센다)

    둘 다 예외로 올린다. 예전엔 뒤쪽을 로그만 남기고 정상 반환했는데, 그러면
    호출부가 성공으로 세서 "N대 성공"이 거짓이 됐다(PushFailed 주석 참고).
    호출부(`_deliver`)가 둘 다 잡으므로 **알림 하나 때문에 글 발행이 실패하지는
    않는다** — 그 방침은 그대로다.
    """
    # 등록 시점에도 막지만 여기서 한 번 더 본다 — 이 검사가 생기기 전에 들어온 행,
    # 또는 DB를 직접 만져 넣은 행이 그대로 나가면 안 된다.
    if not is_allowed_endpoint(endpoint):
        logger.warning("허용되지 않은 푸시 엔드포인트 — 발송하지 않음")
        raise PushGone("허용 목록에 없는 엔드포인트")

    body = _encrypt(json.dumps(data, ensure_ascii=False).encode(), p256dh, auth)
    headers = {
        **_vapid_headers(endpoint),
        "Content-Encoding": "aes128gcm",
        "Content-Type": "application/octet-stream",
        "TTL": str(TTL_SECONDS),
        # 새 글 알림은 즉시성이 필요 없다. normal이면 절전 중인 기기를 깨우지 않고
        # 다음에 깰 때 전달돼 배터리를 덜 쓴다(high는 잠금화면을 즉시 깨운다).
        "Urgency": "normal",
    }
    with httpx.Client(timeout=10.0) as client:
        res = client.post(endpoint, content=body, headers=headers)
    if res.status_code in (404, 410):
        raise PushGone(f"구독 만료 ({res.status_code})")
    if res.status_code >= 400:
        # 본문에 원인이 담겨 오는 경우가 많다(잘못된 서명·payload 초과 등).
        # 엔드포인트는 그 자체가 기기 식별자라 통째로 찍지 않고 오리진만 남긴다.
        origin = urlparse(endpoint).netloc
        logger.warning(
            "푸시 발송 실패 %s: %s %s", origin, res.status_code, res.text[:200]
        )
        raise PushFailed(f"{origin} {res.status_code}")


def notify_new_post_push(post_id: int, post_title: str, author_id: int) -> None:
    """새 글 알림을 '구독 + 알림 켠' 사람들의 모든 기기로 보낸다.

    이메일 알림(services/email.py의 notify_new_post)과 대상 조건이 완전히 같다 —
    같은 의사표시(author_subscriptions.notify)를 읽고 채널만 다르다. 이메일은
    발신 도메인이 없어 스팸함에 꽂히므로, 실제로 닿는 건 이쪽이다.

    푸시 키가 설정 안 됐으면 조용히 아무것도 안 한다(기능 꺼짐)."""
    if not settings.push_enabled:
        return

    # 백그라운드라 요청 세션과 별개로 자체 세션을 연다(email.py와 같은 이유).
    #
    # **조회가 끝나면 세션을 닫고 나서 발송한다.** 예전엔 이 세션을 연 채로 아래
    # 발송 루프를 다 돌아, 기기 N대 × 최대 10초 동안 풀 15칸 중 1칸이
    # `idle in transaction`으로 묶였다. 글 1편 발행이 메일 태스크와 함께 돌므로
    # 한 번의 발행이 2칸을 잡았다. 같은 파일 email.py:157-169는 **이미 반대로**
    # (조회 후 close, 그다음 루프) 하고 있었고 ai.py도 08-10에 같은 이유로 고쳤는데
    # 푸시만 안 쓸려 있었다. (2026-08-11 병목검사)
    db = SessionLocal()
    try:
        subs = db.execute(
            select(
                PushSubscription.id,
                PushSubscription.endpoint,
                PushSubscription.p256dh,
                PushSubscription.auth,
            )
            .join(
                AuthorSubscription,
                AuthorSubscription.subscriber_id == PushSubscription.user_id,
            )
            .join(User, User.id == PushSubscription.user_id)
            .where(
                AuthorSubscription.author_id == author_id,
                AuthorSubscription.approved.is_(True),
                AuthorSubscription.notify.is_(True),
                # 차단된 구독자에게는 보내지 않는다. 2026-08-19 조치는 '차단된 사람의 글이
                # 나가는' 방향만 막았고, **차단된 사람에게 남의 글이 밀려 들어가는** 방향은
                # 그대로였다. 그쪽은 읽기가 404인데도(deps.py의 get_current_user_optional이
                # 차단 계정을 비로그인으로 취급) 구독자 전용 글의 제목과 링크가 기기로 갔다.
                #
                # 조회 조건으로 막는 이유는 PUBLIC_BLOG_ROLES와 같다 — 어느 경로로 차단해도
                # 결과가 같고, 차단을 풀면 알림도 같이 돌아온다. ban_user는 구독·기기 등록을
                # 건드리지 않는다(admin.py) — 지우면 그 '돌아온다'가 성립하지 않는다.
                User.role != BANNED_ROLE,
            )
            # **정렬을 명시한다.** 없으면 순서가 플래너 마음이고, 아래 예산 중단과
            # 겹치면 '어느 기기가 잘리는가'가 설명 불가능해진다. 2026-08-27 훈련에서
            # D=20·D=100 두 회차 모두 **정확히 같은 다섯 대**만 발송됐다.
            .order_by(PushSubscription.id)
        ).all()
    finally:
        # 발송 전에 놓는다 — 아래 루프는 DB가 필요 없다.
        db.close()

    _deliver(
        subs,
        {
            "title": "새 글이 올라왔어",
            "body": post_title,
            # 서비스워커가 알림 클릭 시 열 주소. 절대 경로 대신 앱 라우트를 준다.
            "url": f"/blog/posts/{post_id}",
            # 알림 묶음 키. 같은 tag끼리는 덮어쓴다 — 새 글은 하나로 합쳐도 된다.
            # **종류가 다른 알림과 겹치면 안 된다**(sw.js 주석 참고).
            "tag": "new-post",
        },
        # 글마다 시작점을 돌린다(위 rotate_key 주석). 구독자 전원이 매번 앞머리
        # 다섯 대에 갇히지 않게 하는 유일한 장치다.
        rotate_key=post_id,
    )


def _deliver(
    subs: Sequence[Row[tuple[int, str, str, str]]],
    payload: dict,
    rotate_key: int = 0,
) -> None:
    """구독 목록에 payload를 보내고, 죽은 구독을 정리한다.

    **DB 세션을 안 들고 들어온다.** 호출부가 조회를 끝내고 세션을 닫은 뒤 부른다 —
    발송은 기기 N대 × 최대 10초라, 세션을 쥔 채 돌면 풀(core/database.py) 한 칸이 그동안
    `idle in transaction`으로 묶인다(2026-08-11 병목검사에서 실제로 그랬다).

    `rotate_key`는 **시작점을 돌린다.** 왜 필요한가 — 2026-08-26에 넣은
    `DELIVER_BUDGET_SECONDS`는 벽시계를 기기 수에서 떼어냈지만 **대상은 고정했다.**
    08-27 훈련 실측: 벤더가 무응답일 때 D=20에서도 D=100에서도 발송된 것은 **매번
    목록 앞머리 다섯 대**였다. 장애가 지속되는 동안 뒤쪽 기기는 발행마다 같은 이유로
    건너뛰어진다 — D=100이면 95%가 영구히 못 받는다. 예산이 만든 새 불공정이고,
    예산 자체보다 이쪽이 조용하다(아무 에러도 안 난다).

    글마다 시작점을 돌리면 같은 장애 아래서도 순번이 돌아온다. 키를 **글 id**로 두는
    이유는 같은 글의 재시도가 같은 순서를 밟게 하기 위해서다(시각 기반이면 재시도마다
    대상이 바뀌어 중복 발송이 늘어난다).
    """
    if not subs:
        return
    if rotate_key and len(subs) > 1:
        off = rotate_key % len(subs)
        subs = [*subs[off:], *subs[:off]]
    dead: list[int] = []
    deadline = time.monotonic() + DELIVER_BUDGET_SECONDS
    # **시도와 성공을 가른다.** 예전엔 `sent` 하나였고 예외를 삼킨 뒤에도 증가해서,
    # 로그의 "5/20대에서 중단"이 '5대는 받았다'로 읽혔다. 벤더가 무응답이면 실제
    # 수신은 0대다 — 08-27 훈련에서 그 로그를 근거로 정반대 결론이 날 뻔했다.
    tried = 0
    ok = 0
    failed = 0  # 벤더가 거절했거나 예외가 난 기기 수. tried - ok - gone 과 같다.
    for sub_id, endpoint, p256dh, auth in subs:
        if time.monotonic() > deadline:
            # 예산을 넘기면 남은 기기를 버린다. 알림 몇 개를 못 보내는 것보다
            # 이 루프가 자원을 계속 쥐는 게 나쁘다 — 아래 상수 주석 참고.
            logger.warning(
                "푸시 발송 예산 초과 — %d/%d대 시도(성공 %d대)에서 중단, "
                "남은 기기는 이번 발행을 못 받는다",
                tried,
                len(subs),
                ok,
            )
            break
        tried += 1
        try:
            send_push(endpoint, p256dh, auth, payload)
            ok += 1
        except PushGone:
            dead.append(sub_id)
        except PushFailed:
            # 벤더가 거절했다. 구독은 멀쩡하므로 지우지 않고 실패로만 센다.
            failed += 1
        except Exception:
            # 한 기기 실패가 나머지 발송을 막지 않게(email.py와 같은 방침)
            failed += 1
            logger.exception("푸시 발송 중 예외")

    # 결과를 남긴다. 관리자 화면이 이걸 읽는다(위 _last_delivery 주석).
    # `budget_hit` 이 참이면 남은 기기가 이번 발행을 못 받았다는 뜻이다.
    global _last_delivery
    _last_delivery = {
        "at": datetime.now(UTC).isoformat(),
        # 무엇에 대한 발송이었나. payload 는 이미 화면에 나가는 값이라 여기 담아도
        # 새로 새는 것이 없다(제목·본문 한 줄). 발송 대상의 신원은 안 담는다.
        "kind": payload.get("tag") or "?",
        "title": payload.get("body"),
        "targets": len(subs),
        "tried": tried,
        "ok": ok,
        # 거절당한 기기 수. 이 값이 없던 동안 화면은 `ok < tried` 로만 실패를 알았는데,
        # 거절이 성공으로 세어지고 있었으므로 그 조건이 참이 되는 일이 거의 없었다.
        "failed": failed,
        "gone": len(dead),
        "budget_hit": tried < len(subs),
    }

    # 죽은 구독은 그 자리에서 지운다. 안 지우면 매 발행마다 같은 곳에 던지고
    # 실패하며, 사용자 목록의 '기기 수'도 영원히 틀린 값을 보여준다.
    # 여기서만 세션을 다시 연다 — 발송이 끝난 뒤라 잡는 시간이 짧다.
    if dead:
        db2 = SessionLocal()
        try:
            db2.execute(delete(PushSubscription).where(PushSubscription.id.in_(dead)))
            db2.commit()
            logger.info("만료된 푸시 구독 %d건 정리", len(dead))
        finally:
            db2.close()


def notify_new_comment_push(
    post_id: int, post_title: str, commenter: str, owner_id: int
) -> None:
    """새 댓글을 **글쓴이 본인의 기기**로 알린다.

    새 글 알림과 대상 조건이 다르다. 저쪽은 `author_subscriptions.notify`(남이 나를
    구독하고 알림을 켰는가)를 보지만, 여기서 알릴 사람은 글쓴이 하나다. 자기 글에
    달린 댓글을 받겠다고 자기를 구독할 수는 없으므로, 기기 등록(push_subscriptions)
    자체를 의사표시로 본다. 기기를 등록하지 않았으면 인앱 종에만 남는다.

    댓글 본문은 payload에 넣지 않는다 — 익명 입력이라 잠금화면에 그대로 띄우면
    아무나 남의 잠금화면에 글자를 쓸 수 있게 된다. 누가 어느 글에 달았는지만 알린다.
    """
    if not settings.push_enabled:
        return

    db = SessionLocal()
    try:
        subs = db.execute(
            select(
                PushSubscription.id,
                PushSubscription.endpoint,
                PushSubscription.p256dh,
                PushSubscription.auth,
            )
            .join(User, User.id == PushSubscription.user_id)
            .where(
                PushSubscription.user_id == owner_id,
                # 차단된 글쓴이의 기기로 새 댓글 푸시가 계속 가던 자리. 위 새 글 알림과
                # 같은 누락이다.
                User.role != BANNED_ROLE,
            )
        ).all()
    finally:
        db.close()

    _deliver(
        subs,
        {
            "title": f"{commenter}님이 댓글을 남겼어",
            "body": post_title,
            "url": f"/blog/posts/{post_id}#comments",
            # 글마다 다른 tag. 'new-post'와 겹치면 새 글 알림을 지우고,
            # 글 번호를 안 넣으면 다른 글의 댓글끼리 서로를 지운다.
            "tag": f"comment-{post_id}",
        },
        # 댓글 알림은 대상이 글쓴이 한 사람이라 보통 기기가 한둘이다. 그래도 키를
        # 넘겨둔다 — 기기를 여러 대 등록한 사람에게는 같은 편향이 생긴다.
        rotate_key=post_id,
    )


def _selftest_roundtrip() -> bool:
    """암호화 배선이 맞는지 자체 확인 — 가짜 구독자로 봉인했다가 열어본다.

    브라우저 없이 검증할 수 있는 유일한 지점이라 테스트에서 이걸 쓴다.
    (실제 '알림이 화면에 뜨는가'는 사람이 봐야 한다.)"""
    from cryptography.hazmat.primitives import serialization

    sub_key = ec.generate_private_key(ec.SECP256R1())
    p256dh = base64.urlsafe_b64encode(
        sub_key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
    ).rstrip(b"=").decode()
    auth_secret = os.urandom(16)
    auth = base64.urlsafe_b64encode(auth_secret).rstrip(b"=").decode()

    original = {"title": "새 글이 올라왔어", "body": "한글 제목 확인"}
    sealed = _encrypt(json.dumps(original, ensure_ascii=False).encode(), p256dh, auth)
    opened = http_ece.decrypt(
        sealed, private_key=sub_key, auth_secret=auth_secret, version="aes128gcm"
    )
    return json.loads(opened) == original
