import type { Post, PostSummary, SeriesNav, Visibility } from '../types/post'
import { authHeaders } from './auth'

// 백엔드 주소 (나중에 환경변수로 빼면 좋음)
const BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000/api'

// 한 쪽에 보여줄 글 수. 서버 상한은 50 (그 이상 요청하면 422)
export const POSTS_PAGE_SIZE = 10

export type PostListResult = {
  items: PostSummary[]
  total: number // 필터 적용 후 전체 개수 (페이지 UI용)
  limit: number
  offset: number
}

// 글 목록 (로그인했으면 내 비공개글도 포함되도록 토큰 첨부)
// q=검색어, tag=태그 필터, limit/offset=페이지
export async function fetchPosts(
  opts: { q?: string; tag?: string; limit?: number; offset?: number } = {},
): Promise<PostListResult> {
  const params = new URLSearchParams()
  if (opts.q) params.set('q', opts.q)
  if (opts.tag) params.set('tag', opts.tag)
  params.set('limit', String(opts.limit ?? POSTS_PAGE_SIZE))
  params.set('offset', String(opts.offset ?? 0))

  const res = await fetch(`${BASE}/posts?${params}`, { headers: authHeaders() })
  if (res.status === 429) throw new Error('요청이 너무 잦아. 잠시 후 다시 해줘')
  if (!res.ok) throw new Error('목록 불러오기 실패')
  const data = await res.json()
  // 배열을 주던 옛 백엔드와의 호환: 프론트·백엔드 배포 사이 잠깐 구버전이 응답할 수 있다
  if (Array.isArray(data)) {
    return { items: data, total: data.length, limit: data.length, offset: 0 }
  }
  return data
}

export type TagCount = { tag: string; count: number }

export type PostMetaResult = {
  total: number
  tags: TagCount[]
  recent: PostSummary[]
}

// 사이드바용 집계(전체 글 수·태그별 개수·최근 글).
// 목록이 페이지로 끊기므로 사이드바는 목록이 아니라 이걸 봐야 한다
// (안 그러면 2쪽에서 태그 목록·글 수가 그 페이지 기준으로 틀어짐).
export async function fetchPostsMeta(): Promise<PostMetaResult> {
  const res = await fetch(`${BASE}/posts/meta`, { headers: authHeaders() })
  if (!res.ok) throw new Error('사이드바 정보 불러오기 실패')
  return res.json()
}

// 이 글이 속한 연재의 목록·이전/다음. 연재가 아니면 null.
// 상세 응답에 안 넣고 따로 부르는 이유: 연재가 아닌 글이 대부분인데
// 매 상세 조회마다 연재 질의를 얹을 이유가 없다.
export async function fetchSeries(postId: number): Promise<SeriesNav | null> {
  const res = await fetch(`${BASE}/posts/${postId}/series`, { headers: authHeaders() })
  if (!res.ok) return null // 연재 정보는 부가기능 — 실패해도 글 읽기를 막지 않는다
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
  coverImage: string | null,
  tags: string[],
  series: string | null,
  visibility: Visibility,
): Promise<Post> {
  const res = await fetch(`${BASE}/posts`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ title, content, cover_image: coverImage, tags, series, visibility }),
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
  coverImage: string | null,
  tags: string[],
  series: string | null,
  visibility: Visibility,
): Promise<Post> {
  const res = await fetch(`${BASE}/posts/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ title, content, cover_image: coverImage, tags, series, visibility }),
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
