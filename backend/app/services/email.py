import logging
import smtplib
from email.message import EmailMessage
from html import escape as html_escape

from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.author_subscription import AuthorSubscription
from app.models.user import User

logger = logging.getLogger(__name__)

# SMTP 소켓 타임아웃(초). **인자를 빼면 socket 기본값 = 무한 대기다**
# (socket.setdefaulttimeout도 이 앱 어디에서도 안 부른다).
#
# 왜 무는가: send_email은 전부 BackgroundTask에서 불리고, BackgroundTask의 sync 함수는
# Starlette이 threadpool에서 돌린다. 무한 대기가 걸리면 그 스레드는 **재시작 전까지
# 안 돌아온다** — 40칸짜리 풀에서 한 칸이 영구히 사라진다. 자연 복구가 없다.
# notify_new_post는 수신자마다 연결을 새로 여니 N명이면 N번의 기회다.
#
# 10초인 이유: services/status.py의 메일 점검은 3초를 쓰는데 그건 connect+STARTTLS+login까지의
# **생존 확인**이고 본문이 없다. 실제 발송은 DATA(본문 전송 + 250 대기)가 더 붙는다.
# 본문은 수 KB고 SES의 250 응답은 통상 1초 미만이라 10초면 약 10배 여유다.
# 여기는 요청 경로가 아니라서 CloudFront 60초 예산과 무관하다 — 지켜야 할 건
# '스레드풀 슬롯이 반드시 돌아온다' 하나뿐이다. (2026-08-10 심층검사)
SMTP_TIMEOUT = 10


def _background_send(kind: str, **kw) -> None:
    """BackgroundTask에서 부르는 발송의 유일한 출구. **예외를 여기서 로그로 만든다.**

    왜 필요한가 — BackgroundTask는 응답을 **다 보낸 뒤에** 돈다. 그래서 여기서 예외가 나도
    사용자는 이미 202 "재설정 링크를 보냈어"를 받은 뒤고, 서버 로그에는 처리되지 않은
    트레이스백만 남는다. 이 저장소가 이미 실측해 적어둔 그대로다(routers/subscribers.py의
    폐지 사유: "메일 서버를 죽여놓고 호출 → HTTP 200, 로그엔 처리 안 된 트레이스백만").
    그때 그 라우터는 없앴는데 **같은 병이 forgot-password에 남아 있었다** — 그리고 가입이
    초대제로 닫혀 있어서 그게 지금 살아 있는 유일한 발송 경로다.

    **이게 메일을 도착시키지는 않는다.** 재시도도 영속 큐도 아니다(프로세스가 죽으면 대기
    중이던 태스크는 그대로 유실된다 — 인메모리 큐다). '조용한 실패'를 '읽을 수 있는 실패'로
    바꾸는 것까지다. 진짜 재시도는 별개의 판단이라 여기 안 넣는다.

    수신 주소를 로그에 남긴다. 이 저장소는 보통 원문 대신 지문을 남기지만, 여기선 '어느
    주소가 실패했나'가 곧 조치 그 자체라 지우면 로그가 쓸모없어진다. SES 샌드박스라 대상
    주소는 어차피 유한하고 콘솔에 다 적혀 있다.
    """
    try:
        send_email(**kw)
    except Exception:
        logger.exception(
            "메일 발송 실패 (kind=%s to=%s) — 사용자는 이미 성공 응답을 받았다",
            kind,
            kw.get("to"),
        )



def send_email(to: str, subject: str, body: str, html: str | None = None) -> None:
    msg = EmailMessage()
    msg["From"] = settings.mail_from
    msg["To"] = to
    # 제목엔 사용자 입력(글 제목)이 들어갈 수 있음 → 개행 제거(메일 헤더 인젝션·발송실패 방어)
    msg["Subject"] = subject.replace("\r", " ").replace("\n", " ")
    msg.set_content(body)  # 평문 폴백
    if html is not None:
        # HTML 버전 추가 → 메일 클라이언트가 클릭 가능한 링크/버튼으로 렌더
        msg.add_alternative(html, subtype="html")
    # 로컬 Mailpit = 평문/무인증, 프로드 SES = STARTTLS + 로그인 (config로 분기)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=SMTP_TIMEOUT) as smtp:
        if settings.smtp_use_tls:
            smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(msg)


def _action_html(intro: str, link: str, button_label: str) -> str:
    """클릭 버튼 + 복사용 전체 URL이 들어간 공통 HTML 본문."""
    return f"""\
<div style="font-family:-apple-system,sans-serif;line-height:1.6;color:#1d1d1f">
  <p>{intro}</p>
  <p style="margin:20px 0">
    <a href="{link}" style="display:inline-block;padding:12px 22px;background:#0071e3;
       color:#fff;border-radius:980px;text-decoration:none;font-weight:600">{button_label}</a>
  </p>
  <p style="color:#666;font-size:13px">버튼이 안 눌리면 아래 주소를 복사해 브라우저에 붙여넣어줘:</p>
  <p style="word-break:break-all;font-size:13px"><a href="{link}">{link}</a></p>
  <p style="color:#999;font-size:12px;margin-top:24px">본인이 요청한 게 아니면 이 메일은 무시하면 돼.</p>
</div>"""


def send_verification_email(to: str, link: str) -> None:
    """가입 시 이메일 인증 링크 발송."""
    _background_send(
        "verify",
        to=to,
        subject="[블로그] 이메일 인증을 완료해줘",
        body=(
            "가입을 완료하려면 아래 링크를 열어줘 (24시간 안에):\n\n"
            f"{link}\n\n"
            "본인이 가입한 게 아니면 이 메일은 무시하면 돼."
        ),
        html=_action_html("가입을 완료하려면 아래 버튼을 눌러줘 (24시간 안에).", link, "이메일 인증하기"),
    )


def send_already_registered_email(to: str, login_link: str) -> None:
    """이미 가입·인증된 이메일로 또 가입 시도가 들어왔을 때 안내.
    계정 존재 여부를 HTTP 응답으로는 노출하지 않으려고 '메일로만' 알린다."""
    _background_send(
        "already_registered",
        to=to,
        subject="[블로그] 이미 가입된 계정이야",
        body=(
            "이 이메일로 회원가입 시도가 있었는데, 이미 가입된 계정이야.\n\n"
            "본인이라면 로그인하거나, 비밀번호를 잊었으면 '비밀번호 찾기'를 이용해줘:\n"
            f"{login_link}\n\n"
            "본인이 한 게 아니면 이 메일은 무시해도 돼 (계정은 안전해)."
        ),
        html=_action_html(
            "이 이메일로 회원가입을 시도했는데, 이미 가입된 계정이야. 로그인하거나 비밀번호 찾기를 이용해줘.",
            login_link,
            "로그인하러 가기",
        ),
    )


def send_reset_email(to: str, link: str) -> None:
    """비밀번호 재설정 링크 발송."""
    _background_send(
        "reset",
        to=to,
        subject="[블로그] 비밀번호 재설정",
        body=(
            "비밀번호를 재설정하려면 아래 링크를 열어줘 (1시간 안에):\n\n"
            f"{link}\n\n"
            "본인이 요청한 게 아니면 이 메일은 무시하면 돼 (비번은 그대로야)."
        ),
        html=_action_html("비밀번호를 재설정하려면 아래 버튼을 눌러줘 (1시간 안에).", link, "비밀번호 재설정"),
    )


# send_subscribe_confirm_email은 2026-07-31에 제거됐다. 뉴스레터 구독 폐지와 함께
# 사라진 유일한 '임의 주소 발송' 경로였다(routers/subscribers.py의 폐지 사유 참고).
# 이제 이 모듈이 보내는 메일은 전부 **등록된 계정 주소**로만 간다:
#   가입 인증·이미 가입됨(초대제라 사실상 잠김) · 비번 재설정 · 새 글 알림
# 그래서 SES 샌드박스(검증된 주소로만 발송)에서도 검증 대상이 유한하다.


def notify_new_post(post_id: int, post_title: str, author_id: int) -> None:
    """글쓴이가 새 글을 쓰면, 그 글쓴이를 '구독 + 알림 켠' 사람들의 계정 이메일로 발송.
    (전역 뉴스레터를 없애고 글쓴이별 알림으로 통일 — 2026-07-18)"""
    # 백그라운드라 요청 세션과 별개로 자체 세션을 연다
    db = SessionLocal()
    try:
        # author를 '승인된' 구독으로 갖고 notify=True로 켠 사용자들의 계정 이메일
        emails = db.scalars(
            select(User.email)
            .join(AuthorSubscription, AuthorSubscription.subscriber_id == User.id)
            .where(
                AuthorSubscription.author_id == author_id,
                AuthorSubscription.approved.is_(True),
                AuthorSubscription.notify.is_(True),
            )
        ).all()
    finally:
        db.close()

    # 절대 URL + 실제 라우트(/blog/posts/{id})로 (예전엔 상대경로 /posts/{id}라 링크가 깨졌음)
    link = f"{settings.frontend_base_url}/blog/posts/{post_id}"
    text = f"새 글이 올라왔어!\n\n제목: {post_title}\n\n읽으러 가기:\n{link}"
    # 제목은 사용자 입력 → HTML 이스케이프(메일 HTML 인젝션 방지)
    safe_title = html_escape(post_title)
    html = _action_html(f"새 글이 올라왔어: <b>{safe_title}</b>", link, "글 보러 가기")
    for email in emails:
        try:
            send_email(
                to=email,
                subject=f"[블로그] 새 글: {post_title}",
                body=text,
                html=html,
            )
        except Exception:
            # 한 수신자 실패(예: SES 미인증 주소)가 나머지 발송을 막지 않게
            continue
