import { authHeaders } from './auth'

const BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000/api'

// 거친 메모 → AI가 정돈한 글 구조 마크다운. 로그인 필수(비용 보호)
export async function generateDraft(memo: string): Promise<string> {
  const res = await fetch(`${BASE}/ai/draft`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ memo }),
  })
  if (res.status === 401) throw new Error('로그인이 필요해')
  if (res.status === 503) throw new Error('AI 기능이 아직 설정 안 됐어 (서버에 API 키 필요)')
  if (!res.ok) throw new Error('AI 초안 생성에 실패했어')
  const data = await res.json()
  return data.markdown as string
}
