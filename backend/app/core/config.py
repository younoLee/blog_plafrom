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
    ai_model: str = "claude-sonnet-5"
    # 유저별 '일일' 서버키(Claude) AI 초안 호출 상한 (비용 폭주 방지). BYOK 호출은 제외.
    ai_daily_cap: int = 20
    # 유저별 '월간' 서버키 호출 상한. 일일 캡과 별개의 2차 방어선(매일 조금씩 누적되는 비용 방지).
    ai_monthly_cap: int = 200
    # BYOK용 암호화 키(Fernet). 사용자가 맡긴 GPT/Gemini 키를 이걸로 암호화해 DB 저장.
    # 비어 있으면 BYOK 비활성(키 저장 불가). 생성: python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"
    llm_encryption_key: str = ""

    # 토스페이먼츠 결제 (테스트 모드 기본값 = 토스 공개 문서용 테스트 키).
    # 시크릿키는 서버에서만 사용(프론트 노출 금지). 라이브는 대시보드에서 발급한 실 키로 .env에서 교체.
    # 클라이언트키(프론트)는 VITE_TOSS_CLIENT_KEY로 주입 — 같은 상점의 키 쌍이어야 승인됨.
    toss_secret_key: str = "test_sk_zXLkKEypNArWmo50nX3lmeaxYG5R"
    # Pro 구독 1회 결제 금액(원). 서버가 이 금액으로 주문을 만들고 승인 시 위변조를 검증한다.
    pro_price_krw: int = 9900
    # 구독 유지 기간(일). 결제 승인 시 pro_until = now + 이 일수. 지나면 자동으로 is_pro off.
    pro_days: int = 30
    # 운영 안전장치: True면 시크릿키가 test_로 시작할 때 결제 승인을 거부(Pro 안 켬).
    # 운영 .env에서 True로 두면 "테스트 키 방치 → 공짜 Pro" 사고를 원천 차단.
    # 로컬/데모는 기본 False라 테스트 키로 계속 흐름 확인 가능.
    payments_require_live: bool = False


settings = Settings()
