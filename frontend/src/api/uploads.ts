import { authHeaders } from './auth'

const BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000/api'

// 이미지 파일 업로드 → 저장된 이미지의 URL 반환
export async function uploadImage(file: File): Promise<string> {
  const form = new FormData()
  form.append('file', file)
  // 업로드는 승인된 사람만 가능 → 토큰 첨부 (Content-Type은 브라우저가 자동 설정)
  const res = await fetch(`${BASE}/upload`, {
    method: 'POST',
    headers: authHeaders(),
    body: form,
  })
  if (res.status === 400) throw new Error('이미지 파일만 올릴 수 있어')
  if (res.status === 401 || res.status === 403) throw new Error('업로드 권한이 없어 (승인 필요)')
  if (!res.ok) throw new Error('업로드 실패')
  const data = await res.json()
  return data.url as string
}
