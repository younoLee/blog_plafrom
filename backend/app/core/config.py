from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    database_url: str = "postgresql://postgres:postgres@localhost:5432/blog"
    secret_key: str = "change-me-in-production"

    # 메일 발송 설정 (로컬 기본값은 Mailpit. 나중에 AWS SES 주소로 교체)
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    mail_from: str = "blog@localhost"

    # 업로드 이미지 URL의 베이스 (나중에 S3/CloudFront 주소로 교체)
    public_base_url: str = "http://localhost:8000"

    # AI 글 초안 생성 (Claude API). 키는 .env에만 — 코드/커밋 금지
    anthropic_api_key: str = ""
    # 모델명: .env에서 바꾸면 바로 교체됨 (예: claude-haiku-4-5 로 저비용)
    ai_model: str = "claude-opus-4-8"


settings = Settings()
