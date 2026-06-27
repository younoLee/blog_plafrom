import { Link, Outlet } from 'react-router-dom'
import { useAuth } from '../auth/auth-context'
import { canWrite } from '../api/auth'
import { useTheme } from '../theme'
import { ui } from '../ui'
import { IconMoon, IconSun, IconPencil } from './icons'

function Layout() {
  const { user, logout } = useAuth()
  const { theme, toggle } = useTheme()

  return (
    <div className="min-h-screen bg-[#f5f5f7] text-[#1d1d1f] dark:bg-black dark:text-[#f5f5f7]">
      {/* 상단 고정 헤더 (모든 페이지 공통) — 애플풍 프로스티드 바 */}
      <header className="sticky top-0 z-10 border-b border-black/5 bg-[#f5f5f7]/70 backdrop-blur-xl dark:border-white/10 dark:bg-black/60">
        <div className="mx-auto flex max-w-3xl items-center justify-between px-4 py-3">
          <Link to="/" className="flex items-center gap-2 font-semibold tracking-tight">
            <img src="/favicon.svg" alt="" className="h-6 w-6" />
            <span>DEV 블로그</span>
          </Link>
          <nav className="flex items-center gap-1.5">
            {/* 테마 토글 — 동그란 아이콘 버튼 */}
            <button
              type="button"
              onClick={toggle}
              aria-label="테마 전환"
              className="grid h-9 w-9 place-items-center rounded-full text-gray-600 transition hover:bg-black/[0.06] dark:text-gray-300 dark:hover:bg-white/10"
            >
              {theme === 'dark' ? <IconSun className="h-5 w-5" /> : <IconMoon className="h-5 w-5" />}
            </button>
            {user ? (
              <>
                <span className="hidden text-sm text-gray-500 dark:text-gray-400 sm:inline">{user.email}</span>
                {/* 구독 관리는 로그인한 누구나 */}
                <Link to="/subscriptions" className={ui.btnGhost}>구독</Link>
                {/* 관리자만 보이는 메뉴 */}
                {user.role === 'admin' && (
                  <Link to="/admin" className={ui.btnGhost}>관리자</Link>
                )}
                {/* 글쓰기·설정은 승인된 사람(writer/admin)만 — pending은 안 보임 */}
                {canWrite(user) && (
                  <>
                    <Link to="/settings" className={ui.btnGhost}>설정</Link>
                    <Link to="/blog/new" className={ui.btnPrimary}>
                      <IconPencil className="h-4 w-4" />글쓰기
                    </Link>
                  </>
                )}
                <button type="button" onClick={logout} className={ui.btnGhost}>로그아웃</button>
              </>
            ) : (
              <>
                <Link to="/login" className={ui.btnGhost}>로그인</Link>
                <Link to="/register" className={ui.btnPrimary}>회원가입</Link>
              </>
            )}
          </nav>
        </div>
      </header>

      {/* 페이지 본문 */}
      <main className="mx-auto max-w-3xl px-4 py-12">
        <Outlet />
      </main>

      <footer className="mx-auto max-w-3xl px-4 py-12 text-center text-xs text-gray-400 dark:text-gray-500">
        © 2026 DEV 블로그 · FastAPI · React · Tailwind
      </footer>
    </div>
  )
}

export default Layout
