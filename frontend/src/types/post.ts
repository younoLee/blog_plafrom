// public: 전체공개 / subscribers: 구독자공개 / private: 나만 보기
export type Visibility = 'public' | 'subscribers' | 'private'

// 백엔드 PostRead 스키마와 같은 모양
export interface Post {
  id: number
  title: string
  content: string
  cover_image: string | null // 커버(대표) 이미지 URL, 없으면 null
  tags: string[] // 태그 (없으면 빈 배열)
  owner_id: number | null
  visibility: Visibility
  created_at: string
  updated_at: string
}

// 목록용 — 본문 전체 대신 발췌+읽기시간 (서버 PostSummary와 동일 모양)
export interface PostSummary {
  id: number
  title: string
  excerpt: string
  reading_minutes: number
  cover_image: string | null
  tags: string[]
  owner_id: number | null
  visibility: Visibility
  created_at: string
  updated_at: string
}
