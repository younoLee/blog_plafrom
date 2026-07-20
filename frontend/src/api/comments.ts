import type { Comment } from '../types/comment'
import { authHeaders } from './auth'
import { fetchWithTimeout } from './http'

const BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000/api'

// 특정 글의 댓글 목록.
// 인증 헤더 필수: 백엔드가 글 열람권한(can_view)을 확인하므로, 비공개·구독자공개 글은
// 로그인 토큰을 보내야 소유자/구독자가 댓글을 읽을 수 있음(없으면 익명 취급 → 404).
export async function fetchComments(postId: number): Promise<Comment[]> {
  const res = await fetchWithTimeout(`${BASE}/posts/${postId}/comments`, { headers: authHeaders() })
  if (!res.ok) throw new Error('댓글 불러오기 실패')
  return res.json()
}

// 댓글 작성
export async function addComment(
  postId: number,
  author: string,
  content: string,
): Promise<Comment> {
  const res = await fetch(`${BASE}/posts/${postId}/comments`, {
    method: 'POST',
    // 인증 헤더 포함: 비공개·구독자공개 글에도 댓글을 달 수 있고(권한 확인 통과),
    // 로그인 사용자는 백엔드가 작성자명을 계정으로 고정(사칭 방지).
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ author, content }),
  })
  if (res.status === 422) throw new Error('이름(50자)·내용(2000자) 길이를 확인해줘. 빈칸은 안 돼')
  if (res.status === 429) throw new Error('댓글이 너무 잦아. 잠시 후 다시 해줘')
  if (!res.ok) throw new Error('댓글 작성 실패')
  return res.json()
}

// 댓글 삭제 (글 작성자 본인 또는 관리자만 — 모더레이션)
export async function deleteComment(postId: number, commentId: number): Promise<void> {
  const res = await fetch(`${BASE}/posts/${postId}/comments/${commentId}`, {
    method: 'DELETE',
    headers: authHeaders(),
  })
  if (!res.ok) throw new Error('댓글 삭제 실패')
}
