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
    // **지원 하한을 명시한다.** Vite 8의 기본값은 safari16.4/ios16.4(2023년 3월)이고,
    // 그건 우리가 고른 값이 아니라 도구가 정한 값이다. 그 위에서 도는 걸 확인한
    // 실제 하한은 **사파리 15.4**다 — react-markdown이 Object.hasOwn(15.4)을 쓰기
    // 때문이고, 그건 src/polyfills.ts가 메워서 15.4 미만도 살린다.
    //
    // 지금 번들엔 15.4가 못 읽는 문법이 없어서(class static 블록·private 필드·
    // 새 정규식 플래그 0회, 최상위 await는 15.0부터) 이 값을 낮춰도 출력이 거의
    // 안 변한다. 그래도 적어두는 이유는, 나중에 의존성 하나가 새 문법을 들여오면
    // 기본값에서는 **조용히** 옛 사파리만 죽기 때문이다. 여기 적혀 있으면 그때
    // esbuild가 대신 낮춰준다.
    target: ['es2021', 'safari15.4', 'ios15.4', 'chrome100', 'edge100', 'firefox100'],
  },
})
