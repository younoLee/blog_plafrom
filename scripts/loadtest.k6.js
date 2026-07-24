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
  const path = r < 0.8 ? '/api/posts' : r < 0.9 ? '/api/blog-owner' : '/api/status'
  const res = http.get(`${BASE}${path}`)
  check(res, { 'status 200': (x) => x.status === 200 })
  sleep(0.5 + Math.random()) // 유저당 0.5~1.5초 간격
}
