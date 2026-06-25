import smtplib
from email.message import EmailMessage

from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.subscriber import Subscriber


def send_email(to: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = settings.mail_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    # Mailpit은 인증/TLS 없이 평문 SMTP. (SES로 갈 땐 인증·TLS 추가)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as smtp:
        smtp.send_message(msg)


def send_verification_email(to: str, link: str) -> None:
    """가입 시 이메일 인증 링크 발송."""
    send_email(
        to=to,
        subject="[블로그] 이메일 인증을 완료해줘",
        body=(
            "가입을 완료하려면 아래 링크를 눌러줘 (24시간 안에):\n\n"
            f"{link}\n\n"
            "본인이 가입한 게 아니면 이 메일은 무시하면 돼."
        ),
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
