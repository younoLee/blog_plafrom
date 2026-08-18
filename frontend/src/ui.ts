// 앱 전체에서 공유하는 스타일 토큰.
// 색(accent/canvas/ink)과 모서리(rounded-card/field/btn)는 index.css의 @theme이
// 정의하는 CSS 변수를 탄다. 그래서 여기 문자열을 안 고치고 변수만 바꿔도 외형이 바뀐다 —
// 스킨 기능이 붙을 자리다. 기본값은 지금까지 쓰던 애플풍(알약 버튼·애플 블루)이다.
export const ui = {
  // 기본 버튼: 애플 블루 알약(pill). px는 모바일에서 좁게(px-3.5), sm↑에서 넉넉히(px-5)
  // — 헤더에 버튼이 많아 좁은 화면에서 넘치는 걸 막기 위함
  btnPrimary:
    'inline-flex items-center justify-center gap-1.5 rounded-btn bg-accent px-3.5 py-2 text-sm font-medium text-white transition hover:bg-accent-hi active:scale-[0.98] sm:px-5 sm:py-2.5',
  // 보조 버튼: 연한 회색 알약
  btnGhost:
    'inline-flex items-center justify-center gap-1.5 rounded-btn bg-black/[0.06] px-3.5 py-2 text-sm font-medium text-gray-800 transition hover:bg-black/[0.1] active:scale-[0.98] sm:px-5 sm:py-2.5 dark:bg-white/10 dark:text-gray-100 dark:hover:bg-white/20',
  input:
    'w-full rounded-field border border-black/10 bg-white px-4 py-3 text-sm transition placeholder:text-gray-400 focus:border-accent focus:outline-none focus:ring-4 focus:ring-accent/15 dark:border-white/15 dark:bg-white/5 dark:text-gray-100 dark:placeholder:text-gray-500',
  // 드롭다운: input과 같은 톤. 기본 화살표를 숨기고(appearance-none) 오른쪽에 직접 그린 꺾쇠를 얹음.
  // 감싸는 요소를 relative로 두고 그 안에 select(이 클래스)+IconChevronDown(우측 absolute)을 배치.
  // 옵션 팝업/스크롤바 등 네이티브 UI 색은 index.css의 color-scheme가 테마에 맞춰 처리한다.
  select:
    'w-full cursor-pointer appearance-none rounded-field border border-black/10 bg-white py-3 pl-4 pr-10 text-sm transition hover:border-black/20 focus:border-accent focus:outline-none focus:ring-4 focus:ring-accent/15 dark:border-white/15 dark:bg-[#1c1c1e] dark:text-gray-100 dark:hover:border-white/25',
  // 카드: 더 둥글게, 테두리 옅게, 그림자는 hover 때만 부드럽게 떠오름
  card:
    'rounded-card border border-black/[0.07] bg-white p-6 shadow-[0_1px_3px_rgba(0,0,0,0.04)] transition hover:shadow-[0_8px_30px_rgba(0,0,0,0.08)] dark:border-white/10 dark:bg-white/[0.06]',
  // 그라데이션 글자(블루→퍼플→핑크, 천천히 흐름) — 강조하고 싶은 단어/제목에
  gradientText:
    'animate-gradient bg-gradient-to-r from-accent via-accent-2 to-accent-3 bg-clip-text text-transparent',
  // 히어로 뒤 은은한 색 번짐 — 부모를 relative로 두고 그 안에 배치
  glow:
    'pointer-events-none absolute inset-x-0 -top-16 -z-10 mx-auto h-56 max-w-xl rounded-full bg-gradient-to-tr from-accent/20 via-accent-2/15 to-accent-3/15 blur-3xl',
}
