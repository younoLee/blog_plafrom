import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    // assets를 별도 폴더 없이 dist 최상위에 평평하게 출력
    // → S3 업로드 시 폴더 없이 파일만 올리면 됨
    assetsDir: '',
  },
})
