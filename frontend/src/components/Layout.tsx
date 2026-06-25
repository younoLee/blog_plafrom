import { Link, Outlet } from 'react-router-dom'
import { useAuth } from '../auth/auth-context'
import { useTheme } from '../theme'
import { ui } from '../ui'

function Layout() {
  const { user, logout } = useAuth()
  const { theme, toggle } = useTheme()

  return (
    <div className="min-h-screen bg-gray-50 text-gray-800 dark:bg-gray-900 dark:text-gray-100">
      {/* 상단 고정 헤더 (모든 페이지 공통) */}
      <header className="sticky top-0 z-10 border-b border-gray-200 bg-white/80 backdrop-blur dark:border-gray-800 dark:bg-gray-900/80">
        <div className="mx-auto flex max-w-3xl items-center justify-between px-4 py-3">
          <Link to="/" className="text-lg font-bold tracking-tight text-gray-900 dark:text-white">
            📝 <span className="text-indigo-600 dark:text-indigo-400">DEV</span> 블로그
          </Link>
          <nav className="flex items-center gap-2">
            {/* 테마 토글 */}
            <button
              type="button"
              onClick={toggle}
              aria-label="테마 전환"
              className={ui.btnGhost}
            >
              {theme === 'dark' ? '☀️' : '🌙'}
            </button>
            {user ? (
              <>
                <span className="hidden text-sm text-gray-600 dark:text-gray-300 sm:inline">{user.email}</span>
                <Link to="/blog/new" className={ui.btnPrimary}>✏️ 글쓰기</Link>
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
      <main className="mx-auto max-w-3xl px-4 py-8">
        <Outlet />
      </main>

      <footer className="mx-auto max-w-3xl px-4 py-10 text-center text-xs text-gray-500 dark:text-gray-400">
        © 2026 DEV 블로그 · FastAPI · React · Tailwind
      </footer>
    </div>
  )
}

export default Layout
