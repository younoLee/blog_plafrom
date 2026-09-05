export interface Comment {
  id: number
  post_id: number
  author: string
  content: string
  created_at: string
  // 로그인 계정이 쓴 댓글인가. **author를 신원으로 읽지 말 것** — 익명이 회원과 같은
  // 이름을 칠 수 있고, 실제로 그렇게 관리자 사칭 댓글이 달렸다(2026-08-10 무인증 재현).
  is_member: boolean
  // **보는 사람이 쓴 댓글인가.** 서버가 요청한 사람 기준으로 채운다(익명 댓글은 언제나
  // false). 화면은 이 값으로 '내 댓글 지우기·고치기'를 그린다 — 회원이 자기 오타를
  // 스스로 못 지우던 자리다(09-04 검사 GAP-5).
  is_mine: boolean
}
