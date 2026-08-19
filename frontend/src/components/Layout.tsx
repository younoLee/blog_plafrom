import { Link, Outlet } from 'react-router-dom'
import { useAuth } from '../auth/auth-context'
import { canWrite } from '../api/auth'
import { useTheme } from '../theme'
import { ui } from '../ui'
import { HtmlSlot } from './HtmlSlot'
import { IconMoon, IconSun, IconPencil } from './icons'
import { NotificationBell } from './NotificationBell'

function Layout() {
  const { user, logout, sessionEnded, dismissSessionNotice } = useAuth()
  const { theme, toggle } = useTheme()

  return (
    <div className="min-h-screen bg-canvas text-ink">
      {/* 본문 바로가기 — 평소엔 안 보이고 탭을 처음 누르면 나타난다.
          헤더에 포커스 정류장이 8개 넘게 있어서(테마·종·구독·Pro·관리자·설정·글쓰기·로그아웃)
          키보드나 화면낭독기 사용자는 **글마다** 그걸 다 지나야 본문에 닿았다.
          sr-only만 쓰면 포커스됐을 때도 안 보이므로 focus: 로 되돌린다. */}
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-20 focus:rounded-btn focus:bg-accent focus:px-4 focus:py-2 focus:text-sm focus:text-on-accent"
      >
        본문 바로가기
      </a>
      {/* 상단 고정 헤더 (모든 페이지 공통) — 애플풍 프로스티드 바 */}
      <header data-skin="header" className="sticky top-0 z-10 border-b border-black/5 bg-canvas/70 backdrop-blur-xl dark:border-white/10 dark:bg-canvas/60">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-y-2 px-4 py-3">
          {/* 로고 그림을 뺐다(2026-08-18). public/favicon.svg는 흐린 타원 16개를 겹쳐
              만든 보라 그라데이션 번개인데, 그 모양 자체가 '자동으로 만들어진 표식'으로
              읽힌다. 참고로 본 D2·velog는 둘 다 글자만 쓴다 — 이름이 곧 표식이다.
              탭 아이콘(favicon)과 PWA 아이콘은 그대로 둔다. 그건 이름을 정한 뒤에
              같이 만드는 게 맞고, 지금 지우면 탭에 빈 칸이 남는다. */}
          <Link to="/" data-skin="brand" className="flex shrink-0 items-center font-semibold tracking-tight">
            블로그 만들기
          </Link>
          {/* 버튼이 많아 좁은 화면에선 넘침 → flex-wrap으로 다음 줄로 자연스럽게 줄바꿈 */}
          <nav data-skin="nav" className="flex flex-wrap items-center justify-end gap-1.5">
            {/* 테마 토글 — 동그란 아이콘 버튼 */}
            <button
              type="button"
              onClick={toggle}
              aria-label="테마 전환"
              className="grid h-9 w-9 place-items-center rounded-btn text-gray-600 transition hover:bg-black/[0.06] dark:text-gray-300 dark:hover:bg-white/10"
            >
              {theme === 'dark' ? <IconSun className="h-5 w-5" /> : <IconMoon className="h-5 w-5" />}
            </button>
            {user ? (
              <>
                {/* 헤더 알림 종 (안 읽음 배지 + 드롭다운) */}
                <NotificationBell />
                <span className="hidden text-sm text-gray-500 dark:text-gray-400 sm:inline">{user.email}</span>
                {/* 구독 관리는 로그인한 누구나 */}
                <Link to="/subscriptions" className={ui.btnGhost}>구독</Link>
                {/* Pro 결제 (상위 AI 모델 해금). 이미 Pro면 살짝 강조 */}
                <Link
                  to="/pricing"
                  className={user.is_pro || user.role === 'admin' ? ui.btnGhost : ui.btnPrimary}
                >
                  {user.is_pro || user.role === 'admin' ? 'Pro ✓' : 'Pro'}
                </Link>
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
                {/* 2026-08-14부터 서버에도 알린다 — 이 계정의 **모든 기기**가 함께 로그아웃된다.
                    라벨은 '로그아웃'으로 두되 title로 범위를 밝힌다: 헤더에 긴 문구를 넣으면
                    좁은 화면에서 줄이 무너지는데, 범위를 숨기면 기기 분실 때 잘못 믿게 된다. */}
                <button
                  type="button"
                  onClick={() => void logout()}
                  title="모든 기기에서 로그아웃돼"
                  className={ui.btnGhost}
                >
                  로그아웃
                </button>
              </>
            ) : (
              // 가입은 초대제로 닫아둠 → 헤더엔 로그인만 노출 (자세한 안내는 /register 화면)
              <Link to="/login" className={ui.btnPrimary}>로그인</Link>
            )}
          </nav>
        </div>
      </header>

      {/* 세션이 **내가 안 눌렀는데** 끝났을 때의 안내.
          왜 필요한가: 다른 기기에서 로그아웃하거나 비밀번호를 바꾸면 이 기기의 토큰이
          죽는다. 그때 화면만 조용히 비로그인으로 바뀌면 사용자는 자기가 뭘 잘못 눌렀다고
          생각하고, 쓰던 글이 안 올라간 이유도 모른다.
          왜 헤더 아래 띠인가: 이 저장소엔 토스트 장치가 없고, 만들면 이 한 줄을 위해
          전역 상태·타이머·포털이 생긴다. 띠는 스스로 사라지지 않아서 **놓칠 수 없다**는
          장점이 오히려 맞다 — 놓치면 안 되는 안내다.
          role="alert"인 이유: 이 띠는 **나타나면서** 글자를 함께 들고 온다.
          role="status"(polite)는 이미 떠 있던 영역의 글자가 바뀔 때 읽히고, 내용을
          품은 채 새로 삽입되면 화면낭독기가 그냥 지나치는 경우가 많다. 그러면
          낭독기 사용자만 정확히 '조용한 로그아웃'을 겪는다 — 이 띠가 막으려던 그 일이다.
          저장소의 다른 오류 안내(LoginPage·WritePostPage)도 role="alert"를 쓴다. */}
      {sessionEnded && (
        <div
          role="alert"
          className="border-b border-amber-500/20 bg-amber-50 text-amber-900 dark:border-amber-400/20 dark:bg-amber-500/10 dark:text-amber-200"
        >
          <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-2 px-4 py-2.5 text-sm">
            <span>로그인이 풀렸어 — 다른 기기에서 로그아웃했거나 세션이 만료된 거야.</span>
            <span className="flex items-center gap-1.5">
              {!user && (
                <Link to="/login" className={ui.btnPrimary} onClick={dismissSessionNotice}>
                  다시 로그인
                </Link>
              )}
              <button
                type="button"
                onClick={dismissSessionNotice}
                aria-label="안내 닫기"
                className="rounded-btn px-2 py-1 text-lg leading-none transition hover:bg-black/[0.06] dark:hover:bg-white/10"
              >
                ×
              </button>
            </span>
          </div>
        </div>
      )}

      {/* 페이지 본문 */}
      <main id="main" data-skin="main" tabIndex={-1} className="mx-auto max-w-7xl px-4 py-12">
        <Outlet />
      </main>

      <footer data-skin="footer" className="mx-auto max-w-7xl px-4 py-12 text-center text-xs text-gray-500 dark:text-gray-400">
        {/* 주인(또는 `/@handle`을 보는 중이면 그 사람)이 쓴 문장. 비어 있으면 아무것도
            안 그린다. 링크 줄 **위**에 두는 이유: 이건 사람이 쓴 말이고 아래는 사이트가
            제공하는 길이다. 아래에 두면 사람 말이 각주처럼 읽힌다. */}
        <HtmlSlot slot="footer" className="mx-auto mb-5 max-w-xl text-sm" />
        © 2026 블로그 만들기 · FastAPI · React · Tailwind
        {/* 정적 아카이브와 피드. 서버(EC2)가 꺼져 있어도 열리는 경로라, 절전 중에
            글 목록이 안 뜰 때 여기로 빠져나갈 수 있다. React Router가 가로채면
            안 되므로(SPA 라우트가 아니라 S3의 실제 파일이다) <a>를 쓴다. */}
        <span className="mx-1.5">·</span>
        <Link to="/about" className="hover:underline">소개</Link>
        <span className="mx-1.5">·</span>
        <a href="/devlog.html" className="hover:underline">개발일지 아카이브</a>
        <span className="mx-1.5">·</span>
        {/* 32편에서 뽑은 함정·교훈 239건. 정적 페이지라 서버가 꺼져 있어도 열린다. */}
        <a href="/lessons.html" className="hover:underline">함정과 교훈</a>
        <span className="mx-1.5">·</span>
        <a href="/rss.xml" className="hover:underline">RSS</a>
      </footer>
    </div>
  )
}

export default Layout
