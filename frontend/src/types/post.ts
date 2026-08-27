// public: 전체공개 / subscribers: 구독자공개 / private: 나만 보기
export type Visibility = 'public' | 'subscribers' | 'private'

// 백엔드 PostRead 스키마와 같은 모양
export interface Post {
  id: number
  title: string
  content: string
  cover_image: string | null // 커버(대표) 이미지 URL, 없으면 null
  tags: string[] // 태그 (없으면 빈 배열)
  series: string | null // 연재 이름 (같은 이름끼리 한 시리즈), 없으면 null
  owner_id: number | null
  author_name: string | null
  author_handle: string | null
  visibility: Visibility
  created_at: string
  updated_at: string
}

// 연재 네비 (서버 SeriesNav와 동일 모양). 연재가 아니면 API가 null을 준다.
export interface SeriesItem {
  id: number
  title: string
  created_at: string
}

export interface SeriesNav {
  series: string
  total: number // 이 연재에서 '내가 볼 수 있는' 글 수
  index: number // 이 글이 몇 번째인지 (1부터)
  items: SeriesItem[]
  prev: SeriesItem | null // 이전 편(더 오래된 글)
  next: SeriesItem | null // 다음 편(더 최신 글)
}

// 목록용 — 본문 전체 대신 발췌+읽기시간 (서버 PostSummary와 동일 모양)
export interface PostSummary {
  id: number
  title: string
  excerpt: string
  reading_minutes: number
  cover_image: string | null
  tags: string[]
  series: string | null
  owner_id: number | null
  // 글쓴이 표시용 (2026-08-27). handle 은 **공개 블로그를 가질 수 있는 역할일 때만**
  // 서버가 채운다 — 차단된 사람의 `/@handle` 은 빈 목록이라 링크를 그리면 빈 페이지로
  // 보내게 된다. 그래서 화면은 `author_handle` 이 있을 때만 링크로, 없으면 이름만 그린다.
  author_name: string | null
  author_handle: string | null
  visibility: Visibility
  created_at: string
  updated_at: string
}
