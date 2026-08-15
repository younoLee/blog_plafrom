import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { applyTheme, getInitialTheme } from './theme'
import { installTranslateGuard } from './translateGuard'
import { swapFontStylesheets } from './fontSwap'

// 자동번역(인앱 브라우저 등)이 DOM을 건드려도 React가 크래시 안 나게 — 렌더 전에 설치
installTranslateGuard()

// index.html이 폰트 CSS를 media="print"(= 렌더를 막지 않음)로 실었다. 여기서 되돌려
// 실제로 적용시킨다. 이유와 함정은 fontSwap.ts에.
swapFontStylesheets()

// 렌더 전에 테마 적용 (라이트→다크 깜빡임 방지)
applyTheme(getInitialTheme())

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
