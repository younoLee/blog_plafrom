import smtplib
from email.message import EmailMessage

from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.subscriber import Subscriber


def send_email(to: str, subject: str, body: str, html: str | None = None) -> None:
    msg = EmailMessage()
    msg["From"] = settings.mail_from
    msg["To"] = to
    msg["Subject"] = subject
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


def notify_new_post(post_id: int, post_title: str) -> None:
    """새 글 작성 시 구독자 전원에게 알림 메일 발송 (백그라운드 실행)."""
    # 백그라운드라 요청 세션과 별개로 자체 세션을 연다
    db = SessionLocal()
    try:
        emails = db.scalars(select(Subscriber.email)).all()
    finally:
        db.close()

    for email in emails:
        send_email(
            to=email,
            subject=f"[블로그] 새 글: {post_title}",
            body=f"새 글이 올라왔어!\n\n제목: {post_title}\n\n읽으러 가기: /posts/{post_id}",
        )
