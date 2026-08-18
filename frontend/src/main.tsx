// **이 줄이 맨 위여야 한다.** 모듈은 import 순서대로 실행되므로 아래로 내려가면
// react-markdown이 먼저 평가된다(사유는 polyfills.ts).
import './polyfills'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { applyTheme, getInitialTheme } from './theme'
import { installTranslateGuard } from './translateGuard'
import { swapFontStylesheets } from './fontSwap'
import { applyCachedSkin, refreshSkin } from './api/skin'

// 자동번역(인앱 브라우저 등)이 DOM을 건드려도 React가 크래시 안 나게 — 렌더 전에 설치
installTranslateGuard()

// index.html이 폰트 CSS를 media="print"(= 렌더를 막지 않음)로 실었다. 여기서 되돌려
// 실제로 적용시킨다. 이유와 함정은 fontSwap.ts에.
swapFontStylesheets()

// 렌더 전에 테마 적용 (라이트→다크 깜빡임 방지)
applyTheme(getInitialTheme())

// 저장해 둔 블로그 스킨을 렌더 전에 바른다. 테마와 같은 이유(깜빡임)이고,
// 여기선 이유가 하나 더 있다 — 이 사이트는 서버를 평소 꺼두므로 서버 응답을
// 기다리면 **평상시 방문에는 스킨이 아예 안 보인다.** 캐시가 먼저다.
applyCachedSkin()
// 그다음 서버에 최신 값을 물어본다. 실패(절전)해도 조용히 넘어가고 위에서 바른
// 캐시가 그대로 남는다. 렌더를 막지 않도록 await 하지 않는다.
void refreshSkin()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
