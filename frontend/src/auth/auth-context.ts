import { createContext, useContext } from 'react'
import type { User } from '../api/auth'

export interface AuthState {
  user: User | null
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  register: (email: string, password: string) => Promise<void>
  logout: () => void
  // 서버에서 내 정보를 다시 불러와 갱신 (예: 결제 후 is_pro 반영)
  refreshUser: () => Promise<void>
}

export const AuthContext = createContext<AuthState | null>(null)

// 어디서든 로그인 상태를 꺼내 쓰는 훅
export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth는 AuthProvider 안에서만 쓸 수 있어')
  return ctx
}
