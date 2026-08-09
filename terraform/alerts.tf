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
