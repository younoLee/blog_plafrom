import { useEffect, useState } from 'react'
import { AuthContext } from './auth-context'
import type { User } from '../api/auth'
import * as authApi from '../api/auth'
import { onSessionExpired } from '../api/session'

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)
  const [sessionEnded, setSessionEnded] = useState(false)

  // 앱 시작 시 저장된 토큰으로 내 정보 복구 (새로고침해도 로그인 유지)
  useEffect(() => {
    authApi
      .fetchMe()
      .then(setUser)
      .finally(() => setLoading(false))
  }, [])

  // 어떤 인증 요청이든 401을 받으면 화면을 비로그인으로 되돌린다.
  //
  // 이게 없으면 '좀비'가 생긴다 — 다른 기기에서 로그아웃했거나 비밀번호를 바꾸면
  // 이 기기의 토큰은 죽는데, 화면은 여전히 로그인된 것처럼 보이고 누르는 것마다
  // "로그인이 필요해"만 뜬다. 그 상태에서 로그인 화면으로 가는 길도 없다(헤더가
  // 로그인 버튼 대신 로그아웃을 보여주니까).
  // 그리고 **왜 풀렸는지 말해준다.** 조용히 비로그인으로 바뀌면 사용자는 자기가 뭘
  // 잘못 눌렀다고 생각한다. 이 통지는 내가 누른 로그아웃에서는 오지 않는다(api/auth.ts).
  useEffect(
    () =>
      onSessionExpired(() => {
        setUser(null)
        setSessionEnded(true)
      }),
    [],
  )

  async function login(email: string, password: string) {
    await authApi.login(email, password)
    // 다시 로그인했으면 안내는 제 역할을 끝냈다. 안 내리면 로그인한 화면에
    // "다시 로그인해줘"가 남는다.
    setSessionEnded(false)
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
    setSessionEnded(false)
    setUser(await authApi.fetchMe())
  }

  // 서버에도 알린다 — token_version이 올라가 다른 기기의 토큰까지 죽는다.
  // 서버가 꺼져 있어도(평소 상태다) 이 기기에서는 반드시 나간다: authApi.logout이 삼킨다.
  async function logout() {
    setSessionEnded(false)
    // **화면을 먼저 내린다.** authApi.logout은 보내기 전에 토큰을 지우므로, 이 await가
    // 끝날 때까지(절전이면 8초) 헤더는 로그인 상태인데 모든 요청은 익명으로 나간다.
    // 그 사이 NotificationBell 같은 주기 호출이 401을 받아도 Authorization 헤더가 없어
    // 만료 안내조차 안 뜨고, 사용자는 이유 없는 "로그인이 필요해"만 본다.
    setUser(null)
    await authApi.logout()
  }

  function dismissSessionNotice() {
    setSessionEnded(false)
  }

  // 결제 등으로 서버 상태가 바뀐 뒤 내 정보를 다시 불러와 반영
  async function refreshUser() {
    setUser(await authApi.fetchMe())
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        loading,
        login,
        register,
        redeemInvite,
        logout,
        refreshUser,
        sessionEnded,
        dismissSessionNotice,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}
