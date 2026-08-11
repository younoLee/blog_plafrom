import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { AuthProvider } from './auth/AuthProvider'
import ErrorBoundary from './components/ErrorBoundary'
import Layout from './components/Layout'
import HomePage from './pages/HomePage'
import PostDetailPage from './pages/PostDetailPage'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import WritePostPage from './pages/WritePostPage'
import StatusPage from './pages/StatusPage'
import PortalPage from './pages/PortalPage'
import AdminPage from './pages/AdminPage'
import SettingsPage from './pages/SettingsPage'
// **결제 화면만 lazy로 뗀다.** 라우트 코드분할 자체는 2026-08-10에 철회됐는데,
// 그 근거는 "RSS·정적아카이브로 유치한 유입의 LCP에 RTT 2개가 얹힌다"였다 —
// 즉 **글 읽기 경로**에 대한 판단이다. 이 화면은 그 경로가 아니다:
//   · 로그인 뒤에만 닿고, 익명 독자는 절대 안 온다(LCP에 영향 0)
//   · 프로드에서 결제는 구조적으로 항상 503이다(payments_require_live + 테스트 키).
//     유일한 계정인 admin은 `payments.py`가 400으로 막는다 — 즉 **아무도 못 쓰는 화면**이다
//   · 그런데 `@tosspayments/tosspayments-sdk`를 정적 import해서 그 무게를
//     **결제를 영원히 못 쓰는 방문자 전원**이 내려받고 있었다
// 기능은 그대로 둔다(포트폴리오 자산이고 되살리기도 쉽다). 무게만 뗀다.
// (2026-08-11 동료 리뷰)
import { lazy, Suspense } from 'react'
const PaymentPage = lazy(() => import('./pages/PaymentPage'))
import PaymentSuccessPage from './pages/PaymentSuccessPage'
import PaymentFailPage from './pages/PaymentFailPage'
import SubscriptionsPage from './pages/SubscriptionsPage'
import VerifyPage from './pages/VerifyPage'
import ForgotPasswordPage from './pages/ForgotPasswordPage'
import ResetPasswordPage from './pages/ResetPasswordPage'
import './App.css'

function App() {
  return (
    <ErrorBoundary>
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          {/* 모든 페이지가 Layout(공통 헤더) 아래에 들어감 */}
          <Route element={<Layout />}>
            {/* 통합 랜딩 */}
            <Route path="/" element={<PortalPage />} />
            {/* 블로그 (이전엔 / 였던 것들이 /blog 아래로) */}
            <Route path="/blog" element={<HomePage />} />
            <Route path="/blog/new" element={<WritePostPage />} />
            <Route path="/blog/posts/:id" element={<PostDetailPage />} />
            <Route path="/blog/posts/:id/edit" element={<WritePostPage />} />
            {/* 상태정보 */}
            <Route path="/status" element={<StatusPage />} />
            {/* 관리자 (페이지 안에서 admin 아니면 /blog로 리다이렉트) */}
            <Route path="/admin" element={<AdminPage />} />
            {/* 설정 (페이지 안에서 writer 아니면 /blog로 리다이렉트) */}
            <Route path="/settings" element={<SettingsPage />} />
            {/* Pro 구독 결제 (토스 결제창 → 승인검증 → is_pro 켜짐 → 상위 AI 모델 해금) */}
            <Route
              path="/pricing"
              element={
                <Suspense fallback={<p className="p-8 text-center text-gray-500">불러오는 중…</p>}>
                  <PaymentPage />
                </Suspense>
              }
            />
            <Route path="/payment/success" element={<PaymentSuccessPage />} />
            <Route path="/payment/fail" element={<PaymentFailPage />} />
            {/* 구독 관리 (글쓴이별 계정 구독 + 새 글 알림) */}
            <Route path="/subscriptions" element={<SubscriptionsPage />} />
            {/* 인증 (루트 유지) */}
            <Route path="/login" element={<LoginPage />} />
            <Route path="/register" element={<RegisterPage />} />
            <Route path="/verify" element={<VerifyPage />} />
            {/* /subscribe/confirm 은 뉴스레터 폐지(2026-07-31)와 함께 제거됨.
                옛 확인 메일 링크는 이제 없는 경로다 — 그 메일 자체를 더 이상 보내지 않는다. */}
            <Route path="/forgot" element={<ForgotPasswordPage />} />
            <Route path="/reset" element={<ResetPasswordPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
    </ErrorBoundary>
  )
}

export default App
