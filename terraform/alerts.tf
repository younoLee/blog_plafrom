# AWS 네이티브 알림 — 인스턴스가 통째로 죽는 경우를 몇 분 안에 안다.
#
# 왜 필요한가 — 감시는 이미 있다(`scripts/watch.sh` + 매시 도는 GitHub Actions).
# 그건 **바깥에서** 보기 때문에 "EC2는 running인데 공개 API가 죽었다"라는 조합을
# 잡아낸다. AWS 안에서는 못 보는 것이라 그 설계는 그대로 옳다.
#
# 다만 주기가 1시간이다. 하드웨어·하이퍼바이저 문제로 인스턴스가 통째로 죽으면
# 최악의 경우 59분을 모른다. 이건 바깥에서 볼 필요가 없는 종류의 고장이라
# AWS가 1분마다 이미 재고 있는 신호(StatusCheckFailed)를 그냥 받아쓰면 된다.
# 둘은 경쟁하지 않는다 — **보는 층이 다르다.**
#
# 비용: CloudWatch 알람 10개까지 무료, SNS 이메일 알림 월 1,000건까지 무료.
# 이 파일은 알람 1개 + 토픽 1개라 무료 티어 안에 있다.

variable "alert_email" {
  description = "운영 알림을 받을 주소. 비우면 토픽만 만들고 구독은 만들지 않는다."
  type        = string
  default     = ""

  # 값은 terraform.tfvars(gitignore됨)에 둔다 — `ssh_cidr`·`origin_secret`과 같은 패턴이다.
  # 공개 저장소에 주소를 박으면 수집당한다. 기본값을 비워두는 쪽을 택한 이유는 또 있다:
  # 필수 변수로 만들면 값이 없을 때 **모든 apply가 죽는다**. 그건 재해 복구 한복판에서
  # 첫 삽이 안 들어가는 것이고, `backend_image_tag`가 2026-07-27에 정확히 그 사고를 냈다.
}

resource "aws_sns_topic" "alerts" {
  name = "blog-alerts"
  # KMS 암호화는 안 건다 — 고객관리형 키가 월 $1이고, 이 토픽에 흐르는 건
  # "인스턴스 상태검사가 실패했다"뿐이라 비밀이 아니다. 값을 정직하게 매긴다.
}

# ⚠️ **이 정책이 없으면 AWS가 기본 정책을 붙이는데, 그게 위험하다.**
#
# 2026-08-10 보안검사에서 라이브 값을 떠보니 기본 정책은 이랬다:
#   Principal: {"AWS": "*"}  /  Condition: AWS:SourceOwner = 이 계정
#   Action: Publish · DeleteTopic · Subscribe · AddPermission · RemovePermission · …
# 같은 계정 안에서는 신원 정책 **또는** 리소스 정책 중 하나만 허용해도 통과한다.
# 즉 계정 안의 **모든 주체**가 이 토픽을 지우거나 가짜 알림을 발행할 수 있었다 —
# 공개 저장소의 Actions가 OIDC로 맡는 github-actions-blog-deploy 역할 포함.
# `aws iam simulate-principal-policy`로 실증했다: Publish·DeleteTopic 둘 다
# **allowed (Resource Policy)**.
#
# 이건 iam-github-oidc.tf가 정확히 반대로 추론한 자리다. 거기서 감시 역할의
# `sns:ListSubscriptionsByTopic`을 토픽 하나로 좁힌 이유가 "오염된 액션이 계정의 모든
# 토픽 구독 주소를 읽는 것"이었는데, **같은 오염된 액션이 그 토픽을 통째로 지워
# 상태검사 알람의 전달 경로를 끊을 수 있었다.** 폭발 반경을 신원 정책 쪽에서만 쟀다.
#
# 토픽이 지워지면 아래 알람은 죽은 ARN을 가리킨 채 조용히 아무에게도 안 간다.
# (watch.sh 6-B가 ListSubscriptionsByTopic 실패로 잡긴 하지만 그건 최대 한 시간 뒤다.)
#
# 그래서 Principal을 둘로 좁힌다:
#   ① CloudWatch 서비스 주체 — 알람이 실제로 발행하는 주체다. SourceArn으로 이 계정의
#      알람만 허용해 confused-deputy를 막는다.
#   ② 계정 루트 — IAM 신원 정책으로 위임하는 표준 형태. 운영자(IAM_cli)가 콘솔·CLI로
#      구독을 확인하거나 토픽을 관리하는 경로가 여기로 유지된다.
# 배포 역할에는 신원 정책에 sns Publish/Delete가 없으므로 이제 둘 다 막힌다.
resource "aws_sns_topic_policy" "alerts" {
  arn = aws_sns_topic.alerts.arn

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowCloudWatchAlarmsToPublish"
        Effect    = "Allow"
        Principal = { Service = "cloudwatch.amazonaws.com" }
        Action    = "SNS:Publish"
        Resource  = aws_sns_topic.alerts.arn
        Condition = {
          ArnLike = { "aws:SourceArn" = "arn:aws:cloudwatch:ap-northeast-2:${data.aws_caller_identity.current.account_id}:alarm:*" }
        }
      },
      {
        # 운영자 경로. 계정 루트에 위임하면 그 계정의 IAM 신원 정책이 최종 판정을 한다
        # — 즉 "누가 할 수 있나"가 iam-*.tf 한 곳에서만 결정된다. 기본 정책처럼
        # 리소스 정책이 신원 정책을 **우회**하던 구조를 없애는 게 이 문의 요점이다.
        Sid       = "AllowAccountOwnerManage"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root" }
        Action = [
          "SNS:GetTopicAttributes",
          "SNS:SetTopicAttributes",
          "SNS:ListSubscriptionsByTopic",
          "SNS:Subscribe",
          "SNS:Publish",
          "SNS:DeleteTopic",
        ]
        Resource = aws_sns_topic.alerts.arn
      },
    ]
  })
}

# 이메일 구독은 **받는 사람이 확인 메일의 링크를 눌러야** 활성화된다.
# 누르기 전까지 상태는 PendingConfirmation이고, 그동안 알람은 울려도 아무에게도 안 간다.
# 그 상태를 눈으로 기억하지 않으려고 watch.sh가 매시 확인한다(6-B 검사).
resource "aws_sns_topic_subscription" "alerts_email" {
  count     = var.alert_email != "" ? 1 : 0
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email

  # terraform은 확인 여부를 관리하지 못한다(사람이 메일에서 누르는 일이라).
  # 그래서 apply 직후 상태가 PendingConfirmation이어도 plan은 조용하다.
  lifecycle {
    ignore_changes = [confirmation_timeout_in_minutes]
  }
}

# ── EC2 상태검사 ─────────────────────────────────────────────────────────────
#
# StatusCheckFailed는 둘의 합이다:
#   · System   — AWS 쪽 문제(하이퍼바이저·네트워크·전원). 인스턴스를 옮겨야 낫는다.
#   · Instance — 게스트 쪽 문제(커널 패닉, 파일시스템 손상, 네트워크 설정 붕괴).
# 합을 보는 이유는 이 서버에서는 대응이 같기 때문이다 — 어느 쪽이든 사람이 봐야 한다.
#
# **treat_missing_data가 이 알람의 핵심이다.** 이 서버는 대부분 꺼져 있고, 꺼진
# 인스턴스는 상태검사 지표를 아예 발행하지 않는다. 기본값(missing)으로 두면 알람이
# INSUFFICIENT_DATA로 떠 있게 되고, 그건 '고장'과 '꺼둠'을 구분 못 하는 신호다.
# 이 저장소가 반복해 배운 것 — 끌 때마다 울리는 알람은 아무도 안 보는 알람이 된다
# (watch.sh를 CloudWatch가 아니라 GitHub Actions로 만든 이유도 정확히 이것이었다).
resource "aws_cloudwatch_metric_alarm" "ec2_status_check" {
  alarm_name        = "blog-ec2-status-check-failed"
  alarm_description = "EC2 상태검사 실패(2분 연속). 인스턴스가 꺼져 있을 때는 울리지 않는다."

  namespace   = "AWS/EC2"
  metric_name = "StatusCheckFailed"
  dimensions  = { InstanceId = aws_instance.backend.id }

  # 1분 간격 × 2회 연속. 1회로 하면 재부팅 같은 짧은 구간에도 울린다.
  period              = 60
  evaluation_periods  = 2
  statistic           = "Maximum" # 0=정상 / 1=실패. 평균을 쓰면 한쪽만 실패했을 때 묻힌다.
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  treat_missing_data  = "notBreaching" # 꺼져 있음 ≠ 고장 (위 주석)

  alarm_actions = [aws_sns_topic.alerts.arn]

  # **`ok_actions`는 일부러 두지 않는다.** 처음엔 "복구도 알려야 지금 어떤 상태인지가
  # 닫힌다"며 넣었는데, `notBreaching`과 겹치면 거짓말을 한다:
  # 진짜 고장으로 ALARM이 뜬 뒤 조사하려고 인스턴스를 끄면 지표가 끊기고, 끊긴 구간이
  # '정상'으로 평가돼 ALARM → OK 전이가 난다 → **서버는 죽은 채로 "복구됨" 메일이 간다.**
  #
  # 가설이 아니다. 만든 첫날 이력에 그대로 찍혔다(2026-08-09 코드검사가 잡았다):
  #     2026-08-09T18:47:46+09:00  Alarm updated from INSUFFICIENT_DATA to OK
  # 인스턴스는 그때 stopped였고 상태검사가 정상으로 관측된 적이 한 번도 없었다.
  #
  # 근본 원인은 **OK가 뜻이 둘이라는 것**이다 — `notBreaching`에서 OK는 '정상'과
  # '꺼둠'을 합친 상태다. 뜻이 둘인 값으로 메일을 보내면 받는 쪽이 가릴 수 없다.
  # (`treat_missing_data = "missing"`으로 바꾸면 이 거짓말은 없어지지만, 이번엔
  #  켤 때마다 INSUFFICIENT_DATA → OK 전이가 나서 **부팅할 때마다 메일**이 온다.
  #  이 조합에서 '정직하면서 조용한 OK 메일'은 만들 수 없다.)
  #
  # 반대로 ALARM은 거짓말을 못 한다 — **실제 데이터포인트 2개 연속**이 실패를
  # 보고해야 뜨므로, 인스턴스가 켜져 있고 진짜 고장일 때만이다. 알람의 값은 전부 거기 있다.
  #
  # 복구는 **확인된 뒤에 드러나게** 한다: watch.sh 6-B가 매시 알람 이력을 읽어
  # '지난 24시간에 ALARM이 있었다'를 알리고, 바로 위 1번 검사가 그 시점에 공개 API가
  # 실제로 200인지를 잰다. 둘을 같이 읽으면 '고장났었고 지금은 진짜로 돌아왔다'가 된다.
  # 전이 순간에 추측으로 말하는 대신, 잴 수 있게 된 다음에 말한다.

  # 자동 복구(`arn:aws:automate:…:ec2:recover`)는 **일부러 안 붙였다.**
  # 붙이면 시스템 상태검사 실패 시 AWS가 인스턴스를 다른 하드웨어로 옮겨 되살린다.
  # 안 붙인 이유는 비용도 지원 여부도 아니라 **재볼 수가 없어서**다 — 하드웨어 고장을
  # 일부러 낼 방법이 없으니 "설정했다"에서 멈추게 된다. 이 저장소는 그 상태를
  # 반복해서 당했다(백업이 안 돌고 있던 것, WARN이 아무에게도 안 가던 것).
  # 알림은 SNS로 실제 발행해서 사람에게 닿는 것까지 재볼 수 있다. 재볼 수 있는 것만 켠다.
}

output "alerts_topic_arn" {
  description = "운영 알림 SNS 토픽. 전달 경로를 재볼 때 이 ARN으로 publish 한다."
  value       = aws_sns_topic.alerts.arn
}

# ── 감시를 감시하는 자리 ────────────────────────────────────────────────────
# watch.sh는 매시 돌면서 백업·이미지·SES·CloudTrail·예산·알람 전달까지 본다.
# 그런데 **자기 자신이 멈춘 것은 아무도 못 본다.** 알림 경로가 'Actions 실패 메일'
# 하나뿐이라(watch.sh 상단 주석), 워크플로가 안 돌면 실패 메일도 안 온다 —
# 침묵이 정상과 글자 그대로 구분되지 않는다. 멈추는 경로는 여럿이다:
#   · GitHub이 60일간 커밋 없는 저장소의 스케줄을 자동 정지(watch.yml:14가 스스로 적는다)
#   · Actions 비활성화 · OIDC 역할(github-actions-blog-watch) 삭제 · 워크플로 파일 삭제
# 이 저장소가 세 번 당한 병(백업 4개월, IAM 드리프트, SES 4주)을 잡으려고 만든
# 장치가 그 병에 걸리면 아무도 모르는 상태였다. (2026-08-11 공백검사)
#
# **`treat_missing_data = "breaching"`가 이 알람의 전부다.** 위 EC2 알람이 정확히
# 반대(`notBreaching`)인 것과 짝을 이룬다 — 저기선 '데이터 없음 = 꺼둠'이지만
# 여기선 '데이터 없음 = 감시가 죽었다'가 신호다. 같은 설정을 반대로 쓰는 자리라
# 헷갈리기 쉬워 여기 적어둔다.
#
# 비용: 커스텀 지표 1 + 알람 1. CloudWatch 상시 무료 한도가 10+10이고 이 계정은
# 알람 1개·커스텀 지표 0개였다(2026-08-11 실측) → **추가 비용 0.**
resource "aws_cloudwatch_metric_alarm" "watch_heartbeat" {
  alarm_name        = "blog-watch-heartbeat-missing"
  alarm_description = "매시 도는 감시(GitHub Actions)가 12시간 넘게 하트비트를 안 보냈다. 워크플로가 멈췄는지 확인할 것."

  namespace   = "blog/watch"
  metric_name = "HeartBeat"

  # 감시는 매시 17분에 걸려 있다. 창을 3시간으로 뒀다가 2026-08-31에 12시간으로 넓혔다.
  #
  # 이유는 GitHub 스케줄러가 **지연이 아니라 건너뛰기** 때문이다. 08-24~08-30 실행 60번의
  # 간격을 실측했더니 중앙값은 1.0시간인데 평균이 2.5시간, 최대가 12.6시간이었고,
  # 59개 간격 중 14개가 3시간을 넘었다. 그래서 이 경보가 하루 두 번꼴로 울었고
  # 08-29~08-30 이틀에만 OK↔ALARM을 세 번 왕복하며 메일을 세 통 보냈다.
  #
  # 그 메일은 전부 오탐이었다. 워크플로 실행은 그 기간 내내 전부 성공이었고 서버도
  # 정상이었다. **울려도 사람이 할 일이 없는 알림**이라, 이 저장소가 반복해 경계한
  # '아무도 안 보는 신호'가 되는 자리다(WARN이 종료코드에 안 들어가던 07-22 건과 같은 병의
  # 반대편이다 — 그때는 안 울려서 문제였고 여기는 늘 울려서 문제다).
  #
  # 12시간으로 정한 근거도 그 실측이다. 12시간을 넘는 간격은 59개 중 **1개**뿐이었다.
  # 이 경보가 잡으려는 것은 '감시가 통째로 멈춤'(예: GitHub이 60일 무활동 저장소의 스케줄을
  # 끄는 경우)이고, 그건 12시간 창으로도 충분히 잡힌다.
  #
  # 왜 실행을 더 자주 돌려서 해결하지 않았나 — 그쪽이 원인에 가깝지만 매 실행이 S3 조회를
  # 여러 번 하므로 요청 요금이 붙고(월 몇 센트), 하트비트만 따로 자주 쏘는 방식은
  # **하트비트가 '전체 점검이 돌았다'는 뜻을 잃는다.** 지금 이 지표는 전체 점검이 끝까지
  # 간 뒤에만 나가고, 그 의미가 이 경보의 값이다.
  period              = 3600
  evaluation_periods  = 12
  statistic           = "Sum"
  comparison_operator = "LessThanThreshold"
  threshold           = 1
  treat_missing_data  = "breaching" # 위 주석 — 여기선 침묵이 곧 고장이다

  alarm_actions = [aws_sns_topic.alerts.arn]

  # ok_actions를 안 붙이는 이유는 위 EC2 알람과 같다(복구 전이가 거짓말을 할 수 있다).
  # 다만 여기선 성격이 다르다 — 감시가 되살아나면 그 실행 결과 자체가 메일로 온다.
}

# ── CPU 크레딧 고갈 ─────────────────────────────────────────────────────────
# t2.micro는 버스터블이라 크레딧이 0이 되면 CPU가 baseline 10%로 **강제 제한**된다.
# 그 상태에서도 상태검사는 2/2 ok이고 `/api/status`도 200이다 — 즉 이 계정의
# 다른 모든 장치가 초록인데 사이트만 10배 느린, **유일한 '전부 초록인데 다 느린'
# 장애 모드**다. 지금까지 이걸 보는 눈이 0개였다(2026-08-11 병목검사).
#
# 왜 30인가 — `CpuCredits = "standard"`(실측)라 **정지할 때 적립분을 전부 잃고**
# 부팅 때 launch credit 30으로 리셋된다. 10일치 지표에서 일별 최솟값이 전부
# 29.7~30.2인 게 그 증거다. 30 = 100% 1 vCPU로 30분치이므로, 여기서 더 내려간다는 건
# 버스트 예산을 실제로 쓰고 있다는 뜻이다. 임계를 15로 두면 '절반 썼다' 시점에 울린다.
#
# `treat_missing_data = "notBreaching"` — 인스턴스가 꺼져 있으면 지표가 없다.
# 위 EC2 상태검사 알람과 같은 이유이고, 하트비트 알람과는 반대다(거기선 침묵이 곧 고장).
resource "aws_cloudwatch_metric_alarm" "cpu_credit_low" {
  alarm_name        = "blog-cpu-credit-low"
  alarm_description = "t2.micro CPU 크레딧이 15 미만. 곧 baseline 10%로 스로틀된다 — '전부 초록인데 느린' 상태의 원인."

  namespace   = "AWS/EC2"
  metric_name = "CPUCreditBalance"
  dimensions  = { InstanceId = aws_instance.backend.id }

  period              = 300
  evaluation_periods  = 2
  statistic           = "Minimum"
  comparison_operator = "LessThanThreshold"
  threshold           = 15
  treat_missing_data  = "notBreaching" # 꺼져 있음 ≠ 고갈

  alarm_actions = [aws_sns_topic.alerts.arn]
}
