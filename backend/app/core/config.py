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

    # --- Web Push (VAPID) ---
    #
    # 왜 붙였나 — 이메일 알림이 사실상 안 닿는다. 발신 도메인이 없어(MAIL_FROM이
    # gmail.com) SPF·DKIM 정렬이 깨지고 받는 쪽이 스팸함으로 보낸다. 푸시는 SES를
    # 안 거치므로 그 사슬 밖에 있다.
    #
    # 키는 `python scripts/gen_vapid_keys.py`로 만들어 .env에 넣는다. **공개키는
    # 브라우저에 그대로 나가는 값이라 비밀이 아니고**, 개인키는 비밀이다.
    #
    # 비어 있으면 푸시 기능 전체가 꺼진다(구독 엔드포인트 503, 발송은 무동작).
    # 켜지 않아도 앱이 그대로 도는 게 요점 — AI 키가 없을 때와 같은 방식이다.
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    # 푸시 서비스가 문제 발생 시 연락할 곳. mailto: 또는 https: 여야 한다(RFC 8292).
    vapid_subject: str = "mailto:admin@example.com"

    @property
    def push_enabled(self) -> bool:
        return bool(self.vapid_public_key and self.vapid_private_key)

    # 업로드 이미지 URL의 베이스 (프로드는 CloudFront 주소)
    public_base_url: str = "http://localhost:8000"
    # 이미지 저장소: s3_bucket 설정 시 S3에 업로드, 비어있으면 로컬 디스크(로컬 개발)
    s3_bucket: str = ""
    aws_region: str = "ap-northeast-2"

    # AI 글 초안 생성 (Claude API). 키는 .env에만 — 코드/커밋 금지
    anthropic_api_key: str = ""
    # 모델명: 이제 /ai/draft가 요청마다 모델을 받으므로 사실상 미사용(하위호환용 기본값)
    ai_model: str = "claude-sonnet-5"
    # 유저별 '시간당' 초안 '시도' 상한 (남용/DoS 방어). BYOK도 포함하고 실패도 센다.
    # slowapi의 인메모리 10/hour와 같은 값이지만 이쪽은 DB라 재시작을 견딘다(2중 방어).
    ai_hourly_cap: int = 10
    # 유저별 '일일' 서버키(Claude) AI 초안 호출 상한 (비용 폭주 방지). BYOK 호출은 제외.
    ai_daily_cap: int = 20
    # 유저별 '월간' 서버키 호출 상한. 일일 캡과 별개의 2차 방어선(매일 조금씩 누적되는 비용 방지).
    ai_monthly_cap: int = 200
    # **서비스 전체** 일일 상한. 위 캡들은 전부 유저별이라 계정이 늘면 총액에는 상한이
    # 없었다(2026-08-11 공백검사). Anthropic 청구는 AWS 밖이라 AWS Budgets가 못 본다.
    # 60 = 지금 계정 수(한 자리)에 여유를 크게 준 값이다. 정상 운영에선 절대 안 닿고,
    # 닿았다면 그 자체가 '뭔가 잘못됐다'는 신호다 — 그때 로그에 경고가 남는다.
    ai_daily_cap_global: int = 60
    # **서비스 전체** 일일 토큰 상한(입력+출력). 위 횟수 상한이 '몇 번'을 막는다면
    # 이건 '얼마나'를 막는다 — 실제 청구에 비례하는 건 이쪽이다.
    # 60만 = 초안 한 편이 대략 입력 1~2천 + 출력 2.5~8천 토큰이니, 상위 모델로만
    # 채워도 60회 언저리다(위 횟수 상한과 대략 같은 지점에서 만난다).
    # 둘 다 두는 이유: 토큰은 호출 뒤에야 알 수 있어 한 호출만큼 넘칠 수 있고,
    # 벤더가 usage를 안 주면 0으로 남는다 — 그때 횟수 상한이 받쳐준다.
    ai_daily_token_cap_global: int = 600_000
    # 유저별 '시간당' AI 가드 위반 상한. 넘으면 그 시간 창 동안 초안 생성을 막는다.
    # 3인 이유: 정상 사용자는 평생 0이다(가드는 형식 이탈·프롬프트 유출에만 걸린다).
    # 인젝션은 문구를 바꿔가며 반복하는 시행착오라, 그 반복을 비싸게 만드는 게 목적이다.
    # 모델이 어쩌다 형식을 흘리는 우발적 위반에 여유를 주려고 1이 아니라 3으로 둔다.
    ai_guard_violation_cap: int = 3
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

    # **열린** 가입을 열지 여부. 기본 False = 닫힘.
    # 프론트에서 가입 폼을 지워도 이 라우트가 열려 있으면 누구나 직접 POST해 아무 주소로
    # 인증메일을 보내게 할 수 있다(SES 하드바운스 누적 → 발송정지). 그래서 백엔드에서 닫는다.
    # 이게 바로 초대제 전환의 진짜 목적 — 프론트만 고치면 목적을 하나도 못 이룬다.
    #
    # 이 값이 False여도 계정은 만들어진다. 두 경로가 있고 **둘 다 이 플래그와 무관**하다:
    #   1) 초대 링크 — 관리자가 발급, 받은 사람이 소각(routers/auth.py의 redeem_invite).
    #      2026-08-07에 추가되기 전까지 '초대제'는 403 메시지일 뿐 절차가 없었다.
    #   2) backend/scripts/create_user.py — 관리자/데모 계정용 오프라인 스크립트.
    # 즉 False가 막는 건 '아무나 스스로 가입하는 것' 하나다.
    allow_signup: bool = False

    # X-Forwarded-For에서 뒤에서 몇 번째를 '진짜 클라 IP'로 볼지 = 신뢰하는 프록시 홉 수.
    # 각 신뢰 프록시가 관측한 IP를 XFF 뒤에 하나씩 덧붙이므로, 클라가 위조해 넣은 앞쪽 값은
    # 뒤에서 hops번째에 닿지 못한다. 현행(CloudFront→EC2)=1. ECS(CloudFront→ALB→task)=2로
    # 태스크 env에서 올린다. 틀리면 레이트리밋이 클라가 아니라 엣지 IP를 키로 잡아 무력화된다.
    trusted_proxy_hops: int = 1

    # 오리진 공유 시크릿. CloudFront가 오리진 요청에 X-Origin-Secret로 붙이는 값과 같아야
    # 한다(terraform/variables.tf의 origin_secret). 안 맞으면 main.py의 미들웨어가 403.
    #
    # 왜 필요한가 — 오리진 SG는 'CloudFront 엣지 전체'를 받는다. 공격자가 자기 배포를
    # 만들어 우리 오리진을 가리키면 SG를 통과하고, 그러면 WAF·CSP·요청크기 함수를 전부
    # 우회한 채 /api/*를 때릴 수 있다. 이 값이 '우리 배포를 거쳐 왔다'는 유일한 증거다.
    #
    # 비면 검사를 건너뛴다(fail open). 그래야 로컬 개발이 돌고, 켤 때 CloudFront에 먼저
    # 헤더를 붙인 뒤 백엔드를 올리는 순서가 성립한다 — 순서를 뒤집으면 /api/*가 통째로
    # 막힌다(밖에서는 403이 아니라 200+HTML로 보인다. 이유는 main.py 미들웨어 주석 참고).
    # fail open이 맞는 이유: 이건 인증이 아니라 '엣지 우회 차단'이고, 진짜 인증(JWT)과
    # 권한 검사는 이것과 무관하게 라우터에서 그대로 돈다.
    #
    # **단, 그 fail open은 요청 시점 얘기고 프로드에서는 기동을 막는다.**
    # 프로드(PUBLIC_BASE_URL이 https)에서 이 값이 비면 main.py의 lifespan이 RuntimeError로
    # 죽는다 — 요청마다 403을 내는 것과는 다른 얘기다. 비어 있는 프로드는 '우회 차단이
    # 꺼진 줄 모르고 도는' 상태이고 밖에서 아무 신호도 안 난다(2026-08-11).
    origin_secret: str = ""


settings = Settings()
