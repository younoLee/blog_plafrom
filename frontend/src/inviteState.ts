import type { Invite } from './api/admin'

/**
 * 초대 한 줄의 상태 배지. **순서가 규칙이다** — 사용된 초대는 만료일이 지났어도
 * '사용됨'이지 '만료'가 아니다. 만료로 보이면 관리자가 '아무도 안 썼다'고 읽고
 * 같은 사람에게 초대를 다시 발급한다(그 사람은 이미 가입해 있다).
 *
 * **왜 화면 파일 밖에 있나 (09-04 검사 FQ-10)** — 관리자 화면은 시험이 0건이었고,
 * 이 우선순위는 순수 함수라 화면을 띄우지 않고도 잡을 수 있다. 다만 컴포넌트 파일에서
 * 함수를 같이 export 하면 Fast Refresh 규칙(react-refresh/only-export-components)에
 * 걸리므로 모듈로 뺀다 — postUtils.ts 와 같은 자리다.
 */
export function inviteState(inv: Invite): { label: string; badge: string } {
  if (inv.used_at) return { label: '사용됨', badge: 'bg-gray-100 text-gray-600 dark:bg-white/10 dark:text-gray-300' }
  if (new Date(inv.expires_at) <= new Date())
    return { label: '만료', badge: 'bg-red-100 text-red-700 dark:bg-red-500/15 dark:text-red-300' }
  return { label: '대기 중', badge: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300' }
}
