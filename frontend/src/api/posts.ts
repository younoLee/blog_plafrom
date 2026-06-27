import type { Post, Visibility } from '../types/post'
import { authHeaders } from './auth'

// 백엔드 주소 (나중에 환경변수로 빼면 좋음)
const BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000/api'

// 글 목록 (로그인했으면 내 비공개글도 포함되도록 토큰 첨부)
export async function fetchPosts(): Promise<Post[]> {
  const res = await fetch(`${BASE}/posts`, { headers: authHeaders() })
  if (!res.ok) throw new Error('목록 불러오기 실패')
  return res.json()
}

// 글 단건 조회 (비공개글은 본인 토큰 있어야 200)
export async function getPost(id: number): Promise<Post> {
  const res = await fetch(`${BASE}/posts/${id}`, { headers: authHeaders() })
  if (res.status === 404) throw new Error('글을 찾을 수 없어')
  if (!res.ok) throw new Error('글 불러오기 실패')
  return res.json()
}

// 글 작성 (로그인 필수)
export async function createPost(
  title: string,
  content: string,
  visibility: Visibility,
): Promise<Post> {
  const res = await fetch(`${BASE}/posts`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ title, content, visibility }),
  })
  if (res.status === 401) throw new Error('로그인이 필요해')
  if (res.status === 403) throw new Error('글쓰기 권한이 없어 (관리자 승인 필요)')
  if (res.status === 422) throw new Error('제목(200자)·내용(5만자) 길이를 확인해줘. 빈칸은 안 돼')
  if (res.status === 429) throw new Error('글 작성이 너무 잦아. 잠시 후 다시 해줘')
  if (!res.ok) throw new Error('작성 실패')
  return res.json()
}

// 글 수정 (소유자만)
export async function updatePost(
  id: number,
  title: string,
  content: string,
  visibility: Visibility,
): Promise<Post> {
  const res = await fetch(`${BASE}/posts/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ title, content, visibility }),
  })
  if (res.status === 403) throw new Error('내 글만 수정할 수 있어')
  if (res.status === 422) throw new Error('제목(200자)·내용(5만자) 길이를 확인해줘. 빈칸은 안 돼')
  if (res.status === 429) throw new Error('수정이 너무 잦아. 잠시 후 다시 해줘')
  if (!res.ok) throw new Error('수정 실패')
  return res.json()
}

// 공개범위만 변경 (작성 후 빠른 전환, 소유자/관리자만)
export async function changeVisibility(
  id: number,
  visibility: Visibility,
): Promise<Post> {
  const res = await fetch(`${BASE}/posts/${id}/visibility`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ visibility }),
  })
  if (res.status === 403) throw new Error('내 글만 공개범위를 바꿀 수 있어')
  if (!res.ok) throw new Error('공개범위 변경 실패')
  return res.json()
}

// 글 삭제 (소유자만, 성공 시 204)
export async function deletePost(id: number): Promise<void> {
  const res = await fetch(`${BASE}/posts/${id}`, {
    method: 'DELETE',
    headers: authHeaders(),
  })
  if (res.status === 403) throw new Error('내 글만 삭제할 수 있어')
  if (!res.ok) throw new Error('삭제 실패')
}
