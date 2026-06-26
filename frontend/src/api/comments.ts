import type { Comment } from '../types/comment'

const BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000/api'

// 특정 글의 댓글 목록
export async function fetchComments(postId: number): Promise<Comment[]> {
  const res = await fetch(`${BASE}/posts/${postId}/comments`)
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
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ author, content }),
  })
  if (res.status === 422) throw new Error('이름(50자)·내용(2000자) 길이를 확인해줘. 빈칸은 안 돼')
  if (res.status === 429) throw new Error('댓글이 너무 잦아. 잠시 후 다시 해줘')
  if (!res.ok) throw new Error('댓글 작성 실패')
  return res.json()
}
