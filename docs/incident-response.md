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
| `prod.env`의 `LLM_ENCRYPTION_KEY` | BYOK 복호화 | `llm_credentials` 평문화. **행 수는 훈련 때마다 다시 센다** — 2026-07-27에 0행이었다는 사실이 이 표에 숫자로 굳어 있어서, 그 뒤 BYOK가 실사용에 들어가도 폭발반경이 계속 0으로 읽혔다 |
| `prod.env`의 `DB_PASSWORD` | DB 계정 | 인터넷 미노출이라 SSH·서버 장악이 선행돼야 함 |
| `prod.env`의 `ANTHROPIC_API_KEY` | Claude 청구 | 앱 캡과 무관하게 키 자체로 직접 호출 가능 |
| `~/.ssh/blog-key.pem` | 서버 셸 | 서버 장악 → 단, EC2 역할 권한은 아래처럼 좁다 |
| `prod.env`의 `VAPID_PRIVATE_KEY` | 푸시 발송 권한 | 등록된 **모든 기기로 임의 알림 발송**. 잠금화면에 뜨므로 피싱 경로가 된다. 폐기하면 기존 구독이 전부 무효가 된다(3-5) |
| `prod.env`의 `TOSS_SECRET_KEY` | 결제 승인 API | 결제 조회·취소. 금전 경로라 콘솔에서 즉시 폐기 |
| `prod.env`의 `ORIGIN_SECRET` | CloudFront 우회 | 오리진(EC2:8000)을 직접 칠 수 있게 된다 → 엣지의 WAF·요청크기 제한을 통째로 건너뛴다 |
| **`~/.aws/credentials` → SSM `/blog/prod/env`** | **위 `prod.env` 전 항목** | 관리자 키 한 장이 이 표의 다른 행 **전부의 상위 집합**이다. 우선순위는 항상 이것이 먼저다 |
| **`~/.blog-secrets/prod.env.<타임스탬프>`** | **옛 세대 키 전부** | 에스크로가 로테이션 이력을 보관하므로, 이 PC가 털리면 '이미 교체한 옛 키'까지 같이 나간다. 옛 암호문(BYOK)은 옛 키로 풀린다 |

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

### 관리자 키로도 백업을 못 지운다 (2026-07-27에 막음)

훈련 당시에는 버저닝뿐이라 **관리자 키를 쥔 공격자가 버전째 지울 수 있었다.** 그날
바로 **Object Lock(COMPLIANCE, 14일)** 을 백업 버킷과 CloudTrail 버킷에 걸었다.

실증 — 관리자 자격증명으로 `keep/latest.sql.gz` 삭제를 시도했다:

```
$ aws s3api delete-object --bucket blog-db-backups-... --key keep/latest.sql.gz --version-id ...
AccessDenied ... object protected by object lock
$ ... --bypass-governance-retention          # 우회 플래그까지
AccessDenied ... object protected by object lock
```

GOVERNANCE가 아니라 COMPLIANCE인 이유가 여기 있다. GOVERNANCE는
`s3:BypassGovernanceRetention` 으로 우회되므로 **'관리자 키 유출'이라는 우리 위협에는
무의미하다.** COMPLIANCE는 루트를 포함해 아무도 보존 기간 안에는 못 지운다.

부작용은 확인했다:
- **백업 업로드는 안 깨진다.** EC2 역할과 같은 권한(`s3:PutObject`만)을 가진 임시 역할로
  잠긴 버킷에 업로드가 되는 것을 확인했다. 기본 보존은 자동으로 붙는다.
- **기존 객체엔 소급 적용되지 않는다.** 켤 당시 있던 18개 버전에는 `put-object-retention`으로
  직접 걸었다. 앞으로 켜는 다른 버킷에서도 이 단계를 잊지 말 것.
- 백업 스크립트는 `cp`/`sync`만 쓰고 삭제가 없어 충돌하지 않는다.
- **대가:** 잘못 올린 것도 14일간 못 지운다. 버킷을 정리하려면 그만큼 기다려야 한다.

남은 것은 **사본이 여전히 같은 계정에 있다**는 점이다. 계정 자체를 잃는 시나리오는
Object Lock으로 못 막는다 — 근본 대책은 다른 계정의 사본이다(비용·복잡도로 보류).

## 1. 탐지 — 우리가 알 수 있는 것과 없는 것

**있는 것**
- CloudTrail `blog-audit`: 멀티리전 · 글로벌 이벤트 · **로그파일 검증 켜짐**.
- `lookup-events`로 액세스키 단위 추적이 **실제로 된다**(90일). 관리이벤트는 무료.
- 예산 알림 $10 / $1(zero-spend). 원래 비용 통제용이지만 **암호화폐 채굴형 침해에는
  사실상 유일한 자동 탐지**다 — 우연히 얻은 통제라는 걸 알고 쓸 것.
- `scripts/watch.sh` 5번 항목(2026-07-27 추가): CloudTrail 로깅 생존 · 액세스키 개수 · 키 나이.

**없는 것 (알고 있는 사각지대)**
- **GuardDuty 없음.** ~~CloudWatch 알람 0개.~~ <ins>(**2026-08-11 정정** — 알람은
  2026-08-09에 생겼다: `terraform/alerts.tf:122` `ec2_status_check`(StatusCheckFailed,
  1분×2회, `notBreaching`) → SNS `blog-alerts` → 이메일 구독. 전달 가능 여부는
  `scripts/watch.sh:383`의 6-B가 매시 확인한다. **사고 때 알람 이력과 SNS 구독을
  먼저 뒤질 것** — 이 줄을 믿고 건너뛰면 이미 울린 신호를 놓친다.)</ins>
  GuardDuty가 없다는 것과 애플리케이션 계층 이상(로그인 폭주 등)에 알람이 없다는 것은 그대로다.
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

### 3-4. 2026-07-27에 **일부러 안 한 것** (절차는 아래 3-5~3-8에 생겼다)

> 2026-08-26 보강: 이 절의 항목들이 "안 한 것"으로만 남아 있어서, **로테이션 절차가
> 아예 없는 시크릿**이 넷이 됐다(VAPID·TOSS·ORIGIN_SECRET·LLM). 훈련은 절차를
> 검증하는 것이지 발명하는 것이 아니라, 절차가 없으면 IR 훈련이 돌 대상이 없다.
> 아래에 뼈대를 먼저 썼다. **값과 실측은 다음 훈련에서 채운다.**

- **`LLM_ENCRYPTION_KEY`** — 교체하면 옛 암호문을 못 푼다. 2026-07-27 기준 `llm_credentials`가
  0행이라 무해했지만, **재암호화 계획 없이는 손대지 않는다**가 원칙이다. 교체할 때도
  옛 에스크로 사본을 지우지 않는다(`env_escrow.sh save`가 타임스탬프로 보관한다).
  → 재암호화 도구를 만들었다: `scripts/reencrypt_llm_keys.py`. 절차는 **3-6**.
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

- ~~백업이 관리자 키의 폭발반경 안에 있다.~~ → **2026-07-27에 Object Lock(COMPLIANCE 14일)으로
  막았다**(위 0장). 남은 건 "사본이 같은 계정"뿐이고, 그건 계정 상실 시나리오라 별도 계정
  사본이 있어야 풀린다 — 비용·복잡도로 보류 중인 결정이다.
- **MFA Delete는 안 켰다.** 루트 자격증명으로만 설정할 수 있어 자동화가 불가능하고,
  Object Lock COMPLIANCE가 같은 위협(버전 영구 삭제)을 이미 막는다. 중복 통제로 판단해 생략.
- **`ses-smtp-user`에 MFA가 없다.** 프로그램 접근 전용이라 MFA를 붙일 수 없는 성격이지만,
  그만큼 키 자체가 유일한 방어선이다 → 정기 교체가 유일한 통제(`watch.sh`가 90일에 경고).
- **관리자 권한이 둘이다**(`IAM_cli`·`youno` 모두 AdministratorAccess). 최소권한 원칙상
  CLI 사용자는 필요한 권한으로 좁히는 게 맞다. 데모 프로젝트라 감수 중.
- ~~CloudTrail 로그를 관리자 키로 지울 수 있다.~~ → **같은 날 Object Lock(COMPLIANCE 14일)을
  걸었다.** 로그파일 검증이 *변조*를 드러내고, Object Lock이 *삭제*를 막는다. 다만 보호는
  **적용 이후 쌓이는 로그**에만 걸린다(침해 후의 로그가 증거이므로 목적은 달성된다).

### 3-5. VAPID 키페어 (푸시)

**폐기 조건**: `VAPID_PRIVATE_KEY` 유출. 공개키만 나간 건 무해하다(원래 공개된다).

⚠️ **이건 다른 로테이션과 성격이 다르다. 교체하면 기존 구독이 전부 죽는다.**
브라우저가 구독할 때 서버 공개키를 `applicationServerKey`로 넣어 푸시 서비스에 등록한다
(`frontend/src/api/push.ts:85`). 푸시 서비스는 그 키로 서명된 요청만 받으므로, 키를 바꾸면
**등록된 모든 기기가 조용히 발송 거부**가 된다. 사용자가 알림을 끄고 다시 켜야 복구된다.
사용자에게 알릴 방법이 알림뿐인데 그 알림이 안 가는 상황이라, **공지가 선행돼야 한다.**

```bash
# 1) 새 키페어 생성
docker compose exec -T backend python scripts/gen_vapid_keys.py

# 2) 서버 .env의 VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY 교체 → 백엔드 재생성
#    (VAPID_SUBJECT는 mailto: 연락처라 유출과 무관 — 바꾸지 않는다)

# 3) 죽은 구독을 정리한다. 안 하면 발송 때마다 전 기기에 실패 요청이 나간다.
#    services/push.py는 404/410을 받으면 행을 지우지만, 키 불일치는 403이라 안 지운다.
docker compose exec -T db psql -U postgres -d blog -c "delete from push_subscriptions;"

# 4) 검증 — 실기기 1대가 필요하다. 자동 수단이 없다(/api/status에 항목이 없다).
docker compose exec -T backend python scripts/push_selftest.py
```

**미해결**: 3번을 자동화하려면 발송 실패 403을 '키 불일치'로 분류해 행을 지워야 한다.
지금은 사람이 판단한다. 훈련에서 실제 403 응답 본문을 기록해 둘 것.

### 3-6. `LLM_ENCRYPTION_KEY` (BYOK 재암호화)

**폐기 조건**: `prod.env` 유출. 이 키는 데이터를 푸는 열쇠라 **먼저 재암호화하고 나중에 폐기**한다.
순서를 뒤집으면 `llm_credentials`가 통째로 죽는다.

```bash
# 1) 새 키 생성 (Fernet)
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# 2) 먼저 dry-run — 몇 행이 바뀌는지, 옛 키로 안 풀리는 행이 있는지 본다
scripts/reencrypt_llm_keys.py --dry-run --old "$OLD" --new "$NEW"

# 3) 실행. MultiFernet.rotate라 옛 키로 풀어 새 키로 다시 잠근다
scripts/reencrypt_llm_keys.py --old "$OLD" --new "$NEW"

# 4) 서버 .env의 LLM_ENCRYPTION_KEY를 새 값으로 → 백엔드 재생성
# 5) 검증: 복원 훈련의 BYOK 카나리아가 초록인지 (scripts/restore_drill.sh)
```

⚠️ **옛 에스크로 사본을 지우지 않는다.** 3번이 일부 행에서 실패했다면 그 행은 옛 키로만
풀린다. `env_escrow.sh save`가 타임스탬프로 보관하는 이유가 이것이다.

### 3-7. `TOSS_SECRET_KEY` (결제)

**폐기 조건**: 유출 즉시. 금전 경로라 1순위다.

토스 콘솔에서 사람이 재발급해야 한다(API 없음). 짝이 되는 클라이언트 키가 프론트에
빌드타임으로 박히므로 **프론트 재빌드·재배포가 함께 필요**하다(`.github/workflows/deploy.yml`, 수동 실행).

⚠️ `PAYMENTS_REQUIRE_LIVE=true`를 **같이 확인**한다. `config.py:83`의 코드 기본값이 실제
토스 **테스트 키**이고 `:91`의 `payments_require_live` 기본값이 `False`라, `.env`에서 그 한 줄이
빠지면 테스트 결제 승인이 Pro로 붙는다. `main.py`의 기동 가드가 프로드에서 이걸 막는다.

### 3-8. `ORIGIN_SECRET` (오리진 보호)

**폐기 조건**: 유출. 이걸 쥐면 CloudFront를 우회해 오리진을 직접 칠 수 있다 —
엣지의 WAF와 요청 크기 제한을 통째로 건너뛴다.

**두 곳을 같은 값으로 바꿔야 한다.** 하나만 고치면 `/api/*`가 전부 403이 된다.

```bash
# 1) 새 값 (32자 이상, [A-Za-z0-9_-])
openssl rand -hex 32

# 2) 서버 .env의 ORIGIN_SECRET 교체 → 백엔드 재생성
# 3) terraform 변수도 같은 값으로 → apply (CloudFront 전파에 수 분)
#    terraform.tfvars의 origin_secret을 고치고 apply
# 4) 검증: scripts/verify_deploy.sh 의 '오리진 시크릿 가드' 항목
```

⚠️ **2와 3 사이에 창이 있다.** 그동안 CloudFront는 옛 값을 붙이고 서버는 새 값을 검사하므로
`/api/*`가 403이다. 순서를 뒤집으면(3 먼저) 반대 방향으로 같은 창이 생긴다. 짧은 무중단이
필요하면 서버가 **두 값을 모두 받아들이는** 과도기 코드가 있어야 하는데, 지금은 없다.
훈련에서 실제 창의 길이를 재고 여기 적을 것.
