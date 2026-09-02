# EC2 백엔드 인스턴스 (Docker로 FastAPI 구동. DB는 같은 호스트의 Postgres 컨테이너 —
# RDS는 2026-07-18에 비용 때문에 들어냈다).
resource "aws_instance" "backend" {
  # Amazon Linux 2023 x86_64 (t2.micro는 x86_64다 — arm64 AMI를 넣으면 기동 자체가 안 된다).
  # 2026-09-02에 갱신했다. 직전 값 ami-0436b3a61a7a7e22a는 6월판(al2023-ami-2023.12.20260622.0)
  # 이고 DeprecationTime이 2026-09-17이라, 그날 이후 재건하면 RECOVERY.md 시나리오 B의
  # 1단계(run-instances)가 첫 삽에서 실패한다.
  #
  # 조회한 명령과 결과:
  #   $ aws ssm get-parameters-by-path --path /aws/service/ami-amazon-linux-latest \
  #       --region ap-northeast-2 \
  #       --query 'Parameters[?contains(Name, `al2023`)].[Name,Value]' --output text
  #     .../al2023-ami-kernel-default-x86_64   ami-00b5b2470beafd65f
  #   $ aws ec2 describe-images --region ap-northeast-2 --image-ids ami-00b5b2470beafd65f \
  #       --query 'Images[].[Name,Architecture,CreationDate,DeprecationTime]' --output text
  #     al2023-ami-2023.12.20260831.0-kernel-6.18-x86_64  x86_64
  #     2026-08-26T15:34:32.000Z   2026-11-24T15:36:00.000Z
  #
  # ⚠️ 이 값은 아래 lifecycle의 ignore_changes = [ami] 때문에 **살아 있는 인스턴스를
  #    바꾸지 않는다.** 여기서 id를 갱신해도 plan은 조용하고, 새 AMI는 인스턴스를
  #    새로 만들 때(재건·게임데이)만 쓰인다. 즉 이 줄은 '재건 시작점'을 최신으로
  #    유지하는 용도다. 돌고 있는 호스트의 커널·패키지 패치는 이 값과 무관하며
  #    OS 쪽 절차(dnf)가 따로 담당한다 — 이 저장소에는 아직 그 절차가 없다.
  # 🗓️ 다음 확인: 2026-12-01 (분기 1회. 위 DeprecationTime 2026-11-24보다 뒤이므로,
  #    그때는 이미 만료된 상태다 → 늦어도 11월 안에 다시 조회해 갱신할 것)
  ami                    = "ami-00b5b2470beafd65f"
  instance_type          = "t2.micro"
  key_name               = "blog-key.pem"
  subnet_id              = "subnet-04bf4b4e44fe4defe"
  vpc_security_group_ids = [aws_security_group.ec2.id]

  # 종료(terminate) 보호. 이 인스턴스는 앱뿐 아니라 **Postgres 컨테이너와 그 데이터**를
  # 같이 이고 있고, 아래 root_block_device가 delete_on_termination = true다. 즉 terminate
  # 한 번이면 마지막 백업 이후의 글·댓글이 통째로 사라진다. 2026-09-02 실측으로
  # describe-instance-attribute --attribute disableApiTermination 가 false였다.
  # 지금까지 이걸 막던 것은 scripts/stop_server.sh의 plan 검사 하나뿐이라, 콘솔 클릭·
  # 범위를 안 좁힌 적용·유출된 키는 전부 그냥 통과했다. API 자체를 막는다.
  # 이 인자는 ModifyInstanceAttribute로 도는 **in-place 수정**이라 인스턴스를 교체하지
  # 않는다(교체되면 데이터가 날아가므로 이게 핵심이다. plan으로 확인했다).
  disable_api_termination = true

  # DB 백업(정지 절차 1단계)이 S3(blog-db-backups)에 올릴 수 있도록 인스턴스 프로파일 부여.
  # attach는 in-place(인스턴스 교체 아님). 권한은 db-backup.tf에서 PutObject로만 한정.
  iam_instance_profile = aws_iam_instance_profile.backend.name

  # IMDSv2 강제 (http_tokens=required). SSRF로 자격증명을 캐가는 걸 막는 실질 방어선 —
  # 토큰을 PUT으로 먼저 받아 헤더에 실어야 해서, 주소만 조종하는 SSRF로는 완성 못 한다.
  # (앱 측 1차 방어는 services/llm_keys.py validate_base_url)
  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required"
    # 2를 1로 낮추지 말 것: 백엔드가 '컨테이너' 안에서 인스턴스 역할로 S3에 업로드하는데
    # (routers/uploads.py) 도커 브리지가 홉을 하나 더 써서, 1이면 IMDS에 못 닿아 업로드가 깨진다.
    # 보안은 hop-limit이 아니라 위의 http_tokens=required가 담당한다.
    http_put_response_hop_limit = 2
    instance_metadata_tags      = "disabled"
  }

  # 루트 볼륨. pgdata(Postgres 컨테이너의 데이터)가 이 위에 있다 → terminate = 데이터 소멸.
  # 그래서 위의 disable_api_termination과 아래 lifecycle.prevent_destroy가 붙어 있다.
  #
  # 🔒 **암호화(encrypted)를 여기 안 적는 것은 알고 안 적는 것이다**(2026-09-02 검사 지적).
  #   · 지금 암호화는 **계정 기본 설정**에 의존한다. 실측:
  #       $ aws ec2 get-ebs-encryption-by-default --region ap-northeast-2
  #         { "EbsEncryptionByDefault": true }
  #     즉 이 계정에서 만들어지는 EBS는 기본적으로 암호화된다. 다만 그 사실이
  #     terraform 밖에 있어서, 계정 설정이 꺼지면 이 코드는 조용히 평문 볼륨을 만든다.
  #   · 그런데도 안 고치는 이유: root_block_device의 암호화 인자를 바꾸면 **인스턴스가
  #     교체(replace)될 수 있고**, 이 호스트에서 교체는 곧 DB 소멸이다. 살아 있는
  #     볼륨을 제자리에서 암호화하는 방법도 없다(스냅샷 → 암호화 복사 → 새 볼륨 경로뿐).
  #   · 그러니 이건 '재건할 때' 처리할 항목이다: 다음에 인스턴스를 새로 만들 때
  #     encrypted = true 를 함께 넣으면 교체 비용 없이 얻는다. 그때까지는 계정 기본값이
  #     켜져 있는지가 유일한 보증이므로, 위 명령으로 가끔 확인한다.
  root_block_device {
    delete_on_termination = true
  }

  tags = {
    # 원래는 "blog-backend "(끝 공백)이었다 — 콘솔에서 만든 값을 그대로 맞춘 것이다.
    # 2026-07-27 DR 게임데이에서 그 공백이 실제로 복구를 막았다: 재해 뒤 새 인스턴스를
    # 찾는 명령 `--filters "Name=tag:Name,Values=blog-backend "`가 **아무것도 못 찾는다**.
    # AWS CLI의 축약(shorthand) 필터 파서가 값 뒤의 공백을 잘라내기 때문이다. 그래서
    # IID가 비고, 바로 다음 줄이 InvalidInstanceID.Malformed로 죽는다. JSON 형식 필터로만
    # 매칭되는데, 사고 한복판에서 그걸 떠올릴 이유가 없다. → 공백을 없앤다(태그는 in-place 갱신).
    Name = "blog-backend"
  }

  lifecycle {
    # ① 파괴·교체 자체를 계획 단계에서 막는다. waf.tf:117이 WebACL에 쓰는 것과 같은 장치다.
    #    disable_api_termination이 'AWS API로 지우는 것'을 막는다면, 이건 '테라폼이 지우는
    #    계획을 세우는 것'을 막는다 — 둘은 다른 문이라 둘 다 잠근다.
    #    ⚠️ -target 없는 평범한 apply에서 무슨 일이 일어나는가: 이 인스턴스를 destroy나
    #    replace 하려는 변경이 계획에 섞이면 **plan이 그 자리에서 에러로 죽는다**
    #    ("Instance cannot be destroyed ... has lifecycle.prevent_destroy set").
    #    부분 적용이 아니라 전부 중단이다. 그래서 관계없는 변경(예: 오리진 주차)도 같이
    #    막힌다 — scripts/stop_server.sh는 plan 실패 시 아무것도 적용하지 않고 멈추므로
    #    안전한 쪽으로 넘어진다. 그때는 '왜 교체가 계획됐는지'를 먼저 밝혀야 한다.
    #
    # ② AMI id를 갱신해도 살아 있는 인스턴스를 교체하지 않게 한다. ami는 ForceNew라
    #    id 한 글자만 바뀌어도 계획이 인스턴스 교체를 내고, 그건 루트 볼륨(pgdata)째
    #    소멸이다. 새 값은 '다음에 만들 때'만 쓰인다.
    #    ①과 ②의 관계: ②가 없으면 ami를 갱신하는 순간 ①이 걸려 **plan 전체가 죽는다**
    #    (교체 계획 = 파괴 계획). 즉 ②는 ①의 우회로가 아니라, ①이 무해한 편집에까지
    #    걸리지 않게 해주는 짝이다. 실제 교체 위험은 ①이 계속 막는다.
    #
    # 🔥 **일부러 부술 때는 이 두 줄을 먼저 끈다.** 2026-07-27 / 2026-08-27 DR 게임데이처럼
    #    인스턴스를 진짜로 terminate하고 재건하는 절차(docs/dr-gameday-20260827.md,
    #    RECOVERY.md 시나리오 B)는 이 상태 그대로는 시작할 수 없다. 순서는:
    #      1) DB 백업이 S3에 올라갔는지 먼저 확인한다(scripts/stop_server.sh 1단계).
    #      2) 위 disable_api_termination = true 를 false로 바꾸고 적용한다(in-place).
    #      3) 이 lifecycle 블록의 prevent_destroy 줄을 지운다(테라폼 코드라 적용 불필요).
    #      4) 그다음에야 부수고 재건한다.
    #      5) 재건이 끝나면 2·3을 **되돌린다.** 되돌리는 걸 잊으면 보호가 없는 채로 운영된다.
    #    이 순서를 지키지 않으면 게임데이 중에 plan이 죽어 시간만 쓴다.
    prevent_destroy = true
    ignore_changes  = [ami]
  }
}

# 퍼블릭 IP는 EIP 없이 subnet의 auto-assign(MapPublicIpOnLaunch=true)에 맡긴다.
# → 켤 때마다 IP가 바뀌므로 CloudFront 오리진은 var.backend_origin_dns로 넘긴다.
#   (정지 중엔 오리진이 주차됨. 이유는 variables.tf 참고)

# EC2 백엔드 보안그룹. SSH(22)는 내 IP만, API(8000)는 CloudFront만.
resource "aws_security_group" "ec2" {
  name        = "launch-wizard-1"
  description = "launch-wizard-1 created 2026-06-24T05:31:53.556Z"
  vpc_id      = "vpc-0326229237c590a90"

  # API 포트 — CloudFront(origin-facing) 관리형 prefix list만 허용.
  # 직접 IP:8000 노출 차단 → WAF·HTTPS 우회 + /docs 노출 + 평문 전송 방지.
  ingress {
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    prefix_list_ids = ["pl-22a6434b"] # com.amazonaws.global.cloudfront.origin-facing
  }

  # SSH (내 IP만). 값은 저장소에 두지 않는다 — 공개 저장소에 운영자의 실제 공인 IP를
  # 박아두면 "어디를 노려야 SSH 경계가 뚫리는지"를 알려주는 셈이고, 거주지 노출이기도
  # 하다(2026-07-22 보안검사 지적). terraform.tfvars(gitignore됨)로 주입한다.
  # 기본값을 두지 않으므로 값이 없으면 apply가 **실패한다** — 0.0.0.0/0으로 조용히
  # 넓어지는 것보다 낫다. 재해 복구 절차는 RECOVERY.md 참고.
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.ssh_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# VPC 기본 보안그룹. RDS를 EC2 컨테이너로 이전하면서(2026-07-18) 5432 인바운드는 제거.
# 이제 DB는 compose 네트워크 내부(db:5432)로만 접근 → VPC에 노출되는 DB 포트가 없다.
# aws_default_security_group은 '삭제'가 아니라 '관리'만 한다(destroy해도 SG는 남고 규칙만 비워짐).
resource "aws_default_security_group" "default" {
  vpc_id = "vpc-0326229237c590a90"

  # 같은 보안그룹끼리 전체 허용 (default SG 기본 규칙)
  ingress {
    from_port = 0
    to_port   = 0
    protocol  = "-1"
    self      = true
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
