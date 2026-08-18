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
  // 화면 제목(h1).
  //
  // 전에는 `gradientText`였다 — 블루→퍼플→핑크 그라데이션 글자가 6초 주기로 좌우로
  // 흘렀다. 그게 '사람이 만든 것 같지 않다'는 인상의 가장 큰 몫이었다. 한국 개발
  // 블로그에서 제목 글자가 움직이는 걸 거의 못 본다. 색이 아니라 크기와 굵기로
  // 제목임을 알리는 쪽이 읽기에도 낫다.
  //
  // 옆에 있던 `glow`(히어로 뒤 흐릿한 색 번짐)도 같이 없앴다. 그건 랜딩 페이지
  // 템플릿의 표식에 가깝고, 글 목록 화면이 굳이 흉내 낼 이유가 없다.
  pageTitle: 'text-ink',
}
