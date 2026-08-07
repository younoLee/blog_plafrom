import { useEffect, useState } from 'react'
import { AuthContext } from './auth-context'
import type { User } from '../api/auth'
import * as authApi from '../api/auth'

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  // 앱 시작 시 저장된 토큰으로 내 정보 복구 (새로고침해도 로그인 유지)
  useEffect(() => {
    authApi
      .fetchMe()
      .then(setUser)
      .finally(() => setLoading(false))
  }, [])

  async function login(email: string, password: string) {
    await authApi.login(email, password)
    setUser(await authApi.fetchMe())
  }

  async function register(email: string, password: string) {
    // 이메일 인증 도입 후로는 가입해도 바로 로그인 안 함 (메일 인증 먼저)
    await authApi.register(email, password)
  }

  async function redeemInvite(token: string, password: string) {
    // 위 register와 반대로 **바로 로그인된다.** 초대는 관리자가 그 주소를 골라
    // 발급한 것이라 이메일 인증으로 소유를 다시 확인할 이유가 없다 → 기다릴 단계가 없다.
    await authApi.redeemInvite(token, password)
    setUser(await authApi.fetchMe())
  }

  function logout() {
    authApi.clearToken()
    setUser(null)
  }

  // 결제 등으로 서버 상태가 바뀐 뒤 내 정보를 다시 불러와 반영
  async function refreshUser() {
    setUser(await authApi.fetchMe())
  }

  return (
    <AuthContext.Provider
      value={{ user, loading, login, register, redeemInvite, logout, refreshUser }}
    >
      {children}
    </AuthContext.Provider>
  )
}
