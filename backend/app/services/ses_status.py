"""수신 주소가 SES에 검증돼 있는지 확인한다.

**왜 이게 '주소가 실재하는가'의 답이 되나** — SES 검증은 AWS가 그 주소로 확인
메일을 보내고 **주소 주인이 링크를 눌러야** 끝난다. 그러니 검증됨은 곧
'그 주소가 실재하고, 그 사람이 메일함을 연다'는 뜻이다. 우리 앱이 못 보내는
주소에도 AWS는 보낼 수 있어서(확인 메일은 샌드박스 제한을 안 받는다) 이 경로가 성립한다.

초대제에서 이게 필요한 이유: 가입자는 주소를 못 고르고 관리자가 정한다. 그래서
오타나 남의 주소가 들어가도 **아무도 못 알아챈다** — 메일을 한 통도 안 보내는
설계라 침묵으로 지나간다. 발급 화면에서 미리 알려주는 게 유일한 방어다.

**모르면 모른다고 한다.** 권한이 없거나 자격증명이 없으면 None을 돌려주고,
화면은 아무 말도 하지 않는다. '확인 못 함'을 '문제 있음'으로 바꿔 경고하면
늑대 소년이 되고, 진짜 경고까지 무시하게 된다.
"""
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)


def recipient_status(email: str) -> dict:
    """{'sandbox': bool|None, 'verified': bool|None}

    sandbox=False(프로덕션 액세스)면 수신자 검증이 아예 의미 없으므로,
    호출부는 verified를 무시하고 경고를 띄우지 않아야 한다.
    """
    result: dict = {"sandbox": None, "verified": None}
    try:
        import boto3
        from botocore.config import Config
        from botocore.exceptions import BotoCoreError, ClientError

        # **타임아웃을 반드시 준다.** 이 호출은 초대 발급 응답 경로에 있고, 그 응답에만
        # 원문 토큰이 실린다. botocore 기본값은 연결·읽기 각 60초에 재시도까지 붙어
        # CloudFront의 오리진 타임아웃(60초)을 넘긴다 — 그러면 초대는 DB에 커밋됐는데
        # 링크는 504와 함께 사라진다. 호출부의 try/except는 예외를 잡지 그 위에서
        # 벌어지는 지연을 잡지 못하므로, 여기서 시간을 끊는 것 말고는 방법이 없다.
        ses = boto3.client(
            "sesv2",
            region_name=settings.aws_region,
            config=Config(
                connect_timeout=2, read_timeout=3, retries={"max_attempts": 1}
            ),
        )

        try:
            account = ses.get_account()
            result["sandbox"] = not account.get("ProductionAccessEnabled", False)
        except (BotoCoreError, ClientError) as e:
            # 권한이 없을 수 있다(EC2 역할엔 s3:PutObject뿐이었다). 조용히 모름 처리.
            logger.info("SES 계정 상태를 못 읽음: %s", type(e).__name__)
            return result

        # 프로덕션이면 아무 주소로나 보낼 수 있으므로 검증 여부를 볼 이유가 없다.
        if result["sandbox"] is False:
            return result

        try:
            identity = ses.get_email_identity(EmailIdentity=email)
            result["verified"] = bool(identity.get("VerifiedForSendingStatus", False))
        except ClientError as e:
            # NotFoundException = 등록조차 안 된 주소 → 확실히 '미검증'이다.
            # 그 외(권한 등)는 모름으로 남긴다 — 둘을 섞으면 안 된다.
            if e.response.get("Error", {}).get("Code") == "NotFoundException":
                result["verified"] = False
            else:
                logger.info("SES 주소 상태를 못 읽음: %s", type(e).__name__)
        except BotoCoreError as e:
            logger.info("SES 주소 상태를 못 읽음: %s", type(e).__name__)
    except Exception:
        # boto3 미설치·설정 오류 등. 초대 발급 자체를 막으면 안 되므로 삼킨다.
        logger.exception("SES 상태 확인 실패")
    return result
