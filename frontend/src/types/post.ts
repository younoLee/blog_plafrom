export type Visibility = 'public' | 'private'

// 백엔드 PostRead 스키마와 같은 모양
export interface Post {
  id: number
  title: string
  content: string
  owner_id: number | null
  visibility: Visibility
  created_at: string
  updated_at: string
}
