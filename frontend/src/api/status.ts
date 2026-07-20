import { fetchWithTimeout } from './http'
const BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000/api'

// 백엔드 /status 응답 구조 (main.py의 status()와 일치)
export interface StatusInfo {
  backend: string // "ok"
  database: string // "ok" | "down"
  mail: string // "ok" | "down"
  stats: {
    posts: number | null
    subscribers: number | null
  }
  checked_at: string // ISO 시각
}

// 서비스 상태 조회. 실패 시 에러 throw
export async function fetchStatus(): Promise<StatusInfo> {
  const res = await fetchWithTimeout(`${BASE}/status`)
  if (!res.ok) throw new Error('상태 조회 실패')
  return res.json()
}

// 하루치 업타임 (uptime: 0~1, null이면 그날 데이터 없음 = 서버 꺼져 있던 날)
export interface DayUptime {
  date: string
  uptime: number | null
  checks: number
}

// 서비스 한 개(백엔드/DB/메일)의 업타임 기록
export interface ServiceUptime {
  name: string
  label: string
  overall_uptime: number | null // 그 서비스의 전체 기간 평균
  days: DayUptime[]
}

export interface UptimeHistory {
  services: ServiceUptime[]
  total_checks: number
}

// 최근 N일 일별 업타임 기록 조회
export async function fetchHistory(days = 30): Promise<UptimeHistory> {
  const res = await fetchWithTimeout(`${BASE}/status/history?days=${days}`)
  if (!res.ok) throw new Error('업타임 기록 조회 실패')
  return res.json()
}
