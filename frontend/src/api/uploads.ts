const BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000/api'

// 이미지 파일 업로드 → 저장된 이미지의 URL 반환
export async function uploadImage(file: File): Promise<string> {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch(`${BASE}/upload`, { method: 'POST', body: form })
  if (res.status === 400) throw new Error('이미지 파일만 올릴 수 있어')
  if (!res.ok) throw new Error('업로드 실패')
  const data = await res.json()
  return data.url as string
}
