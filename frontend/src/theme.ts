import { useState } from 'react'

export type Theme = 'light' | 'dark'

// 저장된 값 → 없으면 OS 설정 따름
export function getInitialTheme(): Theme {
  const saved = localStorage.getItem('theme')
  if (saved === 'dark' || saved === 'light') return saved
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

// <html>에 .dark 클래스 적용 + 저장
export function applyTheme(t: Theme) {
  document.documentElement.classList.toggle('dark', t === 'dark')
  localStorage.setItem('theme', t)
}

function currentTheme(): Theme {
  return document.documentElement.classList.contains('dark') ? 'dark' : 'light'
}

// 헤더 토글 버튼에서 쓰는 훅
export function useTheme() {
  const [theme, setTheme] = useState<Theme>(currentTheme())
  function toggle() {
    const next: Theme = theme === 'dark' ? 'light' : 'dark'
    applyTheme(next)
    setTheme(next)
  }
  return { theme, toggle }
}
