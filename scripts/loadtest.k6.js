// ECS Stage 6 '증명'용 부하 스크립트 (k6).
//
// 목적: Fargate 오토스케일(CPU 타깃 60%)이 실제로 스케일아웃→인 하는 걸 유발·관찰한다.
// 대상: CloudFront /api/posts (CachingDisabled라 매 요청이 오리진=ECS 태스크에 도달).
//   ※ /api/* 는 ALB SG가 CloudFront prefix list만 받으므로 랩탑에서 ALB를 직접 못 친다 →
//     반드시 CloudFront 도메인으로 때린다(정상 경로 부하라 더 현실적이기도 하다).
//
// ⚠️ 절대 금지: /api/ai/draft 등 AI 엔드포인트는 부하 대상에 넣지 마라 — 서버 Claude 비용 +
//   시간당 캡(10)이라 부하도 안 되고 돈만 샌다. 읽기 경로(posts/blog-owner)만 때린다.
//
// 실행:
//   BASE_URL=https://d2j66m9udyg9yq.cloudfront.net k6 run scripts/loadtest.k6.js
//   # VUs가 부족해 CPU가 60%를 못 넘으면 stages의 target을 올려가며 조정한다
//   # (0.25 vCPU라 보통 수십 VU면 넘는다 — CloudWatch ECS CPUUtilization 그래프를 보며 맞춘다).
//
// 필요: k6 (https://k6.io). 설치 없이 간단히 보려면 hey 한 줄:
//   hey -z 5m -c 50 https://d2j66m9udyg9yq.cloudfront.net/api/posts

import http from 'k6/http'
import { check, sleep } from 'k6'

const BASE = __ENV.BASE_URL || 'https://d2j66m9udyg9yq.cloudfront.net'

export const options = {
  // 램프: 천천히 올려 CPU>60%로 스케일아웃 유발 → 유지 → 내려 스케일인(쿨다운 5분) 관찰.
  stages: [
    { duration: '2m', target: 30 }, // 워밍업
    { duration: '3m', target: 60 }, // CPU를 60% 위로 밀어 scale-out 유발
    { duration: '4m', target: 60 }, // 유지 — desired 2→3→4 로 느는 걸 관찰
    { duration: '5m', target: 0 },  // 부하 제거 — scale-in(5분 쿨다운) 관찰
  ],
  thresholds: {
    http_req_failed: ['rate<0.02'], // 오리진이 견디면 실패율 2% 미만 (무중단 근거)
    http_req_duration: ['p(95)<2000'],
  },
}

export default function () {
  // 대부분 글 목록(DB 쿼리+직렬화로 CPU 소모), 가끔 다른 읽기 경로 섞어 캐시·단조로움 회피.
  const r = Math.random()
  // `?q=`를 섞는다. 2026-08-26 병목검사 실측: 검색 한 건이 /api/health의 **203배**
  // (약 2.6초)이고, `?limit=10` 기본 목록의 약 27배다. 그런데 이 스크립트는 08-26까지
  // /api/posts·/api/blog-owner·/api/status 셋만 때려 **가장 비싼 경로를 정확히 비켜갔다.**
  // 원인은 본문 전체 ILIKE인데 GIN 인덱스 3종이 idx_scan=0으로 한 번도 안 탄다
  // (본문이 TOAST로 빠져 main heap이 11페이지라 플래너가 Seq Scan을 공짜로 오판한다).
  //
  // 비중을 10%로 낮게 잡은 이유: 이건 처리량을 재려는 게 아니라 **한 요청의 단가가
  // 다른 것과 수십 배 다르다는 사실**을 부하에 반영하려는 것이다. 더 올리면 리미터가
  // 먼저 걸려(60/분) 서버가 아니라 리미터를 재게 된다.
  //
  // 길이를 셋으로 나눈다 — trgm 인덱스는 3글자(trigram) 미만이면 원리적으로 못 탄다.
  // 2글자와 3글자의 비용 차이가 인덱스가 살아났는지를 보는 신호다.
  const Q = ['', '검색', '커넥션']
  let path
  if (r < 0.7) path = '/api/posts'
  else if (r < 0.8) path = `/api/posts?limit=10&q=${encodeURIComponent(Q[1 + (Math.random() < 0.5 ? 0 : 1)])}`
  else if (r < 0.9) path = '/api/blog-owner'
  else path = '/api/status'
  const res = http.get(`${BASE}${path}`)
  // 429는 실패가 아니라 **리미터가 동작한 것**이다. 섞어 세면 오리진 용량을 재는
  // http_req_failed 임계가 리미터 때문에 깨져 무엇을 쟀는지 알 수 없게 된다.
  check(res, { 'status 200 or 429': (x) => x.status === 200 || x.status === 429 })
  sleep(0.5 + Math.random()) // 유저당 0.5~1.5초 간격
}
