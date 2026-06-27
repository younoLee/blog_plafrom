import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { AuthProvider } from './auth/AuthProvider'
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
import SubscriptionsPage from './pages/SubscriptionsPage'
import VerifyPage from './pages/VerifyPage'
import ForgotPasswordPage from './pages/ForgotPasswordPage'
import ResetPasswordPage from './pages/ResetPasswordPage'
import './App.css'

function App() {
  return (
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
            {/* 구독 관리 (계정 구독 + 이메일 구독) */}
            <Route path="/subscriptions" element={<SubscriptionsPage />} />
            {/* 인증 (루트 유지) */}
            <Route path="/login" element={<LoginPage />} />
            <Route path="/register" element={<RegisterPage />} />
            <Route path="/verify" element={<VerifyPage />} />
            <Route path="/forgot" element={<ForgotPasswordPage />} />
            <Route path="/reset" element={<ResetPasswordPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}

export default App
