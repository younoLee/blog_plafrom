export interface Comment {
  id: number
  post_id: number
  author: string
  content: string
  created_at: string
  // 로그인 계정이 쓴 댓글인가. **author를 신원으로 읽지 말 것** — 익명이 회원과 같은
  // 이름을 칠 수 있고, 실제로 그렇게 관리자 사칭 댓글이 달렸다(2026-08-10 무인증 재현).
  is_member: boolean
}
