// 앱에서 쓰는 선(line) 아이콘 모음 — 이모지 대신 SVG로 직접 그린다.
// currentColor를 쓰므로 글자색/다크모드에 자동으로 맞춰지고, 크기는 className(예: "h-5 w-5")으로 조절한다.
import type { ReactNode, SVGProps } from 'react'

type IconProps = SVGProps<SVGSVGElement>

// 공통 틀: 24x24 좌표계, 선 굵기 1.8, 끝은 둥글게 (애플/Feather 스타일)
function Base({ children, ...props }: IconProps & { children: ReactNode }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      {children}
    </svg>
  )
}

// 문서/글 (블로그)
export const IconNote = (p: IconProps) => (
  <Base {...p}>
    <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
    <path d="M14 3v5h5" />
    <path d="M9 13h6M9 17h6" />
  </Base>
)

// 달 (다크모드)
export const IconMoon = (p: IconProps) => (
  <Base {...p}>
    <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
  </Base>
)

// 해 (라이트모드)
export const IconSun = (p: IconProps) => (
  <Base {...p}>
    <circle cx="12" cy="12" r="4.2" />
    <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
  </Base>
)

// 연필 (글쓰기/수정)
export const IconPencil = (p: IconProps) => (
  <Base {...p}>
    <path d="M12 20h9" />
    <path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4z" />
  </Base>
)

// 자물쇠 (비공개)
export const IconLock = (p: IconProps) => (
  <Base {...p}>
    <rect x="4.5" y="11" width="15" height="9" rx="2" />
    <path d="M8 11V8a4 4 0 0 1 8 0v3" />
  </Base>
)

// 그래프 (상태/통계)
export const IconActivity = (p: IconProps) => (
  <Base {...p}>
    <path d="M22 12h-4l-3 8L9 4l-3 8H2" />
  </Base>
)

// 반짝이 (AI)
export const IconSparkles = (p: IconProps) => (
  <Base {...p}>
    <path d="M12 3l1.8 4.9L18.7 9.7l-4.9 1.8L12 16.4l-1.8-4.9L5.3 9.7l4.9-1.8z" />
    <path d="M19 14l.7 1.8 1.8.7-1.8.7L19 19l-.7-1.8-1.8-.7 1.8-.7z" />
  </Base>
)

// 이미지
export const IconImage = (p: IconProps) => (
  <Base {...p}>
    <rect x="3" y="4" width="18" height="16" rx="2" />
    <circle cx="8.5" cy="9.5" r="1.5" />
    <path d="M21 16l-5-5L5 21" />
  </Base>
)

// 새로고침
export const IconRefresh = (p: IconProps) => (
  <Base {...p}>
    <path d="M21 4v6h-6" />
    <path d="M3 20v-6h6" />
    <path d="M3.5 9a8 8 0 0 1 13.4-3L21 10M3 14l4.1 4A8 8 0 0 0 20.5 15" />
  </Base>
)

// 체크 (확인/성공)
export const IconCheck = (p: IconProps) => (
  <Base {...p}>
    <path d="M20 6L9 17l-5-5" />
  </Base>
)

// 오른쪽 화살표 (이동)
export const IconArrowRight = (p: IconProps) => (
  <Base {...p}>
    <path d="M5 12h14" />
    <path d="M13 5l7 7-7 7" />
  </Base>
)

// 왼쪽 화살표 (뒤로)
export const IconArrowLeft = (p: IconProps) => (
  <Base {...p}>
    <path d="M19 12H5" />
    <path d="M11 5l-7 7 7 7" />
  </Base>
)
