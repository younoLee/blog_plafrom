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
