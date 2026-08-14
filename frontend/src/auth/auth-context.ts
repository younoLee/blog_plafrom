import { createContext, useContext } from 'react'
import type { User } from '../api/auth'

export interface AuthState {
  user: User | null
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  register: (email: string, password: string) => Promise<void>
  // 초대 링크로 가입. 이메일을 받지 않는 게 핵심 — 주소는 토큰에 묶여 있고 서버가 정한다.
  // 이메일 인증 단계가 없으므로(관리자가 주소를 보증했다) 끝나면 곧바로 로그인 상태다.
  redeemInvite: (token: string, password: string) => Promise<void>
  // 서버에도 알린다(token_version +1) → **모든 기기**에서 로그아웃된다.
  // 서버가 꺼져 있으면 이 기기만 나간다 — 절전이 평상시라 실패를 막지 않는다.
  logout: () => Promise<void>
  // 서버에서 내 정보를 다시 불러와 갱신 (예: 결제 후 is_pro 반영)
  refreshUser: () => Promise<void>
  /**
   * 내가 누르지 않았는데 로그인이 풀렸다 — 다른 기기에서 로그아웃했거나, 비밀번호를
   * 바꿨거나, 토큰이 만료됐다. 화면이 조용히 비로그인으로 바뀌면 사용자는 자기가
   * 뭘 잘못 눌렀다고 생각한다. Layout이 이걸 보고 안내 띠를 띄운다.
   *
   * 내가 누른 로그아웃에서는 **켜지지 않는다**(api/auth.ts의 logout이 보내기 전에
   * 토큰을 지운다 → 401이 와도 만료 통지가 안 나간다).
   */
  sessionEnded: boolean
  dismissSessionNotice: () => void
}

export const AuthContext = createContext<AuthState | null>(null)

// 어디서든 로그인 상태를 꺼내 쓰는 훅
export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth는 AuthProvider 안에서만 쓸 수 있어')
  return ctx
}
