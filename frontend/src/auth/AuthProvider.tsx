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

  function logout() {
    authApi.clearToken()
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  )
}
