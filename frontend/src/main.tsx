import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { applyTheme, getInitialTheme } from './theme'
import { installTranslateGuard } from './translateGuard'

// 자동번역(인앱 브라우저 등)이 DOM을 건드려도 React가 크래시 안 나게 — 렌더 전에 설치
installTranslateGuard()

// 렌더 전에 테마 적용 (라이트→다크 깜빡임 방지)
applyTheme(getInitialTheme())

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
