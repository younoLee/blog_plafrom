import smtplib
from email.message import EmailMessage
from html import escape as html_escape

from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.subscriber import Subscriber


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
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as smtp:
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
    send_email(
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
    send_email(
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
    send_email(
        to=to,
        subject="[블로그] 비밀번호 재설정",
        body=(
            "비밀번호를 재설정하려면 아래 링크를 열어줘 (1시간 안에):\n\n"
            f"{link}\n\n"
            "본인이 요청한 게 아니면 이 메일은 무시하면 돼 (비번은 그대로야)."
        ),
        html=_action_html("비밀번호를 재설정하려면 아래 버튼을 눌러줘 (1시간 안에).", link, "비밀번호 재설정"),
    )


def send_subscribe_confirm_email(to: str, link: str) -> None:
    """구독 더블옵트인: 본인이 직접 신청했는지 확인하는 링크 발송."""
    send_email(
        to=to,
        subject="[블로그] 구독 확인",
        body=(
            "이 블로그 새 글 알림을 구독하려면 아래 링크를 열어줘 (24시간 안에):\n\n"
            f"{link}\n\n"
            "본인이 신청한 게 아니면 이 메일은 무시하면 돼 (구독은 진행되지 않아)."
        ),
        html=_action_html(
            "이 블로그 새 글 알림을 구독하려면 아래 버튼을 눌러줘 (24시간 안에).",
            link,
            "구독 확인하기",
        ),
    )


def notify_new_post(post_id: int, post_title: str) -> None:
    """새 글 작성 시 '확인된' 구독자에게만 알림 메일 발송 (백그라운드 실행)."""
    # 백그라운드라 요청 세션과 별개로 자체 세션을 연다
    db = SessionLocal()
    try:
        # confirmed=True인 구독자만 → 더블옵트인 핵심 방어선
        # (남이 무단등록한 미확인 이메일에는 절대 발송 안 됨)
        emails = db.scalars(
            select(Subscriber.email).where(Subscriber.confirmed.is_(True))
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
