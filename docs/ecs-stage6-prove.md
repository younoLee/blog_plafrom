# ECS Stage 6 — 증명 & 캡처 체크리스트

> 목적: "오케스트레이션으로 옮겼다"를 **증거**로 만든다. 이게 면접의 핵심 재료다
> (ROADMAP: 면접 관문1을 이거 하나로 완성). 각 항목 = 시연 → 캡처 → 면접 한 줄.
>
> 전제: 🚨 런북대로 apply·이관·컷오버(`api_backend=ecs`) 끝나고 서비스 healthy + CloudFront로
> DB경로 스모크(`/api/status`·`/api/posts`) 통과한 상태.
>
> 공통 변수: 클러스터 `blog` · 서비스 `blog-backend` · 타깃그룹 `blog-backend` · 리전 `ap-northeast-2`
> · 프론트 `https://d2j66m9udyg9yq.cloudfront.net`. 명령은 사용자가 실행(규칙7), 결과는 같이 읽는다.

---

## 0. 상시 켜두는 '가용성 프로버' (무중단 증거의 뼈대)
배포·태스크 종료 시연 **동안** 별도 터미널에서 계속 돌린다. 비-200을 세서 "무중단"을 수치로 증명.
```bash
# 0.5초마다 읽기 경로를 때려 상태코드 집계. 시연 내내 켜두고, 끝나면 Ctrl-C.
while true; do
  code=$(curl -s -o /dev/null -w '%{http_code}' https://d2j66m9udyg9yq.cloudfront.net/api/posts)
  printf '%(%H:%M:%S)T %s\n' -1 "$code"
  sleep 0.5
done | tee /tmp/prober.log
# 끝나고: 비-200 개수 = grep -vc ' 200' /tmp/prober.log  (0이면 무중단 달성)
```
**캡처:** `prober.log` 요약(총 요청 수, 비-200 수=0). **면접:** "롤링 배포·태스크 강제 종료 중에도 5xx 0건."

---

## 1. 오토스케일 — 부하로 scale-out → 부하 제거로 scale-in
```bash
# (터미널 A) 부하 — CPU를 60% 위로 밀어 desired 2→3→4 유발
BASE_URL=https://d2j66m9udyg9yq.cloudfront.net k6 run scripts/loadtest.k6.js
# (터미널 B) 30초마다 desired/running 관찰
watch -n30 'aws ecs describe-services --cluster blog --services blog-backend \
  --query "services[0].{desired:desiredCount,running:runningCount,pending:pendingCount}" --output table'
# 스케일링 활동 내역(언제·왜 늘고 줄었나)
aws application-autoscaling describe-scaling-activities \
  --service-namespace ecs --resource-id service/blog/blog-backend --output table
```
**캡처:** ① CloudWatch 콘솔 **ECS CPUUtilization 그래프**(60% 선 넘는 구간) ② desired가 2→3(→4)로 오르고
부하 제거 후 5분 쿨다운 뒤 2로 내려오는 표 ③ scaling-activities 텍스트.
**면접:** "CPU 타깃 60% 정책으로 부하 시 자동 증설, 빠질 때 5분 쿨다운으로 신중히 축소 — scale-out은 1분/scale-in은 5분으로 급증 먼저 대응."

## 2. 태스크 장애 → ECS 자동 대체
```bash
# 실행 중 태스크 하나를 강제 종료 (프로버는 계속 켜둔 채로)
TASK=$(aws ecs list-tasks --cluster blog --service-name blog-backend \
  --query 'taskArns[0]' --output text)
aws ecs stop-task --cluster blog --task "$TASK" --reason "chaos: prove auto-recovery"
# 이벤트에서 '뜨는 걸' 관찰
aws ecs describe-services --cluster blog --services blog-backend \
  --query 'services[0].events[0:5].message' --output table
```
**캡처:** stop 직후 running이 잠깐 1로 떨어졌다가 새 태스크가 떠 2로 복귀하는 이벤트 로그 + 프로버가 그동안 200 유지.
**면접:** "태스크를 죽여도 desired=2를 맞추려 ECS가 자동으로 새 태스크를 띄우고, ALB가 새 태스크만 라우팅해 무중단 — 사람이 개입 안 함."

## 3. 무중단 롤링 배포
```bash
# 새 이미지 SHA로 서비스 갱신(또는 강제 새 배포). min 100%/max 200%라 새 게 healthy 된 뒤 옛 걸 내린다.
aws ecs update-service --cluster blog --service blog-backend --force-new-deployment
# 롤아웃 관찰
watch -n15 'aws ecs describe-services --cluster blog --services blog-backend \
  --query "services[0].deployments[].{status:status,desired:desiredCount,running:runningCount,rollout:rolloutState}" --output table'
```
**캡처:** PRIMARY/ACTIVE 두 배포가 겹치는 순간(옛것 draining, 새것 running) + 프로버 비-200=0 + 서킷브레이커가 안 걸리고 COMPLETED.
**면접:** "롤링 배포로 무중단 교체. 배포 서킷브레이커가 켜져 있어 나쁜 이미지면 자동 롤백 — apply도 wait_for_steady_state라 조용한 실패가 없다."

## 4. ALB 헬스체크가 태스크를 넣고 뺀다
```bash
# 타깃 헬스 실시간 — 배포/종료 중에 initial→healthy, draining 전이를 본다
TG=$(aws elbv2 describe-target-groups --names blog-backend \
  --query 'TargetGroups[0].TargetGroupArn' --output text)
watch -n10 "aws elbv2 describe-target-health --target-group-arn $TG \
  --query 'TargetHealthDescriptions[].{ip:Target.Id,state:TargetHealth.State}' --output table"
```
**캡처:** 새 태스크가 `initial`→`healthy`로, 내려가는 태스크가 `draining`으로 바뀌는 표(§2·§3 시연 중 같이).
**면접:** "`/api/health`(matcher 200)로 ALB가 healthy 태스크에만 라우팅, 드레이닝으로 in-flight를 끊지 않고 뺀다. stopTimeout 120s라 최대 60초 AI 요청도 안 잘린다."

## 5. 관측성 — 로그·지표
```bash
aws logs tail /ecs/blog-backend --since 30m --follow   # 구조화 로그 스트림
```
**캡처:** CloudWatch **로그 그룹 `/ecs/blog-backend`** 스트림 + ECS 서비스 **Metrics 탭**(CPU/메모리/요청).
**면접:** "태스크 로그·지표가 CloudWatch로 모여 콘솔·CLI로 관측 — EC2 시절 SSH로 `docker logs` 보던 것과 대비."

---

## 6. 정리(Stage 7) — 캡처 끝나면 즉시 과금 정지
```bash
# 1) 오리진을 EC2로 되돌린다(CloudFront가 ALB 참조를 끊게 — 안 하면 destroy가 막힌다)
terraform apply -var="api_backend=ec2" -var="backend_image_tag=<SHA>" -var="backend_origin_dns=<현재 EC2 DNS>"
# 2) ECS·RDS·ALB만 targeted destroy (공유 config라 bare destroy는 CloudFront·EC2·S3까지 지운다!)
terraform destroy \
  -target=aws_ecs_service.backend -target=aws_ecs_task_definition.backend \
  -target=aws_appautoscaling_policy.backend_cpu -target=aws_appautoscaling_target.backend \
  -target=aws_lb_listener.http -target=aws_lb_target_group.backend -target=aws_lb.backend \
  -target=aws_db_instance.main -target=aws_db_subnet_group.main \
  -var="backend_image_tag=<SHA>"
# 3) 확인: aws ecs describe-services / describe-db-instances 로 사라졌는지, 청구 대시보드로 과금 멈췄는지
```
**보존:** terraform 코드·이 문서·위 캡처(스크린샷/로그)는 **남긴다** = 인프라 없이도 증명이 남는 자산.
**면접:** "상시 운영은 EC2 on/off로 $0에 가깝게, 오케스트레이션은 크레딧으로 기간한정 증명 후 정리 — 비용을 의식한 아키텍처 결정."

---

## 순서 요약
프로버 켜기 → §1 부하/오토스케일 → §2 태스크 종료 → §3 롤링 배포 → §4 헬스(§2·3 중 관찰) → §5 로그/지표 캡처 → §6 정리.
한나절이면 충분하고, 실비용 ~$1 이하(시간당 ~$0.08).
