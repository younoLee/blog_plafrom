# 보안 사고 대응(IR) 런북

전제 사고: **이 PC가 털렸다.** 이 한 대에 세 가지가 같이 산다 —
`~/.aws/credentials`(AdministratorAccess 액세스키) · `~/.blog-secrets/prod.env`(시크릿 에스크로) ·
`~/.ssh/blog-key.pem`(운영 서버 SSH 개인키). 하나가 아니라 셋이 동시에 나가는 게 이 구성의 특징이다.

가상의 걱정이 아니다. 2026-07-22 복원 훈련이 **`.dockerignore` 누락으로 `.env`가 이미지에
구워지는 것**을 실제로 잡았다(`RECOVERY.md`). 그 이미지가 ECR로 올라갔다면 그날이 사고였다.

> ✅ **2026-07-27에 이 문서의 로테이션 절차를 실제로 끝까지 밟았다.** SES SMTP 키·관리자
> 액세스키·`SECRET_KEY`를 진짜로 교체하고, 옛 자격증명이 거부되는 것과 새 자격증명으로
> 서비스가 도는 것을 각각 증거로 확인했다. 아래 숫자는 그때 실측한 값이다.

## 0. 무엇이 유출되면 무엇이 열리나 (실측)

| 유출 자산 | 열리는 것 | 폭발반경 |
|---|---|---|
| `~/.aws/credentials` (IAM_cli) | **AdministratorAccess** | 계정 전체. 백업 **영구 삭제 가능**(아래 참고) |
| `prod.env`의 `SMTP_USER/PASSWORD` | SES 발송 그룹 IAM 키 | 도메인 사칭 발송·평판 훼손. **CloudTrail에 안 남는다** |
| `prod.env`의 `SECRET_KEY` | 세션·이메일 링크 위조 | 임의 사용자로 로그인, 인증/비번재설정 링크 위조 |
| `prod.env`의 `LLM_ENCRYPTION_KEY` | BYOK 복호화 | `llm_credentials` 평문화 (2026-07-27 기준 행 0) |
| `prod.env`의 `DB_PASSWORD` | DB 계정 | 인터넷 미노출이라 SSH·서버 장악이 선행돼야 함 |
| `prod.env`의 `ANTHROPIC_API_KEY` | Claude 청구 | 앱 캡과 무관하게 키 자체로 직접 호출 가능 |
| `~/.ssh/blog-key.pem` | 서버 셸 | 서버 장악 → 단, EC2 역할 권한은 아래처럼 좁다 |

### 서버가 털려도 백업은 산다 (`simulate-principal-policy`로 실증)

EC2 인스턴스 역할(`blog-ec2-backup`)이 백업 버킷에 대해 할 수 있는 일:

| 행위 | 결과 |
|---|---|
| `s3:PutObject` → `blog-*` | **allowed** (자기 백업 올리기 — 필요한 권한) |
| `s3:GetObject` → 아무 백업 | **implicitDeny** — 서버는 백업을 **읽지 못한다** |
| `s3:DeleteObject` | **implicitDeny** — 서버발 랜섬웨어가 백업을 못 지운다 |
| `s3:PutObject` → `keep/latest.sql.gz` | **implicitDeny** — 마지막 보루는 서버 손이 안 닿는다 |
| `s3:ListBucket` | **implicitDeny** — 목록조차 못 본다 |

**서버 침해와 백업 파괴가 분리돼 있다.** 최소권한이 실제로 값을 하는 지점이다.

### 다만 관리자 키는 백업을 영구 파괴할 수 있다

백업 버킷은 버저닝만 켜져 있고 **Object Lock도 MFA Delete도 없다.** 실수 삭제는 90일간
되돌릴 수 있지만(비현행 버전 만료 90일), 관리자 키를 쥔 공격자는 버전째 지울 수 있다.
→ 남은 위험으로 관리한다. 근본 대책은 **다른 계정의 사본** 또는 Object Lock.

## 1. 탐지 — 우리가 알 수 있는 것과 없는 것

**있는 것**
- CloudTrail `blog-audit`: 멀티리전 · 글로벌 이벤트 · **로그파일 검증 켜짐**.
- `lookup-events`로 액세스키 단위 추적이 **실제로 된다**(90일). 관리이벤트는 무료.
- 예산 알림 $10 / $1(zero-spend). 원래 비용 통제용이지만 **암호화폐 채굴형 침해에는
  사실상 유일한 자동 탐지**다 — 우연히 얻은 통제라는 걸 알고 쓸 것.
- `scripts/watch.sh` 5번 항목(2026-07-27 추가): CloudTrail 로깅 생존 · 액세스키 개수 · 키 나이.

**없는 것 (알고 있는 사각지대)**
- **GuardDuty 없음, CloudWatch 알람 0개.** 기록은 남지만 실시간으로 보는 눈이 없다.
- **SES SMTP 발송은 CloudTrail에 안 남는다.** 관리이벤트가 아니라서다. 그 키가 털려
  스팸을 뿌려도 CloudTrail로는 못 잡는다 → SES 평판·바운스 지표로 봐야 한다.
- IP 화이트리스트 경보는 **일부러 안 넣었다.** 집 IP가 바뀌면 영구 빨간불이 되고,
  영구 빨간불은 아무도 안 보는 신호와 같다. `watch.sh`에는 오탐이 구조적으로
  불가능한 항목만 넣었다.

### 포렌식 기본 명령

```bash
# 이 키가 언제 어디서 쓰였나 (평소 기준선과 비교하는 게 요점)
aws cloudtrail lookup-events --region ap-northeast-2 \
  --lookup-attributes AttributeKey=AccessKeyId,AttributeValue=<AKIA...> \
  --start-time 2026-07-20T00:00:00Z --max-results 50 \
  --query 'Events[].CloudTrailEvent' --output text \
| tr '\t' '\n' | python3 -c "
import sys,json,collections
ips=collections.Counter(); uas=collections.Counter()
for l in sys.stdin:
    l=l.strip()
    if not l: continue
    e=json.loads(l); ips[e.get('sourceIPAddress')]+=1; uas[(e.get('userAgent') or '')[:60]]+=1
print('IP:',ips.most_common(10)); print('UA:',uas.most_common(6))"
```

**2026-07-27 기준선:** 최근 이벤트 50건이 전부 단일 IP(집 회선)에서, 에이전트는
`Terraform/1.15.8`과 `aws-cli/2.35.23` 둘뿐이었다. **낯선 IP나 `boto3`/콘솔 에이전트가
섞이면 그게 신호다.** 침해가 의심되면 먼저 이 기준선부터 다시 뽑는다.

## 2. 대응 순서

사고 한복판에서 순서를 즉흥으로 정하지 않기 위해 못 박아 둔다.

1. **범위 확정** — 어떤 파일/키가 나갔나. 위 0장 표로 열리는 것을 즉시 나열한다.
2. **포렌식 먼저, 삭제는 나중** — 키를 지우면 그 키의 흔적을 쫓기 어려워진다.
   `lookup-events`로 기준선 이탈부터 확인한다(몇 분이면 된다).
3. **로테이션** — 아래 3장. **순서를 지킨다: 새 것 만들고 → 검증하고 → 옛 것 비활성 →
   재검증 → 삭제.** 곧바로 삭제하면 실패 시 되돌릴 자리가 없다.
4. **검증** — 옛 자격증명이 *실제로 거부되는지* 확인한다. "지웠다"는 증거가 아니다.
5. **사후** — 에스크로 3벌 동기(`scripts/env_escrow.sh save`), `watch.sh` 통과 확인,
   이 문서에 사고 기록 추가.

### ⏱️ 무효화는 즉시가 아니다 (실측)

- 액세스키를 **Inactive로 바꿔도 +12초 시점엔 아직 인증에 성공**했고, **약 40초 안에**
  거부로 바뀌었다(SES SMTP 기준).
- 관리자 키도 같았다 — 비활성 직후엔 살아 있었고 **+11초에 `InvalidClientTokenId`**.
- 새로 만든 키가 쓸 수 있게 되기까지도 **약 10초** 걸렸다.

→ **"껐다"와 "막혔다" 사이에 수십 초의 창이 있다.** 급한 사고에서는 키 비활성만으로
안심하지 말고, 필요하면 사용자 정책 분리·세션 무효화까지 같이 간다.

## 3. 로테이션 절차 (항목별)

> ⚠️ **로테이션 중에는 `watch.sh`가 빨간불이 된다.** 새 키와 옛 키가 잠깐 함께 살기 때문에
> 5번 검사의 "액세스키 1개 기대"가 걸린다. **의도한 동작이다** — 옛 키를 지우면 저절로 꺼진다.
> 매시 감시가 메일을 보내므로, 로테이션이 길어질 것 같으면 미리 알고 있을 것.

### 3-1. SES SMTP 자격증명

SMTP 비밀번호는 IAM 시크릿에서 **파생**한다. 새 키를 만들었다고 끝이 아니다.

```bash
U=ses-smtp-user.20260625-184915
aws iam create-access-key --user-name "$U"   # Id/Secret 확보 (Secret은 이때만 보인다)
```

```python
# 파생 + 인증 확인. .env를 건드리기 전에 여기서 먼저 통과시킨다.
import hmac,hashlib,base64,smtplib
region='ap-northeast-2'
def sign(k,m): return hmac.new(k,m.encode(),hashlib.sha256).digest()
sig=sign(('AWS4'+SECRET).encode(),'11111111')
for m in (region,'ses','aws4_request','SendRawEmail'): sig=sign(sig,m)
pw=base64.b64encode(bytes([0x04])+sig).decode()
s=smtplib.SMTP('email-smtp.ap-northeast-2.amazonaws.com',587); s.starttls(); s.login(KEY_ID,pw)
```

그 다음 서버 `.env`의 `SMTP_USER`/`SMTP_PASSWORD`를 바꾸고 백엔드를 재생성한다.
**검증은 `/api/status`의 `mail` 항목으로 한다** — 이 검사는 TCP 연결이 아니라
**STARTTLS + 로그인까지** 실제로 해보므로 자격증명 교체의 유효한 증거다.
(2026-06-25에 4주 동안 "메일 정상"이라고 25,826번 거짓말한 사고 뒤에 그렇게 강화했다.)

### 3-2. 관리자 액세스키 (`IAM_cli`)

**자기 발 쏘기 쉬운 구간이다.** 반드시 이 순서로.

```bash
cp ~/.aws/credentials ~/.aws/credentials.preIR.$(date -u +%Y%m%dT%H%M%SZ)
aws iam create-access-key --user-name IAM_cli          # 1) 새 키
AWS_ACCESS_KEY_ID=새키 AWS_SECRET_ACCESS_KEY=새시크릿 \
  aws sts get-caller-identity                           # 2) 기존 설정 안 건드리고 먼저 검증
#                                                          (전파에 ~10초 걸린다)
# 3) ~/.aws/credentials 교체 → 4) aws sts get-caller-identity 로 재검증
aws iam update-access-key --user-name IAM_cli --access-key-id 옛키 --status Inactive  # 5)
# 6) 옛 키로 호출해 InvalidClientTokenId 가 뜨는 것을 확인한 뒤에야
aws iam delete-access-key --user-name IAM_cli --access-key-id 옛키                     # 7)
```

### 3-3. `SECRET_KEY`

새 값 생성 → 서버 `.env` 교체 → 백엔드 재생성. **모든 기존 세션과 발송 대기 중인
이메일 인증·비번재설정·구독확인 링크가 무효가 된다**(의도된 결과다).

검증: 옛 `SECRET_KEY`로 서명한 JWT가 거부되는지 직접 확인한다.

```bash
# 옛 키로 서명한 토큰 → 401,  새 키로 서명한 토큰 → 200 이어야 한다
curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $TOK" \
  http://localhost:8000/api/auth/me
```

### 3-4. 이번에 **일부러 안 한 것**

- **`LLM_ENCRYPTION_KEY`** — 교체하면 옛 암호문을 못 푼다. 2026-07-27 기준 `llm_credentials`가
  0행이라 무해했지만, **재암호화 계획 없이는 손대지 않는다**가 원칙이다. 교체할 때도
  옛 에스크로 사본을 지우지 않는다(`env_escrow.sh save`가 타임스탬프로 보관한다).
- **`ANTHROPIC_API_KEY` / 토스 키** — 각 콘솔에서 사람이 재발급해야 한다. 유출 시엔
  1순위로 폐기할 것(앱의 사용량 캡은 우리 앱을 지나가는 호출만 묶는다. 키를 직접 쥔
  공격자에겐 아무 제약이 없다).
- **SSH 키페어** — 교체하려면 인스턴스 교체(`key_name` 변경)나 `authorized_keys` 직접
  수정이 필요하다. 유출 시엔 **SG의 `ssh_cidr`를 먼저 좁히는 것**이 더 빠른 지혈이다.

## 4. 즉시 지혈 (범위가 불확실할 때 먼저 할 것)

```bash
# 1) 오리진 주차 — /api/*를 fail closed 로. 쓰기가 멈춘다.
terraform -chdir=terraform apply -target=aws_cloudfront_distribution.main
# 2) 서버 정지 (백업 뜨고 내려간다)
scripts/stop_server.sh
# 3) SSH 대역을 내 IP로 재확인
curl -s https://checkip.amazonaws.com   # terraform.tfvars의 ssh_cidr와 비교
```

서버를 끄면 EC2 인스턴스 역할로 할 수 있는 일도 같이 사라진다. 범위를 모르는 초기에는
**끄는 게 가장 싼 봉쇄**다 — 이 프로젝트는 상시 가동이 요구되지 않는다는 이점이 있다.

## 5. 남은 위험 (알고 안 고친 것)

- **백업이 관리자 키의 폭발반경 안에 있다.** Object Lock·MFA Delete 없음, 사본이 같은 계정.
  근본 대책은 별도 계정 사본. 비용·복잡도 때문에 보류 중인 결정이다.
- **`ses-smtp-user`에 MFA가 없다.** 프로그램 접근 전용이라 MFA를 붙일 수 없는 성격이지만,
  그만큼 키 자체가 유일한 방어선이다 → 정기 교체가 유일한 통제(`watch.sh`가 90일에 경고).
- **관리자 권한이 둘이다**(`IAM_cli`·`youno` 모두 AdministratorAccess). 최소권한 원칙상
  CLI 사용자는 필요한 권한으로 좁히는 게 맞다. 데모 프로젝트라 감수 중.
- **CloudTrail 로그 버킷이 같은 계정에 있다.** 관리자 키를 쥔 공격자는 증거도 지울 수 있다
  (로그파일 검증이 켜져 있어 *변조*는 드러나지만 *삭제*는 막지 못한다).
