from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    database_url: str = "postgresql://postgres:postgres@localhost:5432/blog"
    secret_key: str = "change-me-in-production"

    # 메일 링크(이메일 인증·비번 재설정)에 넣을 프론트엔드 주소. 프로드는 CloudFront로 교체
    frontend_base_url: str = "http://localhost:5173"

    # 메일 발송 설정 (로컬 기본값은 Mailpit. 프로드는 SES로 교체)
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    mail_from: str = "blog@localhost"
    # SES 같은 인증 SMTP용 (로컬 Mailpit은 빈 값 → 평문/무인증 그대로)
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = False  # SES는 True (587 STARTTLS)

    # 업로드 이미지 URL의 베이스 (프로드는 CloudFront 주소)
    public_base_url: str = "http://localhost:8000"
    # 이미지 저장소: s3_bucket 설정 시 S3에 업로드, 비어있으면 로컬 디스크(로컬 개발)
    s3_bucket: str = ""
    aws_region: str = "ap-northeast-2"

    # AI 글 초안 생성 (Claude API). 키는 .env에만 — 코드/커밋 금지
    anthropic_api_key: str = ""
    # 모델명: 이제 /ai/draft가 요청마다 모델을 받으므로 사실상 미사용(하위호환용 기본값)
    ai_model: str = "claude-sonnet-4-6"
    # BYOK용 암호화 키(Fernet). 사용자가 맡긴 GPT/Gemini 키를 이걸로 암호화해 DB 저장.
    # 비어 있으면 BYOK 비활성(키 저장 불가). 생성: python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"
    llm_encryption_key: str = ""


settings = Settings()
