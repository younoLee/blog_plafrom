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
            {/* 인증 (루트 유지) */}
            <Route path="/login" element={<LoginPage />} />
            <Route path="/register" element={<RegisterPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}

export default App
